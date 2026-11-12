
"""Pruebas del catálogo de marcas."""
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django_otp.oath import totp

from catalogo.models import DominioOficial, HistorialDominio, HistorialMarca, Marca
from catalogo.servicios import (
    actualizar_marca,
    aprobar_dominio_oficial,
    restaurar_marca,
    solicitar_dominio_oficial,
    solicitar_reemplazo_dominio,
)
from catalogo.totp import confirmar_registro_totp, iniciar_registro_totp
from core.models import EventoAuditoria, TipoEvento


@pytest.fixture
def administrador(db):
    usuario_modelo = get_user_model()
    return usuario_modelo.objects.create_user(
        username="admin_catalogo",
        password="ClavePruebaSegura123!",
        is_staff=True,
    )


@pytest.fixture
def usuario_normal(db):
    usuario_modelo = get_user_model()
    return usuario_modelo.objects.create_user(
        username="usuario_catalogo",
        password="ClavePruebaSegura123!",
    )


@pytest.fixture
def marca(db):
    return Marca.objects.create(
        nombre="Marca de prueba",
        tipo=Marca.Tipo.OTRO,
        activa=True,
    )


@pytest.mark.django_db
def test_actualizar_marca_guarda_historial(marca, administrador):
    actualizar_marca(
        marca_id=marca.pk,
        nombre="Marca actualizada",
        tipo=Marca.Tipo.BILLETERA,
        activa=True,
        usuario=administrador,
        motivo="Actualización de prueba",
    )

    marca.refresh_from_db()

    assert marca.nombre == "Marca actualizada"
    assert marca.tipo == Marca.Tipo.BILLETERA

    historial = HistorialMarca.objects.get(marca=marca)

    assert historial.nombre == "Marca de prueba"
    assert historial.tipo == Marca.Tipo.OTRO
    assert historial.usuario == administrador
    assert historial.accion == HistorialMarca.Accion.MODIFICACION


@pytest.mark.django_db
def test_actualizar_marca_registra_auditoria(marca, administrador):
    actualizar_marca(
        marca_id=marca.pk,
        nombre="Marca actualizada",
        tipo=Marca.Tipo.OTRO,
        activa=True,
        usuario=administrador,
        motivo="Cambio autorizado",
    )

    evento = EventoAuditoria.objects.get(
        tipo=TipoEvento.CAMBIO_CATALOGO,
        objeto=f"catalogo.Marca:{marca.pk}",
    )

    assert evento.usuario == administrador
    assert evento.detalle["accion"] == "modificacion"


@pytest.mark.django_db
def test_usuario_normal_no_puede_actualizar(marca, usuario_normal):
    with pytest.raises(PermissionError):
        actualizar_marca(
            marca_id=marca.pk,
            nombre="Cambio no autorizado",
            tipo=Marca.Tipo.OTRO,
            activa=True,
            usuario=usuario_normal,
            motivo="Intento de modificación",
        )

    marca.refresh_from_db()

    assert marca.nombre == "Marca de prueba"
    assert HistorialMarca.objects.count() == 0


@pytest.mark.django_db
def test_error_auditoria_revierte_cambios(marca, administrador):
    with patch(
        "catalogo.servicios.registrar_evento",
        side_effect=ValueError("Error simulado de auditoría"),
    ):
        with pytest.raises(ValueError, match="Error simulado"):
            actualizar_marca(
                marca_id=marca.pk,
                nombre="Cambio fallido",
                tipo=Marca.Tipo.BILLETERA,
                activa=False,
                usuario=administrador,
                motivo="Prueba de transacción",
            )

    marca.refresh_from_db()

    assert marca.nombre == "Marca de prueba"
    assert marca.activa is True
    assert HistorialMarca.objects.count() == 0
    assert EventoAuditoria.objects.filter(
        tipo=TipoEvento.CAMBIO_CATALOGO,
    ).count() == 0





"Pruebas de restauración de marcas desde el historial."

@pytest.mark.django_db
def test_restaurar_marca_recupera_version_anterior(marca, administrador):
    actualizar_marca(
        marca_id=marca.pk,
        nombre="Marca actualizada",
        tipo=Marca.Tipo.BILLETERA,
        activa=False,
        usuario=administrador,
        motivo="Cambio de prueba",
    )

    version_anterior = HistorialMarca.objects.get(
        marca=marca,
        accion=HistorialMarca.Accion.MODIFICACION,
    )

    restaurar_marca(
        historial_id=version_anterior.pk,
        usuario=administrador,
        motivo="Restaurar datos originales",
    )

    marca.refresh_from_db()

    assert marca.nombre == "Marca de prueba"
    assert marca.tipo == Marca.Tipo.OTRO
    assert marca.activa is True

    assert HistorialMarca.objects.filter(marca=marca).count() == 2


