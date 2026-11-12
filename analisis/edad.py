"""Edad de un dominio por RDAP, el reemplazo de WHOIS que va por HTTPS.

WHOIS usa el puerto 43, que la política de salida bloquea. El servidor RDAP de cada
dominio de primer nivel sale del registro de IANA (RFC 9224), que cada proceso pide una
vez al día. Si un dominio no tiene RDAP, como los `.pe`, o la consulta falla, la edad
queda sin dato: nunca se asume antigua.
"""

import json
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from analisis.heuristicas import ACORTADORES
from core.net import PLAZO_TOTAL_SEGUNDOS, RESULTADO_OK, pedir_url
from motor.riesgo import VERSION_INICIAL

URL_REGISTRO_IANA = "https://data.iana.org/rdap/dns.json"
VIGENCIA_REGISTRO_SEGUNDOS = 24 * 60 * 60
# Si IANA no responde, el siguiente intento espera: si no, cada análisis pagaría el plazo.
ESPERA_TRAS_FALLO_SEGUNDOS = 10 * 60
# Tiempo para la edad de todos los dominios de un análisis, registro de IANA incluido.
PLAZO_RDAP_SEGUNDOS = 5

# Webs que dan subdominios a cualquiera. La edad de netlify.app no dice nada de
# estafa.netlify.app, que pudo crearse ayer.
ALOJAMIENTOS_COMPARTIDOS = frozenset({
    "000webhostapp.com",
    "appspot.com",
    "azurewebsites.net",
    "blogspot.com",
    "firebaseapp.com",
    "github.io",
    "glitch.me",
    "godaddysites.com",
    "herokuapp.com",
    "netlify.app",
    "onrender.com",
    "pages.dev",
    "vercel.app",
    "web.app",
    "webflow.io",
    "weebly.com",
    "wixsite.com",
    "workers.dev",
})

# Segundos niveles que muchos países usan como sufijo, como en com.ar o co.uk. Nunca se
# consultan solos: el RDAP de .ar da una fecha de registro para com.ar.
SEGUNDOS_NIVELES = frozenset({"ac", "co", "com", "edu", "gob", "gov", "mil", "net", "nom", "org"})

ERRORES_DE_LECTURA = (ValueError, TypeError, KeyError, IndexError, AttributeError, RecursionError)


@dataclass
class _RegistroIana:
    """Servidores RDAP por dominio de primer nivel, guardados en el proceso."""

    bases: dict[str, str] = field(default_factory=dict)
    # Hora de `time.monotonic()` en que toca pedir el registro otra vez.
    renovar: float = 0.0


_registro = _RegistroIana()


def edad_en_dias(dominios: Iterable[str]) -> int | None:
    """Días desde el registro del dominio más nuevo entre `dominios`, o None sin dato.

    Recibe la web del enlace y la de destino. Los acortadores no cuentan: su edad no dice
    nada del destino. Si falta la edad de alguno, solo se informa la de una web nueva,
    porque una web antigua al final de la cadena puede esconder una nueva al inicio.
    """
    limite = time.monotonic() + PLAZO_RDAP_SEGUNDOS
    fechas: dict[tuple[str, ...], datetime | None] = {}
    for dominio in dominios:
        if _pertenece(dominio, ACORTADORES):
            continue
        candidatos = () if _pertenece(dominio, ALOJAMIENTOS_COMPARTIDOS) else _candidatos(dominio)
        if candidatos not in fechas:
            fechas[candidatos] = _fecha_de_registro(candidatos, limite)

    conocidas = [fecha for fecha in fechas.values() if fecha is not None]
    if not conocidas:
        return None
    dias = max(0, (datetime.now(UTC) - max(conocidas)).days)
    if len(conocidas) < len(fechas) and dias >= VERSION_INICIAL.dias_web_nueva:
        return None
    return dias


def _pertenece(dominio: str, bases: Iterable[str]) -> bool:
    return any(dominio == base or dominio.endswith("." + base) for base in bases)


