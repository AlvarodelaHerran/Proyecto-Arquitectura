"""
Aplicación Flask para Canceladora de Metro con Botón simulador
Raspberry Pi 5
Con sistema de autenticación de usuarios y almacenamiento en InfluxDB
Configuración desde archivo .env
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

# Estado global del sistema
estado_sistema = {
    "estado_puerta": "CERRADA",
    "timestamp": None,
    "total_accesos": 0,
    "personas_dentro": 0,
    "sistema_activo": True,
    "detectando_paso": False,
    "boton_habilitado": False,
    "usuario_actual": None,
    "ultimo_acceso": None
}

# -------------------------
# INICIALIZAR HARDWARE
# -------------------------

try:
    led_rojo = LED(config.PIN_LED_ROJO)
    led_verde = LED(config.PIN_LED_VERDE)
    boton = Button(config.PIN_BOTON, pull_up=True)
    laserA = Button(config.PIN_LASER_A, pull_up=True)
    laserB = Button(config.PIN_LASER_B, pull_up=True)

    s1 = AngularServo(config.PIN_SERVO_1, min_angle=0, max_angle=180,
                      min_pulse_width=0.0005, max_pulse_width=0.0024)
    s2 = AngularServo(config.PIN_SERVO_2, min_angle=0, max_angle=180,
                      min_pulse_width=0.0005, max_pulse_width=0.0024)
    
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
    global estado_sistema
    
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
    global estado_sistema
    
    mostrar_lcd("Cerrando...", "")
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
    
    time.sleep(config.DOOR_CLOSE_DELAY)
    mostrar_lcd("Login en Web", "Para acceder")
    logger.info("✓ Puertas cerradas")

def esperar_persona():
    """Espera a que la persona cruce completamente"""
    global estado_sistema
    
    estado_sistema["detectando_paso"] = True
    mostrar_lcd("Cruzando...", "")
    
    # Espera a que laser A detecte
    while laserA.is_pressed:
        time.sleep(0.05)
    
    # Espera a que laser B detecte
    while not laserB.is_pressed:
        time.sleep(0.05)
    
    mostrar_lcd("Paso completado", "")
    time.sleep(0.5)
    
    estado_sistema["detectando_paso"] = False
    logger.info("✓ Persona ha cruzado completamente")

def procesar_acceso():
    """Procesa un acceso cuando se pulsa el botón"""
    global estado_sistema
    
    # Verificar si el botón está habilitado (usuario logueado)
    if not estado_sistema["boton_habilitado"]:
        mostrar_lcd("ACCESO DENEGADO", "Login primero")
        logger.warning("✗ Intento de acceso sin login")
        time.sleep(2)
        mostrar_lcd("Login en Web", "Para acceder")
        return
    
    timestamp = datetime.now().strftime("%H:%M:%S")
    usuario = estado_sistema["usuario_actual"]
    
    estado_sistema.update({
        "timestamp": timestamp,
        "total_accesos": estado_sistema["total_accesos"] + 1,
        "personas_dentro": estado_sistema["personas_dentro"] + 1,
        "ultimo_acceso": {
            "usuario": usuario,
            "timestamp": timestamp
        }
    })
    
    # Registrar en InfluxDB
    if db_handler:
        db_handler.write_access_event(
            card_id=estado_sistema["total_accesos"],
            user_name=usuario,
            access_granted=True,
            door_id="canceladora_1"
        )
    
    logger.info(f"✓ Acceso #{estado_sistema['total_accesos']} - Usuario: {usuario}")
    
    # Abrir puertas y esperar paso
    abrir_puertas()
    esperar_persona()
    cerrar_puertas()

def monitor_boton():
    """Hilo que monitorea el botón continuamente"""
    logger.info("Iniciando monitoreo del botón...")
    cerrar_puertas()
    
    while estado_sistema["sistema_activo"]:
        try:
            if not estado_sistema["boton_habilitado"]:
                mostrar_lcd("Login en Web", "Para acceder")
            
            boton.wait_for_press()
            
            if estado_sistema["sistema_activo"]:
                procesar_acceso()
                
        except Exception as e:
            logger.error(f"Error en monitor de botón: {e}")
            time.sleep(1)

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
    estado_completo = estado_sistema.copy()
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
        threading.Thread(target=procesar_acceso, daemon=True).start()
        return jsonify({"mensaje": "Acceso simulado", "exito": True})
    elif not estado_sistema["boton_habilitado"]:
        return jsonify({"mensaje": "Debes hacer login primero", "exito": False}), 403
    return jsonify({"mensaje": "Sistema ocupado", "exito": False}), 409

# -------------------------
# INICIO DE LA APLICACIÓN
# -------------------------

if __name__ == '__main__':
    # Mostrar configuración
    config.print_config()
    
    # Iniciar hilo de monitoreo del botón
    hilo_boton = threading.Thread(target=monitor_boton, daemon=True)
    hilo_boton.start()
    
    print("\n" + "="*50)
    print("🚇 SISTEMA CANCELADORA DE METRO INICIADO")
    print("="*50)
    print(f"📱 Accede a la web desde: http://<IP_RASPBERRY>:{config.FLASK_PORT}")
    print(f"🔘 Botón configurado en GPIO {config.PIN_BOTON}")
    print(f"👥 Usuarios registrados: {len(USUARIOS)}")
    print("\n⚠️  CREDENCIALES POR DEFECTO:")
    print(f"   Admin: {config.DEFAULT_ADMIN_USER} / {config.DEFAULT_ADMIN_PASS}")
    print(f"   Usuario1: {config.DEFAULT_USER1_USER} / {config.DEFAULT_USER1_PASS}")
    print(f"   Usuario2: {config.DEFAULT_USER2_USER} / {config.DEFAULT_USER2_PASS}")
    print("="*50 + "\n")
    
    try:
        # Configuración SSL si está habilitada
        ssl_context = None
        if config.ENABLE_HTTPS:
            ssl_context = (config.SSL_CERT_PATH, config.SSL_KEY_PATH)
            logger.info("✓ HTTPS habilitado")
        
        app.run(
            host=config.FLASK_HOST,
            port=config.FLASK_PORT,
            debug=config.FLASK_DEBUG,
            ssl_context=ssl_context
        )
    except KeyboardInterrupt:
        print("\n\nCerrando sistema...")
        estado_sistema["sistema_activo"] = False
        
        # Cerrar puertas y apagar LEDs
        led_verde.off()
        led_rojo.off()
        s1.angle = 0
        s2.angle = 180
        
        if lcd:
            lcd.clear()
        
        if db_handler:
            db_handler.close()
        
        logger.info("Sistema cerrado correctamente")