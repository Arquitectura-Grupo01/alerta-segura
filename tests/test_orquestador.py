"""Modelo del análisis, caché de resultados y orquestador, de punta a punta."""

import re
import threading
import uuid
from datetime import timedelta
from pathlib import Path

import pytest
from django.core.cache import cache, caches
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone

from analisis import orquestador
from analisis.models import Analisis
from analisis.normalizacion import normalizar
from core.models import InvalidacionDominio
from core.resultados import clave_de_resultado, leer_resultado
from inteligencia import fuentes as modulo_fuentes
from inteligencia.fuentes import Fuente
from motor import cache as cache_motor
from motor.cache import (
    descartar_resultado,
    guardar_resultado,
    invalidar_dominio,
    vigencia_segundos,
)
from motor.explicacion import OCUPADO, hace_cuanto
from motor.riesgo import VERSION_INICIAL, Nivel, Senales, calcular

pytestmark = pytest.mark.django_db

HORA = 3600
URL = "https://ejemplo.pe/confirmar?token=abc123"


class Contada(Fuente):
    """Fuente simulada que cuenta cuántas veces sale a consultar."""

    nombre = "contada"
    titulo = "Lista de prueba"

    def __init__(self, responder):
        super().__init__()
        self.responder = responder
        self.llamadas = 0

    def _consultar(self, url):
        self.llamadas += 1
        return self.responder(self)


@pytest.fixture
def fuente(monkeypatch):
    def poner(responder=lambda f: f.desconocido()):
        simulada = Contada(responder)
        monkeypatch.setattr(modulo_fuentes, "_FUENTES", [simulada])
        return simulada

    return poner


def analizar(client, enlace):
    return client.post(reverse("analizar"), {"enlace": enlace}, follow=True)


# --- Tarea 15: qué se guarda de cada análisis -------------------------------

def test_un_analisis_que_no_es_peligroso_guarda_solo_el_dominio(client):
    analizar(client, URL)
    guardado = Analisis.objects.get()
    assert guardado.dominio == "ejemplo.pe"
    assert guardado.url == ""
    assert guardado.nivel < Nivel.PELIGROSO
    todo = " ".join(str(valor) for valor in vars(guardado).values())
    assert "abc123" not in todo and "confirmar" not in todo


def test_un_analisis_peligroso_guarda_la_url_completa(client, fuente):
    fuente(lambda f: f.deteccion())
    analizar(client, URL)
    guardado = Analisis.objects.get()
    assert guardado.nivel == Nivel.PELIGROSO
    assert guardado.url == URL


def test_el_modelo_borra_la_url_de_un_resultado_leve_por_cualquier_camino():
    guardado = Analisis.objects.create(
        tipo_entrada="enlace", dominio="ejemplo.pe", url=URL, nivel=Nivel.TEN_CUIDADO,
        puntaje=10, cobertura=40, version_reglas="1",
    )
    guardado.refresh_from_db()
    assert guardado.url == ""


def test_cada_dato_de_las_estadisticas_tiene_su_campo(client, fuente):
    fuente(lambda f: f.deteccion())
    analizar(client, "http://192.0.2.10/verifica")
    guardado = Analisis.objects.get()
    assert guardado.tipo_entrada == "enlace"
    assert guardado.version_reglas == VERSION_INICIAL.numero
    assert guardado.senales["heuristicas"] == ["ip_como_dominio", "palabras_sospechosas"]
    assert guardado.pesos == {"fuentes": 40, "edad": 25, "heuristicas": 15, "marca": 10}
    assert "una_fuente_confirma" in guardado.reglas
    # De la fuente solo queda su estado, nunca su respuesta.
    assert guardado.fuentes == [
        {"fuente": "contada", "titulo": "Lista de prueba", "estado": "deteccion"}
    ]
    assert (guardado.desde_cache, guardado.departamento) == (False, "")
    assert isinstance(guardado.publico, uuid.UUID) and guardado.publico.version == 4


def test_el_modelo_no_tiene_campos_para_ip_texto_ni_imagenes():
    campos = {campo.name for campo in Analisis._meta.get_fields()}
    assert not campos & {"ip", "texto", "imagen", "captura", "mensaje", "usuario"}
    indices = {campo.name for campo in Analisis._meta.get_fields() if campo.db_index}
    assert {"fecha", "tipo_entrada", "nivel", "dominio"} <= indices


