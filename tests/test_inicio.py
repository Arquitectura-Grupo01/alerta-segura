import re

from django.contrib.staticfiles import finders
from django.urls import reverse

ESTATICOS_DEL_INICIO = (
    "css/sitio.css",
    "js/inicio.js",
    "fonts/geist-latin.woff2",
    "fonts/geist-mono-latin.woff2",
    "img/grano.svg",
)


def _html(client):
    return client.get(reverse("inicio")).content.decode()


def test_inicio_responde_con_el_campo_del_enlace(client):
    res = client.get(reverse("inicio"))
    assert res.status_code == 200
    html = res.content.decode()
    assert '<label class="etiqueta" for="enlace">Pega el enlace que recibiste</label>' in html
    assert 'id="enlace"' in html


def test_inicio_envia_el_formulario_con_token_csrf(client):
    assert 'name="csrfmiddlewaretoken"' in _html(client)


def test_inicio_avisa_que_nunca_se_escriben_contrasenas(client):
    assert "Nunca escribas aquí contraseñas, claves ni códigos." in _html(client)


def test_inicio_muestra_los_cuatro_niveles_con_sus_textos_exactos(client):
    html = _html(client)
    for nivel in ("Seguro", "Ten cuidado", "Peligroso", "Peligro alto"):
        assert f"</svg>{nivel}</h3>" in html


def test_inicio_nunca_promete_seguridad_total(client):
    html = _html(client).lower()
    assert "100 % seguro" not in html
    assert "100% seguro" not in html
    assert "no una garantía" in html


def test_inicio_no_usa_scripts_ni_estilos_en_linea(client):
    # La CSP bloquea todo lo que va en línea; si se cuela algo, la página se rompe en producción.
    html = _html(client)
    assert not re.search(r"<script(?![^>]*\bsrc=)[^>]*>", html, flags=re.IGNORECASE)
    assert not re.search(r"<style", html, flags=re.IGNORECASE)
    assert not re.search(r"\sstyle=", html, flags=re.IGNORECASE)
    assert not re.search(r"\son[a-z]+=", html, flags=re.IGNORECASE)


def test_inicio_no_carga_recursos_de_otros_dominios(client):
    # Nada de CDN, fuentes externas ni scripts de terceros: rompen el anonimato y la CSP.
    assert not re.search(r'(?:src|href)="(?:https?:)?//', _html(client))


def test_inicio_lleva_la_csp(client):
    assert "default-src 'self'" in client.get(reverse("inicio")).headers["Content-Security-Policy"]


def test_estaticos_del_inicio_existen():
    for ruta in ESTATICOS_DEL_INICIO:
        assert finders.find(ruta), ruta
