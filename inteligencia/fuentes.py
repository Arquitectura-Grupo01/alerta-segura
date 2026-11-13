"""Interfaz común de las fuentes externas de Threat Intelligence.

Cada proveedor es una subclase de `Fuente` que escribe `_consultar`. La clase base
pone lo que comparten todas: circuit breaker, cuota diaria, presupuesto global y la
regla de que solo un análisis vigente puede decir «sin detecciones». La vigencia
depende de la edad de la web y la fija la versión de reglas: ver `aplicar_vigencia`.
`consultar_fuentes` las llama en paralelo con un plazo total, y `resumir` entrega al
motor de riesgo el valor de la categoría.

Una fuente caída, que responde «desconocido» o con un análisis viejo nunca cuenta como
limpia. Nada de lo que responde un proveedor sale de la caché técnica: sus términos
prohíben guardarlo en la reputación o en las estadísticas.
"""

import hashlib
import json
import logging
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import Enum

from django.conf import settings
from django.core.cache import cache, caches
from django.db import connections

from core.entrada import consumir_presupuesto_externo
from core.net import RESULTADO_OK, RESULTADO_TIEMPO_AGOTADO, pedir_url
from inteligencia.claves import registrar_clave

logger = logging.getLogger(__name__)

FALLOS_PARA_ABRIR = 3
SEGUNDOS_ABIERTO = 5 * 60
# Un análisis más viejo que esto nunca cuenta, tenga la edad que tenga la web. El plazo
# de cada análisis lo acorta después `aplicar_vigencia`.
VIGENCIA_MAXIMA = timedelta(days=30)
# Desde cuántas fuentes una sospecha cuenta. Una sola no alcanza: 1 antivirus entre 90
# o una IP compartida con reportes se equivocan seguido.
FUENTES_PARA_SOSPECHA = 2
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
# Matiza una detección: la fuente la marca como peligrosa, pero no dice de qué tipo ni
# hay acuerdo entre sus motores. No confirma nada por sí sola.
MOTIVO_SIN_CATEGORIA = "sin_categoria"
# Códigos con que un proveedor dice que se pasó su cuota. PhishTank usa 509.
CODIGOS_DE_CUOTA = frozenset({429, 509})


class FalloDeFuente(Exception):
    """La consulta falló de una forma esperada: red, tiempo, cuota o respuesta rara."""

    def __init__(self, motivo: str = MOTIVO_ERROR):
        super().__init__(motivo)
        self.motivo = motivo


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
    # Por qué falló o qué matiza el estado, con los códigos MOTIVO_*.
    motivo: str = ""
    # Lo que la fuente contó además del estado: motores, fechas, reportes. Son datos de un
    # tercero: solo se guardan en la caché técnica, con `guardar_detalles`.
    datos: dict = field(default_factory=dict)
    # Fecha del análisis del proveedor, solo con «sin detecciones».
    analizado: datetime | None = None


@dataclass(frozen=True)
class Resumen:
    """Lo que el motor de riesgo necesita de las fuentes."""

    # Valor más alto entre las fuentes con evidencia; None si ninguna la tuvo.
    valor: int | None
    # Fuentes que confirman página falsa o programa dañino.
    confirmaciones: int
    # Una fuente la marca como peligrosa sin decir de qué tipo y ninguna lo confirma.
    en_duda: bool = False