@pytest.mark.django_db
def test_restaurar_marca_registra_auditoria(marca, administrador):
    actualizar_marca(
        marca_id=marca.pk,
        nombre="Marca modificada",
        tipo=Marca.Tipo.OTRO,
        activa=True,
        usuario=administrador,
        motivo="Modificación inicial",
    )

    version_anterior = HistorialMarca.objects.get(marca=marca)

    restaurar_marca(
        historial_id=version_anterior.pk,
        usuario=administrador,
        motivo="Corrección de datos",
    )

    assert EventoAuditoria.objects.filter(
        tipo=TipoEvento.CAMBIO_CATALOGO,
        detalle__accion="restauracion",
    ).count() == 1


@pytest.mark.django_db
def test_error_auditoria_revierte_restauracion(marca, administrador):
    actualizar_marca(
        marca_id=marca.pk,
        nombre="Marca modificada",
        tipo=Marca.Tipo.OTRO,
        activa=True,
        usuario=administrador,
        motivo="Cambio inicial",
    )

    version_anterior = HistorialMarca.objects.get(marca=marca)

    with patch(
        "catalogo.servicios.registrar_evento",
        side_effect=ValueError("Error simulado"),
    ):
        with pytest.raises(ValueError, match="Error simulado"):
            restaurar_marca(
                historial_id=version_anterior.pk,
                usuario=administrador,
                motivo="Intento de restauración",
            )

    marca.refresh_from_db()

    assert marca.nombre == "Marca modificada"
    assert HistorialMarca.objects.filter(marca=marca).count() == 1

    assert EventoAuditoria.objects.filter(
        tipo=TipoEvento.CAMBIO_CATALOGO,
    ).count() == 1



"""Prueba para verificar que una solicitud de dominio oficial queda en estado pendiente."""

@pytest.mark.django_db
def test_solicitud_dominio_queda_pendiente(marca, administrador):
    solicitud = solicitar_dominio_oficial(
        marca_id=marca.pk,
        dominio="EJEMPLO.COM.PE",
        fuente_verificacion="https://ejemplo.com.pe",
        usuario=administrador,
        motivo="Registro inicial de prueba",
    )

    assert solicitud.dominio == "ejemplo.com.pe"
    assert solicitud.estado == DominioOficial.Estado.PENDIENTE
    assert solicitud.fecha_verificacion is None
    assert solicitud.solicitado_por == administrador
    assert solicitud.aprobado_por is None
    assert solicitud.aprobado_en is None

    evento = EventoAuditoria.objects.get(
        tipo=TipoEvento.CAMBIO_CATALOGO,
        objeto=f"catalogo.DominioOficial:{solicitud.pk}",
    )

    assert evento.usuario == administrador
    assert evento.detalle["accion"] == "solicitud"


@pytest.mark.django_db
def test_solicitud_dominio_duplicado(marca, administrador):
    datos = {
        "marca_id": marca.pk,
        "dominio": "ejemplo.com.pe",
        "fuente_verificacion": "https://ejemplo.com.pe",
        "usuario": administrador,
        "motivo": "Registro de prueba",
    }

    solicitar_dominio_oficial(**datos)

    from django.core.exceptions import ValidationError

    with pytest.raises(ValidationError):
        solicitar_dominio_oficial(**datos)

    assert DominioOficial.objects.count() == 1


@pytest.mark.django_db
def test_usuario_normal_no_puede_solicitar_dominio(
    marca, usuario_normal
):
    with pytest.raises(PermissionError):
        solicitar_dominio_oficial(
            marca_id=marca.pk,
            dominio="ejemplo.com.pe",
            fuente_verificacion="https://ejemplo.com.pe",
            usuario=usuario_normal,
            motivo="Intento sin autorización",
        )

    assert DominioOficial.objects.count() == 0


