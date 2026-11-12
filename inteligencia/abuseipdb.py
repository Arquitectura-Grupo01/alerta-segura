"""AbuseIPDB: reputación de la IP a la que resuelve el destino.

A AbuseIPDB solo llega la IP, nunca la dirección. Una IP reportada es una sospecha y no
una confirmación: en un hosting compartido conviven webs legítimas y estafas. Una IP sin
reportes no prueba nada, así que nunca da «sin detecciones». Plan gratuito limitado.
"""

import ipaddress
from urllib.parse import urlencode, urlsplit

from core.net import DestinoBloqueado, ip_es_publica, resolver_y_validar
from inteligencia.fuentes import Fuente, Respuesta

URL_CONSULTA = "https://api.abuseipdb.com/api/v2/check"
DIAS_DE_REPORTES = 90
# Provisional: el umbral está pendiente en docs/decisiones.md, con la recomendación de
# empezar alto y ajustarlo con el set de regresión.
UMBRAL_CONFIANZA = 90
VALOR_IP_REPORTADA = 50


class AbuseIPDB(Fuente):
    nombre = "abuseipdb"
    titulo = "AbuseIPDB"
    requiere_clave = True
    cuota_diaria = 1000

    def _consultar(self, url: str) -> Respuesta:
        ip = _ip_del_destino(urlsplit(url).hostname or "")
        if ip is None:
            return self.desconocido()
        _, datos = self.pedir_json(
            f"{URL_CONSULTA}?{urlencode({'ipAddress': ip, 'maxAgeInDays': DIAS_DE_REPORTES})}",
            encabezados={"Key": self.clave, "Accept": "application/json"},
        )
        info = datos["data"]
        if info.get("isWhitelisted") is True:
            return self.desconocido()
        confianza = info["abuseConfidenceScore"]
        if isinstance(confianza, int) and not isinstance(confianza, bool):
            if confianza >= UMBRAL_CONFIANZA:
                return self.deteccion(VALOR_IP_REPORTADA)
        return self.desconocido()


def _ip_del_destino(host: str) -> str | None:
    """La IP pública del destino, IPv4 primero. None si no hay una que consultar."""
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass  # es un nombre: se resuelve abajo
    else:
        return host if ip_es_publica(host) else None
    try:
        ips = resolver_y_validar(host)
    except DestinoBloqueado:
        return None
    return sorted(ips, key=lambda ip: ":" in ip)[0]
