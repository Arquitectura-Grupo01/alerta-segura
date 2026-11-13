"""Pruebas del motor de explicación."""

import itertools

import pytest

from analisis.heuristicas import HEURISTICAS
from motor.explicacion import (
    ACCIONES,
    ACLARACION_SEGURO,
    ADEMAS_IMITA,
    ANTIVIRUS_LA_MARCAN,
    ANTIVIRUS_LIMPIA,
    AVISO,
    DATOS_FUENTE,
    DETALLE_SENAL,
    DIRECCION_NORMAL,
    EL_OTRO_NO,
    ESCRIBE_LA_OFICIAL,
    ESTADO_FUENTE,
    FUENTES_CAIDAS,
    FUENTES_SOSPECHAN,
    GRUPOS_DE_FUENTES,
    IMITA_SIN_SENAL,
    LISTAS_NO_LA_REPORTAN,
    LOS_OTROS_NO,
    MAXIMO_MOTIVOS,
    MINIMO_MOTIVOS,
    MOTIVOS_REGLA,
    MOTIVOS_SENAL,
    MOTORES_SIN_TIPO,
    NADIE_LA_REPORTA,
    NADIE_LA_REVISO,
    NO_IMITA_MARCAS,
    NOTA_FUENTES,
    NOTA_REDIRECCIONES,
    PAISES,
    PISTA_MODALIDAD,
    REPORTA_UNO,
    REPORTAN_VARIOS,
    RESPALDO,
    SE_HACE_PASAR,
    SIGNIFICADO,
    SIN_CUPO,
    SIN_CUPO_VARIOS,
    SIN_DESTINO,
    SIN_REPORTE,
    TIPO_SIN_DETALLE,
    TIPOS_DE_AMENAZA,
    TITULAR,
    TITULAR_ANALISTA,
    TITULAR_EN_DUDA,
    TITULAR_IMITA,
    TITULAR_REPORTADA,
    TITULAR_SEGURO_CON_SENALES,
    TITULAR_SIN_HALLAZGOS,
    TITULAR_WEB_NUEVA,
    UNA_SOLA_SOSPECHA,
    UNO_NO_LA_REPORTA,
    USA_CANAL_OFICIAL,
    WEB_ANTIGUA,
    WEB_DE_MESES,
    FuenteConsultada,
    Recorrido,
    datos_de_fuente,
    explicar,
    terminos_prohibidos,
)
from motor.riesgo import NIVEL_DE_REGLA, Nivel, Senales, calcular


def _textos_para_la_persona():
    yield from MOTIVOS_REGLA.values()
    yield from MOTIVOS_SENAL.values()
    for acciones in ACCIONES.values():
        yield from acciones
    yield ACLARACION_SEGURO
    yield NOTA_REDIRECCIONES
    yield AVISO
    yield NOTA_FUENTES
    yield SIN_REPORTE
    yield FUENTES_SOSPECHAN
    yield SIN_CUPO
    yield SIN_CUPO_VARIOS
    yield UNA_SOLA_SOSPECHA
    yield from DATOS_FUENTE.values()
    yield from TIPOS_DE_AMENAZA.values()
    yield from PAISES.values()
    yield from (titulo for titulo, _ in GRUPOS_DE_FUENTES)
    yield from TITULAR.values()
    yield TITULAR_SIN_HALLAZGOS
    yield TITULAR_IMITA
    yield TITULAR_ANALISTA
    yield TITULAR_SEGURO_CON_SENALES
    yield PISTA_MODALIDAD
    yield USA_CANAL_OFICIAL
    yield ESCRIBE_LA_OFICIAL
    yield from (
        TITULAR_REPORTADA, TITULAR_EN_DUDA, TITULAR_WEB_NUEVA, MOTORES_SIN_TIPO, LOS_OTROS_NO,
        EL_OTRO_NO,
    )
    for respaldo in RESPALDO.values():
        yield from respaldo
    yield from SIGNIFICADO.values()
    yield from (
        REPORTA_UNO, REPORTAN_VARIOS, TIPO_SIN_DETALLE, ADEMAS_IMITA, SE_HACE_PASAR,
        ANTIVIRUS_LA_MARCAN, NADIE_LA_REPORTA, UNO_NO_LA_REPORTA, LISTAS_NO_LA_REPORTAN,
        NADIE_LA_REVISO, ANTIVIRUS_LIMPIA, WEB_ANTIGUA, WEB_DE_MESES, NO_IMITA_MARCAS,
        IMITA_SIN_SENAL, DIRECCION_NORMAL,
    )
    yield FUENTES_CAIDAS
    yield from ESTADO_FUENTE.values()
    yield SIN_DESTINO


