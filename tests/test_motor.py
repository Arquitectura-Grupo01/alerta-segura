"""Pruebas del motor de riesgo."""

from dataclasses import replace

import pytest

from analisis.heuristicas import HEURISTICAS
from motor.riesgo import (
    FUENTES,
    GRUPO_DE_SENAL,
    NIVEL_DE_REGLA,
    SENALES_DE_MARCA,
    VERSION_INICIAL,
    Nivel,
    Senales,
    calcular,
    puntaje_edad,
    puntaje_heuristicas,
    puntaje_marca,
)


def test_cada_heuristica_tiene_puntos_o_es_de_marca():
    sin_puntos = set(HEURISTICAS) - set(GRUPO_DE_SENAL) - SENALES_DE_MARCA
    assert sin_puntos == set()


def test_senal_desconocida_falla():
    with pytest.raises(ValueError):
        puntaje_heuristicas(("senal_inventada",))


def test_tipo_de_entrada_sin_reglas_falla():
    with pytest.raises(ValueError):
        calcular(Senales(tipo_entrada="telefono"))


def test_puntos_de_heuristicas_por_grupo_con_tope():
    assert puntaje_heuristicas(()) == 0
    assert puntaje_heuristicas(("ip_como_dominio",)) == 40
    # Dos señales del mismo grupo suman una sola vez.
    assert puntaje_heuristicas(("ip_como_dominio", "ip_alternativa")) == 40
    assert puntaje_heuristicas(("acortador", "palabras_sospechosas")) == 40
    todas = ("ip_como_dominio", "acortador", "punycode", "muchos_subdominios")
    assert puntaje_heuristicas(todas) == 100


def test_las_senales_de_marca_no_suman_a_las_heuristicas():
    assert puntaje_heuristicas(("dominio_parecido",)) == 0


def test_puntaje_de_marca_sin_catalogo_queda_sin_dato():
    assert puntaje_marca(("dominio_parecido",), catalogo_disponible=False) is None
    assert puntaje_marca(("dominio_parecido",), catalogo_disponible=True) == 100
    assert puntaje_marca((), catalogo_disponible=True) == 0


@pytest.mark.parametrize(
    ("dias", "esperado"),
    [(None, None), (0, 100), (6, 100), (7, 70), (30, 70), (31, 30), (365, 30), (366, 0)],
)
def test_puntaje_de_edad(dias, esperado):
    assert puntaje_edad(dias) == esperado


@pytest.mark.parametrize(
    ("puntaje_fuentes", "nivel"),
    [(0, Nivel.SEGURO), (20, Nivel.SEGURO), (21, Nivel.TEN_CUIDADO), (50, Nivel.TEN_CUIDADO),
     (51, Nivel.PELIGROSO), (80, Nivel.PELIGROSO), (81, Nivel.PELIGRO_ALTO)],
)
def test_umbrales_de_nivel(puntaje_fuentes, nivel):
    # Una versión donde solo cuentan las fuentes deja probar el puntaje exacto.
    version = replace(VERSION_INICIAL, aplicables={"enlace": (FUENTES,)})
    veredicto = calcular(Senales(fuentes=puntaje_fuentes), version)
    assert veredicto.puntaje == puntaje_fuentes
    assert veredicto.nivel == nivel


def test_reproducible_con_las_mismas_senales_y_version():
    senales = Senales(heuristicas=("acortador", "punycode"), edad_dias=12, marca=0)
    assert calcular(senales) == calcular(senales)


def test_el_peso_de_lo_que_falta_se_reparte():
    # Solo heurísticas con 40 puntos: el promedio es 40, no 40 × 15 / 90.
    veredicto = calcular(Senales(heuristicas=("ip_como_dominio",)))
    assert veredicto.puntaje == 40
    assert veredicto.valores[FUENTES] is None


def test_enlace_sin_fuentes_ni_edad_ni_catalogo_tiene_cobertura_baja():
    veredicto = calcular(Senales(heuristicas=()))
    assert veredicto.cobertura == pytest.approx(16.7)
    assert "cobertura_baja" in veredicto.reglas
    assert veredicto.nivel == Nivel.TEN_CUIDADO


def test_dominio_de_3_dias_sin_otras_senales_da_ten_cuidado():
    veredicto = calcular(Senales(edad_dias=3, marca=0))
    assert veredicto.nivel == Nivel.TEN_CUIDADO
    assert "web_nueva" in veredicto.reglas


def test_dominio_de_3_dias_en_una_lista_de_bloqueo_da_peligroso_o_mas():
    veredicto = calcular(Senales(edad_dias=3, marca=0, fuentes=100, fuentes_con_deteccion=1))
    assert veredicto.nivel >= Nivel.PELIGROSO
    assert "una_fuente_confirma" in veredicto.reglas


