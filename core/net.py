"""Primer control de RNF-04: decidir si una IP es un destino permitido.

Este módulo NO hace peticiones. Solo valida. La conexión real (RF-01) debe
conectarse a la IP ya validada y fijar el header Host, para que no exista una
segunda resolución DNS entre la validación y la conexión (DNS rebinding).
"""
import ipaddress
import socket


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
