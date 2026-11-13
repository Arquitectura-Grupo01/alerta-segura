from django.contrib import admin

from .models import ReporteDesacuerdo, SolicitudRevision


@admin.register(ReporteDesacuerdo)
class ReporteDesacuerdoAdmin(admin.ModelAdmin):
    """Solo lectura. Resolver un reporte lleva justificación y auditoría, y eso llega con la
    cola de curación (tarea 37)."""

    list_display = ("fecha", "tipo", "estado", "dominio", "nivel")
    list_filter = ("estado", "tipo")
    date_hierarchy = "fecha"
    readonly_fields = ("fecha", "tipo", "estado", "analisis")
    list_select_related = ("analisis",)

    @admin.display(description="web")
    def dominio(self, reporte):
        return reporte.analisis.dominio

    @admin.display(description="veredicto")
    def nivel(self, reporte):
        return reporte.analisis.get_nivel_display()

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(SolicitudRevision)
class SolicitudRevisionAdmin(admin.ModelAdmin):
    """Solo lectura, como los reportes, hasta que exista la cola de curación (tarea 37)."""

    list_display = ("fecha", "dominio", "estado")
    list_filter = ("estado",)
    date_hierarchy = "fecha"
    readonly_fields = ("fecha", "dominio", "mensaje", "estado")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
