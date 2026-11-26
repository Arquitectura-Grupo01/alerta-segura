"""Tarea 34: ingreso a la consola con usuario, contraseña y TOTP, bloqueo y sesión."""
import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import CommandError, call_command
from django.urls import NoReverseMatch, reverse
from django_otp.oath import totp
from django_otp.plugins.otp_static.models import StaticDevice, StaticToken
from django_otp.plugins.otp_totp.models import TOTPDevice

from core import bloqueo
from core.consola import MENSAJE_ERROR
from core.cuentas import crear_cuenta_interna
from core.models import EventoAuditoria, TipoEvento
from core.roles import ANALISTA

pytestmark = pytest.mark.django_db

CLAVE = "clave-de-prueba-larga"


@pytest.fixture
def cuenta():
    """Cuenta interna ficticia con su autenticador y sus códigos de recuperación."""
    cuenta, dispositivo, codigos = crear_cuenta_interna("ana-consola", CLAVE, ANALISTA)
    return cuenta, dispositivo, codigos


def codigo_actual(dispositivo):
    return str(totp(dispositivo.bin_key, step=dispositivo.step, t0=dispositivo.t0,
                    digits=dispositivo.digits)).zfill(dispositivo.digits)


def ingresar(client, usuario, clave, codigo):
    return client.post(reverse("admin:login"), {
        "username": usuario, "password": clave, "otp_token": codigo,
        "next": reverse("admin:index"),
    })


def puede_abrir_la_consola(client):
    return client.get(reverse("admin:index")).status_code == 200


def eventos(tipo):
    return EventoAuditoria.objects.filter(tipo=tipo)


def test_ingresa_con_usuario_clave_y_codigo(client, cuenta):
    usuario, dispositivo, _ = cuenta
    respuesta = ingresar(client, "ana-consola", CLAVE, codigo_actual(dispositivo))
    assert respuesta.status_code == 302
    assert respuesta.url == reverse("admin:index")
    assert puede_abrir_la_consola(client)
    evento = eventos(TipoEvento.INICIO_SESION).get()
    assert evento.usuario == usuario
    assert evento.detalle == {"factor": "autenticador"}


def test_sin_codigo_no_ingresa(client, cuenta):
    respuesta = ingresar(client, "ana-consola", CLAVE, "")
    assert respuesta.status_code == 200
    assert not puede_abrir_la_consola(client)


def test_con_codigo_incorrecto_no_ingresa(client, cuenta):
    _, dispositivo, _ = cuenta
    incorrecto = "000000" if codigo_actual(dispositivo) != "000000" else "111111"
    respuesta = ingresar(client, "ana-consola", CLAVE, incorrecto)
    assert MENSAJE_ERROR in respuesta.content.decode()
    assert not puede_abrir_la_consola(client)
    assert eventos(TipoEvento.FALLO_SESION).get().detalle == {"causa": "codigo"}


def test_solo_usuario_y_clave_no_abren_la_consola(client, cuenta):
    """Una sesión autenticada sin el segundo factor verificado no abre ninguna página."""
    usuario, _, _ = cuenta
    client.force_login(usuario)
    assert client.get(reverse("admin:index")).status_code == 302


def test_mismo_mensaje_para_usuario_inexistente_y_clave_incorrecta(client, cuenta):
    _, dispositivo, _ = cuenta
    inexistente = ingresar(client, "nadie-ficticio", CLAVE, codigo_actual(dispositivo))
    clave_mala = ingresar(client, "ana-consola", "otra-clave-larga", codigo_actual(dispositivo))
    assert inexistente.status_code == clave_mala.status_code == 200
    assert inexistente.context["form"].errors == clave_mala.context["form"].errors
    assert MENSAJE_ERROR in inexistente.content.decode()


