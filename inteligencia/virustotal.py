"""VirusTotal: el último análisis que sus motores antivirus hicieron de la dirección.

Solo se consultan análisis que ya existen; nunca se envía una dirección nueva a
escanear, porque un envío queda visible para su comunidad. Es una de las dos fuentes
que pueden decir «sin detecciones», y solo con un análisis vigente. Si la dirección
exacta no tiene uno, sirve el de la web completa cuando es conocida y está limpia.
La API pública prohíbe el uso comercial y solo sirve para enriquecer.
"""

import base64
from collections import Counter
from datetime import UTC, datetime, timedelta
from urllib.parse import quote

from inteligencia.fuentes import (
    MOTIVO_SIN_CATEGORIA,
    VIGENCIA_MAXIMA,
    FalloDeFuente,
    Fuente,
    Respuesta,
    fecha_iso,
)

URL_BASE = "https://www.virustotal.com/api/v3/urls/"
URL_WEB = "https://www.virustotal.com/api/v3/domains/"
# Con un análisis de la dirección de hoy no hace falta gastar otra consulta en la web.
ANALISIS_DE_HOY = timedelta(hours=24)
# Edad mínima para que la reputación de la web completa cuente.
DIAS_WEB_CONOCIDA = 365
PREFIJO_WEB = "web:"
# Confirma (100) cuando 3 motores o más coinciden en el tipo de amenaza. Que 3 la marquen
# como «malicious» sin decir de qué tipo no confirma nada: pasa con webs legítimas, como
# la de una organización que publica archivos de prueba para antivirus. Eso y 1 o 2
# motores son una sospecha (50). Ver docs/decisiones.md.
MOTORES_PARA_CONFIRMAR = 3
# Cómo nombra cada motor el tipo de amenaza y el código con que lo muestra el motor de
# explicación. «malicious» o «suspicious» a secas no dicen el tipo.
TIPO_DE_RESULTADO = {"phishing": "pagina_falsa", "malware": "programa_danino"}
VALOR_SOSPECHA = 50


class VirusTotal(Fuente):
    nombre = "virustotal"
    titulo = "VirusTotal"
    requiere_clave = True
    cuota_diaria = 500
    cuota_por_minuto = 4
    usa_web = True

    def _consultar(self, url: str, web: str = "") -> Respuesta:
        detalle, motores, analizado = self._direccion(url)
        # Una detección cuenta aunque el análisis sea viejo; uno limpio, solo si es vigente.
        if motores >= MOTORES_PARA_CONFIRMAR and detalle.get("tipos"):
            return self.deteccion(datos=detalle)
        if motores >= MOTORES_PARA_CONFIRMAR:
            return self.deteccion(
                VALOR_SOSPECHA, datos={**detalle, "sin_categoria": True},
                motivo=MOTIVO_SIN_CATEGORIA,
            )
        if motores > 0:
            return self.deteccion(VALOR_SOSPECHA, datos=detalle)
        # Casi nadie analiza cada página de una web conocida: su reputación completa
        # sirve cuando el análisis de la dirección falta o es viejo.
        reciente = analizado is not None and datetime.now(UTC) - analizado < ANALISIS_DE_HOY
        if web and not reciente:
            de_la_web, fecha_de_la_web = self._web(web, _fecha_de_iso(detalle.get("primera_vez")))
            detalle |= de_la_web
            if fecha_de_la_web is not None:
                analizado = max(analizado or fecha_de_la_web, fecha_de_la_web)
        return self.sin_detecciones(analizado, detalle)

    def _direccion(self, url: str) -> tuple[dict, int, datetime | None]:
        """Detalle, motores que la marcan y fecha del análisis de la dirección exacta."""
        # El identificador de una dirección es la dirección en base64 para URL, sin «=».
        identificador = base64.urlsafe_b64encode(url.encode()).decode().rstrip("=")
        codigo, datos = self.pedir_json(
            URL_BASE + identificador,
            encabezados={"x-apikey": self.clave},
            codigos=(200, 404),
        )
        if codigo == 404:
            return {}, 0, None
        atributos = datos["data"]["attributes"]
        conteo = atributos["last_analysis_stats"]
        motores = conteo["malicious"]
        if not _es_cuenta(motores):
            raise FalloDeFuente()
        detalle = {**_detalle(atributos, conteo), "tipos": _tipos(atributos)}
        return detalle, motores, _fecha(atributos.get("last_analysis_date"))

    def _web(self, web: str, vista_desde: datetime | None = None) -> tuple[dict, datetime | None]:
        """Reputación de la web completa y, si es conocida y limpia, la fecha de su análisis.

        Cuenta como limpia solo una web sin ningún antivirus en contra, con más de un año
        y que figura en algún ranking de webs visitadas. Si la consulta falla, no hay
        reputación y la respuesta de la dirección queda como estaba.

        Los `.pe` no publican su fecha de creación. Ahí vale desde cuándo VirusTotal
        conoce la web: la primera vez que vio la dirección (`vista_desde`) o su ranking
        más antiguo. Es un mínimo: la web existe al menos desde entonces.

        La API pública da 4 consultas por minuto. La reputación de una web se guarda un
        día en la caché técnica, así sus demás páginas no gastan otra consulta.
        """
        guardada = self.leer_cruda(PREFIJO_WEB + web)
        if isinstance(guardada, dict):
            return _reputacion(guardada, vista_desde)
        if not self.otra_consulta():
            return {}, None
        try:
            codigo, datos = self.pedir_json(
                URL_WEB + quote(web, safe=""),
                encabezados={"x-apikey": self.clave},
                codigos=(200, 400, 404),
            )
            if codigo != 200:
                return {}, None
            atributos = datos["data"]["attributes"]
            conteo = atributos["last_analysis_stats"]
            if not isinstance(conteo, dict):
                return {}, None
            rankings = atributos.get("popularity_ranks")
        except (FalloDeFuente, KeyError, TypeError, AttributeError):
            return {}, None
        # Solo lo que se usa, nunca el informe entero.
        resumen = {
            "peligrosa": conteo.get("malicious"),
            "sospechosa": conteo.get("suspicious"),
            "total": sum(valor for valor in conteo.values() if _es_cuenta(valor)),
            "creada": atributos.get("creation_date"),
            "analizada": atributos.get("last_analysis_date"),
            "en_ranking": isinstance(rankings, dict) and bool(rankings),
            "ranking_desde": _ranking_mas_antiguo(rankings),
        }
        self.guardar_cruda(PREFIJO_WEB + web, resumen)
        return _reputacion(resumen, vista_desde)


