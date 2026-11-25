"""Tarea 37: cola de curación y marca de sondeo."""
from dataclasses import asdict

import pytest
from django.test import RequestFactory
from django.urls import reverse

from analisis.models import Analisis
from core import sondeo
from core.cuentas import crear_cuenta_interna
from core.models import EventoAuditoria, TipoEvento
from core.resultados import leer_resultado
from core.roles import ANALISTA
from curacion.models import ReporteDesacuerdo, SolicitudRevision
from inteligencia import fuentes as modulo_fuentes
from inteligencia.fuentes import Fuente
from motor.models import Reputacion
from motor.reputacion import huella
from motor.riesgo import VERSION_INICIAL, Nivel, Senales

pytestmark = pytest.mark.django_db

URL = "https://ejemplo.pe/confirmar?token=abc123"
JUSTIFICACION = "Copia el diseño de un banco y pide la clave"


class Detecta(Fuente):
    nombre = "detecta"
    titulo = "Lista de prueba"

    def _consultar(self, url):
        return self.deteccion()


@pytest.fixture
def analista(ingresar_consola):
    cuenta, _, _ = crear_cuenta_interna("ana-cola", "clave-de-prueba-larga", ANALISTA)
    return cuenta, ingresar_consola(cuenta)


@pytest.fixture
def peligroso(client, monkeypatch):
    """Un análisis Peligroso por una fuente, guardado y en la caché, con un reporte."""
    monkeypatch.setattr(modulo_fuentes, "_FUENTES", [Detecta()])
    client.post(reverse("analizar"), {"enlace": URL})
    analisis = Analisis.objects.get()
    assert analisis.nivel == Nivel.PELIGROSO
    ReporteDesacuerdo.objects.create(analisis=analisis, tipo="era_estafa")
    return analisis


def analisis_de(dominio, nivel=Nivel.TEN_CUIDADO):
    senales = Senales(fuentes=0, edad_dias=4000, marca=0)
    return Analisis.objects.create(
        tipo_entrada=Analisis.Tipo.ENLACE, dominio=dominio, nivel=nivel, puntaje=30,
        cobertura=100, version_reglas=VERSION_INICIAL.numero,
        senales={**asdict(senales), "heuristicas": []},
    )


def decidir(consola, dominio, decision, justificacion=JUSTIFICACION, solo_direcciones=False):
    datos = {"decision": decision, "justificacion": justificacion}
    if solo_direcciones:
        datos["solo_direcciones"] = "on"
    return consola.post(reverse("admin:curacion_caso", args=[dominio]), datos)


def nivel_actual(client):
    client.post(reverse("analizar"), {"enlace": URL})
    return Analisis.objects.latest("fecha").nivel


# --- Terminada cuando --------------------------------------------------------

def test_un_script_en_un_pedido_se_ve_escapado_y_con_csp(analista):
    """Condición de término de la tarea 37 y prueba obligatoria de XSS de docs/seguridad.md."""
    _, consola = analista
    SolicitudRevision.objects.create(dominio="ejemplo.pe", mensaje="<script>alert(1)</script>")
    respuesta = consola.get(reverse("admin:curacion_caso", args=["ejemplo.pe"]))
    html = respuesta.content.decode()
    assert respuesta.status_code == 200
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "<script>alert(1)" not in html
    csp = respuesta.headers["Content-Security-Policy"]
    assert "default-src 'self'" in csp and "unsafe-inline" not in csp


# --- La cola -----------------------------------------------------------------

def test_la_cola_prioriza_por_volumen_y_despues_por_nivel(analista):
    _, consola = analista
    for _ in range(3):
        ReporteDesacuerdo.objects.create(analisis=analisis_de("muchos.example"), tipo="era_estafa")
    ReporteDesacuerdo.objects.create(
        analisis=analisis_de("grave.example", Nivel.PELIGRO_ALTO), tipo="era_legitimo",
    )
    ReporteDesacuerdo.objects.create(
        analisis=analisis_de("leve.example", Nivel.SEGURO), tipo="era_estafa",
    )
    SolicitudRevision.objects.create(dominio="dueno.example", mensaje="Es mi tienda")
    respuesta = consola.get(reverse("admin:curacion_reportedesacuerdo_changelist"))
    orden = [caso["dominio"] for caso in respuesta.context["casos"]]
    assert orden[:3] == ["muchos.example", "grave.example", "leve.example"]
    assert set(orden) == {"muchos.example", "grave.example", "leve.example", "dueno.example"}


