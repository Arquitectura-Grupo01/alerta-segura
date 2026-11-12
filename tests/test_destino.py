"""Seguimiento de un enlace hasta su destino, con las redirecciones que pide la página."""

import pytest

from analisis import destino
from analisis.destino import seguir_enlace
from core.net import (
    MAX_REDIRECCIONES,
    PLAZO_TOTAL_SEGUNDOS,
    RESULTADO_BLOQUEADO,
    RESULTADO_DEMASIADAS_REDIRECCIONES,
    RESULTADO_ERROR_DE_RED,
    RESULTADO_OK,
    RESULTADO_RESPUESTA_GRANDE,
    RESULTADO_TIEMPO_AGOTADO,
    RespuestaSegura,
)


class Red:
    """Reemplaza a pedir_url: responde según la URL y guarda cada llamada."""

    def __init__(self, paginas):
        self.paginas = paginas
        self.llamadas = []

    def __call__(self, url, **opciones):
        self.llamadas.append((url, opciones))
        return self.paginas.get(url, RespuestaSegura(RESULTADO_ERROR_DE_RED))


def pagina(url, cuerpo=b"<html></html>", saltos=0, tipo="text/html", resultado=RESULTADO_OK,
           **encabezados):
    return RespuestaSegura(
        resultado,
        codigo_http=200,
        url_final=url,
        cuerpo=cuerpo,
        encabezados={"content-type": tipo, **encabezados},
        saltos=saltos,
    )


def meta(contenido):
    return f'<html><head><meta http-equiv="refresh" content="{contenido}"></head></html>'.encode()


@pytest.fixture
def red(monkeypatch):
    def poner(paginas):
        falsa = Red(paginas)
        monkeypatch.setattr(destino, "pedir_url", falsa)
        return falsa

    return poner


def test_sin_redirecciones_el_destino_es_el_mismo_enlace(red):
    red({"https://a.example/": pagina("https://a.example/")})
    assert seguir_enlace("https://a.example/") == destino.Destino(
        RESULTADO_OK, "https://a.example/", 0
    )


def test_cuenta_las_redirecciones_que_sigue_pedir_url(red):
    falsa = red({"https://a.example/": pagina("https://b.example/fin", saltos=2)})
    resultado = seguir_enlace("https://a.example/")
    assert (resultado.url, resultado.saltos) == ("https://b.example/fin", 2)
    assert falsa.llamadas[0][1]["max_redirecciones"] == MAX_REDIRECCIONES


def test_un_meta_refresh_cuenta_como_un_salto_mas(red):
    falsa = red({
        "https://a.example/x": pagina("https://a.example/x", meta("0; URL='/y?z=1'"), saltos=1),
        "https://a.example/y?z=1": pagina("https://c.example/fin"),
    })
    resultado = seguir_enlace("https://a.example/x")
    assert (resultado.url, resultado.saltos) == ("https://c.example/fin", 2)
    # La segunda llamada solo puede gastar los saltos que quedan.
    assert falsa.llamadas[1][1]["max_redirecciones"] == MAX_REDIRECCIONES - 2


def test_el_meta_refresh_no_pasa_del_maximo_de_3_saltos(red):
    falsa = red({
        "https://a.example/": pagina(
            "https://a.example/", meta("0;url=https://b.example/"), saltos=MAX_REDIRECCIONES
        ),
    })
    resultado = seguir_enlace("https://a.example/")
    assert resultado == destino.Destino(RESULTADO_DEMASIADAS_REDIRECCIONES, "", 3)
    assert len(falsa.llamadas) == 1


def test_el_tercer_salto_por_meta_refresh_ya_no_admite_otra_redireccion(red):
    falsa = red({
        "https://a.example/": pagina("https://a.example/", meta("0;url=/b"), saltos=2),
        "https://a.example/b": pagina("https://a.example/b"),
    })
    assert seguir_enlace("https://a.example/").saltos == 3
    assert falsa.llamadas[1][1]["max_redirecciones"] == 0


def test_la_cabecera_refresh_tambien_se_sigue(red):
    red({
        "https://a.example/": pagina("https://a.example/", refresh="1;url=https://b.example/"),
        "https://b.example/": pagina("https://b.example/"),
    })
    assert seguir_enlace("https://a.example/").url == "https://b.example/"


