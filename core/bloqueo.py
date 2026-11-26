"""Bloqueo de cuentas internas tras intentos fallidos de inicio de sesión.

Cinco fallos seguidos bloquean la cuenta 15 minutos. Mientras dura el bloqueo se rechaza
todo intento, también con la contraseña y el código correctos. Un inicio de sesión
correcto vuelve el contador a cero.

El contador vive en la caché compartida bajo el id de la cuenta, nunca bajo la IP. Solo
se cuentan las cuentas que existen: el mensaje de error es el mismo en todos los casos,
así que quien prueba nombres no ve la diferencia, y una ola de nombres inventados no
llena la caché hasta borrar el contador de una cuenta real.
"""
import time

from django.core.cache import cache

# Controles de seguridad: valen igual en todos los ambientes y no se leen del entorno.
MAX_FALLOS = 5
DURACION_BLOQUEO = 15 * 60
# Cuánto se recuerda una racha de fallos sin bloqueo. Pasado ese plazo sin intentos,
# la racha empieza de nuevo.
VIGENCIA_FALLOS = 24 * 60 * 60


def _ahora() -> float:
    return time.time()


def _clave(usuario_id) -> str:
    return f"consola:bloqueo:{usuario_id}"


def esta_bloqueada(usuario_id) -> bool:
    estado = cache.get(_clave(usuario_id))
    return bool(estado) and estado["hasta"] > _ahora()


def registrar_fallo(usuario_id) -> bool:
    """Suma un fallo a la cuenta. Devuelve True solo si este fallo la bloqueó.

    No se usa cache.incr: en DatabaseCache, la caché de Render, incr guarda de nuevo con
    la vigencia por defecto de 300 s (ver core/entrada.py). Cada escritura lleva su plazo.
    """
    ahora = _ahora()
    estado = cache.get(_clave(usuario_id)) or {"fallos": 0, "hasta": 0}
    if estado["hasta"] > ahora:
        # Ya bloqueada: un intento más no alarga el bloqueo.
        return False
    if estado["hasta"]:
        # El bloqueo anterior venció: la racha empieza de nuevo.
        estado = {"fallos": 0, "hasta": 0}
    estado["fallos"] += 1
    if estado["fallos"] >= MAX_FALLOS:
        estado["hasta"] = ahora + DURACION_BLOQUEO
        cache.set(_clave(usuario_id), estado, timeout=DURACION_BLOQUEO)
        return True
    cache.set(_clave(usuario_id), estado, timeout=VIGENCIA_FALLOS)
    return False


def limpiar(usuario_id) -> None:
    cache.delete(_clave(usuario_id))
