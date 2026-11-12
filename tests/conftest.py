import pytest
from django.core.cache import cache


@pytest.fixture(autouse=True)
def cache_limpia():
    """La caché de los tests vive en el proceso: sin esto, los contadores del rate limit
    de un test se arrastrarían al siguiente."""
    cache.clear()
    yield
    cache.clear()


@pytest.fixture(autouse=True)
def analisis_sin_red(monkeypatch):
    """Ningún test sale a internet. El análisis de un enlace recibe «error_de_red» salvo que
    el test ponga sus propias respuestas, y el registro de IANA guardado se vacía."""
    from analisis import destino, edad
    from core.net import RESULTADO_ERROR_DE_RED, RespuestaSegura

    def sin_red(url, **opciones):
        return RespuestaSegura(RESULTADO_ERROR_DE_RED)

    monkeypatch.setattr(destino, "pedir_url", sin_red)
    monkeypatch.setattr(edad, "pedir_url", sin_red)
    monkeypatch.setattr(edad, "_registro", edad._RegistroIana())
