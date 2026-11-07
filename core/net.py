"""Política de salida a internet y única puerta por la que la plataforma sale a ella.

validar_url decide si un destino es permitido. pedir_url hace la petición: valida
cada destino, se conecta a la IP ya validada (el nombre se resuelve una sola vez por
salto, así no hay DNS rebinding) y manda el Host original. Este es el único módulo
que importa httpx: el analizador de URL y las fuentes externas usan solo pedir_url.
"""
import http.cookiejar
import ipaddress
import logging
import socket
import time
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlsplit

import httpx

logger = logging.getLogger(__name__)

# Valores de la política. Son controles de seguridad, no configuración: valen
# igual en todos los ambientes y por eso no se leen de variables de entorno.
ESQUEMAS_PERMITIDOS = frozenset({"http", "https"})
PUERTOS_PERMITIDOS = frozenset({80, 443})
METODOS_PERMITIDOS = frozenset({"GET", "HEAD"})
MAX_REDIRECCIONES = 3
TIMEOUT_CONEXION_SEGUNDOS = 2
# Un servidor puede mandar un byte por segundo y nunca disparar el timeout de lectura:
# este plazo corta la solicitud completa, redirecciones incluidas.
PLAZO_TOTAL_SEGUNDOS = 10
MAX_BYTES_RESPUESTA = 2 * 1024 * 1024
MAX_IPS_POR_DESTINO = 3
USER_AGENT = "AlertaSegura/1.0 (analisis de enlaces)"
CODIGOS_DE_REDIRECCION = frozenset({301, 302, 303, 307, 308})

RESULTADO_OK = "ok"
RESULTADO_BLOQUEADO = "destino_bloqueado"
RESULTADO_DEMASIADAS_REDIRECCIONES = "demasiadas_redirecciones"
RESULTADO_RESPUESTA_GRANDE = "respuesta_demasiado_grande"
RESULTADO_TIEMPO_AGOTADO = "tiempo_agotado"
RESULTADO_ERROR_DE_RED = "error_de_red"


class DestinoBloqueado(Exception):
    """El destino resuelve a una red que la plataforma nunca debe contactar.

    categoria es un código corto sin host ni IP, apto para la auditoría.
    """

    def __init__(self, mensaje, categoria="destino"):
        super().__init__(mensaje)
        self.categoria = categoria


@dataclass(frozen=True)
class RespuestaSegura:
    """Resultado de pedir_url. Solo con resultado "ok" la respuesta llegó completa."""

    resultado: str
    codigo_http: int | None = None
    # URL a la que se llegó, con el nombre original y no la IP. No va a la auditoría.
    url_final: str = ""
    cuerpo: bytes = b""
    encabezados: dict = field(default_factory=dict)
    saltos: int = 0
    # Por qué se bloqueó, cuando resultado es "destino_bloqueado".
    motivo: str = ""


def ip_es_publica(valor: str) -> bool:
    try:
        ip = ipaddress.ip_address(valor)
    except ValueError:
        return False
    # ::ffff:127.0.0.1 es loopback disfrazado de IPv6: se evalúa la IPv4 real.
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    # is_global excluye privadas, loopback, link-local (incluye 169.254.169.254,
    # metadata de nube), reservadas, CGNAT 100.64/10 y 0.0.0.0/8.
    return ip.is_global and not ip.is_multicast


def resolver_y_validar(host: str, puerto: int = 443) -> list[str]:
    """Resuelve el host y devuelve sus IPs solo si TODAS son públicas.

    Si una sola es privada se rechaza el destino completo: el sistema operativo
    podría elegir cualquiera de ellas al conectar.
    """
    try:
        resultados = socket.getaddrinfo(host, puerto, proto=socket.IPPROTO_TCP)
    except (socket.gaierror, UnicodeError) as exc:
        raise DestinoBloqueado(f"No resuelve: {host}", "no_resuelve") from exc

    ips = sorted({r[4][0] for r in resultados})
    if not ips:
        raise DestinoBloqueado(f"Sin direcciones: {host}", "no_resuelve")
    bloqueadas = [ip for ip in ips if not ip_es_publica(ip)]
    if bloqueadas:
        raise DestinoBloqueado(f"{host} resuelve a red no permitida", "red_no_permitida")
    return ips


