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
    (_, opciones), *_ = falsa.llamadas
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

def motores(**por_resultado):
    """`last_analysis_results` con tantos motores por resultado: motores(phishing=7)."""
    resultados = {}
    for resultado, cantidad in por_resultado.items():
        categoria = "suspicious" if resultado == "suspicious" else "malicious"
        for numero in range(cantidad):
            resultados[f"Motor {resultado} {numero}"] = {
                "category": categoria, "result": resultado, "method": "blacklist",
            }
    return resultados


def virustotal(malicious, fecha, tipo="phishing"):
    atributos = {
        "last_analysis_stats": {"malicious": malicious, "harmless": 60},
        "last_analysis_results": motores(**{tipo: malicious if type(malicious) is int else 0}),
    }
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

ESCANEO = "0190a1b2-c3d4-7e5f-8a9b-0c1d2e3f4a5b"


def escaneo(fecha, **pagina):
    """Un resultado de la búsqueda, que no trae veredicto."""
    return {
        "_id": ESCANEO,
        "task": {"time": fecha.isoformat().replace("+00:00", "Z"), "url": URL},
        "page": {"url": URL, **pagina},
    }


def veredicto(malicioso, **general):
    return {"verdicts": {
        "overall": {"malicious": malicioso, "score": 100 if malicioso else 0, **general},
        "urlscan": {"brands": [{"name": "Banco de Prueba", "key": "bancoprueba"}]},
    }}


@pytest.fixture
def urlscan(monkeypatch):
    """Responde a la búsqueda exacta, al resultado de un escaneo y a la búsqueda por web."""

    def poner(exacta, resultado=None, de_la_web=None):
        llamadas = []

        def pedir(url, **opciones):
            llamadas.append(url)
            if "/result/" in url:
                return resultado or RespuestaSegura(RESULTADO_ERROR_DE_RED)
            if "page.domain" in parse_qs(urlsplit(url).query)["q"][0]:
                return api({"results": de_la_web or []})
            return api({"results": exacta})

        monkeypatch.setattr(fuentes, "pedir_url", pedir)
        return llamadas

    return poner


def test_urlscan_busca_la_direccion_exacta_o_su_destino_final(red):
    falsa = red(api({"results": []}))
    Urlscan(CLAVE).consultar('https://web.example/a"b\\c')
    (pedida, opciones), (por_web, _) = falsa.llamadas
    partes = urlsplit(pedida)
    assert f"{partes.scheme}://{partes.netloc}{partes.path}" == "https://urlscan.io/api/v1/search/"
    consulta = parse_qs(partes.query)["q"][0]
    frase = 'https://web.example/a\\"b\\\\c'
    assert consulta == f'task.url.keyword:"{frase}" OR page.url.keyword:"{frase}"'
    assert opciones["encabezados"] == {"API-Key": CLAVE}
    assert CLAVE not in pedida
    # Sin escaneos de esa dirección, pregunta por la web: ahí solo va el nombre.
    assert parse_qs(urlsplit(por_web).query)["q"] == ['page.domain:"web.example"']


def test_urlscan_pide_el_veredicto_del_escaneo_mas_reciente(urlscan):
    llamadas = urlscan([escaneo(hace(hours=1))], api(veredicto(True, categories=["phishing"])))
    resultado = Urlscan(CLAVE).consultar(URL)
    assert resultado.estado is Estado.DETECCION
    assert llamadas[1] == f"https://urlscan.io/api/v1/result/{ESCANEO}/"
    assert len(llamadas) == 2
    assert resultado.datos["tipos"] == ["pagina_falsa"]
    assert resultado.datos["marcas"] == ["Banco de Prueba"]
    assert resultado.datos["puntaje"] == 100


def test_urlscan_un_escaneo_limpio_de_hoy_es_sin_detecciones(urlscan):
    urlscan([escaneo(hace(hours=5), country="PE", apexDomainAgeDays=4000)], api(veredicto(False)))
    resultado = Urlscan(CLAVE).consultar(URL)
    assert resultado.estado is Estado.SIN_DETECCIONES
    assert (resultado.datos["pais"], resultado.datos["edad_web_dias"]) == ("PE", 4000)
    # Un escaneo limpio no tiene puntaje de riesgo que mostrar.
    assert resultado.datos["puntaje"] is None


