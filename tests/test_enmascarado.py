import io
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
from django.db import connection

from core.auditoria import registrar_evento
from core.enmascarado import MAX_CARACTERES, FiltroEnmascarado, enmascarar
from core.models import TipoEvento

BASE_DIR = Path(__file__).resolve().parent.parent

# Datos ficticios. 4111 1111 1111 1111 es el número de tarjeta de pruebas que usan
# todas las pasarelas de pago.
DNI = "45678912"
TARJETA = "4111 1111 1111 1111"


@pytest.mark.parametrize("texto,esperado", [
    (f"DNI {DNI}", "DNI [DNI]"),
    ("DNI 45678912-3", "DNI [DNI]"),
    (f"tarjeta {TARJETA}", "tarjeta [TARJETA]"),
    ("tarjeta 4111-1111-1111-1111", "tarjeta [TARJETA]"),
    ("tarjeta 4111111111111111", "tarjeta [TARJETA]"),
    ("CCI 00219300123456789012", "CCI [CCI]"),
    ("CCI 002-193-001234567890-12", "CCI [CCI]"),
    ("tarjeta 4111 1111 1111 1111 5 hijos", "tarjeta [TARJETA] hijos"),
    ("ref 12 4111 1111 1111 1111", "ref [TARJETA]"),
    ("cuenta 1234567890", "cuenta [CUENTA]"),
    ("llama al 987654321", "llama al [TELEFONO]"),
    ("llama al +51 987 654 321", "llama al [TELEFONO]"),
    ("llama al 51987654321", "llama al [TELEFONO]"),
    ("escribe a persona.ficticia@ejemplo.invalid ya", "escribe a [CORREO] ya"),
    ("paga S/ 1,500.50 hoy", "paga [MONTO] hoy"),
    ("paga S/. 200 hoy", "paga [MONTO] hoy"),
    ("paga 300 soles hoy", "paga [MONTO] hoy"),
    ("paga US$ 99 hoy", "paga [MONTO] hoy"),
    ("paga $50 hoy", "paga [MONTO] hoy"),
])
def test_enmascara_cada_tipo_de_dato(texto, esperado):
    assert enmascarar(texto) == esperado


def test_una_tarjeta_no_se_corta_en_pedazos():
    # Si el DNI (8 dígitos) corriera primero, dejaría restos de la tarjeta.
    assert enmascarar(f"pagó con {TARJETA}") == "pagó con [TARJETA]"


def test_el_texto_normal_y_las_urls_no_cambian():
    texto = "Revisa https://ejemplo.invalid/ruta?x=1 antes de las 10:30 del 5 de mayo"
    assert enmascarar(texto) == texto


def test_los_marcadores_no_se_vuelven_a_enmascarar():
    una_vez = enmascarar(f"DNI {DNI} tarjeta {TARJETA}")
    assert enmascarar(una_vez) == una_vez


@pytest.mark.parametrize("texto", [
    "DNI \uff14\uff15\uff16\uff17\uff18\uff19\uff11\uff12",  # dígitos de ancho completo
    "DNI 4567\u200b8912",  # espacio de ancho cero en medio
    "DNI 45\u200d67\u20608912",
    "DNI 4567\u00ad8912",  # guion blando
])
def test_no_se_esquiva_con_unicode(texto):
    salida = enmascarar(texto)
    assert "[DNI]" in salida or "[CUENTA]" in salida
    assert "8912" not in salida


def test_un_texto_demasiado_largo_se_corta_y_se_avisa():
    salida = enmascarar("a" * (MAX_CARACTERES + 500))
    assert salida.endswith(" [TRUNCADO]")
    assert len(salida) == MAX_CARACTERES + len(" [TRUNCADO]")


def test_solo_acepta_texto():
    with pytest.raises(TypeError):
        enmascarar(None)


# --- ReDoS ------------------------------------------------------------------

