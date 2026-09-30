"""Configuración para los servidores Dev y Prod en Render.

Ambos usan este archivo: lo que cambia entre ellos son las variables de entorno,
no el código. Así lo que se prueba en Dev es exactamente lo que llega a Prod.
"""
from .base import *  # noqa: F401,F403
from .base import env

DEBUG = False

# Render termina TLS en su proxy y reenvía por HTTP con este header.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = True
# El health check interno de Render no debe recibir un 301.
SECURE_REDIRECT_EXEMPT = [r"^health/$"]

SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
CSRF_TRUSTED_ORIGINS = env.list("DJANGO_CSRF_TRUSTED_ORIGINS", default=[])

SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"

# HSTS: empezar bajo y subir cuando todo esté estable.
SECURE_HSTS_SECONDS = env.int("DJANGO_HSTS_SECONDS", default=3600)
# NO activar includeSubDomains ni preload: el dominio es *.onrender.com, que
# es compartido y no nos pertenece. Se silencian las advertencias con motivo.
SECURE_HSTS_INCLUDE_SUBDOMAINS = False
SECURE_HSTS_PRELOAD = False
SILENCED_SYSTEM_CHECKS = [
    "security.W005",  # includeSubDomains: dominio compartido de Render
    "security.W021",  # preload: dominio compartido de Render
]
