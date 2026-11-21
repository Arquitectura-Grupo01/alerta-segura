
import re

import pytest
from django.test import Client


@pytest.mark.django_db
def test_server_timing_en_respuesta():
    """Comprueba que Django informa su tiempo de procesamiento."""
    cliente = Client()

    respuesta = cliente.get("/health/")

    assert respuesta.status_code == 200
    assert "Server-Timing" in respuesta.headers

    cabecera = respuesta.headers["Server-Timing"]

    coincidencia = re.fullmatch(
        r"app;dur=(\d+(?:\.\d+)?)",
        cabecera,
    )

    assert coincidencia is not None

    duracion_ms = float(coincidencia.group(1))
    assert duracion_ms >= 0
