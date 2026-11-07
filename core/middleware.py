from django.conf import settings
from django.http import HttpResponse

from .entrada import MAX_BYTES_CUERPO

# Cabeceras de seguridad con valor fijo. Son controles, no configuración: valen
# igual en todos los ambientes y no se leen del entorno.
CABECERAS_FIJAS = {
    # Niega todo permiso del navegador salvo la cámara del propio sitio, que usará
    # el lector de QR (tarea 43).
    "Permissions-Policy": "camera=(self), microphone=(), geolocation=(), payment=(), usb=()",
    # Aislan el sitio de otras ventanas y de recursos de otros orígenes (Spectre).
    # Todo lo que carga la interfaz es del mismo origen, así que require-corp no
    # bloquea nada propio.
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Embedder-Policy": "require-corp",
    "Cross-Origin-Resource-Policy": "same-origin",
}


class CabecerasSeguridadMiddleware:
    """Agrega a todas las respuestas la CSP y las demás cabeceras de seguridad fijas.

    Se asignan siempre y no solo si faltan: una vista no puede debilitarlas.

    Una respuesta que no trae Cache-Control sale con no-store, para que ninguna
    página con un token de CSRF o con un resultado quede en una caché compartida.
    Los archivos estáticos de WhiteNoise y las vistas con política propia
    (never_cache) conservan la suya.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        cabecera = (
            "Content-Security-Policy-Report-Only"
            if settings.CONTENT_SECURITY_POLICY_REPORT_ONLY
            else "Content-Security-Policy"
        )
        response.headers[cabecera] = settings.CONTENT_SECURITY_POLICY
        for nombre, valor in CABECERAS_FIJAS.items():
            response.headers[nombre] = valor
        if "Cache-Control" not in response.headers:
            response.headers["Cache-Control"] = "no-store"
        return response



class LimiteDeTamanoMiddleware:
    """Rechaza por su Content-Length una solicitud que no cabe, antes de leer el cuerpo.

    Django no limita el tamaño total de los archivos subidos. Esto corta los de más de
    5 MB sin leerlos. Un cuerpo más largo que su Content-Length no llega a la vista:
    Django lee exactamente esa cantidad de bytes y ni un byte más.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        largo = request.META.get("CONTENT_LENGTH", "")
        if largo:
            try:
                bytes_declarados = int(largo)
            except ValueError:
                bytes_declarados = -1
            if bytes_declarados < 0:
                return HttpResponse("Solicitud inválida.", status=400, content_type="text/plain")
            if bytes_declarados > MAX_BYTES_CUERPO:
                return HttpResponse(
                    "La solicitud es demasiado grande.", status=413, content_type="text/plain",
                )
        return self.get_response(request)