@pytest.mark.django_db
def test_error_auditoria_revierte_solicitud(marca, administrador):
    with patch(
        "catalogo.servicios.registrar_evento",
        side_effect=ValueError("Error simulado de auditoría"),
    ):
        with pytest.raises(ValueError, match="Error simulado"):
            solicitar_dominio_oficial(
                marca_id=marca.pk,
                dominio="ejemplo.com.pe",
                fuente_verificacion="https://ejemplo.com.pe",
                usuario=administrador,
                motivo="Prueba de transacción",
            )

    assert DominioOficial.objects.count() == 0
    assert EventoAuditoria.objects.filter(
        tipo=TipoEvento.CAMBIO_CATALOGO,
    ).count() == 0




@pytest.mark.django_db
def test_segundo_administrador_aprueba_con_totp(marca, administrador):
    from django.contrib.auth import get_user_model

    segundo_admin = get_user_model().objects.create_user(
        username="segundo_admin",
        password="ClaveDePrueba123!",
        is_staff=True,
    )

    solicitud = solicitar_dominio_oficial(
        marca_id=marca.pk,
        dominio="ejemplo.com.pe",
        fuente_verificacion="https://ejemplo.com.pe",
        usuario=administrador,
        motivo="Solicitud de prueba",
    )

    dispositivo = iniciar_registro_totp(usuario=segundo_admin)
    codigo = str(
        totp(
            dispositivo.bin_key,
            step=dispositivo.step,
            digits=dispositivo.digits,
        )
    ).zfill(6)

    confirmar_registro_totp(
        usuario=segundo_admin,
        dispositivo_id=dispositivo.pk,
        codigo=codigo,
    )

    # La confirmación consume el código actual.
    # Permitimos el siguiente intervalo TOTP solo dentro de esta prueba.
    dispositivo.refresh_from_db()
    dispositivo.t0 -= dispositivo.step
    dispositivo.save(update_fields=["t0"])

    codigo_aprobacion = str(
        totp(
            dispositivo.bin_key,
            step=dispositivo.step,
            t0=dispositivo.t0,
            digits=dispositivo.digits,
        )
    ).zfill(6)

    aprobado = aprobar_dominio_oficial(
        dominio_id=solicitud.pk,
        usuario=segundo_admin,
        codigo=codigo_aprobacion,
        motivo="Fuente verificada para prueba",
    )

    assert aprobado.estado == DominioOficial.Estado.APROBADO
    assert aprobado.aprobado_por == segundo_admin
    assert aprobado.aprobado_en is not None


@pytest.mark.django_db
def test_administrador_no_aprueba_su_solicitud(marca, administrador):
    solicitud = solicitar_dominio_oficial(
        marca_id=marca.pk,
        dominio="ejemplo.com.pe",
        fuente_verificacion="https://ejemplo.com.pe",
        usuario=administrador,
        motivo="Solicitud de prueba",
    )

    with pytest.raises(PermissionError, match="propia solicitud"):
        aprobar_dominio_oficial(
            dominio_id=solicitud.pk,
            usuario=administrador,
            codigo="123456",
            motivo="Intento de autoaprobación",
        )

    solicitud.refresh_from_db()
    assert solicitud.estado == DominioOficial.Estado.PENDIENTE





@pytest.mark.django_db
def test_codigo_totp_utilizado_no_puede_aprobar(marca, administrador):
    from django.contrib.auth import get_user_model

    segundo_admin = get_user_model().objects.create_user(
        username="admin_reutilizacion",
        password="ClaveDePrueba123!",
        is_staff=True,
    )

    solicitud = solicitar_dominio_oficial(
        marca_id=marca.pk,
        dominio="ejemplo.com.pe",
        fuente_verificacion="https://ejemplo.com.pe",
        usuario=administrador,
        motivo="Solicitud de prueba",
    )

    dispositivo = iniciar_registro_totp(usuario=segundo_admin)

    codigo = str(
        totp(
            dispositivo.bin_key,
            step=dispositivo.step,
            digits=dispositivo.digits,
        )
    ).zfill(6)

    confirmar_registro_totp(
        usuario=segundo_admin,
        dispositivo_id=dispositivo.pk,
        codigo=codigo,
    )

    "El código utilizado para confirmar el dispositivo no puede reutilizarse."
    with pytest.raises(ValidationError, match="inválido o ya utilizado"):
        aprobar_dominio_oficial(
            dominio_id=solicitud.pk,
            usuario=segundo_admin,
            codigo=codigo,
            motivo="Intento de reutilización",
        )

    solicitud.refresh_from_db()
    assert solicitud.estado == DominioOficial.Estado.PENDIENTE
    assert solicitud.aprobado_por is None
    assert solicitud.aprobado_en is None





