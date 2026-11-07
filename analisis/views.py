from django.shortcuts import render
from django.views.decorators.http import require_POST

from analisis.heuristicas import detectar_senales
from analisis.normalizacion import LARGO_MAXIMO, URLInvalida, normalizar
from core.entrada import ANALISIS, limitar
from motor.explicacion import explicar
from motor.riesgo import Nivel, Senales, calcular


@require_POST
@limitar(ANALISIS)
def analizar(request):
    """Analiza un enlace con las heurísticas locales y muestra el resultado.

    Todavía no hay fuentes externas, edad del dominio, catálogo de marcas ni
    caché: la cobertura queda por debajo de 70 % y el resultado nunca es Seguro.
    El orquestador de la tarea 25 reemplazará esta vista por el flujo POST,
    redirect y GET hacia `/resultado/<uuid>/`.
    """
    texto = request.POST.get("enlace", "")[:LARGO_MAXIMO + 1]
    try:
        enlace = normalizar(texto)
    except URLInvalida as error:
        # Los mensajes de URLInvalida están escritos para la persona y no traen datos internos.
        respuesta = render(
            request,
            "inicio.html",
            {"error": str(error), "enlace": texto[:LARGO_MAXIMO]},
            status=400,
        )
        respuesta["Cache-Control"] = "no-store"
        return respuesta

    codigos = detectar_senales(enlace)
    veredicto = calcular(Senales(tipo_entrada="enlace", heuristicas=tuple(codigos)))
    contexto = {
        "veredicto": veredicto,
        "nivel": veredicto.nivel,
        "explicacion": explicar(veredicto, enlace.dominio),
        "dominio": enlace.dominio,
        "mostrar_guia": veredicto.nivel >= Nivel.TEN_CUIDADO,
    }
    respuesta = render(request, "resultado.html", contexto)
    # El resultado lleva el dominio que pegó la persona: ni el navegador ni un proxy lo guardan.
    respuesta["Cache-Control"] = "no-store"
    return respuesta
