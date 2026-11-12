import ipaddress
import time
from datetime import timedelta
from unittest import mock

import pytest
from django.core.cache import cache
from django.core.cache.backends import db as cache_db
from django.core.management import call_command
from django.http import HttpResponse
from django.test import RequestFactory
from django.urls import reverse

from analisis import orquestador as vistas_analisis
from config.settings.cache import construir_caches
from core import entrada, net
from core.entrada import (
    ANALISIS,
    CONSULTAS_EXTERNAS_POR_HORA,
    MAX_BYTES_CUERPO,
    REPORTES,
    Politica,
    clave_de_ip,
    consumir_presupuesto_externo,
    ip_del_cliente,
    limitar,
)

# Un análisis que pasa el límite se guarda en la base.
pytestmark = pytest.mark.django_db

IP_A = "203.0.113.9"
IP_B = "198.51.100.7"


def peticion(**meta):
    return RequestFactory().get("/", **meta)


def analizar(client, ip=IP_A, enlace="https://ejemplo.invalid/a"):
    return client.post(reverse("analizar"), {"enlace": enlace}, REMOTE_ADDR=ip)


# --- IP del cliente ---------------------------------------------------------

def test_sin_proxies_confiables_se_ignora_x_forwarded_for(settings):
    settings.ENTRADA_PROXIES_CONFIABLES = 0
    meta = {"REMOTE_ADDR": "10.0.0.1", "HTTP_X_FORWARDED_FOR": "6.6.6.6"}
    assert ip_del_cliente(peticion(**meta)) == "10.0.0.1"


def test_toma_la_entrada_que_agrego_el_proxy_y_no_la_primera(settings):
    settings.ENTRADA_PROXIES_CONFIABLES = 2
    # [lo que escribió el cliente, IP del cliente, IP del proxy de borde]
    meta = {"REMOTE_ADDR": "10.0.0.1", "HTTP_X_FORWARDED_FOR": "6.6.6.6, 203.0.113.5, 172.64.0.1"}
    assert ip_del_cliente(peticion(**meta)) == "203.0.113.5"


def test_el_cliente_no_elige_su_ip_agregando_entradas(settings):
    settings.ENTRADA_PROXIES_CONFIABLES = 2
    falsas = "1.1.1.1, 2.2.2.2, 3.3.3.3, 203.0.113.5, 172.64.0.1"
    meta = {"REMOTE_ADDR": "10.0.0.1", "HTTP_X_FORWARDED_FOR": falsas}
    assert ip_del_cliente(peticion(**meta)) == "203.0.113.5"


def test_con_menos_entradas_de_las_esperadas_usa_la_mas_antigua(settings):
    settings.ENTRADA_PROXIES_CONFIABLES = 2
    meta = {"REMOTE_ADDR": "10.0.0.1", "HTTP_X_FORWARDED_FOR": "203.0.113.5"}
    assert ip_del_cliente(peticion(**meta)) == "203.0.113.5"


@pytest.mark.parametrize("cabecera", ["", " , ", "no-es-una-ip, tampoco", "203.0.113.5:8080"])
def test_sin_x_forwarded_for_valido_usa_la_ip_de_la_conexion(settings, cabecera):
    settings.ENTRADA_PROXIES_CONFIABLES = 1
    meta = {"REMOTE_ADDR": "10.0.0.1", "HTTP_X_FORWARDED_FOR": cabecera}
    assert ip_del_cliente(peticion(**meta)) == "10.0.0.1"


def test_acepta_una_ipv6_en_x_forwarded_for(settings):
    settings.ENTRADA_PROXIES_CONFIABLES = 1
    meta = {"REMOTE_ADDR": "10.0.0.1", "HTTP_X_FORWARDED_FOR": "2001:db8::5"}
    assert ip_del_cliente(peticion(**meta)) == "2001:db8::5"


# --- Clave de la IP ---------------------------------------------------------

def test_la_clave_es_un_hmac_y_no_contiene_la_ip():
    clave = clave_de_ip(IP_A)
    assert len(clave) == 64 and int(clave, 16) >= 0
    assert IP_A not in clave


def test_la_clave_depende_de_la_secret_key(settings):
    antes = clave_de_ip(IP_A)
    settings.SECRET_KEY = "otra-clave-de-prueba"
    assert clave_de_ip(IP_A) != antes