@pytest.mark.django_db
def test_error_auditoria_revierte_aprobacion(marca, administrador, monkeypatch):
    from django.contrib.auth import get_user_model

    segundo_admin = get_user_model().objects.create_user(
        username="admin_rollback",
        password="ClaveDePrueba123!",
        is_staff=True,
    )

    solicitud = solicitar_dominio_oficial(
        marca_id=marca.pk,
        dominio="ejemplo.com.pe",
        fuente_verificacion="https://ejemplo.com.pe",
        usuario=administrador,
        motivo="Solicitud de prueba",
    )

    dispositivo = iniciar_registro_totp(usuario=segundo_admin)
    codigo = str(
        totp(
            dispositivo.bin_key,
            step=dispositivo.step,
            digits=dispositivo.digits,
        )
    ).zfill(6)

    confirmar_registro_totp(
        usuario=segundo_admin,
        dispositivo_id=dispositivo.pk,
        codigo=codigo,
    )

    # Simula un nuevo intervalo TOTP dentro de la prueba.
    dispositivo.refresh_from_db()
    dispositivo.t0 -= dispositivo.step
    dispositivo.save(update_fields=["t0"])

    codigo_aprobacion = str(
        totp(
            dispositivo.bin_key,
            step=dispositivo.step,
            t0=dispositivo.t0,
            digits=dispositivo.digits,
        )
    ).zfill(6)

    def auditoria_fallida(*args, **kwargs):
        raise RuntimeError("Fallo simulado de auditoría")

    monkeypatch.setattr(
        "catalogo.servicios.registrar_evento",
        auditoria_fallida,
    )

    with pytest.raises(RuntimeError, match="Fallo simulado"):
        aprobar_dominio_oficial(
            dominio_id=solicitud.pk,
            usuario=segundo_admin,
            codigo=codigo_aprobacion,
            motivo="Aprobación de prueba",
        )

    solicitud.refresh_from_db()

    assert solicitud.estado == DominioOficial.Estado.PENDIENTE
    assert solicitud.aprobado_por is None
    assert solicitud.aprobado_en is None
    assert solicitud.fecha_verificacion is None
    assert not HistorialDominio.objects.filter(
        dominio_oficial=solicitud
    ).exists()




@pytest.mark.django_db(transaction=True)
def test_codigo_incorrecto_conserva_intento_fallido():
    from django.contrib.auth import get_user_model
    from django_otp.plugins.otp_totp.models import TOTPDevice

    from catalogo.models import DominioOficial, Marca

    User = get_user_model()

    solicitante = User.objects.create_user(
        username="solicitante_throttle",
        password="ClaveDePrueba123!",
        is_staff=True,
    )

    aprobador = User.objects.create_user(
        username="aprobador_throttle",
        password="ClaveDePrueba123!",
        is_staff=True,
    )

    marca = Marca.objects.create(
        nombre="Marca de prueba TOTP",
        tipo=Marca.Tipo.FINANCIERA,
    )

    solicitud = solicitar_dominio_oficial(
        marca_id=marca.pk,
        dominio="ejemplo.com.pe",
        fuente_verificacion="https://ejemplo.com.pe",
        usuario=solicitante,
        motivo="Solicitud para probar intentos fallidos",
    )

    dispositivo = TOTPDevice.objects.create(
        user=aprobador,
        name="Autenticador de prueba",
        confirmed=True,
    )

    codigo_correcto = str(
        totp(
            dispositivo.bin_key,
            step=dispositivo.step,
            digits=dispositivo.digits,
        )
    ).zfill(6)

    codigo_incorrecto = (
        "000000" if codigo_correcto != "000000" else "999999"
    )

    with pytest.raises(ValidationError, match="inválido"):
        aprobar_dominio_oficial(
            dominio_id=solicitud.pk,
            usuario=aprobador,
            codigo=codigo_incorrecto,
            motivo="Prueba de código incorrecto",
        )

    dispositivo.refresh_from_db()
    solicitud.refresh_from_db()

    assert dispositivo.throttling_failure_count == 1
    assert solicitud.estado == DominioOficial.Estado.PENDIENTE




