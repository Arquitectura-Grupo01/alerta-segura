"""Política de salida a internet: decidir si un destino es permitido.

Este módulo NO hace peticiones. Solo valida. La conexión real del analizador de
enlaces debe conectarse a la IP ya validada y fijar el header Host, para que no
exista una segunda resolución DNS entre la validación y la conexión (DNS rebinding).
"""
import ipaddress
import socket
from urllib.parse import urlsplit

# Valores de la política. Son controles de seguridad, no configuración: valen
# igual en todos los ambientes y por eso no se leen de variables de entorno.
ESQUEMAS_PERMITIDOS = frozenset({"http", "https"})
PUERTOS_PERMITIDOS = frozenset({80, 443})
MAX_REDIRECCIONES = 3
TIMEOUT_CONEXION_SEGUNDOS = 2
MAX_BYTES_RESPUESTA = 2 * 1024 * 1024


class DestinoBloqueado(Exception):
    """El destino resuelve a una red que la plataforma nunca debe contactar."""


def ip_es_publica(valor: str) -> bool:
    try:
        ip = ipaddress.ip_address(valor)
    except ValueError:
        return False
    # ::ffff:127.0.0.1 es loopback disfrazado de IPv6: se evalúa la IPv4 real.
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    # is_global excluye privadas, loopback, link-local (incluye 169.254.169.254,
    # metadata de nube), reservadas, CGNAT 100.64/10 y 0.0.0.0/8.
    return ip.is_global and not ip.is_multicast


def resolver_y_validar(host: str, puerto: int = 443) -> list[str]:
    """Resuelve el host y devuelve sus IPs solo si TODAS son públicas.

    Si una sola es privada se rechaza el destino completo: el sistema operativo
    podría elegir cualquiera de ellas al conectar.
    """
    try:
        resultados = socket.getaddrinfo(host, puerto, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise DestinoBloqueado(f"No resuelve: {host}") from exc

    ips = sorted({r[4][0] for r in resultados})
    if not ips:
        raise DestinoBloqueado(f"Sin direcciones: {host}")
    bloqueadas = [ip for ip in ips if not ip_es_publica(ip)]
    if bloqueadas:
        raise DestinoBloqueado(f"{host} resuelve a red no permitida")
    return ips


def validar_url(url: str) -> list[str]:
    """Aplica la política completa a una URL: esquema, puerto y destino.

    Devuelve las IPs validadas del host. Cada redirección debe pasar otra vez
    por aquí antes de seguirla.
    """
    partes = urlsplit(url)
    if partes.scheme not in ESQUEMAS_PERMITIDOS:
        raise DestinoBloqueado(f"Esquema no permitido: {partes.scheme or 'ninguno'}")
    if not partes.hostname:
        raise DestinoBloqueado("La URL no tiene host")
    try:
        puerto = partes.port or (443 if partes.scheme == "https" else 80)
    except ValueError as exc:
        raise DestinoBloqueado("Puerto inválido") from exc
    if puerto not in PUERTOS_PERMITIDOS:
        raise DestinoBloqueado(f"Puerto no permitido: {puerto}")
    return resolver_y_validar(partes.hostname, puerto)