def test_dos_ipv6_del_mismo_64_comparten_clave():
    assert clave_de_ip("2001:db8:1:2::1") == clave_de_ip("2001:db8:1:2:ffff:ffff:ffff:ffff")


def test_dos_ipv6_de_distinto_64_no_comparten_clave():
    assert clave_de_ip("2001:db8:1:2::1") != clave_de_ip("2001:db8:1:3::1")


def test_una_ipv4_dentro_de_ipv6_es_la_misma_que_la_ipv4():
    assert clave_de_ip("::ffff:203.0.113.9") == clave_de_ip(IP_A)


def test_dos_ipv4_distintas_no_comparten_clave():
    assert clave_de_ip(IP_A) != clave_de_ip(IP_B)


def test_una_ip_ilegible_no_rompe_y_comparte_una_clave_aparte():
    assert clave_de_ip("") == clave_de_ip("basura")
    assert clave_de_ip("") != clave_de_ip(IP_A)


# --- Rate limit del análisis -----------------------------------------------

def test_el_analisis_31_recibe_429_sin_llamar_a_ninguna_fuente(client, monkeypatch):
    pedir = mock.Mock()
    senales = mock.Mock(side_effect=vistas_analisis.detectar_senales)
    monkeypatch.setattr(net, "pedir_url", pedir)
    monkeypatch.setattr(vistas_analisis, "detectar_senales", senales)
    # Un enlace distinto cada vez: uno repetido saldría de la caché sin correr las señales.
    for numero in range(30):
        assert analizar(client, enlace=f"https://ejemplo.invalid/{numero}").status_code == 302
    respuesta = analizar(client, enlace="https://ejemplo.invalid/30")
    assert respuesta.status_code == 429
    assert respuesta["Retry-After"] == "600"
    assert respuesta["Cache-Control"] == "no-store"
    assert "muchos análisis seguidos" in respuesta.content.decode()
    # El análisis 31 ni siquiera empezó: no corrieron las señales y no hubo conexiones.
    assert senales.call_count == 30
    pedir.assert_not_called()


def test_otra_ip_tiene_su_propio_contador(client):
    for _ in range(30):
        analizar(client, IP_A)
    assert analizar(client, IP_A).status_code == 429
    assert analizar(client, IP_B).status_code == 302


def test_dos_ipv6_del_mismo_64_comparten_el_contador(client):
    for _ in range(30):
        assert analizar(client, "2001:db8:1:2::1").status_code == 302
    assert analizar(client, "2001:db8:1:2:ffff::9").status_code == 429
    assert analizar(client, "2001:db8:1:3::1").status_code == 302


def test_un_get_no_cuenta_para_el_limite(client):
    for _ in range(40):
        assert client.get(reverse("analizar"), REMOTE_ADDR=IP_A).status_code == 405
    assert analizar(client).status_code == 302


def test_una_solicitud_con_x_forwarded_for_falsificado_no_evade_el_limite(client, settings):
    settings.ENTRADA_PROXIES_CONFIABLES = 2
    for i in range(30):
        cabecera = f"9.9.9.{i}, {IP_A}, 172.64.0.1"
        respuesta = client.post(
            reverse("analizar"), {"enlace": "https://ejemplo.invalid/a"},
            REMOTE_ADDR="10.0.0.1", HTTP_X_FORWARDED_FOR=cabecera,
        )
        assert respuesta.status_code == 302
    respuesta = client.post(
        reverse("analizar"), {"enlace": "https://ejemplo.invalid/a"},
        REMOTE_ADDR="10.0.0.1", HTTP_X_FORWARDED_FOR=f"9.9.9.99, {IP_A}, 172.64.0.1",
    )
    assert respuesta.status_code == 429


def test_la_cache_no_guarda_la_ip_en_claro(client):
    analizar(client)
    claves = [str(clave) for clave in cache._cache]
    assert any("entrada:analisis:" in clave for clave in claves)
    assert not any(IP_A in clave for clave in claves)


def test_el_contador_se_reinicia_al_vencer_la_ventana(client):
    @limitar(Politica("prueba", 2, 1))
    def vista(request):
        from django.http import HttpResponse
        return HttpResponse("ok")

    pedir = peticion(REMOTE_ADDR=IP_A)
    assert [vista(pedir).status_code for _ in range(3)] == [200, 200, 429]
    time.sleep(1.2)
    assert vista(pedir).status_code == 200