@pytest.mark.django_db
def test_aprobacion_guarda_historial(marca, administrador):
    from django.contrib.auth import get_user_model

    segundo_admin = get_user_model().objects.create_user(
        username="admin_historial",
        password="ClaveDePrueba123!",
        is_staff=True,
    )

    solicitud = solicitar_dominio_oficial(
        marca_id=marca.pk,
        dominio="ejemplo.com.pe",
        fuente_verificacion="https://ejemplo.com.pe",
        usuario=administrador,
        motivo="Solicitud de prueba",
    )

    dispositivo = iniciar_registro_totp(usuario=segundo_admin)

    codigo = str(
        totp(
            dispositivo.bin_key,
            step=dispositivo.step,
            digits=dispositivo.digits,
        )
    ).zfill(6)

    confirmar_registro_totp(
        usuario=segundo_admin,
        dispositivo_id=dispositivo.pk,
        codigo=codigo,
    )

    # Simulamos un intervalo TOTP posterior solo en la prueba.
    dispositivo.refresh_from_db()
    dispositivo.t0 -= dispositivo.step
    dispositivo.save(update_fields=["t0"])

    codigo_aprobacion = str(
        totp(
            dispositivo.bin_key,
            step=dispositivo.step,
            t0=dispositivo.t0,
            digits=dispositivo.digits,
        )
    ).zfill(6)

    aprobar_dominio_oficial(
        dominio_id=solicitud.pk,
        usuario=segundo_admin,
        codigo=codigo_aprobacion,
        motivo="Fuente oficial revisada",
    )

    historial = HistorialDominio.objects.get(
        dominio_oficial=solicitud,
        accion=HistorialDominio.Accion.APROBACION,
    )

    assert historial.estado == DominioOficial.Estado.PENDIENTE
    assert historial.dominio == "ejemplo.com.pe"
    assert historial.usuario == segundo_admin
    assert historial.motivo == "Fuente oficial revisada"
    assert historial.aprobado_por is None
    assert historial.aprobado_en is None





@pytest.mark.django_db
def test_reemplazo_mantiene_dominio_anterior_aprobado(
    marca, administrador
):
    anterior = DominioOficial.objects.create(
        marca=marca,
        dominio="anterior-ejemplo.com.pe",
        fuente_verificacion="https://anterior-ejemplo.com.pe",
        estado=DominioOficial.Estado.APROBADO,
        solicitado_por=administrador,
    )

    solicitud = solicitar_reemplazo_dominio(
        dominio_anterior_id=anterior.pk,
        dominio_nuevo="nuevo-ejemplo.com.pe",
        fuente_verificacion="https://nuevo-ejemplo.com.pe",
        usuario=administrador,
        motivo="Cambio de dominio de prueba",
    )

    anterior.refresh_from_db()

    assert anterior.estado == DominioOficial.Estado.APROBADO
    assert solicitud.estado == DominioOficial.Estado.PENDIENTE
    assert solicitud.reemplaza_a_id == anterior.pk
    assert solicitud.marca_id == anterior.marca_id
    assert solicitud.aprobado_por is None
    assert solicitud.fecha_verificacion is None




@pytest.mark.django_db
def test_no_permite_dos_reemplazos_pendientes(marca, administrador):
    anterior = DominioOficial.objects.create(
        marca=marca,
        dominio="anterior-ejemplo.com.pe",
        fuente_verificacion="https://anterior-ejemplo.com.pe",
        estado=DominioOficial.Estado.APROBADO,
        solicitado_por=administrador,
    )

    primera = solicitar_reemplazo_dominio(
        dominio_anterior_id=anterior.pk,
        dominio_nuevo="nuevo-uno-ejemplo.com.pe",
        fuente_verificacion="https://nuevo-uno-ejemplo.com.pe",
        usuario=administrador,
        motivo="Primera solicitud",
    )

    with pytest.raises(
        ValidationError,
        match="Ya existe una solicitud pendiente",
    ):
        solicitar_reemplazo_dominio(
            dominio_anterior_id=anterior.pk,
            dominio_nuevo="nuevo-dos-ejemplo.com.pe",
            fuente_verificacion="https://nuevo-dos-ejemplo.com.pe",
            usuario=administrador,
            motivo="Segunda solicitud",
        )

    assert primera.estado == DominioOficial.Estado.PENDIENTE
    assert DominioOficial.objects.filter(
        reemplaza_a=anterior,
        estado=DominioOficial.Estado.PENDIENTE,
    ).count() == 1




