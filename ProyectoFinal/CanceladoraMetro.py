"""
Aplicación Flask para Canceladora de Metro con Botón simulador
Raspberry Pi 5
Con sistema de autenticación de usuarios y almacenamiento en InfluxDB
Configuración desde archivo .env

ARQUITECTURA MULTIPROCESO:
- Proceso 1 (Principal): Servidor Flask + Hilo de control de puertas
- Proceso 2: Monitor de sensores + Hilo de detección de paso
- Comunicación: Queue para eventos entre procesos
- Variables compartidas: Manager.dict() para estado global
"""

from flask import Flask, render_template, jsonify, request, session, redirect, url_for
import time
from gpiozero import LED, AngularServo, Button
from RPLCD.i2c import CharLCD
import threading
import json
from datetime import datetime, timedelta
from functools import wraps
from influxdb_handler import InfluxDBHandler
import hashlib
import logging
from multiprocessing import Process, Queue, Manager, Value
import ctypes

# Importar configuración
from config import config

# -------------------------
# CONFIGURACIÓN DE LOGGING
# -------------------------
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# -------------------------
# CONFIGURACIÓN DE FLASK
# -------------------------
app = Flask(__name__)
app.secret_key = config.FLASK_SECRET_KEY
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=config.SESSION_TIMEOUT)

# -------------------------
# VARIABLES GLOBALES COMPARTIDAS ENTRE PROCESOS
# -------------------------
manager = None
estado_sistema = None
cola_eventos = None
cola_comandos = None
sistema_activo = None

# -------------------------
# INICIALIZAR INFLUXDB
# -------------------------
db_handler = None
if config.ENABLE_INFLUXDB:
    try:
        db_handler = InfluxDBHandler(**config.get_influxdb_config())
        logger.info("✓ InfluxDB inicializado correctamente")
    except Exception as e:
        logger.error(f"✗ Error inicializando InfluxDB: {e}")
        logger.warning("⚠ El sistema continuará sin InfluxDB")
else:
    logger.info("ℹ InfluxDB deshabilitado en configuración")

# -------------------------
# BASE DE DATOS DE USUARIOS
# -------------------------
def hash_password(password):
    """Hashea una contraseña usando SHA256"""
    return hashlib.sha256(password.encode()).hexdigest()

# Cargar usuarios desde configuración
USUARIOS = {
    config.DEFAULT_ADMIN_USER: {
        "password": hash_password(config.DEFAULT_ADMIN_PASS),
        "nombre": config.DEFAULT_ADMIN_NAME,
        "rol": "admin"
    },
    config.DEFAULT_USER1_USER: {
        "password": hash_password(config.DEFAULT_USER1_PASS),
        "nombre": config.DEFAULT_USER1_NAME,
        "rol": "usuario"
    },
    config.DEFAULT_USER2_USER: {
        "password": hash_password(config.DEFAULT_USER2_PASS),
        "nombre": config.DEFAULT_USER2_NAME,
        "rol": "usuario"
    }
}

# Contador de intentos fallidos de login (para seguridad)
login_attempts = {}

# -------------------------
# HARDWARE GLOBAL (usado por ambos procesos)
# -------------------------
led_rojo = None
led_verde = None
boton = None
laserA = None
laserB = None
s1 = None
s2 = None
lcd = None

