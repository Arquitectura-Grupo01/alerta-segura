"""Adaptadores de URLhaus, PhishTank, VirusTotal, urlscan.io y AbuseIPDB, sin red.

Cada respuesta imita la que documenta el proveedor. Cubren lo que piden las tareas 18 a 20:
detección, dirección que no figura y error en cada adaptador; el umbral de motores de
VirusTotal, un análisis de 30 días que no cuenta como limpio y la cuota agotada; e IP
reportada, IP sin reportes y cuota agotada en AbuseIPDB.
"""

import base64
import json
import logging
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import pytest
from django.core.cache import cache
from django.urls import reverse

from core.net import (
    RESULTADO_BLOQUEADO,
    RESULTADO_ERROR_DE_RED,
    RESULTADO_OK,
    RESULTADO_TIEMPO_AGOTADO,
    DestinoBloqueado,
    RespuestaSegura,
)
from inteligencia import abuseipdb, fuentes
from inteligencia.abuseipdb import AbuseIPDB
from inteligencia.fuentes import (
    FALLOS_PARA_ABRIR,
    MOTIVO_CUOTA,
    MOTIVO_ERROR,
    MOTIVO_TIEMPO,
    Estado,
    resumir,
)
from inteligencia.phishtank import PhishTank
from inteligencia.urlhaus import URLhaus
from inteligencia.urlscan import Urlscan
from inteligencia.virustotal import VirusTotal

URL = "https://web-de-prueba.example/pago"
CLAVE = "clave-ficticia-de-prueba-123"


class Red:
    """Reemplaza a pedir_url: devuelve la respuesta puesta y guarda cada llamada."""

    def __init__(self, respuesta):
        self.respuesta = respuesta
        self.llamadas = []

    def __call__(self, url, **opciones):
        self.llamadas.append((url, opciones))
        return self.respuesta


def api(cuerpo, codigo=200):
    contenido = cuerpo if isinstance(cuerpo, bytes) else json.dumps(cuerpo).encode()
    return RespuestaSegura(RESULTADO_OK, codigo_http=codigo, cuerpo=contenido)


@pytest.fixture
def red(monkeypatch):
    def poner(respuesta):
        falsa = Red(respuesta)
        monkeypatch.setattr(fuentes, "pedir_url", falsa)
        return falsa

    return poner


def hace(**tiempo):
    return datetime.now(UTC) - timedelta(**tiempo)


# --- Lo común a los cinco ---------------------------------------------------

ADAPTADORES = [URLhaus, PhishTank, VirusTotal, Urlscan, AbuseIPDB]


@pytest.fixture(autouse=True)
def ip_publica(monkeypatch):
    """AbuseIPDB resuelve el destino: aquí siempre a una IP pública de ejemplo."""
    monkeypatch.setattr(abuseipdb, "resolver_y_validar", lambda host: ["8.8.8.8"])


@pytest.mark.parametrize("clase", ADAPTADORES)
def test_sin_clave_la_fuente_se_omite(clase):
    assert clase("").disponible() is False
    assert clase(CLAVE).disponible() is True


@pytest.mark.parametrize("clase", ADAPTADORES)
@pytest.mark.parametrize(("respuesta", "motivo"), [
    (RespuestaSegura(RESULTADO_ERROR_DE_RED), MOTIVO_ERROR),
    (RespuestaSegura(RESULTADO_TIEMPO_AGOTADO), MOTIVO_TIEMPO),
    (RespuestaSegura(RESULTADO_BLOQUEADO), MOTIVO_ERROR),
    (api({}, codigo=500), MOTIVO_ERROR),
    (api({}, codigo=401), MOTIVO_ERROR),
    (api({}, codigo=429), MOTIVO_CUOTA),
    (api(b"<html>no es json</html>"), MOTIVO_ERROR),
    (api({"otra": "forma"}), MOTIVO_ERROR),
])
def test_un_error_del_proveedor_es_el_estado_fallo(red, clase, respuesta, motivo):
    red(respuesta)
    resultado = clase(CLAVE).consultar(URL)
    assert (resultado.estado, resultado.motivo) == (Estado.FALLO, motivo)


