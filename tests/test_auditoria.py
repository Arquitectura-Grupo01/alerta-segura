import pytest
from django.contrib.auth.models import AnonymousUser
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError
from django.urls import reverse

from core.auditoria import registrar_evento
from core.models import EventoAuditoria, EventoInmutable, TipoEvento

pytestmark = pytest.mark.django_db


@pytest.fixture
def analista(django_user_model):
    return django_user_model.objects.create_user("analista-prueba", password="x" * 14)


@pytest.fixture
def evento(analista):
    return registrar_evento(
        TipoEvento.CAMBIO_CATALOGO, usuario=analista, objeto="catalogo.Dominio:42",
        motivo="Dominio oficial agregado", detalle={"marca": "Banco Ficticio", "version": 3},
    )


def test_registrar_evento_guarda_tipo_y_autor(evento, analista):
    guardado = EventoAuditoria.objects.get(pk=evento.pk)
    assert guardado.tipo == TipoEvento.CAMBIO_CATALOGO
    assert guardado.usuario == analista
    assert guardado.objeto == "catalogo.Dominio:42"
    assert guardado.motivo == "Dominio oficial agregado"
    assert guardado.detalle == {"marca": "Banco Ficticio", "version": 3}
    assert guardado.fecha is not None


def test_el_autor_es_opcional():
    assert registrar_evento(TipoEvento.DESTINO_BLOQUEADO).usuario is None


def test_un_visitante_anonimo_queda_sin_autor():
    assert registrar_evento(TipoEvento.FALLO_SESION, usuario=AnonymousUser()).usuario is None


def test_los_tipos_son_los_del_plan():
    assert set(TipoEvento.values) == {
        "inicio_sesion", "fallo_sesion", "bloqueo_cuenta", "cambio_catalogo",
        "cambio_reglas", "decision_curacion", "invalidacion", "fallo_fuente",
        "destino_bloqueado", "alerta_seguridad",
    }


def test_un_tipo_desconocido_no_se_guarda():
    with pytest.raises(ValueError):
        registrar_evento("inventado")
    assert EventoAuditoria.objects.count() == 0


# --- Solo agregar -----------------------------------------------------------

def test_editar_un_evento_falla(evento):
    evento.motivo = "Otro motivo"
    with pytest.raises(EventoInmutable):
        evento.save()
    assert EventoAuditoria.objects.get(pk=evento.pk).motivo == "Dominio oficial agregado"


def test_editar_con_force_update_tambien_falla(evento):
    with pytest.raises(EventoInmutable):
        evento.save(force_update=True)


def test_borrar_un_evento_falla(evento):
    with pytest.raises(EventoInmutable):
        evento.delete()
    assert EventoAuditoria.objects.filter(pk=evento.pk).exists()


def test_borrar_o_actualizar_en_bloque_falla(evento):
    with pytest.raises(EventoInmutable):
        EventoAuditoria.objects.all().delete()
    with pytest.raises(EventoInmutable):
        EventoAuditoria.objects.update(motivo="x")
    with pytest.raises(EventoInmutable):
        EventoAuditoria.objects.bulk_update([evento], ["motivo"])
    assert EventoAuditoria.objects.get(pk=evento.pk).motivo == "Dominio oficial agregado"


def test_un_evento_nuevo_con_el_id_de_otro_no_lo_sobrescribe(evento):
    copia = EventoAuditoria(pk=evento.pk, tipo=TipoEvento.CAMBIO_REGLAS, motivo="Editado")
    with pytest.raises(IntegrityError), transaction.atomic():
        copia.save()
    assert EventoAuditoria.objects.get(pk=evento.pk).motivo == "Dominio oficial agregado"


def test_bulk_create_que_actualiza_conflictos_falla(evento):
    copia = EventoAuditoria(pk=evento.pk, tipo=TipoEvento.CAMBIO_REGLAS, motivo="Editado")
    with pytest.raises(EventoInmutable):
        EventoAuditoria.objects.bulk_create(
            [copia], update_conflicts=True, unique_fields=["id"], update_fields=["motivo"],
        )
    assert EventoAuditoria.objects.get(pk=evento.pk).motivo == "Dominio oficial agregado"


def test_no_se_borra_una_cuenta_con_eventos(evento, analista):
    with pytest.raises(ProtectedError):
        analista.delete()
    assert EventoAuditoria.objects.filter(pk=evento.pk).exists()


