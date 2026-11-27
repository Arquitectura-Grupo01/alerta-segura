from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import User
from django.urls import reverse

from .models import EventoAuditoria
from .roles import es_administrador


@admin.register(EventoAuditoria)
class EventoAuditoriaAdmin(admin.ModelAdmin):
    """Consulta de la auditoría, filtrable por fecha, tipo y usuario.

    Es de solo lectura para todos, también para el administrador: nadie agrega, edita
    ni borra eventos desde la consola. Solo la ve un administrador; un permiso de ver
    agregado a mano a otra cuenta no alcanza.
    """

    list_display = ("fecha", "tipo", "usuario", "objeto", "motivo")
    # El filtro de usuario lista solo las cuentas que tienen eventos, no todas.
    list_filter = ("fecha", "tipo", ("usuario", admin.RelatedOnlyFieldListFilter))
    date_hierarchy = "fecha"
    list_select_related = ("usuario",)
    readonly_fields = ("fecha", "tipo", "usuario", "objeto", "motivo", "detalle")
    # Sin acciones en bloque: la única que trae Django es borrar.
    actions = None

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


def _acceso_auditoria(request):
    if not es_administrador(request.user):
        return None
    return {
        "titulo": "Auditoría",
        "cifra": None,
        "descripcion": "Inicios de sesión, bloqueos, decisiones y cambios. Solo lectura.",
        "url": reverse("admin:core_eventoauditoria_changelist"),
    }


def _acceso_cuentas(request):
    if not request.user.has_perm("auth.view_user"):
        return None
    return {
        "titulo": "Cuentas internas",
        "cifra": User.objects.filter(is_staff=True, is_active=True).count(),
        "descripcion": "Cuentas activas del equipo. El rol se asigna con los grupos.",
        "url": reverse("admin:auth_user_changelist"),
    }


admin.site.agregar_acceso(_acceso_auditoria, orden=70)
admin.site.agregar_acceso(_acceso_cuentas, orden=80)