def inicializar_hardware():
    """Inicializa todo el hardware GPIO y LCD"""
    global led_rojo, led_verde, boton, laserA, laserB, s1, s2, lcd
    
    try:
        led_rojo = LED(config.PIN_LED_ROJO)
        led_verde = LED(config.PIN_LED_VERDE)
        boton = Button(config.PIN_BOTON, pull_up=None, active_state=True)
        laserA = Button(config.PIN_LASER_A, pull_up=True)
        laserB = Button(config.PIN_LASER_B, pull_up=True, bounce_time=0.3)

        # SERVOS CON POSICIÓN INICIAL PARA EVITAR MOVIMIENTO AL ARRANCAR
        s1 = AngularServo(config.PIN_SERVO_1, min_angle=0, max_angle=180,
                          min_pulse_width=0.0005, max_pulse_width=0.0024,
                          initial_angle=0)
        s2 = AngularServo(config.PIN_SERVO_2, min_angle=0, max_angle=180,
                          min_pulse_width=0.0005, max_pulse_width=0.0024,
                          initial_angle=180)

        # Pequeña pausa y confirmación de posición cerrada
        time.sleep(0.5)
        s1.angle = 0
        s2.angle = 180

        logger.info("✓ Hardware GPIO inicializado correctamente")
    except Exception as e:
        logger.error(f"✗ Error inicializando GPIO: {e}")
        if not config.SIMULATE_HARDWARE:
            raise

    # LCD I2C
    try:
        lcd = CharLCD(
            i2c_expander='PCF8574',
            address=config.LCD_ADDRESS,
            port=config.LCD_PORT,
            cols=config.LCD_COLS,
            rows=config.LCD_ROWS,
            dotsize=8
        )
        lcd.clear()
        lcd.write_string('Sistema Metro')
        lcd.cursor_pos = (1, 0)
        lcd.write_string('Iniciando...')
        time.sleep(1)
        logger.info("✓ LCD inicializada correctamente")
    except Exception as e:
        lcd = None
        logger.warning(f"⚠ LCD NO DETECTADA: {e}")

# -------------------------
# DECORADORES DE AUTENTICACIÓN
# -------------------------
def login_required(f):
    """Decorador para rutas que requieren autenticación"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'username' not in session:
            return jsonify({"error": "No autenticado", "redirect": "/login"}), 401
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    """Decorador para rutas que requieren rol de administrador"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'username' not in session:
            return jsonify({"error": "No autenticado"}), 401
        username = session['username']
        if USUARIOS.get(username, {}).get('rol') != 'admin':
            return jsonify({"error": "Requiere privilegios de administrador"}), 403
        return f(*args, **kwargs)
    return decorated_function

# -------------------------
# FUNCIONES DE CONTROL
# -------------------------
def mostrar_lcd(linea1, linea2=""):
    """Muestra texto en el LCD"""
    logger.debug(f"LCD: {linea1} | {linea2}")
    if lcd:
        try:
            lcd.clear()
            lcd.write_string(linea1[:config.LCD_COLS])
            if linea2:
                lcd.cursor_pos = (1, 0)
                lcd.write_string(linea2[:config.LCD_COLS])
        except Exception as e:
            logger.error(f"Error LCD: {e}")

def abrir_puertas():
    """Abre las puertas del torniquete"""
    led_rojo.off()
    led_verde.on()

    usuario = estado_sistema["usuario_actual"] or "Usuario"
    mostrar_lcd("ACCESO OK", f"{usuario[:config.LCD_COLS]}")

    estado_sistema["estado_puerta"] = "ABIERTA"

    s1.angle = 90
    s2.angle = 90

    # Registrar estado de puerta en InfluxDB
    if db_handler:
        db_handler.write_door_status(
            door_status="ABIERTA",
            detecting_crossing=False,
            lasers_status={'laser_a': not laserA.is_pressed, 'laser_b': not laserB.is_pressed}
        )

    logger.info(f"✓ Puertas abiertas para {usuario}")

def cerrar_puertas():
    """Cierra las puertas del torniquete"""
    mostrar_lcd("Cerrando...", "")
    time.sleep(1)

    led_verde.off()
    led_rojo.on()

    s1.angle = 0
    s2.angle = 180

    estado_sistema["estado_puerta"] = "CERRADA"
    estado_sistema["boton_habilitado"] = False
    estado_sistema["usuario_actual"] = None

    # Registrar estado de puerta en InfluxDB
    if db_handler:
        db_handler.write_door_status(
            door_status="CERRADA",
            detecting_crossing=False,
            lasers_status={'laser_a': not laserA.is_pressed, 'laser_b': not laserB.is_pressed}
        )

    time.sleep(1)
    mostrar_lcd("Login en Web", "Para acceder")
    logger.info("✓ Puertas cerradas")

# -------------------------
# FUNCIONES DE SEGURIDAD
# -------------------------
def check_login_attempts(username):
    """Verifica si el usuario está bloqueado por intentos fallidos"""
    if username not in login_attempts:
        return True

    attempts, last_attempt = login_attempts[username]

    # Si pasó el tiempo de bloqueo, resetear
    if datetime.now() - last_attempt > timedelta(minutes=config.LOCKOUT_DURATION):
        del login_attempts[username]
        return True

    # Si excedió los intentos
    if attempts >= config.MAX_LOGIN_ATTEMPTS:
        return False

    return True

