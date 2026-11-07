import os
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _python(codigo, **variables):
    entorno = {k: v for k, v in os.environ.items() if k != "DJANGO_SETTINGS_MODULE"}
    entorno.update({"DJANGO_SECRET_KEY": "solo-test-no-es-secreto", **variables})
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


def test_acepta_una_clave_que_empieza_con_dolar():
    # get_random_secret_key() puede generar una clave que empieza con "$".
    clave = "$clave-de-prueba-que-empieza-con-dolar"
    salida = _python(
        "from django.conf import settings; print(settings.SECRET_KEY)",
        DJANGO_SETTINGS_MODULE="config.settings.prod",
        DJANGO_SECRET_KEY=clave,
        DATABASE_URL="sqlite://:memory:",
    )
    assert salida == clave


def test_prod_confia_en_dos_proxies_y_los_demas_ambientes_en_ninguno():
    salida = _python(
        "from config.settings import base, prod, dev, test; "
        "print(prod.ENTRADA_PROXIES_CONFIABLES, base.ENTRADA_PROXIES_CONFIABLES, "
        "dev.ENTRADA_PROXIES_CONFIABLES, test.ENTRADA_PROXIES_CONFIABLES)",
        DATABASE_URL="sqlite://:memory:",
    )
    assert salida == "2 0 0 0"


def test_prod_exige_tls_hacia_postgres():
    salida = _python(
        "from config.settings import prod; print(prod.DATABASES['default']['OPTIONS'])",
        DATABASE_URL="postgres://u:p@db.example:5432/alerta",
    )
    assert "'sslmode': 'require'" in salida


def test_sin_cache_backend_se_usa_la_tabla_de_postgres():
    salida = _python(
        "from config.settings import prod; print(prod.CACHES['default']['BACKEND'])",
        DATABASE_URL="sqlite://:memory:",
    )
    assert salida.endswith("db.DatabaseCache")


def test_cache_backend_redis_usa_redis_cache_url():
    salida = _python(
        "from config.settings import prod; print(prod.CACHES['default']['LOCATION'])",
        CACHE_BACKEND="redis",
        REDIS_CACHE_URL="redis://redis:6379/1",
        DATABASE_URL="sqlite://:memory:",
    )
    assert salida == "redis://redis:6379/1"


def test_cache_backend_invalido_impide_arrancar():
    resultado = subprocess.run(
        [sys.executable, "-c", "from config.settings import prod"],
        cwd=BASE_DIR, capture_output=True, text=True, timeout=60,
        env={**os.environ, "DJANGO_SECRET_KEY": "solo-test", "CACHE_BACKEND": "memcached",
             "DATABASE_URL": "sqlite://:memory:"},
    )
    assert resultado.returncode != 0
    assert "CACHE_BACKEND" in resultado.stderr


def test_prod_respeta_un_sslmode_mas_estricto():
    salida = _python(
        "from config.settings import prod; print(prod.DATABASES['default']['OPTIONS'])",
        DATABASE_URL="postgres://u:p@db.example:5432/alerta?sslmode=verify-full",
    )
    assert "'sslmode': 'verify-full'" in salida
