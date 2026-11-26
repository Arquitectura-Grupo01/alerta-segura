"""Plazos de conservación y purga de datos vencidos (tarea 40).

Conservar solo lo necesario es un principio de la Ley N.° 29733. Los plazos se publican en
templates/legal/privacidad.html: si cambia uno, se cambia allí en el mismo PR.

Render gratuito no tiene tareas programadas, así que la purga es el comando purgar_datos,
que un integrante corre a mano una vez al mes contra Prod. Borra en lotes pequeños, cada
uno en su propia transacción, para no bloquear tablas ni llenar el registro de la base.
"""
from datetime import timedelta

from django.conf import settings
from django.contrib.sessions.models import Session
from django.db import connection, transaction

from .auditoria import registrar_evento
from .models import EventoAuditoria, TipoEvento

# Controles fijos, no configuración. Propuesta pendiente de confirmar en docs/decisiones.md.
DIAS_ANALISIS = 365
DIAS_REPORTES_RESUELTOS = 365
# La auditoría dura más que lo que audita: un año como mínimo.
DIAS_AUDITORIA = 2 * 365
# La caché técnica ya vence a las 24 h (inteligencia/fuentes.py). En la tabla de
# PostgreSQL las filas vencidas siguen ocupando espacio hasta que alguien las lee.
LOTE = 500

# Plan gratuito de Neon. Verificar el límite vigente en el panel antes de cada entrega.
LIMITE_NEON_BYTES = 512 * 1024 * 1024
AVISO_DESDE = 0.8

# Una sentencia fija por tabla de caché (config/settings/cache.py): el nombre de una tabla
# no puede ir como parámetro, y AGENTS.md prohíbe armar SQL con texto.
BORRAR_CACHE_VENCIDA = {
    "cache_alerta": "DELETE FROM cache_alerta WHERE expires < %s",
    "cache_tecnica": "DELETE FROM cache_tecnica WHERE expires < %s",
    "cache_resultados": "DELETE FROM cache_resultados WHERE expires < %s",
}


def limite(ahora, dias):
    return ahora - timedelta(days=dias)


def borrar_en_lotes(borrar_lote) -> int:
    """Llama a `borrar_lote()` hasta que devuelva menos de LOTE. Devuelve el total."""
    total = 0
    while True:
        with transaction.atomic():
            borrados = borrar_lote()
        total += borrados
        if borrados < LOTE:
            return total


def purgar_auditoria(ahora) -> int:
    antes_de = limite(ahora, DIAS_AUDITORIA)
    return borrar_en_lotes(lambda: EventoAuditoria.objects.purgar_lote(antes_de, LOTE))


def contar_auditoria_vencida(ahora) -> int:
    return EventoAuditoria.objects.filter(fecha__lt=limite(ahora, DIAS_AUDITORIA)).count()


def purgar_sesiones(ahora) -> int:
    """Borra las sesiones vencidas de la consola, como clearsessions, pero en lotes."""
    def lote():
        vencidas = Session.objects.filter(expire_date__lt=ahora)
        ids = list(vencidas.values_list("pk", flat=True)[:LOTE])
        return Session.objects.filter(pk__in=ids).delete()[0]

    return borrar_en_lotes(lote)


def contar_sesiones_vencidas(ahora) -> int:
    return Session.objects.filter(expire_date__lt=ahora).count()


def _tablas_de_cache():
    """Las tablas de caché en PostgreSQL. Con Redis no hay ninguna: Redis borra solo."""
    for alias in ("default", "tecnica", "resultados"):
        configuracion = settings.CACHES.get(alias, {})
        if configuracion.get("BACKEND") == "django.core.cache.backends.db.DatabaseCache":
            yield configuracion["LOCATION"]


def purgar_cache_vencida(ahora) -> int:
    """Borra las filas ya vencidas de las tablas de caché. Las vigentes quedan."""
    total = 0
    with connection.cursor() as cursor:
        for tabla in _tablas_de_cache():
            cursor.execute(BORRAR_CACHE_VENCIDA[tabla], [ahora])
            total += cursor.rowcount
    return total


def uso_de_la_base() -> int:
    """Bytes que ocupa la base actual. pg_database_size no requiere superusuario."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_database_size(current_database())")
        return cursor.fetchone()[0]


def registrar_purga(totales: dict) -> None:
    """La purga queda en la auditoría, con cuántas filas borró de cada tipo."""
    registrar_evento(
        TipoEvento.PURGA_DATOS, motivo="Purga mensual de datos vencidos", detalle=totales,
    )
