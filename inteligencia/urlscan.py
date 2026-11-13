"""urlscan.io: escaneos públicos que ya existen de la dirección o de su destino final.

Solo se buscan escaneos hechos por otros; nunca se manda a escanear, porque un escaneo
público queda publicado con el token de una víctima si la dirección lo trae. Es una de
las dos fuentes que pueden decir «sin detecciones», y solo con un escaneo de las
últimas 24 h que traiga su veredicto. Plan gratuito limitado.

La búsqueda no trae el veredicto: hay que pedir el resultado del escaneo más reciente.
Son dos consultas como máximo por análisis. Si nadie escaneó esa dirección, se busca un
escaneo de la misma web solo para mostrar dónde está alojada; ese nunca da veredicto.
"""

import re
from datetime import datetime
from urllib.parse import urlencode, urlsplit

from inteligencia.fuentes import FalloDeFuente, Fuente, Respuesta, fecha_iso

URL_BUSQUEDA = "https://urlscan.io/api/v1/search/"
URL_RESULTADO = "https://urlscan.io/api/v1/result/"
RESULTADOS = 1
UUID = re.compile(r"[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}")
# Categorías de urlscan.io y el código con que `motor.explicacion` las nombra.
TIPO_VISIBLE = {"phishing": "pagina_falsa", "malware": "programa_danino"}


class Urlscan(Fuente):
    nombre = "urlscan"
    titulo = "urlscan.io"
    requiere_clave = True
    # Cupos de la búsqueda sin cuenta, los más bajos publicados. Con cuenta son mayores.
    cuota_diaria = 500
    cuota_por_minuto = 30

    def _consultar(self, url: str) -> Respuesta:
        # task.url es lo que se mandó a escanear; page.url, la página donde terminó.
        frase = _entre_comillas(url)
        escaneos = self._buscar(f'task.url.keyword:"{frase}" OR page.url.keyword:"{frase}"')
        if not escaneos:
            return self.desconocido(self._datos_de_la_web(url))
        # Vienen del más reciente al más antiguo.
        escaneo = escaneos[0]
        detalle = _datos_de_pagina(escaneo)
        veredicto = self._veredicto(escaneo)
        if veredicto is None:
            return self.desconocido(detalle)
        detalle |= _datos_de_veredicto(veredicto)
        if veredicto.get("malicious") is True:
            return self.deteccion(datos=detalle)
        # sin_detecciones exige que el escaneo sea de las últimas 24 h.
        return self.sin_detecciones(_fecha(escaneo), detalle)

    def _buscar(self, consulta: str, cantidad: int = RESULTADOS) -> list[dict]:
        _, datos = self.pedir_json(
            f"{URL_BUSQUEDA}?{urlencode({'q': consulta, 'size': cantidad})}",
            encabezados={"API-Key": self.clave},
        )
        return [escaneo for escaneo in datos["results"] if isinstance(escaneo, dict)]

    def _veredicto(self, escaneo: dict) -> dict | None:
        """El veredicto general del escaneo. None si no se pudo leer: no tumba la fuente."""
        identificador = escaneo.get("_id")
        if not isinstance(identificador, str) or not UUID.fullmatch(identificador):
            return None
        try:
            _, resultado = self.pedir_json(
                f"{URL_RESULTADO}{identificador}/", encabezados={"API-Key": self.clave}
            )
            general = resultado["verdicts"]["overall"]
        except (FalloDeFuente, KeyError, TypeError):
            # Un resultado puede pesar más de lo que se acepta leer.
            return None
        if not isinstance(general, dict) or not isinstance(general.get("malicious"), bool):
            return None
        marcas = resultado["verdicts"].get("urlscan")
        marcas = marcas.get("brands") if isinstance(marcas, dict) else None
        if isinstance(marcas, list):
            general = {**general, "nombres_de_marcas": [
                marca.get("name") for marca in marcas if isinstance(marca, dict)
            ]}
        return general

    def _datos_de_la_web(self, url: str) -> dict:
        host = urlsplit(url).hostname or ""
        if not host:
            return {}
        try:
            escaneos = self._buscar(f'page.domain:"{_entre_comillas(host)}"', cantidad=1)
        except FalloDeFuente:
            return {}
        if not escaneos:
            return {}
        return {**_datos_de_pagina(escaneos[0]), "de_otra_pagina": True}


def _entre_comillas(texto: str) -> str:
    return texto.replace("\\", "\\\\").replace('"', '\\"')


def _datos_de_pagina(escaneo: dict) -> dict:
    pagina = escaneo.get("page")
    pagina = pagina if isinstance(pagina, dict) else {}
    fecha = _fecha(escaneo)
    return {
        "analizado": fecha_iso(fecha.isoformat()) if fecha else "",
        "pais": pagina.get("country"),
        "proveedor": pagina.get("asnname"),
        # De una dirección que es solo un número, urlscan.io informa 0 días.
        "edad_web_dias": pagina.get("apexDomainAgeDays") or None,
        "certificado_dias": pagina.get("tlsAgeDays"),
    }


def _datos_de_veredicto(general: dict) -> dict:
    categorias = general.get("categories")
    categorias = categorias if isinstance(categorias, list) else []
    return {
        "puntaje": general.get("score") if general.get("malicious") else None,
        "tipos": [TIPO_VISIBLE[c] for c in categorias if c in TIPO_VISIBLE],
        "marcas": general.get("nombres_de_marcas"),
    }


def _fecha(escaneo: dict) -> datetime | None:
    try:
        return datetime.fromisoformat(escaneo["task"]["time"])
    except (KeyError, TypeError, ValueError):
        return None