class Fuente:
    """Base de un adaptador. La subclase define `nombre` y escribe `_consultar`."""

    nombre = ""
    # Nombre que ve la persona en el detalle técnico.
    titulo = ""
    plazo_segundos = PLAZO_POR_FUENTE_SEGUNDOS
    # Consultas por día y por minuto que permite el proveedor; None si no hay tope.
    cuota_diaria: int | None = None
    cuota_por_minuto: int | None = None
    # Sin clave, una fuente que la necesita se omite.
    requiere_clave = False

    def __init__(self, clave: str = ""):
        self.clave = clave
        registrar_clave(clave)

    # True si `_consultar` recibe también la web, para dar su reputación.
    usa_web = False

    def disponible(self) -> bool:
        """False si la fuente no se puede usar, por ejemplo sin clave. Entonces se omite."""
        return bool(self.clave) or not self.requiere_clave

    def consultar(self, url: str, web: str = "") -> Respuesta:
        """Consulta la fuente sin lanzar excepciones: un error es el estado «falló».

        `web` es el nombre de la web de destino cuando tiene reputación propia. Va vacío
        en un alojamiento compartido, donde la web no dice nada de cada página.
        """
        if cache.get(self._clave("abierto")):
            return self.fallo(MOTIVO_CIRCUITO)
        if not self._queda_cuota():
            return self.fallo(MOTIVO_CUOTA)
        if not consumir_presupuesto_externo():
            return self.fallo(MOTIVO_PRESUPUESTO)
        self._gastar_cuota()
        try:
            respuesta = self._consultar(url, web) if self.usa_web else self._consultar(url)
        except FalloDeFuente as error:
            logger.warning("La fuente %s falló: %s", self.nombre, error.motivo)
            respuesta = self.fallo(error.motivo)
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
        """Pregunta al proveedor, normalmente con `pedir_json`."""
        raise NotImplementedError

    def pedir_json(
        self,
        url: str,
        *,
        metodo: str = "GET",
        encabezados: dict[str, str] | None = None,
        datos: dict[str, str] | None = None,
        codigos: tuple[int, ...] = (200,),
    ) -> tuple[int, object]:
        """Pide a la API del proveedor y devuelve (código HTTP, JSON leído).

        Sin redirecciones: la clave nunca llega a otro servidor. Un código que no está en
        `codigos`, una respuesta que no es JSON o un problema de red lanzan FalloDeFuente.
        """
        respuesta = pedir_url(
            url,
            metodo=metodo,
            encabezados=encabezados,
            datos=datos,
            max_redirecciones=0,
            plazo_segundos=self.plazo_segundos,
        )
        if respuesta.resultado == RESULTADO_TIEMPO_AGOTADO:
            raise FalloDeFuente(MOTIVO_TIEMPO)
        if respuesta.resultado != RESULTADO_OK:
            raise FalloDeFuente()
        if respuesta.codigo_http in CODIGOS_DE_CUOTA:
            raise FalloDeFuente(MOTIVO_CUOTA)
        if respuesta.codigo_http not in codigos:
            raise FalloDeFuente()
        try:
            return respuesta.codigo_http, json.loads(respuesta.cuerpo)
        except (ValueError, RecursionError) as error:
            raise FalloDeFuente() from error

    # Respuestas que arma la subclase

    def deteccion(
        self, valor: int = VALOR_CONFIRMA, datos: dict | None = None, motivo: str = ""
    ) -> Respuesta:
        return Respuesta(
            self.nombre, Estado.DETECCION, valor=valor, motivo=motivo, datos=datos or {}
        )

    def sin_detecciones(self, analizado: datetime | None, datos: dict | None = None) -> Respuesta:
        """`analizado` es la fecha del análisis del proveedor. Si es viejo, no cuenta."""
        ahora = datetime.now(UTC)
        vigente = (
            analizado is not None
            and analizado.tzinfo is not None
            and ahora - VIGENCIA_MAXIMA <= analizado <= ahora
        )
        if not vigente:
            return Respuesta(self.nombre, Estado.DESCONOCIDO, datos=datos or {})
        return Respuesta(
            self.nombre, Estado.SIN_DETECCIONES, datos=datos or {}, analizado=analizado
        )

    def otra_consulta(self) -> bool:
        """Reserva cuota para una segunda consulta dentro del mismo análisis."""
        if not self._queda_cuota():
            return False
        self._gastar_cuota()
        return True

    def desconocido(self, datos: dict | None = None) -> Respuesta:
        return Respuesta(self.nombre, Estado.DESCONOCIDO, datos=datos or {})

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

    def _clave_por_minuto(self) -> str:
        return self._clave(f"minuto:{datetime.now(UTC):%Y%m%d%H%M}")

    def _queda_cuota(self) -> bool:
        if self.cuota_diaria is not None:
            if cache.get(self._clave_de_cuota(), 0) >= self.cuota_diaria:
                return False
        if self.cuota_por_minuto is not None:
            if cache.get(self._clave_por_minuto(), 0) >= self.cuota_por_minuto:
                return False
        return True

    def _gastar_cuota(self) -> None:
        if self.cuota_diaria is not None:
            ahora = datetime.now(UTC)
            manana = ahora + timedelta(days=1)
            medianoche = manana.replace(hour=0, minute=0, second=0, microsecond=0)
            usadas = cache.get(self._clave_de_cuota(), 0) + 1
            segundos = int((medianoche - ahora).total_seconds()) + 60
            cache.set(self._clave_de_cuota(), usadas, timeout=segundos)
        if self.cuota_por_minuto is not None:
            usadas = cache.get(self._clave_por_minuto(), 0) + 1
            cache.set(self._clave_por_minuto(), usadas, timeout=120)


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
    from inteligencia.abuseipdb import AbuseIPDB
    from inteligencia.phishtank import PhishTank
    from inteligencia.safe_browsing import SafeBrowsing
    from inteligencia.urlhaus import URLhaus
    from inteligencia.urlscan import Urlscan
    from inteligencia.virustotal import VirusTotal

    return [
        SafeBrowsing(settings.SAFE_BROWSING_API_KEY),
        URLhaus(settings.ABUSE_CH_AUTH_KEY),
        PhishTank(settings.PHISHTANK_APP_KEY),
        VirusTotal(settings.VIRUSTOTAL_API_KEY),
        Urlscan(settings.URLSCAN_API_KEY),
        AbuseIPDB(settings.ABUSEIPDB_API_KEY),
    ]


