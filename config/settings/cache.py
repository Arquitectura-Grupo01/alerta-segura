"""Caché compartida entre los procesos de la aplicación.

Django usa LocMemCache si no se configura nada, y esa caché vive dentro de cada
proceso: con varios workers de Gunicorn cada uno vería la suya y el rate limit
o la caché de resultados fallarían sin avisar. Aquí el almacén es siempre externo
al proceso: Redis en local y una tabla de PostgreSQL en Render, que no tiene Redis.
"""
from django.core.exceptions import ImproperlyConfigured

TABLA_CACHE = "cache_alerta"
# La caché técnica guarda las respuestas crudas de las fuentes externas. Va aparte de
# "default": al pasar su tope, la tabla borra filas, y miles de respuestas no deben
# llevarse los contadores del rate limit.
TABLA_CACHE_TECNICA = "cache_tecnica"
# Los resultados de los análisis también van aparte, por el mismo motivo.
TABLA_CACHE_RESULTADOS = "cache_resultados"
# Tope de filas de la tabla en Neon. Al superarlo, Django borra 1 de cada
# CULL_FREQUENCY entradas (aquí la tercera parte), así que la tabla no crece sin límite.
MAX_ENTRIES = 5000
CULL_FREQUENCY = 3


def construir_caches(backend, redis_url):
    """Devuelve el CACHES de Django para el backend pedido: "redis" o "db"."""
    if backend == "db":
        opciones = {"MAX_ENTRIES": MAX_ENTRIES, "CULL_FREQUENCY": CULL_FREQUENCY}
        return {
            "default": {
                "BACKEND": "django.core.cache.backends.db.DatabaseCache",
                "LOCATION": TABLA_CACHE,
                "OPTIONS": opciones,
            },
            "tecnica": {
                "BACKEND": "django.core.cache.backends.db.DatabaseCache",
                "LOCATION": TABLA_CACHE_TECNICA,
                "OPTIONS": opciones,
            },
            "resultados": {
                "BACKEND": "django.core.cache.backends.db.DatabaseCache",
                "LOCATION": TABLA_CACHE_RESULTADOS,
                "OPTIONS": opciones,
            },
        }
    if backend == "redis":
        return {
            "default": {
                "BACKEND": "django.core.cache.backends.redis.RedisCache",
                "LOCATION": redis_url,
            },
            "tecnica": {
                "BACKEND": "django.core.cache.backends.redis.RedisCache",
                "LOCATION": redis_url,
                "KEY_PREFIX": "tecnica",
            },
            "resultados": {
                "BACKEND": "django.core.cache.backends.redis.RedisCache",
                "LOCATION": redis_url,
                "KEY_PREFIX": "resultados",
            },
        }
    raise ImproperlyConfigured(f"CACHE_BACKEND debe ser 'redis' o 'db', no {backend!r}")