@pytest.mark.parametrize("clase", ADAPTADORES)
def test_nunca_sigue_redirecciones_y_usa_el_plazo_de_la_fuente(red, clase):
    falsa = red(RespuestaSegura(RESULTADO_ERROR_DE_RED))
    clase(CLAVE).consultar(URL)
    [(_, opciones)] = falsa.llamadas
    assert opciones["max_redirecciones"] == 0
    assert opciones["plazo_segundos"] == fuentes.PLAZO_POR_FUENTE_SEGUNDOS


@pytest.mark.parametrize("clase", ADAPTADORES)
def test_la_clave_no_aparece_en_los_logs_cuando_falla(red, clase, caplog):
    red(api({}, codigo=500))
    with caplog.at_level(logging.DEBUG):
        for _ in range(FALLOS_PARA_ABRIR):
            clase(CLAVE).consultar(URL)
    assert caplog.records
    assert CLAVE not in caplog.text
    assert "web-de-prueba" not in caplog.text


def test_las_seis_fuentes_quedan_activas_con_sus_claves(settings, monkeypatch):
    monkeypatch.setattr(fuentes, "_FUENTES", None)
    for variable in ("SAFE_BROWSING_API_KEY", "ABUSE_CH_AUTH_KEY", "PHISHTANK_APP_KEY",
                     "VIRUSTOTAL_API_KEY", "URLSCAN_API_KEY", "ABUSEIPDB_API_KEY"):
        setattr(settings, variable, f"{CLAVE}-{variable}")
    nombres = [fuente.nombre for fuente in fuentes.fuentes_activas()]
    assert nombres == [
        "safe_browsing", "urlhaus", "phishtank", "virustotal", "urlscan", "abuseipdb"
    ]


def test_sin_ninguna_clave_no_se_consulta_ninguna_fuente(settings, monkeypatch):
    monkeypatch.setattr(fuentes, "_FUENTES", None)
    assert fuentes.fuentes_activas() == []


# --- URLhaus ----------------------------------------------------------------

def test_urlhaus_pide_por_post_con_la_clave_en_la_cabecera(red):
    falsa = red(api({"query_status": "no_results"}))
    URLhaus(CLAVE).consultar(URL)
    [(pedida, opciones)] = falsa.llamadas
    assert pedida == "https://urlhaus-api.abuse.ch/v1/url/"
    assert opciones["metodo"] == "POST"
    assert opciones["encabezados"] == {"Auth-Key": CLAVE}
    assert opciones["datos"] == {"url": URL}


@pytest.mark.parametrize(("cuerpo", "estado"), [
    ({"query_status": "ok", "url_status": "online", "threat": "malware_download"},
     Estado.DETECCION),
    ({"query_status": "ok", "url_status": "unknown"}, Estado.DETECCION),
    # Dada de baja: suele ser una web comprometida que ya se limpió.
    ({"query_status": "ok", "url_status": "offline"}, Estado.DESCONOCIDO),
    # Que no figure no la vuelve limpia.
    ({"query_status": "no_results"}, Estado.DESCONOCIDO),
    ({"query_status": "invalid_url"}, Estado.DESCONOCIDO),
    ({"query_status": "estado_nuevo"}, Estado.FALLO),
])
def test_urlhaus(red, cuerpo, estado):
    red(api(cuerpo))
    respuesta = URLhaus(CLAVE).consultar(URL)
    assert respuesta.estado is estado
    if estado is Estado.DETECCION:
        assert respuesta.valor == 100


# --- PhishTank --------------------------------------------------------------

def test_phishtank_manda_la_clave_en_el_formulario(red):
    falsa = red(api({"results": {"in_database": False}}))
    PhishTank(CLAVE).consultar(URL)
    [(pedida, opciones)] = falsa.llamadas
    assert pedida == "https://checkurl.phishtank.com/checkurl/"
    assert opciones["metodo"] == "POST"
    assert opciones["datos"] == {"url": URL, "format": "json", "app_key": CLAVE}


