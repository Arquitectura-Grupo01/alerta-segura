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
import zlib
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlsplit

import httpcore
import httpx

logger = logging.getLogger(__name__)

# Valores de la política. Son controles de seguridad, no configuración: valen
# igual en todos los ambientes y por eso no se leen de variables de entorno.
ESQUEMAS_PERMITIDOS = frozenset({"http", "https"})
PUERTOS_PERMITIDOS = frozenset({80, 443})
# POST solo existe para las APIs de las fuentes externas que lo exigen.
METODOS_PERMITIDOS = frozenset({"GET", "HEAD", "POST"})
# Cabeceras que quien llama no puede poner: las fija este módulo o romperían sus controles.
# Accept-Encoding: solo gzip se descomprime con tope.
ENCABEZADOS_PROHIBIDOS = frozenset({
    "host", "cookie", "user-agent", "accept-encoding", "content-length",
    "transfer-encoding", "connection", "proxy-authorization",
})
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


# --- Plazo total ------------------------------------------------------------
# httpx solo tiene timeouts por operación. Un servidor que manda las cabeceras de a un
# byte nunca los dispara y retiene la solicitud por horas. Estas clases acotan cada
# conexión, lectura y escritura al tiempo que le queda a la solicitud.

def _acotar(timeout, limite):
    restante = limite - time.monotonic()
    if restante <= 0:
        raise httpcore.ReadTimeout("Se agotó el plazo total de la solicitud")
    return restante if timeout is None else min(timeout, restante)


class _FlujoConPlazo(httpcore.NetworkStream):
    def __init__(self, flujo, limite):
        self._flujo = flujo
        self._limite = limite

    def read(self, max_bytes, timeout=None):
        return self._flujo.read(max_bytes, _acotar(timeout, self._limite))

    def write(self, buffer, timeout=None):
        self._flujo.write(buffer, _acotar(timeout, self._limite))

    def close(self):
        self._flujo.close()

    def start_tls(self, ssl_context, server_hostname=None, timeout=None):
        flujo = self._flujo.start_tls(ssl_context, server_hostname, _acotar(timeout, self._limite))
        return _FlujoConPlazo(flujo, self._limite)

    def get_extra_info(self, info):
        return self._flujo.get_extra_info(info)


class _RedConPlazo(httpcore.NetworkBackend):
    def __init__(self, limite):
        self._red = httpcore.SyncBackend()
        self._limite = limite

    def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        flujo = self._red.connect_tcp(
            host, port, _acotar(timeout, self._limite), local_address, socket_options,
        )
        return _FlujoConPlazo(flujo, self._limite)

    def sleep(self, seconds):
        self._red.sleep(seconds)


class _TransporteConPlazo(httpx.HTTPTransport):
    """Transporte de httpx que corta la solicitud cuando vence el plazo total."""

    def __init__(self, limite):
        super().__init__(verify=True, trust_env=False)
        # HTTPTransport no deja elegir la red de httpcore, así que se cambia su pool por
        # uno con _RedConPlazo. Si httpx cambia esto, falla el test del servidor que
        # gotea las cabeceras.
        self._pool = httpcore.ConnectionPool(
            ssl_context=httpx.create_ssl_context(trust_env=False),
            max_keepalive_connections=0,
            network_backend=_RedConPlazo(limite),
        )


