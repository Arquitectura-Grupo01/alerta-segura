
import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django_otp.oath import totp
from django_otp.plugins.otp_totp.models import TOTPDevice

from catalogo.totp import confirmar_registro_totp, iniciar_registro_totp


@pytest.fixture
def administrador(db):
    return get_user_model().objects.create_user(
        username="admin_totp",
        password="ClaveSegura123!",
        is_staff=True,
    )


@pytest.fixture
def usuario_normal(db):
    return get_user_model().objects.create_user(
        username="usuario_totp",
        password="ClaveSegura123!",
    )


@pytest.mark.django_db
def test_administrador_puede_iniciar_registro(administrador):
    dispositivo = iniciar_registro_totp(usuario=administrador)

    assert dispositivo.user == administrador
    assert dispositivo.confirmed is False
    assert TOTPDevice.objects.count() == 1


@pytest.mark.django_db
def test_usuario_normal_no_puede_registrar(usuario_normal):
    with pytest.raises(PermissionError):
        iniciar_registro_totp(usuario=usuario_normal)

    assert TOTPDevice.objects.count() == 0


@pytest.mark.django_db(transaction=True)
def test_codigo_valido_confirma_dispositivo(administrador):
    dispositivo = iniciar_registro_totp(usuario=administrador)

    codigo = str(
        totp(dispositivo.bin_key, step=dispositivo.step, digits=dispositivo.digits)
    ).zfill(6)

    confirmado = confirmar_registro_totp(
        usuario=administrador,
        dispositivo_id=dispositivo.pk,
        codigo=codigo,
    )

    assert confirmado.confirmed is True
    dispositivo.refresh_from_db()
    assert dispositivo.confirmed is True


@pytest.mark.django_db(transaction=True)
def test_codigo_incorrecto_no_confirma(administrador):
    dispositivo = iniciar_registro_totp(usuario=administrador)

    codigo_valido = str(
        totp(dispositivo.bin_key, step=dispositivo.step, digits=dispositivo.digits)
    ).zfill(6)
    codigo_incorrecto = (
        "000000" if codigo_valido != "000000" else "999999"
    )

    with pytest.raises(ValidationError):
        confirmar_registro_totp(
            usuario=administrador,
            dispositivo_id=dispositivo.pk,
            codigo=codigo_incorrecto,
        )

    dispositivo.refresh_from_db()
    assert dispositivo.confirmed is False


"administra que un usuario normal no pueda confirmar un dispositivo TOTP."

@pytest.mark.django_db
def test_no_permite_dispositivos_duplicados(administrador):
    iniciar_registro_totp(usuario=administrador)

    with pytest.raises(ValidationError):
        iniciar_registro_totp(usuario=administrador)

    assert TOTPDevice.objects.filter(user=administrador).count() == 1




@pytest.mark.django_db(transaction=True)
def test_totp_registro_conserva_intento_fallido():
    from django.contrib.auth import get_user_model
    from django.core.exceptions import ValidationError
    from django_otp.plugins.otp_totp.models import TOTPDevice

    from catalogo.totp import confirmar_registro_totp

    usuario = get_user_model().objects.create_user(
        username="admin_totp_fallido",
        password="ClaveDePrueba123!",
        is_staff=True,
    )

    dispositivo = TOTPDevice.objects.create(
        user=usuario,
        name="Autenticador de prueba",
        confirmed=False,
    )

    with pytest.raises(ValidationError):
        confirmar_registro_totp(
            usuario=usuario,
            dispositivo_id=dispositivo.pk,
            codigo="000000",
        )

    dispositivo.refresh_from_db()

    assert dispositivo.confirmed is False
    assert dispositivo.throttling_failure_count == 1


@pytest.mark.django_db(transaction=True)
def test_totp_rechaza_transaccion_externa(administrador):
    from django.db import transaction

    dispositivo = iniciar_registro_totp(usuario=administrador)

    codigo = str(
        totp(
            dispositivo.bin_key,
            step=dispositivo.step,
            digits=dispositivo.digits,
        )
    ).zfill(6)

    with transaction.atomic():
        with pytest.raises(RuntimeError, match="transacción externa"):
            confirmar_registro_totp(
                usuario=administrador,
                dispositivo_id=dispositivo.pk,
                codigo=codigo,
            )

    dispositivo.refresh_from_db()

    assert dispositivo.confirmed is False
    assert dispositivo.last_t == -1
