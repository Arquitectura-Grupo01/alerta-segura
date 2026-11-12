from django.core.exceptions import ValidationError
from django.db import transaction
from django_otp.plugins.otp_totp.models import TOTPDevice


def iniciar_registro_totp(*, usuario):
    """Crea un dispositivo TOTP pendiente de confirmación."""

    if (
        usuario is None
        or not usuario.is_authenticated
        or not usuario.is_active
        or not usuario.is_staff
    ):
        raise PermissionError("Se requiere un administrador activo.")

    if TOTPDevice.objects.filter(user=usuario).exists():
        raise ValidationError("El administrador ya tiene un dispositivo TOTP registrado.")

    dispositivo = TOTPDevice.objects.create(
        user=usuario,
        name="Autenticador principal",
        confirmed=False,
    )

    return dispositivo


"""Confirma un dispositivo TOTP con un código válido."""


def confirmar_registro_totp(*, usuario, dispositivo_id, codigo):
    """Confirma un dispositivo TOTP con un código válido."""

    if (
        usuario is None
        or not usuario.is_authenticated
        or not usuario.is_active
        or not usuario.is_staff
    ):
        raise PermissionError("Se requiere un administrador activo.")

    if not isinstance(codigo, str) or not (
        len(codigo) == 6 and codigo.isascii() and codigo.isdigit()
    ):
        raise ValidationError("El código TOTP debe contener seis dígitos.")

    with transaction.atomic():
        dispositivo = TOTPDevice.objects.select_for_update().get(
            pk=dispositivo_id,
            user=usuario,
            confirmed=False,
        )

        codigo_valido = dispositivo.verify_token(codigo)

        if codigo_valido:
            dispositivo.confirmed = True
            dispositivo.save(update_fields=["confirmed"])

    if not codigo_valido:
        raise ValidationError("Código TOTP inválido o vencido.")

    return dispositivo