@pytest.mark.django_db
def test_con_la_cache_de_render_la_ventana_no_se_acorta(settings, monkeypatch):
    # DatabaseCache.incr guardaba con la vigencia por defecto de 300 s: tras 400 s sin
    # solicitudes, el contador volvía a cero y la IP tenía otros 30 análisis.
    settings.CACHES = construir_caches("db", "redis://no-se-usa")
    call_command("createcachetable", verbosity=0)
    vista = limitar(Politica("prueba_db", 2, 600))(lambda request: HttpResponse("ok"))
    pedir = peticion(REMOTE_ADDR=IP_A)
    assert [vista(pedir).status_code for _ in range(2)] == [200, 200]
    # Pasan 400 s: DatabaseCache lee la hora con time.time al guardar y con tz_now al leer.
    reloj, ahora = time.time, cache_db.tz_now
    monkeypatch.setattr(time, "time", lambda: reloj() + 400)
    monkeypatch.setattr(cache_db, "tz_now", lambda: ahora() + timedelta(seconds=400))
    assert vista(pedir).status_code == 429


def test_las_politicas_no_cambian_sin_revision():
    # Si este test falla, alguien cambió un control de seguridad: debe ser deliberado.
    assert ANALISIS == Politica("analisis", 30, 600)
    assert REPORTES == Politica("reportes", 10, 3600)
    assert MAX_BYTES_CUERPO == 5 * 1024 * 1024 + 64 * 1024
    assert entrada.PREFIJO_IPV6 == 64


def test_los_reportes_limitan_a_10_por_hora():
    @limitar(REPORTES)
    def vista(request):
        from django.http import HttpResponse
        return HttpResponse("ok")

    pedir = peticion(REMOTE_ADDR=IP_A)
    estados = [vista(pedir).status_code for _ in range(11)]
    assert estados == [200] * 10 + [429]
    assert vista(peticion(REMOTE_ADDR=IP_B)).status_code == 200


# --- Presupuesto global de consultas externas -------------------------------

def test_el_presupuesto_externo_se_agota_y_dice_que_no(monkeypatch):
    monkeypatch.setattr(entrada, "CONSULTAS_EXTERNAS_POR_HORA", 3)
    assert [consumir_presupuesto_externo() for _ in range(5)] == [True, True, True, False, False]


def test_el_presupuesto_externo_se_renueva_cada_hora(monkeypatch):
    monkeypatch.setattr(entrada, "CONSULTAS_EXTERNAS_POR_HORA", 1)
    ahora = 1_800_000_000
    monkeypatch.setattr(time, "time", lambda: ahora)
    assert consumir_presupuesto_externo() is True
    assert consumir_presupuesto_externo() is False
    monkeypatch.setattr(time, "time", lambda: ahora + 3600)
    assert consumir_presupuesto_externo() is True


def test_el_presupuesto_externo_es_global_y_no_por_ip():
    assert CONSULTAS_EXTERNAS_POR_HORA == 200
    assert ipaddress.ip_address(IP_A) != ipaddress.ip_address(IP_B)


# --- Tamaño de la solicitud -------------------------------------------------

def test_una_solicitud_mas_grande_que_5_mb_recibe_413_sin_leerse(client):
    respuesta = client.get(reverse("health"), CONTENT_LENGTH=str(MAX_BYTES_CUERPO + 1))
    assert respuesta.status_code == 413
    # También la respuesta de rechazo lleva las cabeceras de seguridad.
    assert "Content-Security-Policy" in respuesta


def test_una_solicitud_en_el_limite_pasa(client):
    assert client.get(reverse("health"), CONTENT_LENGTH=str(MAX_BYTES_CUERPO)).status_code == 200


@pytest.mark.parametrize("largo", ["abc", "-1", "1e9", "5 MB"])
def test_un_content_length_invalido_recibe_400(client, largo):
    assert client.get(reverse("health"), CONTENT_LENGTH=largo).status_code == 400


def test_un_formulario_enorme_se_rechaza_antes_de_analizarlo(client, monkeypatch):
    senales = mock.Mock(side_effect=vistas_analisis.detectar_senales)
    monkeypatch.setattr(vistas_analisis, "detectar_senales", senales)
    respuesta = analizar(client, enlace="a" * 200_000)
    assert respuesta.status_code == 400
    senales.assert_not_called()
