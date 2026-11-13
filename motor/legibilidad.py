"""Índice de lecturabilidad de Fernández Huerta para los textos que lee la persona.

    L = 206,84 - 0,60 × P - 1,02 × F

P son las sílabas por cada 100 palabras y F el promedio de palabras por frase. De 70 en
adelante el texto es fácil; `docs/requisitos.md` exige 70 o más.

Circula una versión con F como «frases por cada 100 palabras». Con ella, partir una
frase larga en dos baja el índice, al revés de lo que mide. Gwillim Law lo señaló en
2011 (LINGUIST List 22.2332, «Error in the Fernandez Huerta Readability Formula»): al
fijar la muestra en 100 palabras la fracción quedó invertida respecto de la de Flesch,
de la que se adaptó (1,015 × palabras por frase). Aquí se usa la forma de Flesch.
Original: Fernández Huerta, J. (1959). Medidas sencillas de lecturabilidad. Consigna, 214.

Las sílabas se cuentan con las reglas de diptongo y hiato del español, sin diccionario:
puede errar en palabras raras, y para un índice de un texto completo basta.
"""

import re
import unicodedata

FUERTES = set("aeoáéóíú")
DEBILES = set("iuü")
VOCALES = FUERTES | DEBILES
# Una cifra se lee como una palabra de dos sílabas, por ejemplo «treinta».
SILABAS_DE_CIFRA = 2
INDICE_MINIMO = 70

_PALABRA = re.compile(r"[a-záéíóúüñ]+|\d+", re.IGNORECASE)
_FIN_DE_FRASE = re.compile(r"[.!?…]+|[:;]")


def silabas(palabra: str) -> int:
    """Sílabas de una palabra española. Cuenta núcleos vocálicos."""
    palabra = palabra.lower()
    if palabra.isdigit():
        return SILABAS_DE_CIFRA
    if palabra == "y":
        return 1
    # La «u» de que, qui, gue y gui no suena.
    palabra = re.sub(r"(?<=[qg])u(?=[eiéí])", "", palabra)
    cuenta = 0
    anterior = ""
    for letra in palabra:
        if letra not in VOCALES:
            anterior = letra
            continue
        if anterior not in VOCALES or _hiato(anterior, letra):
            cuenta += 1
        anterior = letra
    return max(cuenta, 1)


def _hiato(primera: str, segunda: str) -> bool:
    """Dos vocales seguidas van en sílabas distintas si las dos son fuertes.

    La «í» y la «ú» con tilde cuentan como fuertes: rompen el diptongo (país, día).
    """
    return primera in FUERTES and segunda in FUERTES


def indice(texto: str) -> float:
    """Índice de Fernández Huerta de un texto. Sin palabras, 100."""
    palabras = _PALABRA.findall(unicodedata.normalize("NFC", texto))
    if not palabras:
        return 100.0
    frases = max(1, len([parte for parte in _FIN_DE_FRASE.split(texto) if _PALABRA.search(parte)]))
    p = 100 * sum(silabas(palabra) for palabra in palabras) / len(palabras)
    f = len(palabras) / frases
    return round(206.84 - 0.60 * p - 1.02 * f, 1)
