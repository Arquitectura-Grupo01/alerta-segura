"""Lectura de la caché de resultados.

Aquí solo se lee: `motor.cache` es el único módulo que escribe. La clave es el SHA-256
de la URL normalizada más la versión de reglas, así que no revela la URL y una versión
nueva deja atrás los resultados de la anterior.
"""

import hashlib

from django.core.cache import caches

from .models import InvalidacionDominio

CACHE = "resultados"
# Lo mínimo que debe traer una entrada. Si falta algo, está dañada y no se usa.
CAMPOS = frozenset({
    "nivel", "puntaje", "cobertura", "reglas", "version", "senales", "fuentes", "dominio",
    "dominio_origen", "redirecciones", "motivos", "acciones", "fecha", "contadores",
})


def clave_de_resultado(url: str, version: str) -> str:
    resumen = hashlib.sha256(f"{version}\n{url}".encode("utf-8", "surrogatepass")).hexdigest()
    return f"resultado:{resumen}"


def contadores_de(dominios) -> dict[str, int]:
    """Contador de invalidación de cada dominio. Un dominio sin fila vale 0."""
    dominios = {dominio for dominio in dominios if dominio}
    guardados = dict(
        InvalidacionDominio.objects.filter(dominio__in=dominios).values_list("dominio", "contador")
    )
    return {dominio: guardados.get(dominio, 0) for dominio in dominios}


def leer_resultado(url: str, version: str) -> dict | None:
    """El resultado vigente de una URL, o None si no hay, está dañado o fue invalidado."""
    entrada = caches[CACHE].get(clave_de_resultado(url, version))
    if not isinstance(entrada, dict) or not CAMPOS <= entrada.keys():
        return None
    contadores = entrada["contadores"]
    if not isinstance(contadores, dict) or contadores != contadores_de(contadores):
        return None
    return entrada
