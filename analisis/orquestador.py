"""Orquestador: lleva un enlace desde la entrada hasta su resultado guardado.

Primero busca un resultado vigente en la caché. Si no hay, sigue el enlace, corre las
heurísticas, busca la edad, consulta las fuentes externas y pasa las señales al motor.
El resultado se guarda en la caché y cada consulta deja su fila en `Analisis`.

Hoy todo corre dentro de la solicitud, como en Render, donde Celery está en modo eager.
Los tiempos están acotados por cada paso: 10 s el enlace, 5 s la edad y 6 s las fuentes.
"""

import threading
from dataclasses import asdict
from datetime import datetime, timedelta

from django.utils import timezone

from analisis.destino import seguir_enlace
from analisis.edad import edad_en_dias, es_web_propia
from analisis.heuristicas import HEURISTICAS, detectar_senales, marca_imitada
from analisis.models import Analisis
from analisis.normalizacion import EnlaceNormalizado, URLInvalida, normalizar
from catalogo.models import DominioOficial
from core.resultados import leer_resultado
from inteligencia.fuentes import (
    MOTIVO_CUOTA,
    MOTIVO_PRESUPUESTO,
    MOTIVO_SIN_CATEGORIA,
    VALOR_CONFIRMA,
    aplicar_vigencia,
    consultar_fuentes,
    edad_informada,
    fuentes_activas,
    guardar_detalles,
    leer_detalles,
    resumir,
)
from motor import modalidades, reputacion
from motor.cache import descartar_resultado, guardar_resultado
from motor.explicacion import Recorrido, explicar
from motor.riesgo import (
    VERSION_INICIAL,
    Nivel,
    Senales,
    Veredicto,
    calcular,
    horas_de_vigencia,
    puntaje_marca,
)

# Análisis a la vez en un proceso. Cada uno abre conexiones y lee páginas de hasta 2 MB,
# y Render da 512 MB.
MAX_SIMULTANEOS = 2
# El servicio no falló: se acabaron las consultas que permite, las suyas o las nuestras.
MOTIVOS_DE_CUPO = frozenset({MOTIVO_CUOTA, MOTIVO_PRESUPUESTO})
ESPERA_DE_TURNO_SEGUNDOS = 3

_turnos = threading.BoundedSemaphore(MAX_SIMULTANEOS)


class Ocupado(Exception):
    """Hay demasiados análisis a la vez en este proceso."""


def analizar_enlace(enlace: EnlaceNormalizado) -> Analisis:
    """Devuelve el análisis guardado de un enlace, de la caché o recién calculado."""
    version = VERSION_INICIAL.numero
    datos = leer_resultado(enlace.url, version)
    if datos is not None:
        try:
            return _registrar(enlace, datos, _veredicto(datos), desde_cache=True)
        except (ValueError, TypeError, KeyError):
            # Entrada dañada: se descarta y se calcula de nuevo.
            descartar_resultado(enlace.url, version)

    if not _turnos.acquire(timeout=ESPERA_DE_TURNO_SEGUNDOS):
        raise Ocupado
    try:
        veredicto, datos = _calcular(enlace)
    finally:
        _turnos.release()
    sin_cupo = any(_estado_visible(fuente) == "sin_cupo" for fuente in datos["fuentes"])
    guardar_resultado(enlace.url, veredicto, datos, incompleto=sin_cupo)
    return _registrar(enlace, datos, veredicto, desde_cache=False)


def senales_de(analisis: Analisis) -> Senales:
    """Las señales guardadas de un análisis, listas para el motor."""
    return _senales(analisis.senales)


def _calcular(enlace: EnlaceNormalizado) -> tuple[Veredicto, dict]:
    destino = seguir_enlace(enlace.url_con_parametros)
    final = _enlace_final(destino.url)
    marcas = _dominios_oficiales()
    oficiales = tuple(marcas)
    encontradas = set(detectar_senales(enlace, oficiales))
    if final is not None:
        encontradas.update(detectar_senales(final, oficiales))
    dominio = final.dominio if final is not None else enlace.dominio
    imitado = marca_imitada(dominio, oficiales) or marca_imitada(enlace.dominio, oficiales)
    vistas = [enlace] + ([final] if final is not None else [])
    modalidad = modalidades.detectar(
        [f"{vista.dominio} {vista.ruta}" for vista in vistas], dominio, oficiales
    )
    dominio_origen = enlace.dominio if dominio != enlace.dominio else ""

    # A las fuentes va la dirección de destino sin parámetros de rastreo.
    activas = fuentes_activas()
    web = dominio if es_web_propia(dominio) else ""
    respuestas = consultar_fuentes(activas, (final or enlace).url, web=web)
    edad = edad_en_dias([enlace.dominio, dominio])
    # Solo la edad del registro público entra a la reputación propia.
    edad_registro = edad
    if edad is None and web:
        # Sin fecha en el registro público, como en los .pe, vale la que dan las fuentes.
        edad = edad_informada(respuestas)
    # Un análisis externo sin hallazgos vale más tiempo en una web antigua.
    respuestas = aplicar_vigencia(respuestas, timedelta(hours=horas_de_vigencia(edad)))
    resumen = resumir(respuestas)
    fuentes = [
        {
            "fuente": fuente.nombre,
            "titulo": fuente.titulo or fuente.nombre,
            "estado": respuesta.estado.value,
            "valor": respuesta.valor,
            # Por qué falló, con los códigos de `inteligencia`. No es dato del proveedor.
            **({"motivo": respuesta.motivo} if respuesta.motivo else {}),
        }
        for fuente, respuesta in zip(activas, respuestas, strict=True)
    ]

    # En el orden del registro, para que los motivos salgan siempre en el mismo orden.
    heuristicas = tuple(codigo for codigo in HEURISTICAS if codigo in encontradas)
    senales = Senales(
        tipo_entrada="enlace",
        heuristicas=heuristicas,
        marca=puntaje_marca(heuristicas, catalogo_disponible=bool(oficiales)),
        edad_dias=edad,
        fuentes=resumen.valor,
        fuentes_con_deteccion=resumen.confirmaciones,
        fuentes_en_duda=resumen.en_duda,
        confirmado_por_analista=reputacion.confirmado(
            (enlace.url, final.url if final else ""), dominio
        ),
    )
    veredicto = calcular(senales)
    reputacion.registrar(
        (final or enlace).url, dominio, heuristicas, senales.marca, edad_registro
    )
    redirecciones = destino.saltos if final is not None else None
    explicacion = explicar(
        veredicto, dominio, Recorrido(redirecciones, dominio_origen), estados_de(fuentes)
    )
    fecha = timezone.now()
    # Lo que contó cada fuente va aparte, a la caché técnica: dura un día y nunca llega
    # a `Analisis` ni a la caché de resultados.
    guardar_detalles(_consulta_de_detalles(fecha, dominio), activas, respuestas)
    datos = {
        "nivel": int(veredicto.nivel),
        "puntaje": veredicto.puntaje,
        "cobertura": veredicto.cobertura,
        "reglas": list(veredicto.reglas),
        "version": veredicto.version,
        "senales": asdict(senales),
        "fuentes": fuentes,
        "dominio": dominio,
        "dominio_origen": dominio_origen,
        "redirecciones": redirecciones,
        "marca_suplantada": marcas.get(imitado, ""),
        "modalidad": modalidad,
        "motivos": list(explicacion.motivos),
        "acciones": list(explicacion.acciones),
        "fecha": fecha.isoformat(),
    }
    return veredicto, datos


