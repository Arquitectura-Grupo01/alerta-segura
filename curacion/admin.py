from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import path, reverse

from core.models import InvalidacionDominio
from core.sondeo import posible_sondeo
from motor.models import Reputacion

from . import servicios
from .formularios import FormularioDecision, FormularioInvalidacion
from .models import ReporteDesacuerdo, SolicitudRevision

CAMPOS_RESOLUCION = ("decision", "justificacion", "resuelto_por", "resuelto_en")


@admin.register(ReporteDesacuerdo)
class ReporteDesacuerdoAdmin(admin.ModelAdmin):
    """La cola de curación (tarea 37).

    La lista agrupa los reportes y pedidos pendientes por web y los ordena por prioridad.
    Cada web abre su caso, donde se confirma el fraude, se descarta o se marca como falso
    positivo, siempre con justificación y auditoría. Los formularios estándar de Django
    quedan cerrados: nadie agrega, edita ni borra reportes a mano.
    """

    list_display = ("fecha", "tipo", "estado", "dominio", "nivel")
    readonly_fields = ("fecha", "tipo", "estado", "analisis", *CAMPOS_RESOLUCION)
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

    def get_urls(self):
        caso = self.admin_site.admin_view(self.caso_view)
        return [path("caso/<str:dominio>/", caso, name="curacion_caso"), *super().get_urls()]

    def changelist_view(self, request, extra_context=None):
        if not self.has_view_permission(request):
            raise PermissionDenied
        casos = servicios.cola()
        for caso in casos:
            caso["sondeo"] = posible_sondeo(caso["dominio"])
        contexto = {
            **self.admin_site.each_context(request),
            "title": "Cola de curación",
            "opts": self.model._meta,
            "casos": casos,
        }
        return TemplateResponse(request, "admin/curacion/cola.html", contexto)

    def caso_view(self, request, dominio):
        if not self.has_view_permission(request):
            raise PermissionDenied
        puede_decidir = request.user.has_perm("curacion.change_reportedesacuerdo")
        formulario = FormularioDecision(request.POST or None)
        if request.method == "POST":
            if not puede_decidir:
                raise PermissionDenied
            if formulario.is_valid():
                try:
                    servicios.resolver_caso(
                        dominio=dominio, usuario=request.user, **formulario.cleaned_data,
                    )
                except ValidationError as error:
                    formulario.add_error(None, error)
                else:
                    messages.success(request, "Caso resuelto. La decisión quedó auditada.")
                    return redirect("admin:curacion_reportedesacuerdo_changelist")
        reportes, solicitudes = servicios.pendientes_de(dominio)
        contexto = {
            **self.admin_site.each_context(request),
            "title": f"Caso de {dominio}",
            "opts": self.model._meta,
            "dominio": dominio,
            "reportes": reportes,
            "solicitudes": solicitudes,
            "reputacion": Reputacion.objects.filter(
                tipo=Reputacion.Tipo.DOMINIO, clave=dominio,
            ).first(),
            "sondeo": posible_sondeo(dominio),
            "formulario": formulario,
            "puede_decidir": puede_decidir,
        }
        return TemplateResponse(request, "admin/curacion/caso.html", contexto)


@admin.register(SolicitudRevision)
class SolicitudRevisionAdmin(admin.ModelAdmin):
    """Historial de pedidos de revisión. Los pendientes se resuelven desde la cola."""

    list_display = ("fecha", "dominio", "estado", "decision")
    list_filter = ("estado",)
    date_hierarchy = "fecha"
    readonly_fields = ("fecha", "dominio", "mensaje", "estado", *CAMPOS_RESOLUCION)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(InvalidacionDominio)
class InvalidacionDominioAdmin(admin.ModelAdmin):
    """Invalidación manual de resultados (tarea 38).

    La lista muestra cuántas veces se invalidó cada web. El botón «Invalidar resultados»
    abre el formulario para una URL exacta o una web completa, con motivo obligatorio.
    Los contadores no se editan a mano.
    """

    list_display = ("dominio", "contador", "actualizado")
    search_fields = ("dominio",)
    readonly_fields = ("dominio", "contador", "actualizado")
    change_list_template = "admin/curacion/invalidaciones.html"
    actions = None

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_urls(self):
        vista = self.admin_site.admin_view(self.invalidar_view)
        return [path("invalidar/", vista, name="curacion_invalidar"), *super().get_urls()]

    def invalidar_view(self, request):
        if not request.user.has_perm("core.change_invalidaciondominio"):
            raise PermissionDenied
        formulario = FormularioInvalidacion(request.POST or None)
        if request.method == "POST" and formulario.is_valid():
            try:
                dominio = servicios.invalidar_resultados(
                    usuario=request.user, **formulario.cleaned_data,
                )
            except ValidationError as error:
                formulario.add_error(None, error)
            else:
                messages.success(
                    request, f"Listo. La próxima consulta de {dominio} se analiza de nuevo.",
                )
                return redirect(reverse("admin:core_invalidaciondominio_changelist"))
        contexto = {
            **self.admin_site.each_context(request),
            "title": "Invalidar resultados",
            "opts": self.model._meta,
            "formulario": formulario,
        }
        return TemplateResponse(request, "admin/curacion/invalidar.html", contexto)
