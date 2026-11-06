from django.conf import settings
from django.db import models
from django.utils import timezone


class EventoInmutable(Exception):
    """Se intentó editar o borrar un evento de auditoría, que es de solo agregar."""


class TipoEvento(models.TextChoices):
    INICIO_SESION = "inicio_sesion", "Inicio de sesión"
    FALLO_SESION = "fallo_sesion", "Fallo de inicio de sesión"
    BLOQUEO_CUENTA = "bloqueo_cuenta", "Bloqueo de cuenta"
    CAMBIO_CATALOGO = "cambio_catalogo", "Cambio de catálogo"
    CAMBIO_REGLAS = "cambio_reglas", "Cambio de reglas"
    DECISION_CURACION = "decision_curacion", "Decisión de curación"
    INVALIDACION = "invalidacion", "Invalidación"
    FALLO_FUENTE = "fallo_fuente", "Fallo de una fuente externa"
    DESTINO_BLOQUEADO = "destino_bloqueado", "Destino bloqueado por anti-SSRF"
    ALERTA_SEGURIDAD = "alerta_seguridad", "Alerta de seguridad"


class EventoQuerySet(models.QuerySet):
    """Cierra los atajos que se saltan save() y delete() de la instancia."""

    def update(self, **kwargs):
        raise EventoInmutable("Los eventos de auditoría no se editan.")

    def bulk_update(self, objs, fields, batch_size=None):
        raise EventoInmutable("Los eventos de auditoría no se editan.")

    def delete(self):
        raise EventoInmutable("Los eventos de auditoría no se borran.")


class EventoAuditoria(models.Model):
    """Registro de solo agregar de lo que pasó en la plataforma.

    Nunca guarda la IP del ciudadano, textos ni URLs completas. Los eventos se
    crean con core.auditoria.registrar_evento, que valida esos campos.
    """

    fecha = models.DateTimeField(default=timezone.now, editable=False, db_index=True)
    tipo = models.CharField(max_length=30, choices=TipoEvento.choices, db_index=True)
    # PROTECT: borrar o anular la cuenta cambiaría eventos ya escritos. Las cuentas
    # internas se desactivan, no se borran.
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
        related_name="+",
    )
    # Qué se tocó, por ejemplo "catalogo.Dominio:42". Solo un identificador.
    objeto = models.CharField(max_length=100, blank=True)
    motivo = models.CharField(max_length=200, blank=True)
    detalle = models.JSONField(default=dict, blank=True)

    objects = EventoQuerySet.as_manager()

    class Meta:
        ordering = ["-fecha", "-id"]
        verbose_name = "evento de auditoría"
        verbose_name_plural = "eventos de auditoría"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise EventoInmutable("Los eventos de auditoría no se editan.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise EventoInmutable("Los eventos de auditoría no se borran.")

    def __str__(self):
        return f"{self.fecha:%Y-%m-%d %H:%M} {self.tipo}"
