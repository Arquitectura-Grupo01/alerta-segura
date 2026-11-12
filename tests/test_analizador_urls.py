
"""Pruebas de normalización de enlaces."""

import pytest

from analisis.normalizacion import URLInvalida, normalizar, normalizar_url


def test_agrega_https():
    resultado = normalizar_url("ejemplo.pe/login")
    assert resultado == "https://ejemplo.pe/login"


def test_convierte_dominio_a_minusculas():
    resultado = normalizar_url("https://EJEMPLO.PE/")
    assert resultado == "https://ejemplo.pe/"


def test_elimina_fragmento():
    resultado = normalizar_url("https://ejemplo.pe/ruta#seccion")
    assert resultado == "https://ejemplo.pe/ruta"


def test_elimina_parametros_de_rastreo():
    resultado = normalizar_url(
        "https://ejemplo.pe/?id=123&utm_source=redes"
    )
    assert resultado == "https://ejemplo.pe/?id=123"


def test_usuario_en_url_lleva_al_host_real():
    # El navegador abre sitio-falso.com: eso es lo que se analiza.
    enlace = normalizar("https://bcp.com.pe@sitio-falso.com/login")
    assert enlace.dominio == "sitio-falso.com"
    assert enlace.url == "https://sitio-falso.com/login"


def test_la_url_para_seguir_el_enlace_conserva_los_parametros():
    # Un acortador puede necesitar los parámetros que la clave de caché quita.
    enlace = normalizar("HTTPS://Usuario@Ejemplo.PE\\r?id=1&utm_source=x#arriba")
    assert enlace.url == "https://ejemplo.pe/r?id=1"
    assert enlace.url_con_parametros == "https://ejemplo.pe/r?id=1&utm_source=x"


def test_rechaza_enlace_vacio():
    with pytest.raises(URLInvalida):
        normalizar_url("")

def test_rechaza_protocolo_javascript():
    with pytest.raises(URLInvalida):
        normalizar_url("javascript:alert(1)")


def test_rechaza_protocolo_file():
    with pytest.raises(URLInvalida):
        normalizar_url("file:///etc/passwd")


def test_rechaza_puerto_no_permitido():
    with pytest.raises(URLInvalida):
        normalizar_url("https://ejemplo.com:9999/")


def test_normaliza_ipv6():
    assert normalizar_url("http://[2001:db8::1]/") == (
        "http://[2001:db8::1]/"
    )


def test_normaliza_dominio_con_punto_final():
    assert normalizar_url("https://EJEMPLO.COM./") == (
        "https://ejemplo.com./"
    )


def test_rechaza_doble_punto_en_puerto():
    with pytest.raises(URLInvalida):
        normalizar_url("https://ejemplo.com:abc/")


def test_barra_invertida_se_lee_como_el_navegador():
    # El navegador lee la barra invertida como "/": abre ejemplo.com y lo demás queda en la ruta.
    enlace = normalizar("https://ejemplo.com\\@sitio-falso.com/")
    assert enlace.dominio == "ejemplo.com"


def test_misma_url_con_y_sin_rastreo_da_la_misma_clave():
    con_rastreo = normalizar_url(
        "https://ejemplo.pe/oferta?id=7&utm_source=wsp&fbclid=abc&igshid=xyz#arriba"
    )
    assert con_rastreo == normalizar_url("ejemplo.pe/oferta?id=7")


def test_dominio_con_punto_final_se_guarda_sin_el_punto():
    assert normalizar("https://ejemplo.com./").dominio == "ejemplo.com"


def test_quita_saltos_de_linea_como_el_navegador():
    enlace = normalizar("https://ejem\nplo.com/")
    assert enlace.dominio == "ejemplo.com"
    assert enlace.original == "https://ejem\nplo.com/"


def test_rechaza_espacios_dentro_del_enlace():
    with pytest.raises(URLInvalida):
        normalizar_url("https://ejemplo.com/una ruta")


def test_rechaza_puerto_no_permitido_sin_esquema():
    with pytest.raises(URLInvalida, match="puerto"):
        normalizar_url("ejemplo.com:8080/")


def test_acepta_puerto_permitido_sin_esquema():
    assert normalizar_url("ejemplo.com:443/oferta") == "https://ejemplo.com/oferta"


def test_rechaza_otro_protocolo_sin_barras():
    with pytest.raises(URLInvalida, match="protocolo"):
        normalizar_url("mailto:alguien@ejemplo.com")


def test_rechaza_enlace_demasiado_largo():
    with pytest.raises(URLInvalida):
        normalizar_url("https://ejemplo.com/" + "a" * 2048)


def test_rechaza_texto_que_no_es_cadena():
    with pytest.raises(URLInvalida):
        normalizar_url(None)


def test_convierte_dominio_internacional_a_punycode():
    assert normalizar("https://bücher.example/").dominio == "xn--bcher-kva.example"


def test_conserva_puerto_explicito_que_no_es_el_del_esquema():
    assert normalizar_url("http://ejemplo.com:443/") == "http://ejemplo.com:443/"
    assert normalizar_url("https://ejemplo.com:443/") == "https://ejemplo.com/"
