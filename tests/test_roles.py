"""Tarea 35: roles de la consola y acceso denegado por defecto."""
import pytest
from django.conf import settings
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.management import call_command
from django.test import RequestFactory
from django.urls import Resolver404, get_resolver, resolve, reverse

from catalogo.models import Marca
from catalogo.servicios import actualizar_marca
from core.cuentas import crear_cuenta_interna
from core.models import EventoAuditoria
from core.roles import ADMINISTRADOR, ANALISTA, ROLES, es_administrador

pytestmark = pytest.mark.django_db

CLAVE = "clave-de-prueba-larga"
# Lo que solo abre un administrador: catálogo, reglas (motor), cuentas internas y su
# segundo factor. La auditoría se revisa aparte, porque es un solo modelo de core.
APPS_DEL_ADMINISTRADOR = ("catalogo", "motor", "auth", "otp_totp", "otp_static")
# Valores de prueba para los parámetros de una ruta: un id y una app registrada.
VALORES_DE_PRUEBA = ("1", "core")


def rutas_internas():
    """Todas las rutas de la consola, descubiertas desde el URLconf.

    Recorre lo registrado bajo el espacio de nombres del admin, con nombre o sin él, y
    arma cada ruta con valores de prueba. Así una ruta interna que se agregue después
    entra sola a este test. La página de ingreso queda fuera: es la única pública.
    """
    _, consola = get_resolver().namespace_dict["admin"]
    prefijo = "/" + settings.ADMIN_PATH
    rutas = set()
    for clave in list(consola.reverse_dict):
        for posibilidades, *_ in consola.reverse_dict.getlist(clave):
            for formato, parametros in posibilidades:
                for valor in VALORES_DE_PRUEBA:
                    ruta = prefijo + formato % {nombre: valor for nombre in parametros}
                    try:
                        coincidencia = resolve(ruta)
                    except Resolver404:
                        continue
                    if coincidencia.url_name != "login":
                        rutas.add(ruta)
    return sorted(rutas)


@pytest.fixture
def cuentas(db):
    analista, _, _ = crear_cuenta_interna("ana-roles", CLAVE, ANALISTA)
    administrador, _, _ = crear_cuenta_interna("beto-roles", CLAVE, ADMINISTRADOR)
    return analista, administrador


def test_crear_roles_deja_exactamente_los_permisos_de_cada_rol():
    analista = Group.objects.create(name=ANALISTA)
    # Un permiso agregado a mano desde el admin desaparece al volver a correr el comando.
    analista.permissions.add(Permission.objects.get(codename="delete_marca"))
    call_command("crear_roles")
    for nombre, permisos in ROLES.items():
        grupo = Group.objects.get(name=nombre)
        guardados = {f"{p.content_type.app_label}.{p.codename}" for p in grupo.permissions.all()}
        assert guardados == permisos


def test_el_administrador_tiene_todo_lo_del_analista():
    assert ROLES[ANALISTA] < ROLES[ADMINISTRADOR]


def test_nadie_borra_desde_la_consola():
    for permisos in ROLES.values():
        assert not [p for p in permisos if ".delete_" in p]


def test_el_recorrido_encuentra_las_rutas_internas():
    rutas = rutas_internas()
    prefijo = "/" + settings.ADMIN_PATH
    assert reverse("admin:index") in rutas
    assert reverse("admin:core_eventoauditoria_changelist") in rutas
    assert reverse("admin:auth_user_change", args=["1"]) in rutas
    assert prefijo + "core/" in rutas
    assert reverse("admin:login") not in rutas
    assert len(rutas) > 40


def test_las_rutas_internas_sin_sesion_dan_302_o_403(client):
    for ruta in rutas_internas():
        for metodo in (client.get, client.post):
            assert metodo(ruta).status_code in (302, 403), ruta


def test_las_rutas_internas_sin_segundo_factor_dan_302_o_403(client, django_user_model):
    """Ni siquiera un superusuario entra si la sesión no pasó por el código."""
    client.force_login(django_user_model.objects.create_superuser("super-roles", password="x"))
    for ruta in rutas_internas():
        assert client.get(ruta).status_code in (302, 403), ruta


