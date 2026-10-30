from django.conf import settings


class ContentSecurityPolicyMiddleware:
    """Agrega la cabecera Content-Security-Policy a todas las respuestas.

    Se fija siempre y no solo si falta: una vista no puede debilitar la política.
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
        return response
