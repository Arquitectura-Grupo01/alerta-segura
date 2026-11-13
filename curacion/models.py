"""Modelos de curación."""

from django.db import models
from django.utils import timezone

from analisis.models import Analisis


class ReporteDesacuerdo(models.Model):
    """Lo que una persona dice de un resultado: si era una estafa o si era legítimo.

    Se asocia al análisis y nunca a quien lo envía: no guarda IP, texto libre ni ningún
    identificador. Entra pendiente a la cola de curación y no toca el veredicto, la
    reputación ni la caché, aunque lleguen cientos iguales: así un bot no puede hacer
    pasar una estafa por segura.
    """

    class Tipo(models.TextChoices):
        ERA_ESTAFA = "era_estafa", "Sí era estafa"
        ERA_LEGITIMO = "era_legitimo", "Era legítimo"

    class Estado(models.TextChoices):
        PENDIENTE = "pendiente", "Pendiente"
        RESUELTO = "resuelto", "Resuelto"

    # Sin el análisis, el reporte no dice nada: se borra con él.
    analisis = models.ForeignKey(Analisis, on_delete=models.CASCADE, related_name="reportes")
    tipo = models.CharField(max_length=15, choices=Tipo.choices)
    estado = models.CharField(max_length=10, choices=Estado.choices, default=Estado.PENDIENTE)
    fecha = models.DateTimeField(default=timezone.now)

    class Meta:
        verbose_name = "reporte de desacuerdo"
        verbose_name_plural = "reportes de desacuerdo"
        ordering = ["-fecha"]
        # La cola de curación lee los pendientes por fecha.
        indexes = [models.Index(fields=["estado", "fecha"], name="reporte_estado_fecha")]

    def __str__(self):
        return f"{self.get_tipo_display()} sobre {self.analisis}"


class SolicitudRevision(models.Model):
    """Pedido del dueño de una web que cree que la marcamos por error.

    Entra pendiente a la misma cola que los reportes de desacuerdo y, como ellos, no
    cambia ningún veredicto por sí solo. No guarda quién lo envía: el mensaje se guarda
    con correos, teléfonos, DNI, cuentas y montos enmascarados.
    """

    MAX_MENSAJE = 1000

    class Estado(models.TextChoices):
        PENDIENTE = "pendiente", "Pendiente"
        RESUELTO = "resuelto", "Resuelto"

    dominio = models.CharField(max_length=253)
    mensaje = models.TextField(max_length=MAX_MENSAJE * 2)
    estado = models.CharField(max_length=10, choices=Estado.choices, default=Estado.PENDIENTE)
    fecha = models.DateTimeField(default=timezone.now)

    class Meta:
        verbose_name = "pedido de revisión"
        verbose_name_plural = "pedidos de revisión"
        ordering = ["-fecha"]
        indexes = [models.Index(fields=["estado", "fecha"], name="solicitud_estado_fecha")]

    def __str__(self):
        return f"Revisión de {self.dominio}"
