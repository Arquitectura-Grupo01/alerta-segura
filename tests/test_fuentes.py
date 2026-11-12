"""Interfaz común de las fuentes externas: estados, circuit breaker, cuota y paralelismo."""

import logging
import sys
import threading
import time
from datetime import UTC, datetime, timedelta

import pytest
from django.core.cache import cache, caches
from django.urls import reverse

from core import entrada
from inteligencia import fuentes as modulo
from inteligencia.claves import MARCADOR, FiltroClaves, ocultar_claves
from inteligencia.fuentes import (
    FALLOS_PARA_ABRIR,
    MOTIVO_CIRCUITO,
    MOTIVO_CUOTA,
    MOTIVO_ERROR,
    MOTIVO_PRESUPUESTO,
    MOTIVO_TIEMPO,
    SEGUNDOS_ABIERTO,
    Estado,
    Fuente,
    consultar_fuentes,
    fuentes_activas,
    resumir,
)

URL = "https://web-de-prueba.example/pagina"
CLAVE = "clave-ficticia-de-prueba+/=123"


class Simulada(Fuente):
    """Fuente que responde lo que el test le pone y cuenta las consultas que recibe."""

    def __init__(self, nombre="simulada", responder=None, cuota=None, clave=""):
        super().__init__(clave)
        self.nombre = nombre
        self.cuota_diaria = cuota
        self.responder = responder or (lambda fuente, url: fuente.desconocido())
        self.consultas = 0

    def _consultar(self, url):
        self.consultas += 1
        return self.responder(self, url)


def hace(horas):
    return datetime.now(UTC) - timedelta(hours=horas)


def romper(fuente, url):
    raise RuntimeError(f"no se pudo pedir {url}?key={fuente.clave}")


# --- Los cuatro estados -----------------------------------------------------

def test_una_deteccion_trae_su_valor():
    fuente = Simulada(responder=lambda f, url: f.deteccion(50))
    respuesta = fuente.consultar(URL)
    assert (respuesta.fuente, respuesta.estado, respuesta.valor) == (
        "simulada", Estado.DETECCION, 50
    )


def test_sin_detecciones_exige_un_analisis_de_las_ultimas_24_horas():
    reciente = Simulada(responder=lambda f, url: f.sin_detecciones(hace(23)))
    assert reciente.consultar(URL).estado is Estado.SIN_DETECCIONES


@pytest.mark.parametrize("analizado", [
    hace(25),
    hace(24 * 30),
    None,
    # Sin zona horaria no se sabe de cuándo es, y una fecha futura no es un análisis.
    datetime.now(),
    hace(-2),
])
def test_un_analisis_viejo_o_sin_fecha_es_desconocido_y_no_limpio(analizado):
    fuente = Simulada(responder=lambda f, url: f.sin_detecciones(analizado))
    assert fuente.consultar(URL).estado is Estado.DESCONOCIDO


def test_una_fuente_que_no_tiene_el_analisis_responde_desconocido():
    assert Simulada().consultar(URL).estado is Estado.DESCONOCIDO


def test_un_error_de_la_fuente_es_el_estado_fallo_y_no_una_excepcion():
    respuesta = Simulada(responder=romper).consultar(URL)
    assert (respuesta.estado, respuesta.motivo) == (Estado.FALLO, MOTIVO_ERROR)


# --- Circuit breaker --------------------------------------------------------

def test_el_circuit_breaker_se_abre_al_tercer_fallo_seguido():
    fuente = Simulada(responder=romper)
    motivos = [fuente.consultar(URL).motivo for _ in range(FALLOS_PARA_ABRIR + 2)]
    assert motivos == [MOTIVO_ERROR] * 3 + [MOTIVO_CIRCUITO] * 2
    # Abierto, ya no llama al proveedor.
    assert fuente.consultas == FALLOS_PARA_ABRIR


