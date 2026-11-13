"""Google Safe Browsing v5: listas de páginas falsas y de programas dañinos.

Se consulta por prefijo de hash (`hashes:search`): a Google solo llegan los primeros
4 bytes del SHA-256 de cada forma de la dirección, nunca la URL del ciudadano. Google
devuelve los hashes completos que empiezan así y la comparación se hace aquí.
La v5 solo responde en protobuf; con `alt=json` contesta 400. El mensaje es corto y
se lee aquí, sin sumar una dependencia.

Es una lista de bloqueo: si la dirección no figura, el estado es «desconocido», no
«sin detecciones». Gratis solo para uso no comercial.
"""

import base64
import hashlib
import ipaddress
import posixpath
import re
from urllib.parse import quote, unquote_to_bytes, urlencode, urlsplit

from core.net import RESULTADO_OK, pedir_url
from inteligencia.fuentes import MOTIVO_ERROR, MOTIVO_TIEMPO, Fuente, Respuesta

URL_BUSQUEDA = "https://safebrowsing.googleapis.com/v5/hashes:search"
BYTES_DE_PREFIJO = 4
# Lo que aporta esta fuente según docs/requisitos.md. Un tipo que no está aquí se ignora.
AMENAZAS = frozenset({"MALWARE", "SOCIAL_ENGINEERING"})
# Números del enum ThreatType de la v5.
TIPOS_DE_AMENAZA = {
    1: "MALWARE",
    2: "SOCIAL_ENGINEERING",
    3: "UNWANTED_SOFTWARE",
    4: "POTENTIALLY_HARMFUL_APPLICATION",
}
# Cómo se le dice a la persona cada tipo: los códigos están en `motor.explicacion`.
TIPO_VISIBLE = {
    "SOCIAL_ENGINEERING": "pagina_falsa",
    "MALWARE": "programa_danino",
    "UNWANTED_SOFTWARE": "programa_no_deseado",
    "POTENTIALLY_HARMFUL_APPLICATION": "aplicacion_riesgosa",
}
MAX_HOSTS = 5
MAX_RUTAS = 6


class SafeBrowsing(Fuente):
    nombre = "safe_browsing"
    titulo = "Google Safe Browsing"
    # Cuota gratuita por defecto del proyecto de Google Cloud.
    cuota_diaria = 10_000

    def disponible(self) -> bool:
        return bool(self.clave)

    def _consultar(self, url: str) -> Respuesta:
        hashes = {hashlib.sha256(forma.encode()).digest() for forma in expresiones(url)}
        if not hashes:
            return self.desconocido()
        prefijos = sorted({_base64(completo[:BYTES_DE_PREFIJO]) for completo in hashes})
        consulta = urlencode(
            [("key", self.clave), *(("hashPrefixes", p) for p in prefijos)]
        )
        respuesta = pedir_url(
            f"{URL_BUSQUEDA}?{consulta}", max_redirecciones=0, plazo_segundos=self.plazo_segundos
        )
        if respuesta.resultado != RESULTADO_OK:
            return self.fallo(MOTIVO_TIEMPO if "tiempo" in respuesta.resultado else MOTIVO_ERROR)
        if respuesta.codigo_http != 200:
            return self.fallo()
        try:
            encontrados = leer_respuesta(respuesta.cuerpo)
        except ValueError:
            return self.fallo()
        # Los de otro sitio cuyo hash empieza igual no cuentan.
        tipos = {tipo for completo, tipo in encontrados if completo in hashes}
        if not tipos & AMENAZAS:
            return self.desconocido()
        # Página falsa primero: es lo que más le importa a quien recibió el enlace.
        visibles = [TIPO_VISIBLE[tipo] for tipo in TIPO_VISIBLE if tipo in tipos]
        return self.deteccion(datos={"tipos": visibles})


def leer_respuesta(cuerpo: bytes) -> list[tuple[bytes, str]]:
    """Lee un SearchHashesResponse y devuelve (hash completo, tipo de amenaza).

    El mensaje trae `full_hashes` en el campo 1. Cada uno lleva el hash en su campo 1 y
    sus detalles en el 2, con el tipo de amenaza en el campo 1 del detalle.
    """
    encontrados = []
    for numero, valor in _campos(cuerpo):
        if numero != 1 or not isinstance(valor, bytes):
            continue
        completo = b""
        tipos = []
        for campo, contenido in _campos(valor):
            if campo == 1 and isinstance(contenido, bytes):
                completo = contenido
            elif campo == 2 and isinstance(contenido, bytes):
                tipos += [dato for sub, dato in _campos(contenido) if sub == 1]
        encontrados += [
            (completo, TIPOS_DE_AMENAZA[tipo]) for tipo in tipos if tipo in TIPOS_DE_AMENAZA
        ]
    return encontrados


