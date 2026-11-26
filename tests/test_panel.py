"""Tarea 53: panel de estadísticas de la consola, inicio con accesos y descarga en CSV."""
import csv
import io
import re
from dataclasses import asdict
from datetime import date, datetime, timedelta
from datetime import timezone as tz

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from django_otp import DEVICE_ID_SESSION_KEY
from django_otp.plugins.otp_totp.models import TOTPDevice

from analisis.models import Analisis
from core.auditoria import registrar_evento
from core.cuentas import crear_cuenta_interna
from core.entrada import consumir_presupuesto_externo, presupuesto_externo_usado
from core.models import TipoEvento
from core.roles import ADMINISTRADOR, ANALISTA
from curacion import estadisticas, graficos
from curacion.estadisticas import Filtros
from curacion.models import ReporteDesacuerdo, SolicitudRevision
from inteligencia import fuentes as modulo_fuentes
from inteligencia.fuentes import Fuente
from motor.riesgo import VERSION_INICIAL, Nivel, Senales

pytestmark = pytest.mark.django_db

CLAVE = "clave-de-prueba-larga"
HOY = date(2026, 11, 20)
PERIODO = Filtros(desde=HOY - timedelta(days=6), hasta=HOY)


def consola_verificada(cuenta):
    """Un cliente propio con la sesión iniciada y el segundo factor ya verificado."""
    consola = Client()
    consola.force_login(cuenta)
    sesion = consola.session
    sesion[DEVICE_ID_SESSION_KEY] = TOTPDevice.objects.filter(user=cuenta).first().persistent_id
    sesion.save()
    return consola


def analisis(dominio="ejemplo.pe", nivel=Nivel.TEN_CUIDADO, fecha=None, **extra):
    senales = {**asdict(Senales(fuentes=0, edad_dias=4000, marca=0)), "heuristicas": []}
    datos = {
        "tipo_entrada": Analisis.Tipo.ENLACE, "dominio": dominio, "nivel": nivel,
        "puntaje": 30, "cobertura": 90, "version_reglas": VERSION_INICIAL.numero,
        "senales": senales, "fecha": fecha or datetime(2026, 11, 20, 15, tzinfo=tz.utc),
    }
    datos.update(extra)
    return Analisis.objects.create(**datos)


@pytest.fixture
def analista(ingresar_consola):
    cuenta, _, _ = crear_cuenta_interna("ana-panel", CLAVE, ANALISTA)
    return ingresar_consola(cuenta)


@pytest.fixture
def administrador():
    """En otro cliente, para usarlo junto al analista en el mismo test."""
    cuenta, _, _ = crear_cuenta_interna("admin-panel", CLAVE, ADMINISTRADOR)
    return consola_verificada(cuenta)


def panel(consola, **filtros):
    return consola.get(reverse("admin:panel"), filtros)


# --- Condiciones de término --------------------------------------------------

def test_un_analista_ve_el_panel_y_una_cuenta_sin_rol_no(analista, django_user_model,
                                                         ingresar_consola):
    assert panel(analista).status_code == 200
    sin_rol = django_user_model.objects.create_user("sin-rol", password=CLAVE, is_staff=True)
    consola = ingresar_consola(sin_rol)
    assert consola.get(reverse("admin:panel")).status_code == 403
    assert consola.get(reverse("admin:panel_csv")).status_code == 403


def test_sin_sesion_el_panel_redirige_al_ingreso(client):
    assert client.get(reverse("admin:panel")).status_code == 302
    assert client.get(reverse("admin:panel_csv")).status_code == 302


@pytest.mark.parametrize("texto", [
    "ejemplo' OR '1'='1", "'; DROP TABLE analisis_analisis; --", "%", "_", "\\", '"',
])
def test_un_filtro_con_comillas_no_rompe_la_consulta(analista, texto):
    analisis("ejemplo.pe", fecha=timezone.now())
    respuesta = panel(analista, dominio=texto)
    assert respuesta.status_code == 200
    # Se busca como texto literal: ninguna de estas cadenas está en "ejemplo.pe".
    assert respuesta.context["resumen"]["total"] == 0
    assert Analisis.objects.count() == 1


