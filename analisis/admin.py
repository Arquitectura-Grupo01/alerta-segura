from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html

from analisis.orquestador import estados_de

from .models import Analisis

CAMPOS = (
    "fecha", "fecha_analisis", "tipo_entrada", "dominio", "dominio_origen", "redirecciones",
    "url", "nivel", "puntaje", "cobertura", "version_reglas", "reglas", "senales", "pesos",
    "marca_suplantada", "modalidad", "desde_cache", "departamento",
)


@admin.register(Analisis)
class AnalisisAdmin(admin.ModelAdmin):
    """Los análisis guardados, de solo lectura. Los ven analistas y administradores.

    No hay IP, texto de la persona ni imágenes: el modelo no los guarda. La dirección
    completa solo existe en los análisis Peligroso o Peligro alto. De cada fuente se muestra
    el estado, nunca la respuesta del proveedor.
    """

    list_display = ("fecha", "dominio", "veredicto", "puntaje", "cobertura", "tipo_entrada",
                    "desde_cache", "marca_suplantada")
    list_filter = ("fecha", "nivel", "tipo_entrada", "desde_cache", "modalidad")
    search_fields = ("dominio", "dominio_origen", "marca_suplantada")
    date_hierarchy = "fecha"
    readonly_fields = (*CAMPOS, "estado_de_las_fuentes", "pagina_de_resultado")
    fields = readonly_fields
    actions = None
    list_per_page = 50

    @admin.display(description="veredicto", ordering="nivel")
    def veredicto(self, analisis):
        """Color y palabra a la vez, con las clases de static/css/consola.css."""
        return format_html(
            '<span class="etiqueta-nivel nivel-{}">{}</span>',
            analisis.nivel, analisis.get_nivel_display(),
        )

    @admin.display(description="fuentes")
    def estado_de_las_fuentes(self, analisis):
        estados = estados_de(analisis.fuentes or [])
        return ", ".join(f"{titulo}: {estado}" for titulo, estado in estados) or "Ninguna"

    @admin.display(description="resultado que vio la persona")
    def pagina_de_resultado(self, analisis):
        # format_html escapa el argumento; la dirección sale de reverse con un UUID.
        return format_html(
            '<a href="{}">Abrir la página de resultado</a>',
            reverse("resultado", args=[analisis.publico]),
        )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


def _acceso_analisis(request):
    if not request.user.has_perm("analisis.view_analisis"):
        return None
    return {
        "titulo": "Análisis",
        "cifra": None,
        "descripcion": "Cada consulta con su veredicto, señales y fuentes. Busca por web.",
        "url": reverse("admin:analisis_analisis_changelist"),
    }


admin.site.agregar_acceso(_acceso_analisis, orden=30)