@pytest.mark.parametrize(("exacta", "resultado"), [
    # Limpio pero viejo.
    ([escaneo(hace(days=30))], api(veredicto(False))),
    # El resultado no se pudo leer: no se puede afirmar que esté limpia.
    ([escaneo(hace(hours=1))], None),
    ([escaneo(hace(hours=1))], api({"verdicts": {"overall": {"score": 0}}})),
    ([escaneo(hace(hours=1))], api({"sin": "veredicto"})),
    ([escaneo(hace(hours=1))], api(b"<html>pesa demasiado</html>")),
    ([{"task": {"time": "no es fecha"}, "_id": ESCANEO}], api(veredicto(False))),
])
def test_urlscan_sin_un_escaneo_limpio_y_reciente_es_desconocido(urlscan, exacta, resultado):
    urlscan(exacta, resultado)
    assert Urlscan(CLAVE).consultar(URL).estado is Estado.DESCONOCIDO


def test_urlscan_no_pide_un_resultado_con_un_identificador_raro(urlscan):
    raro = {**escaneo(hace(hours=1)), "_id": "../../user/quotas"}
    llamadas = urlscan([raro], api(veredicto(True)))
    assert Urlscan(CLAVE).consultar(URL).estado is Estado.DESCONOCIDO
    assert len(llamadas) == 1


def test_urlscan_sin_escaneos_de_la_direccion_muestra_los_de_la_web_sin_veredicto(urlscan):
    llamadas = urlscan([], de_la_web=[escaneo(hace(hours=2), country="PE", asnname="Red SAC")])
    resultado = Urlscan(CLAVE).consultar(URL)
    assert resultado.estado is Estado.DESCONOCIDO
    assert resultado.datos["de_otra_pagina"] is True
    assert (resultado.datos["pais"], resultado.datos["proveedor"]) == ("PE", "Red SAC")
    # Nunca se pide el veredicto de otra página: no es el de esta dirección.
    assert not any("/result/" in llamada for llamada in llamadas)


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
    # Una sola sospecha no cuenta: hacen falta dos fuentes.
    assert resumir([respuesta]).valor is None
    resumen = resumir([respuesta, VirusTotal(CLAVE).deteccion(50)])
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
    assert "<b>VirusTotal</b> <span>La marca como sospechosa</span>" in html
    assert "<li>1 de 61 antivirus la marca como peligrosa.</li>" in html
    assert "Un solo servicio de seguridad la marca como sospechosa." in html
    assert ">Peligroso</h1>" not in html and ">Peligro alto</h1>" not in html


# --- Lo que cada fuente cuenta para el detalle técnico ----------------------

def test_virustotal_cuenta_motores_fechas_votos_y_nombres(red):
    red(api({"data": {"attributes": {
        "last_analysis_stats": {
            "malicious": 9, "suspicious": 2, "undetected": 32, "harmless": 50, "timeout": 0,
        },
        "last_analysis_date": 1794412864,
        "first_submission_date": 1502518296,
        "total_votes": {"harmless": 0, "malicious": 7},
        "threat_names": ["Mal/HTMLGen-A"],
    }}}))
    assert VirusTotal(CLAVE).consultar(URL).datos == {
        "motores_peligrosa": 9,
        "motores_sospechosa": 2,
        "motores_total": 93,
        "analizado": "2026-11-11T16:01:04+00:00",
        "primera_vez": "2017-08-12T06:11:36+00:00",
        "votos_peligrosa": 7,
        "votos_confiable": None,
        "amenazas": ["Mal/HTMLGen-A"],
        "tipos": [],
        # El ejemplo no trae lo que dijo cada motor.
        "sin_categoria": True,
    }


