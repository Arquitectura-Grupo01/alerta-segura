"""Motor de riesgo: convierte las señales de un análisis en nivel, puntaje y cobertura.

Sigue los cuatro pasos de la sección «Motor de riesgo» de `docs/requisitos.md`.
`calcular` es una función pura: no lee la hora, la red ni la base, así que con
las mismas señales y la misma versión de reglas da siempre el mismo resultado.

La versión de reglas vive aquí como constante mientras no exista el modelo
`VersionReglas` de la tarea 21. Cuando exista, `calcular` recibirá la versión
activa leída de la base y esta constante será la versión inicial que se carga.
"""

import math
from collections.abc import Mapping
from dataclasses import dataclass
from enum import IntEnum
from types import MappingProxyType


class Nivel(IntEnum):
    """Los cuatro niveles, de menos a más riesgo. El orden permite compararlos."""

    SEGURO = 0
    TEN_CUIDADO = 1
    PELIGROSO = 2
    PELIGRO_ALTO = 3

    @property
    def texto(self) -> str:
        """El texto exacto que ve la persona."""
        return _TEXTOS[self]

    @property
    def clave(self) -> str:
        """Nombre corto para clases CSS e íconos: `nivel-cuidado`, `#i-cuidado`."""
        return _CLAVES[self]


_TEXTOS = {
    Nivel.SEGURO: "Seguro",
    Nivel.TEN_CUIDADO: "Ten cuidado",
    Nivel.PELIGROSO: "Peligroso",
    Nivel.PELIGRO_ALTO: "Peligro alto",
}

_CLAVES = {
    Nivel.SEGURO: "seguro",
    Nivel.TEN_CUIDADO: "cuidado",
    Nivel.PELIGROSO: "peligroso",
    Nivel.PELIGRO_ALTO: "alto",
}

# Categorías de señales del paso 1.
FUENTES = "fuentes"
EDAD = "edad"
HEURISTICAS = "heuristicas"
MARCA = "marca"
INGENIERIA_SOCIAL = "ingenieria_social"

# Grupo de puntos de cada señal de la dirección. Varias señales del mismo grupo
# suman una sola vez: una IP escrita en hexadecimal no vale más que una normal.
GRUPO_DE_SENAL = MappingProxyType({
    "ip_como_dominio": "ip",
    "ip_alternativa": "ip",
    "acortador": "acortador",
    "punycode": "enganoso",
    "alfabetos_mezclados": "enganoso",
    "usuario_en_url": "enganoso",
    "barra_invertida": "enganoso",
    "caracteres_de_control": "enganoso",
    "punto_final": "enganoso",
    "muchos_subdominios": "subdominios",
    "palabras_sospechosas": "palabras",
})

# Reglas de piso del paso 4 con el nivel mínimo que imponen, de la más grave a la más leve.
NIVEL_DE_REGLA = MappingProxyType({
    "dos_fuentes_confirman": Nivel.PELIGRO_ALTO,
    "fuente_y_suplantacion": Nivel.PELIGRO_ALTO,
    "analista_confirma": Nivel.PELIGRO_ALTO,
    "una_fuente_confirma": Nivel.PELIGROSO,
    "suplantacion_en_web_nueva": Nivel.PELIGROSO,
    "credenciales_con_urgencia": Nivel.PELIGROSO,
    "fuente_no_concluyente": Nivel.TEN_CUIDADO,
    "web_nueva": Nivel.TEN_CUIDADO,
    "cobertura_baja": Nivel.TEN_CUIDADO,
})

# Estas señales no suman a las heurísticas: forman la categoría de suplantación de marca.
SENALES_DE_MARCA = frozenset({"marca_en_subdominio", "dominio_parecido"})


@dataclass(frozen=True)
class VersionReglas:
    """Pesos, umbrales y pisos de una versión de reglas."""

    numero: str
    pesos: Mapping[str, int]
    puntos_heuristicas: Mapping[str, int]
    # Límite superior de puntaje de cada nivel, de menor a mayor.
    umbrales: tuple[tuple[int, Nivel], ...]
    aplicables: Mapping[str, tuple[str, ...]]
    cobertura_minima: int = 70
    aporte_maximo_modelo: int = 10
    suplantacion_minima: int = 60
    dias_web_nueva: int = 30
    # Cuánto vale un análisis externo sin hallazgos según la edad de la web:
    # (edad menor que estos días, horas de vigencia). El último tramo no tiene tope.
    vigencia_analisis: tuple[tuple[int | None, int], ...] = ((None, 24),)