# Se crean en la primera consulta, cuando los settings ya están cargados.
_FUENTES: list[Fuente] | None = None


def consultar_fuentes(
    fuentes: list[Fuente],
    url: str,
    plazo_segundos: float = PLAZO_FUENTES_SEGUNDOS,
    web: str = "",
) -> list[Respuesta]:
    """Consulta todas las fuentes a la vez y devuelve una respuesta por cada una.

    En Render, Celery corre en modo eager y un grupo de tareas iría en serie: por eso
    son hilos. La que no termina dentro del plazo cuenta como «falló» y el análisis sigue.
    """
    if not fuentes:
        return []
    ejecutor = ThreadPoolExecutor(max_workers=len(fuentes), thread_name_prefix="fuente")
    futuros = {
        ejecutor.submit(_consultar_en_hilo, fuente, url, web): fuente for fuente in fuentes
    }
    terminados, _ = wait(futuros, timeout=plazo_segundos)
    # No se espera a las lentas: su propio plazo de red las corta.
    ejecutor.shutdown(wait=False, cancel_futures=True)
    return [
        futuro.result() if futuro in terminados else fuente.fallo(MOTIVO_TIEMPO)
        for futuro, fuente in futuros.items()
    ]


def _consultar_en_hilo(fuente: Fuente, url: str, web: str = "") -> Respuesta:
    try:
        return fuente.consultar(url, web)
    except Exception as error:
        # La caché compartida también puede fallar, y un hilo no debe tumbar el análisis.
        logger.warning("La fuente %s falló: %s", fuente.nombre, type(error).__name__)
        return fuente.fallo(MOTIVO_ERROR)
    finally:
        # Cada hilo abre su conexión a la base para la caché; Django no la cierra solo.
        connections.close_all()


def aplicar_vigencia(respuestas: list[Respuesta], vigencia: timedelta) -> list[Respuesta]:
    """Deja como «desconocido» los análisis sin hallazgos más viejos que `vigencia`.

    La vigencia depende de la edad de la web, que se conoce después de consultar: un día
    para una web nueva o sin edad conocida y más para una antigua. Lo que contó la fuente
    se conserva para el detalle técnico.
    """
    limite = datetime.now(UTC) - vigencia
    return [
        Respuesta(respuesta.fuente, Estado.DESCONOCIDO, datos=respuesta.datos)
        if respuesta.estado is Estado.SIN_DETECCIONES
        and (respuesta.analizado is None or respuesta.analizado < limite)
        else respuesta
        for respuesta in respuestas
    ]


def edad_informada(respuestas: list[Respuesta]) -> int | None:
    """Edad de la web en días según las fuentes: la menor, o None si ninguna la dio.

    `conocida_dias` es un mínimo, desde cuándo la fuente conoce la web: sirve igual,
    porque la web tiene al menos esa edad.
    """
    edades = [
        respuesta.datos.get(dato)
        for respuesta in respuestas
        if respuesta.estado is not Estado.FALLO
        for dato in ("edad_web_dias", "conocida_dias")
    ]
    edades = [
        edad for edad in edades
        if isinstance(edad, int) and not isinstance(edad, bool) and edad >= 0
    ]
    return min(edades) if edades else None


