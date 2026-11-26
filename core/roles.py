"""Roles de la consola interna: analista y administrador.

Cada rol es un grupo de Django con permisos por modelo. Toda función de la consola está
denegada hasta que un permiso de estos la habilita: una cuenta interna sin grupo entra
al admin y no ve nada. El comando `crear_roles` crea los grupos y les deja exactamente
estos permisos, así que una tarea que agrega modelos a la consola los suma aquí y vuelve
a correr el comando.

Los permisos van como texto "app.codename" para que core no importe de otras apps.
"""
from django.contrib.auth.models import Group, Permission
from django.db import transaction

ANALISTA = "Analista"
ADMINISTRADOR = "Administrador"

# Curación, invalidación y estadísticas. Las campañas llegan con la tarea 47.
PERMISOS_ANALISTA = frozenset({
    "curacion.view_reportedesacuerdo",
    "curacion.change_reportedesacuerdo",
    "curacion.view_solicitudrevision",
    "curacion.change_solicitudrevision",
    "core.view_invalidaciondominio",
    "core.add_invalidaciondominio",
    "core.change_invalidaciondominio",
    "analisis.view_analisis",
})

# Lo del analista más catálogo, reglas, cuentas internas y auditoría. Nadie borra: las
# cuentas se desactivan y el catálogo guarda su historial. Los grupos y la auditoría
# son de solo lectura, y el segundo factor se reinicia con el comando reiniciar_totp.
PERMISOS_ADMINISTRADOR = PERMISOS_ANALISTA | frozenset({
    "catalogo.view_marca",
    "catalogo.add_marca",
    "catalogo.change_marca",
    "catalogo.view_dominiooficial",
    "catalogo.add_dominiooficial",
    "catalogo.change_dominiooficial",
    "catalogo.view_canaloficial",
    "catalogo.add_canaloficial",
    "catalogo.change_canaloficial",
    "catalogo.view_varianteobservada",
    "catalogo.add_varianteobservada",
    "catalogo.change_varianteobservada",
    "catalogo.view_historialmarca",
    "catalogo.view_historialdominio",
    "motor.view_reputacion",
    "auth.view_user",
    "auth.add_user",
    "auth.change_user",
    "auth.view_group",
    "core.view_eventoauditoria",
    "otp_totp.view_totpdevice",
    "otp_static.view_staticdevice",
})

ROLES = {
    ANALISTA: PERMISOS_ANALISTA,
    ADMINISTRADOR: PERMISOS_ADMINISTRADOR,
}


class PermisoInexistente(Exception):
    """Un permiso de ROLES no existe en la base: falta migrar o el nombre está mal."""


def _buscar_permisos(nombres):
    encontrados = {}
    for permiso in Permission.objects.select_related("content_type"):
        encontrados[f"{permiso.content_type.app_label}.{permiso.codename}"] = permiso
    faltan = sorted(set(nombres) - set(encontrados))
    if faltan:
        raise PermisoInexistente(", ".join(faltan))
    return [encontrados[nombre] for nombre in nombres]


@transaction.atomic
def sincronizar_roles():
    """Crea los grupos que falten y les deja exactamente los permisos de ROLES.

    Quita los permisos que alguien haya agregado a mano desde el admin. Devuelve los
    grupos por nombre.
    """
    grupos = {}
    for nombre, permisos in ROLES.items():
        grupo, _ = Group.objects.get_or_create(name=nombre)
        grupo.permissions.set(_buscar_permisos(sorted(permisos)))
        grupos[nombre] = grupo
    return grupos


def es_administrador(usuario) -> bool:
    """True si la cuenta es interna, está activa y tiene el rol de administrador.

    Un superusuario de Django ya tiene todos los permisos, así que también cuenta. Las
    cuentas que crea `crear_cuenta_interna` nunca son superusuario.
    """
    if usuario is None or not getattr(usuario, "is_authenticated", False):
        return False
    if not (usuario.is_active and usuario.is_staff):
        return False
    return usuario.is_superuser or usuario.groups.filter(name=ADMINISTRADOR).exists()
