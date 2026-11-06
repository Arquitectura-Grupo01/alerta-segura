"""Caché compartida entre los procesos de la aplicación.

Django usa LocMemCache si no se configura nada, y esa caché vive dentro de cada
proceso: con varios workers de Gunicorn cada uno vería la suya y el rate limit
o la caché de resultados fallarían sin avisar. Aquí el almacén es siempre externo
al proceso: Redis en local y una tabla de PostgreSQL en Render, que no tiene Redis.
"""
from django.core.exceptions import ImproperlyConfigured

TABLA_CACHE = "cache_alerta"
# Tope de filas de la tabla en Neon. Al superarlo, Django borra 1 de cada
# CULL_FREQUENCY entradas (aquí la tercera parte), así que la tabla no crece sin límite.
MAX_ENTRIES = 5000
CULL_FREQUENCY = 3


def construir_caches(backend, redis_url):
    """Devuelve el CACHES de Django para el backend pedido: "redis" o "db"."""
    if backend == "db":
        return {
            "default": {
                "BACKEND": "django.core.cache.backends.db.DatabaseCache",
                "LOCATION": TABLA_CACHE,
                "OPTIONS": {"MAX_ENTRIES": MAX_ENTRIES, "CULL_FREQUENCY": CULL_FREQUENCY},
            }
        }
    if backend == "redis":
        return {
            "default": {
                "BACKEND": "django.core.cache.backends.redis.RedisCache",
                "LOCATION": redis_url,
            }
        }
    raise ImproperlyConfigured(f"CACHE_BACKEND debe ser 'redis' o 'db', no {backend!r}")
