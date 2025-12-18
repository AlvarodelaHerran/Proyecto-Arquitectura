"""
Aplicación Flask para Canceladora de Metro
ARQUITECTURA MULTIPROCESO CORREGIDA:
- Proceso 1 (Principal): Servidor Flask + Hilo procesador de eventos
- Proceso 2: Control de hardware (GPIO/LCD) + Hilo monitor de botón
"""

from flask import Flask, render_template, jsonify, request, session, redirect, url_for
import time
from datetime import datetime, timedelta
from functools import wraps
import hashlib
import logging
from multiprocessing import Process, Queue, Manager, Value
import ctypes
import threading

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
# VARIABLES GLOBALES
# -------------------------
manager = None
estado_sistema = None
cola_eventos = None
cola_comandos = None
sistema_activo = None
db_handler = None

# -------------------------
# BASE DE DATOS DE USUARIOS
# -------------------------
def hash_password(password):
    """Hashea una contraseña usando SHA256"""
    return hashlib.sha256(password.encode()).hexdigest()

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

login_attempts = {}

# -------------------------
# DECORADORES
# -------------------------
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'username' not in session:
            return jsonify({"error": "No autenticado", "redirect": "/login"}), 401
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
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
# FUNCIONES DE SEGURIDAD
# -------------------------
def check_login_attempts(username):
    if username not in login_attempts:
        return True
    attempts, last_attempt = login_attempts[username]
    if datetime.now() - last_attempt > timedelta(minutes=config.LOCKOUT_DURATION):
        del login_attempts[username]
        return True
    if attempts >= config.MAX_LOGIN_ATTEMPTS:
        return False
    return True

def register_failed_attempt(username):
    if username not in login_attempts:
        login_attempts[username] = [1, datetime.now()]
    else:
        attempts, _ = login_attempts[username]
        login_attempts[username] = [attempts + 1, datetime.now()]

# =========================================================================
# PROCESO 1: SERVIDOR FLASK (PRINCIPAL)
# =========================================================================

def hilo_procesador_eventos():
    """
    HILO 1: Procesa eventos del Proceso 2 y envía comandos
    """
    logger.info("🧵 HILO 1 (Flask): Procesador de eventos iniciado")
    
    while sistema_activo.value == 1:
        try:
            if not cola_eventos.empty():
                evento = cola_eventos.get(timeout=0.5)
                
                if evento['tipo'] == 'boton_presionado':
                    logger.info(f"📩 Evento: Botón presionado desde {evento.get('origen', 'desconocido')}")
                    
                    # Verificar si está habilitado
                    if not estado_sistema["boton_habilitado"]:
                        logger.warning("✗ Botón presionado pero usuario no logueado")
                        cola_comandos.put({
                            'accion': 'mostrar_lcd',
                            'linea1': 'ACCESO DENEGADO',
                            'linea2': 'Login primero'
                        })
                        time.sleep(2)
                        cola_comandos.put({
                            'accion': 'mostrar_lcd',
                            'linea1': 'Login en Web',
                            'linea2': 'Para acceder'
                        })
                    else:
                        # Procesar acceso
                        timestamp = datetime.now().strftime("%H:%M:%S")
                        usuario = estado_sistema["usuario_actual"]
                        
                        estado_sistema["timestamp"] = timestamp
                        estado_sistema["total_accesos"] = estado_sistema["total_accesos"] + 1
                        estado_sistema["personas_dentro"] = estado_sistema["personas_dentro"] + 1
                        estado_sistema["ultimo_acceso"] = {
                            "usuario": usuario,
                            "timestamp": timestamp
                        }
                        
                        logger.info(f"✓ Acceso #{estado_sistema['total_accesos']} - Usuario: {usuario}")
                        
                        # Registrar en InfluxDB
                        if db_handler:
                            try:
                                db_handler.write_access_event(
                                    card_id=estado_sistema["total_accesos"],
                                    user_name=usuario,
                                    access_granted=True,
                                    door_id="canceladora_1"
                                )
                            except:
                                pass
                        
                        # Enviar comando para abrir puertas
                        cola_comandos.put({
                            'accion': 'abrir_puertas',
                            'usuario': usuario
                        })
                
                elif evento['tipo'] == 'laser_bloqueado':
                    laser_id = evento['laser']
                    estado_sistema[f"laser_{laser_id.lower()}_bloqueado"] = True
                
                elif evento['tipo'] == 'laser_libre':
                    laser_id = evento['laser']
                    estado_sistema[f"laser_{laser_id.lower()}_bloqueado"] = False
                
                elif evento['tipo'] == 'paso_completado':
                    logger.info("✓ Paso completado, cerrando puertas")
                    cola_comandos.put({'accion': 'cerrar_puertas'})
                    
        except Exception as e:
            if "Empty" not in str(e):
                logger.error(f"Error en procesador: {e}")
        
        time.sleep(0.05)
    
    logger.info("🧵 HILO 1: Detenido")

