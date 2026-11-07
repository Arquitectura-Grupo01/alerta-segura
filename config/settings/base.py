"""Configuración común a todos los ambientes de Alerta Segura.

Regla: ningún secreto ni valor que cambie entre ambientes vive en este archivo.
Todo se lee de variables de entorno: ningún secreto va en el repositorio.
Los controles de seguridad (DEBUG, CSP, política de salida en core/net.py) no
son configuración: valen igual en todos los ambientes y no se leen del entorno.
"""
import os
from pathlib import Path

import environ
from django.core.exceptions import ImproperlyConfigured

from .cache import construir_caches

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env()
# En local se lee .env si existe. En Render las variables vienen del panel.
env_file = BASE_DIR / ".env"
if env_file.exists():
    environ.Env.read_env(env_file)

# django-environ toma un valor que empieza con "$" como el nombre de otra variable,
# y una clave aleatoria puede empezar así. La clave se lee tal cual del entorno.
try:
    SECRET_KEY = os.environ["DJANGO_SECRET_KEY"]
except KeyError:
    raise ImproperlyConfigured("Falta la variable de entorno DJANGO_SECRET_KEY") from None
# Solo dev.py lo activa. No se lee del entorno para que ningún despliegue
# pueda quedar con DEBUG=True por una variable mal cargada.
DEBUG = False
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=[])
APP_ENV = env("APP_ENV", default="local")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "core",
    "analisis",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "core.middleware.CabecerasSeguridadMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

DATABASES = {"default": env.db("DATABASE_URL")}
DATABASES["default"]["CONN_MAX_AGE"] = env.int("DB_CONN_MAX_AGE", default=60)

# Caché compartida entre procesos (ver config/settings/cache.py). "db" es el valor
# por defecto porque funciona donde haya PostgreSQL, como en Render, y la tabla la
# crea scripts/entrypoint.sh. En local .env.example pide "redis". Redis usa la base
# 1 y no la 0 del broker de Celery: cache.clear() hace FLUSHDB y vaciaría la cola.
CACHE_BACKEND = env("CACHE_BACKEND", default="db")
CACHES = construir_caches(CACHE_BACKEND, env("REDIS_CACHE_URL", default="redis://localhost:6379/1"))

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
     "OPTIONS": {"min_length": 12}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "es-pe"
TIME_ZONE = "America/Lima"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
# CSS, JS, fuentes e imágenes propios de la interfaz. collectstatic los copia a
# STATIC_ROOT y Whitenoise los sirve con el nombre versionado por su hash.
STATICFILES_DIRS = [BASE_DIR / "static"]
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Ruta del admin configurable: /admin/ recibe escaneo automatizado constante.
ADMIN_PATH = env("DJANGO_ADMIN_PATH", default="admin/")

# Content-Security-Policy: solo recursos propios y nada en línea. Si un texto de
# un ciudadano llegara sin escapar a una página, el navegador no lo ejecutaría.
# Django 5.2 no la trae; la agrega core.middleware.
CONTENT_SECURITY_POLICY = (
    "default-src 'self'; object-src 'none'; base-uri 'self'; "
    "form-action 'self'; frame-ancestors 'none'"
)
CONTENT_SECURITY_POLICY_REPORT_ONLY = False

# La cookie de CSRF no la lee ningún JavaScript propio: el token viaja en el
# formulario. HttpOnly evita que un script inyectado la robe. Control fijo.
CSRF_COOKIE_HTTPONLY = True

# WhiteNoise manda Access-Control-Allow-Origin: * en los estáticos, pensado para
# servirlos desde una CDN. Aquí salen del mismo origen y ninguna página de otro
# sitio debe leerlos: ZAP lo marca como mala configuración entre dominios (10098).
WHITENOISE_ALLOW_ALL_ORIGINS = False

# --- Celery -----------------------------------------------------------------
# En Render Free no existen background workers. CELERY_EAGER=True ejecuta las
# tareas dentro del proceso web (degradación documentada, ver guía paso 07).
CELERY_BROKER_URL = env("REDIS_URL", default="redis://localhost:6379/0")
CELERY_TASK_ALWAYS_EAGER = env.bool("CELERY_EAGER", default=False)
CELERY_TASK_EAGER_PROPAGATES = True
CELERY_TASK_TIME_LIMIT = 30

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    # Todo mensaje pasa por el enmascarado antes de escribirse (core/enmascarado.py).
    "filters": {"enmascarar": {"()": "core.enmascarado.FiltroEnmascarado"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "filters": ["enmascarar"]}},
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", default="INFO")},
    # httpx registra en INFO cada petición con su ruta y sus parámetros completos, que
    # son lo que el ciudadano mandó a analizar. Solo avisos y errores.
    "loggers": {
        "httpx": {"level": "WARNING"},
        "httpcore": {"level": "WARNING"},
    },
}