def test_un_acierto_entre_fallos_reinicia_la_cuenta():
    respuestas = iter([romper, romper, None, romper, romper])

    def responder(fuente, url):
        accion = next(respuestas)
        return accion(fuente, url) if accion else fuente.desconocido()

    fuente = Simulada(responder=responder)
    estados = [fuente.consultar(URL).motivo for _ in range(5)]
    assert MOTIVO_CIRCUITO not in estados
    assert fuente.consultas == 5


def test_el_circuito_lo_ven_todos_los_procesos():
    Simulada("compartida", responder=romper).consultar(URL)
    Simulada("compartida", responder=romper).consultar(URL)
    Simulada("compartida", responder=romper).consultar(URL)
    otro_proceso = Simulada("compartida")
    assert otro_proceso.consultar(URL).motivo == MOTIVO_CIRCUITO
    # El de otra fuente sigue cerrado.
    assert Simulada("otra").consultar(URL).estado is Estado.DESCONOCIDO


def test_a_los_5_minutos_reintenta_y_si_falla_se_abre_otra_vez():
    fuente = Simulada(responder=romper)
    for _ in range(FALLOS_PARA_ABRIR):
        fuente.consultar(URL)
    # Pasaron los 5 minutos: la marca de circuito abierto venció.
    cache.delete(fuente._clave("abierto"))

    assert fuente.consultar(URL).motivo == MOTIVO_ERROR
    assert fuente.consultar(URL).motivo == MOTIVO_CIRCUITO
    assert fuente.consultas == FALLOS_PARA_ABRIR + 1


def test_el_circuito_abierto_dura_5_minutos(monkeypatch):
    vigencias = {}
    real = cache.set

    def anotar(clave, valor, timeout=None, **resto):
        vigencias[clave] = timeout
        return real(clave, valor, timeout=timeout, **resto)

    monkeypatch.setattr(cache, "set", anotar)
    fuente = Simulada(responder=romper)
    for _ in range(FALLOS_PARA_ABRIR):
        fuente.consultar(URL)
    assert vigencias[fuente._clave("abierto")] == SEGUNDOS_ABIERTO == 300


def test_si_se_recupera_el_circuito_se_cierra():
    fuente = Simulada(responder=romper)
    for _ in range(FALLOS_PARA_ABRIR):
        fuente.consultar(URL)
    cache.delete(fuente._clave("abierto"))
    fuente.responder = lambda f, url: f.deteccion()

    assert fuente.consultar(URL).estado is Estado.DETECCION
    fuente.responder = romper
    assert fuente.consultar(URL).motivo == MOTIVO_ERROR
    assert fuente.consultar(URL).motivo == MOTIVO_ERROR


# --- Cuota y presupuesto ----------------------------------------------------

def test_con_la_cuota_diaria_agotada_falla_sin_llamar_al_proveedor():
    fuente = Simulada(cuota=2)
    estados = [fuente.consultar(URL) for _ in range(4)]
    assert [r.motivo for r in estados] == ["", "", MOTIVO_CUOTA, MOTIVO_CUOTA]
    assert fuente.consultas == 2


def test_la_cuota_agotada_no_abre_el_circuito():
    fuente = Simulada(cuota=1)
    for _ in range(FALLOS_PARA_ABRIR + 2):
        fuente.consultar(URL)
    assert not cache.get(fuente._clave("abierto"))


def test_la_cuota_es_de_cada_fuente():
    Simulada("una", cuota=1).consultar(URL)
    assert Simulada("una", cuota=1).consultar(URL).motivo == MOTIVO_CUOTA
    assert Simulada("dos", cuota=1).consultar(URL).estado is Estado.DESCONOCIDO


def test_sin_presupuesto_global_la_fuente_no_se_consulta(monkeypatch):
    monkeypatch.setattr(entrada, "CONSULTAS_EXTERNAS_POR_HORA", 1)
    fuente = Simulada(cuota=10)
    assert fuente.consultar(URL).estado is Estado.DESCONOCIDO
    assert fuente.consultar(URL).motivo == MOTIVO_PRESUPUESTO
    assert fuente.consultas == 1
    # Lo que no se consultó no gasta la cuota del proveedor.
    assert cache.get(fuente._clave_de_cuota()) == 1


