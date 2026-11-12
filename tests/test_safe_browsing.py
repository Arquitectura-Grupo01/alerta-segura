"""Adaptador de Google Safe Browsing v5, con respuestas grabadas y sin red."""

import base64
import hashlib
import json
from urllib.parse import parse_qs, urlsplit

import pytest

from core.net import (
    RESULTADO_ERROR_DE_RED,
    RESULTADO_OK,
    RESULTADO_TIEMPO_AGOTADO,
    RespuestaSegura,
)
from inteligencia import fuentes, safe_browsing
from inteligencia.fuentes import MOTIVO_ERROR, MOTIVO_TIEMPO, Estado
from inteligencia.safe_browsing import SafeBrowsing, expresiones

CLAVE = "clave-ficticia-de-google"
URL = "https://tienda.web-falsa.example/promo/pago.html?id=7"


def b64(datos):
    return base64.b64encode(datos).decode()


def sha(expresion):
    return hashlib.sha256(expresion.encode()).digest()


def google(hashes, codigo=200):
    """Respuesta de hashes:search con los hashes completos y sus tipos de amenaza."""
    cuerpo = {
        "fullHashes": [
            {"fullHash": b64(completo), "fullHashDetails": [{"threatType": t} for t in tipos]}
            for completo, tipos in hashes
        ],
        "cacheDuration": "300s",
    }
    return RespuestaSegura(RESULTADO_OK, codigo_http=codigo, cuerpo=json.dumps(cuerpo).encode())


@pytest.fixture
def red(monkeypatch):
    pedidas = []

    def poner(respuesta):
        def pedir(url, **opciones):
            pedidas.append((url, opciones))
            return respuesta

        monkeypatch.setattr(safe_browsing, "pedir_url", pedir)
        return pedidas

    return poner


# --- Formas de la dirección -------------------------------------------------

@pytest.mark.parametrize(("url", "canonica"), [
    ("http://host/%25%32%35", "host/%25"),
    ("http://host/%2525252525252525", "host/%25"),
    ("http://www.google.com/blah/..", "www.google.com/"),
    ("http://www.GOOgle.com/", "www.google.com/"),
    ("http://www.google.com.../", "www.google.com/"),
    ("http://evil.com/foo#bar#baz", "evil.com/foo"),
    ("http://host.com//twoslashes?more//slashes", "host.com/twoslashes?more//slashes"),
    ("http://www.google.com/foo\tbar\rbaz\n2", "www.google.com/foobarbaz2"),
    ("http://www.gotaport.com:1234/", "www.gotaport.com/"),
    ("http://host.com/ab%23cd", "host.com/ab%23cd"),
    ("http://notrailingslash.com", "notrailingslash.com/"),
])
def test_canoniza_la_direccion_como_los_ejemplos_de_google(url, canonica):
    assert expresiones(url)[0] == canonica


def test_arma_las_combinaciones_de_host_y_ruta_del_ejemplo_de_google():
    assert expresiones("http://a.b.c/1/2.html?param=1") == [
        "a.b.c/1/2.html?param=1", "a.b.c/1/2.html", "a.b.c/", "a.b.c/1/",
        "b.c/1/2.html?param=1", "b.c/1/2.html", "b.c/", "b.c/1/",
    ]


def test_nunca_pasa_de_30_combinaciones_ni_consulta_el_tld_solo():
    formas = expresiones("http://a.b.c.d.e.f.g/1/2/3/4/5/6/7.html?x=1")
    assert len(formas) == 30
    assert not any(forma.startswith("g/") for forma in formas)


def test_una_ip_no_tiene_dominios_superiores():
    assert expresiones("http://192.0.2.7/a/") == ["192.0.2.7/a/", "192.0.2.7/"]


def test_una_direccion_sin_host_no_tiene_formas():
    assert expresiones("no-es-una-url") == []


# --- Consulta ---------------------------------------------------------------

