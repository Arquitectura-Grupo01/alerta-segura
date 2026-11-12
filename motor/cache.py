"""Escritura de la caché de resultados. Ningún otro módulo escribe en ella.

Un reporte ciudadano nunca pasa por aquí. Tampoco se guardan textos, imágenes ni
teléfonos: de una captura o un QR solo se guarda el resultado de cada URL extraída.
"""

from django.core.cache import caches
from django.db.models import F

from core.models import InvalidacionDominio
from core.resultados import CACHE, clave_de_resultado, contadores_de
from motor.riesgo import Nivel, Veredicto

HORA = 60 * 60
VIGENCIA_SEGUNDOS = {
    Nivel.SEGURO: 6 * HORA,
    Nivel.TEN_CUIDADO: 24 * HORA,
    Nivel.PELIGROSO: 72 * HORA,
    Nivel.PELIGRO_ALTO: 72 * HORA,
}
# Sin información, o Ten cuidado solo por ser una web nueva: se revisa pronto otra vez.
VIGENCIA_SIN_INFORMACION = 6 * HORA


def vigencia_segundos(veredicto: Veredicto) -> int:
    """Cuánto vive un resultado en la caché, según `docs/requisitos.md`.

    Un Ten cuidado que el puntaje no alcanzaba, y que salió solo por un piso como web
    nueva o poca información, dura 6 h. Si el nivel es mayor, usa la vigencia de ese nivel.
    """
    solo_por_piso = veredicto.nivel_puntaje < veredicto.nivel == Nivel.TEN_CUIDADO
    return VIGENCIA_SIN_INFORMACION if solo_por_piso else VIGENCIA_SEGUNDOS[veredicto.nivel]


def guardar_resultado(url: str, veredicto: Veredicto, datos: dict) -> None:
    """Guarda `datos` con la vigencia del nivel y los contadores vigentes de sus dominios."""
    dominios = (datos["dominio"], datos["dominio_origen"])
    entrada = {**datos, "contadores": contadores_de(dominios)}
    caches[CACHE].set(
        clave_de_resultado(url, veredicto.version), entrada, timeout=vigencia_segundos(veredicto)
    )


def descartar_resultado(url: str, version: str) -> None:
    """Borra una entrada dañada para que se calcule de nuevo."""
    caches[CACHE].delete(clave_de_resultado(url, version))


def invalidar_dominio(dominio: str) -> None:
    """Deja sin efecto todos los resultados guardados de un dominio."""
    _, creado = InvalidacionDominio.objects.get_or_create(dominio=dominio, defaults={"contador": 1})
    if not creado:
        InvalidacionDominio.objects.filter(dominio=dominio).update(contador=F("contador") + 1)