def test_por_departamento_oculta_los_grupos_de_menos_de_5():
    for _ in range(5):
        analisis(departamento="Lima")
    for _ in range(4):
        analisis(departamento="Tacna")
    analisis(departamento="Moquegua")
    regiones = estadisticas.por_departamento(estadisticas.analisis_filtrados(PERIODO))
    assert regiones["visibles"] == [{"departamento": "Lima", "cantidad": 5}]
    assert (regiones["ocultos"], regiones["grupos_ocultos"]) == (5, 2)


def test_el_panel_no_muestra_las_regiones_pequenas(analista):
    for _ in range(3):
        analisis(departamento="Tacna", fecha=timezone.now())
    html = panel(analista).content.decode()
    assert "Tacna" not in html
    assert "3 análisis en 1 grupos con menos de 5, ocultos." in html


# --- Cálculos ----------------------------------------------------------------

def test_el_resumen_cuenta_por_nivel_cache_y_webs():
    analisis("a.example", Nivel.SEGURO)
    analisis("a.example", Nivel.PELIGROSO, desde_cache=True)
    analisis("b.example", Nivel.PELIGRO_ALTO)
    analisis("c.example", Nivel.TEN_CUIDADO, fecha=datetime(2026, 1, 1, tzinfo=tz.utc))
    resumen = estadisticas.resumen(estadisticas.analisis_filtrados(PERIODO))
    assert resumen["total"] == 3
    assert resumen["dominios"] == 2
    assert [fila["cantidad"] for fila in resumen["por_nivel"]] == [1, 0, 1, 1]
    assert resumen["riesgosos"] == 2
    assert resumen["porcentaje_cache"] == 33.3


def test_los_dias_se_cuentan_en_hora_de_lima():
    # 03:00 UTC del 20 es todavía el 19 a las 22:00 en Lima.
    analisis(fecha=datetime(2026, 11, 20, 3, tzinfo=tz.utc))
    dias = {fila["dia"]: fila["total"] for fila in
            estadisticas.por_dia(estadisticas.analisis_filtrados(PERIODO), PERIODO)}
    assert dias[date(2026, 11, 19)] == 1
    assert dias[date(2026, 11, 20)] == 0
    assert len(dias) == 7


def test_el_periodo_va_de_medianoche_a_medianoche_de_lima():
    analisis(fecha=datetime(2026, 11, 21, 4, 59, tzinfo=tz.utc))  # 23:59 del 20 en Lima
    analisis(fecha=datetime(2026, 11, 21, 5, 0, tzinfo=tz.utc))  # 00:00 del 21 en Lima
    assert estadisticas.analisis_filtrados(PERIODO).count() == 1


def test_las_direcciones_completas_son_solo_las_peligrosas():
    analisis("a.example", Nivel.PELIGROSO, url="https://a.example/login")
    analisis("a.example", Nivel.PELIGROSO, url="https://a.example/login")
    # El modelo borra la URL de un análisis leve antes de guardarlo.
    analisis("b.example", Nivel.SEGURO, url="https://b.example/?token=abc123")
    urls = estadisticas.top_urls(estadisticas.analisis_filtrados(PERIODO))
    assert urls == [{"url": "https://a.example/login", "dominio": "a.example", "cantidad": 2,
                     "nivel": Nivel.PELIGROSO}]


def test_las_webs_peligrosas_excluyen_las_leves():
    analisis("leve.example", Nivel.TEN_CUIDADO)
    analisis("mala.example", Nivel.PELIGRO_ALTO)
    consulta = estadisticas.analisis_filtrados(PERIODO)
    assert [f["dominio"] for f in estadisticas.top_dominios(consulta, Nivel.PELIGROSO)] == [
        "mala.example",
    ]
    assert len(estadisticas.top_dominios(consulta)) == 2


