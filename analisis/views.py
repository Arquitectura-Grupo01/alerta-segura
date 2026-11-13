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
from core.entrada import ANALISIS, limitar
from motor.explicacion import (
    NOTA_FUENTES,
    OCUPADO,
    Recorrido,
    aviso_para_compartir,
    explicar,
    hace_cuanto,
)
from motor.riesgo import Nivel, calcular

ESPERA_SI_OCUPADO_SEGUNDOS = 10


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
    }
    respuesta = render(request, "resultado.html", contexto)
    # El resultado lleva el dominio que pegó la persona: ni el navegador ni un proxy lo guardan.
    respuesta["Cache-Control"] = "no-store"
    return respuesta


def _volver_al_inicio(request, error, texto, estado):
    respuesta = render(
        request, "inicio.html", {"error": error, "enlace": texto[:LARGO_MAXIMO]}, status=estado
    )
    respuesta["Cache-Control"] = "no-store"
    return respuesta
