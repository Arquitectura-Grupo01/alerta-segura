"""Página de resultado (tarea 27): un test por nivel, por la vista real y no solo la plantilla."""

import re
from dataclasses import asdict
from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from analisis.models import Analisis
from motor.explicacion import ACLARACION_SEGURO
from motor.riesgo import VERSION_INICIAL, Nivel, Senales, calcular

pytestmark = pytest.mark.django_db

DOMINIO = "web-de-prueba.example"

SENALES_POR_NIVEL = {
    Nivel.SEGURO: Senales(heuristicas=(), edad_dias=4000, marca=0, fuentes=0),
    Nivel.TEN_CUIDADO: Senales(heuristicas=("acortador",)),
    Nivel.PELIGROSO: Senales(fuentes=100, fuentes_con_deteccion=1),
    Nivel.PELIGRO_ALTO: Senales(fuentes=100, fuentes_con_deteccion=2),
}
FUENTES = [
    {"fuente": "a", "titulo": "Lista A", "estado": "deteccion", "valor": 100},
    {"fuente": "b", "titulo": "Lista B", "estado": "desconocido", "valor": None},
]


def guardar(senales, dominio=DOMINIO, hace_minutos=0, desde_cache=False):
    veredicto = calcular(senales)
    return Analisis.objects.create(
        fecha_analisis=timezone.now() - timedelta(minutes=hace_minutos),
        tipo_entrada=Analisis.Tipo.ENLACE,
        dominio=dominio,
        redirecciones=0,
        nivel=int(veredicto.nivel),
        puntaje=veredicto.puntaje,
        cobertura=veredicto.cobertura,
        version_reglas=VERSION_INICIAL.numero,
        senales=asdict(senales),
        reglas=list(veredicto.reglas),
        fuentes=FUENTES if senales.fuentes_con_deteccion else [],
        desde_cache=desde_cache,
    )


def ver(client, analisis):
    return client.get(reverse("resultado", args=[analisis.publico]))


@pytest.mark.parametrize("nivel", list(Nivel), ids=lambda nivel: nivel.clave)
def test_cada_nivel_sigue_el_orden_y_las_reglas_de_la_pagina(client, nivel):
    analisis = guardar(SENALES_POR_NIVEL[nivel])
    assert analisis.nivel == nivel
    res = ver(client, analisis)
    html = res.content.decode()
    assert res.status_code == 200
    assert res["Cache-Control"] == "no-store"
    assert '<meta name="robots" content="noindex">' in html

    # Nivel con color, ícono y palabra, y después titular, motivos, qué hacer y detalle.
    marcas = [
        f'class="resultado resultado-principal nivel-{nivel.clave}"',
        f'href="#i-{nivel.clave}"',
        f'id="resultado-nivel">{nivel.texto}</h1>',
        'class="resultado-titular"',
        ">Por qué</h2>",
        ">Qué hacer</h2>",
        "<summary>Ver detalle técnico</summary>",
        'id="reporte"',
    ]
    posiciones = [html.index(marca) for marca in marcas]
    assert posiciones == sorted(posiciones)

    motivos = re.search(r'<ul class="motivos">(.*?)</ul>', html, re.S).group(1)
    assert 3 <= motivos.count("<li>") <= 5
    acciones = re.search(r'<ol class="acciones">(.*?)</ol>', html, re.S).group(1)
    assert acciones.count("<li>") >= 1

    # El detalle empieza colapsado y el destino nunca es un enlace.
    assert '<details class="detalle">' in html
    assert not re.search(rf'href="[^"]*{re.escape(DOMINIO)}', html)
    assert DOMINIO in html

    # La guía aparece desde Ten cuidado; la aclaración, solo en Seguro.
    assert ('id="ya-hice-clic"' in html) is (nivel >= Nivel.TEN_CUIDADO)
    assert (ACLARACION_SEGURO in html) is (nivel == Nivel.SEGURO)
    assert "100 % seguro" not in html.lower() and "100% seguro" not in html.lower()


def test_un_resultado_de_la_cache_dice_hace_cuanto_se_analizo(client):
    analisis = guardar(SENALES_POR_NIVEL[Nivel.TEN_CUIDADO], hace_minutos=42, desde_cache=True)
    assert "Analizado hace 42 minutos" in ver(client, analisis).content.decode()


def test_un_resultado_recien_calculado_no_dice_hace_cuanto(client):
    analisis = guardar(SENALES_POR_NIVEL[Nivel.TEN_CUIDADO], hace_minutos=42)
    html = ver(client, analisis).content.decode()
    assert "Analizado hace" not in html and "Resultado del análisis" in html


def test_un_nombre_con_letras_de_otros_alfabetos_se_muestra_en_punycode(client):
    # «раураl.com» con letras cirílicas, que se ven como las latinas.
    html = client.post(
        reverse("analizar"), {"enlace": "https://раураl.com/"},
        follow=True,
    ).content.decode()
    assert "xn--" in html
    assert "раураl" not in html


def test_un_identificador_que_no_existe_da_404(client):
    import uuid

    assert client.get(reverse("resultado", args=[uuid.uuid4()])).status_code == 404


def test_el_resultado_solo_acepta_get(client):
    analisis = guardar(SENALES_POR_NIVEL[Nivel.PELIGROSO])
    assert client.post(reverse("resultado", args=[analisis.publico])).status_code == 405
