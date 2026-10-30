import os

from celery import Celery

# config/__init__.py importa este módulo antes que wsgi.py. Con "dev" aquí,
# Gunicorn arrancaba con DEBUG=True si faltaba la variable. Solo manage.py usa
# dev por defecto; todo lo que corre en un servidor usa prod.
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.prod")

app = Celery("alerta_segura")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
