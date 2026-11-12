from django.shortcuts import render
from django.views.decorators.http import require_POST

from analisis.destino import seguir_enlace
from analisis.edad import edad_en_dias
from analisis.heuristicas import HEURISTICAS, detectar_senales
from analisis.normalizacion import LARGO_MAXIMO, URLInvalida, normalizar
from core.entrada import ANALISIS, limitar
from inteligencia.fuentes import consultar_fuentes, fuentes_activas, resumir
from motor.explicacion import Recorrido, explicar
from motor.riesgo import Nivel, Senales, calcular


@require_POST
@limitar(ANALISIS)
def analizar(request):
    """Analiza un enlace y muestra el resultado.

    Sigue las redirecciones desde el servidor, revisa la dirección del enlace y la del
    destino, busca la edad de las dos webs y consulta las fuentes externas activas.
    Todavía no hay ninguna fuente, catálogo de marcas ni caché: la cobertura queda por
    debajo de 70 % y el resultado nunca es Seguro.
    El orquestador de la tarea 25 reemplazará esta vista por el flujo POST, redirect y GET
    hacia `/resultado/<uuid>/`.
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

    destino = seguir_enlace(enlace.url_con_parametros)
    final = _enlace_final(destino.url)
    encontradas = set(detectar_senales(enlace))
    if final is not None:
        encontradas.update(detectar_senales(final))
    dominio = final.dominio if final is not None else enlace.dominio
    # A las fuentes va la dirección de destino sin parámetros de rastreo.
    fuentes = resumir(consultar_fuentes(fuentes_activas(), (final or enlace).url))
    senales = Senales(
        tipo_entrada="enlace",
        # En el orden del registro, para que los motivos salgan siempre en el mismo orden.
        heuristicas=tuple(codigo for codigo in HEURISTICAS if codigo in encontradas),
        edad_dias=edad_en_dias([enlace.dominio, dominio]),
        fuentes=fuentes.valor,
        fuentes_con_deteccion=fuentes.confirmaciones,
    )
    recorrido = Recorrido(
        saltos=destino.saltos if final is not None else None,
        desde=enlace.dominio if dominio != enlace.dominio else "",
    )
    veredicto = calcular(senales)
    contexto = {
        "veredicto": veredicto,
        "nivel": veredicto.nivel,
        "explicacion": explicar(veredicto, dominio, recorrido),
        "dominio": dominio,
        "mostrar_guia": veredicto.nivel >= Nivel.TEN_CUIDADO,
    }
    respuesta = render(request, "resultado.html", contexto)
    # El resultado lleva el dominio que pegó la persona: ni el navegador ni un proxy lo guardan.
    respuesta["Cache-Control"] = "no-store"
    return respuesta


def _enlace_final(url: str):
    """La URL donde terminó el enlace, leída como la lee el navegador. None si no hay."""
    if not url:
        return None
    try:
        return normalizar(url)
    except URLInvalida:
        return None
