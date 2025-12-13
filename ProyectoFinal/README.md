# 🚇 Sistema de Control de Acceso - Metro Parallax RFID + InfluxDB

Sistema completo de canceladora de metro con Raspberry Pi, RFID Parallax, LCD 16x2, servidor web Flask e integración con InfluxDB para almacenamiento y visualización de datos en tiempo real.

## 📋 Características

✅ **Lectura de tarjetas RFID Parallax** - Detección automática de accesos
✅ **Almacenamiento en InfluxDB** - Base de datos temporal optimizada para series de tiempo
✅ **Dashboard web en tiempo real** - Interfaz moderna con gráficos y estadísticas
✅ **Visualización de datos históricos** - Consultas de últimos 24h
✅ **Gestión de tarjetas** - Agregar/eliminar tarjetas autorizadas
✅ **Estadísticas detalladas** - Tasa de autorización, accesos por usuario, etc.
✅ **API RESTful** - Endpoints para integración con otros sistemas

---

## 🔧 Requisitos

### Hardware
- **Raspberry Pi 5** (o similar con GPIO)
- **Lector RFID Parallax** (conexión serial 2400 baud)
- **LCD 16x2** con módulo I2C PCF8574
- **Servos y LEDs** (opcional)
- **Fuente de alimentación** adecuada

### Software (Raspberry Pi)
- Python 3.9+
- InfluxDB 2.x
- Flask 3.0+
- influxdb-client para Python

---

## 📦 Instalación

### 1. Preparar el entorno en Raspberry Pi

```bash
# Actualizar sistema
sudo apt-get update
sudo apt-get upgrade -y

# Instalar Python y pip
sudo apt-get install python3 python3-pip python3-dev -y

# Clonar el repositorio
git clone <tu_repo>
cd Proyecto-Arquitectura/ProyectoFinal

# Crear entorno virtual
python3 -m venv venv
source venv/bin/activate

# Instalar dependencias
pip install -r requirements.txt
```

### 2. Instalar y Configurar InfluxDB

```bash
# Descargar e instalar InfluxDB 2.x
curl https://repos.influxdata.com/influxdata-archive.key | gpg --dearmor | sudo tee /usr/share/keyrings/influxdb-archive-keyring.gpg > /dev/null
echo "deb [signed-by=/usr/share/keyrings/influxdb-archive-keyring.gpg] https://repos.influxdata.com/debian stable main" | sudo tee /etc/apt/sources.list.d/influxdb.list

sudo apt-get update
sudo apt-get install influxdb2 -y

# Iniciar InfluxDB
sudo systemctl start influxdb
sudo systemctl enable influxdb

# Verificar estado
sudo systemctl status influxdb
```

### 3. Configurar InfluxDB (Primera vez)

Accede a: **http://raspberry-pi-ip:8086**

1. **Configura el servidor:**
   - Usuario: `admin`
   - Contraseña: (elige una segura)
   - Organización: `metro_org`
   - Bucket: `metro_system`

2. **Genera un token de acceso:**
   - Ve a **API Tokens**
   - Crea nuevo token con permisos de **lectura y escritura**
   - Copia el token

### 4. Configurar la aplicación Python

```bash
# Copiar archivo de configuración
cp .env.example .env

# Editar .env con tus valores
nano .env
```

En `.env`, actualiza:
```
INFLUXDB_TOKEN=tu_token_aqui
INFLUXDB_URL=http://localhost:8086
```

También actualiza en `CanceladoraMetro.py`:
```python
INFLUXDB_CONFIG = {
    "url": "http://localhost:8086",
    "token": "TU_TOKEN_AQUI",  # ← Pega tu token aquí
    "org": "metro_org",
    "bucket": "metro_system"
}
```

---

## 🚀 Ejecutar la Aplicación

```bash
# Activar entorno virtual (si no lo está)
source venv/bin/activate

# Ejecutar la aplicación
python CanceladoraMetro.py
```

La aplicación se iniciará en: **http://raspberry-pi-ip:8000**

---

## 📡 API Endpoints

### Obtener estado actual
```http
GET /estado
```
Devuelve el estado actual del sistema (último acceso, total de accesos, etc.)

### Obtener accesos recientes
```http
GET /api/accesos_recientes?minutos=60
```
Devuelve los accesos de los últimos N minutos desde InfluxDB

### Obtener estadísticas
```http
GET /api/estadisticas?horas=24
```
Devuelve estadísticas (total, permitidos, denegados, porcentaje) de las últimas N horas

### Listar tarjetas
```http
GET /tarjetas
```
Devuelve lista de todas las tarjetas autorizadas