def test_cinco_fallos_bloquean_quince_minutos_aunque_luego_acierte(client, cuenta, monkeypatch):
    """Condición de término de la tarea 34 y prueba obligatoria de docs/seguridad.md."""
    usuario, dispositivo, _ = cuenta
    ahora = [1_000_000.0]
    monkeypatch.setattr(bloqueo, "_ahora", lambda: ahora[0])

    for _ in range(4):
        ingresar(client, "ana-consola", "clave-equivocada-1", codigo_actual(dispositivo))
    assert not eventos(TipoEvento.BLOQUEO_CUENTA).exists()

    ingresar(client, "ana-consola", "clave-equivocada-1", codigo_actual(dispositivo))
    bloqueo_registrado = eventos(TipoEvento.BLOQUEO_CUENTA).get()
    assert bloqueo_registrado.usuario == usuario
    assert bloqueo_registrado.detalle == {"minutos": 15}

    # La contraseña y el código correctos también se rechazan mientras dura el bloqueo.
    respuesta = ingresar(client, "ana-consola", CLAVE, codigo_actual(dispositivo))
    assert MENSAJE_ERROR in respuesta.content.decode()
    assert not puede_abrir_la_consola(client)
    ahora[0] += 15 * 60 - 1
    ingresar(client, "ana-consola", CLAVE, codigo_actual(dispositivo))
    assert not puede_abrir_la_consola(client)
    assert eventos(TipoEvento.FALLO_SESION).filter(detalle__causa="cuenta_bloqueada").count() == 2
    # Los intentos durante el bloqueo no lo alargan ni lo repiten.
    assert eventos(TipoEvento.BLOQUEO_CUENTA).count() == 1

    ahora[0] += 2
    ingresar(client, "ana-consola", CLAVE, codigo_actual(dispositivo))
    assert puede_abrir_la_consola(client)


def test_un_ingreso_correcto_reinicia_la_racha(client, cuenta):
    _, dispositivo, codigos = cuenta
    for _ in range(4):
        ingresar(client, "ana-consola", "clave-equivocada-1", "123456")
    ingresar(client, "ana-consola", CLAVE, codigos[0])
    assert puede_abrir_la_consola(client)
    client.post(reverse("admin:logout"))
    for _ in range(4):
        ingresar(client, "ana-consola", "clave-equivocada-1", "123456")
    assert not eventos(TipoEvento.BLOQUEO_CUENTA).exists()


def test_una_cuenta_inexistente_no_se_bloquea_ni_deja_contador(client):
    for _ in range(6):
        ingresar(client, "nadie-ficticio", CLAVE, "123456")
    assert not eventos(TipoEvento.BLOQUEO_CUENTA).exists()
    fallos = eventos(TipoEvento.FALLO_SESION)
    assert fallos.count() == 6
    assert all(evento.usuario is None for evento in fallos)


def test_los_fallos_no_guardan_lo_que_se_escribio(client, cuenta):
    ingresar(client, "nombre-tipeado-ficticio", "clave-tipeada-ficticia", "654321")
    evento = eventos(TipoEvento.FALLO_SESION).get()
    guardado = f"{evento.objeto} {evento.motivo} {evento.detalle}"
    for texto in ("nombre-tipeado-ficticio", "clave-tipeada-ficticia", "654321"):
        assert texto not in guardado


def test_una_cuenta_desactivada_no_ingresa(client, cuenta):
    usuario, dispositivo, _ = cuenta
    usuario.is_active = False
    usuario.save()
    ingresar(client, "ana-consola", CLAVE, codigo_actual(dispositivo))
    assert not puede_abrir_la_consola(client)


def test_un_codigo_de_recuperacion_sirve_una_sola_vez(client, cuenta):
    _, _, codigos = cuenta
    ingresar(client, "ana-consola", CLAVE, codigos[0].upper())
    assert puede_abrir_la_consola(client)
    assert eventos(TipoEvento.INICIO_SESION).get().detalle == {"factor": "recuperacion"}
    client.post(reverse("admin:logout"))

    ingresar(client, "ana-consola", CLAVE, codigos[0])
    assert not puede_abrir_la_consola(client)
    assert StaticToken.objects.count() == len(codigos) - 1


def test_cerrar_sesion_corta_el_acceso(client, cuenta):
    _, dispositivo, _ = cuenta
    ingresar(client, "ana-consola", CLAVE, codigo_actual(dispositivo))
    assert puede_abrir_la_consola(client)
    client.post(reverse("admin:logout"))
    assert not puede_abrir_la_consola(client)


