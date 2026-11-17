"""Tarea 56: benchmark local del análisis de enlaces y su caché.

Las fuentes y las conexiones externas están simuladas.
Los resultados no representan el rendimiento de Render Dev.
"""

import math
import statistics
import time

import pytest
from django.core.cache import caches

from analisis import orquestador
from analisis.destino import Destino
from analisis.normalizacion import normalizar
from inteligencia import fuentes as modulo_fuentes
from inteligencia.fuentes import Fuente

pytestmark = pytest.mark.django_db


class FuenteContada(Fuente):
    """Fuente ficticia para verificar las consultas externas."""

    nombre = "rendimiento"
    titulo = "Fuente simulada"

    def __init__(self):
        super().__init__()
        self.llamadas = 0

    def _consultar(self, url):
        self.llamadas += 1
        return self.desconocido()


def percentil_95(valores):
    """Percentil 95 mediante rango más cercano."""
    ordenados = sorted(valores)
    posicion = math.ceil(0.95 * len(ordenados)) - 1
    return ordenados[posicion]


def test_rendimiento_analisis_y_cache(monkeypatch):
    fuente = FuenteContada()
    monkeypatch.setattr(modulo_fuentes, "_FUENTES", [fuente])

    llamadas_destino = []
    llamadas_edad = []

    def destino_simulado(url):
        llamadas_destino.append(url)
        return Destino(resultado="error_de_red")

    def edad_simulada(dominios):
        llamadas_edad.append(tuple(dominios))
        return None

    monkeypatch.setattr(orquestador, "seguir_enlace", destino_simulado)
    monkeypatch.setattr(orquestador, "edad_en_dias", edad_simulada)

    urls = [f"https://prueba{i}.example/verificar" for i in range(50)]

    caches["resultados"].clear()

    tiempos_iniciales = []
    tiempos_cache = []

    # 20 análisis iniciales, uno por URL.
    for url in urls:
        enlace = normalizar(url)

        inicio = time.perf_counter()
        resultado = orquestador.analizar_enlace(enlace)
        duracion = time.perf_counter() - inicio

        assert resultado.desde_cache is False
        tiempos_iniciales.append(duracion)

    assert len(llamadas_destino) == 50
    assert len(llamadas_edad) == 50
    assert fuente.llamadas == 50

    # 200 consultas repetidas: 10 por cada URL.
    for _ in range(10):
        for url in urls[:20]:
            enlace = normalizar(url)

            inicio = time.perf_counter()
            resultado = orquestador.analizar_enlace(enlace)
            duracion = time.perf_counter() - inicio

            assert resultado.desde_cache is True
            tiempos_cache.append(duracion)

    # Ninguna consulta adicional al destino, edad o fuente.
    assert len(llamadas_destino) == 50
    assert len(llamadas_edad) == 50
    assert fuente.llamadas == 50

    p95_inicial = percentil_95(tiempos_iniciales)
    p95_cache = percentil_95(tiempos_cache)
    mediana_inicial = statistics.median(tiempos_iniciales)
    mediana_cache = statistics.median(tiempos_cache)

    mejora = mediana_inicial / mediana_cache if mediana_cache > 0 else float("inf")

    print("\n=== TAREA 56: RENDIMIENTO LOCAL ===")
    print(f"Primeros análisis: {len(tiempos_iniciales)}")
    print(f"Consultas desde caché: {len(tiempos_cache)}")
    print(f"P95 inicial: {p95_inicial:.4f} s")
    print(f"Mediana inicial: {mediana_inicial:.4f} s")
    print(f"P95 caché: {p95_cache:.4f} s")
    print(f"Mediana caché: {mediana_cache:.4f} s")
    print(f"Mejora de mediana: {mejora:.2f}x")
    print(f"Consultas simuladas totales: {fuente.llamadas}")
    print("Consultas externas adicionales en caché: 0")
    print(f"Meta P95 inicial <= 8 s: {p95_inicial <= 8}")
    print(f"Meta P95 caché <= 1 s: {p95_cache <= 1}")
    print(f"Meta mejora >= 5x: {mejora >= 5}")

    assert len(tiempos_iniciales) == 50
    assert len(tiempos_cache) == 200