def _dominios_oficiales() -> dict[str, str]:
    """Dominios aprobados de las marcas activas del catálogo, con el nombre de su marca."""
    return dict(
        DominioOficial.objects.filter(
            estado=DominioOficial.Estado.APROBADO, marca__activa=True
        ).values_list("dominio", "marca__nombre")
    )


def detalles_de(analisis: Analisis) -> dict[str, dict]:
    """Lo que contó cada fuente en este análisis, por título. Vacío pasado un día."""
    return leer_detalles(_consulta_de_detalles(analisis.fecha_analisis, analisis.dominio))


def _consulta_de_detalles(fecha: datetime, dominio: str) -> str:
    # La fecha y el dominio son los mismos en el análisis y en sus copias de la caché.
    return f"{int(fecha.timestamp() * 1_000_000)}:{dominio}"


def estados_de(fuentes: list[dict]) -> tuple[tuple[str, str], ...]:
    """Título y estado de cada fuente, como los pide el motor de explicación.

    Una detección de menos de VALOR_CONFIRMA, como 1 o 2 motores de VirusTotal o una IP
    reportada, se muestra como sospecha.
    """
    return tuple((fuente["titulo"], _estado_visible(fuente)) for fuente in fuentes)


def _estado_visible(fuente: dict) -> str:
    valor = fuente.get("valor")
    if fuente["estado"] == "deteccion" and fuente.get("motivo") == MOTIVO_SIN_CATEGORIA:
        return "no_concluyente"
    if fuente["estado"] == "deteccion" and valor is not None and valor < VALOR_CONFIRMA:
        return "sospecha"
    if fuente["estado"] == "fallo" and fuente.get("motivo") in MOTIVOS_DE_CUPO:
        return "sin_cupo"
    return fuente["estado"]


def _senales(guardadas: dict) -> Senales:
    return Senales(**{**guardadas, "heuristicas": tuple(guardadas["heuristicas"])})


def _veredicto(datos: dict) -> Veredicto:
    """Recalcula el veredicto de una entrada de la caché y comprueba que coincide.

    Con las mismas señales y la misma versión el motor da el mismo resultado. Si no
    coincide, la entrada está dañada.
    """
    veredicto = calcular(_senales(datos["senales"]))
    if (int(veredicto.nivel), veredicto.puntaje) != (datos["nivel"], datos["puntaje"]):
        raise ValueError("La entrada de la caché no coincide con sus señales")
    datetime.fromisoformat(datos["fecha"])
    estados_de(datos["fuentes"])
    return veredicto


def _registrar(
    enlace: EnlaceNormalizado, datos: dict, veredicto: Veredicto, desde_cache: bool
) -> Analisis:
    return Analisis.objects.create(
        fecha_analisis=datetime.fromisoformat(datos["fecha"]),
        tipo_entrada=Analisis.Tipo.ENLACE,
        dominio=datos["dominio"],
        dominio_origen=datos["dominio_origen"],
        redirecciones=datos["redirecciones"],
        # El modelo la borra si el nivel es menor que Peligroso.
        url=enlace.url if veredicto.nivel >= Nivel.PELIGROSO else "",
        nivel=int(veredicto.nivel),
        puntaje=veredicto.puntaje,
        cobertura=veredicto.cobertura,
        version_reglas=veredicto.version,
        senales=datos["senales"],
        pesos={
            categoria: VERSION_INICIAL.pesos[categoria] for categoria in veredicto.valores
        },
        reglas=list(veredicto.reglas),
        fuentes=datos["fuentes"],
        # Las entradas de la caché anteriores a estos campos no los traen.
        marca_suplantada=datos.get("marca_suplantada", ""),
        modalidad=datos.get("modalidad", ""),
        desde_cache=desde_cache,
    )


def _enlace_final(url: str) -> EnlaceNormalizado | None:
    """La URL donde terminó el enlace, leída como la lee el navegador. None si no hay."""
    if not url:
        return None
    try:
        return normalizar(url)
    except URLInvalida:
        return None