# -------------------------
# RUTAS FLASK
# -------------------------
@app.route('/')
def index():
    if 'username' not in session:
        return redirect(url_for('login_page'))
    return render_template('dashboard.html')

@app.route('/login')
def login_page():
    if 'username' in session:
        return redirect(url_for('index'))
    return render_template('login.html')

@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    username = data.get('username')
    password = data.get('password')

    if not username or not password:
        return jsonify({"error": "Usuario y contraseña requeridos"}), 400

    if not check_login_attempts(username):
        return jsonify({
            "error": f"Cuenta bloqueada por {config.LOCKOUT_DURATION} minutos"
        }), 403

    usuario = USUARIOS.get(username)
    if usuario and usuario['password'] == hash_password(password):
        if username in login_attempts:
            del login_attempts[username]

        session['username'] = username
        session['nombre'] = usuario['nombre']
        session['rol'] = usuario['rol']
        session.permanent = True

        # Habilitar botón
        estado_sistema["boton_habilitado"] = True
        estado_sistema["usuario_actual"] = usuario['nombre']

        # Actualizar LCD
        cola_comandos.put({
            'accion': 'mostrar_lcd',
            'linea1': 'Login exitoso',
            'linea2': usuario['nombre'][:16]
        })
        time.sleep(1)
        cola_comandos.put({
            'accion': 'mostrar_lcd',
            'linea1': 'Pulsa boton',
            'linea2': 'Para acceder'
        })

        if db_handler:
            try:
                db_handler.write_login_event(
                    username=username,
                    user_name=usuario['nombre'],
                    role=usuario['rol'],
                    success=True
                )
            except:
                pass

        logger.info(f"✓ Login exitoso: {username}")

        return jsonify({
            "exito": True,
            "mensaje": "Login exitoso",
            "usuario": {
                "username": username,
                "nombre": usuario['nombre'],
                "rol": usuario['rol']
            }
        })

    register_failed_attempt(username)
    
    if db_handler:
        try:
            db_handler.write_login_event(
                username=username,
                user_name="Unknown",
                role="none",
                success=False
            )
        except:
            pass

    logger.warning(f"✗ Login fallido: {username}")
    return jsonify({"error": "Credenciales incorrectas"}), 401

@app.route('/api/logout', methods=['POST'])
@login_required
def logout():
    username = session.get('username')
    session.clear()

    estado_sistema["boton_habilitado"] = False
    estado_sistema["usuario_actual"] = None

    cola_comandos.put({
        'accion': 'mostrar_lcd',
        'linea1': 'Sesion cerrada',
        'linea2': 'Hasta pronto'
    })
    time.sleep(1)
    cola_comandos.put({
        'accion': 'mostrar_lcd',
        'linea1': 'Login en Web',
        'linea2': 'Para acceder'
    })

    logger.info(f"✓ Logout: {username}")
    return jsonify({"exito": True, "mensaje": "Sesión cerrada"})

@app.route('/api/session')
def check_session():
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

@app.route('/estado')
@login_required
def obtener_estado():
    estado_completo = dict(estado_sistema)
    estado_completo["usuario_sesion"] = session.get('nombre')
    return jsonify(estado_completo)

@app.route('/usuarios')
@admin_required
def listar_usuarios():
    usuarios_list = [
        {"username": u, "nombre": d['nombre'], "rol": d['rol']}
        for u, d in USUARIOS.items()
    ]
    return jsonify(usuarios_list)

@app.route('/reiniciar_estadisticas', methods=['POST'])
@admin_required
def reiniciar_estadisticas():
    estado_sistema["total_accesos"] = 0
    estado_sistema["personas_dentro"] = 0
    logger.info("✓ Estadísticas reiniciadas")
    return jsonify({"mensaje": "Estadísticas reiniciadas", "exito": True})

