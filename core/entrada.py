"""Capa de entrada: identifica al cliente y limita el uso antes de procesar nada.

No guarda ninguna IP. El contador de cada cliente vive en la caché compartida bajo un
HMAC de su IP (salted_hmac con SECRET_KEY) y expira solo, así que un volcado de la
caché no revela quién usó la plataforma.
"""
import ipaddress
import math
import time
from functools import wraps
from typing import NamedTuple

from django.conf import settings
from django.core.cache import cache
from django.shortcuts import render
from django.utils.crypto import salted_hmac


class Politica(NamedTuple):
    nombre: str
    maximo: int
    ventana_segundos: int


# Controles de seguridad: valen igual en todos los ambientes y no se leen del entorno.
ANALISIS = Politica("analisis", 30, 10 * 60)
REPORTES = Politica("reportes", 10, 60 * 60)
# Tope global de consultas a fuentes externas por hora, sin importar quién las pida: bots
# repartidos en muchas IP no deben agotar las cuotas gratuitas de los proveedores.
# Valor provisional: se ajusta con la cuota real de la primera fuente (tareas 18 y 19).
CONSULTAS_EXTERNAS_POR_HORA = 200
# Archivo de 5 MB más el armado del formulario multipart.
MAX_BYTES_CUERPO = 5 * 1024 * 1024 + 64 * 1024
PREFIJO_IPV6 = 64
SAL_DE_LA_IP = "alerta.entrada.ip"



def ip_del_cliente(request) -> str:
    """IP del cliente, o la de la conexión si no se puede confiar en nada más.

    Render pone un proxy delante y no limpia el X-Forwarded-For que manda el cliente:
    solo agrega. La IP verdadera es la que agregó el primer proxy confiable, contada
    desde la derecha (ENTRADA_PROXIES_CONFIABLES). Tomar la primera entrada deja que el
    cliente escoja su IP; tomar una de más a la derecha junta a todos bajo la IP del proxy.
    """
    remota = request.META.get("REMOTE_ADDR", "")
    proxies = settings.ENTRADA_PROXIES_CONFIABLES
    if proxies <= 0:
        return remota
    entradas = [e.strip() for e in request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")]
    entradas = [e for e in entradas if e]
    if not entradas:
        return remota
    # Con menos entradas de las esperadas se usa la más antigua, que agregó el primer proxy.
    candidata = entradas[max(-proxies, -len(entradas))]
    try:
        ipaddress.ip_address(candidata)
    except ValueError:
        return remota
    return candidata


def clave_de_ip(ip: str) -> str:
    """HMAC de la IP, listo para usar como clave de caché. Nunca devuelve la IP.

    Una conexión IPv6 tiene millones de direcciones: se agrupan por su prefijo /64.
    """
    try:
        direccion = ipaddress.ip_address(ip)
    except ValueError:
        return salted_hmac(SAL_DE_LA_IP, "desconocida", algorithm="sha256").hexdigest()
    if isinstance(direccion, ipaddress.IPv6Address):
        if direccion.ipv4_mapped is not None:
            direccion = direccion.ipv4_mapped
        else:
            direccion = ipaddress.ip_network((direccion, PREFIJO_IPV6), strict=False)
    return salted_hmac(SAL_DE_LA_IP, str(direccion), algorithm="sha256").hexdigest()


def _contar(clave: str, ventana_segundos: int) -> int:
    """Suma 1 al contador de la ventana y devuelve el total. El contador expira solo.

    La ventana empieza con la primera solicitud. No se usa cache.incr: en DatabaseCache,
    la caché de Render, incr guarda de nuevo con la vigencia por defecto de 300 s, y
    tras 5 minutos sin solicitudes el contador volvía a cero. Aquí cada escritura lleva
    la vigencia que le queda a la ventana.
    """
    ahora = time.time()
    inicio, total = cache.get(clave, (ahora, 0))
    if ahora >= inicio + ventana_segundos:
        inicio, total = ahora, 0
    total += 1
    cache.set(clave, (inicio, total), timeout=math.ceil(inicio + ventana_segundos - ahora))
    return total


def limitar(politica: Politica):
    """Decorador de vistas: pasado el máximo de la política, responde HTTP 429.

    Cuenta antes de ejecutar la vista, así que una respuesta servida desde la caché
    de resultados también cuenta, y la solicitud rechazada no llama a ninguna fuente.
    """

    def decorador(vista):
        @wraps(vista)
        def envuelta(request, *args, **kwargs):
            clave = f"entrada:{politica.nombre}:{clave_de_ip(ip_del_cliente(request))}"
            if _contar(clave, politica.ventana_segundos) > politica.maximo:
                respuesta = render(request, "429.html", status=429)
                respuesta["Retry-After"] = str(politica.ventana_segundos)
                respuesta["Cache-Control"] = "no-store"
                return respuesta
            return vista(request, *args, **kwargs)

        return envuelta

    return decorador


def consumir_presupuesto_externo() -> bool:
    """Gasta una consulta del presupuesto global de la hora. False si ya se agotó.

    Quien consulta una fuente externa lo llama antes. Si devuelve False, el análisis
    sigue solo con señales propias y lo dice.
    """
    clave = f"entrada:presupuesto_externo:{int(time.time() // 3600)}"
    return _contar(clave, 3600) <= CONSULTAS_EXTERNAS_POR_HORA