def validar_url(url: str) -> list[str]:
    """Aplica la política completa a una URL: esquema, puerto y destino.

    Devuelve las IPs validadas del host. Cada redirección debe pasar otra vez
    por aquí antes de seguirla.
    """
    try:
        partes = urlsplit(url)
    except ValueError as exc:
        raise DestinoBloqueado("URL inválida", "url_invalida") from exc
    if partes.scheme not in ESQUEMAS_PERMITIDOS:
        raise DestinoBloqueado(f"Esquema no permitido: {partes.scheme or 'ninguno'}", "esquema")
    if not partes.hostname:
        raise DestinoBloqueado("La URL no tiene host", "sin_host")
    try:
        puerto = partes.port or (443 if partes.scheme == "https" else 80)
    except ValueError as exc:
        raise DestinoBloqueado("Puerto inválido", "puerto") from exc
    if puerto not in PUERTOS_PERMITIDOS:
        raise DestinoBloqueado(f"Puerto no permitido: {puerto}", "puerto")
    return resolver_y_validar(partes.hostname, puerto)


# --- Conexiones -------------------------------------------------------------

class _SinCookies(http.cookiejar.CookiePolicy):
    """Política que ni guarda ni envía cookies: la plataforma no tiene sesión con nadie."""

    netscape = True
    rfc2965 = False
    hide_cookie2 = True

    def set_ok(self, cookie, request):
        return False

    def return_ok(self, cookie, request):
        return False

    def domain_return_ok(self, domain, request):
        return False

    def path_return_ok(self, path, request):
        return False


def _crear_cliente(transporte):
    return httpx.Client(
        transport=transporte,
        follow_redirects=False,  # las redirecciones las sigue pedir_url, validando cada salto
        trust_env=False,  # HTTP_PROXY y similares no pueden desviar el tráfico
        timeout=httpx.Timeout(TIMEOUT_CONEXION_SEGUNDOS),
        # Sin conexiones persistentes: el pool de httpx agrupa por IP, y un salto a otro
        # nombre en la misma IP reutilizaría una conexión TLS validada para el primero.
        limits=httpx.Limits(max_keepalive_connections=0),
        cookies=http.cookiejar.CookieJar(policy=_SinCookies()),
        headers={"User-Agent": USER_AGENT},
        verify=True,
    )


def _literal_ip(ip: str) -> str:
    return f"[{ip}]" if ":" in ip else ip


def _auditar_bloqueo(categoria: str, salto: int) -> None:
    """Deja un evento anti-SSRF. Sin host, IP ni URL: solo la categoría y el salto."""
    # Se importa aquí: core.net lo importan módulos que se cargan antes que los modelos.
    from .auditoria import registrar_evento
    from .models import TipoEvento

    try:
        registrar_evento(
            TipoEvento.DESTINO_BLOQUEADO,
            objeto="core.net",
            motivo=f"destino bloqueado: {categoria}",
            detalle={"categoria": categoria, "salto": salto},
        )
    except Exception:
        # Una falla de la auditoría no debe convertir un bloqueo en una caída.
        logger.exception("No se pudo registrar el destino bloqueado en la auditoría")