# --- Consulta en paralelo ---------------------------------------------------

def test_un_analisis_termina_aunque_fallen_todas_las_fuentes():
    todas = [Simulada(f"f{n}", responder=romper) for n in range(4)]
    respuestas = consultar_fuentes(todas, URL)
    assert [r.estado for r in respuestas] == [Estado.FALLO] * 4
    assert resumir(respuestas).valor is None


def test_las_fuentes_se_consultan_a_la_vez_y_responden_en_su_orden():
    barrera = threading.Barrier(3, timeout=5)

    def esperar_a_las_demas(fuente, url):
        barrera.wait()  # en serie, ninguna pasaría de aquí
        return fuente.deteccion()

    todas = [Simulada(f"f{n}", responder=esperar_a_las_demas) for n in range(3)]
    respuestas = consultar_fuentes(todas, URL)
    assert [(r.fuente, r.estado) for r in respuestas] == [
        ("f0", Estado.DETECCION), ("f1", Estado.DETECCION), ("f2", Estado.DETECCION),
    ]


def test_una_fuente_lenta_no_retiene_el_analisis():
    soltar = threading.Event()

    def lenta(fuente, url):
        soltar.wait(5)
        return fuente.deteccion()

    todas = [Simulada("lenta", responder=lenta), Simulada("rapida")]
    inicio = time.monotonic()
    respuestas = consultar_fuentes(todas, URL, plazo_segundos=0.2)
    tardo = time.monotonic() - inicio
    soltar.set()
    assert tardo < 2
    assert (respuestas[0].estado, respuestas[0].motivo) == (Estado.FALLO, MOTIVO_TIEMPO)
    assert respuestas[1].estado is Estado.DESCONOCIDO


def test_si_falla_la_cache_compartida_la_fuente_cuenta_como_caida(monkeypatch):
    class CacheCaida:
        def get(self, *args, **kwargs):
            raise ConnectionError("sin caché")

    # Se cambia en el módulo: la caché de Django es una conexión por hilo.
    monkeypatch.setattr(modulo, "cache", CacheCaida())
    [respuesta] = consultar_fuentes([Simulada()], URL)
    assert (respuesta.estado, respuesta.motivo) == (Estado.FALLO, MOTIVO_ERROR)


def test_sin_fuentes_no_hay_respuestas():
    assert consultar_fuentes([], URL) == []


# --- Resumen para el motor --------------------------------------------------

def test_el_resumen_toma_el_valor_mas_alto_y_cuenta_las_confirmaciones():
    f = Simulada()
    respuestas = [f.deteccion(100), f.deteccion(50), f.sin_detecciones(hace(1)), f.desconocido()]
    resumen = resumir(respuestas)
    assert (resumen.valor, resumen.confirmaciones) == (100, 1)


def test_un_analisis_vigente_sin_hallazgos_vale_cero():
    f = Simulada()
    resumen = resumir([f.sin_detecciones(hace(1)), f.fallo()])
    assert (resumen.valor, resumen.confirmaciones) == (0, 0)


def test_desconocido_y_fallo_no_son_evidencia():
    f = Simulada()
    resumen = resumir([f.desconocido(), f.fallo(), f.sin_detecciones(hace(48))])
    assert (resumen.valor, resumen.confirmaciones) == (None, 0)


# --- Caché técnica ----------------------------------------------------------

def test_la_respuesta_cruda_va_a_la_cache_tecnica_con_una_clave_que_no_revela_la_url():
    fuente = Simulada("proveedor")
    fuente.guardar_cruda(URL, {"malicioso": True})
    assert fuente.leer_cruda(URL) == {"malicioso": True}
    assert Simulada("otro").leer_cruda(URL) is None
    clave = fuente._clave_cruda(URL)
    assert "web-de-prueba" not in clave
    assert cache.get(clave) is None  # no está en la caché de los contadores