def _peores_casos():
    n = 10_000
    casos = {
        "digitos": "1" * n,
        "digitos con espacio": "1 " * (n // 2),
        "digitos con guion": "1-" * (n // 2),
        "casi tarjeta": ("1234 " * 3 + "x") * (n // 16),
        "arrobas": "a@" * (n // 2),
        "correo largo": "a" * 60 + "@" + ("b" * 60 + ".") * 70,
        "puntos": "1." * (n // 2),
        "monto sin cierre": "$" + "9" * (n - 1),
        "monto con comas": "9," * (n // 2) + "soles",
        "soles repetido": "1 soles " * (n // 8),
        "telefono": "9" * (n // 2) + " " + "51" * (n // 4),
        "mezcla": ("S/ 12.5 DNI 12345678 a@b.pe 987654321 " * 300),
    }
    return {nombre: texto[:n] for nombre, texto in casos.items()}


@pytest.mark.parametrize("nombre", list(_peores_casos()))
def test_un_texto_de_10000_caracteres_armado_para_el_peor_caso_tarda_menos_de_un_segundo(nombre):
    texto = _peores_casos()[nombre]
    assert len(texto) <= 10_000
    inicio = time.perf_counter()
    enmascarar(texto)
    assert time.perf_counter() - inicio < 1


# --- Guardar y loguear ------------------------------------------------------

def _logger_con_filtro():
    flujo = io.StringIO()
    manejador = logging.StreamHandler(flujo)
    manejador.addFilter(FiltroEnmascarado())
    registro = logging.getLogger("alerta.prueba.enmascarado")
    registro.handlers = [manejador]
    registro.propagate = False
    registro.setLevel(logging.DEBUG)
    return registro, flujo


def test_el_filtro_enmascara_el_mensaje_y_sus_argumentos():
    registro, flujo = _logger_con_filtro()
    registro.warning("DNI %s y tarjeta %s", DNI, TARJETA)
    salida = flujo.getvalue()
    assert DNI not in salida and TARJETA not in salida
    assert "DNI [DNI] y tarjeta [TARJETA]" in salida


def test_el_filtro_enmascara_la_traza_de_una_excepcion():
    registro, flujo = _logger_con_filtro()
    try:
        raise ValueError(f"fallo con la tarjeta {TARJETA}")
    except ValueError:
        registro.exception("no se pudo procesar")
    salida = flujo.getvalue()
    assert TARJETA not in salida
    assert "[TARJETA]" in salida and "Traceback" in salida


def test_el_filtro_enmascara_una_traza_ya_formateada_por_otro_handler():
    registro = logging.LogRecord("x", logging.ERROR, __file__, 1, "fallo", None, None)
    registro.exc_text = f"ValueError: tarjeta {TARJETA}"
    registro.stack_info = f"Stack: DNI {DNI}"
    FiltroEnmascarado().filter(registro)
    assert registro.exc_text == "ValueError: tarjeta [TARJETA]"
    assert registro.stack_info == "Stack: DNI [DNI]"


def _volcado_de_todas_las_tablas():
    texto = []
    with connection.cursor() as cursor:
        for tabla in connection.introspection.table_names(cursor):
            cursor.execute(f"SELECT * FROM {connection.ops.quote_name(tabla)}")  # noqa: S608
            texto.extend(str(fila) for fila in cursor.fetchall())
    return "\n".join(texto)


@pytest.mark.django_db
def test_lo_guardado_y_lo_logueado_no_contiene_el_dni_ni_la_tarjeta():
    texto = f"DNI {DNI} y tarjeta {TARJETA}"
    registro, flujo = _logger_con_filtro()
    registrar_evento(TipoEvento.ALERTA_SEGURIDAD, motivo=texto, detalle={"nota": texto})
    registro.error(texto)
    tablas = _volcado_de_todas_las_tablas()
    assert "[DNI]" in tablas  # el volcado sí trae la fila guardada
    for secreto in (DNI, TARJETA, TARJETA.replace(" ", "")):
        assert secreto not in tablas
        assert secreto not in flujo.getvalue()


def test_los_logs_reales_de_la_configuracion_salen_enmascarados():
    # Arranca Django en un proceso aparte para probar el LOGGING de config/settings/base.py.
    entorno = {k: v for k, v in os.environ.items() if k != "DJANGO_SETTINGS_MODULE"}
    entorno.update({
        "DJANGO_SECRET_KEY": "solo-test-no-es-secreto",
        "DJANGO_SETTINGS_MODULE": "config.settings.test",
        "DATABASE_URL": os.environ.get("DATABASE_URL", "sqlite://:memory:"),
    })
    codigo = (
        "import django, logging; django.setup(); "
        f"logging.getLogger('alerta.prueba').error('DNI {DNI} tarjeta {TARJETA}')"
    )
    resultado = subprocess.run(
        [sys.executable, "-c", codigo],
        cwd=BASE_DIR, env=entorno, capture_output=True, text=True, timeout=60,
    )
    assert resultado.returncode == 0, resultado.stderr
    salida = resultado.stdout + resultado.stderr
    assert "DNI [DNI] tarjeta [TARJETA]" in salida
    assert DNI not in salida and TARJETA not in salida