def test_cargar_datos_demo_crea_analisis_ficticios_sin_url_en_los_leves():
    call_command("cargar_datos_demo", cantidad=40, verbosity=0)
    assert Analisis.objects.count() == 40
    assert not Analisis.objects.filter(nivel__lt=Nivel.PELIGROSO).exclude(url="").exists()
    assert all(a.dominio.endswith((".example", ".test")) for a in Analisis.objects.all())


# --- Tarea 24: vigencias ----------------------------------------------------

@pytest.mark.parametrize(("senales", "nivel", "horas"), [
    # Seguro.
    (Senales(heuristicas=(), edad_dias=800, marca=0, fuentes=0), Nivel.SEGURO, 6),
    # Sin información: Ten cuidado solo porque la cobertura no alcanza.
    (Senales(heuristicas=()), Nivel.TEN_CUIDADO, 6),
    # Web de 3 días sin otras señales: Ten cuidado solo por esa regla.
    (Senales(heuristicas=(), edad_dias=20, marca=0, fuentes=0), Nivel.TEN_CUIDADO, 6),
    # Ten cuidado por su puntaje.
    (Senales(heuristicas=("ip_como_dominio",), edad_dias=200, marca=0, fuentes=50),
     Nivel.TEN_CUIDADO, 24),
    # La web nueva que sube de nivel usa la vigencia de su nivel.
    (Senales(heuristicas=(), edad_dias=3, marca=0, fuentes=100, fuentes_con_deteccion=1),
     Nivel.PELIGROSO, 72),
    (Senales(fuentes=100, fuentes_con_deteccion=2), Nivel.PELIGRO_ALTO, 72),
])
def test_cada_nivel_tiene_su_vigencia(senales, nivel, horas):
    veredicto = calcular(senales)
    assert veredicto.nivel == nivel
    assert vigencia_segundos(veredicto) == horas * HORA


def _datos(veredicto, dominio="ejemplo.pe", origen=""):
    return {
        "nivel": int(veredicto.nivel), "puntaje": veredicto.puntaje,
        "cobertura": veredicto.cobertura, "reglas": list(veredicto.reglas),
        "version": veredicto.version, "senales": {}, "fuentes": [], "dominio": dominio,
        "dominio_origen": origen, "redirecciones": 0, "motivos": [], "acciones": [],
        "fecha": timezone.now().isoformat(),
    }


def test_el_resultado_se_guarda_con_la_vigencia_de_su_nivel(monkeypatch):
    vigencias = []
    resultados = caches["resultados"]
    monkeypatch.setattr(
        resultados, "set", lambda clave, valor, timeout=None: vigencias.append(timeout)
    )
    alto = calcular(Senales(fuentes=100, fuentes_con_deteccion=2))
    guardar_resultado(URL, alto, _datos(alto))
    assert vigencias == [72 * HORA]


def test_la_clave_no_revela_la_url_y_va_en_la_cache_de_resultados():
    veredicto = calcular(Senales())
    guardar_resultado(URL, veredicto, _datos(veredicto))
    clave = clave_de_resultado(URL, veredicto.version)
    assert re.fullmatch(r"resultado:[0-9a-f]{64}", clave)
    assert "ejemplo" not in clave and "abc123" not in clave
    assert caches["resultados"].get(clave)["dominio"] == "ejemplo.pe"
    # Aparte de la caché de los contadores del rate limit.
    assert cache.get(clave) is None


# --- Tarea 24: invalidación -------------------------------------------------

def test_otra_version_de_reglas_no_ve_los_resultados_de_la_anterior():
    veredicto = calcular(Senales())
    guardar_resultado(URL, veredicto, _datos(veredicto))
    assert leer_resultado(URL, veredicto.version) is not None
    assert leer_resultado(URL, "2") is None


@pytest.mark.parametrize("invalidado", ["web-final.example", "acortador.example"])
def test_invalidar_un_dominio_deja_sin_efecto_todos_sus_resultados(invalidado):
    veredicto = calcular(Senales())
    datos = _datos(veredicto, dominio="web-final.example", origen="acortador.example")
    for ruta in ("a", "b"):
        guardar_resultado(f"https://acortador.example/{ruta}", veredicto, datos)
    guardar_resultado("https://otra.example/", veredicto, _datos(veredicto, "otra.example"))

    invalidar_dominio(invalidado)

    assert leer_resultado("https://acortador.example/a", veredicto.version) is None
    assert leer_resultado("https://acortador.example/b", veredicto.version) is None
    assert leer_resultado("https://otra.example/", veredicto.version) is not None