def test_marcas_modalidades_reglas_y_heuristicas():
    senales = {**asdict(Senales()), "heuristicas": ["acortador", "punycode"]}
    analisis(marca_suplantada="Banco Ficticio", modalidad="bloqueo-de-cuenta",
             reglas=["web_nueva"], senales=senales)
    analisis(marca_suplantada="Banco Ficticio", reglas=["web_nueva", "cobertura_baja"],
             senales={**senales, "heuristicas": ["acortador"]})
    consulta = estadisticas.analisis_filtrados(PERIODO)
    assert estadisticas.top_marcas(consulta) == [
        {"marca_suplantada": "Banco Ficticio", "cantidad": 2, "dominios": 1},
    ]
    modalidad = estadisticas.top_modalidades(consulta)[0]
    assert modalidad["cantidad"] == 1 and "bloqueada" in modalidad["titulo"]
    frecuentes = estadisticas.senales_frecuentes(consulta)
    assert frecuentes["reglas"][0] == {"codigo": "web_nueva", "cantidad": 2}
    assert frecuentes["heuristicas"][0] == {"codigo": "acortador", "cantidad": 2}


def test_cuenta_el_estado_de_cada_fuente_sin_su_respuesta():
    detecta = {"nombre": "vt", "titulo": "VirusTotal", "estado": "deteccion", "valor": 100}
    duda = {"nombre": "vt", "titulo": "VirusTotal", "estado": "deteccion", "valor": 50}
    cae = {"nombre": "vt", "titulo": "VirusTotal", "estado": "fallo", "motivo": "error"}
    analisis(fuentes=[detecta])
    analisis(fuentes=[duda])
    analisis(fuentes=[cae])
    fila = estadisticas.fuentes_en_analisis(estadisticas.analisis_filtrados(PERIODO))[0]
    estados = dict(zip([c for c, _ in estadisticas.ESTADOS_FUENTE], fila["estados"], strict=True))
    assert fila["titulo"] == "VirusTotal" and fila["total"] == 3
    assert (estados["deteccion"], estados["sospecha"], estados["fallo"]) == (1, 1, 1)
    assert fila["respondio"] == 66.7


def test_el_estado_en_vivo_de_las_fuentes(monkeypatch):
    class Prueba(Fuente):
        nombre = "prueba"
        titulo = "Fuente de prueba"
        cuota_diaria = 100

    fuente = Prueba()
    monkeypatch.setattr(modulo_fuentes, "_FUENTES", [fuente])
    for _ in range(3):
        fuente._anotar_fallo()
    fuente._gastar_cuota()
    estado = modulo_fuentes.estado_operativo()[0]
    assert estado["circuito_abierto"] is True
    assert (estado["fallos"], estado["cuota_usada"], estado["cuota_diaria"]) == (3, 1, 100)


def test_el_presupuesto_externo_usado_de_la_hora():
    assert presupuesto_externo_usado() == 0
    consumir_presupuesto_externo()
    consumir_presupuesto_externo()
    assert presupuesto_externo_usado() == 2


# --- Lo que llega de los ciudadanos --------------------------------------------

def test_los_reportes_y_los_pedidos_llegan_al_panel(analista):
    peligroso = analisis("mala.example", Nivel.PELIGROSO, fecha=timezone.now(),
                         url="https://mala.example/pagar")
    ReporteDesacuerdo.objects.create(analisis=peligroso, tipo="era_estafa")
    ReporteDesacuerdo.objects.create(analisis=peligroso, tipo="era_legitimo")
    SolicitudRevision.objects.create(dominio="tienda.example", mensaje="Es mi tienda <b>real</b>")
    respuesta = panel(analista)
    html = respuesta.content.decode()
    assert respuesta.context["reportes"]["era_estafa"] == 1
    assert respuesta.context["reportes"]["era_legitimo"] == 1
    assert respuesta.context["pedidos"]["total"] == 1
    assert "https://mala.example/pagar" in html
    assert reverse("admin:curacion_caso", args=["mala.example"]) in html
    assert reverse("admin:curacion_caso", args=["tienda.example"]) in html
    # Lo que escribe un ciudadano se muestra escapado.
    assert "Es mi tienda &lt;b&gt;real&lt;/b&gt;" in html
    assert respuesta.context["pendientes"] == {"reportes": 2, "pedidos": 1, "casos": 2}


