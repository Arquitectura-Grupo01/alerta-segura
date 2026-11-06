import pytest
from django.http import HttpResponse
from django.test import RequestFactory

from core.middleware import CabecerasSeguridadMiddleware

CABECERAS_ESPERADAS = {
    "Permissions-Policy": "camera=(self), microphone=(), geolocation=(), payment=(), usb=()",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Embedder-Policy": "require-corp",
    "Cross-Origin-Resource-Policy": "same-origin",
}

# Una página normal, una respuesta JSON y un 404.
RUTAS = ["/", "/health/", "/ruta-que-no-existe/"]


@pytest.mark.parametrize("ruta", RUTAS)
@pytest.mark.parametrize("nombre,valor", CABECERAS_ESPERADAS.items())
def test_toda_respuesta_lleva_las_cabeceras_de_seguridad(client, ruta, nombre, valor):
    assert client.get(ruta).headers.get(nombre) == valor


@pytest.mark.parametrize("ruta", ["/", "/ruta-que-no-existe/"])
def test_pagina_dinamica_sale_con_no_store(client, ruta):
    assert client.get(ruta).headers["Cache-Control"] == "no-store"


def test_conserva_el_cache_control_que_ya_trae_la_respuesta():
    def vista(request):
        respuesta = HttpResponse("ok")
        respuesta.headers["Cache-Control"] = "max-age=60, public"
        return respuesta

    respuesta = CabecerasSeguridadMiddleware(vista)(RequestFactory().get("/x/"))
    assert respuesta.headers["Cache-Control"] == "max-age=60, public"


def test_una_vista_no_puede_debilitar_las_cabeceras():
    def vista(request):
        respuesta = HttpResponse("ok")
        respuesta.headers["Cross-Origin-Resource-Policy"] = "cross-origin"
        respuesta.headers["Permissions-Policy"] = "camera=*"
        return respuesta

    respuesta = CabecerasSeguridadMiddleware(vista)(RequestFactory().get("/x/"))
    assert respuesta.headers["Cross-Origin-Resource-Policy"] == "same-origin"
    assert respuesta.headers["Permissions-Policy"] == CABECERAS_ESPERADAS["Permissions-Policy"]


def test_estaticos_llevan_las_cabeceras_sin_cors_abierto_y_con_su_cache(
    client, settings, tmp_path
):
    # WhiteNoise manda Access-Control-Allow-Origin: * por defecto (regla 10098 de ZAP).
    (tmp_path / "prueba.css").write_text("body { margin: 0; }", encoding="utf-8")
    settings.STATIC_ROOT = tmp_path
    respuesta = client.get("/static/prueba.css")
    assert respuesta.status_code == 200
    assert "Access-Control-Allow-Origin" not in respuesta.headers
    assert respuesta.headers["Cross-Origin-Resource-Policy"] == "same-origin"
    assert respuesta.headers["Cache-Control"] != "no-store"


def test_cookie_de_csrf_es_httponly(client, settings):
    respuesta = client.get("/")
    assert respuesta.cookies[settings.CSRF_COOKIE_NAME]["httponly"]


def test_csrf_httponly_no_cambia_sin_revision(settings):
    assert settings.CSRF_COOKIE_HTTPONLY is True


def test_js_propio_no_lee_cookies(settings):
    # Con la cookie de CSRF HttpOnly, un POST con JS toma el token del formulario.
    archivos = list((settings.BASE_DIR / "static" / "js").glob("*.js"))
    assert archivos
    for archivo in archivos:
        assert "document.cookie" not in archivo.read_text(encoding="utf-8"), archivo.name