def test_el_contador_del_dominio_vive_en_una_tabla_y_sube_cada_vez():
    invalidar_dominio("ejemplo.pe")
    invalidar_dominio("ejemplo.pe")
    assert InvalidacionDominio.objects.get(dominio="ejemplo.pe").contador == 2
    # Vaciar las cachés no revive lo invalidado.
    cache.clear()
    caches["resultados"].clear()
    assert InvalidacionDominio.objects.get(dominio="ejemplo.pe").contador == 2


def test_un_resultado_guardado_despues_de_invalidar_vuelve_a_servir():
    veredicto = calcular(Senales())
    invalidar_dominio("ejemplo.pe")
    guardar_resultado(URL, veredicto, _datos(veredicto))
    assert leer_resultado(URL, veredicto.version) is not None


@pytest.mark.parametrize("entrada", ["texto", 7, [], {"nivel": 1}, None])
def test_una_entrada_danada_no_se_usa(entrada):
    caches["resultados"].set(clave_de_resultado(URL, "1"), entrada)
    assert leer_resultado(URL, "1") is None


def test_descartar_borra_la_entrada():
    veredicto = calcular(Senales())
    guardar_resultado(URL, veredicto, _datos(veredicto))
    descartar_resultado(URL, veredicto.version)
    assert leer_resultado(URL, veredicto.version) is None


# --- Tarea 25: de punta a punta ---------------------------------------------

def test_del_formulario_a_la_pagina_de_resultado_con_fuentes_simuladas(client, fuente):
    fuente(lambda f: f.deteccion())
    respuesta = client.post(reverse("analizar"), {"enlace": URL})
    guardado = Analisis.objects.get()
    # POST, redirect y GET: la dirección del resultado es un UUID y no lleva el enlace.
    assert respuesta.status_code == 302
    assert respuesta["Location"] == f"/resultado/{guardado.publico}/"
    assert "ejemplo" not in respuesta["Location"]

    pagina = client.get(respuesta["Location"])
    html = pagina.content.decode()
    assert pagina.status_code == 200
    assert pagina["Cache-Control"] == "no-store"
    assert 'id="resultado-nivel">Peligroso</h1>' in html
    assert "Una lista de seguridad la tiene reportada" in html
    assert "<dt>Lista de prueba" in html and "<dd>La tiene reportada</dd>" in html
    assert "<dt>Fecha del análisis" in html
    assert "Analizado hace" not in html


def test_la_segunda_consulta_sale_de_la_cache_con_cero_llamadas_externas(
    client, fuente, monkeypatch
):
    simulada = fuente(lambda f: f.deteccion())
    seguidos = []
    real = orquestador.seguir_enlace
    monkeypatch.setattr(
        orquestador, "seguir_enlace", lambda url: seguidos.append(url) or real(url)
    )

    primera = analizar(client, URL)
    # La misma dirección con parámetros de rastreo y otro orden de mayúsculas es la misma clave.
    segunda = analizar(client, "HTTPS://Ejemplo.pe/confirmar?token=abc123&utm_source=chat")

    assert (simulada.llamadas, len(seguidos)) == (1, 1)
    uno, dos = Analisis.objects.order_by("id")
    assert (uno.desde_cache, dos.desde_cache) == (False, True)
    assert uno.publico != dos.publico
    assert dos.fecha_analisis == uno.fecha_analisis
    assert (dos.nivel, dos.puntaje, dos.fuentes) == (uno.nivel, uno.puntaje, uno.fuentes)
    assert "Analizado hace menos de un minuto" in segunda.content.decode()
    assert "Analizado hace" not in primera.content.decode()
    motivos = re.compile(r'<ul class="motivos">(.*?)</ul>', re.S)
    assert motivos.search(primera.content.decode()).group(1) == motivos.search(
        segunda.content.decode()
    ).group(1)


