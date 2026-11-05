"""Detección local de señales de riesgo en un enlace, sin visitarlo.

Cada heurística es una función registrada con `@heuristica("codigo")` que recibe
el contexto del enlace y devuelve si encontró la señal. Para agregar una, basta
con escribir la función; el motor de riesgo le asigna puntos y el motor de
explicación, su texto. `tests/test_motor.py` falla si una señal queda sin ellos.
"""

import ipaddress
import re
import unicodedata
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from urllib.parse import unquote

from analisis.normalizacion import EnlaceNormalizado, normalizar

ACORTADORES = frozenset({
    "bit.ly",
    "bitly.com",
    "cutt.ly",
    "is.gd",
    "ow.ly",
    "rb.gy",
    "rebrand.ly",
    "shorturl.at",
    "t.co",
    "t.ly",
    "tiny.cc",
    "tinyurl.com",
    "acortar.link",
})

# Se buscan dentro de la ruta: "verifica" también encuentra "verificar" y "verificacion".
PALABRAS_SOSPECHOSAS = (
    "login",
    "signin",
    "verifica",
    "valida",
    "actualiza",
    "desbloque",
    "password",
    "contrasena",
    "contraseña",
    "clave",
)

# Sufijos de dos niveles que se venden como si fueran uno. Sin esta lista,
# "bcp.com.pe" parecería un subdominio de "com.pe".
SUFIJOS_COMPUESTOS = (
    "com.pe",
    "edu.pe",
    "gob.pe",
    "mil.pe",
    "net.pe",
    "nom.pe",
    "org.pe",
)

# Alfabetos con letras que se ven iguales a las latinas (Unicode TR39).
ALFABETOS_CONFUNDIBLES = ("LATIN", "CYRILLIC", "GREEK")

MAXIMO_SUBDOMINIOS = 3


@dataclass(frozen=True)
class Contexto:
    """Lo que las heurísticas necesitan saber de un enlace."""

    # Lo que pegó la persona, con sus trucos.
    original: str
    # Host que abre el navegador, en minúsculas y punycode, sin punto final.
    dominio: str
    # Ruta decodificada y en minúsculas.
    ruta: str
    # Dominios oficiales del catálogo de marcas; vacío mientras no exista.
    oficiales: tuple[str, ...]

    @property
    def es_ip(self) -> bool:
        return _es_ip(self.dominio) or detectar_ip_alternativa(self.dominio)


Heuristica = Callable[[Contexto], bool]

HEURISTICAS: dict[str, Heuristica] = {}


def heuristica(codigo: str) -> Callable[[Heuristica], Heuristica]:
    """Registra una heurística con el código de la señal que produce."""

    def registrar(funcion: Heuristica) -> Heuristica:
        if codigo in HEURISTICAS:
            raise ValueError(f"La señal {codigo} ya está registrada.")
        HEURISTICAS[codigo] = funcion
        return funcion

    return registrar


def detectar_senales(
    enlace: str | EnlaceNormalizado,
    dominios_oficiales: Iterable[str] | None = None,
) -> list[str]:
    """Devuelve los códigos de las señales encontradas, en el orden del registro.

    Acepta el texto que pegó la persona o un enlace ya normalizado. Con texto,
    lanza `URLInvalida` si no se puede leer.
    """
    if isinstance(enlace, str):
        enlace = normalizar(enlace)

    contexto = Contexto(
        original=enlace.original,
        dominio=enlace.dominio,
        ruta=unquote(enlace.ruta).lower(),
        oficiales=tuple(_limpiar(oficial) for oficial in dominios_oficiales or ()),
    )
    return [codigo for codigo, detectar in HEURISTICAS.items() if detectar(contexto)]


# Heurísticas de la dirección


@heuristica("ip_como_dominio")
def _ip_como_dominio(contexto: Contexto) -> bool:
    return _es_ip(contexto.dominio)


@heuristica("ip_alternativa")
def _ip_alternativa(contexto: Contexto) -> bool:
    return detectar_ip_alternativa(contexto.dominio)


@heuristica("acortador")
def _acortador(contexto: Contexto) -> bool:
    return any(_pertenece(contexto.dominio, acortador) for acortador in ACORTADORES)


@heuristica("punycode")
def _punycode(contexto: Contexto) -> bool:
    return any(etiqueta.startswith("xn--") for etiqueta in contexto.dominio.split("."))


@heuristica("alfabetos_mezclados")
def _alfabetos_mezclados(contexto: Contexto) -> bool:
    return detectar_alfabetos_mezclados(contexto.dominio)


@heuristica("usuario_en_url")
def _usuario_en_url(contexto: Contexto) -> bool:
    # Todo lo que va antes de "@" es un usuario: el navegador lo ignora y abre lo de después.
    return "@" in _autoridad(contexto.original)