@pytest.mark.parametrize("contenido", [
    "5",
    "0;url=",
    "0;url=javascript:alert(1)",
    "0;url=data:text/html,hola",
    "0;url=/#arriba",
    "0;url=https://[::1",
    "ahora;url=https://b.example/",
])
def test_un_refresco_sin_otra_web_deja_el_destino_en_la_pagina(red, contenido):
    falsa = red({"https://a.example/": pagina("https://a.example/", meta(contenido))})
    assert seguir_enlace("https://a.example/").url == "https://a.example/"
    assert len(falsa.llamadas) == 1


@pytest.mark.parametrize("html", [
    # Con JavaScript activo, el navegador no aplica lo que va dentro de noscript o template.
    b'<noscript><meta http-equiv="refresh" content="0;url=/b"></noscript>',
    b'<template><meta http-equiv="refresh" content="0;url=/b"></template>',
    b'<meta name="refresh" content="0;url=/b">',
    # html.parser lanza AssertionError con algunas declaraciones mal formadas.
    b'<![x[ <meta http-equiv="refresh" content="0;url=/b">',
])
def test_solo_cuenta_el_meta_refresh_que_aplica_el_navegador(red, html):
    red({
        "https://a.example/": pagina("https://a.example/", html),
        "https://a.example/b": pagina("https://a.example/b"),
    })
    assert seguir_enlace("https://a.example/").url == "https://a.example/"


def test_sigue_el_primer_meta_refresh_aunque_haya_otro_en_noscript(red):
    html = (
        b'<noscript><meta http-equiv="refresh" content="0;url=/n"></noscript>'
        b'<META HTTP-EQUIV="Refresh" CONTENT="0; url=/b">'
        b'<meta http-equiv="refresh" content="0;url=/c">'
    )
    red({
        "https://a.example/": pagina("https://a.example/", html),
        "https://a.example/b": pagina("https://a.example/b"),
    })
    assert seguir_enlace("https://a.example/").url == "https://a.example/b"


def test_una_respuesta_que_no_es_html_no_se_lee(red):
    red({"https://a.example/": pagina("https://a.example/", meta("0;url=/b"), tipo="text/plain")})
    assert seguir_enlace("https://a.example/").url == "https://a.example/"


def test_una_pagina_de_mas_de_2_mb_tambien_es_un_destino(red):
    red({"https://a.example/": pagina("https://a.example/", resultado=RESULTADO_RESPUESTA_GRANDE)})
    assert seguir_enlace("https://a.example/").url == "https://a.example/"


@pytest.mark.parametrize("resultado", [
    RESULTADO_BLOQUEADO, RESULTADO_ERROR_DE_RED, RESULTADO_TIEMPO_AGOTADO,
    RESULTADO_DEMASIADAS_REDIRECCIONES,
])
def test_si_no_llega_no_hay_destino(red, resultado):
    red({"https://a.example/": RespuestaSegura(resultado, saltos=1)})
    assert seguir_enlace("https://a.example/") == destino.Destino(resultado, "", 1)


def test_toda_la_cadena_comparte_un_solo_plazo(red, monkeypatch):
    reloj = [1000.0]
    monkeypatch.setattr(destino.time, "monotonic", lambda: reloj[0])

    class Lenta(Red):
        def __call__(self, url, **opciones):
            reloj[0] += 6  # cada página tarda 6 s
            return super().__call__(url, **opciones)

    falsa = Lenta({
        "https://a.example/": pagina("https://a.example/", meta("0;url=/b")),
        "https://a.example/b": pagina("https://a.example/b", meta("0;url=/c")),
    })
    monkeypatch.setattr(destino, "pedir_url", falsa)
    resultado = seguir_enlace("https://a.example/")
    plazos = [opciones["plazo_segundos"] for _, opciones in falsa.llamadas]
    assert plazos == [PLAZO_TOTAL_SEGUNDOS, PLAZO_TOTAL_SEGUNDOS - 6]
    assert resultado == destino.Destino(RESULTADO_TIEMPO_AGOTADO, "", 2)