def test_la_sesion_vence_a_los_30_minutos_sin_actividad(client, cuenta):
    assert settings.SESSION_COOKIE_AGE == 30 * 60
    assert settings.SESSION_SAVE_EVERY_REQUEST is True
    _, dispositivo, _ = cuenta
    ingresar(client, "ana-consola", CLAVE, codigo_actual(dispositivo))
    # Cada solicitud renueva el plazo: la cookie vuelve con 30 minutos.
    respuesta = client.get(reverse("admin:index"))
    cookie = respuesta.cookies[settings.SESSION_COOKIE_NAME]
    assert int(cookie["max-age"]) == 30 * 60
    assert cookie["httponly"]
    assert cookie["samesite"] == "Lax"


def test_no_hay_autoregistro_ni_recuperacion_de_clave(client):
    html = client.get(reverse("admin:login")).content.decode()
    assert 'name="otp_token"' in html
    for ruta in ("admin_password_reset", "registro", "signup", "register"):
        with pytest.raises(NoReverseMatch):
            reverse(ruta)
    assert client.get(reverse("admin:auth_user_add")).status_code == 302


def test_el_ingreso_tiene_limite_por_ip(client):
    for _ in range(20):
        assert ingresar(client, "nadie-ficticio", CLAVE, "123456").status_code == 200
    assert ingresar(client, "nadie-ficticio", CLAVE, "123456").status_code == 429
    # Ver la página de ingreso no cuenta para el límite.
    assert client.get(reverse("admin:login")).status_code == 200


# --- Cuentas desde la terminal --------------------------------------------------

def test_crear_cuenta_interna_entrega_autenticador_y_codigos(monkeypatch, capsys):
    monkeypatch.setattr("getpass.getpass", lambda *_: CLAVE)
    call_command("crear_cuenta_interna", "beto-consola", rol="administrador")
    salida = capsys.readouterr().out
    cuenta = get_user_model().objects.get(username="beto-consola")
    assert cuenta.is_staff and not cuenta.is_superuser
    assert list(cuenta.groups.values_list("name", flat=True)) == ["Administrador"]
    assert "otpauth://totp/" in salida
    codigos = StaticToken.objects.filter(device__user=cuenta).values_list("token", flat=True)
    assert len(codigos) == 10
    assert all(codigo in salida for codigo in codigos)
    evento = eventos(TipoEvento.CAMBIO_CUENTA).get()
    assert evento.objeto == f"auth.User:{cuenta.pk}"
    assert evento.detalle == {"rol": "Administrador"}


def test_crear_cuenta_interna_rechaza_una_clave_corta(monkeypatch):
    monkeypatch.setattr("getpass.getpass", lambda *_: "corta-123")
    with pytest.raises(CommandError):
        call_command("crear_cuenta_interna", "beto-consola", rol="analista")
    assert not get_user_model().objects.filter(username="beto-consola").exists()


def test_reiniciar_totp_reemplaza_el_autenticador_y_los_codigos(cuenta, capsys):
    usuario, anterior, codigos = cuenta
    call_command("reiniciar_totp", "ana-consola")
    assert not TOTPDevice.objects.filter(pk=anterior.pk).exists()
    assert TOTPDevice.objects.filter(user=usuario).count() == 1
    assert StaticDevice.objects.filter(user=usuario).count() == 1
    nuevos = set(StaticToken.objects.filter(device__user=usuario).values_list("token", flat=True))
    assert len(nuevos) == 10
    assert "otpauth://totp/" in capsys.readouterr().out
    reinicio = eventos(TipoEvento.CAMBIO_CUENTA).filter(objeto=f"auth.User:{usuario.pk}").first()
    assert reinicio.motivo == "Segundo factor reiniciado desde la terminal"


def test_reiniciar_totp_de_una_cuenta_que_no_existe_falla():
    with pytest.raises(CommandError):
        call_command("reiniciar_totp", "nadie-ficticio")
