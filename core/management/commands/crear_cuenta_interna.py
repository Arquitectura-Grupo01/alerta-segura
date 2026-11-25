"""Crea una cuenta de la consola con su rol, su autenticador y sus códigos de recuperación.

    python manage.py crear_cuenta_interna <usuario> --rol administrador

La clave se pide dos veces sin mostrarla. Al final se muestran, una sola vez, el enlace
para la app del autenticador y los códigos de recuperación.
"""
import getpass

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from core.cuentas import crear_cuenta_interna
from core.roles import ADMINISTRADOR, ANALISTA

from ._segundo_factor import mostrar_segundo_factor

ROLES_POR_OPCION = {"analista": ANALISTA, "administrador": ADMINISTRADOR}


class Command(BaseCommand):
    help = "Crea una cuenta interna con rol, TOTP y códigos de recuperación."

    def add_arguments(self, parser):
        parser.add_argument("usuario")
        parser.add_argument("--rol", required=True, choices=sorted(ROLES_POR_OPCION))

    def handle(self, *args, usuario, rol, **opciones):
        clave = getpass.getpass("Clave (12 caracteres o más): ")
        if clave != getpass.getpass("Repite la clave: "):
            raise CommandError("Las claves no coinciden.")
        try:
            cuenta, totp, codigos = crear_cuenta_interna(usuario, clave, ROLES_POR_OPCION[rol])
        except ValidationError as error:
            raise CommandError(" ".join(error.messages)) from None
        except ValueError as error:
            raise CommandError(str(error)) from None
        self.stdout.write(f"Cuenta {cuenta.username} creada con el rol {rol}.")
        mostrar_segundo_factor(self.stdout, totp, codigos)
