"""Purga de análisis, reportes resueltos y pedidos de revisión resueltos (tarea 40).

Vive en curacion porque es la única app que puede importar de todas: el análisis y los
reportes están en apps distintas y un análisis no se borra mientras tenga un reporte
pendiente en la cola. Los plazos y el borrado en lotes están en core/retencion.py.
"""
from django.db.models import Q

from analisis.models import Analisis
from core import retencion
from core.retencion import DIAS_ANALISIS, DIAS_REPORTES_RESUELTOS, borrar_en_lotes, limite

from .models import ReporteDesacuerdo, SolicitudRevision


def _analisis_vencidos(ahora):
    """Análisis más antiguos que el plazo y sin reportes pendientes.

    Un reporte resuelto se borra con su análisis: la decisión ya quedó en la auditoría,
    que dura más.
    """
    pendientes = ReporteDesacuerdo.objects.filter(estado=ReporteDesacuerdo.Estado.PENDIENTE)
    return Analisis.objects.filter(fecha__lt=limite(ahora, DIAS_ANALISIS)).exclude(
        pk__in=pendientes.values("analisis_id"),
    )


def _resueltos_vencidos(modelo, ahora):
    """Resueltos antes del plazo. Sin fecha de resolución, cuenta la del reporte."""
    antes_de = limite(ahora, DIAS_REPORTES_RESUELTOS)
    return modelo.objects.filter(estado="resuelto").filter(
        Q(resuelto_en__lt=antes_de) | Q(resuelto_en__isnull=True, fecha__lt=antes_de),
    )


def _vencidos(ahora):
    return {
        "analisis": lambda: _analisis_vencidos(ahora),
        "reportes": lambda: _resueltos_vencidos(ReporteDesacuerdo, ahora),
        "pedidos": lambda: _resueltos_vencidos(SolicitudRevision, ahora),
    }


def contar(ahora) -> dict:
    return {nombre: consulta().count() for nombre, consulta in _vencidos(ahora).items()}


def purgar(ahora) -> dict:
    """Borra lo vencido en lotes y devuelve cuántas filas borró de cada tipo.

    Los reportes resueltos van primero, para que el conteo de análisis no los incluya.
    """
    totales = {}
    for nombre in ("reportes", "pedidos", "analisis"):
        consulta = _vencidos(ahora)[nombre]

        def lote(consulta=consulta):
            ids = list(consulta().order_by("pk").values_list("pk", flat=True)[: retencion.LOTE])
            # delete() devuelve el total con los reportes que caen en cascada; se cuenta
            # solo la tabla principal.
            consulta().model.objects.filter(pk__in=ids).delete()
            return len(ids)

        totales[nombre] = borrar_en_lotes(lote)
    return totales
