
"""Pruebas de las heurísticas de URL."""

from analisis.heuristicas import (
    detectar_alfabetos_mezclados,
    detectar_dominio_enganoso,
    detectar_dominio_parecido,
    detectar_ip_alternativa,
    detectar_senales,
    distancia_levenshtein,
    separar_dominio,
)


def test_detecta_ip():
    senales = detectar_senales("http://192.0.2.10/login")
    assert "ip_como_dominio" in senales


def test_detecta_acortador():
    senales = detectar_senales("https://bit.ly/ejemplo")
    assert "acortador" in senales


def test_detecta_punycode():
    senales = detectar_senales("https://xn--bcher-kva.example/")
    assert "punycode" in senales


def test_detecta_subdominios():
    senales = detectar_senales("https://a.b.c.d.e.ejemplo.com")
    assert "muchos_subdominios" in senales


def test_detecta_palabras_sospechosas():
    senales = detectar_senales("https://ejemplo.com/verifica/login")
    assert "palabras_sospechosas" in senales


def test_detecta_usuario_en_url():
    senales = detectar_senales(
        "https://banco.pe@sitio-falso.com/login"
    )
    assert "usuario_en_url" in senales


def test_no_marca_url_simple():
    senales = detectar_senales("https://ejemplo.com/inicio")
    assert senales == []


"Pruebas de heurísticas adicionales de URL."


def test_detecta_ip_decimal():
    assert detectar_ip_alternativa("2130706433")


def test_detecta_ip_hexadecimal():
    assert detectar_ip_alternativa("0x7f000001")


def test_detecta_ip_octal():
    assert detectar_ip_alternativa("0177.0.0.1")


def test_no_confunde_dominio_normal_con_ip():
    assert not detectar_ip_alternativa("ejemplo.com")


def test_detecta_alfabetos_mezclados():
    dominio = "p\u0430ypal.com"
    assert detectar_alfabetos_mezclados(dominio)


def test_detecta_marca_en_subdominio():
    senales = detectar_dominio_enganoso(
        "bcp.com.pe.sitio-falso.com",
        ["bcp.com.pe"],
    )
    assert "marca_en_subdominio" in senales


def test_no_marca_dominio_oficial():
    senales = detectar_dominio_enganoso(
        "www.bcp.com.pe",
        ["bcp.com.pe"],
    )
    assert senales == []


"Pruebas de integración de heurísticas de URL."
def test_integracion_ip_alternativa():
    senales = detectar_senales("http://0x7f000001/")
    assert "ip_alternativa" in senales


def test_integracion_alfabetos_mezclados():
    senales = detectar_senales("https://p\u0430ypal.com/")
    assert "alfabetos_mezclados" in senales



"Pruebas de distancia de Levenshtein entre dominios."

def test_levenshtein_dominios_iguales():
    assert distancia_levenshtein("paypal.com", "paypal.com") == 0


def test_levenshtein_una_modificacion():
    assert distancia_levenshtein("paypal.com", "paypa1.com") == 1


def test_levenshtein_dos_modificaciones():
    assert distancia_levenshtein("banco", "banxo1") == 2


def test_levenshtein_dominios_diferentes():
    assert distancia_levenshtein("paypal.com", "ejemplo.org") > 2


"Pruebas de detección de dominios parecidos a los oficiales."
def test_detecta_dominio_parecido():
    senales = detectar_dominio_parecido(
        "paypa1.com",
        ["paypal.com"],
    )
    assert "dominio_parecido" in senales


def test_no_marca_dominio_oficial_como_parecido():
    senales = detectar_dominio_parecido(
        "paypal.com",
        ["paypal.com"],
    )
    assert senales == []


def test_no_marca_subdominio_legitimo():
    senales = detectar_dominio_parecido(
        "www.paypal.com",
        ["paypal.com"],
    )
    assert senales == []


def test_no_marca_dominio_diferente():
    senales = detectar_dominio_parecido(
        "ejemplo.com",
        ["paypal.com"],
    )
    assert senales == []


"pruebas de integración de heurísticas de dominio parecidos y subdominios."

def test_integracion_dominio_parecido():
    senales = detectar_senales(
        "https://paypa1.com/",
        ["paypal.com"],
    )
    assert "dominio_parecido" in senales


def test_integracion_marca_en_subdominio():
    senales = detectar_senales(
        "https://bcp.com.pe.sitio-falso.com/",
        ["bcp.com.pe"],
    )
    assert "marca_en_subdominio" in senales


def test_integracion_dominio_oficial():
    senales = detectar_senales(
        "https://www.paypal.com/",
        ["paypal.com"],
    )
    assert "dominio_parecido" not in senales
    assert "marca_en_subdominio" not in senales


"separación de nombre y extensión de dominio."
def test_separa_dominio_peruano():
    assert separar_dominio("interbank.com.pe") == (
        "interbank",
        "com.pe",
    )


def test_detecta_dominio_peruano_parecido():
    senales = detectar_dominio_parecido(
        "interban1.com.pe",
        ["interbank.com.pe"],
    )
    assert "dominio_parecido" in senales


def test_no_marca_dominio_peruano_oficial():
    senales = detectar_dominio_parecido(
        "interbank.com.pe",
        ["interbank.com.pe"],
    )
    assert senales == []