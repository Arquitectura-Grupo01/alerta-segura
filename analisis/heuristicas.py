
"""Detección local de señales sospechosas en URLs."""

import ipaddress
import re
import unicodedata
from urllib.parse import urlsplit

ACORTADORES = frozenset({
    "bit.ly",
    "tinyurl.com",
    "t.co",
    "cutt.ly",
    "is.gd",
})

PALABRAS_SOSPECHOSAS = frozenset({
    "login",
    "verifica",
    "verificar",
    "password",
    "contrasena",
    "actualizar",
})


def detectar_senales(
    enlace: str,
    dominios_oficiales: list[str] | None = None,
) -> list[str]:

    """Detecta señales de riesgo sin visitar el enlace."""

    senales = []
    partes = urlsplit(enlace)
    dominio = (partes.hostname or "").lower().rstrip(".")

    try:
        ipaddress.ip_address(dominio)
        senales.append("ip_como_dominio")
    except ValueError:
        pass

    if dominio in ACORTADORES:
        senales.append("acortador")

    if dominio.startswith("xn--") or ".xn--" in dominio:
        senales.append("punycode")

    etiquetas = dominio.split(".")
    if len(etiquetas) > 5:
        senales.append("muchos_subdominios")

    ruta = partes.path.lower()
    if any(palabra in ruta for palabra in PALABRAS_SOSPECHOSAS):
        senales.append("palabras_sospechosas")

    if partes.username is not None:
        senales.append("usuario_en_url")

    if "\\" in enlace:
        senales.append("barra_invertida")

    "detecta si el dominio es una IP en formato decimal, hexadecimal u octal"
    if detectar_ip_alternativa(dominio):
        senales.append("ip_alternativa")

    if detectar_alfabetos_mezclados(dominio):
        senales.append("alfabetos_mezclados")


    "detecta si el dominio contiene un dominio oficial como subdominio o es similar a uno oficial"
    if dominios_oficiales:
        senales.extend(
            detectar_dominio_enganoso(dominio, dominios_oficiales)
        )
        senales.extend(
            detectar_dominio_parecido(dominio, dominios_oficiales)
        )

    return senales


"""Detecta formatos no convencionales de IPv4."""

def detectar_ip_alternativa(dominio: str) -> bool:
    """Detecta formatos no convencionales de IPv4."""

    dominio = dominio.lower().rstrip(".")

    if dominio.startswith("0x"):
        return bool(re.fullmatch(r"0x[0-9a-f]+", dominio))

    if dominio.isascii() and dominio.isdecimal():
        return True

    partes = dominio.split(".")

    if len(partes) == 4:
        return any(
            len(parte) > 1 and parte.startswith("0")
            for parte in partes
            if parte.isascii() and parte.isdecimal()
        )

    return False


def detectar_alfabetos_mezclados(dominio: str) -> bool:
    """Detecta mezclas de letras latinas y cirílicas."""

    try:
        dominio_unicode = dominio.encode("ascii").decode("idna")
    except (UnicodeError, UnicodeDecodeError):
        dominio_unicode = dominio

    for etiqueta in dominio_unicode.split("."):
        alfabetos = set()

        for caracter in etiqueta:
            if not caracter.isalpha():
                continue

            nombre = unicodedata.name(caracter, "")

            if "LATIN" in nombre:
                alfabetos.add("latin")
            elif "CYRILLIC" in nombre:
                alfabetos.add("cirilico")

        if len(alfabetos) > 1:
            return True

    return False


def detectar_dominio_enganoso(
    dominio: str,
    dominios_oficiales: list[str],
) -> list[str]:
    """Busca dominios oficiales usados como subdominios falsos."""

    senales = []
    dominio = dominio.lower().rstrip(".")

    for oficial in dominios_oficiales:
        oficial = oficial.lower().rstrip(".")

        if dominio == oficial or dominio.endswith("." + oficial):
            continue

        if dominio.startswith(oficial + "."):
            senales.append("marca_en_subdominio")
            break

    return senales


"""Calcula la distancia de Levenshtein entre dos textos."""

def distancia_levenshtein(texto1: str, texto2: str) -> int:
    """Calcula las modificaciones entre dos textos."""

    anterior = list(range(len(texto2) + 1))

    for i, caracter1 in enumerate(texto1, start=1):
        actual = [i]

        for j, caracter2 in enumerate(texto2, start=1):
            costo = 0 if caracter1 == caracter2 else 1

            actual.append(
                min(
                    actual[j - 1] + 1,
                    anterior[j] + 1,
                    anterior[j - 1] + costo,
                )
            )

        anterior = actual

    return anterior[-1]



"Detecta dominios similares a los oficiales."
def detectar_dominio_parecido(
    dominio: str,
    dominios_oficiales: list[str],
) -> list[str]:
    """Detecta dominios similares a los oficiales."""

    dominio = dominio.lower().rstrip(".")
    senales = []

    for oficial in dominios_oficiales:
        oficial = oficial.lower().rstrip(".")

        # El dominio oficial y sus subdominios son válidos.
        if dominio == oficial or dominio.endswith("." + oficial):
            continue

        # Comparamos nombres con la misma extensión.
        if "." not in dominio or "." not in oficial:
            continue

        nombre, extension = separar_dominio(dominio)
        nombre_oficial, extension_oficial = separar_dominio(oficial)

        if extension != extension_oficial:
            continue

        distancia = distancia_levenshtein(nombre, nombre_oficial)

        if 1 <= distancia <= 2:
            senales.append("dominio_parecido")
            break

    return senales

"Separa el nombre y el sufijo de un dominio."
def separar_dominio(dominio: str) -> tuple[str, str]:
    """Separa el nombre y el sufijo de un dominio."""

    dominio = dominio.lower().rstrip(".")

    sufijos_compuestos = (
        "com.pe",
        "org.pe",
        "edu.pe",
        "gob.pe",
        "net.pe",
    )

    for sufijo in sufijos_compuestos:
        if dominio.endswith("." + sufijo):
            nombre = dominio[: -(len(sufijo) + 1)]
            return nombre, sufijo

    if "." in dominio:
        nombre, sufijo = dominio.rsplit(".", 1)
        return nombre, sufijo

    return dominio, ""