"""Cuentas internas de la consola: alta y segundo factor.

Render no tiene consola, así que las cuentas se crean desde local con los comandos
crear_cuenta_interna y reiniciar_totp, apuntando a la base del ambiente con una
DATABASE_URL que nunca se guarda en el repo. Cada cambio queda en la auditoría.
"""
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.db import transaction
from django_otp.plugins.otp_static.models import StaticDevice, StaticToken
from django_otp.plugins.otp_totp.models import TOTPDevice

from .auditoria import registrar_evento
from .models import TipoEvento
from .roles import ROLES, sincronizar_roles

CANTIDAD_CODIGOS = 10


def _objeto(cuenta):
    return f"auth.User:{cuenta.pk}"


@transaction.atomic
def preparar_segundo_factor(cuenta):
    """Reemplaza el autenticador y los códigos de recuperación de la cuenta.

    Borra los anteriores, así que una sesión abierta con ellos pierde el acceso a la
    consola. Devuelve el dispositivo TOTP nuevo y los códigos en claro, que se muestran
    una sola vez: en la base solo quedan hasta que se usan.
    """
    TOTPDevice.objects.filter(user=cuenta).delete()
    StaticDevice.objects.filter(user=cuenta).delete()
    totp = TOTPDevice.objects.create(user=cuenta, name="Autenticador", confirmed=True)
    estatico = StaticDevice.objects.create(
        user=cuenta, name="Códigos de recuperación", confirmed=True,
    )
    codigos = []
    while len(codigos) < CANTIDAD_CODIGOS:
        codigo = StaticToken.random_token()
        if codigo not in codigos:
            codigos.append(codigo)
    StaticToken.objects.bulk_create(StaticToken(device=estatico, token=c) for c in codigos)
    return totp, codigos


@transaction.atomic
def crear_cuenta_interna(nombre, clave, rol):
    """Crea una cuenta de la consola con su rol, su autenticador y sus códigos.

    La cuenta nunca es superusuario: lo que puede hacer sale solo de su rol. La clave
    pasa por los validadores de AUTH_PASSWORD_VALIDATORS (12 caracteres o más).
    """
    if rol not in ROLES:
        raise ValueError(f"rol desconocido: {rol!r}")
    modelo = get_user_model()
    if modelo._default_manager.filter(username=nombre).exists():
        raise ValueError("ya existe una cuenta con ese nombre")
    cuenta = modelo(username=nombre, is_staff=True, is_superuser=False)
    validate_password(clave, cuenta)
    cuenta.set_password(clave)
    cuenta.save()
    grupos = sincronizar_roles()
    cuenta.groups.set([grupos[rol]])
    totp, codigos = preparar_segundo_factor(cuenta)
    registrar_evento(
        TipoEvento.CAMBIO_CUENTA, objeto=_objeto(cuenta),
        motivo="Cuenta interna creada desde la terminal", detalle={"rol": rol},
    )
    return cuenta, totp, codigos


def reiniciar_segundo_factor(cuenta):
    """Entrega un autenticador y códigos nuevos a una cuenta que perdió los suyos."""
    totp, codigos = preparar_segundo_factor(cuenta)
    registrar_evento(
        TipoEvento.CAMBIO_CUENTA, objeto=_objeto(cuenta),
        motivo="Segundo factor reiniciado desde la terminal",
    )
    return totp, codigos
