Configuración de InfluxDB para el Sistema de Canceladora Metro
Sistema con Autenticación de Usuarios - Raspberry Pi 5

📦 1. INSTALACIÓN EN RASPBERRY PI 5
bash# Actualizar sistema
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
Salida esperada:
● influxdb.service - InfluxDB is an open-source, distributed, time series database
   Loaded: loaded
   Active: active (running)

🔧 2. CONFIGURACIÓN INICIAL
Acceder a la interfaz web:
http://localhost:8086
O desde otro dispositivo en la red:
http://<IP_RASPBERRY>:8086
Configuración inicial:

Usuario: admin
Contraseña: admin123 (o la que prefieras - ¡cámbiala!)
Organización: metro_org
Bucket inicial: metro_system
Retention period: Infinite (o 30 días si prefieres limitar)


🔑 3. CREAR TOKEN DE ACCESO

En el dashboard de InfluxDB, ve a Data → API Tokens
Click en Generate API Token → All Access API Token
Nombre sugerido: metro_token_admin
Copia el token generado (solo se muestra una vez)

Ejemplo de token (NO usar este, es de ejemplo):
xXyYzZ1234567890abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ==
Pegar el token en tu aplicación:
Edita el archivo principal de Flask y reemplaza en la sección INFLUXDB_CONFIG:
pythonINFLUXDB_CONFIG = {
    "url": "http://localhost:8086",
    "token": "TU_TOKEN_AQUI",  # ⬅️ Pega tu token aquí
    "org": "metro_org",
    "bucket": "metro_system"
}

📚 4. INSTALAR CLIENTE PYTHON
bash# Activar entorno virtual (recomendado)
python3 -m venv venv
source venv/bin/activate

# Instalar cliente InfluxDB
pip install influxdb-client

# Verificar instalación
python3 -c "import influxdb_client; print('✓ Cliente InfluxDB instalado correctamente')"

📊 5. ESTRUCTURA DE MEDIDAS (MEASUREMENTS)
📌 Medida 1: metro_access
Descripción: Registra cada acceso a través del botón físico con autenticación
Fields (campos):
  - access_id: Número de acceso (integer)
  - access_granted: True/False (boolean)

Tags (etiquetas):
  - door: ID de la canceladora (ej: "canceladora_1")
  - user: Nombre del usuario autenticado (ej: "Juan Pérez")
  - access_status: "granted" o "denied"

Timestamp: UTC automático
Ejemplo de dato:
metro_access,door=canceladora_1,user=Juan\ Pérez,access_status=granted access_id=42i,access_granted=true 1638360000000000000

📌 Medida 2: metro_login
Descripción: Registra eventos de login (nuevos y cerrados de sesión)
Fields (campos):
  - user_name: Nombre completo (string)
  - success: True/False (boolean)

Tags (etiquetas):
  - username: Username del usuario (ej: "usuario1")
  - role: Rol del usuario ("admin" o "usuario")
  - status: "success" o "failed"

Timestamp: UTC automático

📌 Medida 3: metro_system_status
Descripción: Registra el estado general del sistema periódicamente
Fields (campos):
  - active_sessions: Sesiones activas (integer)
  - total_access_today: Total accesos del día (integer)
  - people_inside: Personas dentro del recinto (integer)
  - button_enabled: Botón habilitado (boolean)

Tags (etiquetas):
  - status: "active" (botón habilitado) o "waiting" (esperando login)

Timestamp: UTC automático

📌 Medida 4: metro_door_status
Descripción: Registra el estado de las puertas y sensores láser
Fields (campos):
  - is_open: Puerta abierta (boolean)
  - detecting_crossing: Detectando paso de persona (boolean)
  - laser_a_active: Estado láser A (boolean)
  - laser_b_active: Estado láser B (boolean)

Tags (etiquetas):
  - door_status: "ABIERTA" o "CERRADA"

Timestamp: UTC automático