VERSION_INICIAL = VersionReglas(
    # La 2 cambia la vigencia de los análisis externos, que era de 24 h para toda web.
    numero="2",
    vigencia_analisis=((30, 24), (365, 7 * 24), (None, 30 * 24)),
    pesos=MappingProxyType({
        FUENTES: 40,
        EDAD: 25,
        HEURISTICAS: 15,
        MARCA: 10,
        INGENIERIA_SOCIAL: 10,
    }),
    puntos_heuristicas=MappingProxyType({
        "ip": 40,
        "acortador": 20,
        "enganoso": 40,
        "subdominios": 20,
        "palabras": 20,
    }),
    umbrales=(
        (20, Nivel.SEGURO),
        (50, Nivel.TEN_CUIDADO),
        (80, Nivel.PELIGROSO),
        (100, Nivel.PELIGRO_ALTO),
    ),
    # Solo las categorías que existen en v1 para cada tipo de entrada.
    aplicables=MappingProxyType({
        "enlace": (FUENTES, EDAD, HEURISTICAS, MARCA),
    }),
)


@dataclass(frozen=True)
class Senales:
    """Lo que los analizadores y las fuentes encontraron. `None` significa sin dato."""

    tipo_entrada: str = "enlace"
    # Códigos de `analisis.heuristicas`. Para un enlace, revisar la dirección siempre da evidencia.
    heuristicas: tuple[str, ...] = ()
    # De 0 a 100. `None` mientras no exista el catálogo de marcas.
    marca: int | None = None
    edad_dias: int | None = None
    # De 0 a 100. `None` si ninguna fuente tiene un análisis vigente.
    fuentes: int | None = None
    fuentes_con_deteccion: int = 0
    # Una fuente la marca como peligrosa sin decir de qué tipo y ninguna lo confirma.
    fuentes_en_duda: bool = False
    ingenieria_social: int | None = None
    credenciales_con_urgencia: bool = False
    confirmado_por_analista: bool = False


@dataclass(frozen=True)
class Veredicto:
    nivel: Nivel
    puntaje: int
    # Porcentaje del peso aplicable que tuvo evidencia, de 0 a 100.
    cobertura: float
    # Códigos de las reglas de piso que se activaron, de la más grave a la más leve.
    reglas: tuple[str, ...]
    # Valor de 0 a 100 de cada categoría aplicable; `None` si no hubo evidencia.
    valores: Mapping[str, int | None]
    senales: Senales
    version: str
    aporte_modelo: int = 0
    # Nivel que da el puntaje antes de aplicar los pisos.
    nivel_puntaje: Nivel = Nivel.SEGURO


def calcular(
    senales: Senales,
    version: VersionReglas = VERSION_INICIAL,
    aporte_modelo: int = 0,
) -> Veredicto:
    """Calcula el veredicto. Ver los cuatro pasos en `docs/requisitos.md`."""
    if senales.tipo_entrada not in version.aplicables:
        raise ValueError(f"Tipo de entrada sin reglas: {senales.tipo_entrada}")

    aplicables = version.aplicables[senales.tipo_entrada]
    todos = _valores(senales, version)
    valores = {categoria: todos[categoria] for categoria in aplicables}
    con_evidencia = {categoria: valor for categoria, valor in valores.items() if valor is not None}

    # Paso 2: promedio ponderado solo con las categorías que tienen evidencia.
    peso_evidencia = sum(version.pesos[categoria] for categoria in con_evidencia)
    base = (
        sum(valor * version.pesos[categoria] for categoria, valor in con_evidencia.items())
        / peso_evidencia
        if peso_evidencia
        else 0
    )
    aporte = min(max(aporte_modelo, 0), version.aporte_maximo_modelo)
    puntaje = min(100, math.floor(base + aporte + 0.5))

    # Paso 3: cobertura. El aporte del modelo no cuenta.
    peso_aplicable = sum(version.pesos[categoria] for categoria in aplicables)
    cobertura = round(100 * peso_evidencia / peso_aplicable, 1)
    cobertura_baja = peso_evidencia * 100 < version.cobertura_minima * peso_aplicable

    # Paso 4: pisos.
    pisos = _pisos(senales, version, cobertura_baja)
    nivel_puntaje = _nivel_por_puntaje(puntaje, version)
    nivel = max([nivel_puntaje, *pisos.values()])

    return Veredicto(
        nivel=nivel,
        puntaje=puntaje,
        cobertura=cobertura,
        reglas=tuple(pisos),
        valores=MappingProxyType(valores),
        senales=senales,
        version=version.numero,
        aporte_modelo=aporte,
        nivel_puntaje=nivel_puntaje,
    )


