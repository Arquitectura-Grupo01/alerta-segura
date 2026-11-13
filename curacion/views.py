from django.core.exceptions import BadRequest
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils.http import urlencode
from django.views.decorators.http import require_POST

from analisis.models import Analisis
from core.entrada import REPORTES, limitar
from curacion.models import ReporteDesacuerdo
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