def test_un_acierto_de_cache_tambien_pasa_por_el_rate_limit(client):
    for _ in range(30):
        assert client.post(reverse("analizar"), {"enlace": URL}).status_code == 302
    assert client.post(reverse("analizar"), {"enlace": URL}).status_code == 429
    assert Analisis.objects.filter(desde_cache=True).count() == 29


def test_tras_invalidar_el_dominio_se_analiza_de_nuevo(client, fuente):
    simulada = fuente()
    analizar(client, URL)
    invalidar_dominio("ejemplo.pe")
    analizar(client, URL)
    assert simulada.llamadas == 2
    assert not Analisis.objects.filter(desde_cache=True).exists()


def test_una_entrada_de_cache_alterada_se_descarta_y_se_recalcula(client, fuente):
    simulada = fuente()
    analizar(client, URL)
    enlace = normalizar(URL)
    clave = clave_de_resultado(enlace.url, VERSION_INICIAL.numero)
    entrada = caches["resultados"].get(clave)
    # Alguien cambia el nivel guardado: ya no coincide con sus señales.
    caches["resultados"].set(clave, {**entrada, "nivel": 0, "puntaje": 0})

    html = analizar(client, URL).content.decode()

    assert simulada.llamadas == 2
    assert ">Seguro</h1>" not in html
    assert caches["resultados"].get(clave)["nivel"] == entrada["nivel"]


def test_un_resultado_ajeno_no_se_puede_adivinar(client):
    analizar(client, URL)
    assert client.get(reverse("resultado", args=[uuid.uuid4()])).status_code == 404
    assert client.get("/resultado/1/").status_code == 404
    propio = reverse("resultado", args=[Analisis.objects.get().publico])
    assert client.post(propio).status_code == 405


def test_la_pagina_de_un_resultado_antiguo_dice_hace_cuanto_se_analizo(client):
    analizar(client, URL)
    analizar(client, URL)
    Analisis.objects.update(fecha_analisis=timezone.now() - timedelta(hours=3, minutes=5))
    guardado = Analisis.objects.get(desde_cache=True)
    html = client.get(reverse("resultado", args=[guardado.publico])).content.decode()
    assert ">Analizado hace 3 horas</p>" in html


@pytest.mark.parametrize(("segundos", "texto"), [
    (20, "hace menos de un minuto"), (60, "hace 1 minuto"), (59 * 60, "hace 59 minutos"),
    (3600, "hace 1 hora"), (23 * 3600, "hace 23 horas"), (24 * 3600, "hace 1 día"),
    (72 * 3600, "hace 3 días"),
])
def test_hace_cuanto(segundos, texto):
    assert hace_cuanto(segundos) == texto


def test_con_demasiados_analisis_a_la_vez_pide_esperar_sin_colgarse(client, monkeypatch):
    monkeypatch.setattr(orquestador, "_turnos", threading.BoundedSemaphore(1))
    monkeypatch.setattr(orquestador, "ESPERA_DE_TURNO_SEGUNDOS", 0.05)
    orquestador._turnos.acquire()
    respuesta = client.post(reverse("analizar"), {"enlace": URL})
    assert respuesta.status_code == 503
    assert respuesta["Retry-After"] == "10"
    assert OCUPADO in respuesta.content.decode()
    assert not Analisis.objects.exists()

    orquestador._turnos.release()
    assert client.post(reverse("analizar"), {"enlace": URL}).status_code == 302


def test_el_turno_se_devuelve_aunque_el_analisis_falle(monkeypatch):
    def romper(url):
        raise RuntimeError("fallo de prueba")

    monkeypatch.setattr(orquestador, "_turnos", threading.BoundedSemaphore(1))
    monkeypatch.setattr(orquestador, "seguir_enlace", romper)
    with pytest.raises(RuntimeError):
        orquestador.analizar_enlace(normalizar(URL))
    assert orquestador._turnos.acquire(blocking=False)


def test_solo_el_motor_escribe_en_la_cache_de_resultados():
    """Ningún otro módulo de la aplicación llama a set o delete sobre esa caché."""
    raiz = Path(cache_motor.__file__).resolve().parent.parent
    for app in ("analisis", "core", "inteligencia", "catalogo", "curacion"):
        for archivo in (raiz / app).rglob("*.py"):
            texto = archivo.read_text(encoding="utf-8")
            escribe = re.search(r'caches\[(CACHE|"resultados")\]\.(set|delete|clear)', texto)
            assert not escribe, archivo
