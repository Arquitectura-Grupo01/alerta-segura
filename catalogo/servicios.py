"""Servicios para modificar el catálogo de manera auditada."""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django_otp.plugins.otp_totp.models import TOTPDevice

from core.auditoria import registrar_evento
from core.models import TipoEvento

from .models import DominioOficial, HistorialDominio, HistorialMarca, Marca


@transaction.atomic
def actualizar_marca(*, marca_id, nombre, tipo, activa, usuario, motivo):
    """Actualiza una marca y conserva su versión anterior."""

    if usuario is None or not usuario.is_authenticated or not usuario.is_staff:
        raise PermissionError("Se requiere un administrador autenticado.")

    if not motivo or not motivo.strip():
        raise ValidationError("Debes indicar el motivo del cambio.")

    marca = Marca.objects.select_for_update().get(pk=marca_id)

    if marca.nombre == nombre and marca.tipo == tipo and marca.activa == activa:
        raise ValidationError("No hay cambios que registrar.")

    HistorialMarca.objects.create(
        marca=marca,
        nombre=marca.nombre,
        tipo=marca.tipo,
        activa=marca.activa,
        accion=HistorialMarca.Accion.MODIFICACION,
        usuario=usuario,
        motivo=motivo.strip(),
    )

    marca.nombre = nombre
    marca.tipo = tipo
    marca.activa = activa

    marca.full_clean()
    marca.save(update_fields=["nombre", "tipo", "activa"])

    registrar_evento(
        TipoEvento.CAMBIO_CATALOGO,
        usuario=usuario,
        objeto=f"catalogo.Marca:{marca.pk}",
        motivo="Modificación de marca",
        detalle={
            "accion": "modificacion",
            "marca_id": marca.pk,
        },
    )

    return marca


"Conserva una versión anterior de una marca con auditoría."


@transaction.atomic
def restaurar_marca(*, historial_id, usuario, motivo):
    """Restaura una versión anterior de una marca con auditoría."""

    if usuario is None or not usuario.is_authenticated or not usuario.is_staff:
        raise PermissionError("Se requiere un administrador autenticado.")

    if not motivo or not motivo.strip():
        raise ValidationError("Debes indicar el motivo de la restauración.")

    historial = HistorialMarca.objects.get(pk=historial_id)

    marca = Marca.objects.select_for_update().get(pk=historial.marca_id)

    if (
        marca.nombre == historial.nombre
        and marca.tipo == historial.tipo
        and marca.activa == historial.activa
    ):
        raise ValidationError("La marca ya tiene los valores de esta versión.")

    # Guardamos el estado actual antes de restaurar.
    HistorialMarca.objects.create(
        marca=marca,
        nombre=marca.nombre,
        tipo=marca.tipo,
        activa=marca.activa,
        accion=HistorialMarca.Accion.RESTAURACION,
        usuario=usuario,
        motivo=motivo.strip(),
    )

    marca.nombre = historial.nombre
    marca.tipo = historial.tipo
    marca.activa = historial.activa

    marca.full_clean()
    marca.save(update_fields=["nombre", "tipo", "activa"])

    registrar_evento(
        TipoEvento.CAMBIO_CATALOGO,
        usuario=usuario,
        objeto=f"catalogo.Marca:{marca.pk}",
        motivo="Restauración de marca",
        detalle={
            "accion": "restauracion",
            "marca_id": marca.pk,
            "historial_id": historial.pk,
        },
    )

    return marca


"""Registra una solicitud de dominio oficial con auditoría."""


