"""Catálogo de marcas y dominios oficiales desde la consola. Solo el rol administrador."""
import pytest
from django.core.exceptions import ValidationError
from django.test import Client
from django.urls import reverse
from django_otp import DEVICE_ID_SESSION_KEY
from django_otp.oath import totp
from django_otp.plugins.otp_totp.models import TOTPDevice

from catalogo.models import DominioOficial, HistorialMarca, Marca
from catalogo.servicios import crear_marca
from core.cuentas import crear_cuenta_interna
from core.models import EventoAuditoria, TipoEvento
from core.roles import ADMINISTRADOR, ANALISTA

pytestmark = pytest.mark.django_db

CLAVE = "clave-de-prueba-larga"
FUENTE = "https://www.ejemplo.pe/contacto"


def consola_de(nombre, rol=ADMINISTRADOR):
    cuenta, dispositivo, _ = crear_cuenta_interna(nombre, CLAVE, rol)
    consola = Client()
    consola.force_login(cuenta)
    sesion = consola.session
    sesion[DEVICE_ID_SESSION_KEY] = dispositivo.persistent_id
    sesion.save()
    consola.cuenta = cuenta
    consola.dispositivo = dispositivo
    return consola


def codigo(dispositivo):
    dispositivo.refresh_from_db()
    return str(totp(dispositivo.bin_key, step=dispositivo.step, t0=dispositivo.t0,
                    digits=dispositivo.digits)).zfill(dispositivo.digits)


@pytest.fixture
def admin1():
    return consola_de("admin-uno")


@pytest.fixture
def marca():
    return Marca.objects.create(nombre="Banco Ficticio", tipo=Marca.Tipo.BANCO)


def test_un_administrador_crea_una_marca_con_historial_y_auditoria(admin1):
    respuesta = admin1.post(reverse("admin:catalogo_marca_nueva"), {
        "nombre": "Caja Ficticia", "tipo": "caja", "motivo": "Alta inicial del catálogo",
    })
    assert respuesta.status_code == 302
    marca = Marca.objects.get(nombre="Caja Ficticia")
    assert marca.activa
    version = HistorialMarca.objects.get(marca=marca)
    assert (version.accion, version.usuario) == ("creacion", admin1.cuenta)
    evento = EventoAuditoria.objects.get(tipo=TipoEvento.CAMBIO_CATALOGO)
    assert evento.detalle == {"accion": "creacion", "marca_id": marca.pk}


def test_editar_y_restaurar_una_marca(admin1, marca):
    editar = reverse("admin:catalogo_marca_editar", args=[marca.pk])
    assert admin1.get(editar).status_code == 200
    admin1.post(editar, {"nombre": "Banco Nuevo Ficticio", "tipo": "banco", "activa": "on",
                         "motivo": "Cambio de nombre comercial"})
    marca.refresh_from_db()
    assert marca.nombre == "Banco Nuevo Ficticio"
    anterior = HistorialMarca.objects.get(marca=marca)
    assert anterior.nombre == "Banco Ficticio"

    ficha = admin1.get(reverse("admin:catalogo_marca_change", args=[marca.pk])).content.decode()
    restaurar = reverse("admin:catalogo_marca_restaurar", args=[marca.pk, anterior.pk])
    assert restaurar in ficha and "Cambio de nombre comercial" in ficha
    admin1.post(restaurar, {"motivo": "El cambio fue un error"})
    marca.refresh_from_db()
    assert marca.nombre == "Banco Ficticio"
    assert HistorialMarca.objects.filter(marca=marca).count() == 2


def test_sin_motivo_no_se_cambia_nada(admin1, marca):
    editar = reverse("admin:catalogo_marca_editar", args=[marca.pk])
    respuesta = admin1.post(editar, {"nombre": "Otro", "tipo": "banco", "motivo": ""})
    assert respuesta.status_code == 200
    marca.refresh_from_db()
    assert marca.nombre == "Banco Ficticio"
    assert not EventoAuditoria.objects.filter(tipo=TipoEvento.CAMBIO_CATALOGO).exists()


def test_un_error_del_servicio_se_muestra_en_el_formulario(admin1, marca):
    respuesta = admin1.post(reverse("admin:catalogo_marca_nueva"), {
        "nombre": "Banco Ficticio", "tipo": "banco", "motivo": "Duplicado",
    })
    assert respuesta.status_code == 200
    assert Marca.objects.filter(nombre="Banco Ficticio").count() == 1


def test_los_formularios_estandar_quedan_cerrados(admin1, marca):
    assert admin1.post(reverse("admin:catalogo_marca_add"), {"nombre": "X"}).status_code == 403
    cambiar = reverse("admin:catalogo_marca_change", args=[marca.pk])
    assert admin1.post(cambiar, {"nombre": "Y", "tipo": "banco"}).status_code == 403
    borrar = reverse("admin:catalogo_marca_delete", args=[marca.pk])
    assert admin1.post(borrar, {"post": "yes"}).status_code == 403
    assert admin1.post(reverse("admin:catalogo_dominiooficial_add"), {}).status_code == 403
    marca.refresh_from_db()
    assert marca.nombre == "Banco Ficticio"


