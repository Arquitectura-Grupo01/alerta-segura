"""Borra los datos vencidos y muestra cuánto ocupa la base (tarea 40).

    python manage.py purgar_datos --simular   # cuenta lo que borraría, sin borrar
    python manage.py purgar_datos             # borra y deja un evento en la auditoría

Un integrante lo corre a mano una vez al mes contra Prod, con la DATABASE_URL solo en la
terminal. Render gratuito no tiene tareas programadas, y automatizarlo exigiría guardar la
DATABASE_URL de Prod en GitHub Actions.
"""
from django.core.management.base import BaseCommand
from django.utils import timezone

from core import retencion
from curacion import retencion as retencion_curacion


class Command(BaseCommand):
    help = "Borra en lotes los datos vencidos y muestra el uso de la base."

    def add_arguments(self, parser):
        parser.add_argument(
            "--simular", action="store_true", help="Solo cuenta lo que borraría.",
        )

    def handle(self, *args, simular, **opciones):
        ahora = timezone.now()
        if simular:
            totales = {
                **retencion_curacion.contar(ahora),
                "eventos": retencion.contar_auditoria_vencida(ahora),
                "sesiones": retencion.contar_sesiones_vencidas(ahora),
            }
        else:
            totales = {
                **retencion_curacion.purgar(ahora),
                "eventos": retencion.purgar_auditoria(ahora),
                "sesiones": retencion.purgar_sesiones(ahora),
                "cache_vencida": retencion.purgar_cache_vencida(ahora),
            }
            # Después de borrar, para que el evento de la purga no entre en ella.
            retencion.registrar_purga(totales)

        verbo = "Se borrarían" if simular else "Se borraron"
        for nombre, cantidad in totales.items():
            self.stdout.write(f"{verbo} {cantidad} filas de {nombre}.")
        self._mostrar_uso()

    def _mostrar_uso(self):
        usados = retencion.uso_de_la_base()
        proporcion = usados / retencion.LIMITE_NEON_BYTES
        self.stdout.write(
            f"La base ocupa {usados / 1024 / 1024:.1f} MB, el {proporcion:.0%} de "
            f"{retencion.LIMITE_NEON_BYTES / 1024 / 1024:.0f} MB del plan gratuito de Neon."
        )
        if proporcion >= retencion.AVISO_DESDE:
            self.stderr.write(
                "Aviso: la base pasó el 80 % del límite. Revisa el panel de Neon y "
                "conversa con el equipo si hay que acortar algún plazo."
            )
