import time
from gpiozero import LED, AngularServo, Button
from RPLCD.i2c import CharLCD

# -------------------------
# CONFIGURACIÓN DE PINES
# -------------------------

PIN_SERVO_1 = 17
PIN_SERVO_2 = 27

PIN_LASER_A = 22
PIN_LASER_B = 23

PIN_BOTON = 5

PIN_LED_ROJO = 24
PIN_LED_VERDE = 25

# -------------------------
# OBJETOS DE HARDWARE
# -------------------------

led_rojo = LED(PIN_LED_ROJO)
led_verde = LED(PIN_LED_VERDE)

boton = Button(5, pull_up=None, active_state=True)   # Botón normal

laserA = Button(PIN_LASER_A, pull_up=True)
laserB = Button(PIN_LASER_B, pull_up=True)

s1 = AngularServo(PIN_SERVO_1, min_angle=0, max_angle=180,
                  min_pulse_width=0.0005, max_pulse_width=0.0024)
s2 = AngularServo(PIN_SERVO_2, min_angle=0, max_angle=180,
                  min_pulse_width=0.0005, max_pulse_width=0.0024)

# -------------------------
# LCD I2C
# -------------------------

try:
    lcd = CharLCD(i2c_expander='PCF8574',
                  address=0x27,
                  port=1,
                  cols=16,
                  rows=2,
                  dotsize=8)
except:
    lcd = None
    print("LCD NO DETECTADA — usando solo consola")


# -------------------------
# FUNCIONES
# -------------------------

def mensaje(l1, l2=""):
    print(f"LCD: {l1} | {l2}")
    if lcd:
        lcd.clear()
        lcd.write_string(l1)
        lcd.cursor_pos = (1, 0)
        lcd.write_string(l2)

def abrir_puertas():
    led_rojo.off()
    led_verde.on()
    mensaje("ACCESO OK", "Pase")
    s1.angle = 90
    s2.angle = 90

def cerrar_puertas():
    mensaje("Cerrando...", "")
    led_verde.off()
    led_rojo.on()
    s1.angle = 0
    s2.angle = 180
    time.sleep(1)
    mensaje("ESPERANDO", "PULSA BOTON")

def esperar_persona():
    mensaje("Cruzando...", "")
    # Espera a que laser A detecte
    while laserA.is_pressed:
        pass
    # Espera a que laser B detecte
    while not laserB.is_pressed:
        pass
    mensaje("Paso completado", "")
    time.sleep(0.5)

# -------------------------
# BUCLE PRINCIPAL
# -------------------------

def main():
    cerrar_puertas()

    while True:
        mensaje("ESPERANDO", "PULSA BOTON")
        boton.wait_for_press()
        abrir_puertas()
        esperar_persona()
        cerrar_puertas()

if __name__ == "__main__":
    main()