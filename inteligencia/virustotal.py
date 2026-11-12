"""VirusTotal: el último análisis que sus motores antivirus hicieron de la dirección.

Solo se consultan análisis que ya existen; nunca se envía una dirección nueva a
escanear, porque un envío queda visible para su comunidad. Es una de las dos fuentes
que pueden decir «sin detecciones», y solo con un análisis de las últimas 24 h.
La API pública prohíbe el uso comercial y solo sirve para enriquecer.
"""

import base64
from datetime import UTC, datetime

from inteligencia.fuentes import FalloDeFuente, Fuente, Respuesta

URL_BASE = "https://www.virustotal.com/api/v3/urls/"
# Desde 3 motores confirma (100); 1 o 2 son una sospecha (50). Ver docs/requisitos.md.
MOTORES_PARA_CONFIRMAR = 3
VALOR_SOSPECHA = 50


class VirusTotal(Fuente):
    nombre = "virustotal"
    titulo = "VirusTotal"
    requiere_clave = True
    cuota_diaria = 500
    cuota_por_minuto = 4

    def _consultar(self, url: str) -> Respuesta:
        # El identificador de una dirección es la dirección en base64 para URL, sin «=».
        identificador = base64.urlsafe_b64encode(url.encode()).decode().rstrip("=")
        codigo, datos = self.pedir_json(
            URL_BASE + identificador,
            encabezados={"x-apikey": self.clave},
            codigos=(200, 404),
        )
        if codigo == 404:
            return self.desconocido()
        atributos = datos["data"]["attributes"]
        motores = atributos["last_analysis_stats"]["malicious"]
        if not isinstance(motores, int) or isinstance(motores, bool) or motores < 0:
            raise FalloDeFuente()
        # Una detección cuenta aunque el análisis sea viejo; uno limpio, solo si es reciente.
        if motores >= MOTORES_PARA_CONFIRMAR:
            return self.deteccion()
        if motores > 0:
            return self.deteccion(VALOR_SOSPECHA)
        fecha = atributos.get("last_analysis_date")
        if not isinstance(fecha, int) or isinstance(fecha, bool):
            return self.desconocido()
        return self.sin_detecciones(datetime.fromtimestamp(fecha, UTC))
