
from django.contrib import admin

from .models import EventoAuditoria


@admin.register(EventoAuditoria)
class EventoAuditoriaAdmin(admin.ModelAdmin):
    """Consulta de auditoría exclusiva para administradores."""

    list_display = (
        "fecha",
        "tipo",
        "usuario",
        "objeto",
        "motivo",
    )

    list_filter = (
        "tipo",
        "usuario",
    )

    date_hierarchy = "fecha"

    readonly_fields = (
        "fecha",
        "tipo",
        "usuario",
        "objeto",
        "motivo",
        "detalle",
    )

    def has_view_permission(self, request, obj=None):
        return bool(
            request.user.is_authenticated
            and request.user.is_active
            and request.user.is_staff
            and request.user.is_superuser
        )

    def has_module_permission(self, request):
        return self.has_view_permission(request)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
