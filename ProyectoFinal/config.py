"""
Módulo de configuración para el Sistema de Canceladora Metro
Carga variables de entorno desde archivo .env
"""

import os
from dotenv import load_dotenv

# Cargar variables de entorno desde archivo .env
load_dotenv()

class Config:
    """Configuración centralizada del sistema"""
    
    # ============================================
    # INFLUXDB
    # ============================================
    INFLUXDB_URL = os.getenv('INFLUXDB_URL', 'http://localhost:8086')
    INFLUXDB_TOKEN = os.getenv('INFLUXDB_TOKEN', 'your_admin_token_here')
    INFLUXDB_ORG = os.getenv('INFLUXDB_ORG', 'metro_org')
    INFLUXDB_BUCKET = os.getenv('INFLUXDB_BUCKET', 'metro_system')
    ENABLE_INFLUXDB = os.getenv('ENABLE_INFLUXDB', 'true').lower() == 'true'
    
    # ============================================
    # FLASK
    # ============================================
    FLASK_ENV = os.getenv('FLASK_ENV', 'production')
    FLASK_PORT = int(os.getenv('FLASK_PORT', 8000))
    FLASK_HOST = os.getenv('FLASK_HOST', '0.0.0.0')
    FLASK_DEBUG = os.getenv('FLASK_DEBUG', 'False').lower() == 'true'
    FLASK_SECRET_KEY = os.getenv('FLASK_SECRET_KEY', 'tu_clave_secreta_muy_segura_cambiar_en_produccion')
    
    # ============================================
    # HARDWARE - PINES GPIO
    # ============================================
    PIN_SERVO_1 = int(os.getenv('PIN_SERVO_1', 17))
    PIN_SERVO_2 = int(os.getenv('PIN_SERVO_2', 27))
    PIN_LASER_A = int(os.getenv('PIN_LASER_A', 22))
    PIN_LASER_B = int(os.getenv('PIN_LASER_B', 23))
    PIN_BOTON = int(os.getenv('PIN_BOTON', 5))
    PIN_LED_ROJO = int(os.getenv('PIN_LED_ROJO', 13))
    PIN_LED_VERDE = int(os.getenv('PIN_LED_VERDE', 19))
    
    # ============================================
    # LCD I2C
    # ============================================
    LCD_ADDRESS = int(os.getenv('LCD_ADDRESS', '0x3f'), 16)
    LCD_PORT = int(os.getenv('LCD_PORT', 1))
    LCD_COLS = int(os.getenv('LCD_COLS', 16))
    LCD_ROWS = int(os.getenv('LCD_ROWS', 2))
    
    # ============================================
    # USUARIOS POR DEFECTO
    # ============================================
    DEFAULT_ADMIN_USER = os.getenv('DEFAULT_ADMIN_USER', 'admin')
    DEFAULT_ADMIN_PASS = os.getenv('DEFAULT_ADMIN_PASS', 'admin123')
    DEFAULT_ADMIN_NAME = os.getenv('DEFAULT_ADMIN_NAME', 'Administrador')
    
    DEFAULT_USER1_USER = os.getenv('DEFAULT_USER1_USER', 'usuario1')
    DEFAULT_USER1_PASS = os.getenv('DEFAULT_USER1_PASS', 'pass123')
    DEFAULT_USER1_NAME = os.getenv('DEFAULT_USER1_NAME', 'Juan Pérez')
    
    DEFAULT_USER2_USER = os.getenv('DEFAULT_USER2_USER', 'usuario2')
    DEFAULT_USER2_PASS = os.getenv('DEFAULT_USER2_PASS', 'pass123')
    DEFAULT_USER2_NAME = os.getenv('DEFAULT_USER2_NAME', 'María García')
    
    # ============================================
    # SISTEMA
    # ============================================
    DOOR_CLOSE_DELAY = int(os.getenv('DOOR_CLOSE_DELAY', 1))
    SESSION_TIMEOUT = int(os.getenv('SESSION_TIMEOUT', 30))
    LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
    UPDATE_INTERVAL = int(os.getenv('UPDATE_INTERVAL', 1000))
    
    # ============================================
    # SEGURIDAD
    # ============================================
    MAX_LOGIN_ATTEMPTS = int(os.getenv('MAX_LOGIN_ATTEMPTS', 5))
    LOCKOUT_DURATION = int(os.getenv('LOCKOUT_DURATION', 15))
    ENABLE_HTTPS = os.getenv('ENABLE_HTTPS', 'false').lower() == 'true'
    SSL_CERT_PATH = os.getenv('SSL_CERT_PATH', '/path/to/cert.pem')
    SSL_KEY_PATH = os.getenv('SSL_KEY_PATH', '/path/to/key.pem')
    
    # ============================================
    # MODO DEBUG/DESARROLLO
    # ============================================
    HARDWARE_DEBUG = os.getenv('HARDWARE_DEBUG', 'false').lower() == 'true'
    SIMULATE_HARDWARE = os.getenv('SIMULATE_HARDWARE', 'false').lower() == 'true'
    
    @classmethod
    def get_influxdb_config(cls):
        """Retorna configuración de InfluxDB como diccionario"""
        return {
            "url": cls.INFLUXDB_URL,
            "token": cls.INFLUXDB_TOKEN,
            "org": cls.INFLUXDB_ORG,
            "bucket": cls.INFLUXDB_BUCKET
        }
    
    @classmethod
    def validate(cls):
        """Valida la configuración y muestra warnings"""
        warnings = []
        
        if cls.FLASK_SECRET_KEY == 'tu_clave_secreta_muy_segura_cambiar_en_produccion':
            warnings.append("⚠️  ADVERTENCIA: Usando clave secreta por defecto. Cámbiala en producción!")
        
        if cls.INFLUXDB_TOKEN == 'your_admin_token_here':
            warnings.append("⚠️  ADVERTENCIA: Token de InfluxDB no configurado. Usa el token real.")
        
        if cls.FLASK_ENV == 'production' and cls.FLASK_DEBUG:
            warnings.append("⚠️  ADVERTENCIA: Debug mode habilitado en producción. No recomendado.")
        
        return warnings
    
    @classmethod
    def print_config(cls):
        """Imprime la configuración actual (sin valores sensibles)"""
        print("\n" + "="*60)
        print("⚙️  CONFIGURACIÓN DEL SISTEMA")
        print("="*60)
        print(f"Flask Port: {cls.FLASK_PORT}")
        print(f"Flask Debug: {cls.FLASK_DEBUG}")
        print(f"InfluxDB URL: {cls.INFLUXDB_URL}")
        print(f"InfluxDB Org: {cls.INFLUXDB_ORG}")
        print(f"InfluxDB Bucket: {cls.INFLUXDB_BUCKET}")
        print(f"InfluxDB Habilitado: {cls.ENABLE_INFLUXDB}")
        print(f"\nPines GPIO:")
        print(f"  - Botón: GPIO {cls.PIN_BOTON}")
        print(f"  - Servo 1: GPIO {cls.PIN_SERVO_1}")
        print(f"  - Servo 2: GPIO {cls.PIN_SERVO_2}")
        print(f"  - LED Verde: GPIO {cls.PIN_LED_VERDE}")
        print(f"  - LED Rojo: GPIO {cls.PIN_LED_ROJO}")
        print(f"  - Láser A: GPIO {cls.PIN_LASER_A}")
        print(f"  - Láser B: GPIO {cls.PIN_LASER_B}")
        print(f"\nLCD I2C:")
        print(f"  - Dirección: 0x{cls.LCD_ADDRESS:02X}")
        print(f"  - Puerto: {cls.LCD_PORT}")
        print(f"  - Tamaño: {cls.LCD_COLS}x{cls.LCD_ROWS}")
        print("="*60)
        
        # Mostrar warnings
        warnings = cls.validate()
        if warnings:
            print("\n" + "="*60)
            for warning in warnings:
                print(warning)
            print("="*60)


# Crear instancia global de configuración
config = Config()