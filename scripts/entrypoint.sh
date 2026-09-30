#!/bin/sh
# Arranque en Render (Dev y Prod). En el plan Free no hay pre-deploy command,
# por eso las migraciones corren aquí, antes de levantar Gunicorn.
set -e

python manage.py migrate --noinput

exec gunicorn config.wsgi:application \
    --bind "0.0.0.0:${PORT:-8000}" \
    --workers "${WEB_CONCURRENCY:-2}" \
    --timeout 30 \
    --access-logfile - \
    --error-logfile -