@pytest.mark.parametrize(("resultados", "estado"), [
    ({"in_database": True, "verified": True, "valid": True}, Estado.DETECCION),
    ({"in_database": True, "verified": "y", "valid": "y"}, Estado.DETECCION),
    # Sin verificar, o ya no activa: no se afirma nada.
    ({"in_database": True, "verified": "n", "valid": "y"}, Estado.DESCONOCIDO),
    ({"in_database": True, "verified": True, "valid": False}, Estado.DESCONOCIDO),
    ({"in_database": False}, Estado.DESCONOCIDO),
    ({"in_database": "quizás"}, Estado.DESCONOCIDO),
])
def test_phishtank(red, resultados, estado):
    red(api({"meta": {"status": "success"}, "results": resultados}))
    assert PhishTank(CLAVE).consultar(URL).estado is estado


def test_phishtank_con_509_se_quedo_sin_cuota(red):
    red(api({}, codigo=509))
    respuesta = PhishTank(CLAVE).consultar(URL)
    assert (respuesta.estado, respuesta.motivo) == (Estado.FALLO, MOTIVO_CUOTA)


# --- VirusTotal -------------------------------------------------------------

def virustotal(malicious, fecha):
    atributos = {"last_analysis_stats": {"malicious": malicious, "harmless": 60}}
    if fecha is not None:
        atributos["last_analysis_date"] = int(fecha.timestamp())
    return api({"data": {"type": "url", "attributes": atributos}})


def test_virustotal_busca_el_analisis_existente_con_la_clave_en_la_cabecera(red):
    falsa = red(virustotal(0, hace(hours=1)))
    VirusTotal(CLAVE).consultar(URL)
    [(pedida, opciones)] = falsa.llamadas
    identificador = base64.urlsafe_b64encode(URL.encode()).decode().rstrip("=")
    assert pedida == f"https://www.virustotal.com/api/v3/urls/{identificador}"
    assert opciones["encabezados"] == {"x-apikey": CLAVE}
    # Solo lee: nunca manda una dirección nueva a escanear.
    assert opciones.get("metodo", "GET") == "GET"
    assert CLAVE not in pedida


@pytest.mark.parametrize(("motores", "estado", "valor"), [
    (3, Estado.DETECCION, 100),
    (12, Estado.DETECCION, 100),
    (2, Estado.DETECCION, 50),
    (1, Estado.DETECCION, 50),
    (0, Estado.SIN_DETECCIONES, None),
])
def test_virustotal_umbral_de_motores(red, motores, estado, valor):
    red(virustotal(motores, hace(hours=2)))
    respuesta = VirusTotal(CLAVE).consultar(URL)
    assert (respuesta.estado, respuesta.valor) == (estado, valor)


def test_virustotal_un_analisis_limpio_de_30_dias_no_cubre_la_categoria(red):
    red(virustotal(0, hace(days=30)))
    respuesta = VirusTotal(CLAVE).consultar(URL)
    assert respuesta.estado is Estado.DESCONOCIDO
    assert resumir([respuesta]).valor is None


def test_virustotal_una_deteccion_vieja_sigue_contando(red):
    red(virustotal(5, hace(days=30)))
    assert VirusTotal(CLAVE).consultar(URL).estado is Estado.DETECCION


@pytest.mark.parametrize("fecha", [None, "ayer"])
def test_virustotal_sin_fecha_del_analisis_es_desconocido(red, fecha):
    cuerpo = {"data": {"attributes": {"last_analysis_stats": {"malicious": 0}}}}
    if fecha is not None:
        cuerpo["data"]["attributes"]["last_analysis_date"] = fecha
    red(api(cuerpo))
    assert VirusTotal(CLAVE).consultar(URL).estado is Estado.DESCONOCIDO


@pytest.mark.parametrize("motores", ["3", -1, True, None])
def test_virustotal_un_conteo_raro_es_un_fallo(red, motores):
    red(virustotal(motores, hace(hours=1)))
    assert VirusTotal(CLAVE).consultar(URL).estado is Estado.FALLO


def test_virustotal_una_direccion_que_no_tiene_es_desconocida(red):
    red(api({"error": {"code": "NotFoundError"}}, codigo=404))
    assert VirusTotal(CLAVE).consultar(URL).estado is Estado.DESCONOCIDO


def test_virustotal_cuota_de_4_por_minuto(red):
    falsa = red(virustotal(0, hace(hours=1)))
    fuente = VirusTotal(CLAVE)
    motivos = [fuente.consultar(URL).motivo for _ in range(6)]
    assert motivos == ["", "", "", "", MOTIVO_CUOTA, MOTIVO_CUOTA]
    assert len(falsa.llamadas) == 4


