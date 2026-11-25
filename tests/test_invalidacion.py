"""Tarea 38: invalidación manual de resultados."""
import pytest
from django.urls import reverse

from analisis import orquestador
from analisis.models import Analisis
from core.cuentas import crear_cuenta_interna
from core.models import EventoAuditoria, InvalidacionDominio, TipoEvento
from core.resultados import leer_resultado
from core.roles import ANALISTA
from motor.riesgo import VERSION_INICIAL

pytestmark = pytest.mark.django_db

URL_A = "https://ejemplo.pe/confirmar?token=abc123"
URL_B = "https://ejemplo.pe/otra-pagina"
MOTIVO = "La web cambió de dueño según el pedido de revisión"


@pytest.fixture
def motor(monkeypatch):
    """Cuenta cuántas veces corre el análisis completo, sin la caché."""
    llamadas = []
    original = orquestador._calcular

    def contar(enlace):
        llamadas.append(enlace.url)
        return original(enlace)

    monkeypatch.setattr(orquestador, "_calcular", contar)
    return llamadas


@pytest.fixture
def analista(ingresar_consola):
    cuenta, _, _ = crear_cuenta_interna("ana-invalida", "clave-de-prueba-larga", ANALISTA)
    return cuenta, ingresar_consola(cuenta)


def analizar(client, enlace):
    return client.post(reverse("analizar"), {"enlace": enlace})


def invalidar(consola, valor, alcance="dominio", motivo=MOTIVO):
    return consola.post(reverse("admin:curacion_invalidar"), {
        "alcance": alcance, "valor": valor, "motivo": motivo,
    })


def test_invalidar_un_dominio_vuelve_a_llamar_al_motor_en_todas_sus_urls(
    client, motor, analista,
):
    """Condición de término de la tarea 38."""
    _, consola = analista
    analizar(client, URL_A)
    analizar(client, URL_B)
    analizar(client, URL_A)
    analizar(client, URL_B)
    assert len(motor) == 2

    respuesta = invalidar(consola, "ejemplo.pe")
    assert respuesta.status_code == 302

    analizar(client, URL_A)
    analizar(client, URL_B)
    assert len(motor) == 4


def test_invalidar_una_url_exacta_deja_las_demas_en_la_cache(client, motor, analista):
    _, consola = analista
    analizar(client, URL_A)
    analizar(client, URL_B)
    invalidar(consola, URL_A, alcance="url")
    analizar(client, URL_A)
    analizar(client, URL_B)
    assert motor == [URL_A, URL_B, URL_A]


def test_invalidar_no_cambia_el_veredicto_guardado(client, analista):
    _, consola = analista
    analizar(client, URL_A)
    antes = list(Analisis.objects.values_list("pk", "nivel", "puntaje"))
    invalidar(consola, "ejemplo.pe")
    assert list(Analisis.objects.values_list("pk", "nivel", "puntaje")) == antes


def test_cada_invalidacion_queda_auditada_sin_la_url(client, analista):
    cuenta, consola = analista
    invalidar(consola, URL_A, alcance="url")
    evento = EventoAuditoria.objects.get(tipo=TipoEvento.INVALIDACION)
    assert evento.usuario == cuenta
    assert evento.motivo == MOTIVO
    assert evento.detalle == {"alcance": "url", "dominio": "ejemplo.pe"}
    assert "abc123" not in f"{evento.objeto} {evento.motivo} {evento.detalle}"


def test_una_ip_no_llega_a_la_auditoria(analista):
    _, consola = analista
    invalidar(consola, "http://203.0.113.7/pagina")
    assert EventoAuditoria.objects.get(tipo=TipoEvento.INVALIDACION).detalle["dominio"] is None


def test_el_motivo_es_obligatorio(client, analista):
    _, consola = analista
    analizar(client, URL_A)
    respuesta = invalidar(consola, "ejemplo.pe", motivo="   ")
    assert respuesta.status_code == 200
    assert not InvalidacionDominio.objects.exists()
    assert not EventoAuditoria.objects.filter(tipo=TipoEvento.INVALIDACION).exists()
    assert leer_resultado(URL_A, VERSION_INICIAL.numero) is not None


def test_un_motivo_con_un_enlace_no_invalida_nada(client, analista):
    _, consola = analista
    analizar(client, URL_A)
    respuesta = invalidar(consola, URL_A, alcance="url", motivo="Ver https://otra.example/x")
    assert "no puede llevar enlaces" in respuesta.content.decode()
    assert leer_resultado(URL_A, VERSION_INICIAL.numero) is not None
    assert not EventoAuditoria.objects.filter(tipo=TipoEvento.INVALIDACION).exists()


def test_un_enlace_invalido_muestra_un_error(analista):
    _, consola = analista
    respuesta = invalidar(consola, "javascript:alert(1)")
    assert respuesta.status_code == 200
    assert "enlace o un dominio válido" in respuesta.content.decode()


def test_una_cuenta_sin_rol_no_invalida(django_user_model, ingresar_consola):
    sin_rol = django_user_model.objects.create_user("sin-rol", password="x" * 14, is_staff=True)
    consola = ingresar_consola(sin_rol)
    assert consola.get(reverse("admin:curacion_invalidar")).status_code == 403
    assert invalidar(consola, "ejemplo.pe").status_code == 403
    assert not InvalidacionDominio.objects.exists()


def test_la_lista_muestra_el_boton_y_no_deja_editar_contadores(analista):
    _, consola = analista
    invalidar(consola, "ejemplo.pe")
    html = consola.get(reverse("admin:core_invalidaciondominio_changelist")).content.decode()
    assert reverse("admin:curacion_invalidar") in html
    assert "ejemplo.pe" in html
    fila = InvalidacionDominio.objects.get()
    cambiar = reverse("admin:core_invalidaciondominio_change", args=[fila.pk])
    assert consola.post(cambiar, {"contador": 0}).status_code == 403
    assert InvalidacionDominio.objects.get().contador == 1
