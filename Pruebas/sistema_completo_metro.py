import time
from gpiozero import LED, AngularServo  # Buzzer lo dejamos simulado
from RPLCD.i2c import CharLCD
import RPi.GPIO as GPIO
import serial

# --- CONFIGURACIÓN DE PINES ---
PIN_LED_ROJO = 17
PIN_LED_VERDE = 27
PIN_SERVO_1 = 12
PIN_SERVO_2 = 13
# PIN_LASER = 22  # Cuando tengas el sensor láser
# PIN_BUZZER = 23 # Cuando tengas el zumbador

# --- OBJETOS DE HARDWARE ---

led_rojo = LED(PIN_LED_ROJO)
led_verde = LED(PIN_LED_VERDE)

# Servos
s1 = AngularServo(
    PIN_SERVO_1,
    min_angle=0,
    max_angle=180,
    min_pulse_width=0.0005,
    max_pulse_width=0.0024
)

s2 = AngularServo(
    PIN_SERVO_2,
    min_angle=0,
    max_angle=180,
    min_pulse_width=0.0005,
    max_pulse_width=0.0024
)

# --- PARALLAX RFID (SERIAL) ---
# Asegúrate de tener habilitado el puerto serie y pyserial instalado.
ser = serial.Serial(
    port='/dev/serial0',      # UART principal de la Raspberry Pi
    baudrate=2400,            # Parallax usa 2400 baudios
    bytesize=serial.EIGHTBITS,
    parity=serial.PARITY_NONE,
    stopbits=serial.STOPBITS_ONE,
    timeout=0.5
)

# --- LCD (si falla, seguimos solo con consola) ---
try:
    lcd = CharLCD(
        i2c_expander='PCF8574',
        address=0x27,    # cambia a 0x3F si i2cdetect dice otra cosa
        port=1,
        cols=16,
        rows=2,
        dotsize=8
    )
    print("LCD detectada correctamente.")
except Exception as e:
    print("AVISO: LCD no detectada. Usando solo consola.")
    print("Detalle del error:", e)
    lcd = None

# --- FUNCIONES ---

def sonar_zumbador():
    """Simula el pitido corto."""
    print("* BEEP *")
    # Cuando tengas el buzzer:
    # buzzer.on()
    # time.sleep(0.2)
    # buzzer.off()


def mensaje_pantalla(linea1, linea2=""):
    """Escribe en la LCD (si existe) y en consola."""
    print(f"LCD: {linea1} | {linea2}")
    if lcd:
        lcd.clear()
        lcd.write_string(linea1[:16])
        lcd.cursor_pos = (1, 0)
        lcd.write_string(linea2[:16])


def abrir_puertas():
    """Secuencia de apertura."""
    sonar_zumbador()
    led_rojo.off()
    led_verde.on()
    mensaje_pantalla("ACCESO PERMITIDO", "Pase por favor")

    # Girar servos 90 grados
    s1.angle = 90
    s2.angle = 90
    time.sleep(0.5)  # tiempo para que lleguen


def cerrar_puertas():
    """Secuencia de cierre."""
    mensaje_pantalla("Cerrando...", "Puerta Metro")
    led_verde.off()
    led_rojo.on()

    # Posición inicial (ajusta si tus puertas son al revés)
    s1.angle = 0
    s2.angle = 180
    time.sleep(1)

    mensaje_pantalla("ESPERANDO", "TARJETA...")


def esperar_paso_persona():
    """
    Aquí irá la lógica real del sensor láser.
    De momento simulamos que tarda 5 segundos en pasar.
    """
    print("Esperando a que cruce la persona (Simulación 5s)...")
    time.sleep(5)
    # Cuando tengas el láser:
    # while GPIO.input(PIN_LASER) == True:
    #     time.sleep(0.1)
    # print("Persona detectada cruzando!")
    # while GPIO.input(PIN_LASER) == False:
    #     time.sleep(0.1)
    # print("La persona ha terminado de cruzar.")


def esperar_tarjeta_parallax():
    """
    Bloquea hasta que el lector Parallax envía un código válido.
    El Parallax manda 12 bytes: 0x0A + 10 ASCII + 0x0D.
    Devuelve el string con los 10 caracteres de la tarjeta.
    """
    print("Esperando tarjeta Parallax...")
    # Limpiamos cualquier basura en el buffer
    ser.reset_input_buffer()

    while True:
        if ser.in_waiting >= 12:
            data = ser.read(12)
            # Comprobamos formato
            if len(data) == 12 and data[0] == 0x0A and data[-1] == 0x0D:
                codigo = data[1:-1].decode('ascii', errors='ignore')
                print(f"Tarjeta detectada: {codigo}")
                return codigo
        time.sleep(0.05)


# --- BUCLE PRINCIPAL ---

def main():
    try:
        # Estado inicial
        cerrar_puertas()

        while True:
            # 1. Leer tarjeta (Parallax)
            codigo_tarjeta = esperar_tarjeta_parallax()
            # Aquí podrías validar tarjetas:
            # if codigo_tarjeta != "TU_CODIGO_VALIDO": ...

            # 2. Abrir puerta
            abrir_puertas()

            # 3. Esperar a que la persona pase (simulación / láser)
            esperar_paso_persona()

            # 4. Cerrar puerta
            cerrar_puertas()

    except KeyboardInterrupt:
        print("\nApagando sistema...")

    finally:
        if lcd:
            lcd.clear()
        led_rojo.off()
        led_verde.off()
        ser.close()
        GPIO.cleanup()
        print("GPIO y puerto serie liberados.")


if __name__ == "__main__":
    main()