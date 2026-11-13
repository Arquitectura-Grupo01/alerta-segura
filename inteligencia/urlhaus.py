"""URLhaus (abuse.ch): direcciones que distribuyen programas dañinos.

Es una lista de bloqueo: si la dirección no figura, el estado es «desconocido» y nunca
«sin detecciones». Uso gratuito con uso justo; un uso comercial puede necesitar el plan
pagado, y sus datos no se redistribuyen.
"""

from inteligencia.fuentes import Fuente, Respuesta, fecha_iso

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
        archivos = datos.get("payloads")
        etiquetas = datos.get("tags")
        detalle = {
            "tipos": ["programa_danino"],
            "agregada": fecha_iso(datos.get("date_added")),
            "familias": etiquetas if isinstance(etiquetas, list) else None,
            "archivos": len(archivos) if isinstance(archivos, list) and archivos else None,
        }
        # Una dirección dada de baja ya no entrega el programa: suele ser una web
        # comprometida que se limpió.
        if datos.get("url_status") == "offline":
            return self.desconocido({**detalle, "dada_de_baja": True})
        return self.deteccion(datos=detalle)
