"""Catálogo de marcas y dominios oficiales en la consola. Solo para el rol administrador.

Todo cambio pasa por catalogo/servicios.py, que guarda el historial y deja el evento de
auditoría. Los formularios estándar de Django quedan cerrados: con ellos se podría
cambiar el catálogo sin historial ni doble aprobación. Un dominio oficial nuevo no se
activa sin la aprobación de un segundo administrador con su código TOTP, porque un
dominio falso registrado como oficial apagaría la alerta para esa marca.
"""
from django.contrib import admin, messages
from django.core.exceptions import ObjectDoesNotExist, PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.urls import path, reverse

from . import servicios
from .formularios import (
    FormularioAprobacion,
    FormularioMarca,
    FormularioMarcaNueva,
    FormularioMotivo,
    FormularioReemplazo,
    FormularioSolicitudDominio,
)
from .models import (
    CanalOficial,
    DominioOficial,
    HistorialDominio,
    HistorialMarca,
    Marca,
    VarianteObservada,
)


class SoloLectura(admin.ModelAdmin):
    actions = None

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


def _formulario(model_admin, request, *, permiso, titulo, formulario, accion, volver,
                exito, explicacion="", inicial=None):
    """Página con un formulario que llama a un servicio del catálogo.

    `accion(datos)` recibe los datos limpios. Un error del servicio se muestra en el
    formulario y no cambia nada.
    """
    if not request.user.has_perm(permiso):
        raise PermissionDenied
    formulario = formulario(request.POST or None, initial=inicial)
    if request.method == "POST" and formulario.is_valid():
        try:
            accion(formulario.cleaned_data)
        except (ValidationError, PermissionError, ObjectDoesNotExist) as error:
            mensajes = getattr(error, "messages", None) or [str(error) or "No se pudo guardar."]
            for mensaje in mensajes:
                formulario.add_error(None, mensaje)
        else:
            messages.success(request, exito)
            return redirect(volver)
    contexto = {
        **model_admin.admin_site.each_context(request),
        "title": titulo,
        "opts": model_admin.model._meta,
        "formulario": formulario,
        "explicacion": explicacion,
        "volver": volver,
    }
    return TemplateResponse(request, "admin/catalogo/formulario.html", contexto)


@admin.register(Marca)
class MarcaAdmin(SoloLectura):
    list_display = ("nombre", "tipo", "activa", "creada_en")
    list_filter = ("tipo", "activa")
    search_fields = ("nombre",)
    readonly_fields = ("nombre", "tipo", "activa", "creada_en")
    change_list_template = "admin/catalogo/marca/change_list.html"
    change_form_template = "admin/catalogo/marca/change_form.html"

    def get_urls(self):
        envolver = self.admin_site.admin_view
        return [
            path("nueva/", envolver(self.nueva_view), name="catalogo_marca_nueva"),
            path("<int:pk>/editar/", envolver(self.editar_view), name="catalogo_marca_editar"),
            path("<int:pk>/restaurar/<int:historial_pk>/", envolver(self.restaurar_view),
                 name="catalogo_marca_restaurar"),
            *super().get_urls(),
        ]

    def change_view(self, request, object_id, form_url="", extra_context=None):
        historial = HistorialMarca.objects.filter(marca_id=object_id).select_related("usuario")
        contexto = {
            **(extra_context or {}),
            "historial": historial,
            "puede_cambiar": request.user.has_perm("catalogo.change_marca"),
            "dominios": DominioOficial.objects.filter(marca_id=object_id).order_by("dominio"),
        }
        return super().change_view(request, object_id, form_url, contexto)

    def nueva_view(self, request):
        return _formulario(
            self, request, permiso="catalogo.add_marca", titulo="Nueva marca",
            formulario=FormularioMarcaNueva,
            accion=lambda datos: servicios.crear_marca(usuario=request.user, **datos),
            volver=reverse("admin:catalogo_marca_changelist"),
            exito="Marca creada. Agrega sus dominios oficiales desde «Dominios oficiales».",
        )

    def editar_view(self, request, pk):
        marca = get_object_or_404(Marca, pk=pk)
        return _formulario(
            self, request, permiso="catalogo.change_marca", titulo=f"Editar {marca.nombre}",
            formulario=FormularioMarca,
            inicial={"nombre": marca.nombre, "tipo": marca.tipo, "activa": marca.activa},
            accion=lambda datos: servicios.actualizar_marca(
                marca_id=marca.pk, usuario=request.user, **datos,
            ),
            volver=reverse("admin:catalogo_marca_change", args=[marca.pk]),
            exito="Cambio guardado. La versión anterior quedó en el historial.",
        )

    def restaurar_view(self, request, pk, historial_pk):
        version = get_object_or_404(HistorialMarca, pk=historial_pk, marca_id=pk)
        return _formulario(
            self, request, permiso="catalogo.change_marca",
            titulo=f"Restaurar la versión del {version.fecha:%d/%m/%Y %H:%M}",
            formulario=FormularioMotivo,
            explicacion=f"La marca vuelve a: {version.nombre}, {version.get_tipo_display()}, "
                        f"{'activa' if version.activa else 'inactiva'}.",
            accion=lambda datos: servicios.restaurar_marca(
                historial_id=version.pk, usuario=request.user, **datos,
            ),
            volver=reverse("admin:catalogo_marca_change", args=[pk]),
            exito="Versión restaurada. El estado anterior también quedó en el historial.",
        )