@transaction.atomic
def solicitar_dominio_oficial(*, marca_id, dominio, fuente_verificacion, usuario, motivo):
    """Registra una solicitud de dominio oficial pendiente de aprobación."""

    if usuario is None or not usuario.is_authenticated or not usuario.is_staff:
        raise PermissionError("Se requiere un administrador autenticado.")

    if not motivo or not motivo.strip():
        raise ValidationError("Debes indicar el motivo de la solicitud.")

    marca = Marca.objects.get(pk=marca_id)

    dominio_normalizado = dominio.strip().lower().rstrip(".")

    if DominioOficial.objects.filter(dominio=dominio_normalizado).exists():
        raise ValidationError("Este dominio ya está registrado.")

    solicitud = DominioOficial(
        marca=marca,
        dominio=dominio_normalizado,
        fuente_verificacion=fuente_verificacion,
        estado=DominioOficial.Estado.PENDIENTE,
        fecha_verificacion=None,
        solicitado_por=usuario,
        aprobado_por=None,
        aprobado_en=None,
    )

    solicitud.full_clean()
    solicitud.save()

    registrar_evento(
        TipoEvento.CAMBIO_CATALOGO,
        usuario=usuario,
        objeto=f"catalogo.DominioOficial:{solicitud.pk}",
        motivo="Solicitud de dominio oficial",
        detalle={
            "accion": "solicitud",
            "marca_id": marca.pk,
            "dominio_id": solicitud.pk,
        },
    )

    return solicitud


def aprobar_dominio_oficial(*, dominio_id, usuario, codigo, motivo):
    """Aprueba un dominio mediante un segundo administrador con TOTP."""

    if (
        usuario is None
        or not usuario.is_authenticated
        or not usuario.is_active
        or not usuario.is_staff
    ):
        raise PermissionError("Se requiere un administrador activo.")

    if not isinstance(motivo, str) or not motivo.strip():
        raise ValidationError("Debes indicar el motivo de aprobación.")

    if not isinstance(codigo, str) or not (
        len(codigo) == 6 and codigo.isascii() and codigo.isdigit()
    ):
        raise ValidationError("El código TOTP debe contener seis dígitos.")

    # Comprobación inicial antes de consumir el código TOTP.
    dominio = DominioOficial.objects.get(pk=dominio_id)

    if dominio.estado != DominioOficial.Estado.PENDIENTE:
        raise ValidationError("El dominio no está pendiente de aprobación.")

    if dominio.solicitado_por_id is None:
        raise ValidationError("El dominio no tiene un solicitante identificado.")

    if dominio.solicitado_por_id == usuario.pk:
        raise PermissionError("No puedes aprobar tu propia solicitud.")

    # Primera transacción: conservar el resultado de la verificación TOTP.
    with transaction.atomic():
        dispositivo = (
            TOTPDevice.objects.select_for_update().filter(user=usuario, confirmed=True).first()
        )

        if dispositivo is None:
            raise PermissionError("El administrador no tiene TOTP confirmado.")

        codigo_valido = dispositivo.verify_token(codigo)

    # La transacción ya terminó: los intentos fallidos quedan registrados.
    if not codigo_valido:
        raise ValidationError("Código TOTP inválido o ya utilizado.")

    # Segunda transacción: aprobación y auditoría.
    with transaction.atomic():
        dominio = DominioOficial.objects.select_for_update().get(pk=dominio_id)

        anterior = None

        if dominio.reemplaza_a_id is not None:
            anterior = DominioOficial.objects.select_for_update().get(pk=dominio.reemplaza_a_id)

            if anterior.estado != DominioOficial.Estado.APROBADO:
                raise ValidationError("El dominio anterior ya no está aprobado.")

            if anterior.marca_id != dominio.marca_id:
                raise ValidationError("Los dominios deben pertenecer a la misma marca.")

        # Revalidar para evitar aprobar una solicitud modificada.
        if dominio.estado != DominioOficial.Estado.PENDIENTE:
            raise ValidationError("El dominio no está pendiente de aprobación.")

        if dominio.solicitado_por_id is None or dominio.solicitado_por_id == usuario.pk:
            raise PermissionError("La solicitud no cumple la separación de administradores.")

        # Guardar el estado anterior del dominio.
        HistorialDominio.objects.create(
            dominio_oficial=dominio,
            dominio=dominio.dominio,
            fuente_verificacion=dominio.fuente_verificacion,
            fecha_verificacion=dominio.fecha_verificacion,
            estado=dominio.estado,
            solicitado_por=dominio.solicitado_por,
            aprobado_por=dominio.aprobado_por,
            aprobado_en=dominio.aprobado_en,
            accion=HistorialDominio.Accion.APROBACION,
            usuario=usuario,
            motivo=motivo.strip(),
        )

        if anterior is not None:
            HistorialDominio.objects.create(
                dominio_oficial=anterior,
                dominio=anterior.dominio,
                fuente_verificacion=anterior.fuente_verificacion,
                fecha_verificacion=anterior.fecha_verificacion,
                estado=anterior.estado,
                solicitado_por=anterior.solicitado_por,
                aprobado_por=anterior.aprobado_por,
                aprobado_en=anterior.aprobado_en,
                accion=HistorialDominio.Accion.MODIFICACION,
                usuario=usuario,
                motivo=f"Reemplazado por {dominio.dominio}: {motivo.strip()}",
            )

        ahora = timezone.now()

        dominio.estado = DominioOficial.Estado.APROBADO
        dominio.aprobado_por = usuario
        dominio.aprobado_en = ahora
        dominio.fecha_verificacion = ahora

        dominio.full_clean()
        dominio.save(
            update_fields=[
                "estado",
                "aprobado_por",
                "aprobado_en",
                "fecha_verificacion",
            ]
        )

        if anterior is not None:
            anterior.estado = DominioOficial.Estado.RETIRADO
            anterior.full_clean()
            anterior.save(update_fields=["estado"])

        registrar_evento(
            TipoEvento.CAMBIO_CATALOGO,
            usuario=usuario,
            objeto=f"catalogo.DominioOficial:{dominio.pk}",
            motivo="Aprobación de dominio oficial",
            detalle={
                "accion": "aprobacion",
                "dominio_id": dominio.pk,
                "solicitante_id": dominio.solicitado_por_id,
                "aprobador_id": usuario.pk,
                "dominio_anterior_id": dominio.reemplaza_a_id,
            },
        )

    return dominio


