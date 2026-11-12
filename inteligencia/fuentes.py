"""Interfaz común de las fuentes externas de Threat Intelligence.

Cada proveedor es una subclase de `Fuente` que escribe `_consultar`. La clase base
pone lo que comparten todas: circuit breaker, cuota diaria, presupuesto global y la
regla de que solo un análisis de las últimas 24 h puede decir «sin detecciones».
`consultar_fuentes` las llama en paralelo con un plazo total, y `resumir` entrega al
motor de riesgo el valor de la categoría.

Una fuente caída, que responde «desconocido» o con un análisis viejo nunca cuenta como
limpia. Nada de lo que responde un proveedor sale de la caché técnica: sus términos
prohíben guardarlo en la reputación o en las estadísticas.
"""

import hashlib
import logging
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import Enum

from django.conf import settings
from django.core.cache import cache, caches
from django.db import connections

from core.entrada import consumir_presupuesto_externo
from inteligencia.claves import registrar_clave

logger = logging.getLogger(__name__)

FALLOS_PARA_ABRIR = 3
SEGUNDOS_ABIERTO = 5 * 60
VIGENCIA_ANALISIS = timedelta(hours=24)
# Las respuestas crudas de terceros viven 24 h como máximo.
VIGENCIA_CRUDA_SEGUNDOS = 24 * 60 * 60
PLAZO_POR_FUENTE_SEGUNDOS = 4
# Plazo para todas las fuentes de un análisis, que se consultan a la vez.
PLAZO_FUENTES_SEGUNDOS = 6
# Desde este valor la fuente confirma página falsa o programa dañino. Menos es una sospecha.
VALOR_CONFIRMA = 100

MOTIVO_CIRCUITO = "circuito_abierto"
MOTIVO_CUOTA = "cuota_agotada"
MOTIVO_PRESUPUESTO = "presupuesto_agotado"
MOTIVO_TIEMPO = "tiempo_agotado"
MOTIVO_ERROR = "error"


class Estado(Enum):
    DETECCION = "deteccion"
    # Solo con un análisis de la URL de las últimas 24 h sin hallazgos.
    SIN_DETECCIONES = "sin_detecciones"
    # La fuente respondió, pero no tiene ese análisis. No aporta puntaje ni cobertura.
    DESCONOCIDO = "desconocido"
    FALLO = "fallo"


@dataclass(frozen=True)
class Respuesta:
    fuente: str
    estado: Estado
    # De 0 a 100, solo con detección.
    valor: int | None = None
    # Por qué falló, con los códigos MOTIVO_*.
    motivo: str = ""


@dataclass(frozen=True)
class Resumen:
    """Lo que el motor de riesgo necesita de las fuentes."""

    # Valor más alto entre las fuentes con evidencia; None si ninguna la tuvo.
    valor: int | None
    # Fuentes que confirman página falsa o programa dañino.
    confirmaciones: int