def test_los_casos_resueltos_salen_de_la_cola(peligroso, analista):
    _, consola = analista
    decidir(consola, "ejemplo.pe", "descartar")
    respuesta = consola.get(reverse("admin:curacion_reportedesacuerdo_changelist"))
    assert respuesta.context["casos"] == []


# --- Decisiones --------------------------------------------------------------

def test_confirmar_fraude_sube_a_peligro_alto_e_invalida_la_web(client, peligroso, analista):
    cuenta, consola = analista
    assert decidir(consola, "ejemplo.pe", "confirmar").status_code == 302
    fila = Reputacion.objects.get(tipo=Reputacion.Tipo.DOMINIO, clave="ejemplo.pe")
    assert fila.confirmado_por_analista
    assert leer_resultado(URL, VERSION_INICIAL.numero) is None
    assert nivel_actual(client) == Nivel.PELIGRO_ALTO

    reporte = ReporteDesacuerdo.objects.get()
    assert (reporte.estado, reporte.decision, reporte.resuelto_por) == (
        "resuelto", "confirmar", cuenta,
    )
    assert reporte.justificacion == JUSTIFICACION
    evento = EventoAuditoria.objects.get(tipo=TipoEvento.DECISION_CURACION)
    assert evento.usuario == cuenta and evento.motivo == JUSTIFICACION
    assert evento.detalle == {
        "decision": "confirmar", "dominio": "ejemplo.pe", "solo_direcciones": False,
        "reportes": 1, "pedidos": 0,
    }


def test_falso_positivo_quita_la_confirmacion_y_recalcula(client, peligroso, analista):
    _, consola = analista
    decidir(consola, "ejemplo.pe", "confirmar")
    assert nivel_actual(client) == Nivel.PELIGRO_ALTO
    ReporteDesacuerdo.objects.create(analisis=Analisis.objects.latest("fecha"), tipo="era_legitimo")

    decidir(consola, "ejemplo.pe", "falso_positivo")
    fila = Reputacion.objects.get(tipo=Reputacion.Tipo.DOMINIO, clave="ejemplo.pe")
    assert not fila.confirmado_por_analista
    # Vuelve a lo que dicen las demás señales: la fuente sigue detectándola.
    assert nivel_actual(client) == Nivel.PELIGROSO


def test_descartar_no_toca_la_reputacion_ni_la_cache(peligroso, analista):
    _, consola = analista
    decidir(consola, "ejemplo.pe", "descartar")
    assert not Reputacion.objects.filter(confirmado_por_analista=True).exists()
    assert leer_resultado(URL, VERSION_INICIAL.numero) is not None
    assert ReporteDesacuerdo.objects.get().estado == "resuelto"


def test_confirmar_solo_las_direcciones_reportadas(peligroso, analista):
    _, consola = analista
    decidir(consola, "ejemplo.pe", "confirmar", solo_direcciones=True)
    assert Reputacion.objects.get(
        tipo=Reputacion.Tipo.URL, clave=huella(peligroso.url),
    ).confirmado_por_analista
    assert not Reputacion.objects.get(
        tipo=Reputacion.Tipo.DOMINIO, clave="ejemplo.pe",
    ).confirmado_por_analista


def test_sin_direcciones_guardadas_no_se_decide_solo_por_direcciones(analista):
    _, consola = analista
    ReporteDesacuerdo.objects.create(analisis=analisis_de("leve.example"), tipo="era_estafa")
    respuesta = decidir(consola, "leve.example", "confirmar", solo_direcciones=True)
    assert "decide sobre toda la web" in respuesta.content.decode()
    assert ReporteDesacuerdo.objects.get().estado == "pendiente"


def test_la_justificacion_es_obligatoria_y_sin_enlaces(peligroso, analista):
    _, consola = analista
    assert decidir(consola, "ejemplo.pe", "confirmar", justificacion=" ").status_code == 200
    respuesta = decidir(consola, "ejemplo.pe", "confirmar", justificacion="Ver https://x.example")
    assert "no puede llevar enlaces" in respuesta.content.decode()
    assert ReporteDesacuerdo.objects.get().estado == "pendiente"
    assert not Reputacion.objects.filter(confirmado_por_analista=True).exists()
    assert not EventoAuditoria.objects.filter(tipo=TipoEvento.DECISION_CURACION).exists()


