"""Tarea 29: reporte de desacuerdo."""

import ast
import re
import uuid
from dataclasses import asdict
from pathlib import Path

import pytest
from django.contrib import admin
from django.test import Client, RequestFactory
from django.urls import reverse

from analisis.models import Analisis
from core.resultados import leer_resultado
from curacion.admin import ReporteDesacuerdoAdmin
from curacion.models import ReporteDesacuerdo
from inteligencia import fuentes as modulo_fuentes
from inteligencia.fuentes import Fuente
from motor.riesgo import VERSION_INICIAL, Nivel, Senales

pytestmark = pytest.mark.django_db

URL = "https://ejemplo.pe/confirmar?token=abc123"
RAIZ = Path(__file__).resolve().parent.parent
SECCION = re.compile(r'<section class="desacuerdo".*?</section>', re.S)


class Detecta(Fuente):
    nombre = "detecta"
    titulo = "Lista de prueba"

    def _consultar(self, url):
        return self.deteccion()


@pytest.fixture
def peligroso(client, monkeypatch):
    """Un análisis Peligroso, guardado y con su resultado en la caché."""
    monkeypatch.setattr(modulo_fuentes, "_FUENTES", [Detecta()])
    client.post(reverse("analizar"), {"enlace": URL})
    analisis = Analisis.objects.get()
    assert analisis.nivel == Nivel.PELIGROSO
    return analisis


@pytest.fixture
def seguro():
    """Un análisis Seguro: todas las categorías con evidencia y ninguna señal."""
    senales = Senales(fuentes=0, edad_dias=4000, marca=0)
    return Analisis.objects.create(
        tipo_entrada=Analisis.Tipo.ENLACE, dominio="ejemplo.pe", nivel=Nivel.SEGURO,
        puntaje=0, cobertura=100, version_reglas=VERSION_INICIAL.numero,
        senales={**asdict(senales), "heuristicas": []},
    )


def reportar(client, analisis, tipo="era_legitimo", **extra):
    return client.post(reverse("reportar", args=[analisis.publico]), {"tipo": tipo}, **extra)


def seccion(respuesta) -> str:
    return SECCION.search(respuesta.content.decode()).group(0)


# --- Terminada cuando --------------------------------------------------------

def test_cincuenta_reportes_de_un_origen_dejan_diez_pendientes_y_no_cambian_el_veredicto(
    client, peligroso
):
    codigos = [reportar(client, peligroso).status_code for _ in range(50)]

    assert codigos == [302] * 10 + [429] * 40
    assert ReporteDesacuerdo.objects.count() == 10
    assert ReporteDesacuerdo.objects.filter(
        estado=ReporteDesacuerdo.Estado.PENDIENTE, tipo=ReporteDesacuerdo.Tipo.ERA_LEGITIMO
    ).count() == 10
    # Ni el veredicto guardado ni el de la caché se movieron.
    peligroso.refresh_from_db()
    assert peligroso.nivel == Nivel.PELIGROSO
    assert leer_resultado(peligroso.url, VERSION_INICIAL.numero)["nivel"] == Nivel.PELIGROSO
    pagina = client.get(reverse("resultado", args=[peligroso.publico]))
    assert 'id="resultado-nivel">Peligroso</h1>' in pagina.content.decode()
    # Quien vuelve a consultar el enlace recibe Peligroso desde la caché.
    client.post(reverse("analizar"), {"enlace": URL})
    otra = Analisis.objects.latest("id")
    assert (otra.desde_cache, otra.nivel) == (True, Nivel.PELIGROSO)


def test_el_limite_es_por_origen(client, peligroso):
    for _ in range(10):
        reportar(client, peligroso)
    assert reportar(client, peligroso).status_code == 429
    assert reportar(client, peligroso, REMOTE_ADDR="198.51.100.7").status_code == 302
    assert ReporteDesacuerdo.objects.count() == 11


def test_el_429_dice_cuando_volver_a_intentar(client, peligroso):
    for _ in range(10):
        reportar(client, peligroso)
    respuesta = reportar(client, peligroso)
    assert respuesta["Retry-After"] == "3600"


# --- El reporte y la página --------------------------------------------------

def test_el_resultado_ofrece_las_dos_opciones_con_su_token(client, peligroso):
    html = seccion(client.get(reverse("resultado", args=[peligroso.publico])))
    assert f'action="{reverse("reportar", args=[peligroso.publico])}"' in html
    assert 'method="post"' in html
    assert 'name="tipo" value="era_estafa">Sí, era estafa</button>' in html
    assert 'name="tipo" value="era_legitimo">No, era legítimo</button>' in html
    assert 'name="csrfmiddlewaretoken"' in html


def test_el_reporte_vuelve_al_resultado_y_agradece_sin_prometer_cambios(client, peligroso):
    respuesta = reportar(client, peligroso, "era_estafa")
    propio = reverse("resultado", args=[peligroso.publico])
    assert respuesta.status_code == 302
    assert respuesta["Location"] == f"{propio}?reporte=era_estafa#reporte"

    pagina = client.get(respuesta["Location"])
    html = seccion(pagina)
    assert pagina["Cache-Control"] == "no-store"
    assert "Gracias por contarnos" in html
    assert "<form" not in html
    for promesa in ("cambi", "corregi", "actualiz", "bajar"):
        assert promesa not in html.lower()


