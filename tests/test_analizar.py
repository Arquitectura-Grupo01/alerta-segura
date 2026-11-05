"""Pruebas de punta a punta del análisis de un enlace, desde el formulario hasta el resultado."""

import re

import pytest
from django.template.loader import render_to_string
from django.test import Client
from django.urls import reverse

from motor.explicacion import ACLARACION_SEGURO, explicar
from motor.riesgo import Nivel, Senales, calcular

# Un enlace por nivel alcanzable sin fuentes externas. Seguro no se alcanza: la cobertura es baja.
ENLACE_TEN_CUIDADO = "https://ejemplo.com/inicio"
ENLACE_PELIGROSO = "http://192.0.2.10/verifica"
ENLACE_PELIGRO_ALTO = "https://banco.pe@a.b.c.d.bit.ly/verifica"


def _analizar(client, enlace):
    return client.post(reverse("analizar"), {"enlace": enlace})


@pytest.mark.parametrize(
    ("enlace", "nivel"),
    [
        (ENLACE_TEN_CUIDADO, "Ten cuidado"),
        (ENLACE_PELIGROSO, "Peligroso"),
        (ENLACE_PELIGRO_ALTO, "Peligro alto"),
    ],
)
def test_resultado_por_nivel_en_el_orden_fijo(client, enlace, nivel):
    res = _analizar(client, enlace)
    html = res.content.decode()
    assert res.status_code == 200
    assert res["Cache-Control"] == "no-store"
    assert f'id="resultado-nivel">{nivel}</h1>' in html

    posiciones = [
        html.index('class="resultado-palabra"'),
        html.index(">Por qué<"),
        html.index(">Qué hacer<"),
        html.index("<summary>Ver detalle técnico</summary>"),
    ]
    assert posiciones == sorted(posiciones)
    # El detalle va colapsado.
    assert "<details class=\"detalle\">" in html
    # Desde Ten cuidado aparece la guía para quien ya hizo clic.
    assert 'id="ya-hice-clic"' in html


def test_resultado_trae_de_3_a_5_motivos_y_acciones(client):
    html = _analizar(client, ENLACE_PELIGROSO).content.decode()
    motivos = re.search(r'<ul class="motivos">(.*?)</ul>', html, re.DOTALL).group(1)
    acciones = re.search(r'<ol class="acciones">(.*?)</ol>', html, re.DOTALL).group(1)
    assert 3 <= motivos.count("<li>") <= 5
    assert acciones.count("<li>") >= 1


def test_sin_fuentes_externas_nunca_da_seguro(client):
    html = _analizar(client, ENLACE_TEN_CUIDADO).content.decode()
    assert ">Seguro</h1>" not in html
    assert "Todavía no tenemos datos suficientes para decir que es segura." in html


def test_el_destino_nunca_es_un_enlace(client):
    html = _analizar(client, "https://bcp.com.pe@sitio-falso.com/login").content.decode()
    assert "sitio-falso.com" in html
    assert not re.search(r'<a[^>]+href="[^"]*sitio-falso', html)
    assert not re.search(r'href="https?://', html)


def test_el_truco_del_arroba_muestra_el_host_real(client):
    html = _analizar(client, "https://bcp.com.pe@sitio-falso.com/login").content.decode()
    assert '<p class="resultado-dominio"><span class="oculto">Web que abre el enlace: </span>' \
        "sitio-falso.com</p>" in html
    assert "pero en realidad abre sitio-falso.com." in html


def test_el_resultado_no_se_indexa(client):
    html = _analizar(client, ENLACE_TEN_CUIDADO).content.decode()
    assert '<meta name="robots" content="noindex">' in html


def test_el_resultado_no_usa_scripts_ni_estilos_en_linea(client):
    html = _analizar(client, ENLACE_PELIGRO_ALTO).content.decode()
    assert not re.search(r"<script", html, flags=re.IGNORECASE)
    assert not re.search(r"<style", html, flags=re.IGNORECASE)
    assert not re.search(r"\sstyle=", html, flags=re.IGNORECASE)
    assert not re.search(r"\son[a-z]+=", html, flags=re.IGNORECASE)


def test_enlace_invalido_vuelve_al_inicio_con_el_error(client):
    res = _analizar(client, "javascript:alert(1)")
    html = res.content.decode()
    assert res.status_code == 400
    assert res["Cache-Control"] == "no-store"
    assert 'data-tipo="error">El protocolo o formato no está permitido.</p>' in html
    assert 'aria-invalid="true"' in html
    assert 'value="javascript:alert(1)"' in html


def test_enlace_vacio_responde_400(client):
    assert _analizar(client, "").status_code == 400


def test_lo_que_pegan_se_muestra_escapado(client):
    res = _analizar(client, '"><script>alert(1)</script> x')
    html = res.content.decode()
    assert res.status_code == 400
    assert "<script>alert(1)" not in html
    assert "&quot;&gt;&lt;script&gt;" in html


def test_analizar_solo_acepta_post(client):
    assert client.get(reverse("analizar")).status_code == 405


def test_analizar_exige_el_token_csrf():
    cliente = Client(enforce_csrf_checks=True)
    assert cliente.post(reverse("analizar"), {"enlace": ENLACE_TEN_CUIDADO}).status_code == 403


def test_el_formulario_del_inicio_envia_a_analizar(client):
    html = client.get(reverse("inicio")).content.decode()
    assert f'action="{reverse("analizar")}"' in html
    assert "data-prototipo" not in html


def _renderizar(senales):
    veredicto = calcular(senales)
    return render_to_string(
        "resultado.html",
        {
            "veredicto": veredicto,
            "nivel": veredicto.nivel,
            "explicacion": explicar(veredicto, "ejemplo.com"),
            "dominio": "ejemplo.com",
            "mostrar_guia": veredicto.nivel >= Nivel.TEN_CUIDADO,
        },
    )


def test_resultado_seguro_aclara_que_no_garantiza_y_no_muestra_la_guia():
    # Seguro todavía no sale del formulario: se prueba la plantilla con evidencia completa.
    html = _renderizar(Senales(heuristicas=(), edad_dias=800, marca=0, fuentes=0))
    assert 'id="resultado-nivel">Seguro</h1>' in html
    assert ACLARACION_SEGURO in html
    assert 'id="ya-hice-clic"' not in html
    assert "100 % seguro" not in html.lower()
