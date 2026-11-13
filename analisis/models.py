"""Registro de cada análisis.

Cada dato que las estadísticas van a filtrar tiene su propio campo: lo que queda dentro
de un JSON no se puede agrupar después sin migrar. No se guarda la IP, el texto que pegó
la persona ni una imagen, y de cada fuente externa solo su estado, nunca su respuesta.
"""

import uuid

from django.db import models
from django.utils import timezone

from motor.riesgo import Nivel


class Analisis(models.Model):
    class Tipo(models.TextChoices):
        ENLACE = "enlace", "Enlace"
        CAPTURA = "captura", "Captura"
        QR = "qr", "Código QR"
        TEXTO = "texto", "Texto"

    # Identificador de la página de resultado. Es aleatorio para que nadie adivine el de otro.
    publico = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    # Cuándo se hizo la consulta.
    fecha = models.DateTimeField(default=timezone.now, db_index=True)
    # Cuándo se calculó el resultado. Es anterior a `fecha` si vino de la caché.
    fecha_analisis = models.DateTimeField(default=timezone.now)
    tipo_entrada = models.CharField(max_length=10, choices=Tipo.choices, db_index=True)
    # Web donde termina el enlace.
    dominio = models.CharField(max_length=255, db_index=True)
    # Web del enlace que pegó la persona, si el destino está en otra.
    dominio_origen = models.CharField(max_length=255, blank=True)
    # Redirecciones seguidas; vacío si no se pudo llegar al destino.
    redirecciones = models.PositiveSmallIntegerField(null=True, blank=True)
    # Solo con Peligroso o Peligro alto: una URL puede llevar tokens personales.
    url = models.CharField(max_length=2100, blank=True)
    nivel = models.PositiveSmallIntegerField(
        "veredicto", choices=[(nivel.value, nivel.texto) for nivel in Nivel], db_index=True,
    )
    puntaje = models.PositiveSmallIntegerField()
    cobertura = models.FloatField()
    version_reglas = models.CharField(max_length=20)
    senales = models.JSONField(default=dict)
    pesos = models.JSONField(default=dict)
    reglas = models.JSONField(default=list)
    # Una entrada por fuente consultada: nombre, título y estado.
    fuentes = models.JSONField(default=list)
    # Nombre de la marca del catálogo que imita, si imita a una.
    marca_suplantada = models.CharField(max_length=100, blank=True)
    # Clave de `motor.modalidades` que sugieren las palabras de la dirección. Es una pista.
    modalidad = models.CharField(max_length=40, blank=True)
    desde_cache = models.BooleanField(default=False)
    # Queda vacío hasta el registro estadístico.
    departamento = models.CharField(max_length=40, blank=True)

    class Meta:
        verbose_name = "análisis"
        verbose_name_plural = "análisis"
        ordering = ["-fecha"]

    def __str__(self):
        return f"{self.dominio} ({self.get_nivel_display()})"

    def save(self, *args, **kwargs):
        # La regla vive en el modelo para que ningún camino guarde la URL de un resultado leve.
        if self.nivel < Nivel.PELIGROSO:
            self.url = ""
        super().save(*args, **kwargs)