@heuristica("barra_invertida")
def _barra_invertida(contexto: Contexto) -> bool:
    return "\\" in contexto.original


@heuristica("caracteres_de_control")
def _caracteres_de_control(contexto: Contexto) -> bool:
    # El normalizador ya rechazó los demás; estos el navegador los borra sin avisar.
    return any(caracter in contexto.original for caracter in "\t\r\n")


@heuristica("punto_final")
def _punto_final(contexto: Contexto) -> bool:
    autoridad = _autoridad(contexto.original)
    host = autoridad.rpartition("@")[2]
    if not host.startswith("["):
        host = host.split(":", 1)[0]
    return host.endswith(".")


@heuristica("muchos_subdominios")
def _muchos_subdominios(contexto: Contexto) -> bool:
    if contexto.es_ip:
        return False
    nombre, _ = separar_dominio(contexto.dominio)
    return nombre.count(".") > MAXIMO_SUBDOMINIOS


@heuristica("palabras_sospechosas")
def _palabras_sospechosas(contexto: Contexto) -> bool:
    return any(palabra in contexto.ruta for palabra in PALABRAS_SOSPECHOSAS)


# Heurísticas de marca: solo corren con dominios oficiales del catálogo.


@heuristica("marca_en_subdominio")
def _marca_en_subdominio(contexto: Contexto) -> bool:
    return bool(contexto.oficiales) and not contexto.es_ip and bool(
        detectar_dominio_enganoso(contexto.dominio, contexto.oficiales)
    )


@heuristica("dominio_parecido")
def _dominio_parecido(contexto: Contexto) -> bool:
    return bool(contexto.oficiales) and not contexto.es_ip and bool(
        detectar_dominio_parecido(contexto.dominio, contexto.oficiales)
    )


# Funciones de apoyo. Son públicas porque los tests las prueban por separado.


def detectar_ip_alternativa(dominio: str) -> bool:
    """Detecta una IPv4 escrita de una forma que el navegador entiende y una persona no.

    El navegador acepta `2130706433`, `0x7f000001`, `0177.0.0.1` y `127.1` como
    la dirección 127.0.0.1. La forma estándar no cuenta: esa la marca
    `ip_como_dominio`.
    """
    direccion = _ipv4_del_navegador(dominio)
    return direccion is not None and str(direccion) != _limpiar(dominio)


def detectar_alfabetos_mezclados(dominio: str) -> bool:
    """Detecta una parte del dominio que mezcla letras latinas, cirílicas o griegas."""
    try:
        dominio_unicode = dominio.encode("ascii").decode("idna")
    except UnicodeError:
        dominio_unicode = dominio

    for etiqueta in dominio_unicode.split("."):
        alfabetos = {
            _alfabeto(caracter) for caracter in etiqueta if caracter.isalpha()
        } & set(ALFABETOS_CONFUNDIBLES)
        if len(alfabetos) > 1:
            return True
    return False


def detectar_dominio_enganoso(dominio: str, dominios_oficiales: Iterable[str]) -> list[str]:
    """Detecta un dominio oficial, o el nombre de su marca, usado como subdominio.

    Encuentra `bcp.com.pe.sitio-falso.com`, `seguro.bcp.com.pe.sitio.com` y
    `bcp-seguro.sitio-falso.com` para el oficial `bcp.com.pe`.
    """
    dominio = _limpiar(dominio)
    oficiales = [_limpiar(oficial) for oficial in dominios_oficiales]
    if any(_pertenece(dominio, oficial) for oficial in oficiales):
        return []

    nombre, _ = separar_dominio(dominio)
    subdominios = nombre.split(".")[:-1]
    palabras = {palabra for etiqueta in subdominios for palabra in etiqueta.split("-")}

    for oficial in oficiales:
        if f".{oficial}." in f".{dominio}":
            return ["marca_en_subdominio"]
        marca = _etiqueta_principal(oficial)
        # Con nombres de 1 o 2 letras casi cualquier subdominio coincidiría.
        if len(marca) >= 3 and marca in palabras:
            return ["marca_en_subdominio"]
    return []


def distancia_levenshtein(texto1: str, texto2: str, maximo: int | None = None) -> int:
    """Cuenta las letras que hay que agregar, quitar o cambiar para pasar de un texto al otro.

    Con `maximo`, deja de calcular apenas la distancia lo supera y devuelve `maximo + 1`.
    """
    if maximo is not None and abs(len(texto1) - len(texto2)) > maximo:
        return maximo + 1

    anterior = list(range(len(texto2) + 1))
    for i, caracter1 in enumerate(texto1, start=1):
        actual = [i]
        for j, caracter2 in enumerate(texto2, start=1):
            costo = 0 if caracter1 == caracter2 else 1
            actual.append(min(actual[j - 1] + 1, anterior[j] + 1, anterior[j - 1] + costo))
        if maximo is not None and min(actual) > maximo:
            return maximo + 1
        anterior = actual
    return anterior[-1]


