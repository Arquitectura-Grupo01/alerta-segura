from django.contrib import admin
from django.urls import reverse

from .models import Reputacion


@admin.register(Reputacion)
class ReputacionAdmin(admin.ModelAdmin):
    """La base de reputación propia, de solo lectura. Solo la ve el rol administrador.

    Se cambia únicamente con las decisiones de la cola de curación
    (motor.reputacion.marcar_confirmado), que quedan auditadas.
    """

    list_display = ("dominio", "tipo", "analisis", "confirmado_por_analista",
                    "reportes_estafa", "reportes_legitimo", "marca", "ultima_vez")
    list_filter = ("tipo", "confirmado_por_analista")
    search_fields = ("dominio",)
    date_hierarchy = "ultima_vez"
    readonly_fields = (
        "tipo", "clave", "dominio", "primera_vez", "ultima_vez", "analisis", "heuristicas",
        "registrado", "marca", "confirmado_por_analista", "reportes_estafa",
        "reportes_legitimo",
    )
    actions = None

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


def _acceso_reputacion(request):
    if not request.user.has_perm("motor.view_reputacion"):
        return None
    return {
        "titulo": "Reputación propia",
        "cifra": Reputacion.objects.filter(confirmado_por_analista=True).count(),
        "descripcion": "Webs y direcciones con fraude confirmado por un analista.",
        "url": reverse("admin:motor_reputacion_changelist") + "?confirmado_por_analista__exact=1",
    }


admin.site.agregar_acceso(_acceso_reputacion, orden=60)
