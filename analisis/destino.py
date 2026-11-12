"""Seguimiento de un enlace hasta la web donde termina, sin abrirlo en el equipo de la persona.

Las redirecciones HTTP las sigue `core.net.pedir_url`, que valida cada salto. Aquí se
suman las que pide la página misma con `<meta http-equiv="refresh">` o con la cabecera
`Refresh`, que el navegador también sigue. Cada una cuenta como un salto más dentro de
`MAX_REDIRECCIONES`, y todas comparten el plazo total de una solicitud.
"""

import re
import time
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urldefrag, urljoin, urlsplit

from core.net import (
    ESQUEMAS_PERMITIDOS,
    MAX_REDIRECCIONES,
    PLAZO_TOTAL_SEGUNDOS,
    RESULTADO_DEMASIADAS_REDIRECCIONES,
    RESULTADO_OK,
    RESULTADO_RESPUESTA_GRANDE,
    RESULTADO_TIEMPO_AGOTADO,
    pedir_url,
)

# Con estos resultados la página llegó: una de más de 2 MB también es un destino.
RESULTADOS_CON_PAGINA = frozenset({RESULTADO_OK, RESULTADO_RESPUESTA_GRANDE})

# Valor de un refresco según el estándar HTML: segundos de espera, un separador y la URL,
# con «url=» opcional. «5» solo, sin URL, recarga la misma página.
REFRESCO = re.compile(
    r"\s*[0-9.]+(?:\s*[;,]\s*|\s+)(?:url\s*=\s*)?(?P<url>.*)",
    re.IGNORECASE | re.DOTALL,
)


@dataclass(frozen=True)
class Destino:
    """A dónde llevó el enlace."""

    # Resultado de la última petición, con los códigos de `core.net`.
    resultado: str
    # URL donde termina el enlace; vacía si no se pudo llegar.
    url: str = ""
    # Redirecciones seguidas, las de la página incluidas.
    saltos: int = 0


def seguir_enlace(url: str) -> Destino:
    """Sigue las redirecciones de `url` hasta la página final, con un máximo de 3 saltos."""
    limite = time.monotonic() + PLAZO_TOTAL_SEGUNDOS
    saltos = 0
    actual = url
    while True:
        restante = min(limite - time.monotonic(), PLAZO_TOTAL_SEGUNDOS)
        if restante <= 0:
            return Destino(RESULTADO_TIEMPO_AGOTADO, saltos=saltos)
        respuesta = pedir_url(
            actual,
            max_redirecciones=MAX_REDIRECCIONES - saltos,
            plazo_segundos=restante,
        )
        saltos += respuesta.saltos
        if respuesta.resultado not in RESULTADOS_CON_PAGINA:
            return Destino(respuesta.resultado, saltos=saltos)
        siguiente = _url_del_refresco(respuesta)
        if siguiente is None:
            return Destino(respuesta.resultado, url=respuesta.url_final, saltos=saltos)
        if saltos == MAX_REDIRECCIONES:
            return Destino(RESULTADO_DEMASIADAS_REDIRECCIONES, saltos=saltos)
        saltos += 1
        actual = siguiente


def _url_del_refresco(respuesta) -> str | None:
    """URL absoluta a la que manda el refresco de la página, o None si no manda a otra."""
    valor = respuesta.encabezados.get("refresh")
    tipo = respuesta.encabezados.get("content-type", "text/html").lower()
    if valor is None and "html" in tipo:
        valor = _buscar_meta_refresco(respuesta.cuerpo.decode("utf-8", errors="replace"))
    coincidencia = REFRESCO.match(valor or "")
    if coincidencia is None:
        return None
    destino = coincidencia.group("url")
    if destino[:1] in ("'", '"'):
        destino = destino[1:].split(destino[0], 1)[0]
    destino = destino.strip()
    if not destino:
        return None
    try:
        siguiente = urljoin(respuesta.url_final, destino)
        esquema = urlsplit(siguiente).scheme
    except ValueError:
        return None
    # El navegador no sigue un refresco a javascript: o data:. Ir a la misma página es recargarla.
    if esquema not in ESQUEMAS_PERMITIDOS:
        return None
    if urldefrag(siguiente).url == urldefrag(respuesta.url_final).url:
        return None
    return siguiente


class _Encontrado(Exception):
    pass


class _LectorDeRefresco(HTMLParser):
    """Busca el primer `<meta http-equiv="refresh">`, que es el único que sigue el navegador."""

    # Con JavaScript activo, el navegador no aplica lo que va dentro de estas etiquetas.
    INERTES = frozenset({"noscript", "template"})

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.contenido = None
        self._inertes = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.INERTES:
            self._inertes += 1
            return
        atributos = {nombre: valor or "" for nombre, valor in attrs}
        es_refresco = atributos.get("http-equiv", "").strip().lower() == "refresh"
        if tag == "meta" and not self._inertes and es_refresco and "content" in atributos:
            self.contenido = atributos["content"]
            raise _Encontrado

    def handle_endtag(self, tag):
        if tag in self.INERTES and self._inertes:
            self._inertes -= 1


def _buscar_meta_refresco(html: str) -> str | None:
    lector = _LectorDeRefresco()
    try:
        lector.feed(html)
        lector.close()
    except _Encontrado:
        return lector.contenido
    except AssertionError:
        # html.parser lanza AssertionError con algunas declaraciones mal formadas, como
        # «<![x[». Una página así no debe tumbar el análisis.
        return None
    return None
