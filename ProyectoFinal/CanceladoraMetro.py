"""
Aplicación Flask para Canceladora de Metro con Botón simulador
Raspberry Pi 5
Con sistema de autenticación de usuarios y almacenamiento en InfluxDB
"""

from flask import Flask, render_template, jsonify, request, session, redirect, url_for
import time
from gpiozero import LED, AngularServo, Button
from RPLCD.i2c import CharLCD
import threading
import json
from datetime import datetime
from functools import wraps
from influxdb_handler import InfluxDBHandler
import hashlib

# --- CONFIGURACIÓN ---
app = Flask(__name__)
app.secret_key = 'tu_clave_secreta_muy_segura_cambiar_en_produccion'  # CAMBIAR EN PRODUCCIÓN

# Configuración de InfluxDB
INFLUXDB_CONFIG = {
    "url": "http://localhost:8086",
    "token": "your_admin_token_here",
    "org": "metro_org",
    "bucket": "metro_system"
}

# Inicializar cliente InfluxDB
try:
    db_handler = InfluxDBHandler(
        url=INFLUXDB_CONFIG["url"],
        token=INFLUXDB_CONFIG["token"],
        org=INFLUXDB_CONFIG["org"],
        bucket=INFLUXDB_CONFIG["bucket"]
    )
    print("✓ InfluxDB inicializado correctamente")
except Exception as e:
    print(f"✗ Error inicializando InfluxDB: {e}")
    db_handler = None

# -------------------------
# CONFIGURACIÓN DE PINES
# -------------------------

PIN_SERVO_1 = 17
PIN_SERVO_2 = 27
PIN_LASER_A = 22
PIN_LASER_B = 23
PIN_BOTON = 5
PIN_LED_ROJO = 13
PIN_LED_VERDE = 19

# -------------------------
# BASE DE DATOS DE USUARIOS
# -------------------------

def hash_password(password):
    """Hashea una contraseña usando SHA256"""
    return hashlib.sha256(password.encode()).hexdigest()

# Base de datos de usuarios {username: {password_hash, name, role}}
USUARIOS = {
    "admin": {
        "password": hash_password("admin123"),  # Contraseña: admin123
        "nombre": "Administrador",
        "rol": "admin"
    },
    "usuario1": {
        "password": hash_password("pass123"),  # Contraseña: pass123
        "nombre": "Juan Pérez",
        "rol": "usuario"
    },
    "usuario2": {
        "password": hash_password("pass123"),
        "nombre": "María García",
        "rol": "usuario"
    }
}

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

led_rojo = LED(PIN_LED_ROJO)
led_verde = LED(PIN_LED_VERDE)
boton = Button(PIN_BOTON, pull_up=True)
laserA = Button(PIN_LASER_A, pull_up=True)
laserB = Button(PIN_LASER_B, pull_up=True)

s1 = AngularServo(PIN_SERVO_1, min_angle=0, max_angle=180,
                  min_pulse_width=0.0005, max_pulse_width=0.0024)
s2 = AngularServo(PIN_SERVO_2, min_angle=0, max_angle=180,
                  min_pulse_width=0.0005, max_pulse_width=0.0024)

# LCD I2C
try:
    lcd = CharLCD(i2c_expander='PCF8574',
                  address=0x27,
                  port=1,
                  cols=16,
                  rows=2,
                  dotsize=8)
    lcd.clear()
    lcd.write_string('Sistema Metro')
    lcd.cursor_pos = (1, 0)
    lcd.write_string('Iniciando...')
    time.sleep(1)
    print("✓ LCD inicializada correctamente")
except Exception as e:
    lcd = None
    print(f"✗ LCD NO DETECTADA: {e}")

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
    print(f"LCD: {linea1} | {linea2}")
    if lcd:
        try:
            lcd.clear()
            lcd.write_string(linea1[:16])
            if linea2:
                lcd.cursor_pos = (1, 0)
                lcd.write_string(linea2[:16])
        except Exception as e:
            print(f"Error LCD: {e}")

def abrir_puertas():
    """Abre las puertas del torniquete"""
    global estado_sistema
    
    led_rojo.off()
    led_verde.on()
    
    usuario = estado_sistema["usuario_actual"] or "Usuario"
    mostrar_lcd("ACCESO OK", f"{usuario[:16]}")
    
    estado_sistema["estado_puerta"] = "ABIERTA"
    
    s1.angle = 90
    s2.angle = 90
    
    print(f"✓ Puertas abiertas para {usuario}")

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
    
    time.sleep(1)
    mostrar_lcd("Login en Web", "Para acceder")
    print("✓ Puertas cerradas")

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
    print("✓ Persona ha cruzado completamente")