def test_a_google_solo_llegan_prefijos_de_4_bytes_y_nunca_la_url(red):
    pedidas = red(google([]))
    SafeBrowsing(CLAVE).consultar(URL)
    [(pedida, opciones)] = pedidas
    partes = urlsplit(pedida)
    consulta = parse_qs(partes.query)
    assert f"{partes.scheme}://{partes.netloc}{partes.path}" == safe_browsing.URL_BUSQUEDA
    assert consulta["key"] == [CLAVE]
    esperados = {b64(sha(forma)[:4]).rstrip("=") for forma in expresiones(URL)}
    assert set(consulta["hashPrefixes"]) == esperados
    assert "web-falsa" not in pedida and "pago" not in pedida
    # La clave va en la URL: no se sigue ninguna redirección con ella.
    assert opciones["max_redirecciones"] == 0


@pytest.mark.parametrize("tipo", ["MALWARE", "SOCIAL_ENGINEERING"])
def test_un_hash_completo_que_coincide_es_una_deteccion(red, tipo):
    red(google([(sha("web-falsa.example/"), [tipo])]))
    respuesta = SafeBrowsing(CLAVE).consultar(URL)
    assert (respuesta.estado, respuesta.valor) == (Estado.DETECCION, 100)


def test_un_hash_que_solo_comparte_el_prefijo_no_es_una_deteccion(red):
    otro = sha("web-falsa.example/")[:4] + b"\x00" * 28
    red(google([(otro, ["MALWARE"])]))
    assert SafeBrowsing(CLAVE).consultar(URL).estado is Estado.DESCONOCIDO


def test_si_la_direccion_no_figura_el_estado_es_desconocido_y_no_limpio(red):
    red(google([]))
    assert SafeBrowsing(CLAVE).consultar(URL).estado is Estado.DESCONOCIDO


def test_un_tipo_de_amenaza_que_no_aporta_esta_fuente_se_ignora(red):
    red(google([(sha("web-falsa.example/"), ["UNWANTED_SOFTWARE", "TIPO_NUEVO"])]))
    assert SafeBrowsing(CLAVE).consultar(URL).estado is Estado.DESCONOCIDO


def test_acepta_base64_de_url_y_sin_relleno(red):
    completo = sha("web-falsa.example/")
    texto = base64.urlsafe_b64encode(completo).decode().rstrip("=")
    cuerpo = {"fullHashes": [{"fullHash": texto, "fullHashDetails": [{"threatType": "MALWARE"}]}]}
    red(RespuestaSegura(RESULTADO_OK, codigo_http=200, cuerpo=json.dumps(cuerpo).encode()))
    assert SafeBrowsing(CLAVE).consultar(URL).estado is Estado.DETECCION


@pytest.mark.parametrize(("respuesta", "motivo"), [
    (RespuestaSegura(RESULTADO_ERROR_DE_RED), MOTIVO_ERROR),
    (RespuestaSegura(RESULTADO_TIEMPO_AGOTADO), MOTIVO_TIEMPO),
    (google([], codigo=403), MOTIVO_ERROR),
    (google([], codigo=429), MOTIVO_ERROR),
    (RespuestaSegura(RESULTADO_OK, codigo_http=200, cuerpo=b"\x0a\x22binario"), MOTIVO_ERROR),
    (RespuestaSegura(RESULTADO_OK, codigo_http=200, cuerpo=b'{"fullHashes": [{"x": 1}]}'),
     MOTIVO_ERROR),
    (RespuestaSegura(RESULTADO_OK, codigo_http=200,
                     cuerpo=b'{"fullHashes": [{"fullHash": "###", "fullHashDetails": []}]}'),
     MOTIVO_ERROR),
])
def test_un_error_de_google_es_el_estado_fallo(red, respuesta, motivo):
    red(respuesta)
    resultado = SafeBrowsing(CLAVE).consultar(URL)
    assert (resultado.estado, resultado.motivo) == (Estado.FALLO, motivo)


# --- Registro ---------------------------------------------------------------

def test_sin_clave_la_fuente_se_omite(settings, monkeypatch):
    monkeypatch.setattr(fuentes, "_FUENTES", None)
    settings.SAFE_BROWSING_API_KEY = ""
    assert fuentes.fuentes_activas() == []


def test_con_clave_la_fuente_queda_activa(settings, monkeypatch):
    monkeypatch.setattr(fuentes, "_FUENTES", None)
    settings.SAFE_BROWSING_API_KEY = CLAVE
    [activa] = fuentes.fuentes_activas()
    assert (activa.nombre, activa.titulo, activa.clave) == (
        "safe_browsing", "Google Safe Browsing", CLAVE
    )
