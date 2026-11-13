"""Legibilidad de lo que lee la persona (tareas 22 y 33).

El índice de Fernández Huerta se calibró con muestras de unas 100 palabras: un rótulo
suelto, como «Turquía», no se puede medir. Por eso se mide lo que la persona lee de
corrido: el resultado completo de cada combinación de señales y cada sección de la
página de estafas frecuentes.
"""

import pytest
from test_explicacion import _combinaciones_de_senales

from motor.explicacion import explicar, terminos_prohibidos
from motor.legibilidad import INDICE_MINIMO, indice, silabas
from motor.modalidades import MODALIDADES
from motor.riesgo import calcular


@pytest.mark.parametrize(("palabra", "esperado"), [
    ("casa", 2), ("estafa", 3), ("ciudad", 2), ("cuidado", 3), ("guerra", 2), ("quien", 1),
    ("pingüino", 3), ("averigüe", 4), ("país", 2), ("día", 2), ("baúl", 2), ("oír", 2),
    ("aéreo", 4), ("leer", 2), ("caer", 2), ("huevo", 2), ("rey", 1), ("yape", 2),
    ("dirección", 3), ("antivirus", 4), ("y", 1), ("30", 2),
])
def test_cuenta_las_silabas_con_diptongos_e_hiatos(palabra, esperado):
    assert silabas(palabra) == esperado


def test_una_frase_partida_en_dos_es_mas_facil_y_no_mas_dificil():
    """La versión con «frases por cada 100 palabras» daría lo contrario."""
    larga = "Te llaman del banco y te piden un código que llegó a tu celular para ayudarte."
    corta = "Te llaman del banco. Te piden un código que llegó a tu celular para ayudarte."
    assert indice(corta) > indice(larga)


def test_las_palabras_largas_bajan_el_indice():
    assert indice("Usa tu app.") > indice("Utiliza inmediatamente la aplicación correspondiente.")


def test_todo_resultado_se_lee_con_facilidad():
    for senales in _combinaciones_de_senales():
        explicacion = explicar(calcular(senales), "ejemplo.com")
        texto = " ".join([explicacion.titular, *explicacion.motivos, *explicacion.acciones])
        assert indice(texto) >= INDICE_MINIMO, texto


@pytest.mark.parametrize("modalidad", MODALIDADES, ids=lambda m: m.clave)
def test_cada_seccion_de_las_estafas_frecuentes_se_lee_con_facilidad(modalidad):
    texto = " ".join(
        [*modalidad.como_funciona, *modalidad.como_reconocerla, *modalidad.que_hacer,
         modalidad.accion]
    )
    assert indice(texto) >= INDICE_MINIMO, modalidad.clave
    assert terminos_prohibidos(texto) == []
    assert "—" not in texto and "–" not in texto