# --- Sin datos personales ---------------------------------------------------

@pytest.mark.parametrize("detalle", [
    {"ip": "203.0.113.7"},
    {"url": "ok"},
    {"texto": "hola"},
    {"destino": "http://ejemplo.invalid/ruta"},
    {"destino": "203.0.113.7"},
    {"destino": "conecto a 203.0.113.7 y fallo"},
    {"destino": "2001:db8::1"},
    {"destino": "conecto a 2001:db8::1 y fallo"},
    {"destino": "[2001:db8::7]:443"},
    {"contacto": "persona@ejemplo.invalid"},
    {"documento": "DNI 45678912"},
    {"tarjeta_texto": "4111 1111 1111 1111"},
    {"largo": "a" * 121},
    {"anidado": {"a": 1}},
    {"lista": [1, 2]},
    {"Mayuscula": 1},
    {f"k{i}": i for i in range(11)},
])
def test_el_detalle_rechaza_datos_personales_y_formas_raras(detalle):
    with pytest.raises(ValueError) as error:
        registrar_evento(TipoEvento.ALERTA_SEGURIDAD, detalle=detalle)
    assert EventoAuditoria.objects.count() == 0
    # El mensaje nombra el campo, no repite el valor rechazado.
    assert "203.0.113" not in str(error.value)
    assert "45678912" not in str(error.value)


def test_el_detalle_acepta_numeros_booleanos_y_none():
    evento = registrar_evento(
        TipoEvento.ALERTA_SEGURIDAD, detalle={"total": 12, "ratio": 0.5, "activa": True, "x": None},
    )
    assert EventoAuditoria.objects.get(pk=evento.pk).detalle["total"] == 12


@pytest.mark.parametrize("campo,valor", [
    ("objeto", "http://ejemplo.invalid/"),
    ("objeto", "x" * 101),
    ("objeto", "Dominio de Juan Pérez"),
    ("motivo", "correo persona@ejemplo.invalid"),
    ("motivo", "x" * 201),
])
def test_objeto_y_motivo_tambien_se_validan(campo, valor):
    with pytest.raises(ValueError):
        registrar_evento(TipoEvento.CAMBIO_REGLAS, **{campo: valor})


@pytest.mark.parametrize("objeto", [
    "core.net",
    "catalogo.Dominio:42",
    "analisis.Analisis:3f2b1c9e-41d4-4716-a716-446655440000",
])
def test_objeto_guarda_identificadores_tal_cual(objeto):
    evento = registrar_evento(TipoEvento.INVALIDACION, objeto=objeto)
    assert EventoAuditoria.objects.get(pk=evento.pk).objeto == objeto


def test_una_hora_o_una_palabra_hexadecimal_no_cuentan_como_ip():
    evento = registrar_evento(TipoEvento.FALLO_SESION, motivo="Fallo a las 12:30 en cafe:beef")
    assert evento.motivo == "Fallo a las 12:30 en cafe:beef"


def test_el_detalle_debe_ser_un_diccionario():
    with pytest.raises(ValueError):
        registrar_evento(TipoEvento.CAMBIO_REGLAS, detalle=["a"])


# --- Admin ------------------------------------------------------------------

def test_el_admin_no_permite_agregar_editar_ni_borrar(evento, client, django_user_model):
    superusuario = django_user_model.objects.create_superuser(
        "super-prueba", password="y" * 14,
    )
    client.force_login(superusuario)
    assert client.get(reverse("admin:core_eventoauditoria_changelist")).status_code == 200
    assert client.get(reverse("admin:core_eventoauditoria_add")).status_code == 403
    cambiar = reverse("admin:core_eventoauditoria_change", args=[evento.pk])
    borrar = reverse("admin:core_eventoauditoria_delete", args=[evento.pk])
    # Con permiso de solo ver, la página de "cambio" se muestra sin formulario de guardado.
    pagina = client.get(cambiar)
    assert pagina.status_code == 200
    assert b'name="_save"' not in pagina.content
    assert client.post(cambiar, {"motivo": "otro"}).status_code == 403
    assert client.get(borrar).status_code == 403
    assert client.post(borrar, {"post": "yes"}).status_code == 403
    assert EventoAuditoria.objects.get(pk=evento.pk).motivo == "Dominio oficial agregado"
