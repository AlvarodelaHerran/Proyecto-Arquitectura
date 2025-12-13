# Configuración de InfluxDB para el Sistema Metro

## 1. INSTALACIÓN EN RASPBERRY PI

```bash
# Actualizar sistema
sudo apt-get update
sudo apt-get upgrade -y

# Descargar e instalar InfluxDB 2.x
curl https://repos.influxdata.com/influxdata-archive.key | gpg --dearmor | sudo tee /usr/share/keyrings/influxdb-archive-keyring.gpg > /dev/null
echo "deb [signed-by=/usr/share/keyrings/influxdb-archive-keyring.gpg] https://repos.influxdata.com/debian stable main" | sudo tee /etc/apt/sources.list.d/influxdb.list
sudo apt-get update
sudo apt-get install influxdb2

# Iniciar servicio
sudo systemctl start influxdb
sudo systemctl enable influxdb

# Verificar que está corriendo
sudo systemctl status influxdb
```

## 2. CONFIGURACIÓN INICIAL

Accede a la interfaz web: http://localhost:8086

- Usuario: admin
- Contraseña: (la que definas)
- Organización: metro_org
- Bucket inicial: metro_system

## 3. CREAR TOKEN DE ACCESO

1. Ve a la sección "API Tokens" en el dashboard
2. Crea un nuevo token con permisos de lectura y escritura
3. Copia el token y pegalo en `CanceladoraMetro.py` en la variable `INFLUXDB_CONFIG["token"]`

Ejemplo de token (cambia por el tuyo real):
```
your_admin_token_here
```

## 4. INSTALAR CLIENTE PYTHON

```bash
pip install influxdb-client
```

## 5. MEDIR DE PROCESOS

### Medida 1: metro_access
Registra cada acceso a través de una tarjeta RFID

```
Campos (fields):
  - card_id: ID de la tarjeta (integer)
  - access_granted: True/False (boolean)

Etiquetas (tags):
  - door: ID de la puerta (ej: canceladora_1)
  - user: Nombre del usuario (ej: Juan Perez)

Timestamp: automático (UTC)
```

### Medida 2: metro_system_status
Registra el estado general del sistema

```
Campos (fields):
  - active_users: Usuarios activos (integer)
  - total_access: Total accesos permitidos (integer)
  - total_rejected: Total accesos denegados (integer)

Etiquetas (tags):
  - status: Estado del sistema (active/inactive)

Timestamp: automático (UTC)
```

## 6. CONSULTAS ÚTILES DE EJEMPLO

### Últimos 10 accesos:
```
from(bucket: "metro_system")
  |> range(start: -24h)
  |> filter(fn: (r) => r["_measurement"] == "metro_access")
  |> sort(columns: ["_time"], desc: true)
  |> limit(n: 10)
```

### Estadísticas por usuario en últimas 24h:
```
from(bucket: "metro_system")
  |> range(start: -24h)
  |> filter(fn: (r) => r["_measurement"] == "metro_access")
  |> group(columns: ["user"])
  |> count()
```

### Porcentaje de accesos permitidos/denegados:
```
from(bucket: "metro_system")
  |> range(start: -24h)
  |> filter(fn: (r) => r["_measurement"] == "metro_access")
  |> group(columns: ["access_granted"])
  |> count()
```

## 7. VERIFICAR DATOS

En el dashboard de InfluxDB:
1. Ve a "Data Explorer"
2. Selecciona el bucket "metro_system"
3. Selecciona la medida "metro_access" o "metro_system_status"
4. Visualiza los datos

## 8. IMPORTANTE

- El archivo `influxdb_handler.py` debe estar en la misma carpeta que `CanceladoraMetro.py`
- Asegúrate de cambiar el token por uno válido de tu InfluxDB
- La URL debe ser correcta (http://localhost:8086 si está en local)
- InfluxDB debe estar ejecutándose antes de iniciar la aplicación Flask
