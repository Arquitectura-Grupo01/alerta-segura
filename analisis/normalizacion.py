
"""Normalización local de enlaces para Alerta Segura."""

from urllib.parse import (
    parse_qsl,
    urlencode,
    urlsplit,
    urlunsplit,
)

PARAMETROS_RASTREO = frozenset({
    "fbclid",
    "gclid",
    "msclkid",
})


class URLInvalida(ValueError):
    """Indica que una URL no se puede normalizar."""


def normalizar_url(enlace: str) -> str:
    """Normaliza un enlace sin realizar conexiones a internet."""

    if not isinstance(enlace, str):
        raise URLInvalida("El enlace debe ser un texto.")

    enlace = enlace.strip()

    if not enlace:
        raise URLInvalida("El enlace está vacío.")

    if len(enlace) > 2048:
        raise URLInvalida("El enlace es demasiado largo.")

    if any(ord(caracter) < 32 or ord(caracter) == 127
           for caracter in enlace):
        raise URLInvalida("El enlace contiene caracteres de control.")

    if "\\" in enlace:
        raise URLInvalida("El enlace contiene barras invertidas.")

    if " " in enlace:
        raise URLInvalida("El enlace contiene espacios.")


    "detecta si el enlace contiene un dominio oficial como subdominio o es similar a uno oficial"
    if "://" not in enlace:
        if ":" in enlace.split("/", 1)[0]:
            raise URLInvalida("El protocolo o formato no está permitido.")
        enlace = "https://" + enlace

    try:
        partes = urlsplit(enlace)

        if partes.scheme.lower() not in ("http", "https"):
            raise URLInvalida("El protocolo no está permitido.")

        if not partes.hostname:
            raise URLInvalida("El enlace no tiene dominio.")

        if partes.username is not None or partes.password is not None:
            raise URLInvalida("El enlace contiene credenciales o el símbolo @.")

        dominio = partes.hostname.encode("idna").decode("ascii").lower()
        puerto = partes.port

        if ":" in dominio:
            dominio = f"[{dominio}]"

        if puerto is not None:
            if puerto not in (80, 443):
                raise URLInvalida("El puerto no está permitido.")

            puerto_predeterminado = (
                partes.scheme == "https" and puerto == 443
            ) or (
                partes.scheme == "http" and puerto == 80
            )

            if not puerto_predeterminado:
                dominio = f"{dominio}:{puerto}"

        parametros = parse_qsl(
            partes.query,
            keep_blank_values=True,
        )

        parametros_limpios = [
            (clave, valor)
            for clave, valor in parametros
            if not clave.lower().startswith("utm_")
            and clave.lower() not in PARAMETROS_RASTREO
        ]

        ruta = partes.path or "/"

        return urlunsplit((
            partes.scheme.lower(),
            dominio,
            ruta,
            urlencode(parametros_limpios),
            "",
        ))

    except (ValueError, UnicodeError) as error:
        if isinstance(error, URLInvalida):
            raise
        raise URLInvalida("El formato del enlace no es válido.") from error
