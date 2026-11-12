from django.contrib import admin

from .models import EventoAuditoria


@admin.register(EventoAuditoria)
class EventoAuditoriaAdmin(admin.ModelAdmin):
    """Solo lectura: la auditoría no se agrega, edita ni borra desde el admin."""

    list_display = ("fecha", "tipo", "usuario", "objeto", "motivo")
    list_filter = ("tipo",)
    date_hierarchy = "fecha"
    readonly_fields = ("fecha", "tipo", "usuario", "objeto", "motivo", "detalle")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
