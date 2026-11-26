"""Marca de sondeo: alguien prueba muchas variantes de una misma web para ver qué detecta.

Un estafador puede usar la plataforma antes de lanzar su campaña, pegando una dirección
tras otra de su web. Si un mismo origen consulta UMBRAL_VARIANTES direcciones distintas
de una web en una hora, la web queda marcada como posible sondeo y la cola de curación lo
muestra.

No se guarda ninguna IP ni dirección. El origen es el HMAC de la IP de core/entrada.py y
vive una hora; las direcciones se cuentan por un resumen corto. La marca de la web guarda
solo el resumen del dominio.
"""
import hashlib
import math
import time

from django.core.cache import cache

from .entrada import clave_de_ip, ip_del_cliente

# Controles fijos, no configuración.
VENTANA_SEGUNDOS = 60 * 60
UMBRAL_VARIANTES = 10
VIGENCIA_MARCA = 7 * 24 * 60 * 60


def _resumen(texto: str, largo: int = 32) -> str:
    return hashlib.sha256(texto.encode("utf-8", "surrogatepass")).hexdigest()[:largo]


def _clave_marca(dominio: str) -> str:
    return f"sondeo:web:{_resumen(dominio)}"


def anotar_consulta(request, dominio: str, url: str) -> None:
    """Suma la dirección a las consultadas por este origen y marca la web al llegar al umbral.

    Como en core/entrada.py, no se usa cache.incr y cada escritura lleva el plazo que le
    queda a la ventana.
    """
    if not dominio:
        return
    ahora = time.time()
    clave = f"sondeo:origen:{clave_de_ip(ip_del_cliente(request))}:{_resumen(dominio)}"
    inicio, vistas = cache.get(clave, (ahora, ()))
    if ahora >= inicio + VENTANA_SEGUNDOS:
        inicio, vistas = ahora, ()
    huella = _resumen(url, 12)
    if huella in vistas or len(vistas) >= UMBRAL_VARIANTES:
        return
    vistas = (*vistas, huella)
    cache.set(clave, (inicio, vistas), timeout=math.ceil(inicio + VENTANA_SEGUNDOS - ahora))
    if len(vistas) >= UMBRAL_VARIANTES:
        cache.set(_clave_marca(dominio), True, timeout=VIGENCIA_MARCA)


def posible_sondeo(dominio: str) -> bool:
    return bool(dominio) and cache.get(_clave_marca(dominio), False)
