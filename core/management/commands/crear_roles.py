"""Crea los grupos Analista y Administrador con los permisos de core/roles.py."""

from django.core.management.base import BaseCommand, CommandError

from core.roles import ROLES, PermisoInexistente, sincronizar_roles


class Command(BaseCommand):
    help = "Crea o actualiza los roles de la consola. Se corre después de migrate."

    def handle(self, *args, **opciones):
        try:
            sincronizar_roles()
        except PermisoInexistente as error:
            raise CommandError(f"Faltan permisos, corre migrate primero: {error}") from None
        for nombre, permisos in ROLES.items():
            self.stdout.write(f"{nombre}: {len(permisos)} permisos")