def test_la_respuesta_cruda_vive_24_horas_como_maximo(monkeypatch):
    vigencias = []
    tecnica = caches["tecnica"]
    monkeypatch.setattr(
        tecnica, "set", lambda clave, valor, timeout=None: vigencias.append(timeout)
    )
    fuente = Simulada()
    fuente.guardar_cruda(URL, "x")
    fuente.guardar_cruda(URL, "x", segundos=7 * 24 * 3600)
    fuente.guardar_cruda(URL, "x", segundos=600)
    assert vigencias == [86400, 86400, 600]


# --- Claves de API ----------------------------------------------------------

def test_una_clave_de_api_nunca_aparece_en_los_logs(caplog):
    fuente = Simulada(responder=romper, clave=CLAVE)
    with caplog.at_level(logging.DEBUG):
        fuente.consultar(URL)
        consultar_fuentes([fuente], URL)
    assert caplog.records
    assert CLAVE not in caplog.text
    # El mensaje del error puede traer la URL del ciudadano: tampoco se escribe.
    assert "web-de-prueba" not in caplog.text


def test_el_filtro_oculta_la_clave_en_el_mensaje_los_argumentos_y_la_traza():
    Simulada(clave=CLAVE)
    try:
        raise ValueError(f"GET https://api.example/v1?key={CLAVE}")
    except ValueError:
        registro = logging.LogRecord(
            "prueba", logging.ERROR, __file__, 1, "falló %s", (f"key={CLAVE}",), sys.exc_info()
        )
    registro.stack_info = f"pila con {CLAVE}"
    assert FiltroClaves().filter(registro) is True
    escrito = logging.Formatter().format(registro)
    assert CLAVE not in escrito
    assert escrito.count(MARCADOR) == 3


def test_tambien_oculta_la_clave_codificada_para_una_url():
    Simulada(clave=CLAVE)
    assert ocultar_claves("?key=clave-ficticia-de-prueba%2B%2F%3D123&x=1") == f"?key={MARCADOR}&x=1"


def test_el_filtro_de_claves_esta_en_el_log_de_la_aplicacion(settings):
    assert settings.LOGGING["filters"]["claves"]["()"] == "inteligencia.claves.FiltroClaves"
    assert settings.LOGGING["handlers"]["console"]["filters"] == ["claves", "enmascarar"]


# --- En el análisis ---------------------------------------------------------

def test_una_fuente_sin_clave_se_omite(monkeypatch):
    class ConClave(Simulada):
        def disponible(self):
            return bool(self.clave)

    monkeypatch.setattr(modulo, "_FUENTES", [ConClave("sin"), ConClave("con", clave=CLAVE)])
    assert [fuente.nombre for fuente in fuentes_activas()] == ["con"]


def test_una_deteccion_de_una_fuente_sube_el_resultado_a_peligroso(client, monkeypatch):
    vistas = []

    def detectar(fuente, url):
        vistas.append(url)
        return fuente.deteccion()

    monkeypatch.setattr(modulo, "_FUENTES", [Simulada(responder=detectar)])
    html = client.post(
        reverse("analizar"), {"enlace": "ejemplo.com/inicio?utm_source=chat"}
    ).content.decode()
    assert 'id="resultado-nivel">Peligroso</h1>' in html
    assert "Una lista de seguridad la tiene reportada" in html
    # La fuente no recibe los parámetros de rastreo.
    assert vistas == ["https://ejemplo.com/inicio"]


def test_el_analisis_termina_aunque_todas_las_fuentes_fallen(client, monkeypatch):
    monkeypatch.setattr(modulo, "_FUENTES", [Simulada("a", romper), Simulada("b", romper)])
    res = client.post(reverse("analizar"), {"enlace": "ejemplo.com/inicio"})
    html = res.content.decode()
    assert res.status_code == 200
    assert 'id="resultado-nivel">Ten cuidado</h1>' in html
    assert "No pudimos consultar los servicios de seguridad." in html
    assert html.count("<dd>No respondió</dd>") == 2