def _crear_cliente(transporte, limite):
    return httpx.Client(
        # transporte solo llega desde los tests (httpx.MockTransport).
        transport=transporte or _TransporteConPlazo(limite),
        follow_redirects=False,  # las redirecciones las sigue pedir_url, validando cada salto
        trust_env=False,  # HTTP_PROXY y similares no pueden desviar el tráfico
        timeout=httpx.Timeout(TIMEOUT_CONEXION_SEGUNDOS),
        # Sin conexiones persistentes: el pool de httpx agrupa por IP, y un salto a otro
        # nombre en la misma IP reutilizaría una conexión TLS validada para el primero.
        limits=httpx.Limits(max_keepalive_connections=0),
        cookies=http.cookiejar.CookieJar(policy=_SinCookies()),
        # Solo gzip: es lo único que _leer_cuerpo sabe descomprimir con tope.
        headers={"User-Agent": USER_AGENT, "Accept-Encoding": "gzip"},
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


def _leer_cuerpo(respuesta, limite):
    """Lee el cuerpo hasta MAX_BYTES_RESPUESTA ya descomprimidos. Devuelve (cuerpo, resultado).

    Con gzip no se usa iter_bytes: httpx descomprime cada trozo entero antes de
    entregarlo, y 500 bytes con gzip dentro de gzip ocupan cientos de MB. Se leen los
    bytes crudos y se descomprime aquí con tope. Solo se acepta gzip, que es lo que se pide.
    """
    codificacion = respuesta.headers.get("content-encoding", "").strip().lower()
    if codificacion in ("gzip", "x-gzip"):
        descompresor = zlib.decompressobj(16 + zlib.MAX_WBITS)
        trozos = respuesta.iter_raw()
    elif codificacion in ("", "identity"):
        # Sin codificación, httpx no descomprime nada: iter_bytes da los bytes crudos.
        descompresor = None
        trozos = respuesta.iter_bytes()
    else:
        # br, deflate o varias capas ("gzip, gzip"): no se pidieron y no se leen.
        return b"", RESULTADO_ERROR_DE_RED
    cuerpo = bytearray()
    for trozo in trozos:
        if time.monotonic() > limite:
            return b"", RESULTADO_TIEMPO_AGOTADO
        if descompresor is not None:
            trozo = descompresor.decompress(trozo, MAX_BYTES_RESPUESTA + 1 - len(cuerpo))
        cuerpo.extend(trozo)
        if len(cuerpo) > MAX_BYTES_RESPUESTA:
            return bytes(cuerpo[:MAX_BYTES_RESPUESTA]), RESULTADO_RESPUESTA_GRANDE
    return bytes(cuerpo), RESULTADO_OK


def _pedir_a_una_ip(cliente, metodo, url, ip, limite, encabezados, datos):
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
        headers={**encabezados, "Host": f"{host_http}{puerto}"},
        data=datos,
        extensions={"sni_hostname": host},
    ) as respuesta:
        if respuesta.status_code in CODIGOS_DE_REDIRECCION and "location" in respuesta.headers:
            return None, respuesta.headers["location"]
        cuerpo, resultado = b"", RESULTADO_OK
        if metodo != "HEAD":
            cuerpo, resultado = _leer_cuerpo(respuesta, limite)
            if resultado in (RESULTADO_TIEMPO_AGOTADO, RESULTADO_ERROR_DE_RED):
                return RespuestaSegura(resultado), None
        return RespuestaSegura(
            resultado,
            codigo_http=respuesta.status_code,
            url_final=url,
            cuerpo=cuerpo,
            encabezados={k.lower(): v for k, v in respuesta.headers.items()},
        ), None


def _pedir_a_las_ips(cliente, metodo, url, ips, limite, encabezados, datos):
    """Prueba las IPs validadas, IPv4 primero; solo reintenta si no se pudo conectar."""
    ultimo_fallo = None
    # En orden alfabético muchas IPv6 quedan antes que las IPv4 ("2600:..." < "52...").
    # Sin salida IPv6, los tres intentos se gastaban sin probar ninguna IPv4.
    for ip in sorted(ips, key=lambda ip: ":" in ip)[:MAX_IPS_POR_DESTINO]:
        try:
            return _pedir_a_una_ip(cliente, metodo, url, ip, limite, encabezados, datos)
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            ultimo_fallo = exc
        except httpx.TimeoutException:
            return RespuestaSegura(RESULTADO_TIEMPO_AGOTADO), None
        except (httpx.HTTPError, httpx.InvalidURL, UnicodeError, zlib.error):
            # InvalidURL: httpx rechaza, por ejemplo, un carácter de control en la ruta.
            return RespuestaSegura(RESULTADO_ERROR_DE_RED), None
    if isinstance(ultimo_fallo, httpx.ConnectTimeout):
        return RespuestaSegura(RESULTADO_TIEMPO_AGOTADO), None
    return RespuestaSegura(RESULTADO_ERROR_DE_RED), None