@admin.register(DominioOficial)
class DominioOficialAdmin(SoloLectura):
    list_display = ("dominio", "marca", "estado", "solicitado_por", "aprobado_por", "aprobado_en")
    list_filter = ("estado", "marca")
    search_fields = ("dominio", "marca__nombre")
    list_select_related = ("marca", "solicitado_por", "aprobado_por")
    readonly_fields = (
        "marca", "dominio", "estado", "fuente_verificacion", "fecha_verificacion", "creado_en",
        "solicitado_por", "aprobado_por", "aprobado_en", "reemplaza_a",
    )
    change_list_template = "admin/catalogo/dominiooficial/change_list.html"
    change_form_template = "admin/catalogo/dominiooficial/change_form.html"

    def get_urls(self):
        envolver = self.admin_site.admin_view
        return [
            path("solicitar/", envolver(self.solicitar_view),
                 name="catalogo_dominiooficial_solicitar"),
            path("<int:pk>/aprobar/", envolver(self.aprobar_view),
                 name="catalogo_dominiooficial_aprobar"),
            path("<int:pk>/reemplazar/", envolver(self.reemplazar_view),
                 name="catalogo_dominiooficial_reemplazar"),
            *super().get_urls(),
        ]

    def change_view(self, request, object_id, form_url="", extra_context=None):
        contexto = {
            **(extra_context or {}),
            "historial": HistorialDominio.objects.filter(
                dominio_oficial_id=object_id,
            ).select_related("usuario"),
            "puede_cambiar": request.user.has_perm("catalogo.change_dominiooficial"),
        }
        return super().change_view(request, object_id, form_url, contexto)

    def solicitar_view(self, request):
        return _formulario(
            self, request, permiso="catalogo.add_dominiooficial",
            titulo="Solicitar un dominio oficial", formulario=FormularioSolicitudDominio,
            explicacion="El dominio queda pendiente hasta que otro administrador lo apruebe "
                        "con su código TOTP. Verifícalo a mano en la web de la entidad.",
            accion=lambda datos: servicios.solicitar_dominio_oficial(
                marca_id=datos["marca"].pk, dominio=datos["dominio"],
                fuente_verificacion=datos["fuente_verificacion"], usuario=request.user,
                motivo=datos["motivo"],
            ),
            volver=reverse("admin:catalogo_dominiooficial_changelist"),
            exito="Solicitud registrada. Otro administrador debe aprobarla.",
        )

    def aprobar_view(self, request, pk):
        dominio = get_object_or_404(DominioOficial, pk=pk)
        return _formulario(
            self, request, permiso="catalogo.change_dominiooficial",
            titulo=f"Aprobar {dominio.dominio}", formulario=FormularioAprobacion,
            explicacion=f"Marca: {dominio.marca.nombre}. Lo solicitó "
                        f"{dominio.solicitado_por or 'una cuenta desconocida'}. No puedes "
                        "aprobar tu propia solicitud.",
            accion=lambda datos: servicios.aprobar_dominio_oficial(
                dominio_id=dominio.pk, usuario=request.user, **datos,
            ),
            volver=reverse("admin:catalogo_dominiooficial_change", args=[dominio.pk]),
            exito="Dominio aprobado. Ya cuenta como oficial de la marca.",
        )

    def reemplazar_view(self, request, pk):
        dominio = get_object_or_404(DominioOficial, pk=pk)
        return _formulario(
            self, request, permiso="catalogo.change_dominiooficial",
            titulo=f"Reemplazar {dominio.dominio}", formulario=FormularioReemplazo,
            explicacion="El dominio actual sigue vigente hasta que otro administrador "
                        "apruebe el nuevo.",
            accion=lambda datos: servicios.solicitar_reemplazo_dominio(
                dominio_anterior_id=dominio.pk, usuario=request.user, **datos,
            ),
            volver=reverse("admin:catalogo_dominiooficial_change", args=[dominio.pk]),
            exito="Solicitud de reemplazo registrada. Otro administrador debe aprobarla.",
        )


@admin.register(CanalOficial)
class CanalOficialAdmin(SoloLectura):
    """Canales oficiales, de solo lectura. Editarlos necesita historial y auditoría, que
    este modelo todavía no tiene."""

    list_display = ("marca", "tipo", "valor", "activo", "fecha_verificacion")
    list_filter = ("tipo", "activo")
    search_fields = ("marca__nombre", "valor")
    readonly_fields = ("marca", "tipo", "valor", "fuente_verificacion", "fecha_verificacion",
                       "activo")


@admin.register(VarianteObservada)
class VarianteObservadaAdmin(SoloLectura):
    list_display = ("dominio", "marca", "confirmada", "primera_observacion")
    list_filter = ("confirmada", "marca")
    search_fields = ("dominio",)
    readonly_fields = ("dominio", "marca", "confirmada", "primera_observacion")


@admin.register(HistorialDominio)
class HistorialDominioAdmin(SoloLectura):
    list_display = ("fecha", "dominio", "accion", "estado", "usuario")
    list_filter = ("accion",)
    search_fields = ("dominio",)
    readonly_fields = (
        "dominio_oficial", "dominio", "fuente_verificacion", "fecha_verificacion", "estado",
        "solicitado_por", "aprobado_por", "aprobado_en", "accion", "usuario", "fecha", "motivo",
    )


def _acceso_catalogo(request):
    if not request.user.has_perm("catalogo.view_marca"):
        return None
    pendientes = DominioOficial.objects.filter(estado=DominioOficial.Estado.PENDIENTE).count()
    return {
        "titulo": "Catálogo de marcas",
        "cifra": pendientes,
        "descripcion": "Dominios oficiales que esperan la aprobación de otro administrador.",
        "url": reverse("admin:catalogo_dominiooficial_changelist") + "?estado__exact=pendiente",
    }


admin.site.agregar_acceso(_acceso_catalogo, orden=50)