def test_virustotal_con_solo_el_conteo_no_inventa_el_resto(red):
    red(api({"data": {"attributes": {"last_analysis_stats": {"malicious": 4}}}}))
    resultado = VirusTotal(CLAVE).consultar(URL)
    # Sin lo que dijo cada motor no hay tipo: marca, pero no confirma.
    assert (resultado.estado, resultado.valor) == (Estado.DETECCION, 50)
    assert fuentes.limpiar_datos(resultado.datos) == {
        "motores_peligrosa": 4, "motores_total": 4, "sin_categoria": True,
    }


def test_urlhaus_cuenta_el_tipo_las_etiquetas_y_los_archivos(red):
    red(api({
        "query_status": "ok", "url_status": "online", "date_added": "2026-11-13 05:47:15 UTC",
        "tags": ["elf", "Mozi"], "payloads": [{"filename": "bin.sh"}],
    }))
    assert URLhaus(CLAVE).consultar(URL).datos == {
        "tipos": ["programa_danino"],
        "agregada": "2026-11-13T05:47:15+00:00",
        "familias": ["elf", "Mozi"],
        "archivos": 1,
    }


def test_urlhaus_dada_de_baja_lo_dice_y_no_es_deteccion(red):
    red(api({"query_status": "ok", "url_status": "offline", "tags": None, "payloads": None}))
    resultado = URLhaus(CLAVE).consultar(URL)
    assert resultado.estado is Estado.DESCONOCIDO
    assert resultado.datos["dada_de_baja"] is True


def test_abuseipdb_cuenta_los_reportes_y_donde_esta_el_servidor(red):
    red(api({"data": {
        "abuseConfidenceScore": 100, "countryCode": "DE", "isp": "Proveedor de prueba",
        "isTor": True, "totalReports": 472, "numDistinctUsers": 133,
        "lastReportedAt": "2026-11-13T03:32:24+00:00", "isWhitelisted": False,
    }}))
    assert AbuseIPDB(CLAVE).consultar(URL).datos == {
        "ip": "8.8.8.8",
        "pais": "DE",
        "proveedor": "Proveedor de prueba",
        "red_tor": True,
        "reportes": 472,
        "periodo_dias": 90,
        "personas": 133,
        "confianza": 100,
        "ultimo_reporte": "2026-11-13T03:32:24+00:00",
    }


def test_abuseipdb_sin_reportes_solo_dice_donde_esta(red):
    red(api({"data": {
        "abuseConfidenceScore": 0, "countryCode": "PE", "isp": "Red SAC", "isTor": False,
        "totalReports": 0, "numDistinctUsers": 0, "lastReportedAt": None,
    }}))
    resultado = AbuseIPDB(CLAVE).consultar(URL)
    assert resultado.estado is Estado.DESCONOCIDO
    assert fuentes.limpiar_datos(resultado.datos) == {
        "ip": "8.8.8.8", "pais": "PE", "proveedor": "Red SAC",
    }


# --- Detalle en la caché técnica --------------------------------------------

def test_limpiar_datos_quita_lo_vacio_y_acota_lo_que_escribe_un_tercero():
    datos = {
        "vacio": "", "nada": None, "lista_vacia": [], "negativo": -1, "decimal": 1.5,
        "objeto": {"a": 1}, "cero": 0, "falso": False, "cierto": True,
        "largo": "x" * 500, "con_saltos": "uno\n\tdos\x00  tres",
        "lista": ["a", "", 7, None, "b", "c", "d", "e", "f"],
    }
    assert fuentes.limpiar_datos(datos) == {
        "cero": 0, "falso": False, "cierto": True,
        "largo": "x" * fuentes.MAX_TEXTO_DE_DETALLE, "con_saltos": "uno dos tres",
        "lista": ["a"],
    }


@pytest.mark.parametrize(("valor", "esperado"), [
    (1794412864, "2026-11-11T16:01:04+00:00"),
    ("2026-11-13 05:47:15 UTC", "2026-11-13T05:47:15+00:00"),
    ("2026-11-12T15:10:49.513Z", "2026-11-12T15:10:49+00:00"),
    ("2026-11-13T00:32:24-03:00", "2026-11-13T03:32:24+00:00"),
    ("ayer", ""), (None, ""), (True, ""), (10 ** 30, ""), (-10 ** 30, ""),
])
def test_fecha_iso_lee_las_fechas_de_los_proveedores(valor, esperado):
    assert fuentes.fecha_iso(valor) == esperado