def test_dominio_antiguo_sin_fuentes_nunca_es_seguro_aunque_aporte_el_modelo():
    veredicto = calcular(Senales(edad_dias=800, marca=0), aporte_modelo=10)
    assert veredicto.cobertura < 70
    assert veredicto.nivel != Nivel.SEGURO


def test_analisis_de_fuente_vencido_no_aporta_puntaje_ni_cobertura():
    # El adaptador entrega None para un análisis de más de 24 h.
    con_vencido = calcular(Senales(edad_dias=800, marca=0, fuentes=None))
    sin_fuente = calcular(Senales(edad_dias=800, marca=0))
    assert con_vencido.puntaje == sin_fuente.puntaje
    assert con_vencido.cobertura == sin_fuente.cobertura


def test_base_95_mas_10_del_modelo_da_100_y_peligro_alto():
    version = replace(VERSION_INICIAL, aplicables={"enlace": (FUENTES,)})
    veredicto = calcular(Senales(fuentes=95), version, aporte_modelo=10)
    assert veredicto.puntaje == 100
    assert veredicto.nivel == Nivel.PELIGRO_ALTO


def test_el_aporte_del_modelo_se_limita_a_10_y_nunca_resta():
    senales = Senales(heuristicas=("acortador",))
    assert calcular(senales, aporte_modelo=50).puntaje == 30
    assert calcular(senales, aporte_modelo=-20).puntaje == 20


def test_el_modelo_no_cuenta_para_la_cobertura():
    senales = Senales(heuristicas=())
    assert calcular(senales, aporte_modelo=10).cobertura == calcular(senales).cobertura


def test_seguro_con_toda_la_evidencia_limpia():
    veredicto = calcular(Senales(heuristicas=(), edad_dias=800, marca=0, fuentes=0))
    assert veredicto.cobertura == 100
    assert veredicto.nivel == Nivel.SEGURO
    assert veredicto.reglas == ()


@pytest.mark.parametrize(
    ("senales", "regla"),
    [
        (Senales(fuentes=100, fuentes_con_deteccion=2), "dos_fuentes_confirman"),
        (Senales(fuentes=100, fuentes_con_deteccion=1, marca=100), "fuente_y_suplantacion"),
        (Senales(confirmado_por_analista=True), "analista_confirma"),
        (Senales(fuentes=100, fuentes_con_deteccion=1), "una_fuente_confirma"),
        (Senales(marca=60, edad_dias=10), "suplantacion_en_web_nueva"),
        (Senales(credenciales_con_urgencia=True), "credenciales_con_urgencia"),
        (Senales(edad_dias=29), "web_nueva"),
        (Senales(), "cobertura_baja"),
    ],
)
def test_cada_piso_fija_su_nivel_minimo(senales, regla):
    veredicto = calcular(senales)
    assert regla in veredicto.reglas
    assert veredicto.nivel >= NIVEL_DE_REGLA[regla]


def test_dominio_de_30_dias_ya_no_activa_web_nueva():
    assert "web_nueva" not in calcular(Senales(edad_dias=30)).reglas


def test_las_reglas_van_de_la_mas_grave_a_la_mas_leve():
    veredicto = calcular(Senales(edad_dias=3, marca=100))
    niveles = [NIVEL_DE_REGLA[regla] for regla in veredicto.reglas]
    assert niveles == sorted(niveles, reverse=True)


def test_el_veredicto_guarda_version_y_senales():
    senales = Senales(heuristicas=("acortador",))
    veredicto = calcular(senales)
    assert veredicto.version == VERSION_INICIAL.numero
    assert veredicto.senales == senales


def test_textos_y_claves_de_los_niveles():
    textos = ["Seguro", "Ten cuidado", "Peligroso", "Peligro alto"]
    assert [nivel.texto for nivel in Nivel] == textos
    assert [nivel.clave for nivel in Nivel] == ["seguro", "cuidado", "peligroso", "alto"]


# --- Evidencia contradictoria de las fuentes ----------------------------------

def test_una_fuente_no_concluyente_da_ten_cuidado_y_nunca_seguro_ni_peligroso():
    limpia = Senales(heuristicas=(), edad_dias=9000, marca=0, fuentes=0)
    assert calcular(limpia).nivel == Nivel.SEGURO
    en_duda = calcular(Senales(heuristicas=(), edad_dias=9000, marca=0, fuentes=0,
                               fuentes_en_duda=True))
    assert en_duda.nivel == Nivel.TEN_CUIDADO
    assert "fuente_no_concluyente" in en_duda.reglas


def test_si_otra_fuente_confirma_la_duda_ya_no_es_la_regla_que_decide():
    veredicto = calcular(Senales(fuentes=100, fuentes_con_deteccion=1, fuentes_en_duda=True))
    assert veredicto.nivel == Nivel.PELIGROSO
    assert "fuente_no_concluyente" not in veredicto.reglas