def register_failed_attempt(username):
    """Registra un intento fallido de login"""
    if username not in login_attempts:
        login_attempts[username] = [1, datetime.now()]
    else:
        attempts, _ = login_attempts[username]
        login_attempts[username] = [attempts + 1, datetime.now()]

# =========================================================================
# PROCESO 1: SERVIDOR FLASK (PRINCIPAL)
# =========================================================================

# -------------------------
# HILO 1: PROCESADOR DE EVENTOS
# -------------------------
def hilo_procesador_eventos():
    """
    HILO 1 del Proceso Principal
    Procesa eventos provenientes del Proceso 2 (monitor de sensores)
    """
    logger.info("🧵 HILO 1 (Proceso Principal): Procesador de eventos iniciado")
    
    while sistema_activo.value == 1:
        try:
            if not cola_eventos.empty():
                evento = cola_eventos.get(timeout=0.5)
                
                if evento['tipo'] == 'boton_presionado':
                    logger.info(f"📩 Evento recibido: Botón presionado")
                    # Procesar acceso
                    procesar_acceso_desde_evento()
                
                elif evento['tipo'] == 'laser_bloqueado':
                    laser_id = evento['laser']
                    logger.debug(f"📩 Evento: Láser {laser_id} bloqueado")
                    estado_sistema[f"laser_{laser_id}_bloqueado"] = True
                
                elif evento['tipo'] == 'laser_libre':
                    laser_id = evento['laser']
                    logger.debug(f"📩 Evento: Láser {laser_id} libre")
                    estado_sistema[f"laser_{laser_id}_bloqueado"] = False
                    
        except Exception as e:
            if str(e) != "":  # Ignorar timeouts vacíos
                logger.error(f"Error en procesador de eventos: {e}")
        
        time.sleep(0.1)
    
    logger.info("🧵 HILO 1: Procesador de eventos detenido")

# -------------------------
# HILO 2: CONTROLADOR DE PUERTAS
# -------------------------
def hilo_control_puertas():
    """
    HILO 2 del Proceso Principal
    Escucha comandos de la cola y ejecuta acciones sobre las puertas
    """
    logger.info("🧵 HILO 2 (Proceso Principal): Controlador de puertas iniciado")
    
    while sistema_activo.value == 1:
        try:
            if not cola_comandos.empty():
                comando = cola_comandos.get(timeout=0.5)
                
                if comando['accion'] == 'abrir_puertas':
                    logger.info("🚪 Comando: Abrir puertas")
                    abrir_puertas()
                
                elif comando['accion'] == 'cerrar_puertas':
                    logger.info("🚪 Comando: Cerrar puertas")
                    cerrar_puertas()
                
                elif comando['accion'] == 'inicializar':
                    logger.info("🚪 Comando: Inicializar sistema")
                    cerrar_puertas()
                    
        except Exception as e:
            if str(e) != "":
                logger.error(f"Error en control de puertas: {e}")
        
        time.sleep(0.1)
    
    logger.info("🧵 HILO 2: Controlador de puertas detenido")

def procesar_acceso_desde_evento():
    """Procesa un acceso cuando llega un evento del botón"""
    # Verificar si el botón está habilitado (usuario logueado)
    if not estado_sistema["boton_habilitado"]:
        mostrar_lcd("ACCESO DENEGADO", "Login primero")
        logger.warning("✗ Intento de acceso sin login")
        time.sleep(2)
        mostrar_lcd("Login en Web", "Para acceder")
        return

    timestamp = datetime.now().strftime("%H:%M:%S")
    usuario = estado_sistema["usuario_actual"]

    estado_sistema["timestamp"] = timestamp
    estado_sistema["total_accesos"] = estado_sistema["total_accesos"] + 1
    estado_sistema["personas_dentro"] = estado_sistema["personas_dentro"] + 1
    estado_sistema["ultimo_acceso"] = {
        "usuario": usuario,
        "timestamp": timestamp
    }

    # Registrar en InfluxDB
    if db_handler:
        db_handler.write_access_event(
            card_id=estado_sistema["total_accesos"],
            user_name=usuario,
            access_granted=True,
            door_id="canceladora_1"
        )

    logger.info(f"✓ Acceso #{estado_sistema['total_accesos']} - Usuario: {usuario}")

    # Abrir puertas
    cola_comandos.put({'accion': 'abrir_puertas'})
    
    # Enviar comando al Proceso 2 para esperar paso
    cola_comandos.put({'accion': 'esperar_paso'})

