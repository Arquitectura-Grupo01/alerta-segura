"""Edad de los dominios por RDAP, con el registro de servidores de IANA."""

import json
from datetime import UTC, datetime, timedelta

import pytest

from analisis import edad
from analisis.edad import URL_REGISTRO_IANA, edad_en_dias
from core.net import RESULTADO_ERROR_DE_RED, RESULTADO_OK, RespuestaSegura

RDAP_COM = "https://rdap.registro-com.example/com/v1/"
RDAP_FR = "https://rdap.registro-fr.example/"
RDAP_AR = "https://rdap.registro-ar.example/"
RDAP_LY = "https://rdap.registro-ly.example/"

# Como el de IANA: .pe no tiene servidor RDAP, y .kg solo tiene uno por http.
REGISTRO = {
    "services": [
        [["com", "net"], [RDAP_COM]],
        [["fr"], ["http://rdap.registro-fr.example/", RDAP_FR.rstrip("/")]],
        [["ar"], [RDAP_AR]],
        [["ly"], [RDAP_LY]],
        [["kg"], ["http://rdap.registro-kg.example/"]],
    ],
}


def respuesta(cuerpo, codigo=200):
    if not isinstance(cuerpo, bytes):
        cuerpo = json.dumps(cuerpo).encode()
    return RespuestaSegura(RESULTADO_OK, codigo_http=codigo, cuerpo=cuerpo)


def dominio_rdap(nombre, dias=None, fecha=None, **cambios):
    fecha = fecha or (datetime.now(UTC) - timedelta(days=dias)).isoformat()
    return {
        "objectClassName": "domain",
        "ldhName": nombre.upper(),
        "events": [
            {"eventAction": "last changed", "eventDate": "2026-01-01T00:00:00Z"},
            {"eventAction": "registration", "eventDate": fecha},
        ],
        **cambios,
    }


class Red:
    """Reemplaza a pedir_url: un 404 para lo que no conoce y la lista de URLs pedidas."""

    def __init__(self, respuestas):
        self.respuestas = {URL_REGISTRO_IANA: respuesta(REGISTRO), **respuestas}
        self.pedidas = []

    def __call__(self, url, **opciones):
        self.pedidas.append(url)
        return self.respuestas.get(url, respuesta(b"{}", 404))


@pytest.fixture
def red(monkeypatch):
    def poner(respuestas):
        falsa = Red({url: respuesta(cuerpo) for url, cuerpo in respuestas.items()})
        monkeypatch.setattr(edad, "pedir_url", falsa)
        return falsa

    return poner


def test_un_dominio_sin_rdap_queda_sin_edad(red):
    falsa = red({})
    assert edad_en_dias(["bcp.com.pe"]) is None
    assert falsa.pedidas == [URL_REGISTRO_IANA]


def test_un_servidor_solo_por_http_no_se_usa(red):
    falsa = red({})
    assert edad_en_dias(["tienda.kg"]) is None
    assert falsa.pedidas == [URL_REGISTRO_IANA]


def test_da_los_dias_desde_el_registro(red):
    red({f"{RDAP_COM}domain/pagina-nueva.com": dominio_rdap("pagina-nueva.com", dias=3)})
    assert edad_en_dias(["pagina-nueva.com"]) == 3


def test_en_un_dominio_generico_consulta_el_nombre_registrado(red):
    falsa = red({f"{RDAP_COM}domain/ejemplo.com": dominio_rdap("ejemplo.com", dias=900)})
    assert edad_en_dias(["login.cuenta.ejemplo.com"]) == 900
    assert falsa.pedidas[1:] == [f"{RDAP_COM}domain/ejemplo.com"]


def test_en_un_dominio_de_pais_prueba_el_tercer_nivel_y_despues_el_segundo(red):
    falsa = red({f"{RDAP_FR}domain/ejemplo.fr": dominio_rdap("ejemplo.fr", dias=40)})
    assert edad_en_dias(["www.ejemplo.fr"]) == 40
    assert falsa.pedidas[1:] == [f"{RDAP_FR}domain/www.ejemplo.fr", f"{RDAP_FR}domain/ejemplo.fr"]


def test_nunca_consulta_un_sufijo_como_com_ar(red):
    # El RDAP de .ar da fecha de registro para com.ar: sería una web antigua que no existe.
    falsa = red({f"{RDAP_AR}domain/com.ar": dominio_rdap("com.ar", dias=3000)})
    assert edad_en_dias(["tienda-falsa.com.ar"]) is None
    assert falsa.pedidas[1:] == [f"{RDAP_AR}domain/tienda-falsa.com.ar"]


@pytest.mark.parametrize("dominio", ["estafa.netlify.app", "banco-pe.github.io", "192.0.2.10"])
def test_un_alojamiento_compartido_o_una_ip_quedan_sin_edad(red, dominio):
    falsa = red({})
    assert edad_en_dias([dominio]) is None
    assert falsa.pedidas == []


def test_la_edad_de_un_acortador_no_cuenta(red):
    falsa = red({
        f"{RDAP_LY}domain/bit.ly": dominio_rdap("bit.ly", dias=6000),
        f"{RDAP_COM}domain/destino.com": dominio_rdap("destino.com", dias=12),
    })
    assert edad_en_dias(["bit.ly", "destino.com"]) == 12
    assert edad_en_dias(["bit.ly"]) is None
    assert f"{RDAP_LY}domain/bit.ly" not in falsa.pedidas