def _combinaciones_de_senales():
    """Recorre combinaciones de evidencia para probar propiedades de toda explicación."""
    heuristicas = [(), ("acortador",), ("usuario_en_url", "palabras_sospechosas"),
                   ("ip_como_dominio", "punycode", "muchos_subdominios", "barra_invertida",
                    "punto_final", "dominio_parecido")]
    for codigos, edad, marca, fuentes, detecciones, analista, urgencia in itertools.product(
        heuristicas, [None, 2, 20, 200, 900], [None, 0, 100], [None, 0, 50, 100],
        [0, 1, 2], [False, True], [False, True],
    ):
        yield Senales(
            heuristicas=codigos,
            edad_dias=edad,
            marca=marca,
            fuentes=fuentes,
            fuentes_con_deteccion=detecciones if fuentes == 100 else 0,
            confirmado_por_analista=analista,
            credenciales_con_urgencia=urgencia,
        )


def test_cada_senal_tiene_motivo_y_detalle():
    assert set(HEURISTICAS) <= set(MOTIVOS_SENAL)
    assert set(HEURISTICAS) <= set(DETALLE_SENAL)


def test_cada_regla_tiene_motivo():
    assert set(NIVEL_DE_REGLA) <= set(MOTIVOS_REGLA)


def test_cada_nivel_tiene_al_menos_una_accion():
    for nivel in Nivel:
        assert len(ACCIONES[nivel]) >= 1


def test_ningun_texto_usa_terminos_prohibidos():
    for texto in _textos_para_la_persona():
        assert terminos_prohibidos(texto) == [], texto


def test_ningun_texto_usa_raya_ni_semirraya():
    for texto in _textos_para_la_persona():
        assert "\u2014" not in texto and "\u2013" not in texto, texto


def test_detecta_terminos_prohibidos_sin_importar_mayusculas():
    assert terminos_prohibidos("Es un sitio de Phishing") == ["phishing"]
    assert terminos_prohibidos("Revisa la URL") == ["url"]
    assert terminos_prohibidos("Es 100 % seguro") == ["100 % seguro"]
    assert terminos_prohibidos("Una web curiosa") == []


def test_todo_resultado_tiene_de_3_a_5_motivos_y_una_accion():
    for senales in _combinaciones_de_senales():
        veredicto = calcular(senales)
        explicacion = explicar(veredicto, "ejemplo.com")
        assert MINIMO_MOTIVOS <= len(explicacion.motivos) <= MAXIMO_MOTIVOS, senales
        assert len(set(explicacion.motivos)) == len(explicacion.motivos), senales
        assert explicacion.acciones, senales
        for motivo in explicacion.motivos:
            assert terminos_prohibidos(motivo) == [], motivo


def test_seguro_aclara_que_orienta_y_no_garantiza():
    veredicto = calcular(Senales(heuristicas=(), edad_dias=800, marca=0, fuentes=0))
    explicacion = explicar(veredicto, "ejemplo.com")
    assert veredicto.nivel == Nivel.SEGURO
    assert explicacion.aclaracion == ACLARACION_SEGURO
    assert "no una garantía" in explicacion.aclaracion


@pytest.mark.parametrize(
    "senales",
    [Senales(heuristicas=()), Senales(fuentes=100, fuentes_con_deteccion=2)],
)
def test_otros_niveles_no_llevan_aclaracion(senales):
    assert explicar(calcular(senales), "ejemplo.com").aclaracion is None


def test_si_una_regla_sube_el_nivel_su_motivo_va_primero():
    veredicto = calcular(Senales(heuristicas=()))
    motivos = explicar(veredicto, "ejemplo.com").motivos
    assert motivos[0] == MOTIVOS_REGLA["cobertura_baja_sin_hallazgos"]


