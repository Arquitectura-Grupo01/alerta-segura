import pytest
from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import ImproperlyConfigured
from django.core.management import call_command
from django.db import connection
from django.test import override_settings

from config.settings.cache import (
    CULL_FREQUENCY,
    MAX_ENTRIES,
    TABLA_CACHE,
    construir_caches,
)


def test_la_cache_de_los_tests_escribe_y_lee():
    cache.set("clave", {"nivel": "alto"}, 30)
    assert cache.get("clave") == {"nivel": "alto"}
    cache.delete("clave")
    assert cache.get("clave") is None


def test_los_tests_usan_locmem():
    assert settings.CACHES["default"]["BACKEND"].endswith("locmem.LocMemCache")


def test_db_apunta_a_la_tabla_con_tope_de_filas():
    config = construir_caches("db", "redis://ignorada:6379/1")["default"]
    assert config["BACKEND"] == "django.core.cache.backends.db.DatabaseCache"
    assert config["LOCATION"] == TABLA_CACHE
    assert config["OPTIONS"] == {"MAX_ENTRIES": MAX_ENTRIES, "CULL_FREQUENCY": CULL_FREQUENCY}


def test_redis_usa_la_url_recibida():
    config = construir_caches("redis", "redis://redis:6379/1")["default"]
    assert config["BACKEND"] == "django.core.cache.backends.redis.RedisCache"
    assert config["LOCATION"] == "redis://redis:6379/1"


def test_un_backend_desconocido_falla_al_arrancar():
    with pytest.raises(ImproperlyConfigured):
        construir_caches("memcached", "redis://redis:6379/1")


@pytest.mark.django_db
def test_la_cache_en_tabla_escribe_y_lee_despues_de_crearla():
    with override_settings(CACHES=construir_caches("db", "")):
        call_command("createcachetable", verbosity=0)
        # Una segunda ejecución no falla: el entrypoint la corre en cada arranque.
        call_command("createcachetable", verbosity=0)
        cache.set("resultado", "ok", 30)
        assert cache.get("resultado") == "ok"


@pytest.mark.django_db
def test_la_tabla_no_crece_mas_alla_del_tope():
    caches = construir_caches("db", "")
    caches["default"]["OPTIONS"] = {"MAX_ENTRIES": 10, "CULL_FREQUENCY": 2}
    with override_settings(CACHES=caches):
        call_command("createcachetable", verbosity=0)
        for i in range(40):
            cache.set(f"k{i}", i, 300)
        with connection.cursor() as cursor:
            cursor.execute(f"SELECT COUNT(*) FROM {TABLA_CACHE}")  # noqa: S608
            filas = cursor.fetchone()[0]
    assert filas <= 10