def test_manda_la_web_mas_nueva_de_la_cadena(red):
    red({
        f"{RDAP_COM}domain/nueva.com": dominio_rdap("nueva.com", dias=2),
        f"{RDAP_COM}domain/antigua.com": dominio_rdap("antigua.com", dias=9000),
    })
    assert edad_en_dias(["nueva.com", "antigua.com"]) == 2


def test_una_web_antigua_no_esconde_otra_sin_edad(red):
    red({
        f"{RDAP_COM}domain/antigua.com": dominio_rdap("antigua.com", dias=9000),
        f"{RDAP_COM}domain/nueva.com": dominio_rdap("nueva.com", dias=5),
    })
    assert edad_en_dias(["promo.pe", "antigua.com"]) is None
    # Una web nueva sí se informa: la que falta no puede hacer que parezca antigua.
    assert edad_en_dias(["promo.pe", "nueva.com"]) == 5


def test_el_mismo_dominio_se_consulta_una_vez(red):
    falsa = red({f"{RDAP_COM}domain/ejemplo.com": dominio_rdap("ejemplo.com", dias=50)})
    assert edad_en_dias(["ejemplo.com", "www.ejemplo.com"]) == 50
    assert falsa.pedidas.count(f"{RDAP_COM}domain/ejemplo.com") == 1


@pytest.mark.parametrize("cuerpo", [
    b"no es json",
    b"[" * 100_000,
    json.dumps({"objectClassName": "entity", "ldhName": "ejemplo.com", "events": []}).encode(),
    json.dumps(dominio_rdap("otro.com", dias=1)).encode(),
    json.dumps(dominio_rdap("ejemplo.com", dias=1, events=[])).encode(),
    json.dumps(dominio_rdap("ejemplo.com", dias=1, events="ayer")).encode(),
    json.dumps(dominio_rdap("ejemplo.com", fecha="2026-13-01T00:00:00Z")).encode(),
    json.dumps(dominio_rdap("ejemplo.com", fecha="2999-01-01T00:00:00Z")).encode(),
])
def test_una_respuesta_rara_no_da_edad(red, cuerpo):
    red({f"{RDAP_COM}domain/ejemplo.com": cuerpo})
    assert edad_en_dias(["ejemplo.com"]) is None


def test_una_fecha_sin_zona_horaria_se_lee_en_utc(red):
    fecha = (datetime.now(UTC) - timedelta(days=10)).replace(tzinfo=None).isoformat()
    red({f"{RDAP_COM}domain/ejemplo.com": dominio_rdap("ejemplo.com", fecha=fecha)})
    assert edad_en_dias(["ejemplo.com"]) == 10


@pytest.mark.parametrize("codigo", [429, 500])
def test_un_error_del_servidor_rdap_deja_sin_edad(monkeypatch, codigo):
    falsa = Red({f"{RDAP_COM}domain/ejemplo.com": respuesta(b"{}", codigo)})
    monkeypatch.setattr(edad, "pedir_url", falsa)
    assert edad_en_dias(["ejemplo.com"]) is None


def test_el_registro_de_iana_se_pide_una_vez(red):
    falsa = red({f"{RDAP_COM}domain/ejemplo.com": dominio_rdap("ejemplo.com", dias=50)})
    edad_en_dias(["ejemplo.com"])
    edad_en_dias(["ejemplo.com"])
    assert falsa.pedidas.count(URL_REGISTRO_IANA) == 1


@pytest.mark.parametrize("registro", [
    RespuestaSegura(RESULTADO_ERROR_DE_RED),
    respuesta(b"{}", 503),
    respuesta(b"no es json"),
    respuesta({"services": "ninguno"}),
])
def test_si_iana_falla_no_se_reintenta_en_cada_analisis(monkeypatch, registro):
    falsa = Red({})
    falsa.respuestas[URL_REGISTRO_IANA] = registro
    monkeypatch.setattr(edad, "pedir_url", falsa)
    assert edad_en_dias(["ejemplo.com"]) is None
    assert edad_en_dias(["ejemplo.com"]) is None
    assert falsa.pedidas == [URL_REGISTRO_IANA]


def test_si_iana_falla_al_renovar_sigue_con_el_registro_anterior(monkeypatch):
    reloj = [1000.0]
    monkeypatch.setattr(edad.time, "monotonic", lambda: reloj[0])
    falsa = Red({f"{RDAP_COM}domain/ejemplo.com": respuesta(dominio_rdap("ejemplo.com", dias=50))})
    monkeypatch.setattr(edad, "pedir_url", falsa)
    assert edad_en_dias(["ejemplo.com"]) == 50

    reloj[0] += edad.VIGENCIA_REGISTRO_SEGUNDOS
    falsa.respuestas[URL_REGISTRO_IANA] = RespuestaSegura(RESULTADO_ERROR_DE_RED)
    assert edad_en_dias(["ejemplo.com"]) == 50
    assert falsa.pedidas.count(URL_REGISTRO_IANA) == 2


def test_todas_las_consultas_comparten_el_plazo(monkeypatch):
    reloj = [1000.0]
    monkeypatch.setattr(edad.time, "monotonic", lambda: reloj[0])
    plazos = []

    class Lenta(Red):
        def __call__(self, url, **opciones):
            plazos.append(opciones["plazo_segundos"])
            reloj[0] += 2
            return super().__call__(url, **opciones)

    monkeypatch.setattr(edad, "pedir_url", Lenta({}))
    # Registro de IANA, www.ejemplo.fr y ejemplo.fr: cada consulta recibe lo que queda.
    assert edad_en_dias(["www.ejemplo.fr", "otra.com"]) is None
    assert plazos == [edad.PLAZO_RDAP_SEGUNDOS, edad.PLAZO_RDAP_SEGUNDOS - 2, 1]