@pytest.mark.parametrize("tipo", ReporteDesacuerdo.Tipo.values)
def test_cada_tipo_tiene_su_agradecimiento(client, peligroso, tipo):
    """Los valores que `analisis` acepta en `?reporte=` son los de `ReporteDesacuerdo.Tipo`."""
    respuesta = reportar(client, peligroso, tipo)
    assert "Gracias por contarnos" in seccion(client.get(respuesta["Location"]))
    assert ReporteDesacuerdo.objects.get().tipo == tipo


def test_quien_dice_que_era_estafa_ve_los_pasos_de_la_guia(client, peligroso, seguro):
    # Desde Ten cuidado la guía está en la misma página; en Seguro se enlaza a /guia/.
    html = seccion(client.get(reportar(client, peligroso, "era_estafa")["Location"]))
    assert '<a href="#ya-hice-clic">sigue estos pasos</a>' in html
    html = seccion(client.get(reportar(client, seguro, "era_estafa")["Location"]))
    assert f'<a href="{reverse("guia")}">sigue estos pasos</a>' in html
    html = seccion(client.get(reportar(client, seguro, "era_legitimo")["Location"]))
    assert "sigue estos pasos" not in html


def test_un_valor_desconocido_en_la_direccion_no_se_muestra(client, peligroso):
    propio = reverse("resultado", args=[peligroso.publico])
    respuesta = client.get(propio, {"reporte": "<script>alert(1)</script>"})
    html = respuesta.content.decode()
    assert "<script>alert(1)</script>" not in html and "alert(1)" not in html
    assert "<form" in seccion(respuesta)


@pytest.mark.parametrize("datos", [{"tipo": "otro"}, {"tipo": ""}, {}])
def test_solo_se_aceptan_las_dos_opciones(client, peligroso, datos):
    respuesta = client.post(reverse("reportar", args=[peligroso.publico]), datos)
    assert respuesta.status_code == 400
    assert not ReporteDesacuerdo.objects.exists()


def test_un_resultado_que_no_existe_no_se_puede_reportar(client):
    assert reportar(client, Analisis(publico=uuid.uuid4())).status_code == 404
    assert client.post("/resultado/1/reporte/", {"tipo": "era_estafa"}).status_code == 404


def test_solo_se_reporta_por_post(client, peligroso):
    assert client.get(reverse("reportar", args=[peligroso.publico])).status_code == 405
    assert not ReporteDesacuerdo.objects.exists()


def test_sin_token_de_csrf_el_reporte_se_rechaza(peligroso):
    sin_token = Client(enforce_csrf_checks=True)
    assert reportar(sin_token, peligroso).status_code == 403
    assert not ReporteDesacuerdo.objects.exists()


# --- Qué se guarda -------------------------------------------------------------

def test_el_reporte_no_tiene_campos_para_la_persona():
    campos = {campo.name for campo in ReporteDesacuerdo._meta.get_fields()}
    assert campos == {"id", "analisis", "tipo", "estado", "fecha"}


def test_el_reporte_no_guarda_la_ip_ni_el_navegador(client, peligroso):
    reportar(
        client, peligroso, REMOTE_ADDR="203.0.113.45",
        HTTP_X_FORWARDED_FOR="198.51.100.23", HTTP_USER_AGENT="NavegadorDePrueba/1.0",
    )
    reporte = ReporteDesacuerdo.objects.get()
    todo = " ".join(str(valor) for valor in vars(reporte).values())
    for dato in ("203.0.113.45", "198.51.100.23", "NavegadorDePrueba"):
        assert dato not in todo
    assert (reporte.analisis, reporte.estado) == (peligroso, ReporteDesacuerdo.Estado.PENDIENTE)


def test_borrar_el_analisis_borra_sus_reportes(client, peligroso):
    reportar(client, peligroso)
    peligroso.delete()
    assert not ReporteDesacuerdo.objects.exists()


# --- Admin e imports -----------------------------------------------------------

def test_el_admin_muestra_los_reportes_solo_para_leer(client, django_user_model, peligroso):
    reportar(client, peligroso, "era_legitimo")
    modelo_admin = admin.site._registry[ReporteDesacuerdo]
    assert isinstance(modelo_admin, ReporteDesacuerdoAdmin)
    solicitud = RequestFactory().get("/")
    assert not modelo_admin.has_add_permission(solicitud)
    assert not modelo_admin.has_change_permission(solicitud)
    assert not modelo_admin.has_delete_permission(solicitud)

    client.force_login(django_user_model.objects.create_superuser("revisora", password="x"))
    lista = client.get(reverse("admin:curacion_reportedesacuerdo_changelist"))
    assert lista.status_code == 200
    assert "ejemplo.pe" in lista.content.decode()


def test_ninguna_app_importa_de_curacion():
    """AGENTS.md: curacion puede importar de todas, pero ninguna importa de curacion."""
    culpables = []
    for app in ("core", "analisis", "motor", "inteligencia", "catalogo"):
        for archivo in (RAIZ / app).rglob("*.py"):
            for nodo in ast.walk(ast.parse(archivo.read_text(encoding="utf-8"))):
                if isinstance(nodo, ast.ImportFrom) and (nodo.module or "").startswith("curacion"):
                    culpables.append(str(archivo.relative_to(RAIZ)))
                elif isinstance(nodo, ast.Import) and any(
                    alias.name.startswith("curacion") for alias in nodo.names
                ):
                    culpables.append(str(archivo.relative_to(RAIZ)))
    assert culpables == []