# -------------------------
# RUTAS DE AUTENTICACIÓN
# -------------------------
@app.route('/')
def index():
    """Página principal - redirige según autenticación"""
    if 'username' not in session:
        return redirect(url_for('login_page'))
    return render_template('dashboard.html')

@app.route('/login')
def login_page():
    """Página de login"""
    if 'username' in session:
        return redirect(url_for('index'))
    return render_template('login.html')

@app.route('/api/login', methods=['POST'])
def login():
    """API: Inicia sesión"""
    data = request.json
    username = data.get('username')
    password = data.get('password')

    if not username or not password:
        return jsonify({"error": "Usuario y contraseña requeridos"}), 400

    # Verificar si está bloqueado
    if not check_login_attempts(username):
        return jsonify({
            "error": f"Cuenta bloqueada por {config.LOCKOUT_DURATION} minutos debido a múltiples intentos fallidos"
        }), 403

    # Verificar credenciales
    usuario = USUARIOS.get(username)
    if usuario and usuario['password'] == hash_password(password):
        # Login exitoso - limpiar intentos fallidos
        if username in login_attempts:
            del login_attempts[username]

        session['username'] = username
        session['nombre'] = usuario['nombre']
        session['rol'] = usuario['rol']
        session.permanent = True

        # Habilitar el botón para este usuario
        estado_sistema["boton_habilitado"] = True
        estado_sistema["usuario_actual"] = usuario['nombre']

        mostrar_lcd("Login exitoso", usuario['nombre'][:config.LCD_COLS])
        time.sleep(1)
        mostrar_lcd("Pulsa boton", "Para acceder")

        # Registrar login en InfluxDB
        if db_handler:
            db_handler.write_login_event(
                username=username,
                user_name=usuario['nombre'],
                role=usuario['rol'],
                success=True
            )

        logger.info(f"✓ Login exitoso: {username} ({usuario['nombre']})")

        return jsonify({
            "exito": True,
            "mensaje": "Login exitoso",
            "usuario": {
                "username": username,
                "nombre": usuario['nombre'],
                "rol": usuario['rol']
            }
        })

    # Login fallido
    register_failed_attempt(username)

    # Registrar intento fallido en InfluxDB
    if db_handler:
        db_handler.write_login_event(
            username=username,
            user_name="Unknown",
            role="none",
            success=False
        )

    logger.warning(f"✗ Login fallido: {username}")
    return jsonify({"error": "Credenciales incorrectas"}), 401

@app.route('/api/logout', methods=['POST'])
@login_required
def logout():
    """API: Cierra sesión"""
    username = session.get('username')
    session.clear()

    # Deshabilitar el botón
    estado_sistema["boton_habilitado"] = False
    estado_sistema["usuario_actual"] = None

    mostrar_lcd("Sesion cerrada", "Hasta pronto")
    time.sleep(1)
    mostrar_lcd("Login en Web", "Para acceder")

    logger.info(f"✓ Usuario {username} cerró sesión")

    return jsonify({"exito": True, "mensaje": "Sesión cerrada"})

@app.route('/api/session')
def check_session():
    """API: Verifica la sesión actual"""
    if 'username' in session:
        return jsonify({
            "autenticado": True,
            "usuario": {
                "username": session['username'],
                "nombre": session['nombre'],
                "rol": session['rol']
            }
        })
    return jsonify({"autenticado": False})

# -------------------------
# RUTAS DEL SISTEMA
# -------------------------
@app.route('/estado')
@login_required
def obtener_estado():
    """API: Devuelve el estado actual del sistema"""
    estado_completo = dict(estado_sistema)
    estado_completo.update({
        "laser_a_activo": not laserA.is_pressed,
        "laser_b_activo": not laserB.is_pressed,
        "led_verde": led_verde.is_lit,
        "led_rojo": led_rojo.is_lit,
        "usuario_sesion": session.get('nombre')
    })
    return jsonify(estado_completo)

