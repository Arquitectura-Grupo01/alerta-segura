"""Crea análisis ficticios para desarrollar la consola y el panel sin datos reales."""

import random
from dataclasses import asdict
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from analisis.models import Analisis
from motor.riesgo import VERSION_INICIAL, Nivel, Senales, calcular

# Dominios reservados para ejemplos: ninguno existe en internet.
DOMINIOS = ("tienda.example", "banco-falso.example", "premios.test", "envios.example", "pagos.test")
CASOS = (
    Senales(heuristicas=(), edad_dias=900, marca=0, fuentes=0),
    Senales(heuristicas=("acortador",)),
    Senales(heuristicas=("palabras_sospechosas",), edad_dias=12),
    Senales(heuristicas=("ip_como_dominio", "palabras_sospechosas"), edad_dias=3),
    Senales(heuristicas=("usuario_en_url",), fuentes=100, fuentes_con_deteccion=1),
    Senales(heuristicas=("punycode",), edad_dias=2, fuentes=100, fuentes_con_deteccion=2),
)


class Command(BaseCommand):
    help = "Crea análisis ficticios de los últimos 30 días."

    def add_arguments(self, parser):
        parser.add_argument("--cantidad", type=int, default=60)

    def handle(self, *args, cantidad, **opciones):
        # Semilla fija: los datos de demostración son los mismos en cada equipo.
        azar = random.Random(2026)
        ahora = timezone.now()
        creados = []
        for _ in range(cantidad):
            senales = azar.choice(CASOS)
            veredicto = calcular(senales)
            dominio = azar.choice(DOMINIOS)
            fecha = ahora - timedelta(minutes=azar.randrange(30 * 24 * 60))
            creados.append(Analisis(
                fecha=fecha,
                fecha_analisis=fecha,
                tipo_entrada=Analisis.Tipo.ENLACE,
                dominio=dominio,
                redirecciones=0,
                url=f"https://{dominio}/demo" if veredicto.nivel >= Nivel.PELIGROSO else "",
                nivel=int(veredicto.nivel),
                puntaje=veredicto.puntaje,
                cobertura=veredicto.cobertura,
                version_reglas=veredicto.version,
                senales=asdict(senales),
                pesos={c: VERSION_INICIAL.pesos[c] for c in veredicto.valores},
                reglas=list(veredicto.reglas),
                desde_cache=azar.random() < 0.3,
            ))
        Analisis.objects.bulk_create(creados)
        self.stdout.write(f"Se crearon {len(creados)} análisis ficticios.")
