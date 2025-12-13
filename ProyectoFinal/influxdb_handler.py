"""
Módulo para manejar la conexión y almacenamiento de datos en InfluxDB
"""

from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS
from datetime import datetime
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class InfluxDBHandler:
    """Maneja la conexión y operaciones con InfluxDB"""
    
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
            self.write_api = self.client.write_api(write_type=SYNCHRONOUS)
            
            # Verificar conexión
            health = self.client.health()
            logger.info(f"✓ Conectado a InfluxDB: {health}")
            return True
        except Exception as e:
            logger.error(f"✗ Error conectando a InfluxDB: {e}")
            return False
    
    def write_access_event(self, card_id, user_name, access_granted, door_id="door_1"):
        """
        Registra un evento de acceso
        
        Args:
            card_id: ID de la tarjeta RFID
            user_name: Nombre del usuario
            access_granted: True si acceso permitido, False si denegado
            door_id: ID de la puerta/canceladora
        """
        try:
            point = Point("metro_access") \
                .tag("door", door_id) \
                .tag("user", user_name) \
                .field("card_id", card_id) \
                .field("access_granted", access_granted) \
                .time(datetime.utcnow())
            
            self.write_api.write(bucket=self.bucket, record=point)
            logger.info(f"✓ Evento registrado: {user_name} - {'Permitido' if access_granted else 'Denegado'}")
            return True
        except Exception as e:
            logger.error(f"✗ Error escribiendo evento de acceso: {e}")
            return False
    
    def write_system_status(self, status, active_users, total_access, total_rejected):
        """
        Registra el estado del sistema
        
        Args:
            status: Estado del sistema ('active', 'inactive', etc)
            active_users: Número de usuarios activos
            total_access: Total de accesos permitidos
            total_rejected: Total de accesos denegados
        """
        try:
            point = Point("metro_system_status") \
                .tag("status", status) \
                .field("active_users", active_users) \
                .field("total_access", total_access) \
                .field("total_rejected", total_rejected) \
                .time(datetime.utcnow())
            
            self.write_api.write(bucket=self.bucket, record=point)
            return True
        except Exception as e:
            logger.error(f"✗ Error escribiendo estado del sistema: {e}")
            return False
    
    def get_recent_access(self, minutes=60):
        """
        Obtiene los accesos recientes
        
        Args:
            minutes: Minutos hacia atrás para consultar
            
        Returns:
            Lista de accesos recientes
        """
        try:
            query_api = self.client.query_api()
            query = f'''
            from(bucket: "{self.bucket}")
                |> range(start: -{minutes}m)
                |> filter(fn: (r) => r["_measurement"] == "metro_access")
                |> sort(columns: ["_time"], desc: true)
                |> limit(n: 100)
            '''
            
            result = query_api.query(org=self.org, query=query)
            
            accesses = []
            for table in result:
                for record in table.records:
                    accesses.append({
                        'time': record.get_time(),
                        'user': record.tags.get('user'),
                        'door': record.tags.get('door'),
                        'access_granted': record.values.get('access_granted'),
                        'card_id': record.values.get('card_id')
                    })
            
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
        try:
            query_api = self.client.query_api()
            query = f'''
            from(bucket: "{self.bucket}")
                |> range(start: -{hours}h)
                |> filter(fn: (r) => r["_measurement"] == "metro_access")
            '''
            
            result = query_api.query(org=self.org, query=query)
            
            total = 0
            granted = 0
            denied = 0
            
            for table in result:
                for record in table.records:
                    total += 1
                    if record.values.get('access_granted'):
                        granted += 1
                    else:
                        denied += 1
            
            return {
                'total': total,
                'granted': granted,
                'denied': denied,
                'grant_percentage': (granted / total * 100) if total > 0 else 0
            }
        except Exception as e:
            logger.error(f"✗ Error obteniendo estadísticas: {e}")
            return {}
    
    def close(self):
        """Cierra la conexión con InfluxDB"""
        if self.client:
            self.client.close()
            logger.info("✓ Conexión a InfluxDB cerrada")
