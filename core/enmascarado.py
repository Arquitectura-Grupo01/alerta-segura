"""Enmascarado irreversible de datos personales para guardar y loguear.

Se aplica solo al guardar o al escribir un log, nunca antes de analizar: enmascarar
antes rompería las URLs que el motor necesita. El texto que sale de aquí no puede
volver a su forma original.

Las expresiones corren sobre texto hostil, así que ninguna anida cuantificadores:
cada repetición está acotada o consume un carácter de una clase sin ambigüedad.
Además el texto se corta a MAX_CARACTERES antes de aplicarlas.
"""
import logging
import re
import unicodedata

MAX_CARACTERES = 20_000

# Ancho cero y guion blando: sirven para partir un número y esquivar el patrón.
INVISIBLES = re.compile("[\u200b\u200c\u200d\u2060\ufeff\u00ad]")

# El orden importa: lo más largo primero. Si el DNI (8 dígitos) fuera primero,
# cortaría una tarjeta en pedazos. (?<!\d) y (?!\d) impiden empezar o terminar a
# mitad de un número. [ -]? es un solo separador opcional entre dígitos.
# Tarjeta y CCI tienen largo fijo, así que tampoco pueden empezar justo después de
# "dígito + separador" ni terminar justo antes de "separador + dígito": un CCI de 20
# dígitos agrupados con guiones no debe salir como una tarjeta con un resto. Lo que
# no calce aquí lo recoge [CUENTA].
PATRONES = (
    ("[TARJETA]", re.compile(r"(?<!\d)(?<!\d[ -])\d(?:[ -]?\d){12,18}(?![ -]?\d)")),
    ("[CCI]", re.compile(r"(?<!\d)(?<!\d[ -])\d(?:[ -]?\d){19}(?![ -]?\d)")),
    ("[TELEFONO]", re.compile(r"(?<!\d)(?:\+?51[ -]?)?9(?:[ -]?\d){8}(?!\d)")),
    ("[CUENTA]", re.compile(r"(?<!\d)\d(?:[ -]?\d){9,}")),
    ("[DNI]", re.compile(r"(?<!\d)\d{8}(?:-\d)?(?!\d)")),
    (
        "[CORREO]",
        re.compile(r"[A-Za-z0-9._+-]{1,64}@[A-Za-z0-9-]{1,63}(?:\.[A-Za-z0-9-]{1,63}){1,5}"),
    ),
    # (?<![\d.,]) hace que cada número se examine una sola vez, desde su inicio.
    ("[MONTO]", re.compile(r"(?:US\$|S/\.?|\$)\s?\d[\d.,]*", re.IGNORECASE)),
    (
        "[MONTO]",
        re.compile(r"(?<![\d.,])\d[\d.,]*\s?(?:soles|dólares|dolares|usd)\b", re.IGNORECASE),
    ),
)


def normalizar(texto: str) -> str:
    """NFKC y sin caracteres invisibles: la forma sobre la que se buscan los patrones."""
    return INVISIBLES.sub("", unicodedata.normalize("NFKC", texto[:MAX_CARACTERES]))


def enmascarar(texto: str) -> str:
    """Reemplaza DNI, cuentas, CCI, tarjetas, correos, teléfonos y montos por marcadores."""
    if not isinstance(texto, str):
        raise TypeError("enmascarar recibe un texto")
    truncado = len(texto) > MAX_CARACTERES
    texto = normalizar(texto)
    for marcador, patron in PATRONES:
        texto = patron.sub(marcador, texto)
    return texto + " [TRUNCADO]" if truncado else texto


class FiltroEnmascarado(logging.Filter):
    """Enmascara el mensaje, sus argumentos y la traza antes de que el handler escriba."""

    def filter(self, record):
        record.msg = enmascarar(record.getMessage())
        record.args = None
        if record.exc_info:
            record.exc_text = enmascarar(logging.Formatter().formatException(record.exc_info))
            record.exc_info = None
        elif record.exc_text:
            record.exc_text = enmascarar(record.exc_text)
        if record.stack_info:
            record.stack_info = enmascarar(record.stack_info)
        return True