def _pedir_a_una_ip(cliente, metodo, url, ip, limite):
    """Pide url a una IP ya validada. Devuelve (respuesta, None) o (None, location)."""
    partes = urlsplit(url)
    host = partes.hostname.encode("idna").decode("ascii")
    host_http = f"[{host}]" if ":" in host else host
    puerto = f":{partes.port}" if partes.port else ""
    consulta = f"?{partes.query}" if partes.query else ""
    # Se conecta a la IP; Host y SNI llevan el nombre original. Con https el
    # certificado se valida contra ese nombre. Sin userinfo ni fragmento.
    destino = f"{partes.scheme}://{_literal_ip(ip)}{puerto}{partes.path or '/'}{consulta}"
    with cliente.stream(
        metodo,
        destino,
        headers={"Host": f"{host_http}{puerto}"},
        extensions={"sni_hostname": host},
    ) as respuesta:
        if respuesta.status_code in CODIGOS_DE_REDIRECCION and "location" in respuesta.headers:
            return None, respuesta.headers["location"]
        cuerpo = bytearray()
        resultado = RESULTADO_OK
        if metodo != "HEAD":
            # iter_bytes entrega los bytes ya descomprimidos: el tope se cuenta sobre
            # lo que de verdad ocupa memoria, no sobre lo que viajó por la red.
            for trozo in respuesta.iter_bytes():
                if time.monotonic() > limite:
                    return RespuestaSegura(RESULTADO_TIEMPO_AGOTADO), None
                cuerpo.extend(trozo)
                if len(cuerpo) > MAX_BYTES_RESPUESTA:
                    del cuerpo[MAX_BYTES_RESPUESTA:]
                    resultado = RESULTADO_RESPUESTA_GRANDE
                    break
        return RespuestaSegura(
            resultado,
            codigo_http=respuesta.status_code,
            url_final=url,
            cuerpo=bytes(cuerpo),
            encabezados={k.lower(): v for k, v in respuesta.headers.items()},
        ), None


def _pedir_a_las_ips(cliente, metodo, url, ips, limite):
    """Prueba las IPs validadas en orden; solo reintenta si no se pudo conectar."""
    ultimo_fallo = None
    for ip in ips[:MAX_IPS_POR_DESTINO]:
        try:
            return _pedir_a_una_ip(cliente, metodo, url, ip, limite)
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            ultimo_fallo = exc
        except httpx.TimeoutException:
            return RespuestaSegura(RESULTADO_TIEMPO_AGOTADO), None
        except (httpx.HTTPError, UnicodeError):
            return RespuestaSegura(RESULTADO_ERROR_DE_RED), None
    if isinstance(ultimo_fallo, httpx.ConnectTimeout):
        return RespuestaSegura(RESULTADO_TIEMPO_AGOTADO), None
    return RespuestaSegura(RESULTADO_ERROR_DE_RED), None


def pedir_url(url: str, *, metodo: str = "GET", transporte=None) -> RespuestaSegura:
    """Pide una URL aplicando la política de salida y devuelve un RespuestaSegura.

    Cada destino, el inicial y los de las redirecciones, pasa por validar_url. Un destino
    bloqueado deja un evento de auditoría y el resultado dice "destino_bloqueado".
    Solo GET y HEAD, sin cookies. transporte existe para los tests (httpx.MockTransport):
    reemplaza la red, nunca la validación.
    """
    metodo = metodo.upper()
    if metodo not in METODOS_PERMITIDOS:
        raise ValueError("pedir_url solo admite GET y HEAD")
    limite = time.monotonic() + PLAZO_TOTAL_SEGUNDOS
    actual = url
    with _crear_cliente(transporte) as cliente:
        for salto in range(MAX_REDIRECCIONES + 1):
            if time.monotonic() > limite:
                return RespuestaSegura(RESULTADO_TIEMPO_AGOTADO, saltos=salto)
            try:
                ips = validar_url(actual)  # una sola resolución DNS por salto
            except DestinoBloqueado as exc:
                _auditar_bloqueo(exc.categoria, salto)
                return RespuestaSegura(RESULTADO_BLOQUEADO, saltos=salto, motivo=exc.categoria)
            respuesta, location = _pedir_a_las_ips(cliente, metodo, actual, ips, limite)
            if respuesta is not None:
                return _con_saltos(respuesta, salto)
            if salto == MAX_REDIRECCIONES:
                return RespuestaSegura(RESULTADO_DEMASIADAS_REDIRECCIONES, saltos=salto)
            try:
                actual = urljoin(actual, location)
            except ValueError:
                _auditar_bloqueo("url_invalida", salto + 1)
                return RespuestaSegura(RESULTADO_BLOQUEADO, saltos=salto + 1, motivo="url_invalida")
    raise AssertionError("inalcanzable")  # pragma: no cover


def _con_saltos(respuesta: RespuestaSegura, saltos: int) -> RespuestaSegura:
    return RespuestaSegura(
        respuesta.resultado, respuesta.codigo_http, respuesta.url_final, respuesta.cuerpo,
        respuesta.encabezados, saltos, respuesta.motivo,
    )