@app.route('/simular_acceso', methods=['POST'])
@login_required
def simular_acceso_manual():
    if estado_sistema["boton_habilitado"] and not estado_sistema["detectando_paso"]:
        cola_eventos.put({'tipo': 'boton_presionado', 'origen': 'web'})
        return jsonify({"mensaje": "Acceso simulado", "exito": True})
    elif not estado_sistema["boton_habilitado"]:
        return jsonify({"mensaje": "Debes hacer login primero", "exito": False}), 403
    return jsonify({"mensaje": "Sistema ocupado", "exito": False}), 409

@app.route('/api/accesos_recientes')
@login_required
def obtener_accesos_recientes():
    if not db_handler:
        return jsonify({"error": "Base de datos no disponible"}), 500
    
    minutos = request.args.get('minutos', 60, type=int)
    try:
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
    except:
        return jsonify({"error": "Error consultando BD"}), 500

@app.route('/api/estadisticas')
@login_required
def obtener_estadisticas():
    if not db_handler:
        return jsonify({"error": "Base de datos no disponible"}), 500
    
    horas = request.args.get('horas', 24, type=int)
    try:
        stats = db_handler.get_access_statistics(hours=horas)
        return jsonify({
            "total_accesos": stats.get('total', 0),
            "accesos_permitidos": stats.get('granted', 0),
            "accesos_denegados": stats.get('denied', 0),
            "porcentaje_autorizacion": round(stats.get('grant_percentage', 0), 2)
        })
    except:
        return jsonify({"error": "Error consultando estadísticas"}), 500

# =========================================================================
# PROCESO 2: CONTROL DE HARDWARE
# =========================================================================