def test_con_algo_en_contra_la_falta_de_informacion_se_dice_sin_suavizar():
    veredicto = calcular(Senales(heuristicas=("acortador",)))
    motivos = explicar(veredicto, "bit.ly").motivos
    assert MOTIVOS_REGLA["cobertura_baja"] in motivos
    assert MOTIVOS_REGLA["cobertura_baja_sin_hallazgos"] not in motivos


def test_una_sola_sospecha_se_dice_y_no_cuenta():
    consultadas = (("Lista A", "sospecha"), ("Lista B", "desconocido"))
    explicacion = explicar(calcular(Senales()), "ejemplo.com", fuentes=consultadas)
    assert UNA_SOLA_SOSPECHA in explicacion.motivos
    assert NADIE_LA_REVISO not in explicacion.motivos


def test_dos_sospechas_se_dicen_como_varios_servicios():
    explicacion = explicar(calcular(Senales(fuentes=50)), "ejemplo.com")
    assert FUENTES_SOSPECHAN in explicacion.motivos


def test_si_el_puntaje_decide_las_senales_van_primero():
    veredicto = calcular(Senales(heuristicas=("usuario_en_url",)))
    motivos = explicar(veredicto, "sitio-falso.com").motivos
    assert motivos[0] == MOTIVOS_SENAL["usuario_en_url"].format(dominio="sitio-falso.com")


def test_el_motivo_muestra_el_dominio_real():
    veredicto = calcular(Senales(heuristicas=("usuario_en_url",)))
    motivos = explicar(veredicto, "sitio-falso.com").motivos
    esperado = (
        "El enlace pone un nombre al inicio para confundir, pero en realidad abre "
        "sitio-falso.com."
    )
    assert esperado in motivos


def test_la_edad_se_dice_en_dias_y_una_sola_vez():
    veredicto = calcular(Senales(edad_dias=3, marca=100))
    motivos = explicar(veredicto, "ejemplo.com").motivos
    assert motivos[0] == "Imita a una marca conocida en una web creada hace 3 días."
    assert sum("hace 3 días" in motivo for motivo in motivos) == 1


def test_lo_que_no_se_pudo_revisar_no_es_un_motivo():
    """«No sabemos cuándo se creó» no le sirve a quien recibió el enlace."""
    for senales in _combinaciones_de_senales():
        for motivo in explicar(calcular(senales), "ejemplo.com").motivos:
            assert "No sabemos" not in motivo and "Todavía no la" not in motivo


def test_detalle_tecnico_explica_cada_termino():
    explicacion = explicar(calcular(Senales(heuristicas=("acortador",))), "bit.ly")
    assert [termino for termino, _, _ in explicacion.detalle] == [
        "Servicios de seguridad",
        "Edad de la web",
        "Trucos en la dirección",
    ]
    con_marca = explicar(calcular(Senales(marca=0)), "ejemplo.com").detalle
    assert ("Imita a una marca", "No") == con_marca[-1][:2]
    assert [termino for termino, _, _ in explicacion.calculo] == [
        "Puntaje de riesgo",
        "Información disponible",
        "Versión de reglas",
    ]
    assert all(nota for _, _, nota in explicacion.detalle + explicacion.calculo)
    assert explicacion.senales == (DETALLE_SENAL["acortador"],)


@pytest.mark.parametrize(("recorrido", "valor"), [
    (Recorrido(saltos=None), SIN_DESTINO),
    (Recorrido(saltos=0), "Ninguna"),
    (Recorrido(saltos=2), "2"),
    (Recorrido(saltos=1, desde="bit.ly"), "1, desde bit.ly"),
])
def test_el_detalle_dice_cuantas_redirecciones_hubo(recorrido, valor):
    detalle = explicar(calcular(Senales()), "ejemplo.com", recorrido).detalle
    assert detalle[0] == ("Redirecciones", valor, NOTA_REDIRECCIONES)
    assert len(detalle) == len(explicar(calcular(Senales()), "ejemplo.com").detalle) + 1