@app.route('/usuarios')
@admin_required
def listar_usuarios():
    """API: Lista todos los usuarios (solo admin)"""
    usuarios_list = [
        {
            "username": username,
            "nombre": data['nombre'],
            "rol": data['rol']
        }
        for username, data in USUARIOS.items()
    ]
    return jsonify(usuarios_list)

@app.route('/reiniciar_estadisticas', methods=['POST'])
@admin_required
def reiniciar_estadisticas():
    """API: Reinicia los contadores de estadísticas (solo admin)"""
    estado_sistema["total_accesos"] = 0
    estado_sistema["personas_dentro"] = 0
    logger.info("✓ Estadísticas reiniciadas por administrador")
    return jsonify({"mensaje": "Estadísticas reiniciadas", "exito": True})

@app.route('/api/accesos_recientes')
@login_required
def obtener_accesos_recientes():
    """API: Obtiene los accesos recientes desde InfluxDB"""
    if not db_handler:
        return jsonify({"error": "Base de datos no disponible"}), 500

    minutos = request.args.get('minutos', 60, type=int)
    accesos = db_handler.get_recent_access(minutes=minutos)

    return jsonify({
        "total": len(accesos),
        "accesos": [
            {
                "timestamp": str(acc['time']),
                "usuario": acc['user'],
                "puerta": acc['door'],
                "autorizado": acc['access_granted'],
                "usuario_id": acc['card_id']
            } for acc in accesos
        ]
    })

@app.route('/api/estadisticas')
@login_required
def obtener_estadisticas():
    """API: Obtiene estadísticas desde InfluxDB"""
    if not db_handler:
        return jsonify({"error": "Base de datos no disponible"}), 500

    horas = request.args.get('horas', 24, type=int)
    stats = db_handler.get_access_statistics(hours=horas)

    return jsonify({
        "total_accesos": stats.get('total', 0),
        "accesos_permitidos": stats.get('granted', 0),
        "accesos_denegados": stats.get('denied', 0),
        "porcentaje_autorizacion": round(stats.get('grant_percentage', 0), 2)
    })

@app.route('/simular_acceso', methods=['POST'])
@login_required
def simular_acceso_manual():
    """API: Simula un acceso desde la web"""
    if not estado_sistema["detectando_paso"] and estado_sistema["boton_habilitado"]:
        # Enviar evento de botón presionado a la cola
        cola_eventos.put({'tipo': 'boton_presionado', 'origen': 'web'})
        return jsonify({"mensaje": "Acceso simulado", "exito": True})
    elif not estado_sistema["boton_habilitado"]:
        return jsonify({"mensaje": "Debes hacer login primero", "exito": False}), 403
    return jsonify({"mensaje": "Sistema ocupado", "exito": False}), 409

# =========================================================================
# PROCESO 2: MONITOR DE SENSORES
# =========================================================================

