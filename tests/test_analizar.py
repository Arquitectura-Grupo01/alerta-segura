"""Pruebas de punta a punta del análisis de un enlace, desde el formulario hasta el resultado."""

import functools
import json
import re
import socket
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from django.template.loader import render_to_string
from django.test import Client
from django.urls import reverse

from analisis import destino, edad, orquestador
from analisis.destino import Destino
from core import net
from motor.explicacion import ACLARACION_SEGURO, SIN_DESTINO, aviso_para_compartir, explicar
from motor.riesgo import Nivel, Senales, calcular

# Un enlace por nivel alcanzable sin fuentes externas. Seguro no se alcanza: la cobertura es baja.
ENLACE_TEN_CUIDADO = "https://ejemplo.com/inicio"
ENLACE_PELIGROSO = "http://192.0.2.10/verifica"
ENLACE_PELIGRO_ALTO = "https://banco.pe@a.b.c.d.bit.ly/verifica"


# Cada análisis deja su fila en la base.
pytestmark = pytest.mark.django_db


def _analizar(client, enlace):
    """Envía el formulario y sigue la redirección hasta la página de resultado."""
    return client.post(reverse("analizar"), {"enlace": enlace}, follow=True)


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
    assert "No encontramos nada malo, pero nos falta información para decir que es segura." in html


def test_el_destino_nunca_es_un_enlace(client):
    html = _analizar(client, "https://bcp.com.pe@sitio-falso.com/login").content.decode()
    # Se compara el texto exacto: CodeQL marca "dominio" in texto como validación incompleta.
    assert re.search(r">sitio-falso\.com</p>", html)
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
    # El único script es un archivo propio; ninguno va escrito en la página.
    assert re.findall(r"<script[^>]*>", html, flags=re.IGNORECASE) == [
        '<script src="/static/js/resultado.js" defer>'
    ]
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
            "publico": uuid.uuid4(),
        },
    )


def test_resultado_seguro_aclara_que_no_garantiza_y_no_muestra_la_guia():
    # Seguro todavía no sale del formulario: se prueba la plantilla con evidencia completa.
    html = _renderizar(Senales(heuristicas=(), edad_dias=800, marca=0, fuentes=0))
    assert 'id="resultado-nivel">Seguro</h1>' in html
    assert ACLARACION_SEGURO in html
    assert 'id="ya-hice-clic"' not in html
    assert "100 % seguro" not in html.lower()


def _red_simulada(monkeypatch, rutas):
    """Conecta el análisis a la pedir_url real con DNS y servidores simulados.

    Cada nombre resuelve a una IP pública de ejemplo y nada sale a internet.
    """
    nombres = {host for host, _ in rutas}

    def resolver(host, puerto, *args, **kwargs):
        assert host in nombres, f"El test no esperaba una consulta a {host}"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", puerto))]

    pedidas = []

    def manejar(peticion):
        clave = (peticion.headers["host"], peticion.url.path)
        pedidas.append((*clave, peticion.url.query.decode()))
        return rutas.get(clave, httpx.Response(404))

    monkeypatch.setattr(socket, "getaddrinfo", resolver)
    pedir = functools.partial(net.pedir_url, transporte=httpx.MockTransport(manejar))
    monkeypatch.setattr(destino, "pedir_url", pedir)
    monkeypatch.setattr(edad, "pedir_url", pedir)
    return pedidas


def _rdap(nombre, dias):
    fecha = (datetime.now(UTC) - timedelta(days=dias)).isoformat()
    return httpx.Response(200, json={
        "objectClassName": "domain",
        "ldhName": nombre,
        "events": [{"eventAction": "registration", "eventDate": fecha}],
    })