def test_los_detalles_se_guardan_un_dia_y_solo_en_la_cache_tecnica(monkeypatch):
    guardado = {}
    tecnica = fuentes.caches["tecnica"]
    monkeypatch.setattr(
        tecnica, "set", lambda clave, valor, timeout: guardado.update(valor=valor, timeout=timeout)
    )
    fuente = VirusTotal(CLAVE)
    respuesta = fuente.deteccion(datos={"motores_peligrosa": 3, "analizado": ""})
    fuentes.guardar_detalles("consulta", [fuente], [respuesta])
    assert guardado == {
        "valor": {"VirusTotal": {"motores_peligrosa": 3}},
        "timeout": fuentes.VIGENCIA_CRUDA_SEGUNDOS,
    }


def test_los_detalles_se_leen_por_titulo_y_sin_datos_no_se_guarda_nada():
    con_datos, sin_datos = VirusTotal(CLAVE), URLhaus(CLAVE)
    respuestas = [con_datos.deteccion(datos={"motores_peligrosa": 3}), sin_datos.desconocido()]
    fuentes.guardar_detalles("una", [con_datos, sin_datos], respuestas)
    fuentes.guardar_detalles("otra", [sin_datos], [sin_datos.desconocido()])
    assert fuentes.leer_detalles("una") == {"VirusTotal": {"motores_peligrosa": 3}}
    assert fuentes.leer_detalles("otra") == {}


def test_si_la_cache_tecnica_falla_el_detalle_se_omite(monkeypatch):
    def rota(*args, **kwargs):
        raise OSError("sin base")

    tecnica = fuentes.caches["tecnica"]
    monkeypatch.setattr(tecnica, "set", rota)
    monkeypatch.setattr(tecnica, "get", rota)
    fuente = VirusTotal(CLAVE)
    fuentes.guardar_detalles("x", [fuente], [fuente.deteccion(datos={"motores_peligrosa": 3})])
    assert fuentes.leer_detalles("x") == {}


def test_un_detalle_alterado_en_la_cache_se_limpia_al_leerlo():
    clave = fuentes._clave_de_detalles("x")
    fuentes.caches["tecnica"].set(clave, {"VirusTotal": {"amenazas": ["a" * 900]}, 7: {}, "B": 3})
    assert fuentes.leer_detalles("x") == {
        "VirusTotal": {"amenazas": ["a" * fuentes.MAX_TEXTO_DE_DETALLE]},
    }
    fuentes.caches["tecnica"].set(clave, "no es un diccionario")
    assert fuentes.leer_detalles("x") == {}


# --- Reputación de la web completa en VirusTotal -----------------------------

WEB = "www.web-de-prueba.example"


def informe_de_web(
    peligrosa=0, sospechosa=0, edad_dias=4000, rankings=True, hace_horas=48, ranking_dias=None
):
    ranking = {"rank": 5000}
    if ranking_dias is not None:
        ranking["timestamp"] = int(hace(days=ranking_dias).timestamp())
    atributos = {
        "last_analysis_stats": {
            "malicious": peligrosa, "suspicious": sospechosa, "harmless": 60, "undetected": 30,
        },
        "last_analysis_date": int(hace(hours=hace_horas).timestamp()),
        "popularity_ranks": {"Lista de prueba": ranking} if rankings else {},
    }
    if edad_dias is not None:
        atributos["creation_date"] = int(hace(days=edad_dias).timestamp())
    return api({"data": {"attributes": atributos}})


@pytest.fixture
def vt(monkeypatch):
    """Responde distinto a la consulta de la dirección y a la de la web."""

    def poner(direccion, web=None):
        llamadas = []

        def pedir(url, **opciones):
            llamadas.append(url)
            if "/domains/" in url:
                return web or RespuestaSegura(RESULTADO_ERROR_DE_RED)
            return direccion

        monkeypatch.setattr(fuentes, "pedir_url", pedir)
        return llamadas

    return poner


