"""Panel de estadísticas de la consola y su descarga en CSV (tarea 53).

Lo ven analistas y administradores (permiso analisis.view_analisis). La sección de
seguridad, con los eventos de auditoría, solo la ve un administrador. Las vistas se
registran en la consola desde curacion/admin.py con admin.site.agregar_vista.
"""
import csv

from django.contrib import admin
from django.core.exceptions import PermissionDenied
from django.http import StreamingHttpResponse
from django.template.response import TemplateResponse
from django.utils import timezone

from core.roles import es_administrador

from . import estadisticas, graficos
from .formularios import FormularioFiltros

PERMISO = "analisis.view_analisis"
# Una celda que empieza así se interpreta como fórmula en Excel o LibreOffice.
INICIOS_DE_FORMULA = ("=", "+", "-", "@", "\t", "\r")
COLUMNAS_CSV = (
    ("fecha", "Fecha (Lima)"),
    ("tipo_entrada", "Tipo"),
    ("dominio", "Web"),
    ("dominio_origen", "Web del enlace pegado"),
    ("url", "Dirección completa (solo Peligroso o más)"),
    ("nivel", "Veredicto"),
    ("puntaje", "Puntaje"),
    ("cobertura", "Cobertura"),
    ("marca_suplantada", "Marca suplantada"),
    ("modalidad", "Modalidad"),
    ("desde_cache", "Desde la caché"),
    ("version_reglas", "Versión de reglas"),
)


def _exigir_permiso(request):
    if not request.user.has_perm(PERMISO):
        raise PermissionDenied


def _filtros(request):
    """El formulario y los filtros. Sin filtros válidos valen los últimos 30 días, y el
    formulario muestra ese período en sus campos."""
    if request.GET:
        formulario = FormularioFiltros(request.GET)
        if formulario.is_valid():
            return formulario, formulario.cleaned_data["filtros"]
        return formulario, estadisticas.Filtros.por_defecto()
    filtros = estadisticas.Filtros.por_defecto()
    return FormularioFiltros(initial={"desde": filtros.desde, "hasta": filtros.hasta}), filtros


def _clase_nivel(fila):
    return f"relleno-{fila['nivel']}"


def panel_view(request):
    _exigir_permiso(request)
    formulario, filtros = _filtros(request)
    datos = estadisticas.todo(filtros, con_seguridad=es_administrador(request.user))
    resumen = datos["resumen"]
    contexto = {
        **admin.site.each_context(request),
        "title": "Panel de estadísticas",
        "formulario": formulario,
        "filtros": filtros,
        "consulta_actual": request.GET.urlencode(),
        **datos,
        "grafico_dias": graficos.barras_por_dia(datos["por_dia"]),
        "grafico_niveles": graficos.barras_horizontales(
            resumen["por_nivel"], "texto", clase=_clase_nivel,
        ),
        "grafico_maliciosos": graficos.barras_horizontales(
            datos["top_maliciosos"], "dominio", clase=_clase_nivel,
        ),
        "grafico_marcas": graficos.barras_horizontales(datos["top_marcas"], "marca_suplantada"),
    }
    return TemplateResponse(request, "admin/curacion/panel.html", contexto)


def _celda(valor):
    """Texto seguro para una hoja de cálculo: sin fórmulas (inyección de CSV)."""
    texto = "" if valor is None else str(valor)
    if texto.startswith(INICIOS_DE_FORMULA):
        return "'" + texto
    return texto


class _Eco:
    """Archivo falso para csv.writer: devuelve la línea en lugar de guardarla."""

    def write(self, linea):
        return linea


def _filas_csv(consulta):
    escritor = csv.writer(_Eco())
    yield "﻿" + escritor.writerow([titulo for _, titulo in COLUMNAS_CSV])
    campos = [campo for campo, _ in COLUMNAS_CSV]
    niveles = {nivel.value: nivel.texto for nivel in estadisticas.NIVELES}
    for fila in consulta.values(*campos).iterator():
        fila["fecha"] = timezone.localtime(fila["fecha"], estadisticas.LIMA).strftime(
            "%Y-%m-%d %H:%M",
        )
        fila["nivel"] = niveles.get(fila["nivel"], fila["nivel"])
        fila["desde_cache"] = "sí" if fila["desde_cache"] else "no"
        yield escritor.writerow([_celda(fila[campo]) for campo in campos])


def exportar_csv(request):
    """Los análisis del período filtrado, uno por fila. Sin IP ni textos de la persona."""
    _exigir_permiso(request)
    _, filtros = _filtros(request)
    consulta = estadisticas.analisis_filtrados(filtros).order_by("fecha", "id")
    respuesta = StreamingHttpResponse(_filas_csv(consulta), content_type="text/csv; charset=utf-8")
    nombre = f"analisis_{filtros.desde:%Y%m%d}_{filtros.hasta:%Y%m%d}.csv"
    respuesta["Content-Disposition"] = f'attachment; filename="{nombre}"'
    respuesta["Cache-Control"] = "no-store"
    return respuesta
