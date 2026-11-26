"""Tarea 55: regresión del motor ante estafas frecuentes en Perú.

Escenarios ficticios, señales simuladas y ninguna llamada de red. El repo es público:
las URLs van desactivadas (hxxp y [.]) y con marcas ficticias; `activar` las arma
solo al usarlas.
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


# --- Señales de la URL, con URLs desactivadas y marcas ficticias ----------------

OFICIAL = "bancodeprueba.pe"


def activar(url: str) -> str:
    """Arma la URL desactivada que está escrita en el test."""
    return url.replace("hxxp", "http").replace("[.]", ".")


@pytest.mark.parametrize(
    ("url", "oficiales", "senal_esperada"),
    [
        ("hxxps://bancodeprueba[.]pe@falso[.]example/login", (OFICIAL,), "usuario_en_url"),
        ("hxxps://bancodeprueba[.]pe.falso[.]example/login", (OFICIAL,), "marca_en_subdominio"),
        ("hxxps://bancodepruebaa[.]pe/verifica", (OFICIAL,), "dominio_parecido"),
        ("hxxps://bit[.]ly/ejemplo", (), "acortador"),
        ("hxxps://xn--bcher-kva[.]example/", (), "punycode"),
        # «bаncodeprueba» con una «а» cirílica, que se ve igual que la latina.
        ("hxxps://bаncodeprueba[.]example/", (), "alfabetos_mezclados"),
        ("hxxps://ejemplo[.]example/desbloquear", (), "palabras_sospechosas"),
    ],
)
def test_detecta_evasiones_en_url(url, oficiales, senal_esperada):
    assert senal_esperada in detectar_senales(activar(url), oficiales)


def test_arroba_analiza_el_dominio_de_destino():
    enlace = normalizar(activar("hxxps://bancodeprueba[.]pe@falso[.]example/login"))

    assert enlace.dominio == "falso.example"
    assert "usuario_en_url" in detectar_senales(enlace)


@pytest.mark.parametrize(
    "url",
    [
        "hxxps://www.bancodeprueba[.]pe/",
        "hxxps://www.registro-de-prueba[.]gob[.]pe/",
        "hxxps://www.tributos-de-prueba[.]gob[.]pe/",
    ],
)
def test_dominios_legitimos_no_son_suplantacion(url):
    oficiales = (OFICIAL, "registro-de-prueba.gob.pe", "tributos-de-prueba.gob.pe")

    senales = detectar_senales(activar(url), oficiales)

    assert "dominio_parecido" not in senales
    assert "marca_en_subdominio" not in senales


# --- Limitaciones conocidas ------------------------------------------------------

@pytest.mark.xfail(
    strict=True,
    reason="Limitación conocida: el analizador no une letras separadas ni quita "
    "caracteres de ancho cero. Si este test pasa, se arregló: quita el xfail.",
)
@pytest.mark.parametrize(
    "url",
    [
        "hxxps://ejemplo[.]example/v-e-r-i-f-i-c-a",
        "hxxps://ejemplo[.]example/ver​ifica",
    ],
)
def test_evasion_por_letras_separadas_y_ancho_cero(url):
    assert "palabras_sospechosas" in detectar_senales(activar(url))


def test_cobertura_baja_no_se_clasifica_como_seguro():
    """Sin evidencia suficiente, el motor debe advertir al usuario."""
    veredicto = calcular(Senales(heuristicas=()))

    assert veredicto.nivel >= Nivel.TEN_CUIDADO
    assert "cobertura_baja" in veredicto.reglas