def test_las_fuentes_se_separan_en_con_evidencia_sin_reportes_y_no_respondieron():
    consultadas = (
        ("Lista A", "fallo"), ("Lista B", "desconocido"), ("Lista C", "deteccion"),
        ("Lista D", "sin_detecciones"), ("Lista E", "sospecha"),
    )
    grupos = explicar(calcular(Senales(fuentes=100, fuentes_con_deteccion=1)), "x.com",
                      fuentes=consultadas).fuentes
    assert [(grupo.titulo, [f.nombre for f in grupo.fuentes]) for grupo in grupos] == [
        ("Con evidencia", ["Lista C", "Lista D", "Lista E"]),
        ("Sin reportes", ["Lista B"]),
        ("No respondieron", ["Lista A"]),
    ]
    assert grupos[0].fuentes[0] == FuenteConsultada("Lista C", ESTADO_FUENTE["deteccion"])
    assert grupos[2].fuentes[0].estado == ESTADO_FUENTE["fallo"]


def test_un_grupo_sin_fuentes_no_aparece_y_sin_fuentes_no_hay_grupos():
    veredicto = calcular(Senales())
    assert explicar(veredicto, "x.com").fuentes == ()
    [grupo] = explicar(veredicto, "x.com", fuentes=(("Lista A", "fallo"),)).fuentes
    assert grupo.titulo == "No respondieron"


def test_cada_fuente_muestra_lo_que_conto_y_la_que_no_conto_nada_solo_su_estado():
    consultadas = (("Lista A", "deteccion"), ("Lista B", "desconocido"), ("Lista C", "desconocido"),
                   ("Lista D", "fallo"))
    detalles = {
        "Lista A": {"motores_peligrosa": 9, "motores_total": 93},
        "Lista B": {"ip": "203.0.113.7", "pais": "PE"},
        # De una fuente que no respondió no se muestra nada, aunque haya datos guardados.
        "Lista D": {"motores_peligrosa": 9, "motores_total": 93},
        "Otra": {"reportes": 5},
    }
    grupos = explicar(calcular(Senales(fuentes=100, fuentes_con_deteccion=1)), "x.com",
                      fuentes=consultadas, detalles=detalles).fuentes
    fuentes = {fuente.nombre: fuente for grupo in grupos for fuente in grupo.fuentes}
    assert fuentes["Lista A"].datos == ("9 de 93 antivirus la marcan como peligrosa.",)
    assert fuentes["Lista B"] == FuenteConsultada(
        "Lista B", SIN_REPORTE, ("Número del servidor: 203.0.113.7.", "El servidor está en Perú."),
    )
    assert fuentes["Lista C"] == FuenteConsultada("Lista C", ESTADO_FUENTE["desconocido"])
    assert fuentes["Lista D"] == FuenteConsultada("Lista D", ESTADO_FUENTE["fallo"])