def test_la_seguridad_solo_la_ve_un_administrador(analista, administrador):
    registrar_evento(TipoEvento.BLOQUEO_CUENTA)
    assert "Seguridad y auditoría" not in panel(analista).content.decode()
    respuesta = panel(administrador)
    assert "Seguridad y auditoría" in respuesta.content.decode()
    bloqueos = {f["tipo"]: f["cantidad"] for f in respuesta.context["seguridad"]["por_tipo"]}
    assert bloqueos["bloqueo_cuenta"] == 1


# --- Filtros -------------------------------------------------------------------

def test_los_filtros_por_fecha_y_tipo(analista):
    analisis("vieja.example", fecha=datetime(2026, 1, 10, 15, tzinfo=tz.utc))
    analisis("nueva.example", fecha=datetime(2026, 11, 20, 15, tzinfo=tz.utc))
    respuesta = panel(analista, desde="2026-01-01", hasta="2026-01-31")
    assert respuesta.context["resumen"]["total"] == 1
    assert respuesta.context["top_dominios"][0]["dominio"] == "vieja.example"
    assert panel(analista, desde="2026-01-01", hasta="2026-01-31",
                 tipo="captura").context["resumen"]["total"] == 0


def test_un_periodo_invalido_muestra_el_error_y_usa_30_dias(analista):
    respuesta = panel(analista, desde="2026-11-20", hasta="2026-11-01")
    assert "anterior a «Hasta»" in respuesta.content.decode()
    assert respuesta.context["filtros"].dias == estadisticas.DIAS_POR_DEFECTO
    assert panel(analista, desde="2024-01-01", hasta="2026-01-01").context["filtros"].dias == 30


# --- Gráficos y CSP --------------------------------------------------------------

def test_el_tope_del_eje_es_redondo():
    assert [graficos._techo(n) for n in (0, 1, 7, 10, 11, 35, 120, 999)] == [
        1, 1, 10, 10, 20, 50, 200, 1000,
    ]


def test_las_barras_son_proporcionales():
    dias = [{"dia": HOY, "niveles": [5, 5, 0, 0], "total": 10},
            {"dia": HOY + timedelta(days=1), "niveles": [0, 0, 0, 0], "total": 0}]
    grafico = graficos.barras_por_dia(dias)
    tramos = grafico["barras"][0]["tramos"]
    assert grafico["tope"] == 10
    assert sum(t["alto"] for t in tramos) == pytest.approx(grafico["base"])
    assert grafico["barras"][1]["tramos"] == []


def test_el_panel_respeta_la_csp(analista):
    analisis(fecha=timezone.now(), nivel=Nivel.PELIGROSO)
    respuesta = panel(analista)
    html = respuesta.content.decode()
    assert "<svg" in html
    # El idioma español escribe los decimales con coma, que en un atributo SVG no vale.
    assert not re.search(r'(?:x|y|width|height)="\d+,\d', html)
    assert ' height="' in html
    assert " style=" not in html and "<style" not in html
    assert "<script>" not in html and " onclick=" not in html
    assert "unsafe-inline" not in respuesta.headers["Content-Security-Policy"]
    assert respuesta.headers["Cache-Control"].startswith("no-cache") or \
        "no-store" in respuesta.headers["Cache-Control"]


# --- CSV ---------------------------------------------------------------------------

def leer_csv(respuesta):
    texto = b"".join(respuesta.streaming_content).decode("utf-8").lstrip("﻿")
    return list(csv.reader(io.StringIO(texto)))


def test_el_csv_trae_los_analisis_del_periodo_sin_formulas(analista):
    analisis("ejemplo.pe", Nivel.PELIGROSO, fecha=timezone.now(),
             url="https://ejemplo.pe/login", marca_suplantada="=HYPERLINK(\"x\")")
    analisis("leve.example", Nivel.SEGURO, fecha=timezone.now(), marca_suplantada="+51 999")
    respuesta = analista.get(reverse("admin:panel_csv"))
    assert respuesta["Content-Type"].startswith("text/csv")
    assert respuesta["Content-Disposition"].startswith('attachment; filename="analisis_')
    filas = leer_csv(respuesta)
    assert filas[0][0] == "Fecha (Lima)"
    assert len(filas) == 3
    marcas = {fila[2]: fila[8] for fila in filas[1:]}
    assert marcas["ejemplo.pe"] == "'=HYPERLINK(\"x\")"
    assert marcas["leve.example"] == "'+51 999"
    urls = {fila[2]: fila[4] for fila in filas[1:]}
    assert urls == {"ejemplo.pe": "https://ejemplo.pe/login", "leve.example": ""}