def _candidatos(dominio: str) -> tuple[str, ...]:
    """Nombres que se consultan, del más largo al más corto.

    Un registro de dominios genéricos (.com, .xyz) vende el segundo nivel. Uno de país
    puede vender el segundo (ejemplo.fr) o el tercero (ejemplo.com.ar): se prueba el
    tercero y, si no existe, el segundo, salvo que sea un sufijo como com.ar.
    """
    etiquetas = dominio.split(".")
    # Una IP no tiene registro de dominio.
    if len(etiquetas) < 2 or not all(etiquetas) or etiquetas[-1].isdigit():
        return ()
    segundo = ".".join(etiquetas[-2:])
    if len(etiquetas[-1]) > 2:
        return (segundo,)
    candidatos = [".".join(etiquetas[-3:])] if len(etiquetas) > 2 else []
    if etiquetas[-2] not in SEGUNDOS_NIVELES:
        candidatos.append(segundo)
    return tuple(candidatos)


def _fecha_de_registro(candidatos: tuple[str, ...], limite: float) -> datetime | None:
    if not candidatos:
        return None
    base = _servidor_rdap(candidatos[0].rsplit(".", 1)[-1], limite)
    if base is None:
        return None
    for candidato in candidatos:
        respuesta = _pedir(f"{base}domain/{candidato}", limite)
        if respuesta is None:
            return None
        # 404: el registro no tiene ese nombre, como www.ejemplo.fr. Se prueba el siguiente.
        if respuesta.codigo_http == 404:
            continue
        if respuesta.codigo_http != 200:
            return None
        return _leer_fecha(respuesta.cuerpo, candidato)
    return None


def _leer_fecha(cuerpo: bytes, candidato: str) -> datetime | None:
    """Fecha del evento «registration» de una respuesta RDAP de dominio (RFC 9083)."""
    try:
        datos = json.loads(cuerpo)
        if datos["objectClassName"] != "domain":
            return None
        # Otro nombre en la respuesta no es la fecha del dominio que se pidió.
        if datos["ldhName"].lower().rstrip(".") != candidato:
            return None
        fechas = [
            evento["eventDate"]
            for evento in datos["events"]
            if evento.get("eventAction") == "registration"
        ]
        if not fechas:
            return None
        fecha = datetime.fromisoformat(fechas[0])
    except ERRORES_DE_LECTURA:
        return None
    if fecha.tzinfo is None:
        fecha = fecha.replace(tzinfo=UTC)
    return None if fecha > datetime.now(UTC) else fecha


def _servidor_rdap(tld: str, limite: float) -> str | None:
    if time.monotonic() >= _registro.renovar:
        bases = _pedir_registro_iana(limite)
        if bases:
            _registro.bases = bases
            _registro.renovar = time.monotonic() + VIGENCIA_REGISTRO_SEGUNDOS
        else:
            # Se sigue con el registro anterior, si había uno.
            _registro.renovar = time.monotonic() + ESPERA_TRAS_FALLO_SEGUNDOS
    return _registro.bases.get(tld)


def _pedir_registro_iana(limite: float) -> dict[str, str]:
    """{tld: URL base} con los servidores HTTPS del registro de IANA. Vacío si falla."""
    respuesta = _pedir(URL_REGISTRO_IANA, limite)
    if respuesta is None or respuesta.codigo_http != 200:
        return {}
    bases = {}
    try:
        for tlds, urls in json.loads(respuesta.cuerpo)["services"]:
            https = [url for url in urls if url.startswith("https://")]
            if not https:
                continue
            base = https[0] if https[0].endswith("/") else https[0] + "/"
            bases.update({tld.lower(): base for tld in tlds})
    except ERRORES_DE_LECTURA:
        return {}
    return bases


def _pedir(url: str, limite: float):
    """Pide `url` con el tiempo que le queda al análisis. None si no hubo respuesta."""
    restante = min(limite - time.monotonic(), PLAZO_TOTAL_SEGUNDOS)
    if restante <= 0:
        return None
    respuesta = pedir_url(url, plazo_segundos=restante)
    return respuesta if respuesta.resultado == RESULTADO_OK else None
