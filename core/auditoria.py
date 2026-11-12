"""Función que usan las demás apps para dejar un evento de auditoría.

    from core.auditoria import registrar_evento
    registrar_evento(TipoEvento.DESTINO_BLOQUEADO, motivo="IP privada", detalle={"puerto": 443})
"""
import ipaddress
import re

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
# ser un número o un UUID. Por eso no pasa por la heurística de datos personales.
IDENTIFICADOR = re.compile(r"[a-z][a-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)*(?::[A-Za-z0-9-]{1,64})?")
DIGITOS_LARGOS = re.compile(r"\d{8,}")  # DNI, teléfono, tarjeta, cuenta
SEPARADORES = re.compile(r"[ -]")


def _parece_dato_personal(valor: str) -> bool:
    """Heurística que falla cerrado: ante la duda, el valor se rechaza.

    Hasta que exista enmascarar() (tarea 10), esta es la defensa contra una IP,
    una URL, un correo o un documento colados en un evento. Con enmascarar() el
    texto se enmascara aquí en vez de rechazarse.
    """
    if "://" in valor or "@" in valor:
        return True
    # Sin espacios ni guiones, para que "4111 1111 1111 1111" cuente como 16 dígitos.
    if DIGITOS_LARGOS.search(SEPARADORES.sub("", valor)):
        return True
    return _contiene_ip(valor)


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


def _validar_texto(campo: str, valor: str, maximo: int) -> None:
    # Los mensajes nombran el campo y nunca repiten el valor: no filtrarlo al log.
    if len(valor) > maximo:
        raise ValueError(f"{campo} supera {maximo} caracteres")
    if _parece_dato_personal(valor):
        raise ValueError(f"{campo} parece traer un dato personal")


def _validar_detalle(detalle: dict) -> None:
    if len(detalle) > MAX_CLAVES_DETALLE:
        raise ValueError(f"detalle admite hasta {MAX_CLAVES_DETALLE} claves")
    for clave, valor in detalle.items():
        if not isinstance(clave, str) or not CLAVE_VALIDA.fullmatch(clave):
            raise ValueError("las claves de detalle son minúsculas con guion bajo")
        if clave in CLAVES_PROHIBIDAS:
            raise ValueError(f"detalle no admite la clave {clave!r}")
        # bool antes que int: en Python True es un int.
        if valor is None or isinstance(valor, (bool, int, float)):
            continue
        if isinstance(valor, str):
            _validar_texto(f"detalle[{clave!r}]", valor, MAX_LARGO_TEXTO)
            continue
        raise ValueError(f"detalle[{clave!r}] debe ser texto corto, número, booleano o None")


def registrar_evento(tipo, *, usuario=None, objeto="", motivo="", detalle=None):
    """Guarda un evento de auditoría y lo devuelve.

    usuario es la cuenta interna que actuó; un visitante anónimo cuenta como None.
    objeto es solo un identificador ("catalogo.Dominio:42"). Un valor que parezca
    una IP, una URL, un correo o un documento levanta ValueError y no se guarda.
    """
    if tipo not in TipoEvento.values:
        raise ValueError(f"tipo de evento desconocido: {tipo!r}")
    detalle = {} if detalle is None else detalle
    if not isinstance(detalle, dict):
        raise ValueError("detalle debe ser un diccionario")
    _validar_objeto(objeto)
    _validar_texto("motivo", motivo, MAX_LARGO_MOTIVO)
    _validar_detalle(detalle)
    if usuario is not None and not getattr(usuario, "is_authenticated", False):
        usuario = None
    return EventoAuditoria.objects.create(
        tipo=tipo, usuario=usuario, objeto=objeto, motivo=motivo, detalle=detalle,
    )
