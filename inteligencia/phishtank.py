"""PhishTank: páginas falsas verificadas por su comunidad.

Es una lista de bloqueo: si la dirección no figura, el estado es «desconocido». Solo
cuenta una página verificada y todavía activa. Requiere registro: sin clave, la fuente
se omite sin tocar el motor.
"""

from inteligencia.fuentes import Fuente, Respuesta

URL_CONSULTA = "https://checkurl.phishtank.com/checkurl/"


class PhishTank(Fuente):
    nombre = "phishtank"
    titulo = "PhishTank"
    requiere_clave = True

    def _consultar(self, url: str) -> Respuesta:
        _, datos = self.pedir_json(
            URL_CONSULTA,
            metodo="POST",
            datos={"url": url, "format": "json", "app_key": self.clave},
        )
        resultado = datos["results"]
        figura = _si(resultado.get("in_database"))
        if figura and _si(resultado.get("verified")) and _si(resultado.get("valid")):
            return self.deteccion(datos={"tipos": ["pagina_falsa"]})
        return self.desconocido()


def _si(valor) -> bool:
    """PhishTank responde con booleanos o con textos como «y», según el campo."""
    if isinstance(valor, bool):
        return valor
    return isinstance(valor, str) and valor.strip().lower() in ("y", "yes", "true")
