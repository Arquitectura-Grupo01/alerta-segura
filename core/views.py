import os
from datetime import date

from django.conf import settings
from django.db import connection
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET


@never_cache
@require_GET
def health(request):
    """Liveness: responde si el proceso está vivo. No toca BD ni APIs externas.

    Devuelve el commit desplegado para que el smoke test verifique que está
    probando la versión nueva y no la anterior que Render aún mantiene viva.
    El repo es público, así que exponer el SHA no filtra información nueva.
    """
    return JsonResponse({
        "status": "ok",
        "env": os.environ.get("APP_ENV", "local"),
        "commit": os.environ.get("RENDER_GIT_COMMIT", "unknown"),
    })


@never_cache
@require_GET
def ready(request):
    """Readiness: confirma que la app puede hablar con la base de datos."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception:
        # No se devuelve el detalle del error: evitaría filtrar la cadena de conexión.
        return JsonResponse({"status": "db_unavailable"}, status=503)
    return JsonResponse({"status": "ready"})




def inicio(request):
    return render(request, "inicio.html")


@require_GET
def guia(request):
    """Guía para quien ya hizo clic, dio datos o pagó. Texto fijo: no pide ni recibe datos."""
    return render(request, "guia.html")


def _legal(plantilla):
    def vista(request):
        return render(request, plantilla, {"dominio_oficial": settings.DOMINIO_OFICIAL})

    vista.__doc__ = f"Página de texto fijo `{plantilla}`. No recibe datos."
    return require_GET(vista)


privacidad = _legal("legal/privacidad.html")
terminos = _legal("legal/terminos.html")
como_verificamos = _legal("legal/como_verificamos.html")


# RFC 9116: el archivo vence y hay que renovarlo antes de esta fecha. Un test avisa.
SECURITY_TXT_VENCE = date(2027, 11, 1)
CONTACTO_SEGURIDAD = (
    "https://github.com/Arquitectura-Grupo01/alerta-segura/security/advisories/new"
)
POLITICA_SEGURIDAD = (
    "https://github.com/Arquitectura-Grupo01/alerta-segura/blob/main/SECURITY.md"
)


@require_GET
def security_txt(request):
    """`/.well-known/security.txt` según RFC 9116: a quién reportar una vulnerabilidad."""
    lineas = [
        f"Contact: {CONTACTO_SEGURIDAD}",
        f"Expires: {SECURITY_TXT_VENCE.isoformat()}T00:00:00Z",
        "Preferred-Languages: es, en",
        f"Policy: {POLITICA_SEGURIDAD}",
    ]
    if settings.DOMINIO_OFICIAL:
        lineas.append(f"Canonical: https://{settings.DOMINIO_OFICIAL}/.well-known/security.txt")
    return HttpResponse("\n".join(lineas) + "\n", content_type="text/plain; charset=utf-8")
