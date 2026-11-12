"""Función que usan las demás apps para dejar un evento de auditoría.

    from core.auditoria import registrar_evento
    registrar_evento(TipoEvento.DESTINO_BLOQUEADO, motivo="IP privada", detalle={"puerto": 443})
"""
import ipaddress
import re

from .enmascarado import enmascarar, normalizar
from .models import EventoAuditoria, TipoEvento

MAX_CLAVES_DETALLE = 10
MAX_LARGO_TEXTO = 120
MAX_LARGO_OBJETO = 100
MAX_LARGO_MOTIVO = 200
CLAVE_VALIDA = re.compile(r"[a-z][a-z0-9_]{0,39}")
# Nombres que invitan a guardar justo lo que la auditoría no debe guardar.
CLAVES_PROHIBIDAS = frozenset({
    "ip", "ip_cliente", "direccion_ip", "url", "texto", "contenido", "correo",
    "email", "telefono", "dni", "tarjeta", "cuenta", "captura",
})
IPV4_EN_TEXTO = re.compile(r"(?:\d{1,3}\.){3}\d{1,3}")
# Tramos que podrían ser una IPv6 dentro de un texto ("conecto a 2001:db8::1").
TRAMO_IP = re.compile(r"[0-9A-Fa-f:.]{2,}")
# objeto es un identificador, "app.Modelo:id" o un módulo como "core.net". El id puede
# ser un número o un UUID. No se enmascara: enmascarar partiría un UUID en pedazos.
IDENTIFICADOR = re.compile(r"[a-z][a-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)*(?::[A-Za-z0-9-]{1,64})?")


def _es_ip_o_url(valor: str) -> bool:
    """La IP del ciudadano y las URLs completas no se guardan nunca, ni enmascaradas.

    DNI, tarjetas, cuentas, correos, teléfonos y montos sí se enmascaran: lo hace
    _validar_texto con enmascarar().
    """
    return "://" in valor or _contiene_ip(valor)


def _contiene_ip(valor: str) -> bool:
    """True si el texto trae una IPv4 o una IPv6, sola o en medio de una frase."""
    if IPV4_EN_TEXTO.search(valor):
        return True
    for tramo in TRAMO_IP.findall(valor):
        if ":" not in tramo:
            continue
        try:
            ipaddress.ip_address(tramo.rstrip("."))
        except ValueError:
            continue
        return True
    return False


def _validar_objeto(objeto: str) -> None:
    if len(objeto) > MAX_LARGO_OBJETO:
        raise ValueError(f"objeto supera {MAX_LARGO_OBJETO} caracteres")
    if objeto and not IDENTIFICADOR.fullmatch(objeto):
        raise ValueError("objeto debe ser un identificador como catalogo.Dominio:42")


def _validar_texto(campo: str, valor: str, maximo: int) -> str:
    """Devuelve el texto enmascarado. Los mensajes de error nunca repiten el valor."""
    if len(valor) > maximo:
        raise ValueError(f"{campo} supera {maximo} caracteres")
    # Se busca sobre el texto normalizado: "２０３.０.１１３.７" o una IP con caracteres
    # invisibles en medio también es una IP.
    valor = normalizar(valor)
    if _es_ip_o_url(valor):
        raise ValueError(f"{campo} trae una IP o una URL, que no se guardan")
    return enmascarar(valor)


def _validar_detalle(detalle: dict) -> dict:
    if len(detalle) > MAX_CLAVES_DETALLE:
        raise ValueError(f"detalle admite hasta {MAX_CLAVES_DETALLE} claves")
    limpio = {}
    for clave, valor in detalle.items():
        if not isinstance(clave, str) or not CLAVE_VALIDA.fullmatch(clave):
            raise ValueError("las claves de detalle son minúsculas con guion bajo")
        if clave in CLAVES_PROHIBIDAS:
            raise ValueError(f"detalle no admite la clave {clave!r}")
        # bool antes que int: en Python True es un int.
        if valor is None or isinstance(valor, (bool, int, float)):
            limpio[clave] = valor
        elif isinstance(valor, str):
            limpio[clave] = _validar_texto(f"detalle[{clave!r}]", valor, MAX_LARGO_TEXTO)
        else:
            raise ValueError(f"detalle[{clave!r}] debe ser texto corto, número, booleano o None")
    return limpio


def registrar_evento(tipo, *, usuario=None, objeto="", motivo="", detalle=None):
    """Guarda un evento de auditoría y lo devuelve.

    usuario es la cuenta interna que actuó; un visitante anónimo cuenta como None.
    objeto es solo un identificador ("catalogo.Dominio:42") y se guarda tal cual. motivo
    y detalle pasan por enmascarar() antes de guardarse. Una IP o una URL levanta ValueError y el
    evento no se guarda.
    """
    if tipo not in TipoEvento.values:
        raise ValueError(f"tipo de evento desconocido: {tipo!r}")
    detalle = {} if detalle is None else detalle
    if not isinstance(detalle, dict):
        raise ValueError("detalle debe ser un diccionario")
    _validar_objeto(objeto)
    motivo = _validar_texto("motivo", motivo, MAX_LARGO_MOTIVO)
    detalle = _validar_detalle(detalle)
    if usuario is not None and not getattr(usuario, "is_authenticated", False):
        usuario = None
    return EventoAuditoria.objects.create(
        tipo=tipo, usuario=usuario, objeto=objeto, motivo=motivo, detalle=detalle,
    )
