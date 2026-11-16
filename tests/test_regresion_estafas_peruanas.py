
"""Tarea 55: regresión del motor ante estafas frecuentes en Perú.

Escenarios ficticios, señales simuladas y ninguna llamada de red.
"""

from dataclasses import dataclass

import pytest

from analisis.heuristicas import detectar_senales
from analisis.normalizacion import normalizar
from motor.riesgo import Nivel, Senales, calcular


@dataclass(frozen=True)
class Caso:
    nombre: str
    modalidad: str
    senales: Senales
    esperado: Nivel
    fraude: bool


CASOS = (
    # Estafas frecuentes en el Perú
    Caso(
        "yape_pago_falso", "Yape",
        Senales(
            marca=100, edad_dias=2,
            fuentes=100, fuentes_con_deteccion=2,
        ),
        Nivel.PELIGRO_ALTO, True,
    ),
    Caso(
        "plin_suplantacion", "Plin",
        Senales(
            marca=100, edad_dias=4,
            fuentes=100, fuentes_con_deteccion=1,
        ),
        Nivel.PELIGRO_ALTO, True,
    ),
    Caso(
        "banco_credenciales", "Banca",
        Senales(
            credenciales_con_urgencia=True,
            heuristicas=("palabras_sospechosas",),
        ),
        Nivel.PELIGROSO, True,
    ),
    Caso(
        "sunat_devolucion_falsa", "SUNAT",
        Senales(marca=100, edad_dias=3),
        Nivel.PELIGROSO, True,
    ),
    Caso(
        "reniec_tramite_falso", "RENIEC",
        Senales(fuentes=100, fuentes_con_deteccion=1),
        Nivel.PELIGROSO, True,
    ),
    Caso(
        "bono_estado_falso", "Bonos",
        Senales(marca=100, edad_dias=1),
        Nivel.PELIGROSO, True,
    ),
    Caso(
        "afp_retiro_falso", "AFP",
        Senales(fuentes=100, fuentes_con_deteccion=2),
        Nivel.PELIGRO_ALTO, True,
    ),
    Caso(
        "courier_entrega_falsa", "Courier",
        Senales(
            credenciales_con_urgencia=True,
            edad_dias=5,
        ),
        Nivel.PELIGROSO, True,
    ),
    # Evasiones representadas mediante señales del analizador
    Caso(
        "unicode_confundible", "Unicode",
        Senales(
            heuristicas=("alfabetos_mezclados",),
            marca=100, edad_dias=3,
        ),
        Nivel.PELIGROSO, True,
    ),
    Caso(
        "dominio_punycode", "Punycode",
        Senales(
            heuristicas=("punycode",),
            fuentes=100, fuentes_con_deteccion=1,
        ),
        Nivel.PELIGROSO, True,
    ),
    Caso(
        "cadena_acortadores", "Acortadores",
        Senales(
            heuristicas=("acortador",),
            fuentes=100, fuentes_con_deteccion=1,
        ),
        Nivel.PELIGROSO, True,
    ),
    Caso(
        "usuario_en_url", "URL con @",
        Senales(
            heuristicas=("usuario_en_url",),
            marca=100, edad_dias=2,
        ),
        Nivel.PELIGROSO, True,
    ),
    # Casos legítimos: evidencia completa y limpia
    Caso(
        "banco_legitimo", "Banca",
        Senales(edad_dias=2000, marca=0, fuentes=0),
        Nivel.SEGURO, False,
    ),
    Caso(
        "sunat_legitimo", "SUNAT",
        Senales(edad_dias=1500, marca=0, fuentes=0),
        Nivel.SEGURO, False,
    ),
    Caso(
        "reniec_legitimo", "RENIEC",
        Senales(edad_dias=1800, marca=0, fuentes=0),
        Nivel.SEGURO, False,
    ),
    Caso(
        "comercio_legitimo", "Comercio",
        Senales(edad_dias=900, marca=0, fuentes=0),
        Nivel.SEGURO, False,
    ),
)


@pytest.mark.parametrize("caso", CASOS, ids=lambda caso: caso.nombre)
def test_regresion_de_niveles(caso):
    veredicto = calcular(caso.senales)

    assert veredicto.nivel >= caso.esperado if caso.fraude else (
        veredicto.nivel == caso.esperado
    )