def _campos(datos: bytes) -> list[tuple[int, int | bytes]]:
    """Los campos de un mensaje protobuf: (número, entero o bytes). ValueError si está roto."""
    campos = []
    posicion = 0
    while posicion < len(datos):
        etiqueta, posicion = _varint(datos, posicion)
        numero, tipo = etiqueta >> 3, etiqueta & 7
        if tipo == 0:
            valor, posicion = _varint(datos, posicion)
        elif tipo == 2:
            largo, posicion = _varint(datos, posicion)
            valor = datos[posicion:posicion + largo]
            if len(valor) != largo:
                raise ValueError("protobuf cortado")
            posicion += largo
        elif tipo in (1, 5):
            # Números de ancho fijo: esta respuesta no los usa, pero se saltan bien.
            ancho = 8 if tipo == 1 else 4
            valor = datos[posicion:posicion + ancho]
            if len(valor) != ancho:
                raise ValueError("protobuf cortado")
            posicion += ancho
        else:
            raise ValueError("protobuf con un tipo de campo desconocido")
        campos.append((numero, valor))
    return campos


def _varint(datos: bytes, posicion: int) -> tuple[int, int]:
    valor = 0
    for desplazamiento in range(0, 70, 7):
        if posicion >= len(datos):
            raise ValueError("protobuf cortado")
        byte = datos[posicion]
        posicion += 1
        valor |= (byte & 0x7F) << desplazamiento
        if not byte & 0x80:
            return valor, posicion
    raise ValueError("varint demasiado largo")


def expresiones(url: str) -> list[str]:
    """Las formas host/ruta de una URL que Google tiene en sus listas, 30 como máximo.

    Sigue «URLs and Hashing» de Safe Browsing: hasta 5 hosts, del exacto a los últimos
    componentes, por hasta 6 rutas, de la exacta con parámetros a la raíz.
    """
    try:
        host, ruta, parametros = _canonizar(url)
    except ValueError:
        return []
    return [h + r for h in _hosts(host) for r in _rutas(ruta, parametros)]


def _canonizar(url: str) -> tuple[str, str, str]:
    url = re.sub(r"[\t\r\n]", "", url).split("#", 1)[0]
    partes = urlsplit(url)
    host = _desescapar(partes.hostname or "").decode("utf-8", "surrogateescape")
    host = re.sub(r"\.{2,}", ".", host.strip(".")).lower()
    if not host:
        raise ValueError("La URL no tiene host")
    ruta = _desescapar(partes.path or "/")
    # posixpath resuelve /./ y /../ y junta las barras repetidas.
    termina_en_barra = ruta.endswith((b"/", b"/.", b"/.."))
    ruta = posixpath.normpath(ruta).lstrip(b"/")
    ruta = b"/" + ruta + (b"/" if termina_en_barra and ruta not in (b"", b".") else b"")
    if ruta in (b"/.", b"/./"):
        ruta = b"/"
    return _escapar(host.encode("utf-8", "surrogateescape")), _escapar(ruta), partes.query


def _desescapar(texto: str) -> bytes:
    """Quita los %XX las veces que haga falta: %2525 termina en %."""
    datos = texto.encode("utf-8", "surrogateescape")
    while True:
        nuevo = unquote_to_bytes(datos)
        if nuevo == datos:
            return datos
        datos = nuevo


def _escapar(datos: bytes) -> str:
    # Se escapan los bytes hasta 32, desde 127, «#» y «%», con hexadecimal en mayúsculas.
    seguros = bytes(b for b in range(33, 127) if b not in b"#%")
    return quote(datos, safe=seguros)


def _hosts(host: str) -> list[str]:
    try:
        ipaddress.ip_address(host.strip("[]"))
        return [host]
    except ValueError:
        pass  # no es una IP: se prueban también sus dominios superiores
    partes = host.split(".")
    # Con los últimos 5 componentes, quitando el primero cada vez, sin llegar al TLD.
    cortos = [".".join(partes[i:]) for i in range(max(1, len(partes) - 5), len(partes) - 1)]
    return list(dict.fromkeys([host, *cortos]))[:MAX_HOSTS]


def _rutas(ruta: str, parametros: str) -> list[str]:
    rutas = [f"{ruta}?{parametros}"] if parametros else []
    rutas.append(ruta)
    componentes = ruta.split("/")[1:-1]
    for cantidad in range(min(len(componentes), 3) + 1):
        rutas.append("/" + "".join(parte + "/" for parte in componentes[:cantidad]))
    return list(dict.fromkeys(rutas))[:MAX_RUTAS]


def _base64(datos: bytes) -> str:
    return base64.b64encode(datos).decode().rstrip("=")
