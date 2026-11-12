import gzip
import socket
import threading
import time
import tracemalloc
import zlib
from pathlib import Path

import httpx
import pytest

from core import net
from core.models import EventoAuditoria, TipoEvento
from core.net import (
    MAX_BYTES_RESPUESTA,
    RESULTADO_BLOQUEADO,
    RESULTADO_DEMASIADAS_REDIRECCIONES,
    RESULTADO_ERROR_DE_RED,
    RESULTADO_OK,
    RESULTADO_RESPUESTA_GRANDE,
    RESULTADO_TIEMPO_AGOTADO,
    DestinoBloqueado,
    pedir_url,
    validar_url,
)

BASE_DIR = Path(__file__).resolve().parent.parent


def resolver(monkeypatch, mapa):
    """Hace que los nombres de mapa resuelvan a las IPs dadas. Una IP escrita como
    número ("2130706433", "0x7f000001") sigue pasando por el resolutor real."""
    real = socket.getaddrinfo

    def falso(host, puerto, *args, **kwargs):
        if host in mapa:
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, puerto)) for ip in mapa[host]]
        return real(host, puerto, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", falso)


def servidor(rutas):
    """MockTransport que responde según (Host, ruta) y guarda cada petición recibida."""
    peticiones = []

    def manejar(peticion):
        peticiones.append(peticion)
        return rutas.get((peticion.headers["host"], peticion.url.path), httpx.Response(404))

    return httpx.MockTransport(manejar), peticiones


def redireccion(destino, **encabezados):
    return httpx.Response(302, headers={"Location": destino, **encabezados})


class Trozos(httpx.SyncByteStream):
    """Cuerpo que se entrega por trozos y se descomprime al leerlo, como en la red."""

    def __init__(self, trozos, pausa=0):
        self.trozos = trozos
        self.pausa = pausa

    def __iter__(self):
        for trozo in self.trozos:
            time.sleep(self.pausa)
            yield trozo


# --- Conexión a la IP validada ---------------------------------------------

def test_se_conecta_a_la_ip_validada_con_el_host_original(monkeypatch):
    resolver(monkeypatch, {"ok.example": ["8.8.8.8"]})
    transporte, peticiones = servidor({("ok.example", "/a"): httpx.Response(200, content=b"hola")})
    respuesta = pedir_url("https://ok.example/a?x=1", transporte=transporte)
    assert respuesta.resultado == RESULTADO_OK
    assert (respuesta.codigo_http, respuesta.cuerpo) == (200, b"hola")
    assert respuesta.url_final == "https://ok.example/a?x=1"
    peticion = peticiones[0]
    assert peticion.url.host == "8.8.8.8"
    assert peticion.headers["host"] == "ok.example"
    assert peticion.url.query == b"x=1"
    # El certificado se valida contra el nombre original, no contra la IP.
    assert peticion.extensions["sni_hostname"] == "ok.example"


def test_un_puerto_explicito_viaja_en_el_host(monkeypatch):
    resolver(monkeypatch, {"ok.example": ["8.8.8.8"]})
    transporte, peticiones = servidor({("ok.example:80", "/"): httpx.Response(200)})
    assert pedir_url("http://ok.example:80/", transporte=transporte).resultado == RESULTADO_OK
    assert peticiones[0].headers["host"] == "ok.example:80"


def test_una_ip_ipv6_se_conecta_entre_corchetes(monkeypatch):
    resolver(monkeypatch, {"v6.example": ["2606:4700:4700::1111"]})
    transporte, peticiones = servidor({("v6.example", "/"): httpx.Response(200)})
    assert pedir_url("https://v6.example/", transporte=transporte).resultado == RESULTADO_OK
    assert peticiones[0].url.host == "2606:4700:4700::1111"


def test_las_credenciales_de_la_url_no_se_envian(monkeypatch):
    resolver(monkeypatch, {"ok.example": ["8.8.8.8"]})
    transporte, peticiones = servidor({("ok.example", "/a"): httpx.Response(200)})
    pedir_url("http://usuario:clave@ok.example/a#parte", transporte=transporte)
    assert "authorization" not in peticiones[0].headers
    assert peticiones[0].url.userinfo == b""
    assert peticiones[0].headers["user-agent"] == net.USER_AGENT


def test_si_una_ip_no_conecta_prueba_la_siguiente_ya_validada(monkeypatch):
    resolver(monkeypatch, {"ok.example": ["1.1.1.1", "8.8.8.8"]})
    vistas = []

    def manejar(peticion):
        vistas.append(peticion.url.host)
        if peticion.url.host == "1.1.1.1":
            raise httpx.ConnectError("sin conexión")
        return httpx.Response(200)

    respuesta = pedir_url("http://ok.example/", transporte=httpx.MockTransport(manejar))
    assert respuesta.resultado == RESULTADO_OK
    assert vistas == ["1.1.1.1", "8.8.8.8"]


def test_prueba_las_ipv4_antes_que_las_ipv6(monkeypatch):
    ips = ["2606:4700::1", "2606:4700::2", "2606:4700::3", "52.0.0.1"]
    resolver(monkeypatch, {"doble.example": ips})
    vistas = []

    def manejar(peticion):
        vistas.append(peticion.url.host)
        return httpx.Response(200)

    respuesta = pedir_url("http://doble.example/", transporte=httpx.MockTransport(manejar))
    assert respuesta.resultado == RESULTADO_OK
    assert vistas == ["52.0.0.1"]


def test_una_url_con_un_caracter_de_control_es_un_error_de_red(monkeypatch):
    resolver(monkeypatch, {"ok.example": ["8.8.8.8"]})
    transporte, peticiones = servidor({})
    respuesta = pedir_url("http://ok.example/a\x7fb", transporte=transporte)
    assert respuesta.resultado == RESULTADO_ERROR_DE_RED
    assert peticiones == []


@pytest.mark.parametrize("error,esperado", [
    (httpx.ConnectError("x"), RESULTADO_ERROR_DE_RED),
    (httpx.ConnectTimeout("x"), RESULTADO_TIEMPO_AGOTADO),
    (httpx.ReadTimeout("x"), RESULTADO_TIEMPO_AGOTADO),
    (httpx.RemoteProtocolError("x"), RESULTADO_ERROR_DE_RED),
])
def test_los_fallos_de_red_se_devuelven_como_resultado(monkeypatch, error, esperado):
    resolver(monkeypatch, {"ok.example": ["8.8.8.8"]})

    def manejar(peticion):
        raise error

    respuesta = pedir_url("http://ok.example/", transporte=httpx.MockTransport(manejar))
    assert respuesta.resultado == esperado


# --- SSRF -------------------------------------------------------------------

@pytest.mark.django_db
def test_una_redireccion_a_la_metadata_de_nube_se_bloquea_y_se_audita(monkeypatch):
    resolver(monkeypatch, {"publico.example": ["8.8.8.8"]})
    transporte, peticiones = servidor({
        ("publico.example", "/"): redireccion("http://169.254.169.254/latest/meta-data/"),
    })
    respuesta = pedir_url("http://publico.example/", transporte=transporte)
    assert respuesta.resultado == RESULTADO_BLOQUEADO
    assert respuesta.saltos == 1
    # Nunca se abrió conexión con la IP interna: solo se pidió el destino público.
    assert [p.url.host for p in peticiones] == ["8.8.8.8"]
    evento = EventoAuditoria.objects.get()
    assert evento.tipo == TipoEvento.DESTINO_BLOQUEADO
    assert evento.detalle == {"categoria": "red_no_permitida", "salto": 1}
    # La auditoría no guarda la IP, el host ni la URL a la que se intentó llegar.
    guardado = f"{evento.objeto} {evento.motivo} {evento.detalle}"
    assert "169.254" not in guardado and "publico.example" not in guardado


@pytest.mark.django_db
def test_una_redireccion_a_file_se_bloquea_y_se_audita(monkeypatch):
    resolver(monkeypatch, {"publico.example": ["8.8.8.8"]})
    transporte, peticiones = servidor({
        ("publico.example", "/"): redireccion("file:///etc/passwd"),
    })
    respuesta = pedir_url("http://publico.example/", transporte=transporte)
    assert (respuesta.resultado, respuesta.motivo) == (RESULTADO_BLOQUEADO, "esquema")
    assert len(peticiones) == 1
    assert EventoAuditoria.objects.get().detalle == {"categoria": "esquema", "salto": 1}


FORMAS_DE_IP_INTERNA = [
    "http://127.0.0.1/",
    "http://2130706433/",
    "http://0177.0.0.1/",
    "http://0x7f000001/",
    "http://[::ffff:127.0.0.1]/",
    "http://[::1]/",
    "http://169.254.169.254/latest/meta-data/",
    "http://10.0.0.5/",
]


@pytest.mark.django_db
@pytest.mark.parametrize("url", FORMAS_DE_IP_INTERNA)
def test_las_formas_alternativas_de_una_ip_interna_no_conectan(url):
    transporte, peticiones = servidor({})
    respuesta = pedir_url(url, transporte=transporte)
    assert respuesta.resultado == RESULTADO_BLOQUEADO
    assert peticiones == []
    assert EventoAuditoria.objects.filter(tipo=TipoEvento.DESTINO_BLOQUEADO).count() == 1


@pytest.mark.django_db
def test_un_dominio_que_resuelve_a_localhost_no_conecta(monkeypatch):
    resolver(monkeypatch, {"malo.example": ["127.0.0.1"]})
    transporte, peticiones = servidor({})
    respuesta = pedir_url("http://malo.example/", transporte=transporte)
    assert (respuesta.resultado, respuesta.motivo) == (RESULTADO_BLOQUEADO, "red_no_permitida")
    assert peticiones == []


@pytest.mark.django_db
def test_un_dominio_con_una_ip_publica_y_otra_interna_se_bloquea_entero(monkeypatch):
    resolver(monkeypatch, {"mixto.example": ["8.8.8.8", "10.0.0.1"]})
    transporte, peticiones = servidor({})
    respuesta = pedir_url("http://mixto.example/", transporte=transporte)
    assert respuesta.resultado == RESULTADO_BLOQUEADO
    assert peticiones == []


def test_un_puerto_no_permitido_no_conecta(monkeypatch):
    resolver(monkeypatch, {"ok.example": ["8.8.8.8"]})
    transporte, peticiones = servidor({})
    # Sin django_db: si intentara auditar, la falla se registra y el resultado no cambia.
    respuesta = pedir_url("http://ok.example:8080/", transporte=transporte)
    assert (respuesta.resultado, respuesta.motivo) == (RESULTADO_BLOQUEADO, "puerto")
    assert peticiones == []


def test_si_la_auditoria_falla_el_bloqueo_se_mantiene(monkeypatch):
    import core.auditoria

    def falla(*args, **kwargs):
        raise RuntimeError("base caída")

    monkeypatch.setattr(core.auditoria, "registrar_evento", falla)
    respuesta = pedir_url("http://127.0.0.1/", transporte=servidor({})[0])
    assert respuesta.resultado == RESULTADO_BLOQUEADO


@pytest.mark.parametrize("url", ["http://[::1", "http://" + "a" * 70 + ".example/"])
def test_una_url_mal_formada_es_un_destino_bloqueado_y_no_una_excepcion(url):
    with pytest.raises(DestinoBloqueado):
        validar_url(url)


# --- Redirecciones ----------------------------------------------------------

def _cadena(redirecciones):
    rutas = {
        ("ok.example", f"/r{i}"): redireccion(f"http://ok.example/r{i + 1}")
        for i in range(redirecciones)
    }
    rutas[("ok.example", f"/r{redirecciones}")] = httpx.Response(200, content=b"fin")
    return servidor(rutas)


def test_sigue_tres_redirecciones_validando_cada_salto(monkeypatch):
    resolver(monkeypatch, {"ok.example": ["8.8.8.8"]})
    transporte, peticiones = _cadena(3)
    respuesta = pedir_url("http://ok.example/r0", transporte=transporte)
    assert (respuesta.resultado, respuesta.cuerpo, respuesta.saltos) == (RESULTADO_OK, b"fin", 3)
    assert respuesta.url_final == "http://ok.example/r3"
    assert len(peticiones) == 4


def test_a_la_cuarta_redireccion_se_detiene(monkeypatch):
    resolver(monkeypatch, {"ok.example": ["8.8.8.8"]})
    transporte, peticiones = _cadena(4)
    respuesta = pedir_url("http://ok.example/r0", transporte=transporte)
    assert respuesta.resultado == RESULTADO_DEMASIADAS_REDIRECCIONES
    assert len(peticiones) == 4  # la quinta nunca se pide


def test_quien_llama_puede_pedir_menos_redirecciones(monkeypatch):
    resolver(monkeypatch, {"ok.example": ["8.8.8.8"]})
    transporte, peticiones = _cadena(2)
    respuesta = pedir_url("http://ok.example/r0", max_redirecciones=1, transporte=transporte)
    assert (respuesta.resultado, respuesta.saltos) == (RESULTADO_DEMASIADAS_REDIRECCIONES, 1)
    assert len(peticiones) == 2


@pytest.mark.parametrize("opciones", [
    {"max_redirecciones": net.MAX_REDIRECCIONES + 1},
    {"max_redirecciones": -1},
    {"plazo_segundos": net.PLAZO_TOTAL_SEGUNDOS + 1},
    {"plazo_segundos": 0},
])
def test_los_limites_de_la_politica_solo_pueden_bajar(opciones):
    with pytest.raises(ValueError):
        pedir_url("http://ok.example/", **opciones)


@pytest.mark.django_db
def test_cada_salto_resuelve_su_propio_destino(monkeypatch):
    resolver(monkeypatch, {"uno.example": ["8.8.8.8"], "dos.example": ["10.0.0.9"]})
    transporte, peticiones = servidor({
        ("uno.example", "/"): redireccion("http://dos.example/"),
    })
    respuesta = pedir_url("http://uno.example/", transporte=transporte)
    assert respuesta.resultado == RESULTADO_BLOQUEADO
    assert [p.url.host for p in peticiones] == ["8.8.8.8"]


def test_un_location_mal_formado_lo_rechaza_httpx_sin_conectar_a_ningun_lado(monkeypatch):
    # httpx interpreta el Location aunque no siga la redirección, y lo rechaza.
    resolver(monkeypatch, {"ok.example": ["8.8.8.8"]})
    transporte, peticiones = servidor({("ok.example", "/"): redireccion("http://[::1/x")})
    respuesta = pedir_url("http://ok.example/", transporte=transporte)
    assert respuesta.resultado == RESULTADO_ERROR_DE_RED
    assert [p.url.host for p in peticiones] == ["8.8.8.8"]


@pytest.mark.django_db
def test_si_el_location_no_se_puede_unir_se_bloquea_y_se_audita(monkeypatch):
    resolver(monkeypatch, {"ok.example": ["8.8.8.8"]})

    def no_une(base, destino):
        raise ValueError("Invalid IPv6 URL")

    monkeypatch.setattr(net, "urljoin", no_une)
    transporte, peticiones = servidor({("ok.example", "/"): redireccion("/otra")})
    respuesta = pedir_url("http://ok.example/", transporte=transporte)
    assert (respuesta.resultado, respuesta.motivo) == (RESULTADO_BLOQUEADO, "url_invalida")
    assert len(peticiones) == 1
    assert EventoAuditoria.objects.get().detalle == {"categoria": "url_invalida", "salto": 1}


def test_una_redireccion_relativa_se_resuelve_contra_el_nombre_original(monkeypatch):
    resolver(monkeypatch, {"ok.example": ["8.8.8.8"]})
    transporte, peticiones = servidor({
        ("ok.example", "/a"): redireccion("/b"),
        ("ok.example", "/b"): httpx.Response(200, content=b"b"),
    })
    respuesta = pedir_url("http://ok.example/a", transporte=transporte)
    assert (respuesta.resultado, respuesta.cuerpo) == (RESULTADO_OK, b"b")


def test_una_redireccion_sin_location_es_la_respuesta_final(monkeypatch):
    resolver(monkeypatch, {"ok.example": ["8.8.8.8"]})
    transporte, _ = servidor({("ok.example", "/"): httpx.Response(301)})
    respuesta = pedir_url("http://ok.example/", transporte=transporte)
    assert (respuesta.resultado, respuesta.codigo_http) == (RESULTADO_OK, 301)


# --- Tamaño y tiempo --------------------------------------------------------

def test_2_mb_descomprimidos_cortan_la_respuesta(monkeypatch):
    resolver(monkeypatch, {"ok.example": ["8.8.8.8"]})
    comprimido = gzip.compress(b"a" * (MAX_BYTES_RESPUESTA * 4))
    assert len(comprimido) < 50_000  # viajaron pocos KB; descomprimidos son 8 MB
    respuesta_http = httpx.Response(
        200, headers={"Content-Encoding": "gzip"}, stream=Trozos([comprimido]),
    )
    transporte, _ = servidor({("ok.example", "/"): respuesta_http})
    respuesta = pedir_url("http://ok.example/", transporte=transporte)
    assert respuesta.resultado == RESULTADO_RESPUESTA_GRANDE
    assert len(respuesta.cuerpo) == MAX_BYTES_RESPUESTA


def _gzip_de_ceros(megas):
    compresor = zlib.compressobj(9, zlib.DEFLATED, 16 + zlib.MAX_WBITS)
    bloque = bytes(1024 * 1024)
    return b"".join([compresor.compress(bloque) for _ in range(megas)] + [compresor.flush()])


def test_una_bomba_gzip_se_corta_sin_llenar_la_memoria(monkeypatch):
    resolver(monkeypatch, {"ok.example": ["8.8.8.8"]})
    comprimido = _gzip_de_ceros(100)
    # Trozos de 64 KB, como los entrega la red. Cada uno se descomprime en unos 64 MB.
    trozos = [comprimido[i:i + 65536] for i in range(0, len(comprimido), 65536)]
    respuesta_http = httpx.Response(
        200, headers={"Content-Encoding": "gzip"}, stream=Trozos(trozos),
    )
    transporte, peticiones = servidor({("ok.example", "/"): respuesta_http})
    tracemalloc.start()
    respuesta = pedir_url("http://ok.example/", transporte=transporte)
    _, pico = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert respuesta.resultado == RESULTADO_RESPUESTA_GRANDE
    assert len(respuesta.cuerpo) == MAX_BYTES_RESPUESTA
    assert pico < 8 * MAX_BYTES_RESPUESTA
    assert peticiones[0].headers["accept-encoding"] == "gzip"


@pytest.mark.parametrize("codificacion", ["gzip, gzip", "br", "deflate"])
def test_una_codificacion_que_no_se_pidio_no_se_lee(monkeypatch, codificacion):
    resolver(monkeypatch, {"ok.example": ["8.8.8.8"]})
    # 500 bytes con gzip dentro de gzip se descomprimen en cientos de MB.
    cuerpo = gzip.compress(gzip.compress(bytes(10 * 1024 * 1024)))
    respuesta_http = httpx.Response(
        200, headers={"Content-Encoding": codificacion}, stream=Trozos([cuerpo]),
    )
    transporte, _ = servidor({("ok.example", "/"): respuesta_http})
    respuesta = pedir_url("http://ok.example/", transporte=transporte)
    assert (respuesta.resultado, respuesta.cuerpo) == (RESULTADO_ERROR_DE_RED, b"")


@pytest.mark.parametrize("largo,esperado", [
    (MAX_BYTES_RESPUESTA, RESULTADO_OK),
    (MAX_BYTES_RESPUESTA + 1, RESULTADO_RESPUESTA_GRANDE),
])
def test_el_limite_de_2_mb_es_exacto(monkeypatch, largo, esperado):
    resolver(monkeypatch, {"ok.example": ["8.8.8.8"]})
    transporte, _ = servidor({("ok.example", "/"): httpx.Response(200, content=b"a" * largo)})
    respuesta = pedir_url("http://ok.example/", transporte=transporte)
    assert respuesta.resultado == esperado
    assert len(respuesta.cuerpo) == MAX_BYTES_RESPUESTA


def test_un_servidor_que_gotea_bytes_se_corta_por_el_plazo_total(monkeypatch):
    resolver(monkeypatch, {"lento.example": ["8.8.8.8"]})
    monkeypatch.setattr(net, "PLAZO_TOTAL_SEGUNDOS", 0.3)
    lento = httpx.Response(200, stream=Trozos([b"x"] * 100, pausa=0.1))
    transporte, _ = servidor({("lento.example", "/"): lento})
    inicio = time.monotonic()
    respuesta = pedir_url("http://lento.example/", transporte=transporte)
    assert respuesta.resultado == RESULTADO_TIEMPO_AGOTADO
    assert time.monotonic() - inicio < 2


def test_quien_llama_puede_pedir_un_plazo_menor(monkeypatch):
    resolver(monkeypatch, {"lento.example": ["8.8.8.8"]})
    lento = httpx.Response(200, stream=Trozos([b"x"] * 100, pausa=0.1))
    transporte, _ = servidor({("lento.example", "/"): lento})
    inicio = time.monotonic()
    respuesta = pedir_url("http://lento.example/", plazo_segundos=0.3, transporte=transporte)
    assert respuesta.resultado == RESULTADO_TIEMPO_AGOTADO
    assert time.monotonic() - inicio < 2


def _servidor_que_gotea_cabeceras(puerto, segundos):
    """Servidor real en 127.0.0.1 que manda las cabeceras de a un byte cada 0,2 s."""
    escucha = socket.socket()
    escucha.bind(("127.0.0.1", 0))
    escucha.listen(1)
    escucha.settimeout(5)
    puerto.append(escucha.getsockname()[1])
    try:
        conexion, _ = escucha.accept()
        with conexion:
            conexion.recv(4096)
            conexion.sendall(b"HTTP/1.1 200 OK\r\nX-Goteo: ")
            fin = time.monotonic() + segundos
            while time.monotonic() < fin:
                conexion.sendall(b"a")
                time.sleep(0.2)
    except OSError:
        pass  # el cliente cortó la conexión, que es lo esperado
    finally:
        escucha.close()


def test_un_servidor_que_gotea_las_cabeceras_se_corta_por_el_plazo_total(monkeypatch):
    # Cada byte llega antes del timeout de lectura de 2 s, así que solo el plazo total
    # puede cortar. Usa la red de verdad: MockTransport no pasa por la red de httpcore.
    puerto = []
    hilo = threading.Thread(target=_servidor_que_gotea_cabeceras, args=(puerto, 6), daemon=True)
    hilo.start()
    while not puerto:
        time.sleep(0.01)
    monkeypatch.setattr(net, "validar_url", lambda url: ["127.0.0.1"])
    monkeypatch.setattr(net, "PLAZO_TOTAL_SEGUNDOS", 1)
    inicio = time.monotonic()
    respuesta = pedir_url(f"http://lento.example:{puerto[0]}/")
    assert respuesta.resultado == RESULTADO_TIEMPO_AGOTADO
    assert time.monotonic() - inicio < 3


# --- Método, cookies y cliente ---------------------------------------------

def test_head_no_descarga_el_cuerpo(monkeypatch):
    resolver(monkeypatch, {"ok.example": ["8.8.8.8"]})
    transporte, peticiones = servidor({("ok.example", "/"): httpx.Response(200)})
    respuesta = pedir_url("http://ok.example/", metodo="head", transporte=transporte)
    assert (respuesta.resultado, respuesta.cuerpo) == (RESULTADO_OK, b"")
    assert peticiones[0].method == "HEAD"


@pytest.mark.parametrize("metodo", ["PUT", "DELETE", "PATCH", "OPTIONS"])
def test_solo_se_admiten_get_head_y_post(metodo):
    transporte, peticiones = servidor({})
    with pytest.raises(ValueError):
        pedir_url("http://ok.example/", metodo=metodo, transporte=transporte)
    assert peticiones == []


def test_no_se_guardan_ni_se_envian_cookies(monkeypatch):
    resolver(monkeypatch, {"ok.example": ["8.8.8.8"]})
    transporte, peticiones = servidor({
        ("ok.example", "/a"): redireccion("/b", **{"Set-Cookie": "sid=secreto; Path=/"}),
        ("ok.example", "/b"): httpx.Response(200),
    })
    assert pedir_url("http://ok.example/a", transporte=transporte).resultado == RESULTADO_OK
    assert "cookie" not in peticiones[1].headers


def test_el_cliente_ignora_el_proxy_del_entorno_y_no_reutiliza_conexiones(monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://proxy.invalid:3128")
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.invalid:3128")
    resolver(monkeypatch, {"ok.example": ["8.8.8.8"]})
    capturado = {}
    original = httpx.Client

    def espia(*args, **kwargs):
        capturado.update(kwargs)
        return original(*args, **kwargs)

    monkeypatch.setattr(net.httpx, "Client", espia)
    transporte, _ = servidor({("ok.example", "/"): httpx.Response(200)})
    pedir_url("http://ok.example/", transporte=transporte)
    assert capturado["trust_env"] is False
    assert capturado["follow_redirects"] is False
    assert capturado["verify"] is True
    assert capturado["limits"].max_keepalive_connections == 0
    assert capturado["timeout"].connect == net.TIMEOUT_CONEXION_SEGUNDOS


def test_httpx_no_escribe_las_urls_pedidas_en_el_log(monkeypatch, caplog):
    # httpx registra en INFO cada petición con su ruta y sus parámetros completos.
    import logging

    assert logging.getLogger("httpx").getEffectiveLevel() >= logging.WARNING
    assert logging.getLogger("httpcore").getEffectiveLevel() >= logging.WARNING


# --- httpx solo en core/net.py ---------------------------------------------

def test_httpx_solo_se_importa_en_core_net():
    aplicaciones = ["config", "core", "analisis", "motor", "inteligencia", "catalogo", "curacion"]
    importan = []
    for app in aplicaciones:
        for archivo in (BASE_DIR / app).rglob("*.py"):
            texto = archivo.read_text(encoding="utf-8")
            if any(f"{forma} {cliente}" in texto
                   for forma in ("import", "from") for cliente in ("httpx", "httpcore")):
                importan.append(archivo.relative_to(BASE_DIR).as_posix())
    assert importan == ["core/net.py"]


# --- POST y cabeceras para las APIs de las fuentes externas -------------------

def test_un_post_lleva_su_formulario_y_sus_cabeceras_a_la_ip_validada(monkeypatch):
    resolver(monkeypatch, {"api.example": ["8.8.8.8"]})
    transporte, peticiones = servidor({("api.example", "/v1/url/"): httpx.Response(200, json={})})
    respuesta = pedir_url(
        "https://api.example/v1/url/",
        metodo="POST",
        encabezados={"Auth-Key": "clave-ficticia"},
        datos={"url": "https://web.example/a?b=1"},
        transporte=transporte,
    )
    assert respuesta.resultado == RESULTADO_OK
    [peticion] = peticiones
    assert (peticion.method, peticion.url.host) == ("POST", "8.8.8.8")
    assert peticion.headers["host"] == "api.example"
    assert peticion.headers["auth-key"] == "clave-ficticia"
    assert peticion.headers["user-agent"] == net.USER_AGENT
    assert peticion.headers["content-type"] == "application/x-www-form-urlencoded"
    assert peticion.content == b"url=https%3A%2F%2Fweb.example%2Fa%3Fb%3D1"


@pytest.mark.parametrize("opciones", [
    {"metodo": "POST", "datos": {"url": "x"}},
    {"encabezados": {"x-apikey": "clave-ficticia"}},
])
def test_con_una_clave_o_un_post_no_se_sigue_ninguna_redireccion(monkeypatch, opciones):
    resolver(monkeypatch, {"api.example": ["8.8.8.8"], "otro.example": ["8.8.4.4"]})
    transporte, peticiones = servidor({
        ("api.example", "/"): redireccion("https://otro.example/robar"),
    })
    respuesta = pedir_url("https://api.example/", transporte=transporte, **opciones)
    assert (respuesta.resultado, respuesta.saltos) == (RESULTADO_DEMASIADAS_REDIRECCIONES, 0)
    # La clave nunca llegó a otro servidor.
    assert [p.headers["host"] for p in peticiones] == ["api.example"]


@pytest.mark.parametrize("opciones", [
    {"encabezados": {"Key": "x"}, "max_redirecciones": 1},
    {"metodo": "POST", "max_redirecciones": 2},
    {"metodo": "GET", "datos": {"a": "b"}},
    {"encabezados": {"Host": "interno.example"}},
    {"encabezados": {"cookie": "sesion=1"}},
    {"encabezados": {"Accept-Encoding": "br"}},
    {"encabezados": {"User-Agent": "otro"}},
])
def test_las_opciones_que_romperian_la_politica_se_rechazan(opciones):
    transporte, peticiones = servidor({})
    with pytest.raises(ValueError):
        pedir_url("https://api.example/", transporte=transporte, **opciones)
    assert peticiones == []


@pytest.mark.django_db
def test_un_post_a_una_red_interna_se_bloquea_y_se_audita(monkeypatch):
    resolver(monkeypatch, {"api.example": ["169.254.169.254"]})
    transporte, peticiones = servidor({})
    respuesta = pedir_url(
        "https://api.example/", metodo="POST", datos={"a": "b"}, transporte=transporte
    )
    assert respuesta.resultado == RESULTADO_BLOQUEADO
    assert peticiones == []
    assert EventoAuditoria.objects.get().tipo == TipoEvento.DESTINO_BLOQUEADO