def proceso_control_hardware(cola_eventos_p2, cola_comandos_p2, estado_sistema_p2, sistema_activo_p2):
    """
    PROCESO 2: Maneja TODO el hardware GPIO y LCD
    """
    import os
    from gpiozero import LED, AngularServo, Button
    from RPLCD.i2c import CharLCD
    
    logger.info(f"🔧 PROCESO 2: Control hardware iniciado (PID: {os.getpid()})")
    
    # Inicializar hardware EN ESTE PROCESO
    try:
        led_rojo = LED(config.PIN_LED_ROJO)
        led_verde = LED(config.PIN_LED_VERDE)
        boton = Button(config.PIN_BOTON, pull_up=None, active_state=True)
        laserA = Button(config.PIN_LASER_A, pull_up=True)
        laserB = Button(config.PIN_LASER_B, pull_up=True, bounce_time=0.3)

        s1 = AngularServo(config.PIN_SERVO_1, min_angle=0, max_angle=180,
                          min_pulse_width=0.0005, max_pulse_width=0.0024,
                          initial_angle=0)
        s2 = AngularServo(config.PIN_SERVO_2, min_angle=0, max_angle=180,
                          min_pulse_width=0.0005, max_pulse_width=0.0024,
                          initial_angle=180)

        time.sleep(0.5)
        s1.angle = 0
        s2.angle = 180

        logger.info("✓ Hardware GPIO inicializado en Proceso 2")
    except Exception as e:
        logger.error(f"✗ Error inicializando GPIO: {e}")
        return

    # LCD
    lcd = None
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
        logger.info("✓ LCD inicializada en Proceso 2")
    except Exception as e:
        logger.warning(f"⚠ LCD NO DETECTADA: {e}")

    def mostrar_lcd_local(linea1, linea2=""):
        """Muestra texto en LCD"""
        if lcd:
            try:
                lcd.clear()
                lcd.write_string(linea1[:config.LCD_COLS])
                if linea2:
                    lcd.cursor_pos = (1, 0)
                    lcd.write_string(linea2[:config.LCD_COLS])
            except Exception as e:
                logger.error(f"Error LCD: {e}")

    def abrir_puertas_local(usuario):
        """Abre las puertas"""
        led_rojo.off()
        led_verde.on()
        mostrar_lcd_local("ACCESO OK", usuario[:16])
        
        s1.angle = 90
        s2.angle = 90
        
        estado_sistema_p2["estado_puerta"] = "ABIERTA"
        logger.info(f"✓ Puertas abiertas: {usuario}")

    def cerrar_puertas_local():
        """Cierra las puertas"""
        mostrar_lcd_local("Cerrando...", "")
        time.sleep(1)
        
        led_verde.off()
        led_rojo.on()
        
        s1.angle = 0
        s2.angle = 180
        
        estado_sistema_p2["estado_puerta"] = "CERRADA"
        estado_sistema_p2["boton_habilitado"] = False
        estado_sistema_p2["usuario_actual"] = None
        
        time.sleep(1)
        mostrar_lcd_local("Login en Web", "Para acceder")
        logger.info("✓ Puertas cerradas")

    def esperar_paso_persona():
        """Espera a que la persona cruce"""
        estado_sistema_p2["detectando_paso"] = True
        logger.info("👤 Esperando paso de persona...")
        
        timeout = time.time() + 15
        detectado = False
        
        # Esperar bloqueo del láser B
        while time.time() < timeout:
            if laserB.is_pressed:
                detectado = True
                logger.info("✓ Persona detectada")
                break
            time.sleep(0.1)
        
        if detectado:
            # Esperar que se libere
            while laserB.is_pressed and time.time() < timeout:
                time.sleep(0.1)
            logger.info("✓ Persona cruzó completamente")
            time.sleep(1)
        else:
            logger.warning("⚠ Timeout: No se detectó paso")
        
        estado_sistema_p2["detectando_paso"] = False
        
        # Notificar al Proceso 1
        cola_eventos_p2.put({'tipo': 'paso_completado'})

    # -------------------------
    # HILO 3: MONITOR DE BOTÓN
    # -------------------------
    def hilo_monitor_boton():
        """HILO 3: Monitorea el botón físico"""
        logger.info("🧵 HILO 3 (Hardware): Monitor de botón iniciado")
        
        # Inicializar cerrado
        cerrar_puertas_local()
        
        while sistema_activo_p2.value == 1:
            try:
                if boton.wait_for_press(timeout=0.5):
                    logger.info("🔘 Botón físico presionado")
                    cola_eventos_p2.put({
                        'tipo': 'boton_presionado',
                        'origen': 'fisico',
                        'timestamp': datetime.now().isoformat()
                    })
                    time.sleep(0.5)  # Debounce
            except Exception as e:
                if "timed out" not in str(e).lower():
                    logger.error(f"Error monitor botón: {e}")
                time.sleep(0.1)
        
        logger.info("🧵 HILO 3: Detenido")

    # -------------------------
    # HILO 4: MONITOR DE LÁSERES
    # -------------------------
    def hilo_monitor_laseres():
        """HILO 4: Monitorea los láseres"""
        logger.info("🧵 HILO 4 (Hardware): Monitor de láseres iniciado")
        
        estado_a_ant = False
        estado_b_ant = False
        
        while sistema_activo_p2.value == 1:
            try:
                # Monitorear Láser A
                laser_a_bloq = laserA.is_pressed
                if laser_a_bloq != estado_a_ant:
                    tipo = 'laser_bloqueado' if laser_a_bloq else 'laser_libre'
                    cola_eventos_p2.put({
                        'tipo': tipo,
                        'laser': 'A',
                        'timestamp': datetime.now().isoformat()
                    })
                    estado_a_ant = laser_a_bloq
                
                # Monitorear Láser B
                laser_b_bloq = laserB.is_pressed
                if laser_b_bloq != estado_b_ant:
                    tipo = 'laser_bloqueado' if laser_b_bloq else 'laser_libre'
                    cola_eventos_p2.put({
                        'tipo': tipo,
                        'laser': 'B',
                        'timestamp': datetime.now().isoformat()
                    })
                    estado_b_ant = laser_b_bloq
                
                # Actualizar estado en tiempo real
                estado_sistema_p2["laser_a_activo"] = not laser_a_bloq
                estado_sistema_p2["laser_b_activo"] = not laser_b_bloq
                estado_sistema_p2["led_verde"] = led_verde.is_lit
                estado_sistema_p2["led_rojo"] = led_rojo.is_lit
                
                time.sleep(0.1)
                
            except Exception as e:
                logger.error(f"Error monitor láseres: {e}")
                time.sleep(1)
        
        logger.info("🧵 HILO 4: Detenido")

    # -------------------------
    # HILO PROCESADOR DE COMANDOS
    # -------------------------
    def hilo_procesar_comandos():
        """Procesa comandos del Proceso 1"""
        logger.info("🧵 HILO 5 (Hardware): Procesador comandos iniciado")
        
        while sistema_activo_p2.value == 1:
            try:
                if not cola_comandos_p2.empty():
                    cmd = cola_comandos_p2.get(timeout=0.5)
                    
                    if cmd['accion'] == 'abrir_puertas':
                        abrir_puertas_local(cmd.get('usuario', 'Usuario'))
                        # Esperar paso
                        esperar_paso_persona()
                    
                    elif cmd['accion'] == 'cerrar_puertas':
                        cerrar_puertas_local()
                    
                    elif cmd['accion'] == 'mostrar_lcd':
                        mostrar_lcd_local(cmd['linea1'], cmd.get('linea2', ''))
                    
            except Exception as e:
                if "Empty" not in str(e):
                    logger.error(f"Error procesando comandos: {e}")
            
            time.sleep(0.05)
        
        logger.info("🧵 HILO 5: Detenido")

    # Iniciar hilos del Proceso 2
    hilo_btn = threading.Thread(target=hilo_monitor_boton, daemon=True)
    hilo_laser = threading.Thread(target=hilo_monitor_laseres, daemon=True)
    hilo_cmd = threading.Thread(target=hilo_procesar_comandos, daemon=True)
    
    hilo_btn.start()
    hilo_laser.start()
    hilo_cmd.start()
    
    # Mantener proceso vivo
    hilo_btn.join()
    hilo_laser.join()
    hilo_cmd.join()
    
    # Cleanup
    led_verde.off()
    led_rojo.off()
    s1.angle = 0
    s2.angle = 180
    if lcd:
        lcd.clear()
    
    logger.info("🔧 PROCESO 2: Detenido")