@pytest.mark.parametrize("direccion", [api({}, codigo=404), virustotal(0, hace(days=40))])
def test_virustotal_sin_analisis_vigente_de_la_direccion_usa_el_de_la_web_conocida(vt, direccion):
    llamadas = vt(direccion, informe_de_web())
    respuesta = VirusTotal(CLAVE).consultar(URL, WEB)
    assert respuesta.estado is Estado.SIN_DETECCIONES
    assert llamadas[1] == f"https://www.virustotal.com/api/v3/domains/{WEB}"
    assert respuesta.datos["por_la_web"] is True
    assert (respuesta.datos["web_peligrosa"], respuesta.datos["web_total"]) == (0, 90)
    assert respuesta.datos["edad_web_dias"] == 4000
    assert hace(hours=49) < respuesta.analizado < hace(hours=47)


@pytest.mark.parametrize("web", [
    informe_de_web(peligrosa=1),
    informe_de_web(sospechosa=1),
    # Con menos de un año o sin fecha, la web todavía no tiene historia.
    informe_de_web(edad_dias=200),
    informe_de_web(edad_dias=None),
    # Sin figurar en ningún ranking, nadie la conoce.
    informe_de_web(rankings=False),
    # El análisis de la web también puede ser muy viejo.
    informe_de_web(hace_horas=24 * 40),
    api({}, codigo=400),
    api({}, codigo=404),
    api({"otra": "forma"}),
    api({"data": {"attributes": {"last_analysis_stats": "texto"}}}),
    None,
])
def test_virustotal_una_web_que_no_es_conocida_y_limpia_no_cuenta(vt, web):
    vt(api({}, codigo=404), web)
    respuesta = VirusTotal(CLAVE).consultar(URL, WEB)
    assert respuesta.estado is Estado.DESCONOCIDO
    assert "por_la_web" not in respuesta.datos


def test_virustotal_una_deteccion_de_la_direccion_manda_sobre_la_web(vt):
    llamadas = vt(virustotal(5, hace(days=40)), informe_de_web())
    assert VirusTotal(CLAVE).consultar(URL, WEB).estado is Estado.DETECCION
    assert len(llamadas) == 1


def test_virustotal_con_un_analisis_de_hoy_no_gasta_la_consulta_de_la_web(vt):
    llamadas = vt(virustotal(0, hace(hours=2)), informe_de_web())
    assert VirusTotal(CLAVE).consultar(URL, WEB).estado is Estado.SIN_DETECCIONES
    assert len(llamadas) == 1


def test_virustotal_sin_web_no_pregunta_por_ella(vt):
    llamadas = vt(api({}, codigo=404), informe_de_web())
    assert VirusTotal(CLAVE).consultar(URL).estado is Estado.DESCONOCIDO
    assert len(llamadas) == 1


def test_virustotal_la_consulta_de_la_web_tambien_gasta_cuota(vt):
    llamadas = vt(api({}, codigo=404), informe_de_web())
    fuente = VirusTotal(CLAVE)
    webs = [WEB, "otra.example", "tercera.example"]
    estados = [fuente.consultar(URL, web).estado for web in webs]
    # 4 por minuto: dos análisis con sus dos consultas, y el tercero ya no sale.
    assert estados == [Estado.SIN_DETECCIONES, Estado.SIN_DETECCIONES, Estado.FALLO]
    assert len(llamadas) == 4


def test_virustotal_la_reputacion_de_una_web_se_pide_una_vez_al_dia(vt):
    llamadas = vt(api({}, codigo=404), informe_de_web())
    fuente = VirusTotal(CLAVE)
    respuestas = [fuente.consultar(f"{URL}/{pagina}", WEB) for pagina in ("a", "b", "c")]
    assert [respuesta.estado for respuesta in respuestas] == [Estado.SIN_DETECCIONES] * 3
    assert respuestas[2].datos == respuestas[0].datos
    # Tres direcciones y una sola consulta por la web.
    assert sum("/domains/" in llamada for llamada in llamadas) == 1
    # En la caché técnica queda un resumen, no el informe del proveedor.
    assert set(fuente.leer_cruda("web:" + WEB)) == {
        "peligrosa", "sospechosa", "total", "creada", "analizada", "en_ranking", "ranking_desde",
    }


