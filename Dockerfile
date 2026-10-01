# syntax=docker/dockerfile:1
# ---------- Etapa 1: compilar dependencias ----------
FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /build
COPY requirements.txt .
RUN pip wheel --wheel-dir /wheels -r requirements.txt

# ---------- Etapa 2: imagen final, sin herramientas de compilación ----------
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Parches de seguridad del sistema operativo. La imagen oficial de Python va
# días detrás de los parches de Debian; esto los aplica en cada build.
# Detectado por Trivy: CVE-2026-75804 y CVE-2026-84782 (OpenSSL).
RUN apt-get update \
    && apt-get upgrade -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

# Dependencias del sistema para RF-02 y RF-04. Descomentar al implementarlas:
# cada paquete instalado es superficie que Trivy va a escanear.
# RUN apt-get update \
#  && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-spa libzbar0 \
#  && rm -rf /var/lib/apt/lists/*

# Usuario sin privilegios: si alguien explota la app, no es root en el contenedor.
RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --no-create-home app

WORKDIR /app
COPY --from=builder /wheels /wheels
RUN pip install --no-index --find-links=/wheels /wheels/* && rm -rf /wheels

COPY --chown=app:app . .

# collectstatic necesita settings cargables; la clave de build es desechable
# y solo existe durante este RUN, no queda en la imagen.
RUN DJANGO_SETTINGS_MODULE=config.settings.prod \
    DJANGO_SECRET_KEY=build-only-not-a-secret \
    DATABASE_URL=sqlite:////tmp/build.db \
    python manage.py collectstatic --noinput \
    && chmod +x scripts/entrypoint.sh \
    && chown -R app:app /app/staticfiles

USER app
EXPOSE 8000
CMD ["./scripts/entrypoint.sh"]