@pytest.mark.parametrize(("datos", "frases"), [
    ({"tipos": ["pagina_falsa"]}, ["La clasifica como página falsa."]),
    ({"tipos": ["pagina_falsa", "programa_danino", "otro"]},
     ["La clasifica como página falsa y programa dañino."]),
    ({"motores_peligrosa": 1, "motores_total": 90, "motores_sospechosa": 1},
     ["1 de 90 antivirus la marca como peligrosa.", "1 antivirus la marca como sospechosa."]),
    ({"motores_peligrosa": 0, "motores_total": 90},
     ["Ninguno de sus 90 antivirus la marca como peligrosa."]),
    ({"motores_peligrosa": 4}, ["4 antivirus la marcan como peligrosa."]),
    # Sin motores que respondieron, el cero no dice nada.
    ({"motores_peligrosa": 0}, []),
    ({"motores_peligrosa": 9, "motores_total": 3}, ["9 antivirus la marcan como peligrosa."]),
    ({"puntaje": 100, "marcas": ["Banco de Prueba", "Tienda"]},
     ["Le da 100 de 100 puntos de riesgo.", "Dice que imita a Banco de Prueba, Tienda."]),
    ({"puntaje": 0}, []),
    ({"por_la_web": True, "web_peligrosa": 0, "web_sospechosa": 0, "web_total": 92,
      "en_ranking": True},
     [DATOS_FUENTE["por_la_web"],
      "Ninguno de sus 92 antivirus marca la web completa como peligrosa.",
      "Figura en las listas de las webs más visitadas."]),
    ({"web_peligrosa": 1, "web_sospechosa": 2, "web_total": 92},
     ["3 de 92 antivirus marcan la web completa como peligrosa o sospechosa."]),
    ({"web_peligrosa": 0}, []),
    ({"archivos": 1, "familias": ["elf", "Mozi"], "agregada": "2026-11-13T05:47:15+00:00"},
     ["Etiquetas del reporte: elf, Mozi.", "Entrega 1 archivo dañino conocido.",
      "La reportaron el 13 de noviembre de 2026."]),
    ({"votos_peligrosa": 7}, ["Votos de su comunidad: peligrosa 7."]),
    ({"votos_peligrosa": 7, "votos_confiable": 2},
     ["Votos de su comunidad: peligrosa 7, confiable 2."]),
    ({"reportes": 472, "periodo_dias": 90, "personas": 133, "confianza": 100,
      "ultimo_reporte": "2026-11-13T03:32:24+00:00"},
     ["472 reportes de abuso contra ese servidor en los últimos 90 días.",
      "Los enviaron 133 personas distintas.", "Nivel de abuso: 100 de 100.",
      "Último reporte: 13 de noviembre de 2026."]),
    ({"reportes": 1, "periodo_dias": 90, "personas": 1, "confianza": 0},
     ["1 reporte de abuso contra ese servidor en los últimos 90 días.",
      "Nivel de abuso: 0 de 100."]),
    # Sin reportes, la confianza y la fecha no se muestran.
    ({"confianza": 0, "personas": 0, "ultimo_reporte": "2026-11-13T03:32:24+00:00"}, []),
    ({"pais": "de", "proveedor": "Proveedor S.A.", "red_tor": True, "lista_blanca": True},
     ["El servidor está en Alemania.", "Lo aloja Proveedor S.A.",
      "El servidor es una salida de la red Tor, que oculta de dónde viene alguien.",
      "El servidor está en su lista de servidores de confianza."]),
    ({"pais": "ZZ"}, ["El servidor está en el país de código ZZ."]),
    ({"pais": "Perú"}, []),
    ({"conocida_dias": 2900}, ["Este servicio conoce la web hace 7 años."]),
    ({"edad_web_dias": 3525, "certificado_dias": 9},
     ["Según este servicio, la web existe hace 9 años.",
      "Su certificado de seguridad se emitió hace 9 días."]),
    ({"analizado": "2026-11-12T15:10:49+00:00", "de_otra_pagina": True},
     ["Última revisión: 12 de noviembre de 2026.",
      "Estos datos son de otra página de la misma web."]),
    # Sin ningún otro dato, el aviso de «otra página» no tiene a qué referirse.
    ({"de_otra_pagina": True}, []),
    ({"analizado": "no es fecha", "primera_vez": 7, "amenazas": "texto", "ip": 5}, []),
    ({}, []),
])
def test_cada_dato_de_una_fuente_tiene_su_frase_y_el_que_falta_no_deja_hueco(datos, frases):
    assert list(datos_de_fuente(datos)) == frases


def test_un_analisis_limpio_pero_viejo_dice_que_no_alcanza():
    datos = {"motores_peligrosa": 0, "motores_total": 90, "analizado": "2022-10-29T15:52:26+00:00"}
    assert datos_de_fuente(datos, "desconocido")[-1] == DATOS_FUENTE["revision_antigua"].format(
        fecha="29 de octubre de 2022"
    )
    reciente = datos_de_fuente(datos, "sin_detecciones")
    assert reciente[-1] == "Última revisión: 29 de octubre de 2022."


@pytest.mark.parametrize("datos", [None, "texto", 7, ["a"]])
def test_un_detalle_que_no_es_un_diccionario_no_deja_frases(datos):
    assert datos_de_fuente(datos) == ()


@pytest.mark.parametrize(("consultadas", "motivo"), [
    ((("Lista A", "fallo"), ("Lista B", "fallo")), FUENTES_CAIDAS),
    ((("Lista A", "desconocido"), ("Lista B", "fallo")), NADIE_LA_REVISO),
    ((("Lista A", "desconocido"), ("Lista B", "fallo")), UNO_NO_LA_REPORTA),
    ((("Lista A", "desconocido"), ("Lista B", "desconocido"), ("Lista C", "fallo")),
     NADIE_LA_REPORTA.format(cantidad=2)),
])
def test_una_fuente_caida_o_sin_datos_se_dice_y_no_cuenta_como_limpia(consultadas, motivo):
    explicacion = explicar(calcular(Senales()), "ejemplo.com", fuentes=consultadas)
    assert motivo in explicacion.motivos
    assert "Todavía no la buscamos en listas de seguridad." not in explicacion.motivos


