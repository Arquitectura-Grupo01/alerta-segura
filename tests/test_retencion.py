"""Tarea 40: plazos de conservación y purga de datos vencidos."""
from dataclasses import asdict
from datetime import timedelta

import pytest
from django.contrib.sessions.models import Session
from django.core.cache import caches
from django.core.management import call_command
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from analisis.models import Analisis
from config.settings import cache as config_cache
from core import retencion
from core.models import EventoAuditoria, EventoInmutable, TipoEvento
from curacion.models import ReporteDesacuerdo, SolicitudRevision
from motor.riesgo import VERSION_INICIAL, Nivel, Senales

pytestmark = pytest.mark.django_db

DIA = timedelta(days=1)


def hace(dias):
    return timezone.now() - dias * DIA


def analisis(dias, dominio="ejemplo.pe"):
    senales = Senales(fuentes=0, edad_dias=4000, marca=0)
    return Analisis.objects.create(
        tipo_entrada=Analisis.Tipo.ENLACE, dominio=dominio, nivel=Nivel.TEN_CUIDADO,
        puntaje=30, cobertura=100, version_reglas=VERSION_INICIAL.numero,
        senales={**asdict(senales), "heuristicas": []}, fecha=hace(dias),
    )


def reporte(de, estado="pendiente", resuelto_hace=None):
    return ReporteDesacuerdo.objects.create(
        analisis=de, tipo="era_estafa", estado=estado, fecha=de.fecha,
        resuelto_en=hace(resuelto_hace) if resuelto_hace is not None else None,
    )


def evento(dias):
    nuevo = EventoAuditoria(tipo=TipoEvento.INICIO_SESION, fecha=hace(dias))
    nuevo.save()
    return nuevo


def sesion(clave, vence_en_dias):
    return Session.objects.create(
        session_key=clave.ljust(32, "0"), session_data="",
        expire_date=timezone.now() + vence_en_dias * DIA,
    )


def existe(objeto):
    return type(objeto).objects.filter(pk=objeto.pk).exists()


def test_la_purga_borra_solo_lo_vencido(capsys):
    """Condición de término de la tarea 40."""
    viejo = analisis(retencion.DIAS_ANALISIS + 1)
    nuevo = analisis(retencion.DIAS_ANALISIS - 1)
    viejo_con_pendiente = analisis(retencion.DIAS_ANALISIS + 30)
    pendiente = reporte(viejo_con_pendiente)
    resuelto_viejo = reporte(nuevo, "resuelto", resuelto_hace=retencion.DIAS_REPORTES_RESUELTOS + 1)
    resuelto_nuevo = reporte(nuevo, "resuelto", resuelto_hace=10)
    pedido_viejo = SolicitudRevision.objects.create(
        dominio="ejemplo.pe", mensaje="Es mi web", estado="resuelto",
        fecha=hace(500), resuelto_en=hace(retencion.DIAS_REPORTES_RESUELTOS + 1),
    )
    pedido_pendiente = SolicitudRevision.objects.create(
        dominio="ejemplo.pe", mensaje="Es mi web", fecha=hace(900),
    )
    evento_viejo = evento(retencion.DIAS_AUDITORIA + 1)
    evento_nuevo = evento(retencion.DIAS_ANALISIS + 1)
    sesion_vencida = sesion("vencida", -1)
    sesion_activa = sesion("activa", 1)

    call_command("purgar_datos")

    for borrado in (viejo, resuelto_viejo, pedido_viejo, evento_viejo, sesion_vencida):
        assert not existe(borrado), borrado
    for vigente in (nuevo, viejo_con_pendiente, pendiente, resuelto_nuevo, pedido_pendiente,
                    evento_nuevo, sesion_activa):
        assert existe(vigente), vigente
    salida = capsys.readouterr().out
    assert "Se borraron 1 filas de analisis." in salida
    assert "La base ocupa" in salida


def test_la_purga_queda_en_la_auditoria():
    evento(retencion.DIAS_AUDITORIA + 1)
    analisis(retencion.DIAS_ANALISIS + 1)
    call_command("purgar_datos")
    purga = EventoAuditoria.objects.get(tipo=TipoEvento.PURGA_DATOS)
    assert purga.detalle["eventos"] == 1
    assert purga.detalle["analisis"] == 1
    assert set(purga.detalle) == {
        "analisis", "reportes", "pedidos", "eventos", "sesiones", "cache_vencida",
    }