def test_virustotal_una_web_que_no_se_pudo_consultar_no_queda_guardada(vt):
    vt(api({}, codigo=404), None)
    fuente = VirusTotal(CLAVE)
    fuente.consultar(URL, WEB)
    assert fuente.leer_cruda("web:" + WEB) is None


def test_virustotal_si_solo_queda_cuota_para_la_direccion_no_pregunta_por_la_web(vt):
    llamadas = vt(api({}, codigo=404), informe_de_web())
    fuente = VirusTotal(CLAVE)
    cache.set(fuente._clave_por_minuto(), 3)
    assert fuente.consultar(URL, WEB).estado is Estado.DESCONOCIDO
    assert len(llamadas) == 1


def test_virustotal_sin_fecha_de_creacion_vale_desde_cuando_conoce_la_web(vt):
    """Los .pe no publican su fecha: sirve el ranking más antiguo en que figura la web."""
    vt(api({}, codigo=404), informe_de_web(edad_dias=None, ranking_dias=900))
    respuesta = VirusTotal(CLAVE).consultar(URL, WEB)
    assert respuesta.estado is Estado.SIN_DETECCIONES
    assert respuesta.datos["conocida_dias"] == 900
    assert "edad_web_dias" not in respuesta.datos


def test_virustotal_sin_fecha_de_creacion_vale_la_primera_vez_que_vio_la_direccion(vt):
    direccion = api({"data": {"attributes": {
        "last_analysis_stats": {"malicious": 0, "harmless": 60},
        "last_analysis_date": int(hace(days=100).timestamp()),
        "first_submission_date": int(hace(days=2900).timestamp()),
    }}})
    vt(direccion, informe_de_web(edad_dias=None, ranking_dias=30))
    respuesta = VirusTotal(CLAVE).consultar(URL, WEB)
    assert respuesta.estado is Estado.SIN_DETECCIONES
    assert respuesta.datos["conocida_dias"] == 2900


def test_virustotal_una_web_conocida_hace_poco_no_cuenta(vt):
    vt(api({}, codigo=404), informe_de_web(edad_dias=None, ranking_dias=200))
    respuesta = VirusTotal(CLAVE).consultar(URL, WEB)
    assert respuesta.estado is Estado.DESCONOCIDO
    assert respuesta.datos["conocida_dias"] == 200


# --- VirusTotal: marcar no es confirmar ---------------------------------------
# Formas tomadas de respuestas reales del 2026-11-13, con motores de nombre ficticio.

def informe(fecha=None, **por_resultado):
    resultados = motores(**por_resultado)
    marcan = sum(1 for r in resultados.values() if r["category"] == "malicious")
    sospechan = len(resultados) - marcan
    return api({"data": {"attributes": {
        "last_analysis_stats": {
            "malicious": marcan, "suspicious": sospechan, "undetected": 31, "harmless": 58,
        },
        "last_analysis_results": resultados,
        "last_analysis_date": int((fecha or hace(hours=3)).timestamp()),
    }}})


# La web de una organización legítima: 3 motores dicen «malicious» y ninguno dice el tipo.
WEB_LEGITIMA_MARCADA = {"malicious": 3, "suspicious": 1}


def test_virustotal_tres_motores_sin_tipo_no_confirman(red):
    red(informe(**WEB_LEGITIMA_MARCADA))
    respuesta = VirusTotal(CLAVE).consultar(URL)
    assert (respuesta.estado, respuesta.valor) == (Estado.DETECCION, 50)
    assert respuesta.motivo == fuentes.MOTIVO_SIN_CATEGORIA
    assert respuesta.datos["sin_categoria"] is True and respuesta.datos["tipos"] == []
    resumen = resumir([respuesta])
    assert (resumen.valor, resumen.confirmaciones, resumen.en_duda) == (None, 0, True)


