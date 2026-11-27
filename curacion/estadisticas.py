"""Estadísticas del panel de la consola (tarea 53).

Solo agregados con el ORM (`values`, `annotate`, `Count`), sin SQL armado a mano: un filtro
por dominio con comillas no puede romper ni alterar la consulta. Los días se cuentan en hora
de Lima. Solo datos propios: de las fuentes externas se usa el estado que guardó cada
análisis, nunca su respuesta. Por departamento se ocultan los grupos de menos de 5 análisis.

Vive en curacion porque es la única app que puede leer análisis, reportes y auditoría.
"""
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.db.models import Avg, Count, Max, Q
from django.db.models.functions import TruncDate

from analisis.models import Analisis
from analisis.orquestador import estados_de
from core.entrada import CONSULTAS_EXTERNAS_POR_HORA, presupuesto_externo_usado
from core.models import EventoAuditoria, TipoEvento
from inteligencia.fuentes import estado_operativo
from motor.modalidades import MODALIDADES
from motor.riesgo import Nivel

from .models import ReporteDesacuerdo, SolicitudRevision

LIMA = ZoneInfo("America/Lima")
DIAS_POR_DEFECTO = 30
MAX_DIAS = 366
TOP = 10
MINIMO_POR_REGION = 5
ULTIMOS = 15
NIVELES = tuple(Nivel)
TITULOS_MODALIDAD = {modalidad.clave: modalidad.titulo for modalidad in MODALIDADES}
# Estados de una fuente en un análisis, como los muestra el detalle técnico.
ESTADOS_FUENTE = (
    ("deteccion", "Detección"),
    ("sospecha", "Sospecha"),
    ("no_concluyente", "No concluyente"),
    ("sin_detecciones", "Sin detecciones"),
    ("desconocido", "Sin información"),
    ("sin_cupo", "Sin cupo"),
    ("fallo", "No respondió"),
)
TIPOS_DE_SEGURIDAD = (
    TipoEvento.INICIO_SESION,
    TipoEvento.FALLO_SESION,
    TipoEvento.BLOQUEO_CUENTA,
    TipoEvento.CAMBIO_CUENTA,
    TipoEvento.DESTINO_BLOQUEADO,
    TipoEvento.FALLO_FUENTE,
    TipoEvento.ALERTA_SEGURIDAD,
)


@dataclass(frozen=True)
class Filtros:
    desde: date
    hasta: date
    tipo: str = ""
    dominio: str = ""

    @classmethod
    def por_defecto(cls, hoy: date | None = None) -> "Filtros":
        hoy = hoy or datetime.now(LIMA).date()
        return cls(desde=hoy - timedelta(days=DIAS_POR_DEFECTO - 1), hasta=hoy)

    @property
    def inicio(self) -> datetime:
        """Medianoche de Lima del primer día, inclusive."""
        return datetime.combine(self.desde, time.min, tzinfo=LIMA)

    @property
    def fin(self) -> datetime:
        """Medianoche de Lima del día siguiente al último, exclusive."""
        return datetime.combine(self.hasta + timedelta(days=1), time.min, tzinfo=LIMA)

    @property
    def dias(self) -> int:
        return (self.hasta - self.desde).days + 1


def analisis_filtrados(filtros: Filtros):
    consulta = Analisis.objects.filter(fecha__gte=filtros.inicio, fecha__lt=filtros.fin)
    if filtros.tipo:
        consulta = consulta.filter(tipo_entrada=filtros.tipo)
    if filtros.dominio:
        # icontains del ORM: el texto va como parámetro, nunca pegado al SQL.
        consulta = consulta.filter(dominio__icontains=filtros.dominio)
    return consulta


def _porcentaje(parte: int, total: int) -> float:
    return round(100 * parte / total, 1) if total else 0.0


def resumen(consulta) -> dict:
    totales = consulta.aggregate(
        total=Count("id"),
        desde_cache=Count("id", filter=Q(desde_cache=True)),
        dominios=Count("dominio", distinct=True),
        puntaje=Avg("puntaje"),
        cobertura=Avg("cobertura"),
        **{f"nivel_{nivel.value}": Count("id", filter=Q(nivel=nivel)) for nivel in NIVELES},
    )
    total = totales["total"]
    por_nivel = [
        {
            "nivel": nivel.value,
            "texto": nivel.texto,
            "cantidad": totales[f"nivel_{nivel.value}"],
            "porcentaje": _porcentaje(totales[f"nivel_{nivel.value}"], total),
        }
        for nivel in NIVELES
    ]
    riesgosos = sum(fila["cantidad"] for fila in por_nivel if fila["nivel"] >= Nivel.PELIGROSO)
    return {
        "total": total,
        "dominios": totales["dominios"],
        "desde_cache": totales["desde_cache"],
        "porcentaje_cache": _porcentaje(totales["desde_cache"], total),
        "puntaje_promedio": round(totales["puntaje"] or 0, 1),
        "cobertura_promedio": round(totales["cobertura"] or 0, 1),
        "riesgosos": riesgosos,
        "porcentaje_riesgosos": _porcentaje(riesgosos, total),
        "por_nivel": por_nivel,
    }