def pedir_url(
    url: str,
    *,
    metodo: str = "GET",
    encabezados: dict[str, str] | None = None,
    datos: dict[str, str] | None = None,
    max_redirecciones: int | None = None,
    plazo_segundos: float | None = None,
    transporte=None,
) -> RespuestaSegura:
    """Pide una URL aplicando la política de salida y devuelve un RespuestaSegura.

    Cada destino, el inicial y los de las redirecciones, pasa por validar_url. Un destino
    bloqueado deja un evento de auditoría y el resultado dice "destino_bloqueado".
    GET, HEAD y POST, sin cookies. max_redirecciones y plazo_segundos solo pueden bajar
    los valores de la política, que son los que se usan si faltan: el analizador de URL
    los usa para repartir sus 3 saltos y su tiempo entre varias llamadas.

    encabezados y datos (un formulario, solo con POST) existen para las APIs de las
    fuentes externas, que llevan ahí su clave. Con cabeceras propias, o con POST, no se
    sigue ninguna redirección: la clave o el cuerpo nunca llegan a otro servidor.
    transporte existe para los tests (httpx.MockTransport): reemplaza la red, nunca la
    validación.
    """
    metodo = metodo.upper()
    if metodo not in METODOS_PERMITIDOS:
        raise ValueError("pedir_url solo admite GET, HEAD y POST")
    if datos is not None and metodo != "POST":
        raise ValueError("Solo un POST lleva datos")
    encabezados = dict(encabezados or {})
    prohibidos = {nombre.lower() for nombre in encabezados} & ENCABEZADOS_PROHIBIDOS
    if prohibidos:
        raise ValueError(f"Cabeceras que pedir_url no permite cambiar: {sorted(prohibidos)}")
    sin_redirecciones = metodo == "POST" or bool(encabezados)
    if max_redirecciones is None:
        max_redirecciones = 0 if sin_redirecciones else MAX_REDIRECCIONES
    if sin_redirecciones and max_redirecciones:
        raise ValueError("Con POST o con cabeceras propias no se siguen redirecciones")
    if plazo_segundos is None:
        plazo_segundos = PLAZO_TOTAL_SEGUNDOS
    if not 0 <= max_redirecciones <= MAX_REDIRECCIONES:
        raise ValueError(f"max_redirecciones va de 0 a {MAX_REDIRECCIONES}")
    if not 0 < plazo_segundos <= PLAZO_TOTAL_SEGUNDOS:
        raise ValueError(f"plazo_segundos va de más de 0 a {PLAZO_TOTAL_SEGUNDOS}")
    limite = time.monotonic() + plazo_segundos
    actual = url
    with _crear_cliente(transporte, limite) as cliente:
        for salto in range(max_redirecciones + 1):
            if time.monotonic() > limite:
                return RespuestaSegura(RESULTADO_TIEMPO_AGOTADO, saltos=salto)
            try:
                ips = validar_url(actual)  # una sola resolución DNS por salto
            except DestinoBloqueado as exc:
                _auditar_bloqueo(exc.categoria, salto)
                return RespuestaSegura(RESULTADO_BLOQUEADO, saltos=salto, motivo=exc.categoria)
            respuesta, location = _pedir_a_las_ips(
                cliente, metodo, actual, ips, limite, encabezados, datos
            )
            if respuesta is not None:
                return _con_saltos(respuesta, salto)
            if salto == max_redirecciones:
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
