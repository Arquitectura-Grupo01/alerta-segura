"""Lectura y escritura de la base de reputación propia. Ver `motor.models.Reputacion`."""

import hashlib
import logging
from datetime import date, timedelta

from django.db import DatabaseError, transaction
from django.db.models import F, Q
from django.utils import timezone

from motor.cache import invalidar_dominio
from motor.models import Reputacion

logger = logging.getLogger(__name__)

REPORTE_ESTAFA = "era_estafa"
REPORTE_LEGITIMO = "era_legitimo"


def huella(url: str) -> str:
    """SHA-256 de la dirección normalizada: identifica la dirección sin guardarla."""
    return hashlib.sha256(url.encode("utf-8", "surrogatepass")).hexdigest()


def registrar(
    url: str,
    dominio: str,
    heuristicas: tuple[str, ...],
    marca: int | None,
    edad_registro: int | None,
) -> None:
    """Suma un análisis a la web y a la dirección.

    `edad_registro` es la edad según RDAP; si vino de una fuente externa, va None. Si la
    base falla, el análisis sigue: la reputación es un registro, no parte del resultado.
    """
    try:
        _registrar(url, dominio, heuristicas, marca, edad_registro)
    except DatabaseError as error:
        logger.warning("No se registró la reputación: %s", type(error).__name__)


def _registrar(url, dominio, heuristicas, marca, edad_registro) -> None:
    hoy = timezone.now()
    registrado = (hoy - timedelta(days=edad_registro)).date() if edad_registro is not None else None
    with transaction.atomic():
        for tipo, clave in ((Reputacion.Tipo.DOMINIO, dominio), (Reputacion.Tipo.URL, huella(url))):
            fila, _ = Reputacion.objects.select_for_update().get_or_create(
                tipo=tipo, clave=clave, defaults={"dominio": dominio, "primera_vez": hoy}
            )
            fila.ultima_vez = hoy
            fila.analisis = F("analisis") + 1
            fila.heuristicas = sorted(set(fila.heuristicas) | set(heuristicas))
            if registrado is not None:
                fila.registrado = registrado
            if marca is not None:
                fila.marca = max(marca, fila.marca or 0)
            fila.save()


def confirmado(urls: tuple[str, ...], dominio: str) -> bool:
    """True si un analista confirmó el fraude en toda la web o en alguna de las direcciones.

    Recibe la dirección que pegó la persona y la final, después de las redirecciones: el
    analista confirma la que quedó guardada en el análisis, que es la primera.
    """
    huellas = [huella(url) for url in urls if url]
    return Reputacion.objects.filter(
        Q(tipo=Reputacion.Tipo.DOMINIO, clave=dominio)
        | Q(tipo=Reputacion.Tipo.URL, clave__in=huellas),
        confirmado_por_analista=True,
    ).exists()


def marcar_confirmado(dominio: str, valor: bool = True, url: str = "") -> None:
    """Lo usa la cola de curación cuando un analista confirma o descarta un fraude.

    También deja sin efecto los resultados guardados de esa web: sin eso, la caché
    seguiría mostrando el nivel anterior hasta vencer.
    """
    tipo, clave = (Reputacion.Tipo.URL, huella(url)) if url else (Reputacion.Tipo.DOMINIO, dominio)
    fila, _ = Reputacion.objects.get_or_create(
        tipo=tipo, clave=clave, defaults={"dominio": dominio}
    )
    fila.confirmado_por_analista = valor
    fila.save(update_fields=["confirmado_por_analista"])
    invalidar_dominio(dominio)


def sumar_reporte(dominio: str, tipo_reporte: str) -> None:
    """Suma un reporte ciudadano al contador de la web. El motor nunca lee este contador."""
    campo = {REPORTE_ESTAFA: "reportes_estafa", REPORTE_LEGITIMO: "reportes_legitimo"}.get(
        tipo_reporte
    )
    if campo is None or not dominio:
        return
    try:
        fila, _ = Reputacion.objects.get_or_create(
            tipo=Reputacion.Tipo.DOMINIO, clave=dominio, defaults={"dominio": dominio}
        )
        Reputacion.objects.filter(pk=fila.pk).update(**{campo: F(campo) + 1})
    except DatabaseError as error:
        # El reporte ya quedó guardado: el contador es un resumen y no debe dar error.
        logger.warning("No se sumó el reporte a la reputación: %s", type(error).__name__)


def edad_registrada(dominio: str) -> int | None:
    """Edad en días según la fecha de RDAP guardada, o None."""
    fila = Reputacion.objects.filter(tipo=Reputacion.Tipo.DOMINIO, clave=dominio).first()
    if fila is None or fila.registrado is None:
        return None
    return max(0, (date.today() - fila.registrado).days)
