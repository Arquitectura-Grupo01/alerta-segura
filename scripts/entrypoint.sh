#!/bin/sh
# Arranque en Render (Dev y Prod). En el plan Free no hay pre-deploy command,
# por eso las migraciones corren aquí, antes de levantar Gunicorn.
set -e

# manage.py usa dev por defecto (pensado para desarrollo local). En el servidor
# todo corre con prod salvo que el ambiente indique otra cosa.
export DJANGO_SETTINGS_MODULE="${DJANGO_SETTINGS_MODULE:-config.settings.prod}"

python manage.py migrate --noinput
# Crea la tabla de la caché compartida si CACHE_BACKEND=db. Es idempotente y no
# hace nada con otro backend.
python manage.py createcachetable

exec gunicorn config.wsgi:application \
    --bind "0.0.0.0:${PORT:-8000}" \
    --workers "${WEB_CONCURRENCY:-2}" \
    --timeout 30 \
    --access-logfile - \
    --error-logfile -