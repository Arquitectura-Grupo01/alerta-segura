"""Páginas legales y de confianza, y el pedido de revisión de los dueños (tareas 32 y 29)."""

import re
from datetime import date, timedelta

import pytest
from django.test import Client
from django.urls import reverse

from core.views import CONTACTO_SEGURIDAD, SECURITY_TXT_VENCE
from curacion.models import SolicitudRevision

PAGINAS = ["privacidad", "terminos", "como_verificamos", "contacto"]


def enviar(client, dominio="mi-tienda.example", mensaje="Es la web de mi tienda de ropa."):
    return client.post(reverse("solicitar_revision"), {"dominio": dominio, "mensaje": mensaje})


@pytest.mark.parametrize("nombre", PAGINAS)
def test_cada_pagina_existe_y_esta_enlazada_desde_el_pie(client, nombre):
    res = client.get(reverse(nombre))
    assert res.status_code == 200
    pie = client.get(reverse("inicio")).content.decode().split('<footer class="pie">')[1]
    assert f'href="{reverse(nombre)}"' in pie


@pytest.mark.parametrize("nombre", ["privacidad", "terminos", "como_verificamos"])
def test_las_paginas_de_texto_no_reciben_datos(client, nombre):
    assert client.post(reverse(nombre)).status_code == 405
    assert "<form" not in client.get(reverse(nombre)).content.decode()


def test_la_privacidad_dice_que_guarda_que_no_y_a_quien_consulta(client):
    html = client.get(reverse("privacidad")).content.decode()
    for texto in ("Qué guardamos", "Lo que nunca guardamos", "Por cuánto tiempo",
                  "A quién consultamos", "Ley N.° 29733", "solo si el resultado es Peligroso"):
        assert texto in html
    # Cada servicio externo figura con lo que recibe.
    for servicio in ("Google Safe Browsing", "VirusTotal", "urlscan.io", "URLhaus", "PhishTank",
                     "AbuseIPDB"):
        assert servicio in html


def test_los_terminos_aclaran_que_orienta_y_no_reemplaza_a_nadie(client):
    html = client.get(reverse("terminos")).content.decode()
    assert "Orienta, no garantiza" in html
    for quien in ("tu banco", "la policía", "un abogado"):
        assert quien in html


def test_como_verificamos_explica_los_limites(client):
    html = client.get(reverse("como_verificamos")).content.decode()
    assert "cloaking" in html
    assert "no cuenta como web limpia" in html


@pytest.mark.parametrize("nombre", ["terminos", "como_verificamos"])
def test_el_dominio_oficial_sale_de_la_configuracion(client, settings, nombre):
    settings.DOMINIO_OFICIAL = "oficial.example"
    assert '<b class="mono">oficial.example</b>' in client.get(reverse(nombre)).content.decode()
    settings.DOMINIO_OFICIAL = ""
    html = client.get(reverse(nombre)).content.decode()
    assert "una sola dirección" in html and "oficial.example" not in html


# --- security.txt -------------------------------------------------------------

def test_security_txt_responde_con_contacto_y_vencimiento(client, settings):
    settings.DOMINIO_OFICIAL = ""
    res = client.get("/.well-known/security.txt")
    assert res.status_code == 200
    assert res["Content-Type"] == "text/plain; charset=utf-8"
    texto = res.content.decode()
    assert f"Contact: {CONTACTO_SEGURIDAD}" in texto
    assert re.search(r"^Expires: \d{4}-\d{2}-\d{2}T00:00:00Z$", texto, re.M)
    assert "Canonical" not in texto


def test_security_txt_trae_la_direccion_canonica_si_hay_dominio_oficial(client, settings):
    settings.DOMINIO_OFICIAL = "oficial.example"
    texto = client.get("/.well-known/security.txt").content.decode()
    assert "Canonical: https://oficial.example/.well-known/security.txt" in texto


def test_security_txt_no_esta_vencido_ni_vence_en_mas_de_un_anio():
    """RFC 9116: menos de un año. Si este test falla, hay que renovar la fecha."""
    hoy = date.today()
    assert hoy + timedelta(days=30) <= SECURITY_TXT_VENCE <= hoy + timedelta(days=366)


# --- Pedido de revisión de los dueños -----------------------------------------

@pytest.mark.django_db
def test_el_pedido_entra_pendiente_y_muestra_un_agradecimiento_sin_promesas(client):
    res = enviar(client, dominio="https://www.Mi-Tienda.example/productos?utm_source=x")
    assert res.status_code == 302
    assert res["Location"] == f"{reverse('contacto')}?enviado=1#formulario"
    solicitud = SolicitudRevision.objects.get()
    assert (solicitud.dominio, solicitud.estado) == ("www.mi-tienda.example", "pendiente")
    html = client.get(res["Location"]).content.decode()
    assert "Recibimos tu pedido." in html and "<form" not in html
    for promesa in ("vamos a cambiar", "quitaremos", "corregiremos", "te responderemos"):
        assert promesa not in html.lower()


@pytest.mark.django_db
def test_el_mensaje_se_guarda_enmascarado(client):
    enviar(client, mensaje="Escríbeme a dueno@correo.example o al 987 654 321. Mi DNI 45678912.")
    mensaje = SolicitudRevision.objects.get().mensaje
    assert "dueno@correo.example" not in mensaje and "987 654 321" not in mensaje
    assert "45678912" not in mensaje
    assert "[CORREO]" in mensaje


@pytest.mark.django_db
@pytest.mark.parametrize(("dominio", "mensaje", "error"), [
    ("", "Es mi web.", "Escribe el nombre de tu web"),
    ("javascript:alert(1)", "Es mi web.", "Escribe el nombre de tu web"),
    ("mi-tienda.example", "   ", "Cuéntanos en pocas palabras"),
    ("mi-tienda.example", "x" * 1001, "El mensaje puede tener hasta 1000 caracteres."),
])
def test_un_pedido_incompleto_vuelve_al_formulario_con_el_error(client, dominio, mensaje, error):
    res = enviar(client, dominio=dominio, mensaje=mensaje)
    assert res.status_code == 400
    assert res["Cache-Control"] == "no-store"
    assert error in res.content.decode()
    assert not SolicitudRevision.objects.exists()


@pytest.mark.django_db
def test_lo_que_escribe_la_persona_vuelve_escapado(client):
    html = enviar(client, dominio='"><script>alert(1)</script>', mensaje="").content.decode()
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


@pytest.mark.django_db
def test_comparte_el_limite_de_10_por_hora_con_los_reportes(client):
    codigos = [enviar(client).status_code for _ in range(12)]
    assert codigos == [302] * 10 + [429] * 2
    assert SolicitudRevision.objects.count() == 10


@pytest.mark.django_db
def test_el_pedido_exige_el_token_csrf():
    estricto = Client(enforce_csrf_checks=True)
    assert enviar(estricto).status_code == 403


def test_el_formulario_no_pide_datos_personales(client):
    html = client.get(reverse("contacto")).content.decode()
    formulario = html.split('<form class="contacto"')[1].split("</form>")[0]
    campos = set(re.findall(r'name="([a-z_]+)"', formulario))
    assert campos == {"dominio", "mensaje", "csrfmiddlewaretoken"}


def test_pedir_el_formulario_con_get_no_guarda_nada(client):
    client.get(reverse("contacto"), {"dominio": "x.example", "mensaje": "hola"})
    assert client.get(reverse("solicitar_revision")).status_code == 405