# --- El reporte que lee la persona -------------------------------------------

PELIGRO_ALTO = Senales(fuentes=100, fuentes_con_deteccion=3)
REPORTAN = (
    ("Google Safe Browsing", "deteccion"), ("VirusTotal", "deteccion"),
    ("urlscan.io", "deteccion"), ("URLhaus", "desconocido"), ("AbuseIPDB", "fallo"),
)
CONTADO = {
    "Google Safe Browsing": {"tipos": ["pagina_falsa"]},
    "VirusTotal": {"motores_peligrosa": 9, "motores_total": 93},
    "urlscan.io": {"tipos": ["pagina_falsa"], "marcas": ["Banco de Prueba"]},
}


def test_un_peligro_alto_dice_quien_la_reporta_cuantos_antivirus_y_a_quien_imita():
    motivos = explicar(calcular(PELIGRO_ALTO), "x.example", fuentes=REPORTAN,
                       detalles=CONTADO).motivos
    assert motivos == (
        "Google Safe Browsing, VirusTotal y urlscan.io la tienen reportada como página falsa.",
        "9 de 93 antivirus la marcan como peligrosa.",
        "Se hace pasar por Banco de Prueba.",
        SIGNIFICADO["pagina_falsa"],
        RESPALDO[Nivel.PELIGRO_ALTO][0],
    )[:len(motivos)]
    assert len(motivos) >= 4


def test_pasado_un_dia_el_peligro_alto_sigue_nombrando_a_quien_la_reporta():
    motivos = explicar(calcular(PELIGRO_ALTO), "x.example", fuentes=REPORTAN).motivos
    assert motivos[0] == (
        "Google Safe Browsing, VirusTotal y urlscan.io la tienen reportada como página falsa "
        "o peligrosa."
    )
    assert motivos[1] == SIGNIFICADO[""]
    assert len(motivos) >= 3


def test_un_programa_danino_se_explica_distinto_que_una_pagina_falsa():
    motivos = explicar(
        calcular(Senales(fuentes=100, fuentes_con_deteccion=1)), "x.example",
        fuentes=(("URLhaus", "deteccion"),), detalles={"URLhaus": {"tipos": ["programa_danino"]}},
    ).motivos
    assert motivos[0] == "URLhaus la tiene reportada como programa dañino."
    assert SIGNIFICADO["programa_danino"] in motivos


@pytest.mark.parametrize("senales", [
    PELIGRO_ALTO,
    Senales(fuentes=100, fuentes_con_deteccion=1),
    Senales(heuristicas=("ip_como_dominio", "palabras_sospechosas", "usuario_en_url"),
            edad_dias=3, marca=100),
])
def test_un_resultado_peligroso_no_trae_frases_tranquilizadoras_ni_huecos(senales):
    veredicto = calcular(senales)
    assert veredicto.nivel >= Nivel.PELIGROSO
    motivos = explicar(veredicto, "x.example", fuentes=REPORTAN, detalles=CONTADO).motivos
    for motivo in motivos:
        assert motivo not in (DIRECCION_NORMAL, NO_IMITA_MARCAS, NADIE_LA_REVISO)
        assert "No sabemos" not in motivo and "Todavía no" not in motivo
        assert "existe hace" not in motivo