@pytest.mark.parametrize(("por_resultado", "tipos"), [
    ({"phishing": 7, "malicious": 1, "suspicious": 2}, ["pagina_falsa"]),
    ({"malware": 8, "malicious": 3, "suspicious": 1}, ["programa_danino"]),
    ({"phishing": 3, "malware": 4}, ["pagina_falsa", "programa_danino"]),
    ({"Phishing": 3}, ["pagina_falsa"]),
])
def test_virustotal_confirma_cuando_tres_motores_coinciden_en_el_tipo(red, por_resultado, tipos):
    red(informe(**por_resultado))
    respuesta = VirusTotal(CLAVE).consultar(URL)
    assert (respuesta.estado, respuesta.valor, respuesta.motivo) == (Estado.DETECCION, 100, "")
    assert respuesta.datos["tipos"] == tipos
    assert resumir([respuesta]).confirmaciones == 1


@pytest.mark.parametrize("por_resultado", [
    # Muchos motores, pero repartidos: ningún tipo llega a 3.
    {"phishing": 2, "malware": 2, "malicious": 2},
    {"malicious": 12},
    # «suspicious» no es «malicious», aunque el motor diga el tipo en otro campo.
    {"phishing": 2, "suspicious": 9},
    {"spam": 5},
])
def test_virustotal_sin_acuerdo_en_el_tipo_no_confirma(red, por_resultado):
    red(informe(**por_resultado))
    respuesta = VirusTotal(CLAVE).consultar(URL)
    assert respuesta.valor == 50
    assert resumir([respuesta]).confirmaciones == 0


def test_virustotal_un_motor_suelto_sigue_siendo_una_sospecha_que_sola_no_cuenta(red):
    red(informe(phishing=2))
    respuesta = VirusTotal(CLAVE).consultar(URL)
    assert (respuesta.valor, respuesta.motivo) == (50, "")
    resumen = resumir([respuesta])
    assert (resumen.valor, resumen.en_duda) == (None, False)


def test_un_programa_danino_real_sigue_detectado_por_la_lista_que_lo_confirma(red):
    """3 motores sin tipo en VirusTotal y la dirección en URLhaus: confirma URLhaus."""
    red(informe(malicious=3))
    de_virustotal = VirusTotal(CLAVE).consultar(URL)
    de_urlhaus = URLhaus(CLAVE).deteccion(datos={"tipos": ["programa_danino"]})
    resumen = resumir([de_virustotal, de_urlhaus])
    assert (resumen.valor, resumen.confirmaciones, resumen.en_duda) == (100, 1, False)


def test_dos_fuentes_que_solo_sospechan_cuentan_como_sospecha(red):
    red(informe(**WEB_LEGITIMA_MARCADA))
    resumen = resumir([VirusTotal(CLAVE).consultar(URL), AbuseIPDB(CLAVE).deteccion(50)])
    assert (resumen.valor, resumen.confirmaciones) == (50, 0)


# --- De punta a punta: el veredicto y lo que se le dice a la persona ----------

@pytest.fixture
def solo_virustotal(monkeypatch):
    def poner(por_url):
        def pedir(url, **opciones):
            for parte, respuesta in por_url.items():
                if base64.urlsafe_b64encode(parte.encode()).decode().rstrip("=") in url:
                    return respuesta
            return api({}, codigo=404)

        monkeypatch.setattr(fuentes, "pedir_url", pedir)
        monkeypatch.setattr(fuentes, "_FUENTES", [VirusTotal(CLAVE)])

    return poner


def analizar(client, enlace):
    return client.post(reverse("analizar"), {"enlace": enlace}, follow=True).content.decode()


