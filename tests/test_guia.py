"""Guía «Ya hice clic, di mis datos o pagué»: página fija, sin formularios y enlazada."""

import re
from urllib.parse import urlsplit

import pytest
from django.urls import reverse

from motor.explicacion import terminos_prohibidos

SITUACIONES = ("hice-clic", "di-mis-datos", "pague", "instale-una-app", "codigo-whatsapp")
# Sitios oficiales verificados; la fecha está en el comentario de la plantilla.
SITIOS_OFICIALES = {
    "www.gob.pe",
    "enlinea.indecopi.gob.pe",
    "www.yape.com.pe",
    "faq.whatsapp.com",
    "support.google.com",
}


@pytest.fixture
def html(client):
    respuesta = client.get(reverse("guia"))
    assert respuesta.status_code == 200
    return respuesta.content.decode()


def _visible(html):
    """La página sin los comentarios de plantilla ni las etiquetas."""
    return re.sub(r"<[^>]+>", " ", html)


def test_la_guia_existe_en_su_direccion(client):
    assert reverse("guia") == "/guia/"
    assert client.get("/guia/").status_code == 200


def test_la_guia_no_pide_ningun_dato(html):
    for etiqueta in ("form", "input", "textarea", "select"):
        assert not re.search(rf"<{etiqueta}\b", html, flags=re.IGNORECASE)
    assert "csrfmiddlewaretoken" not in html


def test_la_guia_no_recibe_datos(client):
    assert client.post(reverse("guia"), {"dato": "x"}).status_code == 405


@pytest.mark.parametrize("situacion", SITUACIONES)
def test_cada_situacion_tiene_su_seccion_con_pasos_numerados(html, situacion):
    seccion = re.search(rf'<section class="guia-caso" id="{situacion}".*?</section>', html, re.S)
    assert seccion, situacion
    assert '<ol class="pasos">' in seccion.group(0)
    assert seccion.group(0).count("<li>") >= 4
    assert f'<a href="#{situacion}">' in html


def test_dice_que_el_numero_del_banco_sale_de_la_tarjeta_y_no_del_mensaje(html):
    assert "Llama a tu banco con el número que está en tu tarjeta o en su app." in html
    assert "Nunca uses el número que vino en el mensaje." in html


def test_explica_que_pruebas_guardar_y_donde_denunciar(html):
    assert 'id="pruebas"' in html and 'id="denunciar"' in html
    for texto in ("Capturas del mensaje", "La fecha y la hora", "El monto", "DIVINDAT", "INDECOPI"):
        assert texto in html


def test_los_enlaces_de_fuera_van_solo_a_sitios_oficiales_por_https(html):
    externos = re.findall(r'<a href="(https?://[^"]+)"([^>]*)>', html)
    assert externos
    for url, atributos in externos:
        partes = urlsplit(url)
        assert partes.scheme == "https"
        assert partes.hostname in SITIOS_OFICIALES, url
        assert 'rel="noopener noreferrer"' in atributos


def test_no_hay_telefonos_que_no_se_pudieron_verificar(html):
    # Ningún número de contacto: los de las entidades no se verificaron en su sitio.
    assert not re.search(r"\b\d{3}[ -]?\d{3,4}\b", _visible(html))
    assert "tel:" not in html and "wa.me" not in html


def test_la_guia_no_usa_jerga_ni_scripts_ni_estilos_en_linea(html):
    assert terminos_prohibidos(_visible(html)) == []
    assert not re.search(r"<script|<style|\sstyle=|\son[a-z]+=", html, flags=re.IGNORECASE)


def test_cada_anclaje_interno_de_la_guia_existe(html):
    for ancla in re.findall(r'<a href="#([^"]+)"', html):
        assert f'id="{ancla}"' in html, ancla


def test_el_inicio_y_la_cabecera_enlazan_a_la_guia(client):
    inicio = client.get(reverse("inicio")).content.decode()
    assert '<a href="/guia/"' in inicio
    for situacion in SITUACIONES:
        assert f'href="/guia/#{situacion}"' in inicio


@pytest.mark.parametrize("enlace", [
    "https://ejemplo.com/inicio",
    "http://192.0.2.10/verifica",
    "https://banco.pe@a.b.c.d.bit.ly/verifica",
])
@pytest.mark.django_db
def test_todo_resultado_desde_ten_cuidado_enlaza_a_la_guia(client, enlace):
    respuesta = client.post(reverse("analizar"), {"enlace": enlace}, follow=True)
    resultado = respuesta.content.decode()
    assert ">Seguro</h1>" not in resultado
    for situacion in SITUACIONES:
        assert f'href="/guia/#{situacion}"' in resultado


def test_ningun_comentario_de_la_plantilla_llega_a_la_pagina(html):
    # En Django, {# #} solo vale en una línea. Uno de varias líneas se imprime tal cual.
    assert "{#" not in html and "#}" not in html
    assert "{%" not in html and "verificados" not in html


def test_la_guia_no_se_confunde_con_el_inicio(client, html):
    inicio = client.get(reverse("inicio")).content.decode()
    titulo = re.search(r"<h1>(.*?)</h1>", html, re.S).group(1)
    assert titulo == "Qué hacer si ya hiciste clic, diste tus datos o pagaste"
    assert titulo not in inicio
    # La cabecera marca la guía como la página actual, y solo en la guía.
    assert '<a href="/guia/" aria-current="page">Ya hice clic</a>' in html
    assert "aria-current" not in inicio
    assert '<p class="guia-ruta"><a href="/">Inicio</a>' in html
