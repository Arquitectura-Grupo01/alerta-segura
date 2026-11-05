
"""Pruebas de las heurísticas de URL."""

import pytest

from analisis.heuristicas import (
    HEURISTICAS,
    detectar_alfabetos_mezclados,
    detectar_dominio_enganoso,
    detectar_dominio_parecido,
    detectar_ip_alternativa,
    detectar_senales,
    distancia_levenshtein,
    dominio_registrable,
    heuristica,
    separar_dominio,
)
from analisis.normalizacion import URLInvalida, normalizar


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


def test_integracion_ip_alternativa():
    senales = detectar_senales("http://0x7f000001/")
    assert "ip_alternativa" in senales


def test_integracion_alfabetos_mezclados():
    senales = detectar_senales("https://p\u0430ypal.com/")
    assert "alfabetos_mezclados" in senales




def test_levenshtein_dominios_iguales():
    assert distancia_levenshtein("paypal.com", "paypal.com") == 0


def test_levenshtein_una_modificacion():
    assert distancia_levenshtein("paypal.com", "paypa1.com") == 1


def test_levenshtein_dos_modificaciones():
    assert distancia_levenshtein("banco", "banxo1") == 2


def test_levenshtein_dominios_diferentes():
    assert distancia_levenshtein("paypal.com", "ejemplo.org") > 2


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


# Trucos que el navegador lee distinto que Python (tarea 16).


def test_truco_del_arroba_marca_la_senal_y_analiza_el_host_real():
    enlace = normalizar("https://bcp.com.pe@sitio-falso.com/")
    assert enlace.dominio == "sitio-falso.com"
    assert "usuario_en_url" in detectar_senales(enlace)


def test_detecta_barra_invertida():
    assert "barra_invertida" in detectar_senales("https://ejemplo.com\\@sitio-falso.com/")


def test_detecta_punto_final_en_el_host():
    assert "punto_final" in detectar_senales("https://ejemplo.com./")


def test_punto_al_final_de_la_ruta_no_es_punto_final():
    assert "punto_final" not in detectar_senales("https://ejemplo.com/ruta.")


def test_detecta_caracteres_de_control_que_el_navegador_borra():
    assert "caracteres_de_control" in detectar_senales("https://ejem\tplo.com/")


def test_detecta_dominio_con_letras_cirilicas():
    senales = detectar_senales("https://pаypal.com/")
    assert "alfabetos_mezclados" in senales
    assert "punycode" in senales


def test_detecta_letras_griegas_mezcladas():
    assert detectar_alfabetos_mezclados("ρaypal.com")


def test_dominio_solo_latino_no_mezcla_alfabetos():
    assert not detectar_alfabetos_mezclados("bücher.example")


@pytest.mark.parametrize("host", ["127.1", "0x7f.1", "0x7f.0.0.1", "017700000001"])
def test_detecta_ip_abreviada_u_octal(host):
    assert detectar_ip_alternativa(host)


@pytest.mark.parametrize("host", ["192.0.2.10", "08.1.2.3", "1.2.3.4.5", "2024.pe"])
def test_no_es_ip_alternativa(host):
    assert not detectar_ip_alternativa(host)


def test_detecta_ipv6_como_dominio():
    assert "ip_como_dominio" in detectar_senales("http://[2001:db8::1]/")


def test_detecta_acortadores_agregados():
    for enlace in ("https://acortar.link/abc", "https://rb.gy/abc", "https://www.bit.ly/abc"):
        assert "acortador" in detectar_senales(enlace), enlace


def test_detecta_palabra_con_tilde_codificada_en_la_ruta():
    assert "palabras_sospechosas" in detectar_senales("https://ejemplo.com/contrase%C3%B1a")


def test_palabras_del_dominio_no_cuentan_como_ruta():
    assert "palabras_sospechosas" not in detectar_senales("https://login.ejemplo.com/")


# Subdominios con sufijos peruanos de dos niveles.


def test_tres_subdominios_en_com_pe_no_son_muchos():
    assert "muchos_subdominios" not in detectar_senales("https://a.b.c.ejemplo.com.pe/")


def test_cuatro_subdominios_en_com_pe_son_muchos():
    assert "muchos_subdominios" in detectar_senales("https://a.b.c.d.ejemplo.com.pe/")


def test_ip_no_cuenta_subdominios():
    assert "muchos_subdominios" not in detectar_senales("http://192.0.2.10/")


def test_dominio_registrable_quita_subdominios():
    assert dominio_registrable("login.seguro.bcp.com.pe") == "bcp.com.pe"
    assert dominio_registrable("www.ejemplo.com") == "ejemplo.com"


# Marca y dominios parecidos.


def test_detecta_marca_en_medio_del_dominio():
    senales = detectar_dominio_enganoso("seguro.bcp.com.pe.sitio-falso.com", ["bcp.com.pe"])
    assert senales == ["marca_en_subdominio"]


def test_detecta_nombre_de_marca_como_palabra_de_un_subdominio():
    senales = detectar_dominio_enganoso("bcp-seguro.sitio-falso.com", ["bcp.com.pe"])
    assert senales == ["marca_en_subdominio"]


def test_marca_de_dos_letras_no_se_busca_en_subdominios():
    assert detectar_dominio_enganoso("bn.sitio.com", ["bn.com.pe"]) == []


def test_detecta_parecido_aunque_tenga_subdominio():
    assert detectar_dominio_parecido("login.interbanc.com.pe", ["interbank.com.pe"]) == [
        "dominio_parecido"
    ]


def test_nombre_corto_solo_admite_un_cambio():
    assert detectar_dominio_parecido("bxp.com.pe", ["bcp.com.pe"]) == ["dominio_parecido"]
    assert detectar_dominio_parecido("abc.com.pe", ["bcp.com.pe"]) == []


def test_nombre_de_dos_letras_no_se_compara():
    assert detectar_dominio_parecido("ab.com.pe", ["bn.com.pe"]) == []


def test_subdominio_oficial_no_es_parecido():
    assert detectar_dominio_parecido("zonasegura.bcp.com.pe", ["www.bcp.com.pe"]) == []


def test_sin_catalogo_no_corren_las_heuristicas_de_marca():
    senales = detectar_senales("https://bcp.com.pe.sitio-falso.com/")
    assert "marca_en_subdominio" not in senales
    assert "dominio_parecido" not in senales


def test_levenshtein_con_maximo_corta_temprano():
    assert distancia_levenshtein("viabcp", "otronombrelargo", maximo=2) == 3
    assert distancia_levenshtein("viabcp", "viabcpp", maximo=2) == 1


# Registro de heurísticas.


def test_acepta_enlace_ya_normalizado():
    enlace = normalizar("bit.ly/abc")
    assert detectar_senales(enlace) == detectar_senales("bit.ly/abc")


def test_texto_invalido_lanza_url_invalida():
    with pytest.raises(URLInvalida):
        detectar_senales("javascript:alert(1)")


def test_no_se_puede_registrar_dos_veces_la_misma_senal():
    with pytest.raises(ValueError):
        heuristica("acortador")(lambda contexto: False)


def test_devuelve_las_senales_en_el_orden_del_registro():
    senales = detectar_senales("http://192.0.2.10/verifica")
    orden = list(HEURISTICAS)
    assert senales == sorted(senales, key=orden.index)