@pytest.mark.django_db
def test_aprobar_reemplazo_retira_dominio_anterior(
    marca, administrador
):
    from django.contrib.auth import get_user_model
    from django_otp.oath import totp
    from django_otp.plugins.otp_totp.models import TOTPDevice

    segundo_admin = get_user_model().objects.create_user(
        username="admin_reemplazo",
        password="ClaveDePrueba123!",
        is_staff=True,
    )

    anterior = DominioOficial.objects.create(
        marca=marca,
        dominio="anterior-ejemplo.com.pe",
        fuente_verificacion="https://anterior-ejemplo.com.pe",
        estado=DominioOficial.Estado.APROBADO,
        solicitado_por=administrador,
    )

    solicitud = solicitar_reemplazo_dominio(
        dominio_anterior_id=anterior.pk,
        dominio_nuevo="nuevo-ejemplo.com.pe",
        fuente_verificacion="https://nuevo-ejemplo.com.pe",
        usuario=administrador,
        motivo="Migración de dominio de prueba",
    )

    dispositivo = TOTPDevice.objects.create(
        user=segundo_admin,
        name="Autenticador de prueba",
        confirmed=True,
    )

    codigo = str(
        totp(
            dispositivo.bin_key,
            step=dispositivo.step,
            digits=dispositivo.digits,
        )
    ).zfill(6)

    aprobar_dominio_oficial(
        dominio_id=solicitud.pk,
        usuario=segundo_admin,
        codigo=codigo,
        motivo="Verificación del nuevo dominio",
    )

    anterior.refresh_from_db()
    solicitud.refresh_from_db()

    assert anterior.estado == DominioOficial.Estado.RETIRADO
    assert solicitud.estado == DominioOficial.Estado.APROBADO
    assert solicitud.aprobado_por == segundo_admin

    assert HistorialDominio.objects.filter(
        dominio_oficial=anterior,
        estado=DominioOficial.Estado.APROBADO,
    ).exists()

    assert HistorialDominio.objects.filter(
        dominio_oficial=solicitud,
        estado=DominioOficial.Estado.PENDIENTE,
    ).exists()





@pytest.mark.django_db
def test_error_auditoria_revierte_reemplazo(
    marca, administrador, monkeypatch
):
    from django.contrib.auth import get_user_model
    from django_otp.oath import totp
    from django_otp.plugins.otp_totp.models import TOTPDevice

    segundo_admin = get_user_model().objects.create_user(
        username="admin_rollback_reemplazo",
        password="ClaveDePrueba123!",
        is_staff=True,
    )

    anterior = DominioOficial.objects.create(
        marca=marca,
        dominio="anterior-ejemplo.com.pe",
        fuente_verificacion="https://anterior-ejemplo.com.pe",
        estado=DominioOficial.Estado.APROBADO,
        solicitado_por=administrador,
    )

    solicitud = solicitar_reemplazo_dominio(
        dominio_anterior_id=anterior.pk,
        dominio_nuevo="nuevo-ejemplo.com.pe",
        fuente_verificacion="https://nuevo-ejemplo.com.pe",
        usuario=administrador,
        motivo="Solicitud de reemplazo de prueba",
    )

    dispositivo = TOTPDevice.objects.create(
        user=segundo_admin,
        name="Autenticador de prueba",
        confirmed=True,
    )

    codigo = str(
        totp(
            dispositivo.bin_key,
            step=dispositivo.step,
            digits=dispositivo.digits,
        )
    ).zfill(6)

    def simular_error(*args, **kwargs):
        raise RuntimeError("Error simulado de auditoría")

    monkeypatch.setattr(
        "catalogo.servicios.registrar_evento",
        simular_error,
    )

    with pytest.raises(RuntimeError, match="Error simulado"):
        aprobar_dominio_oficial(
            dominio_id=solicitud.pk,
            usuario=segundo_admin,
            codigo=codigo,
            motivo="Aprobación de reemplazo",
        )

    anterior.refresh_from_db()
    solicitud.refresh_from_db()

    assert anterior.estado == DominioOficial.Estado.APROBADO
    assert solicitud.estado == DominioOficial.Estado.PENDIENTE
    assert solicitud.aprobado_por is None

    assert not HistorialDominio.objects.filter(
        dominio_oficial__in=[anterior, solicitud]
    ).exists()
