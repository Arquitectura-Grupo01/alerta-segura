from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from analisis.models import Analisis
from analisis.normalizacion import LARGO_MAXIMO, URLInvalida, normalizar
from analisis.orquestador import (
    Ocupado,
    analizar_enlace,
    detalles_de,
    estados_de,
    senales_de,
)
from catalogo.models import CanalOficial
from core.entrada import ANALISIS, limitar
from motor.explicacion import (
    NOTA_FUENTES,
    OCUPADO,
    Marca,
    Recorrido,
    aviso_para_compartir,
    explicar,
    hace_cuanto,
)
from motor.modalidades import MODALIDADES
from motor.riesgo import Nivel, calcular

ESPERA_SI_OCUPADO_SEGUNDOS = 10
# Los valores de `curacion.models.ReporteDesacuerdo.Tipo`. Esta app no importa de curacion.
REPORTES_RECIBIDOS = ("era_estafa", "era_legitimo")


@require_POST
@limitar(ANALISIS)
def analizar(request):
    """Recibe un enlace, lo analiza y redirige a la página de su resultado.

    POST, redirect y GET: al recargar el resultado no se envía el formulario otra vez.
    """
    texto = request.POST.get("enlace", "")[:LARGO_MAXIMO + 1]
    try:
        enlace = normalizar(texto)
    except URLInvalida as error:
        # Los mensajes de URLInvalida están escritos para la persona y no traen datos internos.
        return _volver_al_inicio(request, str(error), texto, estado=400)
    try:
        analisis = analizar_enlace(enlace)
    except Ocupado:
        respuesta = _volver_al_inicio(request, OCUPADO, texto, estado=503)
        respuesta["Retry-After"] = str(ESPERA_SI_OCUPADO_SEGUNDOS)
        return respuesta
    return redirect("resultado", publico=analisis.publico)


@require_GET
def resultado(request, publico):
    """Muestra un análisis guardado. Quien no tiene su identificador no puede verlo."""
    analisis = get_object_or_404(Analisis, publico=publico)
    # Con las mismas señales y la misma versión de reglas, el motor da el mismo veredicto.
    veredicto = calcular(senales_de(analisis))
    recorrido = Recorrido(analisis.redirecciones, analisis.dominio_origen)
    explicacion = explicar(
        veredicto,
        analisis.dominio,
        recorrido,
        estados_de(analisis.fuentes),
        detalles_de(analisis),
        modalidad=analisis.modalidad,
        marca=_marca(analisis.marca_suplantada),
    )
    segundos = (timezone.now() - analisis.fecha_analisis).total_seconds()
    contexto = {
        "veredicto": veredicto,
        "nivel": veredicto.nivel,
        "explicacion": explicacion,
        "nota_fuentes": NOTA_FUENTES,
        "dominio": analisis.dominio,
        "aviso": aviso_para_compartir(veredicto, analisis.dominio),
        "fecha": analisis.fecha_analisis,
        "hace": hace_cuanto(segundos) if analisis.desde_cache else "",
        "mostrar_guia": veredicto.nivel >= Nivel.TEN_CUIDADO,
        "publico": analisis.publico,
        # Tras enviar un reporte, la página agradece en lugar de mostrar otra vez las opciones.
        "reporte": _reporte_recibido(request),
    }
    respuesta = render(request, "resultado.html", contexto)
    # El resultado lleva el dominio que pegó la persona: ni el navegador ni un proxy lo guardan.
    respuesta["Cache-Control"] = "no-store"
    return respuesta


def _reporte_recibido(request) -> str:
    reporte = request.GET.get("reporte", "")
    return reporte if reporte in REPORTES_RECIBIDOS else ""


def _marca(nombre: str) -> Marca | None:
    """La marca imitada con sus canales oficiales activos. Se lee al mostrar el resultado:
    un canal que el catálogo corrige se ve corregido también en resultados anteriores."""
    if not nombre:
        return None
    canales = CanalOficial.objects.filter(
        marca__nombre=nombre, marca__activa=True, activo=True
    ).exclude(tipo=CanalOficial.Tipo.REPORTE)
    return Marca(
        nombre, tuple((canal.get_tipo_display(), canal.valor) for canal in canales)
    )


@require_GET
def modalidades(request):
    """Página de las estafas frecuentes en el Perú. Texto fijo: no recibe datos."""
    return render(request, "modalidades.html", {"modalidades": MODALIDADES})


def _volver_al_inicio(request, error, texto, estado):
    respuesta = render(
        request, "inicio.html", {"error": error, "enlace": texto[:LARGO_MAXIMO]}, status=estado
    )
    respuesta["Cache-Control"] = "no-store"
    return respuesta
