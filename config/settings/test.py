from .base import *  # noqa: F401,F403

DEBUG = False
ALLOWED_HOSTS = ["testserver"]
# solo tests: acelera
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
CELERY_TASK_ALWAYS_EAGER = True
# Los tests no dependen de Redis ni de una tabla de caché: cada proceso usa la suya.
CACHES = {
    "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"},
    "tecnica": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "tecnica",
    },
    "resultados": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "resultados",
    },
}
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}
