import pytest
from django.core.cache import cache, caches


@pytest.fixture(autouse=True)
def cache_limpia():
    """La caché de los tests vive en el proceso: sin esto, los contadores del rate limit
    de un test se arrastrarían al siguiente."""
    cache.clear()
    caches["tecnica"].clear()
    caches["resultados"].clear()
    yield
    cache.clear()
    caches["tecnica"].clear()
    caches["resultados"].clear()


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


@pytest.fixture
def ingresar_consola(client):
    """Inicia sesión en la consola con el segundo factor ya verificado.

    force_login solo autentica; la consola exige además un dispositivo TOTP verificado
    en la sesión, como queda tras pasar por el formulario de ingreso.
    """
    from django_otp import DEVICE_ID_SESSION_KEY
    from django_otp.plugins.otp_totp.models import TOTPDevice

    def ingresar(cuenta):
        dispositivo = TOTPDevice.objects.create(user=cuenta, name="Pruebas", confirmed=True)
        client.force_login(cuenta)
        sesion = client.session
        sesion[DEVICE_ID_SESSION_KEY] = dispositivo.persistent_id
        sesion.save()
        return client

    return ingresar
