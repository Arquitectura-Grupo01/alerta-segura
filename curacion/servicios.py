"""Acciones de la consola de curación: invalidar resultados y resolver casos.

Cada acción exige el permiso de su rol (core/roles.py), lleva un motivo o una
justificación y deja un evento de auditoría. Ninguna escribe en la caché por su cuenta:
usan las funciones de `motor`, la única app que lo hace.
"""
import ipaddress

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import models, transaction
from django.utils import timezone

from analisis.normalizacion import URLInvalida, normalizar
from core.auditoria import MAX_LARGO_MOTIVO, registrar_evento
from core.enmascarado import enmascarar
from core.models import TipoEvento
from curacion.models import ReporteDesacuerdo, SolicitudRevision
from motor import reputacion
from motor.cache import invalidar_dominio, invalidar_url
from motor.riesgo import Nivel

ERROR_ENLACE = "Escribe un enlace o un dominio válido, por ejemplo ejemplo.pe."
ERROR_MOTIVO = "Escribe el motivo."
ERROR_MOTIVO_LARGO = f"El motivo puede tener hasta {MAX_LARGO_MOTIVO} caracteres."
ERROR_MOTIVO_CON_ENLACE = "El motivo no puede llevar enlaces ni direcciones IP."


class Alcance(models.TextChoices):
    URL = "url", "Solo esta dirección exacta"
    DOMINIO = "dominio", "Toda la web"


class Decision(models.TextChoices):
    CONFIRMAR = "confirmar", "Confirmar fraude"
    DESCARTAR = "descartar", "Descartar"
    FALSO_POSITIVO = "falso_positivo", "Marcar como falso positivo"


def _exigir_permiso(usuario, permiso):
    if not (usuario.is_active and usuario.is_staff and usuario.has_perm(permiso)):
        raise PermissionDenied


def _limpiar_motivo(motivo):
    motivo = (motivo or "").strip()
    if not motivo:
        raise ValidationError(ERROR_MOTIVO)
    if len(motivo) > MAX_LARGO_MOTIVO:
        raise ValidationError(ERROR_MOTIVO_LARGO)
    return motivo


def _dominio_para_auditoria(dominio):
    """El dominio, salvo que sea una IP: la auditoría no guarda ninguna IP."""
    try:
        ipaddress.ip_address(dominio.strip("[]"))
    except ValueError:
        return dominio
    return None


def _auditar(tipo, usuario, motivo, detalle):
    try:
        registrar_evento(tipo, usuario=usuario, motivo=motivo, detalle=detalle)
    except ValueError:
        # registrar_evento rechaza un motivo con una URL o una IP; el texto del analista
        # nunca llega a la auditoría sin pasar esa revisión.
        raise ValidationError(ERROR_MOTIVO_CON_ENLACE) from None


def invalidar_resultados(*, alcance, valor, motivo, usuario):
    """Obliga a recalcular el análisis de una URL exacta o de toda una web.

    No cambia ningún veredicto: la siguiente consulta corre el análisis completo y el
    motor decide de nuevo. Devuelve el dominio afectado.
    """
    _exigir_permiso(usuario, "core.change_invalidaciondominio")
    alcance = Alcance(alcance)
    motivo = _limpiar_motivo(motivo)
    try:
        enlace = normalizar(valor or "")
    except URLInvalida:
        raise ValidationError(ERROR_ENLACE) from None
    detalle = {"alcance": alcance.value, "dominio": _dominio_para_auditoria(enlace.dominio)}
    with transaction.atomic():
        _auditar(TipoEvento.INVALIDACION, usuario, motivo, detalle)
        if alcance == Alcance.DOMINIO:
            invalidar_dominio(enlace.dominio)
    if alcance == Alcance.URL:
        # La caché no participa de la transacción: se borra solo si la auditoría quedó.
        invalidar_url(enlace.url)
    return enlace.dominio


def pendientes_de(dominio):
    """Los reportes y pedidos de revisión pendientes de una web."""
    reportes = ReporteDesacuerdo.objects.filter(
        estado=ReporteDesacuerdo.Estado.PENDIENTE, analisis__dominio=dominio,
    ).select_related("analisis")
    solicitudes = SolicitudRevision.objects.filter(
        estado=SolicitudRevision.Estado.PENDIENTE, dominio=dominio,
    )
    return reportes, solicitudes


