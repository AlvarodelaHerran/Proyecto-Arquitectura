import serial
import time

# Abre el puerto serie de la Raspberry Pi
ser = serial.Serial(
    port='/dev/serial0',   # UART de la Pi
    baudrate=2400,         # Parallax usa 2400 baudios
    bytesize=serial.EIGHTBITS,
    parity=serial.PARITY_NONE,
    stopbits=serial.STOPBITS_ONE,
    timeout=0.5
)

def leer_tarjeta():
    print("Esperando tarjeta Parallax...\n")
    while True:
        # El Parallax envía 12 bytes: 0x0A + 10 dígitos ASCII + 0x0D
        if ser.in_waiting >= 12:
            data = ser.read(12)
            if len(data) == 12 and data[0] == 0x0A and data[-1] == 0x0D:
                codigo = data[1:-1].decode('ascii', errors='ignore')
                print("Tarjeta detectada:", codigo)
                return codigo
        time.sleep(0.05)

if __name__ == "__main__":
    try:
        while True:
            uid = leer_tarjeta()
            # Pequeña pausa para no leer dos veces la misma tarjeta
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nSaliendo...")
    finally:
        ser.close()