"""
Aplicación Flask para Canceladora de Metro con RFID Parallax y LCD
Raspberry Pi 5
Con integración de InfluxDB para almacenamiento de datos en tiempo real
"""

from flask import Flask, render_template, jsonify, request
import time
from RPLCD.i2c import CharLCD
import serial
import RPi.GPIO as GPIO
import threading
import json
from datetime import datetime
from influxdb_handler import InfluxDBHandler

# --- CONFIGURACIÓN ---
app = Flask(__name__)

# Configuración de InfluxDB
INFLUXDB_CONFIG = {
    "url": "http://localhost:8086",        # URL del servidor InfluxDB
    "token": "your_admin_token_here",      # Token de autenticación (obtener de InfluxDB)
    "org": "metro_org",                     # Organización
    "bucket": "metro_system"                # Bucket para datos
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

# Pin para habilitar el lector RFID Parallax (activo bajo)
ENABLE_PIN = 17  # GPIO17 - Cambia según tu conexión

# Puerto serial para Parallax RFID
# Si usas versión USB: '/dev/ttyUSB0'
# Si usas versión Serial conectada a GPIO: '/dev/ttyAMA0' o '/dev/serial0'
SERIAL_PORT = '/dev/ttyUSB0'  # Cambia según tu modelo

# Base de datos simple de tarjetas autorizadas (ID: nombre)
TARJETAS_AUTORIZADAS = {
    123456789: "Usuario 1",
    987654321: "Usuario 2",
    # Añade más IDs según necesites
}

# Estado global del sistema
estado_sistema = {
    "ultima_tarjeta": None,
    "nombre_usuario": None,
    "acceso": None,
    "timestamp": None,
    "total_accesos": 0,
    "total_rechazos": 0,
    "sistema_activo": True
}

# --- INICIALIZAR HARDWARE ---
try:
    lcd = CharLCD(i2c_expander='PCF8574', address=0x27, port=1, cols=16, rows=2, dotsize=8)
    lcd.clear()
    lcd.write_string('Sistema Metro')
    lcd.cursor_pos = (1, 0)
    lcd.write_string('Iniciando...')
    time.sleep(1)
    print("✓ LCD inicializada correctamente")
except Exception as e:
    print(f"✗ Error con LCD: {e}")
    lcd = None

# Configurar GPIO para el pin ENABLE del Parallax RFID
GPIO.setwarnings(False)
GPIO.setmode(GPIO.BCM)
GPIO.setup(ENABLE_PIN, GPIO.OUT)
GPIO.output(ENABLE_PIN, GPIO.LOW)  # LOW = Activado

# Configurar puerto serial para Parallax RFID
try:
    rfid_serial = serial.Serial(
        port=SERIAL_PORT,
        baudrate=2400,
        bytesize=serial.EIGHTBITS,
        parity=serial.PARITY_NONE,
        stopbits=serial.STOPBITS_ONE,
        timeout=1
    )
    print(f"✓ Lector RFID Parallax inicializado en {SERIAL_PORT}")
except Exception as e:
    print(f"✗ Error al abrir puerto serial: {e}")
    rfid_serial = None

# --- FUNCIONES DE CONTROL ---
def mostrar_lcd(linea1, linea2=""):
    """Muestra texto en el LCD"""
    if lcd:
        try:
            lcd.clear()
            lcd.write_string(linea1[:16])
            if linea2:
                lcd.cursor_pos = (1, 0)
                lcd.write_string(linea2[:16])
        except Exception as e:
            print(f"Error LCD: {e}")

def procesar_tarjeta(id_tarjeta):
    """Procesa la lectura de una tarjeta RFID"""
    global estado_sistema
    
    timestamp = datetime.now().strftime("%H:%M:%S")
    
    if id_tarjeta in TARJETAS_AUTORIZADAS:
        # Acceso autorizado
        nombre = TARJETAS_AUTORIZADAS[id_tarjeta]
        estado_sistema.update({
            "ultima_tarjeta": id_tarjeta,
            "nombre_usuario": nombre,
            "acceso": "AUTORIZADO",
            "timestamp": timestamp,
            "total_accesos": estado_sistema["total_accesos"] + 1
        })
        
        # Registrar en InfluxDB
        if db_handler:
            db_handler.write_access_event(
                card_id=id_tarjeta,
                user_name=nombre,
                access_granted=True,
                door_id="canceladora_1"
            )
        
        mostrar_lcd("ACCESO PERMITIDO", nombre)
        print(f"✓ Acceso autorizado: {nombre} (ID: {id_tarjeta})")
        
    else:
        # Acceso denegado
        estado_sistema.update({
            "ultima_tarjeta": id_tarjeta,
            "nombre_usuario": "Desconocido",
            "acceso": "DENEGADO",
            "timestamp": timestamp,
            "total_rechazos": estado_sistema["total_rechazos"] + 1
        })
        
        # Registrar en InfluxDB
        if db_handler:
            db_handler.write_access_event(
                card_id=id_tarjeta,
                user_name="Desconocido",
                access_granted=False,
                door_id="canceladora_1"
            )
        
        mostrar_lcd("ACCESO DENEGADO", f"ID: {id_tarjeta}")
        print(f"✗ Acceso denegado: ID {id_tarjeta}")
    
    # Volver a pantalla de espera después de 3 segundos
    time.sleep(3)
    mostrar_lcd("Escanea Tarjeta", "Metro - Activo")

def leer_rfid_continuo():
    """Hilo para lectura continua del RFID Parallax"""
    print("Iniciando lectura continua de RFID Parallax...")
    mostrar_lcd("Escanea Tarjeta", "Metro - Activo")
    
    ultima_tarjeta = None
    ultimo_tiempo = 0
    
    while estado_sistema["sistema_activo"]:
        try:
            if rfid_serial and rfid_serial.in_waiting > 0:
                # Leer 12 bytes del Parallax RFID
                # Formato: 0x0A + 10 caracteres ASCII + 0x0D
                datos = rfid_serial.read(12)
                
                if len(datos) == 12:
                    # Verificar bytes de inicio y fin
                    if datos[0] == 0x0A and datos[11] == 0x0D:
                        # Extraer el ID (10 caracteres ASCII en el medio)
                        id_str = datos[1:11].decode('ascii', errors='ignore')
                        
                        # Convertir el ID hexadecimal a entero
                        try:
                            id_tarjeta = int(id_str, 16)
                            
                            # Evitar lecturas duplicadas (debounce)
                            tiempo_actual = time.time()
                            if id_tarjeta != ultima_tarjeta or (tiempo_actual - ultimo_tiempo) > 2:
                                procesar_tarjeta(id_tarjeta)
                                ultima_tarjeta = id_tarjeta
                                ultimo_tiempo = tiempo_actual
                                
                        except ValueError:
                            print(f"ID inválido recibido: {id_str}")
                            
        except Exception as e:
            print(f"Error en lectura RFID: {e}")
            time.sleep(1)

# --- RUTAS FLASK ---
@app.route('/')
def index():
    """Página principal"""
    return render_template('index.html')

@app.route('/estado')
def obtener_estado():
    """API: Devuelve el estado actual del sistema"""
    return jsonify(estado_sistema)

@app.route('/tarjetas')
def listar_tarjetas():
    """API: Lista todas las tarjetas autorizadas"""
    tarjetas = [{"id": id_tarj, "nombre": nombre} 
                for id_tarj, nombre in TARJETAS_AUTORIZADAS.items()]
    return jsonify(tarjetas)

@app.route('/agregar_tarjeta', methods=['POST'])
def agregar_tarjeta():
    """API: Añade una nueva tarjeta autorizada"""
    data = request.json
    id_tarjeta = int(data.get('id'))
    nombre = data.get('nombre')
    
    TARJETAS_AUTORIZADAS[id_tarjeta] = nombre
    return jsonify({"mensaje": f"Tarjeta {id_tarjeta} agregada", "exito": True})

@app.route('/eliminar_tarjeta/<int:id_tarjeta>', methods=['DELETE'])
def eliminar_tarjeta(id_tarjeta):
    """API: Elimina una tarjeta autorizada"""
    if id_tarjeta in TARJETAS_AUTORIZADAS:
        del TARJETAS_AUTORIZADAS[id_tarjeta]
        return jsonify({"mensaje": f"Tarjeta {id_tarjeta} eliminada", "exito": True})
    return jsonify({"mensaje": "Tarjeta no encontrada", "exito": False}), 404

@app.route('/reiniciar_estadisticas', methods=['POST'])
def reiniciar_estadisticas():
    """API: Reinicia los contadores de estadísticas"""
    estado_sistema["total_accesos"] = 0
    estado_sistema["total_rechazos"] = 0
    return jsonify({"mensaje": "Estadísticas reiniciadas", "exito": True})

@app.route('/api/accesos_recientes')
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
                "tarjeta_id": acc['card_id']
            } for acc in accesos
        ]
    })

@app.route('/api/estadisticas')
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

# --- INICIO DE LA APLICACIÓN ---
if __name__ == '__main__':
    # Iniciar hilo de lectura RFID
    hilo_rfid = threading.Thread(target=leer_rfid_continuo, daemon=True)
    hilo_rfid.start()
    
    print("\n" + "="*50)
    print("🚇 SISTEMA CANCELADORA DE METRO INICIADO")
    print("="*50)
    print(f"📱 Accede a la web desde: http://<IP_RASPBERRY>:8000")
    print(f"💳 Tarjetas autorizadas: {len(TARJETAS_AUTORIZADAS)}")
    print("="*50 + "\n")
    
    try:
        app.run(host='0.0.0.0', port=8000, debug=False)
    except KeyboardInterrupt:
        print("\n\nCerrando sistema...")
        estado_sistema["sistema_activo"] = False
        GPIO.output(ENABLE_PIN, GPIO.HIGH)  # Desactivar lector
        if rfid_serial:
            rfid_serial.close()
        if lcd:
            lcd.clear()
        GPIO.cleanup()
        print("Sistema cerrado correctamente")