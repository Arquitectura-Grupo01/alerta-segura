"""Base de reputación propia: lo que Alerta Segura sabe de una web por sus propios medios.

Guarda solo señales propias: las heurísticas de la dirección, la fecha de registro que
da el registro público (RDAP), si imita a una marca del catálogo, si un analista confirmó
el fraude y cuántos reportes recibió. Nada de lo que responde una fuente externa entra
aquí, ni siquiera el nivel, que se calcula con ellas: sus términos lo prohíben y esta
base es el activo de datos del proyecto.

Un reporte ciudadano solo suma a su contador. El motor de riesgo no lee los contadores,
así que ningún reporte cambia un nivel.
"""

from django.db import models
from django.utils import timezone


class Reputacion(models.Model):
    """Señales propias acumuladas de una web o de una dirección exacta."""

    class Tipo(models.TextChoices):
        DOMINIO = "dominio", "Web"
        URL = "url", "Dirección exacta"

    tipo = models.CharField(max_length=7, choices=Tipo.choices)
    # El dominio, o el SHA-256 de la dirección normalizada: la dirección puede traer el
    # token de una víctima y no se guarda en claro.
    clave = models.CharField(max_length=253)
    dominio = models.CharField(max_length=253, db_index=True)
    primera_vez = models.DateTimeField(default=timezone.now)
    ultima_vez = models.DateTimeField(default=timezone.now)
    analisis = models.PositiveIntegerField(default=0)
    # Códigos de `analisis.heuristicas` vistos alguna vez.
    heuristicas = models.JSONField(default=list)
    # Fecha de registro según RDAP. Nunca la que informa una fuente externa.
    registrado = models.DateField(null=True, blank=True)
    # El valor más alto de suplantación de marca visto, de 0 a 100.
    marca = models.PositiveSmallIntegerField(null=True, blank=True)
    confirmado_por_analista = models.BooleanField(default=False)
    reportes_estafa = models.PositiveIntegerField(default=0)
    reportes_legitimo = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = "reputación"
        verbose_name_plural = "reputación propia"
        constraints = [
            models.UniqueConstraint(fields=["tipo", "clave"], name="reputacion_unica"),
        ]

    def __str__(self):
        return f"{self.get_tipo_display()} {self.dominio}"