def test_el_csv_respeta_los_filtros(analista):
    analisis("a.example", fecha=timezone.now())
    analisis("b.example", fecha=timezone.now())
    filas = leer_csv(analista.get(reverse("admin:panel_csv"), {"dominio": "a.ex"}))
    assert [fila[2] for fila in filas[1:]] == ["a.example"]


# --- Inicio de la consola ------------------------------------------------------------

def titulos(respuesta):
    return [acceso["titulo"] for acceso in respuesta.context["accesos"]]


def test_el_inicio_muestra_los_accesos_del_analista(analista):
    vistos = titulos(analista.get(reverse("admin:index")))
    assert vistos[:2] == ["Panel de estadísticas", "Cola de curación"]
    assert "Análisis" in vistos and "Invalidar resultados" in vistos
    for prohibido in ("Catálogo de marcas", "Auditoría", "Cuentas internas", "Reputación propia"):
        assert prohibido not in vistos


def test_el_inicio_muestra_todo_al_administrador(administrador):
    vistos = titulos(administrador.get(reverse("admin:index")))
    assert vistos == [
        "Panel de estadísticas", "Cola de curación", "Análisis", "Invalidar resultados",
        "Catálogo de marcas", "Reputación propia", "Auditoría", "Cuentas internas",
    ]


def test_la_consola_usa_la_linea_grafica_del_sitio(analista):
    html = analista.get(reverse("admin:index")).content.decode()
    assert "css/consola.css" in html
    assert "dark_mode.css" not in html and "theme-toggle" not in html
    # La página de ingreso, vista sin sesión, también.
    ingreso = Client().get(reverse("admin:login")).content.decode()
    assert "css/consola.css" in ingreso and "theme-toggle" not in ingreso


# --- Análisis y reputación en la consola ----------------------------------------------

def test_un_analista_busca_y_abre_los_analisis_sin_editarlos(analista):
    guardado = analisis("ejemplo.pe", Nivel.PELIGROSO, fecha=timezone.now(),
                        fuentes=[{"titulo": "URLhaus", "estado": "deteccion", "valor": 100}])
    analisis("otra.example", fecha=timezone.now())
    lista = analista.get(reverse("admin:analisis_analisis_changelist"), {"q": "ejemplo"})
    assert list(lista.context["cl"].result_list) == [guardado]
    assert '<span class="etiqueta-nivel nivel-2">Peligroso</span>' in lista.content.decode()
    ficha = analista.get(reverse("admin:analisis_analisis_change", args=[guardado.pk]))
    html = ficha.content.decode()
    assert "URLhaus: deteccion" in html
    assert reverse("resultado", args=[guardado.publico]) in html
    cambiar = reverse("admin:analisis_analisis_change", args=[guardado.pk])
    assert analista.post(cambiar, {"dominio": "x.example"}).status_code == 403
    borrar = reverse("admin:analisis_analisis_delete", args=[guardado.pk])
    assert analista.post(borrar, {"post": "yes"}).status_code == 403
    assert Analisis.objects.get(pk=guardado.pk).dominio == "ejemplo.pe"


def test_la_reputacion_la_ve_solo_un_administrador(analista, administrador):
    lista = reverse("admin:motor_reputacion_changelist")
    assert administrador.get(lista).status_code == 200
    assert analista.get(lista).status_code == 403


def test_sin_filtros_el_formulario_muestra_los_ultimos_30_dias(analista):
    filtros = Filtros.por_defecto()
    html = panel(analista).content.decode()
    assert f'value="{filtros.desde:%Y-%m-%d}"' in html
    assert f'value="{filtros.hasta:%Y-%m-%d}"' in html