def procesar_acceso():
    """Procesa un acceso cuando se pulsa el botón"""
    global estado_sistema
    
    # Verificar si el botón está habilitado (usuario logueado)
    if not estado_sistema["boton_habilitado"]:
        mostrar_lcd("ACCESO DENEGADO", "Login primero")
        print("✗ Intento de acceso sin login")
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
    
    print(f"✓ Acceso #{estado_sistema['total_accesos']} - Usuario: {usuario}")
    
    # Abrir puertas y esperar paso
    abrir_puertas()
    esperar_persona()
    cerrar_puertas()

def monitor_boton():
    """Hilo que monitorea el botón continuamente"""
    print("Iniciando monitoreo del botón...")
    cerrar_puertas()
    
    while estado_sistema["sistema_activo"]:
        try:
            if not estado_sistema["boton_habilitado"]:
                mostrar_lcd("Login en Web", "Para acceder")
            
            boton.wait_for_press()
            
            if estado_sistema["sistema_activo"]:
                procesar_acceso()
                
        except Exception as e:
            print(f"Error en monitor de botón: {e}")
            time.sleep(1)

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
    
    # Verificar credenciales
    usuario = USUARIOS.get(username)
    if usuario and usuario['password'] == hash_password(password):
        # Login exitoso
        session['username'] = username
        session['nombre'] = usuario['nombre']
        session['rol'] = usuario['rol']
        
        # Habilitar el botón para este usuario
        estado_sistema["boton_habilitado"] = True
        estado_sistema["usuario_actual"] = usuario['nombre']
        
        mostrar_lcd("Login exitoso", usuario['nombre'][:16])
        time.sleep(1)
        mostrar_lcd("Pulsa boton", "Para acceder")
        
        return jsonify({
            "exito": True,
            "mensaje": "Login exitoso",
            "usuario": {
                "username": username,
                "nombre": usuario['nombre'],
                "rol": usuario['rol']
            }
        })
    
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
    
    print(f"✓ Usuario {username} cerró sesión")
    
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

@app.route('/agregar_usuario', methods=['POST'])
@admin_required
def agregar_usuario():
    """API: Añade un nuevo usuario (solo admin)"""
    data = request.json
    username = data.get('username')
    password = data.get('password')
    nombre = data.get('nombre')
    rol = data.get('rol', 'usuario')
    
    if username in USUARIOS:
        return jsonify({"error": "El usuario ya existe"}), 400
    
    USUARIOS[username] = {
        "password": hash_password(password),
        "nombre": nombre,
        "rol": rol
    }
    
    return jsonify({"mensaje": f"Usuario {username} agregado", "exito": True})

@app.route('/eliminar_usuario/<username>', methods=['DELETE'])
@admin_required
def eliminar_usuario(username):
    """API: Elimina un usuario (solo admin)"""
    if username == "admin":
        return jsonify({"error": "No se puede eliminar al administrador"}), 400
    
    if username in USUARIOS:
        del USUARIOS[username]
        return jsonify({"mensaje": f"Usuario {username} eliminado", "exito": True})
    
    return jsonify({"error": "Usuario no encontrado"}), 404

@app.route('/reiniciar_estadisticas', methods=['POST'])
@admin_required
def reiniciar_estadisticas():
    """API: Reinicia los contadores de estadísticas (solo admin)"""
    estado_sistema["total_accesos"] = 0
    estado_sistema["personas_dentro"] = 0
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
    # Iniciar hilo de monitoreo del botón
    hilo_boton = threading.Thread(target=monitor_boton, daemon=True)
    hilo_boton.start()
    
    print("\n" + "="*50)
    print("🚇 SISTEMA CANCELADORA DE METRO INICIADO")
    print("="*50)
    print(f"📱 Accede a la web desde: http://<IP_RASPBERRY>:8000")
    print(f"🔘 Botón configurado en GPIO {PIN_BOTON}")
    print(f"👥 Usuarios registrados: {len(USUARIOS)}")
    print("\n⚠️  CREDENCIALES POR DEFECTO:")
    print("   Admin: admin / admin123")
    print("   Usuario1: usuario1 / pass123")
    print("   Usuario2: usuario2 / pass123")
    print("="*50 + "\n")
    
    try:
        app.run(host='0.0.0.0', port=8000, debug=False)
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
        
        print("Sistema cerrado correctamente")