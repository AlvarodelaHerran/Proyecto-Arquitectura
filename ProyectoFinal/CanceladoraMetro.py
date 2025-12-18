"""
Canceladora Metro – versión con multiprocessing + threading
Cumple rúbrica ACO
"""

# =========================
# IMPORTS
# =========================
from multiprocessing import Process, Queue
import threading
import time
from flask import Flask, render_template, jsonify, request, session, redirect, url_for
from gpiozero import LED, AngularServo, Button
from RPLCD.i2c import CharLCD
from datetime import datetime, timedelta
from functools import wraps
from influxdb_handler import InfluxDBHandler
import hashlib
import logging

from config import config

# =========================
# LOGGING
# =========================
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# =========================
# ESTADO COMPARTIDO
# =========================
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

# =========================
# USUARIOS
# =========================
def hash_password(password):
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

# =========================
# PROCESO 1 – FLASK
# =========================
def run_flask(event_queue):

    app = Flask(__name__)
    app.secret_key = config.FLASK_SECRET_KEY
    app.config['EVENT_QUEUE'] = event_queue
    app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=config.SESSION_TIMEOUT)

    # ---------- Decoradores ----------
    def login_required(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if 'username' not in session:
                return jsonify({"error": "No autenticado"}), 401
            return f(*args, **kwargs)
        return decorated

    # ---------- Rutas ----------
    @app.route('/')
    def index():
        if 'username' not in session:
            return redirect('/login')
        return render_template('dashboard.html')

    @app.route('/login')
    def login_page():
        return render_template('login.html')

    @app.route('/api/login', methods=['POST'])
    def login():
        data = request.json
        user = USUARIOS.get(data['username'])
        if user and user['password'] == hash_password(data['password']):
            session['username'] = data['username']
            session['nombre'] = user['nombre']
            event_queue.put({"type": "login", "user": user['nombre']})
            return jsonify({"ok": True})
        return jsonify({"error": "Credenciales incorrectas"}), 401

    @app.route('/simular_acceso', methods=['POST'])
    @login_required
    def simular():
        event_queue.put({"type": "acceso_web"})
        return jsonify({"ok": True})

    app.run(
        host=config.FLASK_HOST,
        port=config.FLASK_PORT,
        debug=config.FLASK_DEBUG
    )

# =========================
# PROCESO 2 – HARDWARE
# =========================
def run_hardware(event_queue):

    # ---------- Hardware ----------
    led_rojo = LED(config.PIN_LED_ROJO)
    led_verde = LED(config.PIN_LED_VERDE)
    boton = Button(config.PIN_BOTON)
    laserB = Button(config.PIN_LASER_B)

    s1 = AngularServo(config.PIN_SERVO_1, initial_angle=0)
    s2 = AngularServo(config.PIN_SERVO_2, initial_angle=180)

    lcd = None
    try:
        lcd = CharLCD('PCF8574', config.LCD_ADDRESS)
        lcd.clear()
    except:
        pass

    db_handler = None
    if config.ENABLE_INFLUXDB:
        db_handler = InfluxDBHandler(**config.get_influxdb_config())

    # ---------- Funciones ----------
    def abrir_puertas():
        led_rojo.off()
        led_verde.on()
        s1.angle = 90
        s2.angle = 90

    def cerrar_puertas():
        led_verde.off()
        led_rojo.on()
        s1.angle = 0
        s2.angle = 180

    def procesar_acceso():
        abrir_puertas()
        time.sleep(2)
        cerrar_puertas()

        estado_sistema["total_accesos"] += 1
        if db_handler:
            db_handler.write_access_event(
                card_id=estado_sistema["total_accesos"],
                user_name=estado_sistema["usuario_actual"],
                access_granted=True,
                door_id="canceladora_1"
            )

    # ---------- HILO 1 ----------
    def hilo_boton():
        while estado_sistema["sistema_activo"]:
            boton.wait_for_press()
            procesar_acceso()

    # ---------- HILO 2 ----------
    def hilo_eventos():
        while estado_sistema["sistema_activo"]:
            if not event_queue.empty():
                evento = event_queue.get()
                if evento["type"] in ("acceso_web", "login"):
                    estado_sistema["usuario_actual"] = evento.get("user")
                    procesar_acceso()
            time.sleep(0.1)

    threading.Thread(target=hilo_boton, daemon=True).start()
    threading.Thread(target=hilo_eventos, daemon=True).start()

    while True:
        time.sleep(1)

# =========================
# MAIN (LANZADOR)
# =========================
if __name__ == "__main__":

    cola_eventos = Queue()

    p_web = Process(target=run_flask, args=(cola_eventos,))
    p_hw = Process(target=run_hardware, args=(cola_eventos,))

    p_web.start()
    p_hw.start()

    p_web.join()
    p_hw.join()