def resumir(respuestas: list[Respuesta]) -> Resumen:
    """Valor de la categoría de fuentes: el más alto entre las que tienen evidencia.

    Una confirmación cuenta sola. Una sospecha cuenta desde FUENTES_PARA_SOSPECHA
    fuentes; una sola no suma puntaje ni impide que otra fuente diga «sin detecciones».
    """
    detecciones = [
        respuesta.valor or 0 for respuesta in respuestas if respuesta.estado is Estado.DETECCION
    ]
    confirmaciones = sum(1 for valor in detecciones if valor >= VALOR_CONFIRMA)
    sospechas = [valor for valor in detecciones if 0 < valor < VALOR_CONFIRMA]
    limpias = any(respuesta.estado is Estado.SIN_DETECCIONES for respuesta in respuestas)
    if confirmaciones:
        valor = max(detecciones)
    elif len(sospechas) >= FUENTES_PARA_SOSPECHA:
        valor = max(sospechas)
    elif limpias:
        valor = 0
    else:
        valor = None
    en_duda = not confirmaciones and any(
        respuesta.estado is Estado.DETECCION and respuesta.motivo == MOTIVO_SIN_CATEGORIA
        for respuesta in respuestas
    )
    return Resumen(valor=valor, confirmaciones=confirmaciones, en_duda=en_duda)


# Detalle de las fuentes: lo que cada una contó de una dirección, para el detalle técnico.

MAX_TEXTO_DE_DETALLE = 60
MAX_ELEMENTOS_DE_DETALLE = 4


def limpiar_datos(datos: dict) -> dict:
    """Deja solo datos simples y cortos: lo que no sirve se quita en vez de mostrarse vacío.

    Un proveedor puede cambiar su respuesta, y parte de ella la escribe quien montó la
    página (el nombre de un servidor, por ejemplo). Aquí se acota; la plantilla la escapa.
    """
    limpios = {}
    for nombre, valor in datos.items():
        if isinstance(valor, list):
            valor = [_texto(elemento) for elemento in valor[:MAX_ELEMENTOS_DE_DETALLE]]
            valor = [elemento for elemento in valor if elemento]
        elif isinstance(valor, str):
            valor = _texto(valor)
        elif isinstance(valor, bool):
            pass
        elif not isinstance(valor, int) or valor < 0:
            valor = None
        if valor not in (None, "", []):
            limpios[nombre] = valor
    return limpios


def _texto(valor) -> str:
    if not isinstance(valor, str):
        return ""
    visible = "".join(letra if letra.isprintable() else " " for letra in valor)
    return " ".join(visible.split())[:MAX_TEXTO_DE_DETALLE]


def fecha_iso(valor) -> str:
    """Una fecha del proveedor, en segundos o en texto ISO, como ISO en UTC. Vacío si no sirve."""
    try:
        if isinstance(valor, bool):
            return ""
        if isinstance(valor, int):
            fecha = datetime.fromtimestamp(valor, UTC)
        elif isinstance(valor, str):
            fecha = datetime.fromisoformat(valor.strip().replace(" UTC", "+00:00"))
            if fecha.tzinfo is None:
                fecha = fecha.replace(tzinfo=UTC)
        else:
            return ""
    except (ValueError, OverflowError, OSError):
        return ""
    return fecha.astimezone(UTC).isoformat(timespec="seconds")


def guardar_detalles(consulta: str, fuentes: list[Fuente], respuestas: list[Respuesta]) -> None:
    """Guarda en la caché técnica, 24 h, lo que cada fuente contó de un análisis."""
    detalles = {
        fuente.titulo or fuente.nombre: limpiar_datos(respuesta.datos)
        for fuente, respuesta in zip(fuentes, respuestas, strict=True)
    }
    detalles = {titulo: datos for titulo, datos in detalles.items() if datos}
    if not detalles:
        return
    try:
        caches["tecnica"].set(
            _clave_de_detalles(consulta), detalles, timeout=VIGENCIA_CRUDA_SEGUNDOS
        )
    except Exception as error:
        # El detalle es un extra: sin él, el resultado se muestra igual.
        logger.warning("No se guardó el detalle de las fuentes: %s", type(error).__name__)


def leer_detalles(consulta: str) -> dict[str, dict]:
    """Detalle por título de fuente. Vacío si venció, si no hubo o si la caché falla."""
    try:
        detalles = caches["tecnica"].get(_clave_de_detalles(consulta))
    except Exception as error:
        logger.warning("No se leyó el detalle de las fuentes: %s", type(error).__name__)
        return {}
    if not isinstance(detalles, dict):
        return {}
    return {
        titulo: limpiar_datos(datos)
        for titulo, datos in detalles.items()
        if isinstance(titulo, str) and isinstance(datos, dict)
    }


def _clave_de_detalles(consulta: str) -> str:
    return "detalle:" + hashlib.sha256(consulta.encode("utf-8", "surrogatepass")).hexdigest()
