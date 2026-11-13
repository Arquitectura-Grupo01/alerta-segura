from django.core.exceptions import BadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import urlencode
from django.views.decorators.http import require_GET, require_POST

from analisis.models import Analisis
from analisis.normalizacion import LARGO_MAXIMO, URLInvalida, normalizar
from core.enmascarado import enmascarar
from core.entrada import REPORTES, limitar
from curacion.models import ReporteDesacuerdo, SolicitudRevision
from motor import reputacion


@require_POST
@limitar(REPORTES)
def reportar(request, publico):
    """Guarda el reporte de una persona sobre un resultado y vuelve a ese resultado.

    Vive en `curacion` porque ninguna app importa de aquí. Solo agrega un reporte
    pendiente: el veredicto, la reputación y la caché quedan como estaban.
    """
    analisis = get_object_or_404(Analisis, publico=publico)
    try:
        tipo = ReporteDesacuerdo.Tipo(request.POST.get("tipo", ""))
    except ValueError:
        raise BadRequest("Tipo de reporte desconocido") from None
    reporte = ReporteDesacuerdo.objects.create(analisis=analisis, tipo=tipo)
    # Solo suma al contador: el motor no lo lee y el veredicto queda igual.
    reputacion.sumar_reporte(analisis.dominio, reporte.tipo)
    # POST, redirect y GET, como el análisis: al recargar no se envía otro reporte. La
    # dirección sale de `reverse` y el parámetro es uno de los dos tipos del modelo.
    destino = reverse("resultado", args=[analisis.publico])
    return redirect(f"{destino}?{urlencode({'reporte': reporte.tipo})}#reporte")


ERROR_DOMINIO = "Escribe el nombre de tu web, por ejemplo ejemplo.com."
ERROR_MENSAJE = "Cuéntanos en pocas palabras por qué crees que es un error."
ERROR_LARGO = f"El mensaje puede tener hasta {SolicitudRevision.MAX_MENSAJE} caracteres."


@require_GET
def contacto(request):
    """Formulario para dueños de webs marcadas por error. No guarda nada al mostrarse."""
    contexto = {
        "enviado": request.GET.get("enviado") == "1",
        "max_mensaje": SolicitudRevision.MAX_MENSAJE,
    }
    return render(request, "legal/contacto.html", contexto)


@require_POST
@limitar(REPORTES)
def solicitar_revision(request):
    """Recibe el pedido del dueño de una web y lo deja pendiente en la cola de curación.

    Comparte el límite de los reportes: 10 por hora desde un mismo origen.
    """
    dominio_texto = request.POST.get("dominio", "")[: LARGO_MAXIMO + 1].strip()
    mensaje = request.POST.get("mensaje", "").strip()
    errores = {}
    dominio = ""
    try:
        dominio = normalizar(dominio_texto).dominio
    except URLInvalida:
        errores["dominio"] = ERROR_DOMINIO
    if not mensaje:
        errores["mensaje"] = ERROR_MENSAJE
    elif len(mensaje) > SolicitudRevision.MAX_MENSAJE:
        errores["mensaje"] = ERROR_LARGO
    if errores:
        respuesta = render(
            request,
            "legal/contacto.html",
            {
                "errores": errores,
                "dominio": dominio_texto[:LARGO_MAXIMO],
                "mensaje": mensaje[: SolicitudRevision.MAX_MENSAJE],
                "max_mensaje": SolicitudRevision.MAX_MENSAJE,
            },
            status=400,
        )
        respuesta["Cache-Control"] = "no-store"
        return respuesta
    # El dueño puede dejar su correo o su teléfono en el mensaje: se guardan enmascarados.
    SolicitudRevision.objects.create(dominio=dominio, mensaje=enmascarar(mensaje))
    return redirect(f"{reverse('contacto')}?{urlencode({'enviado': '1'})}#formulario")
