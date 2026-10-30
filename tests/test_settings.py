import os
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _python(codigo, **variables):
    entorno = {k: v for k, v in os.environ.items() if k != "DJANGO_SETTINGS_MODULE"}
    entorno.update(DJANGO_SECRET_KEY="solo-test-no-es-secreto", **variables)
    resultado = subprocess.run(
        [sys.executable, "-c", codigo],
        cwd=BASE_DIR, env=entorno, capture_output=True, text=True, timeout=60,
    )
    assert resultado.returncode == 0, resultado.stderr
    return resultado.stdout.strip()


def test_wsgi_usa_prod_si_falta_la_variable():
    salida = _python(
        "import config.wsgi; from django.conf import settings; "
        "print(settings.SETTINGS_MODULE, settings.DEBUG)",
        DATABASE_URL="sqlite://:memory:",
    )
    assert salida == "config.settings.prod False"


def test_prod_exige_tls_hacia_postgres():
    salida = _python(
        "from config.settings import prod; print(prod.DATABASES['default']['OPTIONS'])",
        DATABASE_URL="postgres://u:p@db.example:5432/alerta",
    )
    assert "'sslmode': 'require'" in salida


def test_prod_respeta_un_sslmode_mas_estricto():
    salida = _python(
        "from config.settings import prod; print(prod.DATABASES['default']['OPTIONS'])",
        DATABASE_URL="postgres://u:p@db.example:5432/alerta?sslmode=verify-full",
    )
    assert "'sslmode': 'verify-full'" in salida