### Agregar tarjeta
```http
POST /agregar_tarjeta
Content-Type: application/json

{
    "id": 123456789,
    "nombre": "Juan Pérez"
}
```

### Eliminar tarjeta
```http
DELETE /eliminar_tarjeta/123456789
```

### Reiniciar estadísticas
```http
POST /reiniciar_estadisticas
```

---

## 📊 Estructura de Datos en InfluxDB

### Medida: metro_access
Registra cada acceso

```
Measurement: metro_access
Tags:
  - door: "canceladora_1"
  - user: "Juan Pérez"
Fields:
  - card_id: 123456789 (integer)
  - access_granted: true (boolean)
Timestamp: UTC automático
```

### Medida: metro_system_status
Registra estado del sistema

```
Measurement: metro_system_status
Tags:
  - status: "active"
Fields:
  - active_users: 5 (integer)
  - total_access: 120 (integer)
  - total_rejected: 8 (integer)
Timestamp: UTC automático
```

---

## 🔍 Consultas InfluxDB Útiles

### Últimos 10 accesos:
```flux
from(bucket: "metro_system")
  |> range(start: -24h)
  |> filter(fn: (r) => r["_measurement"] == "metro_access")
  |> sort(columns: ["_time"], desc: true)
  |> limit(n: 10)
```

### Accesos por usuario (últimas 24h):
```flux
from(bucket: "metro_system")
  |> range(start: -24h)
  |> filter(fn: (r) => r["_measurement"] == "metro_access")
  |> group(columns: ["user"])
  |> count()
```

### Tasa de autorización:
```flux
from(bucket: "metro_system")
  |> range(start: -24h)
  |> filter(fn: (r) => r["_measurement"] == "metro_access")
  |> group(columns: ["access_granted"])
  |> count()
```

---

## 📁 Estructura del Proyecto

```
ProyectoFinal/
├── CanceladoraMetro.py          # Aplicación Flask principal
├── influxdb_handler.py           # Módulo para manejar InfluxDB
├── requirements.txt              # Dependencias Python
├── .env.example                  # Plantilla de configuración
├── INFLUXDB_CONFIG.md            # Guía de configuración InfluxDB
├── README.md                     # Este archivo
└── templates/
    └── index.html               # Dashboard web interactivo
```

---

## 🐛 Solución de Problemas

### Error: "No module named 'influxdb_client'"
```bash
pip install influxdb-client
```

### Error: "Connection refused" a InfluxDB
- Verifica que InfluxDB está corriendo: `sudo systemctl status influxdb`
- Comprueba la URL en la configuración
- Asegúrate del token válido

### Error: "Invalid token"
- Genera un nuevo token en el dashboard de InfluxDB
- Actualiza el token en `CanceladoraMetro.py`

### RFID no detecta tarjetas
- Verifica el puerto serial: `ls /dev/tty*`
- Comprueba la velocidad de baud (2400 para Parallax)
- Prueba con el script: `prueba_rfid_y_lcd.py`

### LCD no funciona
- Verifica la dirección I2C: `sudo i2cdetect -y 1`
- Confirma que el módulo PCF8574 está en dirección 0x27

---

## 📈 Monitoreo y Mantenimiento

### Ver logs de InfluxDB
```bash
sudo journalctl -u influxdb -f
```

### Backup de datos
```bash
influx backup /ruta/backup
```

### Limpieza de datos antiguos
En InfluxDB, configura retención de datos en las medidas según sea necesario.

---

## 🔐 Seguridad

- **Tokens de API:** Cambia el token por defecto por uno seguro
- **Firewall:** Restringe acceso a puertos 8000 (Flask) y 8086 (InfluxDB)
- **HTTPS:** En producción, configura SSL/TLS con nginx
- **Contraseña InfluxDB:** Usa contraseña fuerte

---

## 📞 Soporte

Para problemas, revisa:
1. Los logs: `python CanceladoraMetro.py` (en terminal)
2. El dashboard de InfluxDB (http://ip:8086)
3. El dashboard web (http://ip:8000)

---

## 📝 Notas

- Los datos se guardan en InfluxDB con timestamp UTC
- El dashboard se actualiza cada segundo (estado actual) y cada 5 segundos (histórico)
- Los datos se retienen según la política de retención configurada en InfluxDB
- Para uso en producción, usa un gestor de procesos como `systemd` o `supervisor`

---

**Proyecto desarrollado para Sistema de Control de Acceso Metro**  
Profesor: [Tu profesor]  
Fecha: 2025