# =========================================================================
# INICIO DEL SISTEMA
# =========================================================================

def iniciar_sistema():
    """Inicializa ambos procesos"""
    global manager, estado_sistema, cola_eventos, cola_comandos, sistema_activo, db_handler
    
    # Inicializar InfluxDB
    if config.ENABLE_INFLUXDB:
        try:
            from influxdb_handler import InfluxDBHandler
            db_handler = InfluxDBHandler(**config.get_influxdb_config())
            logger.info("✓ InfluxDB inicializado")
        except Exception as e:
            logger.error(f"✗ Error InfluxDB: {e}")
            db_handler = None
    
    # Manager para compartir datos
    manager = Manager()
    
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
        "laser_a_activo": True,
        "laser_b_activo": True,
        "led_verde": False,
        "led_rojo": True
    })
    
    cola_eventos = Queue()
    cola_comandos = Queue()
    sistema_activo = Value(ctypes.c_int, 1)
    
    print("\n" + "="*60)
    print("🚇 SISTEMA CANCELADORA METRO - MULTIPROCESO")
    print("="*60)
    print(f"📱 URL: http://<IP_RASPBERRY>:{config.FLASK_PORT}")
    print(f"🔘 Botón: GPIO {config.PIN_BOTON}")
    print(f"👥 Usuarios: {len(USUARIOS)}")
    print("\n📊 ARQUITECTURA:")
    print("   PROCESO 1 (Flask): 1 hilo")
    print("     └─ Procesador de eventos")
    print("   PROCESO 2 (Hardware): 3 hilos")
    print("     ├─ Monitor botón físico")
    print("     ├─ Monitor láseres")
    print("     └─ Procesador comandos")
    print("   Comunicación: 2 Queues")
    print("="*60 + "\n")
    
    # Iniciar Proceso 2
    p2 = Process(
        target=proceso_control_hardware,
        args=(cola_eventos, cola_comandos, estado_sistema, sistema_activo),
        name="ControlHardware"
    )
    p2.start()
    logger.info(f"✓ Proceso 2 iniciado (PID: {p2.pid})")
    
    # Iniciar Hilo 1 en Proceso 1
    hilo_eventos = threading.Thread(target=hilo_procesador_eventos, daemon=True)
    hilo_eventos.start()
    logger.info("✓ Hilo 1 iniciado (Proceso Flask)")
    
    try:
        app.run(
            host=config.FLASK_HOST,
            port=config.FLASK_PORT,
            debug=False,
            use_reloader=False
        )
    except KeyboardInterrupt:
        print("\n\n🛑 Cerrando...")
    finally:
        sistema_activo.value = 0
        p2.join(timeout=5)
        if p2.is_alive():
            p2.terminate()
            p2.join()
        
        if db_handler:
            db_handler.close()
        
        logger.info("✓ Sistema cerrado")

if __name__ == '__main__':
    iniciar_sistema()
