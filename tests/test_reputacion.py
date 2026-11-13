"""Base de reputación propia (tarea 23)."""

import pytest
from django.urls import reverse

from analisis import orquestador
from analisis.models import Analisis
from core.resultados import leer_resultado
from inteligencia import fuentes as modulo_fuentes
from inteligencia.fuentes import Fuente
from motor import reputacion
from motor.models import Reputacion
from motor.riesgo import VERSION_INICIAL, Nivel

pytestmark = pytest.mark.django_db

URL = "https://web-de-prueba.example/verifica?token=abc123"


class Detecta(Fuente):
    nombre = "detecta"
    titulo = "Lista de prueba"

    def _consultar(self, url):
        return self.deteccion(datos={"tipos": ["pagina_falsa"], "motores_total": 4321})


class InformaEdad(Fuente):
    nombre = "informa_edad"
    titulo = "Servicio con edad"

    def _consultar(self, url):
        return self.desconocido({"edad_web_dias": 4000})


def analizar(client, enlace=URL):
    return client.post(reverse("analizar"), {"enlace": enlace}, follow=True)


def test_tras_una_deteccion_externa_la_reputacion_no_guarda_ese_dato(client, monkeypatch):
    monkeypatch.setattr(modulo_fuentes, "_FUENTES", [Detecta()])
    analizar(client)
    assert Analisis.objects.get().nivel >= Nivel.PELIGROSO
    filas = list(Reputacion.objects.values())
    assert {fila["tipo"] for fila in filas} == {"dominio", "url"}
    for fila in filas:
        texto = repr({k: v for k, v in fila.items() if k != "clave"})
        assert "pagina_falsa" not in texto and "4321" not in texto and "detecta" not in texto
        assert fila["confirmado_por_analista"] is False
        assert fila["heuristicas"] == ["palabras_sospechosas"]
        # La dirección no se guarda en claro: puede traer el token de una víctima.
        assert "abc123" not in texto and "verifica" not in texto
    campos = {campo.name for campo in Reputacion._meta.fields}
    assert not campos & {"nivel", "puntaje", "fuentes", "valor"}


def test_la_edad_que_informa_una_fuente_no_entra_a_la_reputacion(client, monkeypatch):
    monkeypatch.setattr(modulo_fuentes, "_FUENTES", [InformaEdad()])
    analizar(client, "https://web-de-prueba.pe/")
    assert Analisis.objects.get().senales["edad_dias"] == 4000
    assert set(Reputacion.objects.values_list("registrado", flat=True)) == {None}


def test_la_edad_del_registro_publico_si_se_guarda(client, monkeypatch):
    monkeypatch.setattr(orquestador, "edad_en_dias", lambda dominios: 400)
    analizar(client)
    assert reputacion.edad_registrada("web-de-prueba.example") == 400


def test_cada_analisis_suma_a_la_web_y_a_la_direccion(client):
    analizar(client)
    analizar(client, "https://web-de-prueba.example/otra")
    web = Reputacion.objects.get(tipo="dominio")
    assert web.analisis == 2
    assert Reputacion.objects.filter(tipo="url").count() == 2


def test_un_reporte_suma_al_contador_y_no_cambia_el_nivel(client, monkeypatch):
    monkeypatch.setattr(modulo_fuentes, "_FUENTES", [Detecta()])
    respuesta = analizar(client)
    analisis = Analisis.objects.get()
    publico = analisis.publico
    for _ in range(5):
        client.post(reverse("reportar", args=[publico]), {"tipo": "era_legitimo"})
    web = Reputacion.objects.get(tipo="dominio")
    assert (web.reportes_legitimo, web.reportes_estafa) == (5, 0)
    analisis.refresh_from_db()
    assert analisis.nivel >= Nivel.PELIGROSO
    guardado = leer_resultado(analisis.url, VERSION_INICIAL.numero)
    assert guardado["nivel"] == analisis.nivel
    assert respuesta.status_code == 200


def test_un_fraude_confirmado_por_un_analista_da_peligro_alto(client):
    reputacion.marcar_confirmado("web-de-prueba.example")
    analizar(client)
    analisis = Analisis.objects.get()
    assert analisis.nivel == Nivel.PELIGRO_ALTO
    assert "analista_confirma" in analisis.reglas


def test_la_confirmacion_de_una_direccion_no_alcanza_a_otra_de_la_misma_web(client):
    reputacion.marcar_confirmado("web-de-prueba.example", url="https://web-de-prueba.example/otra")
    analizar(client, "https://web-de-prueba.example/inicio")
    assert "analista_confirma" not in Analisis.objects.get().reglas


def test_un_reporte_de_tipo_desconocido_no_suma():
    reputacion.sumar_reporte("web.example", "otro")
    reputacion.sumar_reporte("", "era_estafa")
    assert not Reputacion.objects.exists()


def test_la_confirmacion_de_la_direccion_pegada_vale_aunque_redirija(client, monkeypatch):
    from analisis.destino import Destino

    monkeypatch.setattr(
        orquestador, "seguir_enlace",
        lambda url: Destino("ok", url="https://destino-final.example/pago", saltos=1),
    )
    reputacion.marcar_confirmado("acortado.example", url="https://acortado.example/x")
    analizar(client, "https://acortado.example/x")
    assert "analista_confirma" in Analisis.objects.get().reglas


def test_si_la_base_falla_al_guardar_la_reputacion_el_analisis_sigue(client, monkeypatch):
    from django.db import DatabaseError

    def rota(*args, **kwargs):
        raise DatabaseError("sin base")

    monkeypatch.setattr(reputacion, "_registrar", rota)
    assert analizar(client).status_code == 200
    assert Analisis.objects.count() == 1