def por_dia(consulta, filtros: Filtros) -> list[dict]:
    """Análisis por día de Lima y por nivel, con los días sin análisis en cero."""
    filas = (
        consulta.order_by()
        .annotate(dia=TruncDate("fecha", tzinfo=LIMA))
        .values("dia", "nivel")
        .annotate(cantidad=Count("id"))
    )
    conteo = {(fila["dia"], fila["nivel"]): fila["cantidad"] for fila in filas}
    dias = []
    for numero in range(filtros.dias):
        dia = filtros.desde + timedelta(days=numero)
        niveles = [conteo.get((dia, nivel.value), 0) for nivel in NIVELES]
        dias.append({"dia": dia, "niveles": niveles, "total": sum(niveles)})
    return dias


def top_dominios(consulta, nivel_minimo: int | None = None) -> list[dict]:
    if nivel_minimo is not None:
        consulta = consulta.filter(nivel__gte=nivel_minimo)
    return list(
        consulta.values("dominio")
        .annotate(cantidad=Count("id"), nivel=Max("nivel"))
        .order_by("-cantidad", "dominio")[:TOP]
    )


def top_urls(consulta) -> list[dict]:
    """Direcciones completas más consultadas. Solo existen en análisis Peligroso o más:
    en los demás se guarda solo el dominio, porque una dirección puede traer datos de la
    persona (AGENTS.md)."""
    return list(
        consulta.exclude(url="")
        .values("url", "dominio")
        .annotate(cantidad=Count("id"), nivel=Max("nivel"))
        .order_by("-cantidad", "url")[:TOP]
    )


def top_marcas(consulta) -> list[dict]:
    return list(
        consulta.exclude(marca_suplantada="")
        .values("marca_suplantada")
        .annotate(cantidad=Count("id"), dominios=Count("dominio", distinct=True))
        .order_by("-cantidad", "marca_suplantada")[:TOP]
    )


def top_modalidades(consulta) -> list[dict]:
    filas = (
        consulta.exclude(modalidad="")
        .values("modalidad")
        .annotate(cantidad=Count("id"))
        .order_by("-cantidad", "modalidad")[:TOP]
    )
    return [
        {**fila, "titulo": TITULOS_MODALIDAD.get(fila["modalidad"], fila["modalidad"])}
        for fila in filas
    ]


def senales_frecuentes(consulta) -> dict:
    """Reglas del motor y heurísticas de la dirección más frecuentes.

    Viven en campos JSON, así que se cuentan en Python, leyendo solo esas dos columnas.
    """
    reglas, heuristicas = Counter(), Counter()
    for reglas_activas, senales in consulta.values_list("reglas", "senales").iterator():
        reglas.update(reglas_activas or [])
        heuristicas.update((senales or {}).get("heuristicas") or [])
    return {
        "reglas": [{"codigo": c, "cantidad": n} for c, n in reglas.most_common(TOP)],
        "heuristicas": [{"codigo": c, "cantidad": n} for c, n in heuristicas.most_common(TOP)],
    }


def fuentes_en_analisis(consulta) -> list[dict]:
    """Cuántas veces cada fuente dio cada estado en los análisis del período."""
    conteo: dict[str, Counter] = {}
    for fuentes in consulta.values_list("fuentes", flat=True).iterator():
        for titulo, estado in estados_de(fuentes or []):
            conteo.setdefault(titulo, Counter())[estado] += 1
    filas = []
    for titulo in sorted(conteo):
        estados = conteo[titulo]
        total = sum(estados.values())
        filas.append({
            "titulo": titulo,
            "total": total,
            "estados": [estados.get(clave, 0) for clave, _ in ESTADOS_FUENTE],
            "respondio": _porcentaje(total - estados.get("fallo", 0) - estados.get("sin_cupo", 0),
                                     total),
        })
    return filas


def por_departamento(consulta) -> dict:
    """Análisis por departamento. Los grupos de menos de MINIMO_POR_REGION se suman en
    «ocultos» para que una región con pocos casos no identifique a nadie."""
    filas = (
        consulta.order_by().values("departamento").annotate(cantidad=Count("id"))
        .order_by("-cantidad", "departamento")
    )
    visibles, ocultos, grupos_ocultos = [], 0, 0
    for fila in filas:
        if fila["cantidad"] >= MINIMO_POR_REGION:
            visibles.append({
                "departamento": fila["departamento"] or "Sin dato",
                "cantidad": fila["cantidad"],
            })
        else:
            ocultos += fila["cantidad"]
            grupos_ocultos += 1
    return {"visibles": visibles, "ocultos": ocultos, "grupos_ocultos": grupos_ocultos}


