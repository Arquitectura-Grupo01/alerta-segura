"""Normalización local de enlaces, sin conexiones a internet.

El enlace se lee como lo leería el navegador de la persona, no como lo lee Python.
`https://banco.pe@sitio-falso.com` abre sitio-falso.com y el navegador trata `\\`
como `/`. Si se leyera como Python, el analizador revisaría una web distinta a la
que se abre. Los trucos se conservan en `original` para que las heurísticas los
marquen como señales de riesgo.
"""

from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from core.net import ESQUEMAS_PERMITIDOS, PUERTOS_PERMITIDOS

LARGO_MAXIMO = 2048

PUERTO_POR_DEFECTO = {"http": 80, "https": 443}

PARAMETROS_RASTREO = frozenset({
    "fbclid",
    "gclid",
    "msclkid",
    "igshid",
    "ttclid",
    "yclid",
    "mc_cid",
    "mc_eid",
})

# El navegador quita las tabulaciones y los saltos de línea de un enlace sin avisar.
CARACTERES_OCULTOS = "\t\n\r"


class URLInvalida(ValueError):
    """Indica que una URL no se puede normalizar."""


@dataclass(frozen=True)
class EnlaceNormalizado:
    """Un enlace leído como lo leería el navegador."""

    # Lo que pegó la persona, sin espacios alrededor. Las heurísticas lo revisan tal cual.
    original: str
    # URL normalizada: será la clave de la caché de resultados.
    url: str
    # Host de destino en minúsculas y punycode, sin puerto ni punto final.
    dominio: str
    # Ruta de la URL, para buscar palabras sospechosas.
    ruta: str


def normalizar(enlace: str) -> EnlaceNormalizado:
    """Normaliza un enlace sin conectarse a internet.

    Agrega `https` si falta, pasa el host a minúsculas y punycode, quita el
    usuario, el fragmento y los parámetros de rastreo. Lanza `URLInvalida` si el
    enlace no se puede leer o usa un protocolo o puerto no permitido.
    """
    if not isinstance(enlace, str):
        raise URLInvalida("El enlace debe ser un texto.")

    original = enlace.strip()
    if not original:
        raise URLInvalida("El enlace está vacío.")
    if len(original) > LARGO_MAXIMO:
        raise URLInvalida("El enlace es demasiado largo.")

    legible = original.replace("\\", "/")
    for caracter in CARACTERES_OCULTOS:
        legible = legible.replace(caracter, "")

    if any(ord(caracter) < 32 or ord(caracter) == 127 for caracter in legible):
        raise URLInvalida("El enlace contiene caracteres de control.")
    if " " in legible:
        raise URLInvalida("El enlace contiene espacios.")

    if "://" not in legible:
        # Sin esquema, un ":" antes de la primera barra es un puerto si lo siguen solo
        # números (ejemplo.com:443) y otro protocolo en los demás casos (javascript:, mailto:).
        inicio = legible.split("/", 1)[0]
        if ":" in inicio and not inicio.rpartition(":")[2].isdigit():
            raise URLInvalida("El protocolo o formato no está permitido.")
        legible = "https://" + legible

    try:
        partes = urlsplit(legible)
        esquema = partes.scheme.lower()
        if esquema not in ESQUEMAS_PERMITIDOS:
            raise URLInvalida("El protocolo no está permitido.")
        if not partes.hostname:
            raise URLInvalida("El enlace no tiene dominio.")

        # hostname ya descarta el usuario y la contraseña, igual que el navegador.
        host = partes.hostname.encode("idna").decode("ascii").lower()
        host_url = f"[{host}]" if ":" in host else host

        puerto = partes.port
        if puerto is not None:
            if puerto not in PUERTOS_PERMITIDOS:
                raise URLInvalida("El puerto no está permitido.")
            if puerto != PUERTO_POR_DEFECTO[esquema]:
                host_url = f"{host_url}:{puerto}"

        parametros = [
            (clave, valor)
            for clave, valor in parse_qsl(partes.query, keep_blank_values=True)
            if not _es_parametro_de_rastreo(clave)
        ]
        ruta = partes.path or "/"
        url = urlunsplit((esquema, host_url, ruta, urlencode(parametros), ""))
    except (ValueError, UnicodeError) as error:
        if isinstance(error, URLInvalida):
            raise
        raise URLInvalida("El formato del enlace no es válido.") from error

    return EnlaceNormalizado(original=original, url=url, dominio=host.rstrip("."), ruta=ruta)


def normalizar_url(enlace: str) -> str:
    """Devuelve solo la URL normalizada, que es la clave de la caché."""
    return normalizar(enlace).url


def _es_parametro_de_rastreo(clave: str) -> bool:
    clave = clave.lower()
    return clave.startswith("utm_") or clave in PARAMETROS_RASTREO