def test_un_analista_no_abre_catalogo_reglas_cuentas_ni_auditoria(cuentas, ingresar_consola):
    analista, _ = cuentas
    client = ingresar_consola(analista)
    # Ningún permiso de esas apps, aunque todavía no tengan página en la consola.
    permisos = Permission.objects.filter(content_type__app_label__in=APPS_DEL_ADMINISTRADOR)
    assert permisos.exists()
    for permiso in permisos:
        assert not analista.has_perm(f"{permiso.content_type.app_label}.{permiso.codename}")

    prohibidos = [
        modelo for modelo in admin.site._registry
        if modelo._meta.app_label in APPS_DEL_ADMINISTRADOR or modelo is EventoAuditoria
    ]
    assert get_user_model() in prohibidos and EventoAuditoria in prohibidos
    for modelo in prohibidos:
        ruta = reverse(f"admin:{modelo._meta.app_label}_{modelo._meta.model_name}_changelist")
        assert client.get(ruta).status_code == 403, ruta
    assert client.get(reverse("admin:auth_user_add")).status_code == 403


def test_un_analista_abre_la_curacion(cuentas, ingresar_consola):
    analista, _ = cuentas
    client = ingresar_consola(analista)
    assert client.get(reverse("admin:curacion_reportedesacuerdo_changelist")).status_code == 200
    apps = {app["app_label"] for app in client.get(reverse("admin:index")).context["app_list"]}
    assert "curacion" in apps
    assert not apps & {*APPS_DEL_ADMINISTRADOR, "core"}


def test_un_administrador_abre_cuentas_y_auditoria(cuentas, ingresar_consola):
    _, administrador = cuentas
    client = ingresar_consola(administrador)
    assert client.get(reverse("admin:auth_user_changelist")).status_code == 200
    assert client.get(reverse("admin:core_eventoauditoria_changelist")).status_code == 200
    assert client.get(reverse("admin:curacion_reportedesacuerdo_changelist")).status_code == 200


def test_una_cuenta_interna_sin_rol_no_ve_nada(django_user_model, ingresar_consola):
    sin_rol = django_user_model.objects.create_user("sin-rol", password=CLAVE, is_staff=True)
    client = ingresar_consola(sin_rol)
    assert client.get(reverse("admin:index")).context["app_list"] == []
    for modelo in admin.site._registry:
        ruta = reverse(f"admin:{modelo._meta.app_label}_{modelo._meta.model_name}_changelist")
        assert client.get(ruta).status_code == 403, ruta


def test_un_permiso_de_ver_agregado_a_mano_no_abre_la_auditoria(cuentas, ingresar_consola):
    analista, _ = cuentas
    analista.user_permissions.add(Permission.objects.get(codename="view_eventoauditoria"))
    client = ingresar_consola(get_user_model().objects.get(pk=analista.pk))
    assert client.get(reverse("admin:core_eventoauditoria_changelist")).status_code == 403


def test_un_administrador_no_se_da_superusuario_ni_permisos_sueltos(cuentas):
    _, administrador = cuentas
    solicitud = RequestFactory().get("/")
    solicitud.user = administrador
    modelo_admin = admin.site._registry[get_user_model()]
    campos = modelo_admin.get_readonly_fields(solicitud, administrador)
    assert "is_superuser" in campos and "user_permissions" in campos
    assert not modelo_admin.has_delete_permission(solicitud, administrador)


def test_solo_un_administrador_cambia_el_catalogo(cuentas):
    analista, administrador = cuentas
    marca = Marca.objects.create(nombre="Banco Ficticio", tipo=Marca.Tipo.BANCO)
    assert not es_administrador(analista)
    assert es_administrador(administrador)
    with pytest.raises(PermissionError):
        actualizar_marca(marca_id=marca.pk, nombre="Otro Ficticio", tipo=marca.tipo,
                         activa=True, usuario=analista, motivo="Prueba")
    actualizar_marca(marca_id=marca.pk, nombre="Otro Ficticio", tipo=marca.tipo,
                     activa=True, usuario=administrador, motivo="Prueba")


def test_un_administrador_desactivado_deja_de_serlo(cuentas):
    _, administrador = cuentas
    administrador.is_active = False
    assert not es_administrador(administrador)