def test_virustotal_cuota_diaria_agotada(red):
    falsa = red(virustotal(0, hace(hours=1)))
    fuente = VirusTotal(CLAVE)
    cache.set(fuente._clave_de_cuota(), 500)
    respuesta = fuente.consultar(URL)
    assert (respuesta.estado, respuesta.motivo) == (Estado.FALLO, MOTIVO_CUOTA)
    assert falsa.llamadas == []


def test_virustotal_cuota_agotada_en_el_proveedor(red):
    red(api({"error": {"code": "QuotaExceededError"}}, codigo=429))
    respuesta = VirusTotal(CLAVE).consultar(URL)
    assert (respuesta.estado, respuesta.motivo) == (Estado.FALLO, MOTIVO_CUOTA)


# --- urlscan.io -------------------------------------------------------------

def escaneo(malicioso, fecha, forma="plana"):
    if forma == "plana":
        veredictos = {"malicious": malicioso, "score": 0}
    elif forma == "overall":
        veredictos = {"overall": {"malicious": malicioso}}
    else:
        veredictos = None
    item = {
        "task": {"time": fecha.isoformat().replace("+00:00", "Z"), "url": URL},
        "page": {"url": URL},
    }
    if veredictos is not None:
        item["verdicts"] = veredictos
    return item


def test_urlscan_busca_la_direccion_exacta_o_su_destino_final(red):
    falsa = red(api({"results": []}))
    Urlscan(CLAVE).consultar('https://web.example/a"b\\c')
    [(pedida, opciones)] = falsa.llamadas
    partes = urlsplit(pedida)
    assert f"{partes.scheme}://{partes.netloc}{partes.path}" == "https://urlscan.io/api/v1/search/"
    consulta = parse_qs(partes.query)["q"][0]
    frase = 'https://web.example/a\\"b\\\\c'
    assert consulta == f'task.url.keyword:"{frase}" OR page.url.keyword:"{frase}"'
    assert opciones["encabezados"] == {"API-Key": CLAVE}
    assert CLAVE not in pedida


@pytest.mark.parametrize("forma", ["plana", "overall"])
def test_urlscan_un_escaneo_malicioso_es_una_deteccion(red, forma):
    red(api({"results": [escaneo(False, hace(hours=1)), escaneo(True, hace(days=40), forma)]}))
    assert Urlscan(CLAVE).consultar(URL).estado is Estado.DETECCION


def test_urlscan_un_escaneo_limpio_de_hoy_es_sin_detecciones(red):
    red(api({"results": [escaneo(False, hace(days=3)), escaneo(False, hace(hours=5))]}))
    assert Urlscan(CLAVE).consultar(URL).estado is Estado.SIN_DETECCIONES


@pytest.mark.parametrize("resultados", [
    [],
    # Limpio pero viejo.
    [escaneo(False, hace(days=30))],
    # Sin veredicto en la respuesta: no se puede afirmar que esté limpia.
    [escaneo(None, hace(hours=1), forma="sin")],
    [{"task": {"time": "no es fecha"}, "verdicts": {"malicious": False}}],
])
def test_urlscan_sin_un_escaneo_limpio_y_reciente_es_desconocido(red, resultados):
    red(api({"results": resultados}))
    assert Urlscan(CLAVE).consultar(URL).estado is Estado.DESCONOCIDO


# --- AbuseIPDB --------------------------------------------------------------

def abuse(confianza, lista_blanca=False):
    return api({"data": {
        "ipAddress": "8.8.8.8", "abuseConfidenceScore": confianza, "totalReports": 40,
        "isWhitelisted": lista_blanca, "lastReportedAt": "2026-11-10T10:00:00+00:00",
    }})


def test_abuseipdb_solo_recibe_la_ip_del_destino(red):
    falsa = red(abuse(0))
    AbuseIPDB(CLAVE).consultar(URL)
    [(pedida, opciones)] = falsa.llamadas
    partes = urlsplit(pedida)
    assert f"{partes.scheme}://{partes.netloc}{partes.path}" == (
        "https://api.abuseipdb.com/api/v2/check"
    )
    assert parse_qs(partes.query) == {"ipAddress": ["8.8.8.8"], "maxAgeInDays": ["90"]}
    assert opciones["encabezados"] == {"Key": CLAVE, "Accept": "application/json"}
    assert "web-de-prueba" not in pedida