def puntaje_heuristicas(codigos: tuple[str, ...], version: VersionReglas = VERSION_INICIAL) -> int:
    """Suma los puntos de los grupos encontrados, con tope de 100."""
    desconocidos = set(codigos) - set(GRUPO_DE_SENAL) - SENALES_DE_MARCA
    if desconocidos:
        raise ValueError(f"Señales sin puntos asignados: {sorted(desconocidos)}")
    grupos = {GRUPO_DE_SENAL[codigo] for codigo in codigos if codigo in GRUPO_DE_SENAL}
    return min(100, sum(version.puntos_heuristicas[grupo] for grupo in grupos))


def puntaje_marca(codigos: tuple[str, ...], catalogo_disponible: bool) -> int | None:
    """Vale 100 si la dirección imita a una marca del catálogo y 0 si no. Sin catálogo, sin dato."""
    if not catalogo_disponible:
        return None
    return 100 if SENALES_DE_MARCA & set(codigos) else 0


def horas_de_vigencia(edad_dias: int | None, version: VersionReglas = VERSION_INICIAL) -> int:
    """Horas que vale un análisis externo sin hallazgos para una web de esa edad.

    Una página falsa vive horas o días, así que en una web nueva solo sirve un análisis
    de hoy. Sin edad conocida se usa el plazo más corto.
    """
    if edad_dias is None:
        return version.vigencia_analisis[0][1]
    for tope, horas in version.vigencia_analisis:
        if tope is None or edad_dias < tope:
            return horas
    return version.vigencia_analisis[-1][1]


def puntaje_edad(edad_dias: int | None) -> int | None:
    if edad_dias is None:
        return None
    if edad_dias < 7:
        return 100
    if edad_dias <= 30:
        return 70
    if edad_dias <= 365:
        return 30
    return 0


def _valores(senales: Senales, version: VersionReglas) -> dict[str, int | None]:
    heuristicas = (
        puntaje_heuristicas(senales.heuristicas, version)
        if senales.tipo_entrada == "enlace"
        else None
    )
    return {
        FUENTES: senales.fuentes,
        EDAD: puntaje_edad(senales.edad_dias),
        HEURISTICAS: heuristicas,
        MARCA: senales.marca,
        INGENIERIA_SOCIAL: senales.ingenieria_social,
    }


def _pisos(senales: Senales, version: VersionReglas, cobertura_baja: bool) -> dict[str, Nivel]:
    """Devuelve las reglas activadas con su nivel mínimo, de la más grave a la más leve."""
    suplantacion = senales.marca is not None and senales.marca >= version.suplantacion_minima
    web_nueva = senales.edad_dias is not None and senales.edad_dias < version.dias_web_nueva

    activas = {
        "dos_fuentes_confirman": senales.fuentes_con_deteccion >= 2,
        "fuente_y_suplantacion": senales.fuentes_con_deteccion >= 1 and suplantacion,
        "analista_confirma": senales.confirmado_por_analista,
        "una_fuente_confirma": senales.fuentes_con_deteccion == 1,
        "suplantacion_en_web_nueva": suplantacion and web_nueva,
        "credenciales_con_urgencia": senales.credenciales_con_urgencia,
        # Evidencia contradictoria: ni Seguro ni Peligroso, hasta que algo lo aclare.
        "fuente_no_concluyente": senales.fuentes_en_duda and not senales.fuentes_con_deteccion,
        "web_nueva": web_nueva,
        "cobertura_baja": cobertura_baja,
    }
    return {codigo: NIVEL_DE_REGLA[codigo] for codigo, activa in activas.items() if activa}


def _nivel_por_puntaje(puntaje: int, version: VersionReglas) -> Nivel:
    for limite, nivel in version.umbrales:
        if puntaje <= limite:
            return nivel
    return version.umbrales[-1][1]
