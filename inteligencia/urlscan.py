"""urlscan.io: escaneos públicos que ya existen de la dirección o de su destino final.

Solo se buscan escaneos hechos por otros; nunca se manda a escanear, porque un escaneo
público queda publicado con el token de una víctima si la dirección lo trae. Es una de
las dos fuentes que pueden decir «sin detecciones», y solo con un escaneo de las
últimas 24 h que traiga su veredicto. Plan gratuito limitado.
"""

from datetime import datetime
from urllib.parse import urlencode

from inteligencia.fuentes import Fuente, Respuesta

URL_BUSQUEDA = "https://urlscan.io/api/v1/search/"
RESULTADOS = 10


class Urlscan(Fuente):
    nombre = "urlscan"
    titulo = "urlscan.io"
    requiere_clave = True
    # Cupos de la búsqueda sin cuenta, los más bajos publicados. Con cuenta son mayores.
    cuota_diaria = 500
    cuota_por_minuto = 30

    def _consultar(self, url: str) -> Respuesta:
        # task.url es lo que se mandó a escanear; page.url, la página donde terminó.
        frase = url.replace("\\", "\\\\").replace('"', '\\"')
        consulta = f'task.url.keyword:"{frase}" OR page.url.keyword:"{frase}"'
        _, datos = self.pedir_json(
            f"{URL_BUSQUEDA}?{urlencode({'q': consulta, 'size': RESULTADOS})}",
            encabezados={"API-Key": self.clave},
        )
        limpios = []
        for escaneo in datos["results"]:
            malicioso = _veredicto(escaneo)
            if malicioso is True:
                return self.deteccion()
            if malicioso is False:
                limpios.append(_fecha(escaneo))
        limpios = [fecha for fecha in limpios if fecha is not None]
        if limpios:
            # sin_detecciones exige que el escaneo sea de las últimas 24 h.
            return self.sin_detecciones(max(limpios))
        return self.desconocido()


def _veredicto(escaneo: dict) -> bool | None:
    """True o False si el escaneo trae su veredicto; None si no lo trae."""
    veredictos = escaneo.get("verdicts")
    if not isinstance(veredictos, dict):
        return None
    if isinstance(veredictos.get("malicious"), bool):
        return veredictos["malicious"]
    general = veredictos.get("overall")
    if isinstance(general, dict) and isinstance(general.get("malicious"), bool):
        return general["malicious"]
    return None


def _fecha(escaneo: dict) -> datetime | None:
    try:
        return datetime.fromisoformat(escaneo["task"]["time"])
    except (KeyError, TypeError, ValueError):
        return None
