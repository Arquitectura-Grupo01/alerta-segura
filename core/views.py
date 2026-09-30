import os

from django.db import connection
from django.http import JsonResponse
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
