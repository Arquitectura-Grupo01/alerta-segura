"""Modelos del catálogo de marcas y canales oficiales."""

from django.conf import settings
from django.core.validators import RegexValidator
from django.db import models
from django.utils import timezone

validar_dominio = RegexValidator(
    regex=r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$",
    message="Ingresa un dominio válido, sin https:// ni rutas.",
)


class Marca(models.Model):
    class Tipo(models.TextChoices):
        BANCO = "banco", "Banco"
        BILLETERA = "billetera", "Billetera digital"
        CAJA = "caja", "Caja municipal o rural"
        FINANCIERA = "financiera", "Financiera"
        AFP = "afp", "AFP"
        ESTADO = "estado", "Entidad pública"
        SERVICIO = "servicio", "Empresa de servicios"
        OTRO = "otro", "Otro"

    nombre = models.CharField(max_length=150, unique=True)
    tipo = models.CharField(max_length=20, choices=Tipo.choices)
    activa = models.BooleanField(default=True)
    creada_en = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["nombre"]
        verbose_name = "marca"
        verbose_name_plural = "marcas"

    def __str__(self):
        return self.nombre


class DominioOficial(models.Model):
    class Estado(models.TextChoices):
        PENDIENTE = "pendiente", "Pendiente de aprobación"
        APROBADO = "aprobado", "Aprobado"
        RECHAZADO = "rechazado", "Rechazado"
        RETIRADO = "retirado", "Retirado"

    marca = models.ForeignKey(
        Marca,
        on_delete=models.PROTECT,
        related_name="dominios_oficiales",
    )
    dominio = models.CharField(
        max_length=253,
        unique=True,
        validators=[validar_dominio],
    )
    fuente_verificacion = models.URLField(max_length=500)
    fecha_verificacion = models.DateTimeField(null=True, blank=True)
    estado = models.CharField(
        max_length=15,
        choices=Estado.choices,
        default=Estado.PENDIENTE,
    )
    creado_en = models.DateTimeField(default=timezone.now)

    solicitado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="dominios_solicitados",
        null=True,
        blank=True,
    )

    aprobado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="dominios_aprobados",
        null=True,
        blank=True,
    )

    aprobado_en = models.DateTimeField(
        null=True,
        blank=True,
    )

    reemplaza_a = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        related_name="solicitudes_reemplazo",
        null=True,
        blank=True,
        help_text="Dominio oficial anterior que será reemplazado.",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["reemplaza_a"],
                condition=models.Q(
                    estado="pendiente",
                    reemplaza_a__isnull=False,
                ),
                name="unico_reemplazo_pendiente",
            ),
        ]

    def __str__(self):
        return self.dominio


class CanalOficial(models.Model):
    class Tipo(models.TextChoices):
        WEB = "web", "Sitio web"
        APP = "app", "Aplicación móvil"
        TELEFONO = "telefono", "Teléfono"
        REPORTE = "reporte", "Canal para reportar fraude"

    marca = models.ForeignKey(
        Marca,
        on_delete=models.PROTECT,
        related_name="canales_oficiales",
    )
    tipo = models.CharField(max_length=15, choices=Tipo.choices)
    valor = models.CharField(max_length=500)
    fuente_verificacion = models.URLField(max_length=500)
    fecha_verificacion = models.DateTimeField(null=True, blank=True)
    activo = models.BooleanField(default=False)

    class Meta:
        ordering = ["marca", "tipo"]
        verbose_name = "canal oficial"
        verbose_name_plural = "canales oficiales"

    def __str__(self):
        return f"{self.marca.nombre} - {self.get_tipo_display()}"


class VarianteObservada(models.Model):
    marca = models.ForeignKey(
        Marca,
        on_delete=models.PROTECT,
        related_name="variantes_observadas",
    )
    dominio = models.CharField(
        max_length=253,
        unique=True,
        validators=[validar_dominio],
    )
    primera_observacion = models.DateTimeField(default=timezone.now)
    confirmada = models.BooleanField(default=False)

    class Meta:
        ordering = ["-primera_observacion"]
        verbose_name = "variante observada"
        verbose_name_plural = "variantes observadas"

    def __str__(self):
        return self.dominio


"Historial de cambios de marcas y dominios oficiales, para auditoría y trazabilidad."


class HistorialMarca(models.Model):
    """Conserva una versión anterior de una marca."""

    class Accion(models.TextChoices):
        CREACION = "creacion", "Creación"
        MODIFICACION = "modificacion", "Modificación"
        RESTAURACION = "restauracion", "Restauración"

    marca = models.ForeignKey(
        Marca,
        on_delete=models.PROTECT,
        related_name="historial",
    )
    nombre = models.CharField(max_length=150)
    tipo = models.CharField(max_length=20, choices=Marca.Tipo.choices)
    activa = models.BooleanField()

    accion = models.CharField(
        max_length=15,
        choices=Accion.choices,
    )
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    fecha = models.DateTimeField(default=timezone.now)
    motivo = models.CharField(max_length=200)

    class Meta:
        ordering = ["-fecha", "-id"]
        verbose_name = "historial de marca"
        verbose_name_plural = "historial de marcas"

    def __str__(self):
        return f"{self.marca.nombre} - {self.accion}"


class HistorialDominio(models.Model):
    """Conserva el estado anterior de un dominio oficial."""

    class Accion(models.TextChoices):
        MODIFICACION = "modificacion", "Modificación"
        RESTAURACION = "restauracion", "Restauración"
        APROBACION = "aprobacion", "Aprobación"
        RECHAZO = "rechazo", "Rechazo"

    dominio_oficial = models.ForeignKey(
        DominioOficial,
        on_delete=models.PROTECT,
        related_name="historial",
    )

    dominio = models.CharField(max_length=253)
    fuente_verificacion = models.URLField(max_length=500)
    fecha_verificacion = models.DateTimeField(null=True, blank=True)
    estado = models.CharField(
        max_length=15,
        choices=DominioOficial.Estado.choices,
    )

    solicitado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="+",
        null=True,
        blank=True,
    )
    aprobado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="+",
        null=True,
        blank=True,
    )
    aprobado_en = models.DateTimeField(null=True, blank=True)

    accion = models.CharField(
        max_length=15,
        choices=Accion.choices,
    )
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="+",
    )
    fecha = models.DateTimeField(default=timezone.now)
    motivo = models.CharField(max_length=200)

    class Meta:
        ordering = ["-fecha", "-id"]
        verbose_name = "historial de dominio"
        verbose_name_plural = "historial de dominios"

    def __str__(self):
        return f"{self.dominio} - {self.accion}"