@transaction.atomic
def solicitar_reemplazo_dominio(
    *,
    dominio_anterior_id,
    dominio_nuevo,
    fuente_verificacion,
    usuario,
    motivo,
):
    """Solicita reemplazar un dominio aprobado sin retirarlo todavía."""

    if (
        usuario is None
        or not usuario.is_authenticated
        or not usuario.is_active
        or not usuario.is_staff
    ):
        raise PermissionError("Se requiere un administrador activo.")

    if not isinstance(motivo, str) or not motivo.strip():
        raise ValidationError("Debes indicar el motivo del reemplazo.")

    if not isinstance(dominio_nuevo, str):
        raise ValidationError("Debes indicar un dominio válido.")

    anterior = DominioOficial.objects.select_for_update().get(pk=dominio_anterior_id)

    if anterior.estado != DominioOficial.Estado.APROBADO:
        raise ValidationError("Solo se puede reemplazar un dominio aprobado.")

    nuevo_normalizado = dominio_nuevo.strip().lower().rstrip(".")

    if nuevo_normalizado == anterior.dominio:
        raise ValidationError("El nuevo dominio debe ser diferente del anterior.")

    if DominioOficial.objects.filter(
        reemplaza_a=anterior,
        estado=DominioOficial.Estado.PENDIENTE,
    ).exists():
        raise ValidationError("Ya existe una solicitud pendiente para reemplazar este dominio.")

    solicitud = DominioOficial(
        marca=anterior.marca,
        dominio=nuevo_normalizado,
        fuente_verificacion=fuente_verificacion,
        fecha_verificacion=None,
        estado=DominioOficial.Estado.PENDIENTE,
        solicitado_por=usuario,
        aprobado_por=None,
        aprobado_en=None,
        reemplaza_a=anterior,
    )

    solicitud.full_clean()
    solicitud.save()

    registrar_evento(
        TipoEvento.CAMBIO_CATALOGO,
        usuario=usuario,
        objeto=f"catalogo.DominioOficial:{solicitud.pk}",
        motivo="Solicitud de reemplazo de dominio",
        detalle={
            "accion": "solicitud_reemplazo",
            "dominio_id": solicitud.pk,
            "dominio_anterior_id": anterior.pk,
            "marca_id": anterior.marca_id,
        },
    )

    return solicitud