def proceso_monitor_sensores(cola_eventos_p2, cola_comandos_p2, estado_sistema_p2, sistema_activo_p2):
    """
    PROCESO 2: Monitor de sensores y actuadores
    Contiene 2 hilos:
    - Hilo 3: Monitor de botón físico
    - Hilo 4: Monitor de láseres
    """
    logger.info("🔧 PROCESO 2: Monitor de sensores iniciado (PID: %d)", os.getpid())
    
    # Reinicializar hardware en este proceso
    inicializar_hardware()
    
    # -------------------------
    # HILO 3: MONITOR DE BOTÓN
    # -------------------------
    def hilo_monitor_boton():
        """
        HILO 3 del Proceso 2
        Monitorea continuamente el botón físico
        """
        logger.info("🧵 HILO 3 (Proceso 2): Monitor de botón iniciado")
        
        # Inicializar puertas cerradas
        cola_comandos_p2.put({'accion': 'inicializar'})
        
        while sistema_activo_p2.value == 1:
            try:
                # Esperar a que se presione el botón
                if boton.wait_for_press(timeout=0.5):
                    logger.info("🔘 Botón físico presionado")
                    # Enviar evento al Proceso 1
                    cola_eventos_p2.put({
                        'tipo': 'boton_presionado',
                        'origen': 'fisico',
                        'timestamp': datetime.now().isoformat()
                    })
                    time.sleep(0.5)  # Debounce
            except Exception as e:
                logger.error(f"Error en monitor de botón: {e}")
                time.sleep(1)
        
        logger.info("🧵 HILO 3: Monitor de botón detenido")
    
    # -------------------------
    # HILO 4: MONITOR DE LÁSERES
    # -------------------------
    def hilo_monitor_laseres():
        """
        HILO 4 del Proceso 2
        Monitorea el estado de los láseres A y B
        """
        logger.info("🧵 HILO 4 (Proceso 2): Monitor de láseres iniciado")
        
        estado_laser_a_anterior = False
        estado_laser_b_anterior = False
        
        while sistema_activo_p2.value == 1:
            try:
                # Monitorear Láser A
                laser_a_bloqueado = laserA.is_pressed
                if laser_a_bloqueado != estado_laser_a_anterior:
                    tipo_evento = 'laser_bloqueado' if laser_a_bloqueado else 'laser_libre'
                    cola_eventos_p2.put({
                        'tipo': tipo_evento,
                        'laser': 'A',
                        'timestamp': datetime.now().isoformat()
                    })
                    estado_laser_a_anterior = laser_a_bloqueado
                
                # Monitorear Láser B
                laser_b_bloqueado = laserB.is_pressed
                if laser_b_bloqueado != estado_laser_b_anterior:
                    tipo_evento = 'laser_bloqueado' if laser_b_bloqueado else 'laser_libre'
                    cola_eventos_p2.put({
                        'tipo': tipo_evento,
                        'laser': 'B',
                        'timestamp': datetime.now().isoformat()
                    })
                    estado_laser_b_anterior = laser_b_bloqueado
                
                # Procesar comandos
                if not cola_comandos_p2.empty():
                    comando = cola_comandos_p2.get_nowait()
                    if comando['accion'] == 'esperar_paso':
                        esperar_persona_paso()
                
                time.sleep(0.1)
                
            except Exception as e:
                logger.error(f"Error en monitor de láseres: {e}")
                time.sleep(1)
        
        logger.info("🧵 HILO 4: Monitor de láseres detenido")
    
    def esperar_persona_paso():
        """Espera a que la persona cruce completamente"""
        estado_sistema_p2["detectando_paso"] = True
        
        logger.info("👤 Esperando detección de paso...")
        
        timeout = time.time() + 15
        detectado = False
        
        # Esperar a que se bloquee el láser B
        while time.time() < timeout:
            if laserB.is_pressed:
                detectado = True
                logger.info("✓ Persona detectada cruzando")
                break
            time.sleep(0.1)
        
        if detectado:
            # Esperar a que se libere el láser B
            logger.info("Esperando a que termine de cruzar...")
            while laserB.is_pressed and time.time() < timeout:
                time.sleep(0.1)
            
            logger.info("✓ Persona cruzó completamente")
            time.sleep(1)
        else:
            logger.warning("⚠ Timeout: No se detectó paso en 15 segundos")
        
        estado_sistema_p2["detectando_paso"] = False
        
        # Enviar comando para cerrar puertas
        cola_comandos_p2.put({'accion': 'cerrar_puertas'})
    
    # Iniciar hilos del Proceso 2
    hilo_boton = threading.Thread(target=hilo_monitor_boton, daemon=True)
    hilo_laseres = threading.Thread(target=hilo_monitor_laseres, daemon=True)
    
    hilo_boton.start()
    hilo_laseres.start()
    
    # Mantener el proceso vivo
    hilo_boton.join()
    hilo_laseres.join()
    
    logger.info("🔧 PROCESO 2: Monitor de sensores detenido")

# =========================================================================
# FUNCIÓN PRINCIPAL
# =========================================================================