def reportes(filtros: Filtros) -> dict:
    """Reportes «Sí, era estafa» y «No, era legítimo» recibidos en el período."""
    consulta = ReporteDesacuerdo.objects.filter(fecha__gte=filtros.inicio, fecha__lt=filtros.fin)
    if filtros.tipo:
        consulta = consulta.filter(analisis__tipo_entrada=filtros.tipo)
    if filtros.dominio:
        consulta = consulta.filter(analisis__dominio__icontains=filtros.dominio)
    totales = consulta.aggregate(
        total=Count("id"),
        era_estafa=Count("id", filter=Q(tipo=ReporteDesacuerdo.Tipo.ERA_ESTAFA)),
        era_legitimo=Count("id", filter=Q(tipo=ReporteDesacuerdo.Tipo.ERA_LEGITIMO)),
        pendientes=Count("id", filter=Q(estado=ReporteDesacuerdo.Estado.PENDIENTE)),
        confirmados=Count("id", filter=Q(decision="confirmar")),
        descartados=Count("id", filter=Q(decision="descartar")),
        falsos_positivos=Count("id", filter=Q(decision="falso_positivo")),
    )
    ultimos = consulta.select_related("analisis").order_by("-fecha")[:ULTIMOS]
    return {**totales, "ultimos": list(ultimos)}


def pedidos(filtros: Filtros) -> dict:
    """Pedidos de «Mi web aparece por error» recibidos en el período."""
    consulta = SolicitudRevision.objects.filter(fecha__gte=filtros.inicio, fecha__lt=filtros.fin)
    if filtros.dominio:
        consulta = consulta.filter(dominio__icontains=filtros.dominio)
    totales = consulta.aggregate(
        total=Count("id"),
        pendientes=Count("id", filter=Q(estado=SolicitudRevision.Estado.PENDIENTE)),
    )
    return {**totales, "ultimos": list(consulta.order_by("-fecha")[:ULTIMOS])}


def seguridad(filtros: Filtros) -> dict:
    """Eventos de auditoría del período. Solo lo ve un administrador."""
    consulta = EventoAuditoria.objects.filter(fecha__gte=filtros.inicio, fecha__lt=filtros.fin)
    conteo = dict(consulta.order_by().values_list("tipo").annotate(cantidad=Count("id")))
    por_tipo = [
        {"tipo": tipo.value, "texto": tipo.label, "cantidad": conteo.get(tipo.value, 0)}
        for tipo in TipoEvento
    ]
    ultimos = (
        consulta.filter(tipo__in=TIPOS_DE_SEGURIDAD).select_related("usuario")[:ULTIMOS]
    )
    return {"por_tipo": por_tipo, "ultimos": list(ultimos)}


def fuentes_en_vivo() -> dict:
    """Estado de cada fuente ahora mismo: clave, circuito y cuota del día."""
    usadas = presupuesto_externo_usado()
    return {
        "fuentes": estado_operativo(),
        "presupuesto_usado": usadas,
        "presupuesto_total": CONSULTAS_EXTERNAS_POR_HORA,
        "presupuesto_porcentaje": _porcentaje(usadas, CONSULTAS_EXTERNAS_POR_HORA),
    }


def pendientes() -> dict:
    """Lo que espera a un analista, sin importar el período."""
    reportes_pendientes = ReporteDesacuerdo.objects.filter(
        estado=ReporteDesacuerdo.Estado.PENDIENTE,
    )
    pedidos_pendientes = SolicitudRevision.objects.filter(estado=SolicitudRevision.Estado.PENDIENTE)
    webs = set(reportes_pendientes.values_list("analisis__dominio", flat=True))
    webs |= set(pedidos_pendientes.values_list("dominio", flat=True))
    return {
        "reportes": reportes_pendientes.count(),
        "pedidos": pedidos_pendientes.count(),
        "casos": len(webs),
    }


def todo(filtros: Filtros, *, con_seguridad: bool) -> dict:
    consulta = analisis_filtrados(filtros)
    datos = {
        "resumen": resumen(consulta),
        "por_dia": por_dia(consulta, filtros),
        "top_dominios": top_dominios(consulta),
        "top_maliciosos": top_dominios(consulta, nivel_minimo=Nivel.PELIGROSO),
        "top_urls": top_urls(consulta),
        "top_marcas": top_marcas(consulta),
        "top_modalidades": top_modalidades(consulta),
        "senales": senales_frecuentes(consulta),
        "fuentes": fuentes_en_analisis(consulta),
        "departamentos": por_departamento(consulta),
        "reportes": reportes(filtros),
        "pedidos": pedidos(filtros),
        "pendientes": pendientes(),
        "en_vivo": fuentes_en_vivo(),
        "estados_fuente": [texto for _, texto in ESTADOS_FUENTE],
    }
    if con_seguridad:
        datos["seguridad"] = seguridad(filtros)
    return datos