def test_un_seguro_cuenta_lo_que_se_comprobo():
    consultadas = (("VirusTotal", "sin_detecciones"), ("urlscan.io", "sin_detecciones"),
                   ("URLhaus", "desconocido"), ("AbuseIPDB", "fallo"))
    detalles = {"VirusTotal": {"web_peligrosa": 0, "web_total": 92}}
    explicacion = explicar(
        calcular(Senales(fuentes=0, edad_dias=9600, marca=0)), "banco.example",
        fuentes=consultadas, detalles=detalles,
    )
    assert explicacion.titular == TITULAR[Nivel.SEGURO]
    assert explicacion.motivos == (
        "Ninguno de los 3 servicios de seguridad que consultamos la tiene reportada.",
        "VirusTotal la revisó con 92 antivirus y ninguno la marca como peligrosa.",
        "La web existe hace 26 años. Las estafas suelen usar webs creadas hace pocos días.",
        NO_IMITA_MARCAS,
        DIRECCION_NORMAL,
    )
    assert explicacion.acciones[0] == (
        "Puedes abrirla. Antes de escribir una clave, mira que la dirección de arriba diga "
        "banco.example."
    )


def test_un_ten_cuidado_sin_hallazgos_no_acusa_y_dice_que_falta():
    consultadas = (("VirusTotal", "desconocido"), ("urlscan.io", "desconocido"))
    explicacion = explicar(calcular(Senales(edad_dias=900)), "tienda.example", fuentes=consultadas)
    assert explicacion.titular == TITULAR_SIN_HALLAZGOS
    assert explicacion.motivos == (
        MOTIVOS_REGLA["cobertura_baja_sin_hallazgos"],
        "Ninguno de los 2 servicios de seguridad que consultamos la tiene reportada.",
        NADIE_LA_REVISO,
        "La web existe hace 2 años. Las estafas suelen usar webs creadas hace pocos días.",
        DIRECCION_NORMAL,
    )


def test_un_ten_cuidado_con_senales_lo_dice_en_el_titular():
    explicacion = explicar(calcular(Senales(heuristicas=("acortador",))), "bit.ly")
    assert explicacion.titular == TITULAR[Nivel.TEN_CUIDADO]
    web_nueva = explicar(calcular(Senales(edad_dias=4, fuentes=0, marca=0)), "x.example")
    assert web_nueva.titular == TITULAR_WEB_NUEVA


def test_cada_nivel_tiene_su_titular_y_sus_propias_acciones():
    titulares = {TITULAR[nivel] for nivel in Nivel} | {TITULAR_SIN_HALLAZGOS}
    assert len(titulares) == len(Nivel) + 1
    primeras = {ACCIONES[nivel][0] for nivel in Nivel}
    assert len(primeras) == len(Nivel)
    for nivel in (Nivel.TEN_CUIDADO, Nivel.PELIGROSO, Nivel.PELIGRO_ALTO):
        assert len(ACCIONES[nivel]) == 3


@pytest.mark.parametrize(("edad_dias", "texto"), [
    (3, "3 días"), (365, "365 días"), (400, "más de un año"), (730, "2 años"), (9600, "26 años"),
])
def test_la_edad_de_la_web_se_dice_como_la_diria_una_persona(edad_dias, texto):
    detalle = dict((termino, valor) for termino, valor, _ in
                   explicar(calcular(Senales(edad_dias=edad_dias)), "x.example").detalle)
    assert detalle["Edad de la web"] == texto


@pytest.mark.parametrize(("consultadas", "valor"), [
    (REPORTAN, "La reportan 3 de 4"),
    ((("A", "desconocido"), ("B", "sin_detecciones"), ("C", "fallo")), "Ninguno de 2 la reporta"),
    ((("A", "fallo"),), "No respondieron"),
    ((), "Sin consultar"),
])
def test_el_detalle_resume_los_servicios_de_seguridad(consultadas, valor):
    senales = PELIGRO_ALTO if valor.startswith("La reportan") else Senales()
    detalle = dict((termino, v) for termino, v, _ in
                   explicar(calcular(senales), "x.example", fuentes=consultadas).detalle)
    assert detalle["Servicios de seguridad"] == valor


def test_en_un_peligroso_la_falta_de_informacion_no_es_un_motivo():
    veredicto = calcular(Senales(heuristicas=("ip_como_dominio", "palabras_sospechosas")))
    assert veredicto.nivel == Nivel.PELIGROSO and "cobertura_baja" in veredicto.reglas
    motivos = explicar(veredicto, "192.0.2.10").motivos
    assert MOTIVOS_REGLA["cobertura_baja"] not in motivos
    assert motivos[2] == RESPALDO[Nivel.PELIGROSO][0]


# --- Un servicio sin cupo ------------------------------------------------------

