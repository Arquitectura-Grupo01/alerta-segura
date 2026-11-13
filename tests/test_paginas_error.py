"""Páginas de error: código de estado, texto en español y nada del detalle interno.

Las pruebas provocan cada error de verdad (ruta inexistente, excepción en una vista,
CSRF inválido, límite de solicitudes) y revisan que la respuesta no filtre rutas,
trazas ni el mensaje de la excepción.
"""

import pytest
from django.core.exceptions import PermissionDenied, SuspiciousOperation
from django.http import HttpResponse
from django.template.loader import render_to_string
from django.test import Client
from django.urls import path

from core.entrada import ANALISIS

SECRETO = "detalle-interno-que-no-debe-verse"


def vista_con_error(request):
    raise RuntimeError(SECRETO)


def vista_prohibida(request):
    raise PermissionDenied(SECRETO)


def vista_mal_formada(request):
    raise SuspiciousOperation(SECRETO)


urlpatterns = [
    # Las páginas de error enlazan al inicio y a la guía con {% url %}.
    path("", lambda request: HttpResponse("inicio"), name="inicio"),
    path("guia/", lambda request: HttpResponse("guia"), name="guia"),
    # Las páginas que enlaza el pie de base.html.
    *(
        path(f"{nombre}/", lambda request: HttpResponse(""), name=nombre)
        for nombre in ("privacidad", "terminos", "como_verificamos", "contacto", "modalidades")
    ),
    path("falla/", vista_con_error),
    path("prohibida/", vista_prohibida),
    path("mal-formada/", vista_mal_formada),
]


@pytest.fixture
def rutas_de_prueba(settings):
    """Cambia las URL del proyecto por las de este archivo: solo existen para provocar errores."""
    settings.ROOT_URLCONF = __name__


def verificar_pagina(respuesta, estado, texto):
    cuerpo = respuesta.content.decode()
    assert respuesta.status_code == estado
    assert texto in cuerpo
    assert 'lang="es"' in cuerpo
    assert 'href="/"' in cuerpo
    assert "Traceback" not in cuerpo
    assert SECRETO not in cuerpo
    assert "RuntimeError" not in cuerpo
    assert ".py" not in cuerpo
    assert "Content-Security-Policy" in respuesta.headers
    return cuerpo


def test_ruta_inexistente_da_404_en_espanol(client):
    cuerpo = verificar_pagina(client.get("/no-existe-esta-ruta/"), 404, "No encontramos esa página")
    # La ruta pedida no se imprime: es texto del visitante.
    assert "no-existe-esta-ruta" not in cuerpo


def test_la_404_no_refleja_el_texto_de_la_ruta(client):
    cuerpo = client.get("/<script>alert(1)</script>/").content.decode()
    assert "<script>alert(1)" not in cuerpo


def test_excepcion_en_una_vista_da_500_sin_detalle(rutas_de_prueba):
    cliente = Client(raise_request_exception=False)
    respuesta = cliente.get("/falla/")
    verificar_pagina(respuesta, 500, "Algo salió mal de nuestro lado")


def test_permiso_denegado_da_403(rutas_de_prueba):
    respuesta = Client(raise_request_exception=False).get("/prohibida/")
    verificar_pagina(respuesta, 403, "No tienes permiso")


def test_solicitud_sospechosa_da_400(rutas_de_prueba):
    respuesta = Client(raise_request_exception=False).get("/mal-formada/")
    verificar_pagina(respuesta, 400, "No pudimos leer tu solicitud")


def test_csrf_invalido_da_403_con_pagina_propia(settings):
    cliente = Client(enforce_csrf_checks=True)
    respuesta = cliente.post("/analizar/", {"enlace": "https://ejemplo.invalid/a"})
    cuerpo = verificar_pagina(respuesta, 403, "La página caducó")
    assert "CSRF" not in cuerpo


def test_limite_de_solicitudes_da_429(client, monkeypatch):
    monkeypatch.setattr("core.entrada.ANALISIS", ANALISIS)
    for _ in range(ANALISIS.maximo):
        client.post("/analizar/", {"enlace": ""})
    respuesta = client.post("/analizar/", {"enlace": ""})
    verificar_pagina(respuesta, 429, "Hiciste muchos análisis seguidos")
    assert respuesta["Retry-After"] == str(ANALISIS.ventana_segundos)


def test_la_500_se_renderiza_sin_contexto_ni_peticion():
    """Django renderiza 500.html sin contexto: no puede depender de la base ni de otras."""
    html = render_to_string("500.html")
    assert "Algo salió mal de nuestro lado" in html
    assert 'href="/"' in html
    assert "Traceback" not in html


@pytest.mark.parametrize("plantilla", ["400", "403", "403_csrf", "404", "429"])
def test_las_paginas_con_diseno_tienen_titulo_enlace_y_sin_variables(plantilla):
    html = render_to_string(
        f"{plantilla}.html",
        {"request_path": SECRETO, "exception": SECRETO},
    )
    assert "<h1" in html and "Volver al inicio" in html
    assert SECRETO not in html
