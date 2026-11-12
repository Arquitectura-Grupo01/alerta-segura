"""Pruebas del motor de explicación."""

import itertools

import pytest

from analisis.heuristicas import HEURISTICAS
from motor.explicacion import (
    ACCIONES,
    ACLARACION_SEGURO,
    DETALLE_SENAL,
    MAXIMO_MOTIVOS,
    MINIMO_MOTIVOS,
    MOTIVOS_REGLA,
    MOTIVOS_SENAL,
    NOTA_REDIRECCIONES,
    SIN_DESTINO,
    Recorrido,
    explicar,
    terminos_prohibidos,
)
from motor.riesgo import NIVEL_DE_REGLA, Nivel, Senales, calcular


def _textos_para_la_persona():
    yield from MOTIVOS_REGLA.values()
    yield from MOTIVOS_SENAL.values()
    for acciones in ACCIONES.values():
        yield from acciones
    yield ACLARACION_SEGURO
    yield NOTA_REDIRECCIONES
    yield SIN_DESTINO


def _combinaciones_de_senales():
    """Recorre combinaciones de evidencia para probar propiedades de toda explicación."""
    heuristicas = [(), ("acortador",), ("usuario_en_url", "palabras_sospechosas"),
                   ("ip_como_dominio", "punycode", "muchos_subdominios", "barra_invertida",
                    "punto_final", "dominio_parecido")]
    for codigos, edad, marca, fuentes, detecciones, analista, urgencia in itertools.product(
        heuristicas, [None, 2, 20, 200, 900], [None, 0, 100], [None, 0, 50, 100],
        [0, 1, 2], [False, True], [False, True],
    ):
        yield Senales(
            heuristicas=codigos,
            edad_dias=edad,
            marca=marca,
            fuentes=fuentes,
            fuentes_con_deteccion=detecciones if fuentes == 100 else 0,
            confirmado_por_analista=analista,
            credenciales_con_urgencia=urgencia,
        )


def test_cada_senal_tiene_motivo_y_detalle():
    assert set(HEURISTICAS) <= set(MOTIVOS_SENAL)
    assert set(HEURISTICAS) <= set(DETALLE_SENAL)


def test_cada_regla_tiene_motivo():
    assert set(NIVEL_DE_REGLA) <= set(MOTIVOS_REGLA)


def test_cada_nivel_tiene_al_menos_una_accion():
    for nivel in Nivel:
        assert len(ACCIONES[nivel]) >= 1


def test_ningun_texto_usa_terminos_prohibidos():
    for texto in _textos_para_la_persona():
        assert terminos_prohibidos(texto) == [], texto


def test_ningun_texto_usa_raya_ni_semirraya():
    for texto in _textos_para_la_persona():
        assert "\u2014" not in texto and "\u2013" not in texto, texto


def test_detecta_terminos_prohibidos_sin_importar_mayusculas():
    assert terminos_prohibidos("Es un sitio de Phishing") == ["phishing"]
    assert terminos_prohibidos("Revisa la URL") == ["url"]
    assert terminos_prohibidos("Es 100 % seguro") == ["100 % seguro"]
    assert terminos_prohibidos("Una web curiosa") == []


def test_todo_resultado_tiene_de_3_a_5_motivos_y_una_accion():
    for senales in _combinaciones_de_senales():
        veredicto = calcular(senales)
        explicacion = explicar(veredicto, "ejemplo.com")
        assert MINIMO_MOTIVOS <= len(explicacion.motivos) <= MAXIMO_MOTIVOS, senales
        assert len(set(explicacion.motivos)) == len(explicacion.motivos), senales
        assert explicacion.acciones, senales
        for motivo in explicacion.motivos:
            assert terminos_prohibidos(motivo) == [], motivo


def test_seguro_aclara_que_orienta_y_no_garantiza():
    veredicto = calcular(Senales(heuristicas=(), edad_dias=800, marca=0, fuentes=0))
    explicacion = explicar(veredicto, "ejemplo.com")
    assert veredicto.nivel == Nivel.SEGURO
    assert explicacion.aclaracion == ACLARACION_SEGURO
    assert "no una garantía" in explicacion.aclaracion


@pytest.mark.parametrize(
    "senales",
    [Senales(heuristicas=()), Senales(fuentes=100, fuentes_con_deteccion=2)],
)
def test_otros_niveles_no_llevan_aclaracion(senales):
    assert explicar(calcular(senales), "ejemplo.com").aclaracion is None


def test_si_una_regla_sube_el_nivel_su_motivo_va_primero():
    veredicto = calcular(Senales(heuristicas=()))
    motivos = explicar(veredicto, "ejemplo.com").motivos
    assert motivos[0] == MOTIVOS_REGLA["cobertura_baja"]


def test_si_el_puntaje_decide_las_senales_van_primero():
    veredicto = calcular(Senales(heuristicas=("usuario_en_url",)))
    motivos = explicar(veredicto, "sitio-falso.com").motivos
    assert motivos[0] == MOTIVOS_SENAL["usuario_en_url"].format(dominio="sitio-falso.com")


def test_el_motivo_muestra_el_dominio_real():
    veredicto = calcular(Senales(heuristicas=("usuario_en_url",)))
    motivos = explicar(veredicto, "sitio-falso.com").motivos
    esperado = (
        "El enlace pone un nombre al inicio para confundir, pero en realidad abre "
        "sitio-falso.com."
    )
    assert esperado in motivos


def test_la_edad_se_dice_en_dias_y_una_sola_vez():
    veredicto = calcular(Senales(edad_dias=3, marca=100))
    motivos = explicar(veredicto, "ejemplo.com").motivos
    assert motivos[0] == "Imita a una marca conocida en una web creada hace 3 días."
    assert sum("hace 3 días" in motivo for motivo in motivos) == 1


def test_dice_lo_que_todavia_no_se_pudo_revisar():
    motivos = explicar(calcular(Senales(heuristicas=())), "ejemplo.com").motivos
    assert "Todavía no la buscamos en listas de seguridad." in motivos
    assert "No sabemos cuándo se creó la web." in motivos


def test_detalle_tecnico_explica_cada_termino():
    explicacion = explicar(calcular(Senales(heuristicas=("acortador",))), "bit.ly")
    terminos = [termino for termino, _, _ in explicacion.detalle]
    assert terminos == [
        "Listas de seguridad",
        "Edad de la web",
        "Parecido con una marca",
        "Información disponible",
        "Puntaje",
        "Versión de reglas",
    ]
    assert all(nota for _, _, nota in explicacion.detalle)
    assert explicacion.senales == (DETALLE_SENAL["acortador"],)


@pytest.mark.parametrize(("recorrido", "valor"), [
    (Recorrido(saltos=None), SIN_DESTINO),
    (Recorrido(saltos=0), "Ninguna"),
    (Recorrido(saltos=2), "2"),
    (Recorrido(saltos=1, desde="bit.ly"), "1, desde bit.ly"),
])
def test_el_detalle_dice_cuantas_redirecciones_hubo(recorrido, valor):
    detalle = explicar(calcular(Senales()), "ejemplo.com", recorrido).detalle
    assert detalle[0] == ("Redirecciones", valor, NOTA_REDIRECCIONES)
    assert len(detalle) == len(explicar(calcular(Senales()), "ejemplo.com").detalle) + 1