@pytest.mark.django_db
def test_una_web_marcada_sin_tipo_no_sale_peligrosa_ni_se_la_acusa_de_robar(
    client, solo_virustotal
):
    solo_virustotal({"https://organizacion.example/": informe(**WEB_LEGITIMA_MARCADA)})
    html = analizar(client, "https://organizacion.example/")
    assert 'id="resultado-nivel">Ten cuidado</h1>' in html
    assert "Los servicios de seguridad no se ponen de acuerdo sobre esta web." in html
    assert (
        "<li>3 de 93 antivirus de VirusTotal la marcan como peligrosa, pero ninguno dice de qué "
        "tipo. No alcanza para confirmarlo.</li>"
    ) in html
    assert "<b>VirusTotal</b> <span>La marca como peligrosa, sin decir de qué tipo</span>" in html
    for acusacion in ("estafa", "robar", "banco o a una tienda", "página falsa", "claves o dinero"):
        assert acusacion not in html.split('class="motivos"')[1].split("</ul>")[0]
    assert "señales claras de estafa" not in html


@pytest.mark.django_db
def test_una_web_marcada_sin_tipo_tampoco_sale_segura(client, solo_virustotal, monkeypatch):
    """Evidencia contradictoria: otro servicio la ve limpia y la web es antigua."""
    from analisis import orquestador

    class Limpia(fuentes.Fuente):
        nombre = "limpia"
        titulo = "Otro servicio"

        def _consultar(self, url):
            return self.sin_detecciones(hace(hours=2))

    solo_virustotal({"https://organizacion.example/": informe(**WEB_LEGITIMA_MARCADA)})
    monkeypatch.setattr(fuentes, "_FUENTES", [VirusTotal(CLAVE), Limpia()])
    monkeypatch.setattr(orquestador, "edad_en_dias", lambda dominios: 9000)
    html = analizar(client, "https://organizacion.example/")
    assert 'id="resultado-nivel">Ten cuidado</h1>' in html
    assert "<li>El otro servicio de seguridad que consultamos no la tiene reportada.</li>" in html


@pytest.mark.django_db
def test_dos_direcciones_de_la_misma_web_reciben_veredictos_distintos(client, solo_virustotal):
    solo_virustotal({
        "https://organizacion.example/": informe(**WEB_LEGITIMA_MARCADA),
        "https://organizacion.example/archivo.com": informe(malware=8, malicious=3),
    })
    portada = analizar(client, "https://organizacion.example/")
    archivo = analizar(client, "https://organizacion.example/archivo.com")
    assert 'id="resultado-nivel">Ten cuidado</h1>' in portada
    assert 'id="resultado-nivel">Peligroso</h1>' in archivo
    assert "Está reportada como peligrosa. No la abras." in archivo
    assert "<li>VirusTotal la tiene reportada como programa dañino.</li>" in archivo
    assert "<li>11 de 100 antivirus la marcan como peligrosa.</li>" in archivo
    assert "Puede instalar un programa dañino en tu celular o computadora." in archivo
    assert "página falsa" not in archivo.split('class="motivos"')[1].split("</ul>")[0]


@pytest.mark.django_db
def test_una_pagina_falsa_real_sigue_saliendo_peligrosa_con_su_tipo(client, solo_virustotal):
    solo_virustotal({"https://banco-falso.example/": informe(phishing=7, suspicious=2)})
    html = analizar(client, "https://banco-falso.example/")
    assert 'id="resultado-nivel">Peligroso</h1>' in html
    assert "<li>VirusTotal la tiene reportada como página falsa.</li>" in html
    assert "Una página falsa copia a una web real para robarte claves o dinero." in html


@pytest.mark.django_db
def test_sin_saber_el_tipo_la_explicacion_no_lo_inventa(client, monkeypatch):
    class SinTipo(fuentes.Fuente):
        nombre = "sin_tipo"
        titulo = "Lista sin tipo"

        def _consultar(self, url):
            return self.deteccion()

    monkeypatch.setattr(fuentes, "_FUENTES", [SinTipo()])
    html = analizar(client, "https://reportada.example/")
    assert 'id="resultado-nivel">Peligroso</h1>' in html
    assert "<li>Lista sin tipo la tiene reportada como página falsa o peligrosa.</li>" in html
    assert "<li>No dicen de qué tipo es la amenaza, solo que es peligrosa.</li>" in html
    assert "suelen copiar a un banco" not in html and "robar" not in html.split("Qué hacer")[0]