def test_reporte_de_falsos_negativos(capsys):
    fraudulentos = [caso for caso in CASOS if caso.fraude]

    falsos_negativos = [
        caso.nombre
        for caso in fraudulentos
        if calcular(caso.senales).nivel == Nivel.SEGURO
    ]

    tasa = 100 * len(falsos_negativos) / len(fraudulentos)

    print("\nREPORTE DE REGRESION - ESTAFAS PERUANAS")
    print(f"Version de reglas: {calcular(Senales()).version}")
    print(f"Casos totales: {len(CASOS)}")
    print(f"Escenarios fraudulentos: {len(fraudulentos)}")
    print(f"Falsos negativos: {len(falsos_negativos)}")
    print(f"Tasa de falsos negativos: {tasa:.2f}%")
    print(f"Casos no detectados: {falsos_negativos}")

    assert tasa == 0, (
        f"Se detectaron falsos negativos: {falsos_negativos}"
    )



# Pruebas con URLs ficticias, sin conexiones externas.


@pytest.mark.parametrize(
    ("url", "oficiales", "senal_esperada"),
    [
        (
            "https://bcp.com.pe@sitio-falso.example/login",
            ("bcp.com.pe",),
            "usuario_en_url",
        ),
        (
            "https://bcp.com.pe.sitio-falso.example/login",
            ("bcp.com.pe",),
            "marca_en_subdominio",
        ),
        (
            "https://interban1.com.pe/verifica",
            ("interbank.com.pe",),
            "dominio_parecido",
        ),
        (
            "https://bit.ly/ejemplo",
            (),
            "acortador",
        ),
        (
            "https://xn--bcher-kva.example/",
            (),
            "punycode",
        ),
        (
            "https://p\u0430ypal.example/",
            (),
            "alfabetos_mezclados",
        ),
        (
            "https://ejemplo.com/desbloquear",
            (),
            "palabras_sospechosas",
        ),
    ],
)
def test_detecta_evasiones_en_url(url, oficiales, senal_esperada):
    senales = detectar_senales(url, oficiales)
    assert senal_esperada in senales


def test_arroba_analiza_el_dominio_de_destino():
    enlace = normalizar("https://bcp.com.pe@sitio-falso.example/login")

    assert enlace.dominio == "sitio-falso.example"
    assert "usuario_en_url" in detectar_senales(enlace)


@pytest.mark.parametrize(
    "url",
    [
        "https://www.bcp.com.pe/",
        "https://www.sunat.gob.pe/",
        "https://www.reniec.gob.pe/",
    ],
)
def test_dominios_legitimos_no_son_suplantacion(url):
    dominio = normalizar(url).dominio
    oficiales = (
        "bcp.com.pe",
        "sunat.gob.pe",
        "reniec.gob.pe",
    )

    senales = detectar_senales(url, oficiales)

    assert dominio in oficiales or any(
        dominio.endswith("." + oficial) for oficial in oficiales
    )
    assert "dominio_parecido" not in senales
    assert "marca_en_subdominio" not in senales




# Casos adicionales de evasión y limitaciones conocidas.


@pytest.mark.parametrize(
    ("url", "senal_esperada"),
    [
        (
            "https://ejemplo.com/verifica",
            "palabras_sospechosas",
        ),
        (
            "https://ejemplo.com/v-e-r-i-f-i-c-a",
            None,
        ),
        (
            "https://ejemplo.com/ver\u200bifica",
            None,
        ),
    ],
)
def test_evasion_por_separacion_y_ancho_cero(url, senal_esperada):
    """Registra qué detecta actualmente el analizador.

    None significa que la señal no se detecta en esta versión;
    no equivale a considerar seguro el enlace.
    """
    senales = detectar_senales(url)

    if senal_esperada is None:
        assert "palabras_sospechosas" not in senales
    else:
        assert senal_esperada in senales


def test_acortador_detectado_sin_seguir_redirecciones():
    """Comprueba la señal local; no simula una redirección real."""
    senales = detectar_senales("https://bit.ly/ejemplo")

    assert "acortador" in senales


def test_cobertura_baja_no_se_clasifica_como_seguro():
    """Sin evidencia suficiente, el motor debe advertir al usuario."""
    veredicto = calcular(Senales(heuristicas=()))

    assert veredicto.nivel >= Nivel.TEN_CUIDADO
    assert "cobertura_baja" in veredicto.reglas