def test_un_servicio_sin_cupo_se_dice_y_se_invita_a_reintentar():
    consultadas = (("VirusTotal", "sin_cupo"), ("urlscan.io", "desconocido"))
    explicacion = explicar(calcular(Senales(edad_dias=900)), "x.example", fuentes=consultadas)
    assert SIN_CUPO.format(nombres="VirusTotal") in explicacion.motivos
    assert UNO_NO_LA_REPORTA in explicacion.motivos
    [sin_reportes, no_respondieron] = explicacion.fuentes
    assert no_respondieron.fuentes[0].estado == "Llegó a su límite de consultas por ahora"
    detalle = dict((termino, valor) for termino, valor, _ in explicacion.detalle)
    assert detalle["Servicios de seguridad"] == "Ninguno de 1 la reporta"


def test_si_todos_los_servicios_estan_sin_cupo_no_se_dice_que_fallaron():
    consultadas = (("VirusTotal", "sin_cupo"), ("urlscan.io", "sin_cupo"))
    motivos = explicar(calcular(Senales()), "x.example", fuentes=consultadas).motivos
    assert SIN_CUPO_VARIOS.format(nombres="VirusTotal y urlscan.io") in motivos
    assert FUENTES_CAIDAS not in motivos


@pytest.mark.parametrize("senales", [
    # Otro servicio ya dio un análisis limpio: el que falta no cambia nada.
    Senales(fuentes=0, edad_dias=900, marca=0),
    # En un resultado peligroso, reintentar no es el consejo.
    Senales(fuentes=100, fuentes_con_deteccion=2),
])
def test_el_aviso_de_cupo_solo_sale_si_ese_servicio_podia_cambiar_el_resultado(senales):
    consultadas = (("VirusTotal", "sin_cupo"), ("urlscan.io", "deteccion"))
    motivos = explicar(calcular(senales), "x.example", fuentes=consultadas).motivos
    assert not any("límite de consultas" in motivo for motivo in motivos)


# --- El titular solo afirma lo que la evidencia respalda -----------------------

@pytest.mark.parametrize(("senales", "titular"), [
    (Senales(fuentes=100, fuentes_con_deteccion=1), TITULAR_REPORTADA),
    (Senales(heuristicas=("ip_como_dominio", "palabras_sospechosas")), TITULAR[Nivel.PELIGROSO]),
    (Senales(fuentes_en_duda=True), TITULAR_EN_DUDA),
    (Senales(fuentes_en_duda=True, fuentes=0, edad_dias=9000, marca=0), TITULAR_EN_DUDA),
])
def test_el_titular_depende_de_la_evidencia(senales, titular):
    assert explicar(calcular(senales), "x.example").titular == titular


def test_ningun_titular_de_un_resultado_reportado_habla_de_estafa():
    for senales in (Senales(fuentes=100, fuentes_con_deteccion=1), Senales(fuentes_en_duda=True)):
        assert "estafa" not in explicar(calcular(senales), "x.example").titular


def test_una_fuente_no_concluyente_dice_cuantos_la_marcan_y_que_dicen_los_demas():
    consultadas = (("VirusTotal", "no_concluyente"), ("A", "desconocido"), ("B", "desconocido"),
                   ("C", "fallo"))
    detalles = {"VirusTotal": {"motores_peligrosa": 3, "motores_total": 93, "sin_categoria": True}}
    explicacion = explicar(calcular(Senales(fuentes_en_duda=True)), "x.example",
                           fuentes=consultadas, detalles=detalles)
    assert explicacion.motivos[:2] == (
        MOTORES_SIN_TIPO.format(cantidad=3, total=93, nombre="VirusTotal"),
        LOS_OTROS_NO.format(cantidad=2),
    )
    sin_detalle = explicar(calcular(Senales(fuentes_en_duda=True)), "x.example",
                           fuentes=consultadas)
    assert sin_detalle.motivos[0] == MOTIVOS_REGLA["fuente_no_concluyente"]
    [con_evidencia, _, _] = explicacion.fuentes
    assert con_evidencia.fuentes[0].datos[:2] == (
        "3 de 93 antivirus la marcan como peligrosa.",
        "Ninguno de esos antivirus dice de qué tipo es la amenaza.",
    )
