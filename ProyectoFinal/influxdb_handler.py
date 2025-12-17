"""
Módulo para manejar la conexión y almacenamiento de datos en InfluxDB
Sistema de Canceladora de Metro - Raspberry Pi 5
Adaptado para registrar accesos con autenticación de usuarios
"""

from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS
from datetime import datetime
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class InfluxDBHandler:
    """Maneja la conexión y operaciones con InfluxDB para el sistema de canceladora"""
    
    def __init__(self, url="http://localhost:8086", token="your_token", org="your_org", bucket="metro_system"):
        """
        Inicializa la conexión a InfluxDB
        
        Args:
            url: URL del servidor InfluxDB (ej: http://localhost:8086)
            token: Token de autenticación
            org: Organización en InfluxDB
            bucket: Bucket donde se almacenarán los datos
        """
        self.url = url
        self.token = token
        self.org = org
        self.bucket = bucket
        self.client = None
        self.write_api = None
        
        self.connect()
    
    def connect(self):
        """Establece conexión con InfluxDB"""
        try:
            self.client = InfluxDBClient(
                url=self.url,
                token=self.token,
                org=self.org
            )
            self.write_api = self.client.write_api(write_options=SYNCHRONOUS)
            
            # Verificar conexión
            health = self.client.health()
            logger.info(f"✓ Conectado a InfluxDB - Status: {health.status}")
            return True
        except Exception as e:
            logger.error(f"✗ Error conectando a InfluxDB: {e}")
            logger.warning("⚠ El sistema continuará sin almacenamiento en InfluxDB")
            return False
    
    def write_access_event(self, card_id, user_name, access_granted, door_id="canceladora_1"):
        """
        Registra un evento de acceso en la canceladora
        
        Args:
            card_id: ID del acceso (número de acceso)
            user_name: Nombre del usuario autenticado
            access_granted: True si acceso permitido, False si denegado
            door_id: ID de la canceladora
        """
        if not self.client:
            logger.warning("Cliente InfluxDB no conectado. Evento no registrado.")
            return False
        
        try:
            point = Point("metro_access") \
                .tag("door", door_id) \
                .tag("user", user_name) \
                .tag("access_status", "granted" if access_granted else "denied") \
                .field("access_id", int(card_id)) \
                .field("access_granted", access_granted) \
                .time(datetime.utcnow())
            
            self.write_api.write(bucket=self.bucket, record=point)
            logger.info(f"✓ Evento registrado: {user_name} - Acceso #{card_id} - {'Permitido' if access_granted else 'Denegado'}")
            return True
        except Exception as e:
            logger.error(f"✗ Error escribiendo evento de acceso: {e}")
            return False
    
    def write_login_event(self, username, user_name, role, success=True):
        """
        Registra un evento de login en el sistema
        
        Args:
            username: Username del usuario
            user_name: Nombre completo del usuario
            role: Rol del usuario (admin/usuario)
            success: Si el login fue exitoso
        """
        if not self.client:
            return False
        
        try:
            point = Point("metro_login") \
                .tag("username", username) \
                .tag("role", role) \
                .tag("status", "success" if success else "failed") \
                .field("user_name", user_name) \
                .field("success", success) \
                .time(datetime.utcnow())
            
            self.write_api.write(bucket=self.bucket, record=point)
            logger.info(f"✓ Login registrado: {username} ({user_name}) - {'Exitoso' if success else 'Fallido'}")
            return True
        except Exception as e:
            logger.error(f"✗ Error escribiendo evento de login: {e}")
            return False
    
    def write_system_status(self, active_sessions, total_access_today, people_inside, button_enabled):
        """
        Registra el estado actual del sistema
        
        Args:
            active_sessions: Número de sesiones activas
            total_access_today: Total de accesos del día
            people_inside: Personas actualmente dentro
            button_enabled: Si el botón está habilitado
        """
        if not self.client:
            return False
        
        try:
            point = Point("metro_system_status") \
                .tag("status", "active" if button_enabled else "waiting") \
                .field("active_sessions", active_sessions) \
                .field("total_access_today", total_access_today) \
                .field("people_inside", people_inside) \
                .field("button_enabled", button_enabled) \
                .time(datetime.utcnow())
            
            self.write_api.write(bucket=self.bucket, record=point)
            return True
        except Exception as e:
            logger.error(f"✗ Error escribiendo estado del sistema: {e}")
            return False
    
    def write_door_status(self, door_status, detecting_crossing, lasers_status):
        """
        Registra el estado de las puertas y sensores
        
        Args:
            door_status: Estado de la puerta (ABIERTA/CERRADA)
            detecting_crossing: Si está detectando el cruce de una persona
            lasers_status: Dict con estado de los láseres {'laser_a': bool, 'laser_b': bool}
        """
        if not self.client:
            return False
        
        try:
            point = Point("metro_door_status") \
                .tag("door_status", door_status) \
                .field("is_open", door_status == "ABIERTA") \
                .field("detecting_crossing", detecting_crossing) \
                .field("laser_a_active", lasers_status.get('laser_a', False)) \
                .field("laser_b_active", lasers_status.get('laser_b', False)) \
                .time(datetime.utcnow())
            
            self.write_api.write(bucket=self.bucket, record=point)
            return True
        except Exception as e:
            logger.error(f"✗ Error escribiendo estado de puerta: {e}")
            return False
    
    def get_recent_access(self, minutes=60):
        """
        Obtiene los accesos recientes
        
        Args:
            minutes: Minutos hacia atrás para consultar
            
        Returns:
            Lista de accesos recientes
        """
        if not self.client:
            logger.warning("Cliente InfluxDB no conectado")
            return []
        
        try:
            query_api = self.client.query_api()
            query = f'''
            from(bucket: "{self.bucket}")
                |> range(start: -{minutes}m)
                |> filter(fn: (r) => r["_measurement"] == "metro_access")
                |> filter(fn: (r) => r["_field"] == "access_granted" or r["_field"] == "access_id")
                |> pivot(rowKey:["_time"], columnKey: ["_field"], valueColumn: "_value")
                |> sort(columns: ["_time"], desc: true)
                |> limit(n: 100)
            '''
            
            result = query_api.query(org=self.org, query=query)
            
            accesses = []
            for table in result:
                for record in table.records:
                    accesses.append({
                        'time': record.get_time(),
                        'user': record.values.get('user'),
                        'door': record.values.get('door'),
                        'access_granted': record.values.get('access_granted'),
                        'card_id': record.values.get('access_id'),
                        'access_status': record.values.get('access_status')
                    })
            
            logger.info(f"✓ Obtenidos {len(accesses)} accesos recientes")
            return accesses
        except Exception as e:
            logger.error(f"✗ Error obteniendo accesos recientes: {e}")
            return []
    
    def get_access_statistics(self, hours=24):
        """
        Obtiene estadísticas de acceso
        
        Args:
            hours: Horas hacia atrás para analizar
            
        Returns:
            Diccionario con estadísticas
        """
        if not self.client:
            logger.warning("Cliente InfluxDB no conectado")
            return {}
        
        try:
            query_api = self.client.query_api()
            
            # Query para contar accesos totales
            query = f'''
            from(bucket: "{self.bucket}")
                |> range(start: -{hours}h)
                |> filter(fn: (r) => r["_measurement"] == "metro_access")
                |> filter(fn: (r) => r["_field"] == "access_granted")
                |> count()
            '''
            
            result = query_api.query(org=self.org, query=query)
            
            total = 0
            granted = 0
            denied = 0
            
            for table in result:
                for record in table.records:
                    count = record.get_value()
                    status = record.values.get('access_status')
                    
                    if status == 'granted':
                        granted += count
                    elif status == 'denied':
                        denied += count
                    total += count
            
            stats = {
                'total': total,
                'granted': granted,
                'denied': denied,
                'grant_percentage': round((granted / total * 100) if total > 0 else 0, 2)
            }
            
            logger.info(f"✓ Estadísticas obtenidas: {stats}")
            return stats
            
        except Exception as e:
            logger.error(f"✗ Error obteniendo estadísticas: {e}")
            return {
                'total': 0,
                'granted': 0,
                'denied': 0,
                'grant_percentage': 0
            }
    
    def get_user_access_history(self, user_name, hours=168):
        """
        Obtiene el historial de accesos de un usuario específico
        
        Args:
            user_name: Nombre del usuario
            hours: Horas hacia atrás (default: 1 semana)
            
        Returns:
            Lista con el historial de accesos
        """
        if not self.client:
            return []
        
        try:
            query_api = self.client.query_api()
            query = f'''
            from(bucket: "{self.bucket}")
                |> range(start: -{hours}h)
                |> filter(fn: (r) => r["_measurement"] == "metro_access")
                |> filter(fn: (r) => r["user"] == "{user_name}")
                |> filter(fn: (r) => r["_field"] == "access_id")
                |> sort(columns: ["_time"], desc: true)
            '''
            
            result = query_api.query(org=self.org, query=query)
            
            history = []
            for table in result:
                for record in table.records:
                    history.append({
                        'timestamp': record.get_time(),
                        'access_id': record.get_value(),
                        'door': record.values.get('door')
                    })
            
            return history
        except Exception as e:
            logger.error(f"✗ Error obteniendo historial de usuario: {e}")
            return []
    
    def get_daily_access_trend(self, days=7):
        """
        Obtiene la tendencia de accesos por día
        
        Args:
            days: Número de días a analizar
            
        Returns:
            Dict con datos de tendencia por día
        """
        if not self.client:
            return {}
        
        try:
            query_api = self.client.query_api()
            query = f'''
            from(bucket: "{self.bucket}")
                |> range(start: -{days}d)
                |> filter(fn: (r) => r["_measurement"] == "metro_access")
                |> filter(fn: (r) => r["_field"] == "access_granted")
                |> filter(fn: (r) => r["access_status"] == "granted")
                |> aggregateWindow(every: 1d, fn: count, createEmpty: false)
                |> yield(name: "daily_count")
            '''
            
            result = query_api.query(org=self.org, query=query)
            
            trend_data = []
            for table in result:
                for record in table.records:
                    trend_data.append({
                        'date': record.get_time().strftime('%Y-%m-%d'),
                        'count': record.get_value()
                    })
            
            return {'trend': trend_data}
        except Exception as e:
            logger.error(f"✗ Error obteniendo tendencia diaria: {e}")
            return {}
    
    def close(self):
        """Cierra la conexión con InfluxDB"""
        if self.client:
            self.client.close()
            logger.info("✓ Conexión a InfluxDB cerrada")