def detectar_dominio_parecido(dominio: str, dominios_oficiales: Iterable[str]) -> list[str]:
    """Detecta un dominio a 1 o 2 letras de uno oficial, sin contar subdominios.

    `login.viabcpp.com` se compara como `viabcpp.com`. Con nombres de menos de 6
    letras solo cuenta 1 cambio y con menos de 3 no se compara, porque casi
    cualquier dominio corto queda cerca de otro.
    """
    dominio = _limpiar(dominio)
    oficiales = [_limpiar(oficial) for oficial in dominios_oficiales]
    if any(_pertenece(dominio, oficial) for oficial in oficiales):
        return []

    registrable = dominio_registrable(dominio)
    for oficial in oficiales:
        registrable_oficial = dominio_registrable(oficial)
        marca = _etiqueta_principal(registrable_oficial)
        if len(marca) < 3:
            continue
        maximo = 2 if len(marca) >= 6 else 1
        distancia = distancia_levenshtein(registrable, registrable_oficial, maximo)
        if 1 <= distancia <= maximo:
            return ["dominio_parecido"]
    return []


def separar_dominio(dominio: str) -> tuple[str, str]:
    """Separa un dominio en su nombre y su sufijo: `interbank.com.pe` da `interbank` y `com.pe`."""
    dominio = _limpiar(dominio)
    for sufijo in SUFIJOS_COMPUESTOS:
        if dominio.endswith("." + sufijo):
            return dominio[: -(len(sufijo) + 1)], sufijo
    if "." in dominio:
        nombre, sufijo = dominio.rsplit(".", 1)
        return nombre, sufijo
    return dominio, ""


def dominio_registrable(dominio: str) -> str:
    """Devuelve el dominio sin subdominios: `login.bcp.com.pe` da `bcp.com.pe`."""
    nombre, sufijo = separar_dominio(dominio)
    principal = nombre.rsplit(".", 1)[-1]
    return f"{principal}.{sufijo}" if sufijo else principal


def _etiqueta_principal(dominio: str) -> str:
    return separar_dominio(dominio)[0].rsplit(".", 1)[-1]


def _limpiar(dominio: str) -> str:
    return dominio.strip().lower().rstrip(".")


def _pertenece(dominio: str, base: str) -> bool:
    """Indica si el dominio es la base o uno de sus subdominios."""
    return dominio == base or dominio.endswith("." + base)


def _es_ip(dominio: str) -> bool:
    try:
        ipaddress.ip_address(dominio)
    except ValueError:
        # No es una IP escrita en la forma estándar.
        return False
    return True


def _alfabeto(caracter: str) -> str:
    # El nombre Unicode empieza por el alfabeto: "CYRILLIC SMALL LETTER A".
    return unicodedata.name(caracter, "").split(" ", 1)[0]


def _autoridad(original: str) -> str:
    """Devuelve el usuario, el host y el puerto del enlace, como los lee el navegador."""
    texto = re.sub(r"[\t\r\n]", "", original).replace("\\", "/")
    _, separador, resto = texto.partition("://")
    if not separador:
        resto = texto
    return re.split(r"[/?#]", resto, maxsplit=1)[0]


def _ipv4_del_navegador(dominio: str) -> ipaddress.IPv4Address | None:
    """Lee el host como lo hace el navegador (estándar URL de WHATWG) cuando parece una IPv4."""
    partes = _limpiar(dominio).split(".")
    if not 1 <= len(partes) <= 4:
        return None

    numeros = []
    for parte in partes:
        numero = _numero_del_navegador(parte)
        if numero is None:
            return None
        numeros.append(numero)

    *primeros, ultimo = numeros
    if any(numero > 255 for numero in primeros) or ultimo >= 256 ** (5 - len(numeros)):
        return None

    valor = ultimo
    for posicion, numero in enumerate(primeros):
        valor += numero * 256 ** (3 - posicion)
    return ipaddress.IPv4Address(valor)


def _numero_del_navegador(parte: str) -> int | None:
    if re.fullmatch(r"0x[0-9a-f]*", parte):
        return int(parte[2:] or "0", 16)
    if re.fullmatch(r"0[0-7]+", parte):
        return int(parte, 8)
    # Un cero inicial seguido de 8 o 9 no es octal válido y el navegador rechaza el host.
    if re.fullmatch(r"0|[1-9][0-9]*", parte):
        return int(parte)
    return None
