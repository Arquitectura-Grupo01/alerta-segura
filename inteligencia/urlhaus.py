"""URLhaus (abuse.ch): direcciones que distribuyen programas dañinos.

Es una lista de bloqueo: si la dirección no figura, el estado es «desconocido» y nunca
«sin detecciones». Uso gratuito con uso justo; un uso comercial puede necesitar el plan
pagado, y sus datos no se redistribuyen.
"""

from inteligencia.fuentes import Fuente, Respuesta

URL_CONSULTA = "https://urlhaus-api.abuse.ch/v1/url/"


class URLhaus(Fuente):
    nombre = "urlhaus"
    titulo = "URLhaus"
    requiere_clave = True

    def _consultar(self, url: str) -> Respuesta:
        _, datos = self.pedir_json(
            URL_CONSULTA,
            metodo="POST",
            encabezados={"Auth-Key": self.clave},
            datos={"url": url},
        )
        estado = datos["query_status"]
        if estado in ("no_results", "invalid_url"):
            return self.desconocido()
        if estado != "ok":
            return self.fallo()
        # Una dirección dada de baja ya no entrega el programa: suele ser una web
        # comprometida que se limpió.
        if datos.get("url_status") == "offline":
            return self.desconocido()
        return self.deteccion()
