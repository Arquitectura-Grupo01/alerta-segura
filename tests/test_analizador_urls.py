
"""Pruebas de normalización de enlaces."""

import pytest

from analisis.urls import URLInvalida, normalizar_url


def test_agrega_https():
    resultado = normalizar_url("ejemplo.pe/login")
    assert resultado == "https://ejemplo.pe/login"


def test_convierte_dominio_a_minusculas():
    resultado = normalizar_url("https://EJEMPLO.PE/")
    assert resultado == "https://ejemplo.pe/"


def test_elimina_fragmento():
    resultado = normalizar_url("https://ejemplo.pe/ruta#seccion")
    assert resultado == "https://ejemplo.pe/ruta"


def test_elimina_parametros_de_rastreo():
    resultado = normalizar_url(
        "https://ejemplo.pe/?id=123&utm_source=redes"
    )
    assert resultado == "https://ejemplo.pe/?id=123"


def test_rechaza_usuario_en_url():
    with pytest.raises(URLInvalida):
        normalizar_url(
            "https://bcp.com.pe@sitio-falso.com/login"
        )


def test_rechaza_enlace_vacio():
    with pytest.raises(URLInvalida):
        normalizar_url("")

"adicionalmente, se rechazan protocolos no permitidos y puertos no permitidos"
def test_rechaza_protocolo_javascript():
    with pytest.raises(URLInvalida):
        normalizar_url("javascript:alert(1)")


def test_rechaza_protocolo_file():
    with pytest.raises(URLInvalida):
        normalizar_url("file:///etc/passwd")


def test_rechaza_puerto_no_permitido():
    with pytest.raises(URLInvalida):
        normalizar_url("https://ejemplo.com:9999/")


"ipv6 y dominio con punto final se normalizan correctamente"
def test_normaliza_ipv6():
    assert normalizar_url("http://[2001:db8::1]/") == (
        "http://[2001:db8::1]/"
    )


def test_normaliza_dominio_con_punto_final():
    assert normalizar_url("https://EJEMPLO.COM./") == (
        "https://ejemplo.com./"
    )


def test_rechaza_doble_punto_en_puerto():
    with pytest.raises(URLInvalida):
        normalizar_url("https://ejemplo.com:abc/")


def test_rechaza_barra_invertida():
    with pytest.raises(URLInvalida):
        normalizar_url("https://ejemplo.com\\@sitio-falso.com/")