def test_un_acortador_que_lleva_a_una_web_de_3_dias(client, monkeypatch):
    registro = {"services": [
        [["example"], ["https://rdap.registro.example/"]],
        [["ly"], ["https://rdap.registro-ly.example/"]],
    ]}
    pedidas = _red_simulada(monkeypatch, {
        ("bit.ly", "/abc"): httpx.Response(301, headers={"Location": "https://web-nueva.example/"}),
        ("web-nueva.example", "/"): httpx.Response(
            200,
            headers={"Content-Type": "text/html; charset=utf-8"},
            content=b'<meta http-equiv="refresh" content="0;url=/verifica">',
        ),
        ("web-nueva.example", "/verifica"): httpx.Response(200, content=b"<form></form>"),
        ("data.iana.org", "/rdap/dns.json"): httpx.Response(200, content=json.dumps(registro)),
        ("rdap.registro.example", "/domain/web-nueva.example"): _rdap("web-nueva.example", 3),
        ("rdap.registro-ly.example", "/domain/bit.ly"): _rdap("bit.ly", 6000),
    })

    html = _analizar(client, "bit.ly/abc?utm_source=chat").content.decode()

    # El destino final es el que se muestra, y la edad es la suya.
    assert '<span class="oculto">Web que abre el enlace: </span>web-nueva.example</p>' in html
    assert "<li>La web se creó hace 3 días. Muchas estafas usan webs recién creadas.</li>" in html
    assert "<dt>Redirecciones" in html
    assert "<dd>2, desde bit.ly</dd>" in html
    # «verifica» está en la ruta del destino, no en el enlace que pegaron.
    assert "palabras como «verifica» o «login»" in html
    assert 'id="resultado-nivel">Peligroso</h1>' in html
    # El acortador recibió sus parámetros, y su propia edad no se consultó.
    assert pedidas[0] == ("bit.ly", "/abc", "utm_source=chat")
    assert ("rdap.registro-ly.example", "/domain/bit.ly", "") not in pedidas


def test_si_no_se_puede_seguir_el_enlace_el_detalle_lo_dice(client):
    html = _analizar(client, ENLACE_TEN_CUIDADO).content.decode()
    assert f"<dd>{SIN_DESTINO}</dd>" in html
    assert '<span class="oculto">Web que abre el enlace: </span>ejemplo.com</p>' in html
    # Lo que no se pudo saber va en el detalle, no entre los motivos.
    assert "No sabemos cuándo se creó la web." not in html
    assert "<dd>No se pudo saber</dd>" in html


def test_si_la_direccion_de_destino_no_se_puede_leer_se_analiza_el_enlace_pegado(
    client, monkeypatch
):
    monkeypatch.setattr(
        orquestador, "seguir_enlace",
        lambda url: Destino(net.RESULTADO_OK, "https://otra.example/a b", 1),
    )
    html = _analizar(client, ENLACE_TEN_CUIDADO).content.decode()
    assert f"<dd>{SIN_DESTINO}</dd>" in html
    assert '<span class="oculto">Web que abre el enlace: </span>ejemplo.com</p>' in html


def test_desde_ten_cuidado_se_puede_avisar_a_un_familiar_sin_mandar_el_enlace(client):
    html = _analizar(client, "https://bcp.com.pe@sitio-falso.com/login?token=abc").content.decode()
    boton = re.search(r'<div class="avisar" data-avisar hidden>\s*<button[^>]*>', html).group(0)
    # El dominio va desactivado y el aviso no trae la ruta, el token ni un enlace.
    assert "Lleva a sitio-falso[.]com." in boton
    assert "token" not in boton and "http" not in boton and "/login" not in boton
    assert "salió «Peligroso»" in boton


def test_el_aviso_no_existe_en_seguro_y_dice_el_nivel_y_la_accion():
    senales = Senales(heuristicas=(), edad_dias=800, marca=0, fuentes=0)
    assert aviso_para_compartir(calcular(senales), "ejemplo.com") == ""
    assert "data-avisar" not in _renderizar(senales)

    alto = calcular(Senales(fuentes=100, fuentes_con_deteccion=2))
    assert aviso_para_compartir(alto, "2001:db8::1") == (
        "Revisé en Alerta Segura un enlace que me llegó y salió «Peligro alto». "
        "Lleva a 2001[:]db8[:][:]1. Si te llega a ti, no abras el enlace, no respondas y "
        "borra el mensaje."
    )