def _reputacion(resumen: dict, vista_desde: datetime | None = None) -> tuple[dict, datetime | None]:
    """Detalle de la web y, si es conocida y limpia, la fecha de su análisis."""
    peligrosa, sospechosa = resumen.get("peligrosa"), resumen.get("sospechosa")
    ahora = datetime.now(UTC)
    creada = _fecha(resumen.get("creada"))
    conocida_desde = [
        fecha for fecha in (vista_desde, _fecha(resumen.get("ranking_desde")))
        if fecha is not None and fecha <= ahora
    ]
    edad = None
    detalle_de_edad = {}
    if creada is not None and creada <= ahora:
        edad = (ahora - creada).days
        detalle_de_edad = {"edad_web_dias": edad}
    elif conocida_desde:
        edad = (ahora - min(conocida_desde)).days
        detalle_de_edad = {"conocida_dias": edad}
    en_ranking = resumen.get("en_ranking") is True
    detalle = {
        "web_peligrosa": peligrosa,
        "web_sospechosa": sospechosa,
        "web_total": resumen.get("total") or None,
        "en_ranking": en_ranking or None,
        **detalle_de_edad,
    }
    limpia = _es_cuenta(peligrosa) and _es_cuenta(sospechosa) and peligrosa + sospechosa == 0
    conocida = en_ranking and edad is not None and edad > DIAS_WEB_CONOCIDA
    analizado = _fecha(resumen.get("analizada"))
    vigente = analizado is not None and datetime.now(UTC) - analizado <= VIGENCIA_MAXIMA
    if not (limpia and conocida and vigente):
        return detalle, None
    return {**detalle, "por_la_web": True}, analizado


def _detalle(atributos: dict, conteo: dict) -> dict:
    """Lo que se muestra en el detalle técnico. Todo es opcional: lo que falta se omite."""
    cuentas = [valor for valor in conteo.values() if _es_cuenta(valor)]
    votos = atributos.get("total_votes")
    votos = votos if isinstance(votos, dict) else {}
    amenazas = atributos.get("threat_names")
    return {
        "motores_peligrosa": conteo.get("malicious"),
        "motores_sospechosa": conteo.get("suspicious"),
        # Sin motores que respondieron no hay «de cuántos».
        "motores_total": sum(cuentas) or None,
        "analizado": fecha_iso(atributos.get("last_analysis_date")),
        "primera_vez": fecha_iso(atributos.get("first_submission_date")),
        "votos_peligrosa": votos.get("malicious") or None,
        "votos_confiable": votos.get("harmless") or None,
        "amenazas": amenazas if isinstance(amenazas, list) else None,
    }


def _tipos(atributos: dict) -> list[str]:
    """Tipos de amenaza en que coinciden MOTORES_PARA_CONFIRMAR motores o más."""
    resultados = atributos.get("last_analysis_results")
    if not isinstance(resultados, dict):
        return []
    cuenta = Counter()
    for resultado in resultados.values():
        if isinstance(resultado, dict) and resultado.get("category") == "malicious":
            nombre = resultado.get("result")
            nombre = nombre.strip().lower() if isinstance(nombre, str) else ""
            tipo = TIPO_DE_RESULTADO.get(nombre)
            if tipo:
                cuenta[tipo] += 1
    return [
        tipo for tipo in TIPO_DE_RESULTADO.values() if cuenta[tipo] >= MOTORES_PARA_CONFIRMAR
    ]


def _es_cuenta(valor) -> bool:
    return isinstance(valor, int) and not isinstance(valor, bool) and valor >= 0


def _fecha(segundos) -> datetime | None:
    if not _es_cuenta(segundos):
        return None
    try:
        return datetime.fromtimestamp(segundos, UTC)
    except (ValueError, OverflowError, OSError):
        return None


def _fecha_de_iso(texto) -> datetime | None:
    try:
        return datetime.fromisoformat(texto) if isinstance(texto, str) and texto else None
    except ValueError:
        return None


def _ranking_mas_antiguo(rankings) -> int | None:
    """Fecha, en segundos, del ranking más antiguo en que figura la web."""
    if not isinstance(rankings, dict):
        return None
    fechas = [
        ranking.get("timestamp") for ranking in rankings.values() if isinstance(ranking, dict)
    ]
    fechas = [fecha for fecha in fechas if _es_cuenta(fecha) and fecha > 0]
    return min(fechas) if fechas else None
