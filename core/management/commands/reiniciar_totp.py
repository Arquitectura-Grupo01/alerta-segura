"""Entrega un autenticador y códigos de recuperación nuevos a una cuenta interna.

    python manage.py reiniciar_totp <usuario>

Lo corre un administrador cuando alguien perdió su celular o sus códigos. Los anteriores
dejan de servir y queda un evento en la auditoría.
"""
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from core.cuentas import reiniciar_segundo_factor

from ._segundo_factor import mostrar_segundo_factor


class Command(BaseCommand):
    help = "Reemplaza el TOTP y los códigos de recuperación de una cuenta interna."

    def add_arguments(self, parser):
        parser.add_argument("usuario")

    def handle(self, *args, usuario, **opciones):
        modelo = get_user_model()
        try:
            cuenta = modelo._default_manager.get(username=usuario, is_staff=True)
        except modelo.DoesNotExist:
            raise CommandError("No hay una cuenta interna con ese nombre.") from None
        totp, codigos = reiniciar_segundo_factor(cuenta)
        self.stdout.write(f"Segundo factor de {cuenta.username} reiniciado.")
        mostrar_segundo_factor(self.stdout, totp, codigos)