class Fuente:
    """Base de un adaptador. La subclase define `nombre` y escribe `_consultar`."""

    nombre = ""
    # Nombre que ve la persona en el detalle técnico.
    titulo = ""
    plazo_segundos = PLAZO_POR_FUENTE_SEGUNDOS
    # Consultas por día que permite el proveedor; None si no hay tope.
    cuota_diaria: int | None = None

    def __init__(self, clave: str = ""):
        self.clave = clave
        registrar_clave(clave)

    def disponible(self) -> bool:
        """False si la fuente no se puede usar, por ejemplo sin clave. Entonces se omite."""
        return True

    def consultar(self, url: str) -> Respuesta:
        """Consulta la fuente sin lanzar excepciones: un error es el estado «falló»."""
        if cache.get(self._clave("abierto")):
            return self.fallo(MOTIVO_CIRCUITO)
        if not self._queda_cuota():
            return self.fallo(MOTIVO_CUOTA)
        if not consumir_presupuesto_externo():
            return self.fallo(MOTIVO_PRESUPUESTO)
        self._gastar_cuota()
        try:
            respuesta = self._consultar(url)
        except Exception as error:
            # Solo el tipo: el mensaje de un error de red puede traer la URL del ciudadano.
            logger.warning("La fuente %s falló: %s", self.nombre, type(error).__name__)
            respuesta = self.fallo(MOTIVO_ERROR)
        if respuesta.estado is Estado.FALLO:
            self._anotar_fallo()
        else:
            cache.delete(self._clave("fallos"))
        return respuesta

    def _consultar(self, url: str) -> Respuesta:
        """Pregunta al proveedor con `core.net.pedir_url` y `plazo_segundos`."""
        raise NotImplementedError

    # Respuestas que arma la subclase

    def deteccion(self, valor: int = VALOR_CONFIRMA) -> Respuesta:
        return Respuesta(self.nombre, Estado.DETECCION, valor=valor)

    def sin_detecciones(self, analizado: datetime | None) -> Respuesta:
        """`analizado` es la fecha del análisis del proveedor. Si es viejo, no cuenta."""
        ahora = datetime.now(UTC)
        vigente = (
            analizado is not None
            and analizado.tzinfo is not None
            and ahora - VIGENCIA_ANALISIS <= analizado <= ahora
        )
        return Respuesta(self.nombre, Estado.SIN_DETECCIONES if vigente else Estado.DESCONOCIDO)

    def desconocido(self) -> Respuesta:
        return Respuesta(self.nombre, Estado.DESCONOCIDO)

    def fallo(self, motivo: str = MOTIVO_ERROR) -> Respuesta:
        return Respuesta(self.nombre, Estado.FALLO, motivo=motivo)

    # Respuesta cruda en la caché técnica

    def guardar_cruda(self, consulta: str, datos, segundos: int = VIGENCIA_CRUDA_SEGUNDOS) -> None:
        segundos = min(segundos, VIGENCIA_CRUDA_SEGUNDOS)
        caches["tecnica"].set(self._clave_cruda(consulta), datos, timeout=segundos)

    def leer_cruda(self, consulta: str):
        return caches["tecnica"].get(self._clave_cruda(consulta))

    def _clave_cruda(self, consulta: str) -> str:
        # La clave no revela la URL consultada.
        resumen = hashlib.sha256(consulta.encode("utf-8", "surrogatepass")).hexdigest()
        return f"cruda:{self.nombre}:{resumen}"

    # Circuit breaker y cuota. Viven en la caché compartida para que todos los procesos
    # los vean. Sin `cache.incr`, que en la tabla de Render reinicia la vigencia.

    def _clave(self, dato: str) -> str:
        return f"fuente:{self.nombre}:{dato}"

    def _anotar_fallo(self) -> None:
        fallos = cache.get(self._clave("fallos"), 0) + 1
        cache.set(self._clave("fallos"), fallos, timeout=VIGENCIA_CRUDA_SEGUNDOS)
        if fallos >= FALLOS_PARA_ABRIR:
            # Al vencer se deja pasar una consulta de prueba. Si falla, se abre otra vez.
            cache.set(self._clave("abierto"), True, timeout=SEGUNDOS_ABIERTO)

    def _clave_de_cuota(self) -> str:
        return self._clave(f"cuota:{datetime.now(UTC):%Y%m%d}")

    def _queda_cuota(self) -> bool:
        if self.cuota_diaria is None:
            return True
        return cache.get(self._clave_de_cuota(), 0) < self.cuota_diaria

    def _gastar_cuota(self) -> None:
        if self.cuota_diaria is None:
            return
        ahora = datetime.now(UTC)
        medianoche = (ahora + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        usadas = cache.get(self._clave_de_cuota(), 0) + 1
        segundos = int((medianoche - ahora).total_seconds()) + 60
        cache.set(self._clave_de_cuota(), usadas, timeout=segundos)


def fuentes_activas() -> list[Fuente]:
    """Las fuentes que se consultan en cada análisis.

    Una fuente que no está disponible, por ejemplo sin clave, se omite sin tocar el motor.
    """
    global _FUENTES
    if _FUENTES is None:
        _FUENTES = _crear_fuentes()
    return [fuente for fuente in _FUENTES if fuente.disponible()]


def _crear_fuentes() -> list[Fuente]:
    # Se importan aquí: cada adaptador importa este módulo.
    from inteligencia.safe_browsing import SafeBrowsing

    return [SafeBrowsing(settings.SAFE_BROWSING_API_KEY)]


# Se crean en la primera consulta, cuando los settings ya están cargados.
_FUENTES: list[Fuente] | None = None


def consultar_fuentes(
    fuentes: list[Fuente], url: str, plazo_segundos: float = PLAZO_FUENTES_SEGUNDOS
) -> list[Respuesta]:
    """Consulta todas las fuentes a la vez y devuelve una respuesta por cada una.

    En Render, Celery corre en modo eager y un grupo de tareas iría en serie: por eso
    son hilos. La que no termina dentro del plazo cuenta como «falló» y el análisis sigue.
    """
    if not fuentes:
        return []
    ejecutor = ThreadPoolExecutor(max_workers=len(fuentes), thread_name_prefix="fuente")
    futuros = {ejecutor.submit(_consultar_en_hilo, fuente, url): fuente for fuente in fuentes}
    terminados, _ = wait(futuros, timeout=plazo_segundos)
    # No se espera a las lentas: su propio plazo de red las corta.
    ejecutor.shutdown(wait=False, cancel_futures=True)
    return [
        futuro.result() if futuro in terminados else fuente.fallo(MOTIVO_TIEMPO)
        for futuro, fuente in futuros.items()
    ]


def _consultar_en_hilo(fuente: Fuente, url: str) -> Respuesta:
    try:
        return fuente.consultar(url)
    except Exception as error:
        # La caché compartida también puede fallar, y un hilo no debe tumbar el análisis.
        logger.warning("La fuente %s falló: %s", fuente.nombre, type(error).__name__)
        return fuente.fallo(MOTIVO_ERROR)
    finally:
        # Cada hilo abre su conexión a la base para la caché; Django no la cierra solo.
        connections.close_all()


def resumir(respuestas: list[Respuesta]) -> Resumen:
    """Valor de la categoría de fuentes: el más alto entre las que tienen evidencia."""
    valores = [
        respuesta.valor or 0
        for respuesta in respuestas
        if respuesta.estado in (Estado.DETECCION, Estado.SIN_DETECCIONES)
    ]
    return Resumen(
        valor=max(valores) if valores else None,
        confirmaciones=sum(1 for valor in valores if valor >= VALOR_CONFIRMA),
    )
