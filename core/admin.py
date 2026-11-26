from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import User

from .models import EventoAuditoria
from .roles import es_administrador


@admin.register(EventoAuditoria)
class EventoAuditoriaAdmin(admin.ModelAdmin):
    """Solo lectura: la auditoría no se agrega, edita ni borra desde el admin.

    Solo la ve un administrador. Un permiso de ver agregado a mano a otra cuenta no
    alcanza.
    """

    list_display = ("fecha", "tipo", "usuario", "objeto", "motivo")
    list_filter = ("tipo", "usuario")
    date_hierarchy = "fecha"
    readonly_fields = ("fecha", "tipo", "usuario", "objeto", "motivo", "detalle")

    def has_module_permission(self, request):
        return es_administrador(request.user)

    def has_view_permission(self, request, obj=None):
        return es_administrador(request.user) and super().has_view_permission(request, obj)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


admin.site.unregister(User)


@admin.register(User)
class CuentaInternaAdmin(UserAdmin):
    """Cuentas internas. El rol se asigna con los grupos Analista y Administrador.

    Quien no es superusuario no puede darse el superusuario ni permisos sueltos: lo que
    hace una cuenta sale solo de su rol. Las cuentas no se borran, se desactivan, porque
    la auditoría las referencia.
    """

    def get_readonly_fields(self, request, obj=None):
        campos = super().get_readonly_fields(request, obj)
        if not request.user.is_superuser:
            campos = (*campos, "is_superuser", "user_permissions")
        return campos

    def has_delete_permission(self, request, obj=None):
        return False