def test_abuseipdb_una_ip_reportada_es_una_sospecha_y_no_una_confirmacion(red):
    red(abuse(100))
    respuesta = AbuseIPDB(CLAVE).consultar(URL)
    assert (respuesta.estado, respuesta.valor) == (Estado.DETECCION, 50)
    resumen = resumir([respuesta])
    assert (resumen.valor, resumen.confirmaciones) == (50, 0)


@pytest.mark.parametrize(("confianza", "lista_blanca"), [
    (0, False),
    (abuseipdb.UMBRAL_CONFIANZA - 1, False),
    (100, True),
    ("100", False),
])
def test_abuseipdb_una_ip_sin_reportes_suficientes_es_desconocida(red, confianza, lista_blanca):
    red(abuse(confianza, lista_blanca))
    respuesta = AbuseIPDB(CLAVE).consultar(URL)
    # Nunca «sin detecciones»: una IP limpia no prueba que la web lo sea.
    assert respuesta.estado is Estado.DESCONOCIDO


def test_abuseipdb_una_ip_escrita_en_la_direccion_se_consulta_directo(red, monkeypatch):
    monkeypatch.setattr(abuseipdb, "resolver_y_validar", lambda host: pytest.fail("no resuelve"))
    falsa = red(abuse(0))
    AbuseIPDB(CLAVE).consultar("http://1.1.1.1/login")
    assert parse_qs(urlsplit(falsa.llamadas[0][0]).query)["ipAddress"] == ["1.1.1.1"]


@pytest.mark.parametrize("url", ["http://10.0.0.5/", "http://[::1]/"])
def test_abuseipdb_no_consulta_ips_internas(red, url):
    falsa = red(abuse(100))
    assert AbuseIPDB(CLAVE).consultar(url).estado is Estado.DESCONOCIDO
    assert falsa.llamadas == []


def test_abuseipdb_un_destino_que_no_resuelve_es_desconocido(red, monkeypatch):
    def no_resuelve(host):
        raise DestinoBloqueado("no resuelve", "no_resuelve")

    monkeypatch.setattr(abuseipdb, "resolver_y_validar", no_resuelve)
    falsa = red(abuse(100))
    assert AbuseIPDB(CLAVE).consultar(URL).estado is Estado.DESCONOCIDO
    assert falsa.llamadas == []


def test_abuseipdb_prefiere_la_ipv4(red, monkeypatch):
    ips = ["2001:4860::8888", "8.8.4.4"]
    monkeypatch.setattr(abuseipdb, "resolver_y_validar", lambda host: ips)
    falsa = red(abuse(0))
    AbuseIPDB(CLAVE).consultar(URL)
    assert parse_qs(urlsplit(falsa.llamadas[0][0]).query)["ipAddress"] == ["8.8.4.4"]


def test_abuseipdb_cuota_diaria_agotada(red):
    falsa = red(abuse(100))
    fuente = AbuseIPDB(CLAVE)
    cache.set(fuente._clave_de_cuota(), 1000)
    respuesta = fuente.consultar(URL)
    assert (respuesta.estado, respuesta.motivo) == (Estado.FALLO, MOTIVO_CUOTA)
    assert falsa.llamadas == []


# --- En el resultado --------------------------------------------------------

@pytest.mark.django_db
def test_una_sospecha_se_muestra_como_sospecha_y_no_sube_a_peligroso(client, red, monkeypatch):
    red(virustotal(1, hace(hours=1)))
    monkeypatch.setattr(fuentes, "_FUENTES", [VirusTotal(CLAVE)])
    html = client.post(reverse("analizar"), {"enlace": URL}, follow=True).content.decode()
    assert "<dt>VirusTotal" in html
    assert "<dd>La marca como sospechosa</dd>" in html
    assert "Un servicio de seguridad la marca como sospechosa." in html
    assert ">Peligroso</h1>" not in html and ">Peligro alto</h1>" not in html