def resolver_caso(*, dominio, decision, solo_direcciones, justificacion, usuario):
    """Resuelve todos los pendientes de una web con una decisión justificada y auditada.

    Confirmar fraude deja la confirmación del analista en la reputación, que el motor
    convierte en el piso Peligro alto, y deja sin efecto los resultados guardados.
    Falso positivo quita esa confirmación y también obliga a recalcular. Descartar cierra
    los pendientes sin tocar la reputación ni la caché.

    Con `solo_direcciones`, la decisión vale para las direcciones exactas reportadas y no
    para toda la web, como en un alojamiento compartido. Solo hay direcciones guardadas de
    los análisis Peligroso o superiores.
    """
    _exigir_permiso(usuario, "curacion.change_reportedesacuerdo")
    decision = Decision(decision)
    justificacion = _limpiar_motivo(justificacion)
    with transaction.atomic():
        reportes, solicitudes = pendientes_de(dominio)
        reportes = list(reportes.select_for_update(of=("self",)))
        solicitudes = list(solicitudes.select_for_update())
        if not reportes and not solicitudes:
            raise ValidationError("Este caso ya no tiene pendientes.")
        urls = sorted({r.analisis.url for r in reportes if r.analisis.url})
        if solo_direcciones and decision != Decision.DESCARTAR and not urls:
            raise ValidationError(
                "No hay direcciones guardadas para este caso: decide sobre toda la web."
            )
        _auditar(TipoEvento.DECISION_CURACION, usuario, justificacion, {
            "decision": decision.value,
            "dominio": _dominio_para_auditoria(dominio),
            "solo_direcciones": bool(solo_direcciones),
            "reportes": len(reportes),
            "pedidos": len(solicitudes),
        })
        if decision != Decision.DESCARTAR:
            confirmado = decision == Decision.CONFIRMAR
            for url in (urls if solo_direcciones else [""]):
                reputacion.marcar_confirmado(dominio, confirmado, url=url)
        resolucion = {
            "estado": "resuelto",
            "decision": decision.value,
            # Se guarda enmascarado, como todo texto antes de guardarse.
            "justificacion": enmascarar(justificacion),
            "resuelto_por": usuario,
            "resuelto_en": timezone.now(),
        }
        ReporteDesacuerdo.objects.filter(pk__in=[r.pk for r in reportes]).update(**resolucion)
        SolicitudRevision.objects.filter(pk__in=[s.pk for s in solicitudes]).update(**resolucion)


def cola():
    """Los casos pendientes agrupados por web, de mayor a menor prioridad.

    Primero las webs con más reportes y pedidos parecidos, después las de nivel más alto
    y, al final, las más antiguas.
    """
    casos = {}
    reportes = ReporteDesacuerdo.objects.filter(estado=ReporteDesacuerdo.Estado.PENDIENTE)
    for fila in reportes.values("analisis__dominio", "analisis__nivel", "fecha", "tipo"):
        caso = _caso(casos, fila["analisis__dominio"], fila["fecha"])
        caso["nivel"] = max(caso["nivel"], fila["analisis__nivel"])
        caso["reportes"] += 1
        caso[fila["tipo"]] += 1
    solicitudes = SolicitudRevision.objects.filter(estado=SolicitudRevision.Estado.PENDIENTE)
    for fila in solicitudes.values("dominio", "fecha"):
        caso = _caso(casos, fila["dominio"], fila["fecha"])
        caso["pedidos"] += 1
    for caso in casos.values():
        caso["total"] = caso["reportes"] + caso["pedidos"]
        # Un pedido de revisión no trae análisis: sin reportes, el caso no tiene nivel.
        caso["nivel_texto"] = Nivel(caso["nivel"]).texto if caso["nivel"] >= 0 else ""
    return sorted(casos.values(), key=lambda c: (-c["total"], -c["nivel"], c["desde"]))


def _caso(casos, dominio, fecha):
    caso = casos.setdefault(dominio, {
        "dominio": dominio, "nivel": -1, "reportes": 0, "pedidos": 0, "desde": fecha,
        "era_estafa": 0, "era_legitimo": 0,
    })
    caso["desde"] = min(caso["desde"], fecha)
    return caso