def iniciar_sistema():
    """Función principal que inicia ambos procesos"""
    global manager, estado_sistema, cola_eventos, cola_comandos, sistema_activo
    
    # Inicializar hardware en proceso principal
    inicializar_hardware()
    
    # Crear manager para compartir datos entre procesos
    manager = Manager()
    
    # Estado compartido entre procesos
    estado_sistema = manager.dict({
        "estado_puerta": "CERRADA",
        "timestamp": None,
        "total_accesos": 0,
        "personas_dentro": 0,
        "sistema_activo": True,
        "detectando_paso": False,
        "boton_habilitado": False,
        "usuario_actual": None,
        "ultimo_acceso": None,
        "laser_a_bloqueado": False,
        "laser_b_bloqueado": False
    })
    
    # Colas para comunicación entre procesos
    cola_eventos = Queue()  # Proceso 2 → Proceso 1 (eventos de sensores)
    cola_comandos = Queue()  # Proceso 1 → Proceso 2 (comandos de control)
    
    # Variable para controlar la ejecución
    sistema_activo = Value(ctypes.c_int, 1)
    
    # Mostrar configuración
    config.print_config()
    
    print("\n" + "="*60)
    print("🚇 SISTEMA CANCELADORA DE METRO - ARQUITECTURA MULTIPROCESO")
    print("="*60)
    print(f"📱 Accede a la web desde: http://<IP_RASPBERRY>:{config.FLASK_PORT}")
    print(f"🔘 Botón configurado en GPIO {config.PIN_BOTON}")
    print(f"👥 Usuarios registrados: {len(USUARIOS)}")
    print("\n⚠️  CREDENCIALES POR DEFECTO:")
    print(f"   Admin: {config.DEFAULT_ADMIN_USER} / {config.DEFAULT_ADMIN_PASS}")
    print(f"   Usuario1: {config.DEFAULT_USER1_USER} / {config.DEFAULT_USER1_PASS}")
    print(f"   Usuario2: {config.DEFAULT_USER2_USER} / {config.DEFAULT_USER2_PASS}")
    print("\n📊 ARQUITECTURA:")
    print("   • PROCESO 1 (Principal): Flask + 2 hilos")
    print("     - Hilo 1: Procesador de eventos")
    print("     - Hilo 2: Controlador de puertas")
    print("   • PROCESO 2: Monitor sensores + 2 hilos")
    print("     - Hilo 3: Monitor de botón físico")
    print("     - Hilo 4: Monitor de láseres")
    print("   • Comunicación: 2 colas (Queue)")
    print("     - cola_eventos: Proceso 2 → Proceso 1")
    print("     - cola_comandos: Proceso 1 → Proceso 2")
    print("="*60 + "\n")
    
    # Iniciar PROCESO 2 (Monitor de sensores)
    proceso_sensores = Process(
        target=proceso_monitor_sensores,
        args=(cola_eventos, cola_comandos, estado_sistema, sistema_activo),
        name="MonitorSensores"
    )
    proceso_sensores.start()
    logger.info(f"✓ Proceso 2 iniciado (PID: {proceso_sensores.pid})")
    
    # Iniciar hilos del PROCESO 1 (Flask)
    hilo_eventos = threading.Thread(target=hilo_procesador_eventos, daemon=True)
    hilo_puertas = threading.Thread(target=hilo_control_puertas, daemon=True)
    
    hilo_eventos.start()
    hilo_puertas.start()
    logger.info("✓ Hilos del Proceso 1 iniciados")
    
    try:
        # Configuración SSL si está habilitada
        ssl_context = None
        if config.ENABLE_HTTPS:
            ssl_context = (config.SSL_CERT_PATH, config.SSL_KEY_PATH)
            logger.info("✓ HTTPS habilitado")
        
        # Iniciar Flask (PROCESO 1 - Principal)
        app.run(
            host=config.FLASK_HOST,
            port=config.FLASK_PORT,
            debug=False,  # No usar debug en multiproceso
            ssl_context=ssl_context,
            use_reloader=False  # Importante: deshabilitar reloader
        )
    except KeyboardInterrupt:
        print("\n\n🛑 Cerrando sistema...")
    finally:
        # Detener todos los procesos e hilos
        sistema_activo.value = 0
        
        # Esperar a que termine el Proceso 2
        proceso_sensores.join(timeout=5)
        if proceso_sensores.is_alive():
            logger.warning("⚠ Terminando Proceso 2 forzadamente...")
            proceso_sensores.terminate()
            proceso_sensores.join()
        
        # Cerrar puertas y apagar LEDs
        if led_verde:
            led_verde.off()
        if led_rojo:
            led_rojo.off()
        if s1 and s2:
            s1.angle = 0
            s2.angle = 180
        
        if lcd:
            lcd.clear()
        
        if db_handler:
            db_handler.close()
        
        logger.info("✓ Sistema cerrado correctamente")

# -------------------------
# INICIO DE LA APLICACIÓN
# -------------------------
if __name__ == '__main__':
    import os
    iniciar_sistema()
