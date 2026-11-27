"""Geometría de los gráficos SVG del panel, calculada en el servidor.

La plantilla solo dibuja rectángulos y textos con atributos de presentación y clases de
static/css/consola.css: la CSP prohíbe estilos en línea y el panel no usa librerías de
gráficos ni CDN. Cada gráfico va acompañado de una tabla con los mismos números.
"""
import math

ALTO_BARRAS = 180
MARGEN_IZQUIERDO = 36
MARGEN_INFERIOR = 22
ANCHO_DIA = 18
SEPARACION = 4
MAX_ETIQUETAS = 10
ALTO_FILA = 26
ANCHO_HORIZONTAL = 600
ANCHO_ETIQUETA = 220


def _techo(maximo: int) -> int:
    """Un tope redondo para el eje: 10, 20, 50, 100, 200..."""
    if maximo <= 0:
        return 1
    base = 10 ** max(0, math.floor(math.log10(maximo)))
    for paso in (1, 2, 5, 10):
        if paso * base >= maximo:
            return paso * base
    return 10 * base


def barras_por_dia(dias: list[dict]) -> dict:
    """Barras apiladas por nivel, una por día. `dias` sale de estadisticas.por_dia."""
    tope = _techo(max((dia["total"] for dia in dias), default=0))
    alto_util = ALTO_BARRAS - MARGEN_INFERIOR
    paso_etiqueta = max(1, math.ceil(len(dias) / MAX_ETIQUETAS))
    barras = []
    for posicion, dia in enumerate(dias):
        x = MARGEN_IZQUIERDO + posicion * (ANCHO_DIA + SEPARACION)
        base = alto_util
        tramos = []
        for nivel, cantidad in enumerate(dia["niveles"]):
            if not cantidad:
                continue
            alto = cantidad * alto_util / tope
            base -= alto
            tramos.append({"y": round(base, 2), "alto": round(alto, 2), "nivel": nivel,
                           "cantidad": cantidad})
        barras.append({
            "x": x,
            "dia": dia["dia"],
            "total": dia["total"],
            "tramos": tramos,
            "etiqueta": posicion % paso_etiqueta == 0,
        })
    ancho = MARGEN_IZQUIERDO + len(dias) * (ANCHO_DIA + SEPARACION)
    return {
        "ancho": max(ancho, 200),
        "alto": ALTO_BARRAS,
        "ancho_barra": ANCHO_DIA,
        "base": alto_util,
        "tope": tope,
        "mitad": tope // 2 if tope > 1 else None,
        "y_mitad": round(alto_util / 2, 2),
        "barras": barras,
        "x_eje": MARGEN_IZQUIERDO - 4,
        "y_texto": ALTO_BARRAS - 6,
    }


def barras_horizontales(filas: list[dict], etiqueta: str, *, clase=None) -> dict:
    """Una barra por fila, proporcional a `cantidad`. `clase(fila)` elige el color."""
    maximo = max((fila["cantidad"] for fila in filas), default=0) or 1
    ancho_util = ANCHO_HORIZONTAL - ANCHO_ETIQUETA - 48
    salida = []
    for posicion, fila in enumerate(filas):
        salida.append({
            "y": posicion * ALTO_FILA,
            "texto": str(fila[etiqueta]),
            "cantidad": fila["cantidad"],
            "ancho": round(max(2, fila["cantidad"] * ancho_util / maximo), 2) if fila["cantidad"]
            else 0,
            "clase": clase(fila) if clase else "barra-total",
        })
    return {
        "ancho": ANCHO_HORIZONTAL,
        "alto": max(ALTO_FILA, len(filas) * ALTO_FILA),
        "x_barra": ANCHO_ETIQUETA,
        "ancho_util": ancho_util,
        "filas": salida,
    }