@pytest.mark.django_db(transaction=True)
def test_un_dominio_oficial_necesita_la_aprobacion_de_otro_administrador(marca):
    admin1 = consola_de("admin-uno")
    admin2 = consola_de("admin-dos")
    admin1.post(reverse("admin:catalogo_dominiooficial_solicitar"), {
        "marca": marca.pk, "dominio": "bancoficticio.pe", "fuente_verificacion": FUENTE,
        "motivo": "Verificado en la web del banco",
    })
    dominio = DominioOficial.objects.get(dominio="bancoficticio.pe")
    assert dominio.estado == DominioOficial.Estado.PENDIENTE
    aprobar = reverse("admin:catalogo_dominiooficial_aprobar", args=[dominio.pk])

    # Quien lo pidió no puede aprobarlo.
    propio = admin1.post(aprobar, {"codigo": codigo(admin1.dispositivo), "motivo": "Mío"})
    assert "propia solicitud" in propio.content.decode()
    # Un código incorrecto tampoco.
    malo = "000000" if codigo(admin2.dispositivo) != "000000" else "111111"
    assert "inválido" in admin2.post(aprobar, {"codigo": malo, "motivo": "Revisado"}) \
        .content.decode()
    dominio.refresh_from_db()
    assert dominio.estado == DominioOficial.Estado.PENDIENTE

    # Tras un fallo, django-otp hace esperar antes de aceptar otro código.
    TOTPDevice.objects.filter(pk=admin2.dispositivo.pk).update(throttling_failure_count=0,
                                                               throttling_failure_timestamp=None)
    respuesta = admin2.post(aprobar, {"codigo": codigo(admin2.dispositivo), "motivo": "Revisado"})
    assert respuesta.status_code == 302
    dominio.refresh_from_db()
    assert (dominio.estado, dominio.aprobado_por) == (DominioOficial.Estado.APROBADO,
                                                      admin2.cuenta)


def test_solicitar_un_reemplazo_deja_el_actual_vigente(admin1, marca):
    actual = DominioOficial.objects.create(
        marca=marca, dominio="bancoficticio.pe", fuente_verificacion=FUENTE,
        estado=DominioOficial.Estado.APROBADO,
    )
    ficha = admin1.get(reverse("admin:catalogo_dominiooficial_change", args=[actual.pk]))
    reemplazar = reverse("admin:catalogo_dominiooficial_reemplazar", args=[actual.pk])
    assert reemplazar in ficha.content.decode()
    admin1.post(reemplazar, {"dominio_nuevo": "nuevobanco.pe", "fuente_verificacion": FUENTE,
                             "motivo": "Cambió de dominio"})
    nuevo = DominioOficial.objects.get(dominio="nuevobanco.pe")
    assert (nuevo.estado, nuevo.reemplaza_a) == (DominioOficial.Estado.PENDIENTE, actual)
    actual.refresh_from_db()
    assert actual.estado == DominioOficial.Estado.APROBADO


def test_un_analista_no_usa_ninguna_accion_del_catalogo(marca):
    analista = consola_de("ana-catalogo", ANALISTA)
    dominio = DominioOficial.objects.create(marca=marca, dominio="bancoficticio.pe",
                                            fuente_verificacion=FUENTE)
    for ruta in (
        reverse("admin:catalogo_marca_nueva"),
        reverse("admin:catalogo_marca_editar", args=[marca.pk]),
        reverse("admin:catalogo_dominiooficial_solicitar"),
        reverse("admin:catalogo_dominiooficial_aprobar", args=[dominio.pk]),
        reverse("admin:catalogo_dominiooficial_reemplazar", args=[dominio.pk]),
    ):
        assert analista.get(ruta).status_code == 403, ruta
        assert analista.post(ruta, {"motivo": "x"}).status_code == 403, ruta


def test_crear_marca_exige_el_rol_y_un_nombre_nuevo(marca, django_user_model):
    sin_rol = django_user_model.objects.create_user("sin-rol", password=CLAVE, is_staff=True)
    with pytest.raises(PermissionError):
        crear_marca(nombre="Otra", tipo="banco", usuario=sin_rol, motivo="Prueba")
    cuenta, _, _ = crear_cuenta_interna("admin-tres", CLAVE, ADMINISTRADOR)
    with pytest.raises(ValidationError):
        crear_marca(nombre="Banco Ficticio", tipo="banco", usuario=cuenta, motivo="Duplicado")
    with pytest.raises(ValidationError):
        crear_marca(nombre="Otra", tipo="banco", usuario=cuenta, motivo="  ")
