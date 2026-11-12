"""Claves de API de las fuentes externas: nunca llegan a un log.

Algunas APIs llevan la clave en la URL (`?key=`), y una URL puede terminar en un
mensaje de error o en una traza. Cada fuente registra su clave al crearse y el filtro
la cambia por `[CLAVE]` en todo lo que se escribe.
"""

import logging
from urllib.parse import quote

MARCADOR = "[CLAVE]"

_claves: set[str] = set()


def registrar_clave(clave: str) -> None:
    """Anota una clave para ocultarla, también en su forma codificada para una URL."""
    if clave:
        _claves.update({clave, quote(clave, safe="")})


def ocultar_claves(texto: str) -> str:
    # Las más largas primero: una clave puede contener a otra.
    for clave in sorted(_claves, key=len, reverse=True):
        texto = texto.replace(clave, MARCADOR)
    return texto


class FiltroClaves(logging.Filter):
    """Oculta las claves registradas en el mensaje, sus argumentos y la traza."""

    def filter(self, record):
        record.msg = ocultar_claves(record.getMessage())
        record.args = None
        if record.exc_info:
            traza = logging.Formatter().formatException(record.exc_info)
            record.exc_text = ocultar_claves(traza)
            record.exc_info = None
        elif record.exc_text:
            record.exc_text = ocultar_claves(record.exc_text)
        if record.stack_info:
            record.stack_info = ocultar_claves(record.stack_info)
        return True