🔍 6. CONSULTAS ÚTILES (FLUX QUERIES)
📋 Últimos 20 accesos registrados:
fluxfrom(bucket: "metro_system")
  |> range(start: -24h)
  |> filter(fn: (r) => r["_measurement"] == "metro_access")
  |> filter(fn: (r) => r["_field"] == "access_id")
  |> sort(columns: ["_time"], desc: true)
  |> limit(n: 20)

👤 Accesos por usuario en las últimas 24h:
fluxfrom(bucket: "metro_system")
  |> range(start: -24h)
  |> filter(fn: (r) => r["_measurement"] == "metro_access")
  |> filter(fn: (r) => r["_field"] == "access_granted")
  |> filter(fn: (r) => r["access_status"] == "granted")
  |> group(columns: ["user"])
  |> count()
  |> sort(columns: ["_value"], desc: true)

📈 Accesos permitidos vs denegados (últimas 24h):
fluxfrom(bucket: "metro_system")
  |> range(start: -24h)
  |> filter(fn: (r) => r["_measurement"] == "metro_access")
  |> filter(fn: (r) => r["_field"] == "access_granted")
  |> group(columns: ["access_status"])
  |> count()

🕐 Accesos por hora del día (últimos 7 días):
fluxfrom(bucket: "metro_system")
  |> range(start: -7d)
  |> filter(fn: (r) => r["_measurement"] == "metro_access")
  |> filter(fn: (r) => r["_field"] == "access_granted")
  |> filter(fn: (r) => r["access_status"] == "granted")
  |> aggregateWindow(every: 1h, fn: count, createEmpty: false)
  |> yield(name: "hourly_access")

🚪 Estado de puertas en tiempo real:
fluxfrom(bucket: "metro_system")
  |> range(start: -1h)
  |> filter(fn: (r) => r["_measurement"] == "metro_door_status")
  |> filter(fn: (r) => r["_field"] == "is_open")
  |> last()

🔐 Historial de logins (últimos 7 días):
fluxfrom(bucket: "metro_system")
  |> range(start: -7d)
  |> filter(fn: (r) => r["_measurement"] == "metro_login")
  |> filter(fn: (r) => r["_field"] == "success")
  |> sort(columns: ["_time"], desc: true)

📊 Tendencia diaria de accesos (última semana):
fluxfrom(bucket: "metro_system")
  |> range(start: -7d)
  |> filter(fn: (r) => r["_measurement"] == "metro_access")
  |> filter(fn: (r) => r["_field"] == "access_granted")
  |> filter(fn: (r) => r["access_status"] == "granted")
  |> aggregateWindow(every: 1d, fn: count, createEmpty: false)
  |> yield(name: "daily_trend")

🎯 7. VERIFICAR DATOS EN EL DASHBOARD
En la interfaz web de InfluxDB:

Data Explorer → Selecciona bucket metro_system
Selecciona measurement: metro_access, metro_login, etc.
Selecciona fields: access_granted, access_id, etc.
Aplica filtros por tiempo y tags
Submit para visualizar

Ejemplo de visualización:

Gráfico de líneas: Accesos por hora
Gráfico circular: Porcentaje granted/denied
Tabla: Últimos 50 accesos con usuario y timestamp


🔄 8. CREAR DASHBOARDS PERSONALIZADOS
Dashboard recomendado: "Monitor Metro en Tiempo Real"
Paneles sugeridos:

Single Stat - Total accesos hoy
Single Stat - Personas dentro
Single Stat - Sesiones activas
Line Graph - Accesos por hora (últimas 24h)
Bar Chart - Top 10 usuarios con más accesos
Pie Chart - Accesos granted vs denied
Table - Últimos 20 accesos


⚙️ 9. CONFIGURACIÓN DE RETENCIÓN
Para evitar que la base de datos crezca indefinidamente:
bash# Desde la línea de comandos de InfluxDB CLI
influx bucket update \
  --id <bucket-id> \
  --retention 30d \
  --org metro_org
O desde la interfaz web:

Data → Buckets
Click en metro_system
Edit → Cambiar Retention Period a 30 days


🔐 10. SEGURIDAD Y BUENAS PRÁCTICAS
✅ Recomendaciones:

Cambiar contraseña por defecto del admin
Crear tokens específicos para cada aplicación (no usar All Access Token en producción)
Habilitar HTTPS si accedes desde fuera de la red local
Hacer backups periódicos del bucket:

bash   influx backup /path/to/backup -b metro_system

Monitorear el uso de disco de InfluxDB
Crear usuarios con permisos limitados para consultas de solo lectura


🛠️ 11. TROUBLESHOOTING
Problema: "Error conectando a InfluxDB"
Soluciones:
bash# Verificar que InfluxDB está corriendo
sudo systemctl status influxdb

# Reiniciar servicio
sudo systemctl restart influxdb

# Ver logs
sudo journalctl -u influxdb -f

# Verificar puerto 8086 abierto
sudo netstat -tuln | grep 8086

Problema: "Token inválido"
Soluciones:

Regenerar token en la interfaz web
Verificar que copiaste el token completo
Asegurarte de que el token tiene permisos de lectura/escritura en el bucket


Problema: "Bucket no encontrado"
Soluciones:
bash# Listar buckets existentes
influx bucket list --org metro_org

# Crear bucket si no existe
influx bucket create --name metro_system --org metro_org

📁 12. ESTRUCTURA DE ARCHIVOS
proyecto_metro/
├── app.py                    # Aplicación Flask principal
├── influxdb_handler.py       # Handler de InfluxDB ⬅️
├── templates/
│   ├── dashboard.html
│   └── login.html
├── requirements.txt
└── README.md
requirements.txt actualizado:
Flask==3.0.0
gpiozero==2.0.1
RPLCD==1.3.0
influxdb-client==1.38.0

✅ 13. CHECKLIST DE VERIFICACIÓN
Antes de iniciar tu aplicación, verifica:

 InfluxDB instalado y corriendo (sudo systemctl status influxdb)
 Interfaz web accesible en http://localhost:8086
 Organización metro_org creada
 Bucket metro_system creado
 Token de API generado y copiado
 Token pegado en INFLUXDB_CONFIG en el código
 Cliente Python instalado (pip install influxdb-client)
 Archivo influxdb_handler.py en la misma carpeta
 Aplicación Flask puede conectarse sin errores


🚀 14. INICIAR EL SISTEMA
bash# 1. Activar entorno virtual (si usas uno)
source venv/bin/activate

# 2. Verificar InfluxDB
sudo systemctl status influxdb

# 3. Iniciar aplicación Flask
python3 app.py
Salida esperada:
✓ InfluxDB inicializado correctamente
✓ Conectado a InfluxDB - Status: pass
✓ LCD inicializada correctamente

==================================================
🚇 SISTEMA CANCELADORA DE METRO INICIADO
==================================================
📱 Accede a la web desde: http://<IP_RASPBERRY>:8000
🔘 Botón configurado en GPIO 5
👥 Usuarios registrados: 3

⚠️  CREDENCIALES POR DEFECTO:
   Admin: admin / admin123
   Usuario1: usuario1 / pass123
   Usuario2: usuario2 / pass123
==================================================

 * Running on all addresses (0.0.0.0)
 * Running on http://127.0.0.1:8000

📞 15. SOPORTE Y RECURSOS

Documentación oficial InfluxDB 2.x: https://docs.influxdata.com/influxdb/v2/
Cliente Python InfluxDB: https://github.com/influxdata/influxdb-client-python
Flux Query Language: https://docs.influxdata.com/flux/v0/


🎓 NOTAS FINALES

Desarrollo vs Producción: En producción, usa HTTPS y tokens con permisos específicos
Escalabilidad: InfluxDB puede manejar millones de puntos de datos
Monitoreo: Considera crear alertas en InfluxDB para eventos críticos
Integración: Puedes conectar Grafana para dashboards más avanzados