def test_la_justificacion_se_guarda_enmascarada(peligroso, analista):
    _, consola = analista
    decidir(consola, "ejemplo.pe", "descartar", justificacion="Lo confirmó el DNI 45678912")
    assert "45678912" not in ReporteDesacuerdo.objects.get().justificacion


def test_una_decision_resuelve_tambien_los_pedidos_del_dueno(peligroso, analista):
    _, consola = analista
    SolicitudRevision.objects.create(dominio="ejemplo.pe", mensaje="Es mi tienda")
    decidir(consola, "ejemplo.pe", "descartar")
    assert SolicitudRevision.objects.get().estado == "resuelto"


def test_un_caso_ya_resuelto_no_se_vuelve_a_decidir(peligroso, analista):
    _, consola = analista
    decidir(consola, "ejemplo.pe", "descartar")
    respuesta = decidir(consola, "ejemplo.pe", "confirmar")
    assert respuesta.status_code == 200
    assert EventoAuditoria.objects.filter(tipo=TipoEvento.DECISION_CURACION).count() == 1


def test_una_cuenta_sin_rol_no_abre_la_cola_ni_decide(
    peligroso, django_user_model, ingresar_consola,
):
    sin_rol = django_user_model.objects.create_user("sin-rol", password="x" * 14, is_staff=True)
    consola = ingresar_consola(sin_rol)
    assert consola.get(reverse("admin:curacion_reportedesacuerdo_changelist")).status_code == 403
    assert decidir(consola, "ejemplo.pe", "confirmar").status_code == 403
    assert ReporteDesacuerdo.objects.get().estado == "pendiente"


def test_los_reportes_no_se_editan_a_mano(peligroso, analista):
    _, consola = analista
    reporte = ReporteDesacuerdo.objects.get()
    cambiar = reverse("admin:curacion_reportedesacuerdo_change", args=[reporte.pk])
    assert consola.post(cambiar, {"estado": "resuelto"}).status_code == 403
    assert ReporteDesacuerdo.objects.get().estado == "pendiente"


# --- Marca de sondeo -----------------------------------------------------------

def consulta_desde(ip):
    return RequestFactory().post("/analizar/", REMOTE_ADDR=ip)


def test_diez_direcciones_de_una_web_desde_un_origen_marcan_sondeo():
    solicitud = consulta_desde("203.0.113.7")
    for numero in range(sondeo.UMBRAL_VARIANTES - 1):
        sondeo.anotar_consulta(solicitud, "ejemplo.pe", f"https://ejemplo.pe/p{numero}")
    # Repetir una dirección no suma.
    sondeo.anotar_consulta(solicitud, "ejemplo.pe", "https://ejemplo.pe/p0")
    assert not sondeo.posible_sondeo("ejemplo.pe")
    sondeo.anotar_consulta(solicitud, "ejemplo.pe", "https://ejemplo.pe/ultima")
    assert sondeo.posible_sondeo("ejemplo.pe")
    assert not sondeo.posible_sondeo("otra.example")


def test_muchos_origenes_distintos_no_marcan_sondeo():
    for numero in range(sondeo.UMBRAL_VARIANTES * 2):
        sondeo.anotar_consulta(
            consulta_desde(f"203.0.113.{numero}"), "ejemplo.pe", f"https://ejemplo.pe/p{numero}",
        )
    assert not sondeo.posible_sondeo("ejemplo.pe")


def test_la_marca_de_sondeo_no_guarda_ips_ni_direcciones():
    from django.core.cache import cache

    solicitud = consulta_desde("203.0.113.7")
    for numero in range(sondeo.UMBRAL_VARIANTES):
        sondeo.anotar_consulta(solicitud, "ejemplo.pe", f"https://ejemplo.pe/token{numero}")
    guardado = repr({clave: cache.get(clave) for clave in cache._cache}) + repr(list(cache._cache))
    for texto in ("203.0.113.7", "ejemplo.pe", "token"):
        assert texto not in guardado


def test_cada_analisis_anota_la_consulta_y_la_cola_muestra_el_sondeo(client, analista):
    _, consola = analista
    for numero in range(sondeo.UMBRAL_VARIANTES):
        client.post(reverse("analizar"), {"enlace": f"https://ejemplo.pe/variante{numero}"})
    ReporteDesacuerdo.objects.create(analisis=Analisis.objects.first(), tipo="era_estafa")
    html = consola.get(reverse("admin:curacion_reportedesacuerdo_changelist")).content.decode()
    assert "Posible sondeo" in html