def test_simular_no_borra_nada_ni_deja_evento(capsys):
    viejo = analisis(retencion.DIAS_ANALISIS + 1)
    viejo_evento = evento(retencion.DIAS_AUDITORIA + 1)
    call_command("purgar_datos", simular=True)
    assert existe(viejo) and existe(viejo_evento)
    assert not EventoAuditoria.objects.filter(tipo=TipoEvento.PURGA_DATOS).exists()
    salida = capsys.readouterr().out
    assert "Se borrarían 1 filas de analisis." in salida
    assert "Se borrarían 1 filas de eventos." in salida


def test_borra_en_lotes_pequenos(monkeypatch):
    monkeypatch.setattr(retencion, "LOTE", 2)
    for _ in range(5):
        evento(retencion.DIAS_AUDITORIA + 1)
        analisis(retencion.DIAS_ANALISIS + 1)
    lotes = []
    original = EventoAuditoria.objects.purgar_lote

    def contar(antes_de, lote):
        lotes.append(lote)
        return original(antes_de, lote)

    monkeypatch.setattr(EventoAuditoria.objects, "purgar_lote", contar, raising=False)
    call_command("purgar_datos")
    assert lotes == [2, 2, 2]
    assert not Analisis.objects.exists()
    assert EventoAuditoria.objects.get(tipo=TipoEvento.PURGA_DATOS).detalle["analisis"] == 5


def test_la_auditoria_sigue_cerrada_fuera_de_la_purga():
    viejo = evento(retencion.DIAS_AUDITORIA + 1)
    with pytest.raises(EventoInmutable):
        EventoAuditoria.objects.filter(pk=viejo.pk).delete()
    assert EventoAuditoria.objects.purgar_lote(hace(retencion.DIAS_AUDITORIA), 10) == 1


def test_la_auditoria_dura_mas_que_lo_que_audita():
    assert retencion.DIAS_AUDITORIA > max(
        retencion.DIAS_ANALISIS, retencion.DIAS_REPORTES_RESUELTOS,
    )
    assert retencion.DIAS_AUDITORIA >= 365


def test_hay_una_sentencia_fija_por_cada_tabla_de_cache():
    tablas = {
        config_cache.TABLA_CACHE, config_cache.TABLA_CACHE_TECNICA,
        config_cache.TABLA_CACHE_RESULTADOS,
    }
    assert set(retencion.BORRAR_CACHE_VENCIDA) == tablas


def test_borra_las_filas_vencidas_de_la_cache_en_postgres():
    tablas = config_cache.construir_caches("db", "")
    with override_settings(CACHES={**tablas, "default": tablas["default"]}):
        call_command("createcachetable")
        caches["tecnica"].set("respuesta", {"dato": 1}, timeout=60)
        caches["default"].set("contador", 3, timeout=60)
        assert retencion.purgar_cache_vencida(timezone.now()) == 0
        assert caches["tecnica"].get("respuesta") == {"dato": 1}
        # Un día después, las dos filas ya vencieron.
        assert retencion.purgar_cache_vencida(timezone.now() + DIA) == 2
        assert caches["tecnica"].get("respuesta") is None


def test_avisa_cuando_la_base_pasa_el_80_por_ciento(monkeypatch, capsys):
    monkeypatch.setattr(retencion, "LIMITE_NEON_BYTES", 1024)
    call_command("purgar_datos", simular=True)
    assert "pasó el 80 %" in capsys.readouterr().err


def test_mide_el_uso_de_la_base():
    assert retencion.uso_de_la_base() > 0


def test_los_plazos_se_publican_en_la_politica_de_privacidad(client):
    html = client.get(reverse("privacidad")).content.decode()
    assert "Todavía no se borran solos" not in html
    for texto in ("<dt>Análisis</dt><dd>Un año.", "Reportes y pedidos de revisión",
                  "<dt>Registro de lo que hace el equipo</dt><dd>Dos años."):
        assert texto in html
