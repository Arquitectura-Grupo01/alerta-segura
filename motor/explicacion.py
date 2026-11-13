"""Motor de explicación: traduce un veredicto a motivos y acciones en español cotidiano.

Todos los textos que ve la persona están en este módulo, para poder cambiarlos
después de la prueba de comprensión sin buscarlos por el código.

Cada motivo cuenta algo que se encontró o se comprobó y que a la persona le sirve
para decidir. Empiezan por lo que decidió el nivel, con nombres y números cuando los
hay (qué servicios la reportan, cuántos antivirus, a quién imita), siguen con las
señales de la dirección y terminan con lo que se revisó. Lo que no se pudo revisar
solo se dice cuando explica por qué el resultado no es Seguro: en un resultado
peligroso, un dato que falta no le sirve a nadie.

Los textos se muestran con el autoescapado de Django: el dominio que se inserta
en un motivo nunca se marca como seguro.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType

from motor.riesgo import (
    EDAD,
    FUENTES,
    HEURISTICAS,
    MARCA,
    NIVEL_DE_REGLA,
    SENALES_DE_MARCA,
    Nivel,
    Veredicto,
)

MINIMO_MOTIVOS = 3
# Con menos días que estos, una web es nueva. Es el valor de la versión de reglas.
DIAS_WEB_NUEVA = 30
MAXIMO_MOTIVOS = 5

# Términos que no se usan con la persona, con lo que se dice en su lugar.
TERMINOS_PROHIBIDOS = MappingProxyType({
    "phishing": "página falsa",
    "malware": "programa dañino",
    "dominio reciente": "web creada hace 3 días",
    "subdominio": "palabras antes del nombre de la web",
    "punycode": "letras especiales",
    "url": "enlace o dirección",
    "100 % seguro": "una orientación, no una garantía",
    "100% seguro": "una orientación, no una garantía",
})

MOTIVOS_REGLA = MappingProxyType({
    "dos_fuentes_confirman": "Varias listas de seguridad la tienen reportada como página falsa "
    "o peligrosa.",
    "fuente_y_suplantacion": "Una lista de seguridad la tiene reportada y además imita a una "
    "marca conocida.",
    "analista_confirma": "Nuestro equipo revisó esta web y confirmó que es una estafa.",
    "una_fuente_confirma": "Una lista de seguridad la tiene reportada como página falsa o "
    "peligrosa.",
    "suplantacion_en_web_nueva": "Imita a una marca conocida en una web creada hace {edad}.",
    "credenciales_con_urgencia": "Te pide claves o un pago con prisa o con amenazas.",
    "web_nueva": "La web se creó hace {edad}. Muchas estafas usan webs recién creadas.",
    "fuente_no_concluyente": "Un servicio de seguridad la marca como peligrosa, pero no dice "
    "de qué tipo. No alcanza para confirmarlo.",
    "cobertura_baja": "Todavía no tenemos datos suficientes para decir que es segura.",
    # La misma regla cuando no se encontró nada en contra: no debe sonar a acusación.
    "cobertura_baja_sin_hallazgos": "No encontramos nada malo, pero nos falta información "
    "para decir que es segura.",
})

# Un motivo que ya cuenta lo mismo que otro lo reemplaza.
REEMPLAZA = MappingProxyType({
    "fuente_y_suplantacion": frozenset({"una_fuente_confirma"}),
    "suplantacion_en_web_nueva": frozenset({"web_nueva"}),
})

# Reglas cuyo motivo ya dice la edad de la web.
EDAD_YA_CONTADA = frozenset({"web_nueva", "suplantacion_en_web_nueva"})

MOTIVOS_SENAL = MappingProxyType({
    "ip_como_dominio": "La dirección es una serie de números y no el nombre de una web. "
    "Los bancos y las tiendas no usan direcciones así.",
    "ip_alternativa": "La dirección es un número escrito de una forma rara para esconder a "
    "dónde lleva.",
    "acortador": "Es un enlace acortado. No deja ver a qué web lleva hasta que lo abres.",
    "punycode": "El nombre de la web usa letras especiales que pueden imitar a las normales.",
    "alfabetos_mezclados": "El nombre de la web mezcla letras de otros alfabetos que se ven "
    "iguales a las nuestras.",
    "usuario_en_url": "El enlace pone un nombre al inicio para confundir, pero en realidad "
    "abre {dominio}.",
    "barra_invertida": "El enlace usa la barra «\\» para confundir sobre la web que abre.",
    "caracteres_de_control": "El enlace trae caracteres invisibles que el navegador borra al "
    "abrirlo.",
    "punto_final": "El nombre de la web termina en un punto, un truco para pasar algunos "
    "filtros.",
    "muchos_subdominios": "La dirección pone muchas palabras antes del nombre real de la web "
    "para esconderlo.",
    "palabras_sospechosas": "La dirección usa palabras como «verifica» o «login», típicas de "
    "las páginas falsas que piden claves.",
    "marca_en_subdominio": "Usa el nombre de una marca conocida, pero la web que abre es "
    "{dominio}.",
    "dominio_parecido": "Su nombre se parece mucho al de una marca conocida, pero no es su web "
    "oficial.",
})

# Nombre y explicación de una línea de cada señal, para el detalle técnico.
DETALLE_SENAL = MappingProxyType({
    "ip_como_dominio": ("IP en lugar de nombre", "La dirección usa números en vez de un nombre."),
    "ip_alternativa": (
        "IP disfrazada",
        "Un número que el navegador convierte en una dirección de internet.",
    ),
    "acortador": ("Enlace acortado", "Un servicio que esconde la dirección real detrás de otra."),
    "punycode": ("Letras especiales", "El nombre usa letras fuera del alfabeto común."),
    "alfabetos_mezclados": (
        "Alfabetos mezclados",
        "Letras de otro alfabeto, como el cirílico, que imitan a las nuestras.",
    ),
    "usuario_en_url": (
        "Texto antes de «@»",
        "El navegador ignora lo que va antes de «@» y abre lo que sigue.",
    ),
    "barra_invertida": (
        "Barra invertida",
        "El navegador lee «\\» como «/» y eso cambia la web que abre.",
    ),
    "caracteres_de_control": (
        "Caracteres invisibles",
        "Saltos de línea o tabulaciones que el navegador borra.",
    ),
    "punto_final": ("Punto al final del nombre", "Un punto final que algunos filtros no esperan."),
    "muchos_subdominios": (
        "Muchas partes antes del nombre",
        "Más de 3 partes antes del nombre real de la web.",
    ),
    "palabras_sospechosas": (
        "Palabras para pedir claves",
        "Palabras como «login» o «verifica» en la dirección.",
    ),
    "marca_en_subdominio": (
        "Marca delante de otra web",
        "El nombre de una marca puesto delante del nombre real de la web.",
    ),
    "dominio_parecido": (
        "Nombre parecido a una marca",
        "A 1 o 2 letras del nombre de una web oficial.",
    ),
})

# `{dominio}` es la web que abre el enlace.
ACCIONES = MappingProxyType({
    Nivel.SEGURO: (
        "Puedes abrirla. Antes de escribir una clave, mira que la dirección de arriba diga "
        "{dominio}.",
        "Si la página te apura para pagar o te pide un código que llegó a tu celular, ciérrala.",
    ),
    Nivel.TEN_CUIDADO: (
        "No escribas claves, códigos ni los datos de tu tarjeta en esa web.",
        "Si dice ser de tu banco o de una tienda, entra tú mismo desde su app o escribiendo su "
        "dirección oficial.",
        "Pregunta a quien te lo envió, por otro medio, si de verdad lo mandó.",
    ),
    Nivel.PELIGROSO: (
        "No abras el enlace ni respondas el mensaje.",
        "No entregues datos ni hagas pagos que te pidan desde ahí.",
        "Avisa a quien te lo envió: puede que le hayan robado la cuenta.",
    ),
    Nivel.PELIGRO_ALTO: (
        "No abras el enlace, no respondas y borra el mensaje.",
        "Bloquea el número o la cuenta que te lo envió.",
        "Si ya diste tus claves o pagaste, llama a tu banco con el número de tu tarjeta o de su "
        "app.",
    ),
})

# Una frase bajo el nivel que resume el resultado.
TITULAR = MappingProxyType({
    Nivel.SEGURO: "No encontramos señales de estafa en esta web.",
    Nivel.TEN_CUIDADO: "Tiene señales que suelen usar las estafas.",
    Nivel.PELIGROSO: "Su dirección tiene varios trucos que usan las estafas. No la abras.",
    Nivel.PELIGRO_ALTO: "Varias pruebas confirman que es peligrosa. No la abras.",
})
TITULAR_SIN_HALLAZGOS = "No podemos confirmar que sea segura."
# El titular solo afirma lo que la evidencia respalda.
TITULAR_REPORTADA = "Está reportada como peligrosa. No la abras."
TITULAR_EN_DUDA = "Los servicios de seguridad no se ponen de acuerdo sobre esta web."
TITULAR_WEB_NUEVA = "Es una web recién creada."
MOTORES_SIN_TIPO = (
    "{cantidad} de {total} antivirus de {nombre} la marcan como peligrosa, pero ninguno dice "
    "de qué tipo. No alcanza para confirmarlo."
)
LOS_OTROS_NO = "Los otros {cantidad} servicios de seguridad que consultamos no la tienen reportada."
EL_OTRO_NO = "El otro servicio de seguridad que consultamos no la tiene reportada."

# Motivos con lo que dijeron los servicios de seguridad.
REPORTA_UNO = "{nombres} la tiene reportada como {tipo}."
REPORTAN_VARIOS = "{nombres} la tienen reportada como {tipo}."
TIPO_SIN_DETALLE = "página falsa o peligrosa"
ADEMAS_IMITA = "Además, imita el nombre de una marca conocida."
SE_HACE_PASAR = "Se hace pasar por {marcas}."
ANTIVIRUS_LA_MARCAN = "{cantidad} de {total} antivirus la marcan como peligrosa."
# Qué quiere decir el reporte para quien recibió el enlace.
SIGNIFICADO = MappingProxyType({
    "pagina_falsa": "Una página falsa copia a una web real para robarte claves o dinero.",
    "programa_danino": "Puede instalar un programa dañino en tu celular o computadora.",
    # Sin el tipo no se afirma qué hace la web.
    "": "No dicen de qué tipo es la amenaza, solo que es peligrosa.",
})
NADIE_LA_REPORTA = (
    "Ninguno de los {cantidad} servicios de seguridad que consultamos la tiene reportada."
)
UNO_NO_LA_REPORTA = "El servicio de seguridad que consultamos no la tiene reportada."
LISTAS_NO_LA_REPORTAN = "Las listas de seguridad que consultamos no la tienen reportada."
NADIE_LA_REVISO = "Ninguno la revisó hace poco, así que no pueden confirmar que esté limpia."
ANTIVIRUS_LIMPIA = "{nombre} la revisó con {total} antivirus y ninguno la marca como peligrosa."
WEB_ANTIGUA = "La web existe hace {edad}. Las estafas suelen usar webs creadas hace pocos días."
WEB_DE_MESES = "La web se creó hace {edad}."
NO_IMITA_MARCAS = "No imita el nombre de los bancos y tiendas que tenemos registrados."
IMITA_SIN_SENAL = "Usa el nombre de una marca conocida, pero no es su web oficial."
DIRECCION_NORMAL = (
    "La dirección está escrita de forma normal, sin trucos para parecerse a otra web."
)
# Si aun así faltan motivos, estos completan el mínimo. Son consejos, no hallazgos.
RESPALDO = MappingProxyType({
    Nivel.SEGURO: (
        "Una web puede cambiar: si algo te parece raro, vuelve a analizarla.",
        "Revisamos la dirección y la web que abre, no lo que te piden dentro.",
    ),
    Nivel.TEN_CUIDADO: (
        "Si no esperabas este enlace, desconfía aunque venga de un contacto.",
        "Una web puede ser nueva o poco conocida y ser legítima, pero conviene confirmarlo.",
    ),
    Nivel.PELIGROSO: (
        "El resultado vale para esta dirección, no para todas las páginas de la misma web.",
        "La revisamos nosotros: el enlace no se abrió en tu celular.",
    ),
    Nivel.PELIGRO_ALTO: (
        "El resultado vale para esta dirección, no para todas las páginas de la misma web.",
        "La revisamos nosotros: el enlace no se abrió en tu celular.",
    ),
})

ACLARACION_SEGURO = "Es una orientación, no una garantía: una web puede cambiar después de hoy."

NOTA_REDIRECCIONES = (
    "Veces que el enlace pasa a otra dirección antes de llegar. Las seguimos nosotros y el "
    "enlace nunca se abre en tu celular."
)
SIN_DESTINO = "No pudimos seguir el enlace"
OCUPADO = "Estamos revisando muchos enlaces a la vez. Espera unos segundos y vuelve a intentarlo."

AVISO = (
    "Revisé en Alerta Segura un enlace que me llegó y salió «{nivel}». Lleva a {dominio}. "
    "Si te llega a ti, {accion}"
)

# Estado de cada servicio de seguridad consultado, con los códigos de `inteligencia`.
ESTADO_FUENTE = MappingProxyType({
    "deteccion": "La tiene reportada",
    "sospecha": "La marca como sospechosa",
    "no_concluyente": "La marca como peligrosa, sin decir de qué tipo",
    "sin_detecciones": "La revisó hace poco y no encontró nada",
    "desconocido": "No tiene datos de esta web",
    "fallo": "No respondió",
    "sin_cupo": "Llegó a su límite de consultas por ahora",
})
# Estados en que el servicio no dijo nada de la web.
NO_RESPONDIO = frozenset({"fallo", "sin_cupo"})
SIN_CUPO = (
    "{nombres} llegó a su límite de consultas. Vuelve a analizarla en unos minutos para un "
    "resultado más completo."
)
SIN_CUPO_VARIOS = (
    "{nombres} llegaron a su límite de consultas. Vuelve a analizarla en unos minutos para un "
    "resultado más completo."
)
# Un servicio sin reporte que igual contó algo, como dónde está alojada la web.
SIN_REPORTE = "No la tiene reportada"
NOTA_FUENTES = (
    "Si un servicio no responde o no tiene datos, eso no cuenta como web limpia. Lo que "
    "cuenta cada uno se muestra durante un día."
)
# Los servicios se muestran en tres grupos, en este orden.
GRUPOS_DE_FUENTES = (
    ("Con evidencia", frozenset({"deteccion", "sospecha", "no_concluyente", "sin_detecciones"})),
    ("Sin reportes", frozenset({"desconocido"})),
    ("No respondieron", NO_RESPONDIO),
)

# Cómo se nombra cada tipo de amenaza que informa un servicio.
TIPOS_DE_AMENAZA = MappingProxyType({
    "pagina_falsa": "página falsa",
    "programa_danino": "programa dañino",
    "programa_no_deseado": "programa no deseado",
    "aplicacion_riesgosa": "aplicación riesgosa",
})

# Frases del detalle de un servicio. Cada una sale solo si el servicio trajo ese dato.
DATOS_FUENTE = MappingProxyType({
    "tipos": "La clasifica como {lista}.",
    "motores": "{cantidad} de {total} antivirus la marcan como peligrosa.",
    "un_motor": "1 de {total} antivirus la marca como peligrosa.",
    "ningun_motor": "Ninguno de sus {total} antivirus la marca como peligrosa.",
    "motores_sin_total": "{cantidad} antivirus la marcan como peligrosa.",
    "motores_sospechosa": "{cantidad} antivirus la marcan como sospechosa.",
    "un_motor_sospechosa": "1 antivirus la marca como sospechosa.",
    "sin_categoria": "Ninguno de esos antivirus dice de qué tipo es la amenaza.",
    "puntaje": "Le da {cantidad} de 100 puntos de riesgo.",
    "marcas": "Dice que imita a {lista}.",
    "amenazas": "Nombre que le dan los antivirus: {lista}.",
    "familias": "Etiquetas del reporte: {lista}.",
    "archivos": "Entrega {cantidad} archivos dañinos conocidos.",
    "un_archivo": "Entrega 1 archivo dañino conocido.",
    "dada_de_baja": "La dirección figura como dada de baja.",
    "agregada": "La reportaron el {fecha}.",
    "analizado": "Última revisión: {fecha}.",
    "revision_antigua": "Última revisión: {fecha}. Es muy antigua para decir que está limpia.",
    "por_la_web": "Nadie revisó hace poco esta dirección exacta. Vale la revisión de la web "
    "completa.",
    "web_limpia": "Ninguno de sus {total} antivirus marca la web completa como peligrosa.",
    "web_marcada": "{cantidad} de {total} antivirus marcan la web completa como peligrosa o "
    "sospechosa.",
    "en_ranking": "Figura en las listas de las webs más visitadas.",
    "de_otra_pagina": "Estos datos son de otra página de la misma web.",
    "primera_vez": "La vio por primera vez el {fecha}.",
    "votos": "Votos de su comunidad: peligrosa {peligrosa}, confiable {confiable}.",
    "votos_peligrosa": "Votos de su comunidad: peligrosa {peligrosa}.",
    "votos_confiable": "Votos de su comunidad: confiable {confiable}.",
    "ip": "Número del servidor: {ip}.",
    "pais": "El servidor está en {pais}.",
    "proveedor": "Lo aloja {proveedor}.",
    "red_tor": "El servidor es una salida de la red Tor, que oculta de dónde viene alguien.",
    "reportes": "{cantidad} reportes de abuso contra ese servidor en los últimos {dias} días.",
    "un_reporte": "1 reporte de abuso contra ese servidor en los últimos {dias} días.",
    "personas": "Los enviaron {cantidad} personas distintas.",
    "confianza": "Nivel de abuso: {cantidad} de 100.",
    "ultimo_reporte": "Último reporte: {fecha}.",
    "lista_blanca": "El servidor está en su lista de servidores de confianza.",
    "edad_web": "Según este servicio, la web existe hace {edad}.",
    "conocida": "Este servicio conoce la web hace {edad}.",
    "certificado": "Su certificado de seguridad se emitió hace {edad}.",
})

MESES = (
    "enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre",
    "octubre", "noviembre", "diciembre",
)

# Código de país de dos letras y su nombre. Uno que no está aquí se muestra con su código.
PAISES = MappingProxyType({
    "AR": "Argentina", "AU": "Australia", "BG": "Bulgaria", "BO": "Bolivia", "BR": "Brasil",
    "CA": "Canadá", "CH": "Suiza", "CL": "Chile", "CN": "China", "CO": "Colombia",
    "CZ": "República Checa", "DE": "Alemania", "EC": "Ecuador", "ES": "España",
    "FI": "Finlandia", "FR": "Francia", "GB": "Reino Unido", "HK": "Hong Kong",
    "ID": "Indonesia", "IE": "Irlanda", "IN": "India", "IR": "Irán", "IT": "Italia",
    "JP": "Japón", "KR": "Corea del Sur", "LT": "Lituania", "LV": "Letonia", "MD": "Moldavia",
    "MX": "México", "MY": "Malasia", "NL": "Países Bajos", "PA": "Panamá", "PE": "Perú",
    "PL": "Polonia", "PT": "Portugal", "RO": "Rumania", "RU": "Rusia", "SC": "Seychelles",
    "SE": "Suecia", "SG": "Singapur", "TH": "Tailandia", "TR": "Turquía", "TW": "Taiwán",
    "UA": "Ucrania", "US": "Estados Unidos", "UY": "Uruguay", "VE": "Venezuela",
    "VN": "Vietnam", "ZA": "Sudáfrica",
})
FUENTES_CAIDAS = "No pudimos consultar los servicios de seguridad."
FUENTES_SOSPECHAN = "Varios servicios de seguridad la marcan como sospechosa."
UNA_SOLA_SOSPECHA = (
    "Un solo servicio de seguridad la marca como sospechosa. Hacen falta dos para contarlo."
)


@dataclass(frozen=True)
class Recorrido:
    """Lo que pasó al seguir el enlace hasta la web donde termina."""

    # Redirecciones seguidas; None si no se pudo llegar al destino.
    saltos: int | None
    # Web del enlace que pegó la persona, si el destino está en otra.
    desde: str = ""


@dataclass(frozen=True)
class FuenteConsultada:
    nombre: str
    estado: str
    # Lo que el servicio contó, una frase por dato. Vacío si no contó nada o ya venció.
    datos: tuple[str, ...] = ()


@dataclass(frozen=True)
class GrupoDeFuentes:
    titulo: str
    fuentes: tuple[FuenteConsultada, ...]


@dataclass(frozen=True)
class Explicacion:
    # Frase que resume el resultado, bajo el nivel.
    titular: str
    motivos: tuple[str, ...]
    acciones: tuple[str, ...]
    # Solo en Seguro.
    aclaracion: str | None
    # (nombre, explicación) de cada señal encontrada.
    senales: tuple[tuple[str, str], ...]
    # (término, valor, explicación) de lo que se revisó.
    detalle: tuple[tuple[str, str, str], ...]
    # (término, valor, explicación) de cómo se llegó al nivel.
    calculo: tuple[tuple[str, str, str], ...] = ()
    # Servicios de seguridad consultados. Un grupo sin servicios no aparece.
    fuentes: tuple[GrupoDeFuentes, ...] = ()


def explicar(
    veredicto: Veredicto,
    dominio: str,
    recorrido: Recorrido | None = None,
    fuentes: tuple[tuple[str, str], ...] = (),
    detalles: Mapping[str, dict] | None = None,
) -> Explicacion:
    """Arma la explicación de un veredicto.

    `dominio` es la web donde termina el enlace en el navegador. Con `recorrido`, el
    detalle técnico dice cuántas redirecciones hubo. `fuentes` trae el nombre y el
    estado de cada servicio de seguridad consultado, y `detalles`, lo que contó cada
    uno, por nombre. Los detalles duran un día: sin ellos queda solo el estado.
    """
    detalles = detalles or {}
    return Explicacion(
        titular=_titular(veredicto),
        motivos=_motivos(veredicto, dominio, fuentes, detalles),
        acciones=tuple(accion.format(dominio=dominio) for accion in ACCIONES[veredicto.nivel]),
        aclaracion=ACLARACION_SEGURO if veredicto.nivel == Nivel.SEGURO else None,
        senales=tuple(
            DETALLE_SENAL[codigo]
            for codigo in veredicto.senales.heuristicas
            if codigo in DETALLE_SENAL
        ),
        detalle=_redirecciones(recorrido) + _detalle(veredicto, fuentes),
        calculo=_calculo(veredicto),
        fuentes=_grupos_de_fuentes(fuentes, detalles),
    )


def _grupos_de_fuentes(
    fuentes: tuple[tuple[str, str], ...], detalles: Mapping[str, dict]
) -> tuple[GrupoDeFuentes, ...]:
    grupos = []
    for titulo, estados in GRUPOS_DE_FUENTES:
        del_grupo = tuple(
            _fuente_consultada(nombre, estado, detalles.get(nombre))
            for nombre, estado in fuentes
            if estado in estados
        )
        if del_grupo:
            grupos.append(GrupoDeFuentes(titulo, del_grupo))
    return tuple(grupos)


def _fuente_consultada(nombre: str, estado: str, datos) -> FuenteConsultada:
    # De un servicio que no respondió no hay nada que contar.
    frases = datos_de_fuente(datos, estado) if estado not in NO_RESPONDIO else ()
    texto = SIN_REPORTE if estado == "desconocido" and frases else ESTADO_FUENTE[estado]
    return FuenteConsultada(nombre, texto, frases)


def datos_de_fuente(datos, estado: str = "") -> tuple[str, ...]:
    """Las frases del detalle de un servicio. Un dato que falta o no sirve no deja frase."""
    if not isinstance(datos, Mapping):
        return ()
    frases = []

    def agregar(clave: str, **valores) -> None:
        frases.append(DATOS_FUENTE[clave].format(**valores))

    tipos = [
        TIPOS_DE_AMENAZA[tipo]
        for tipo in _lista(datos.get("tipos"))
        if tipo in TIPOS_DE_AMENAZA
    ]
    if tipos:
        agregar("tipos", lista=_enumerar(tipos))

    peligrosa = _cuenta(datos.get("motores_peligrosa"))
    total = _cuenta(datos.get("motores_total"))
    if peligrosa is not None and total and peligrosa <= total:
        clave = {0: "ningun_motor", 1: "un_motor"}.get(peligrosa, "motores")
        agregar(clave, cantidad=peligrosa, total=total)
    elif peligrosa:
        agregar("motores_sin_total", cantidad=peligrosa)
    if datos.get("sin_categoria") is True and peligrosa:
        agregar("sin_categoria")
    sospechosa = _cuenta(datos.get("motores_sospechosa"))
    if sospechosa:
        clave = "un_motor_sospechosa" if sospechosa == 1 else "motores_sospechosa"
        agregar(clave, cantidad=sospechosa)

    web_total = _cuenta(datos.get("web_total"))
    web_marcada = _cuenta(datos.get("web_peligrosa"))
    if datos.get("por_la_web") is True:
        agregar("por_la_web")
    if web_total and web_marcada is not None:
        web_marcada += _cuenta(datos.get("web_sospechosa")) or 0
        if web_marcada == 0:
            agregar("web_limpia", total=web_total)
        elif web_marcada <= web_total:
            agregar("web_marcada", cantidad=web_marcada, total=web_total)
    if datos.get("en_ranking") is True:
        agregar("en_ranking")

    puntaje = _cuenta(datos.get("puntaje"))
    if puntaje and puntaje <= 100:
        agregar("puntaje", cantidad=puntaje)
    for clave in ("marcas", "amenazas", "familias"):
        lista = _lista(datos.get(clave))
        if lista:
            agregar(clave, lista=", ".join(lista))
    archivos = _cuenta(datos.get("archivos"))
    if archivos:
        agregar("un_archivo" if archivos == 1 else "archivos", cantidad=archivos)
    if datos.get("dada_de_baja") is True:
        agregar("dada_de_baja")
    for clave in ("agregada", "primera_vez"):
        fecha = _fecha(datos.get(clave))
        if fecha:
            agregar(clave, fecha=fecha)

    votos_peligrosa = _cuenta(datos.get("votos_peligrosa"))
    votos_confiable = _cuenta(datos.get("votos_confiable"))
    if votos_peligrosa and votos_confiable:
        agregar("votos", peligrosa=votos_peligrosa, confiable=votos_confiable)
    elif votos_peligrosa:
        agregar("votos_peligrosa", peligrosa=votos_peligrosa)
    elif votos_confiable:
        agregar("votos_confiable", confiable=votos_confiable)

    reportes = _cuenta(datos.get("reportes"))
    dias = _cuenta(datos.get("periodo_dias"))
    if reportes and dias:
        agregar("un_reporte" if reportes == 1 else "reportes", cantidad=reportes, dias=dias)
        personas = _cuenta(datos.get("personas"))
        if personas and 1 < personas <= reportes:
            agregar("personas", cantidad=personas)
        confianza = _cuenta(datos.get("confianza"))
        if confianza is not None and confianza <= 100:
            agregar("confianza", cantidad=confianza)
        fecha = _fecha(datos.get("ultimo_reporte"))
        if fecha:
            agregar("ultimo_reporte", fecha=fecha)

    ip = datos.get("ip")
    if isinstance(ip, str) and ip:
        agregar("ip", ip=ip)
    pais = datos.get("pais")
    if isinstance(pais, str) and len(pais) == 2 and pais.isalpha():
        agregar("pais", pais=PAISES.get(pais.upper(), f"el país de código {pais.upper()}"))
    proveedor = datos.get("proveedor")
    if isinstance(proveedor, str) and proveedor.strip(". "):
        agregar("proveedor", proveedor=proveedor.strip(". "))
    if datos.get("red_tor") is True:
        agregar("red_tor")
    if datos.get("lista_blanca") is True:
        agregar("lista_blanca")
    for clave, dato in (
        ("edad_web", "edad_web_dias"),
        ("conocida", "conocida_dias"),
        ("certificado", "certificado_dias"),
    ):
        dias_de_edad = _cuenta(datos.get(dato))
        if dias_de_edad is not None:
            agregar(clave, edad=_edad_larga(dias_de_edad))

    fecha = _fecha(datos.get("analizado"))
    if fecha:
        # Un análisis sin hallazgos que no llegó a «sin detecciones» es de más de un día.
        antigua = estado == "desconocido" and peligrosa == 0 and total
        agregar("revision_antigua" if antigua else "analizado", fecha=fecha)
    if frases and datos.get("de_otra_pagina") is True:
        agregar("de_otra_pagina")
    return tuple(frases)


def _cuenta(valor) -> int | None:
    if isinstance(valor, bool) or not isinstance(valor, int) or valor < 0:
        return None
    return valor


def _lista(valor) -> list[str]:
    if not isinstance(valor, list | tuple):
        return []
    return [elemento for elemento in valor if isinstance(elemento, str) and elemento]


def _enumerar(textos: list[str]) -> str:
    if len(textos) == 1:
        return textos[0]
    return ", ".join(textos[:-1]) + " y " + textos[-1]


def _fecha(valor) -> str:
    """«12 de noviembre de 2026», desde una fecha ISO. Vacío si no se puede leer."""
    if not isinstance(valor, str):
        return ""
    try:
        fecha = datetime.fromisoformat(valor)
    except ValueError:
        return ""
    return f"{fecha.day} de {MESES[fecha.month - 1]} de {fecha.year}"


def _edad_larga(dias: int) -> str:
    """La edad en años cuando pasa de dos: «9 años» se entiende mejor que «3525 días»."""
    if dias >= 730:
        return f"{dias // 365} años"
    return _edad(dias)


def aviso_para_compartir(veredicto: Veredicto, dominio: str) -> str:
    """Texto que la persona manda a un familiar. Vacío en Seguro: no hay de qué avisar.

    El dominio va desactivado (`ejemplo[.]com`) para que el chat no lo vuelva un enlace,
    y nunca lleva la dirección del resultado.
    """
    if veredicto.nivel == Nivel.SEGURO:
        return ""
    accion = ACCIONES[veredicto.nivel][0].format(dominio=dominio)
    return AVISO.format(
        nivel=veredicto.nivel.texto,
        dominio=dominio.replace(".", "[.]").replace(":", "[:]"),
        accion=accion[:1].lower() + accion[1:],
    )


def hace_cuanto(segundos: float) -> str:
    """«hace 5 minutos», para decir cuándo se analizó un resultado que ya estaba guardado."""
    minutos = int(segundos // 60)
    if minutos < 1:
        return "hace menos de un minuto"
    if minutos < 60:
        return "hace 1 minuto" if minutos == 1 else f"hace {minutos} minutos"
    horas = minutos // 60
    if horas < 24:
        return "hace 1 hora" if horas == 1 else f"hace {horas} horas"
    dias = horas // 24
    return "hace 1 día" if dias == 1 else f"hace {dias} días"


def terminos_prohibidos(texto: str) -> list[str]:
    """Devuelve los términos prohibidos que aparecen en el texto."""
    return [
        termino
        for termino in TERMINOS_PROHIBIDOS
        if re.search(rf"(?<!\w){re.escape(termino)}(?!\w)", texto, re.IGNORECASE)
    ]


# Reglas que se explican con lo que dijeron los servicios de seguridad.
REGLAS_DE_FUENTES = frozenset({
    "dos_fuentes_confirman", "fuente_y_suplantacion", "una_fuente_confirma",
})


def _sin_hallazgos(veredicto: Veredicto) -> bool:
    """Ten cuidado solo por falta de información: no se encontró nada en contra."""
    return (
        veredicto.nivel == Nivel.TEN_CUIDADO
        and veredicto.puntaje == 0
        and not veredicto.senales.heuristicas
        and not {"web_nueva", "fuente_no_concluyente"} & set(veredicto.reglas)
    )


def _titular(veredicto: Veredicto) -> str:
    """La frase que resume el resultado. Solo afirma lo que la evidencia respalda."""
    if _sin_hallazgos(veredicto):
        return TITULAR_SIN_HALLAZGOS
    if veredicto.nivel == Nivel.PELIGROSO and veredicto.senales.fuentes_con_deteccion:
        return TITULAR_REPORTADA
    if veredicto.nivel == Nivel.TEN_CUIDADO and not veredicto.senales.heuristicas:
        if "fuente_no_concluyente" in veredicto.reglas:
            return TITULAR_EN_DUDA
        if "web_nueva" in veredicto.reglas:
            return TITULAR_WEB_NUEVA
    return TITULAR[veredicto.nivel]


def _motivos(
    veredicto: Veredicto,
    dominio: str,
    fuentes: tuple[tuple[str, str], ...] = (),
    detalles: Mapping[str, dict] | None = None,
) -> tuple[str, ...]:
    detalles = detalles or {}
    datos = {"dominio": dominio, "edad": _edad(veredicto.senales.edad_dias)}
    reemplazadas = {
        reemplazada
        for regla in veredicto.reglas
        for reemplazada in REEMPLAZA.get(regla, ())
    }
    # Las reglas del mismo nivel que el resultado van primero si subieron el nivel y, si el
    # puntaje ya llegaba a ese nivel, después de las señales.
    del_nivel = [
        regla
        for regla in veredicto.reglas
        if NIVEL_DE_REGLA[regla] == veredicto.nivel and regla not in reemplazadas
    ]
    subieron_el_nivel = veredicto.nivel_puntaje < veredicto.nivel
    textos_reglas = []
    for regla in del_nivel:
        textos_reglas += _motivos_de_regla(regla, veredicto, datos, fuentes, detalles)
    textos_senales = [
        MOTIVOS_SENAL[codigo].format(**datos)
        for codigo in veredicto.senales.heuristicas
        if codigo in MOTIVOS_SENAL
    ]
    if subieron_el_nivel:
        candidatos = textos_reglas + textos_senales
    else:
        candidatos = textos_senales + textos_reglas
    contar_edad = not EDAD_YA_CONTADA & set(del_nivel)
    candidatos += _lo_revisado(veredicto, datos, contar_edad, fuentes, detalles)
    motivos = _sin_repetir(candidatos)

    # Si faltan motivos, las reglas de nivel menor también explican el resultado.
    if len(motivos) < MINIMO_MOTIVOS:
        menores = []
        # En un resultado peligroso, que falte información no explica nada.
        omitidas = {"cobertura_baja"} if veredicto.nivel >= Nivel.PELIGROSO else set()
        for regla in veredicto.reglas:
            if regla not in del_nivel and regla not in reemplazadas | omitidas:
                menores += _motivos_de_regla(regla, veredicto, datos, fuentes, detalles)
        motivos = _sin_repetir(motivos + menores)
    if len(motivos) < MINIMO_MOTIVOS:
        motivos = _sin_repetir(motivos + list(RESPALDO[veredicto.nivel]))
    return tuple(motivos[:MAXIMO_MOTIVOS])


def _sin_repetir(textos: list[str]) -> list[str]:
    return list(dict.fromkeys(textos))


def _motivos_de_regla(
    regla: str,
    veredicto: Veredicto,
    datos: dict[str, str],
    fuentes: tuple[tuple[str, str], ...],
    detalles: Mapping[str, dict],
) -> list[str]:
    if regla == "cobertura_baja" and _sin_hallazgos(veredicto):
        return [MOTIVOS_REGLA["cobertura_baja_sin_hallazgos"]]
    if regla == "fuente_no_concluyente":
        # Las dos mitades de la contradicción van juntas: quién la marca y quién no.
        return (_motivos_sin_tipo(fuentes, detalles) or [MOTIVOS_REGLA[regla]]) + _los_demas(
            fuentes
        )
    reportan = [nombre for nombre, estado in fuentes if estado == "deteccion"]
    if regla not in REGLAS_DE_FUENTES or not reportan:
        return [MOTIVOS_REGLA[regla].format(**datos)]
    return _motivos_de_reportes(reportan, detalles, regla == "fuente_y_suplantacion")


def _motivos_de_reportes(
    reportan: list[str], detalles: Mapping[str, dict], con_suplantacion: bool
) -> list[str]:
    """Quién la reporta, como qué, cuántos antivirus, a quién imita y qué significa."""
    contado = [
        detalles[nombre] for nombre in reportan if isinstance(detalles.get(nombre), Mapping)
    ]
    tipos = _sin_repetir([
        tipo
        for datos in contado
        for tipo in _lista(datos.get("tipos"))
        if tipo in TIPOS_DE_AMENAZA
    ])
    tipo = _enumerar([TIPOS_DE_AMENAZA[t] for t in tipos]) if tipos else TIPO_SIN_DETALLE
    frase = REPORTA_UNO if len(reportan) == 1 else REPORTAN_VARIOS
    motivos = [frase.format(nombres=_enumerar(reportan), tipo=tipo)]
    for datos in contado:
        peligrosa = _cuenta(datos.get("motores_peligrosa"))
        total = _cuenta(datos.get("motores_total"))
        if peligrosa and total and 1 < peligrosa <= total:
            motivos.append(ANTIVIRUS_LA_MARCAN.format(cantidad=peligrosa, total=total))
            break
    marcas = _sin_repetir([marca for datos in contado for marca in _lista(datos.get("marcas"))])
    if marcas:
        motivos.append(SE_HACE_PASAR.format(marcas=_enumerar(marcas)))
    elif con_suplantacion:
        motivos.append(ADEMAS_IMITA)
    motivos.append(SIGNIFICADO.get(tipos[0] if tipos else "", SIGNIFICADO[""]))
    return motivos


def _motivos_sin_tipo(
    fuentes: tuple[tuple[str, str], ...], detalles: Mapping[str, dict]
) -> list[str]:
    """Cuántos antivirus la marcan sin decir el tipo, con el nombre del servicio."""
    motivos = []
    for nombre, estado in fuentes:
        contado = detalles.get(nombre)
        if estado != "no_concluyente" or not isinstance(contado, Mapping):
            continue
        peligrosa = _cuenta(contado.get("motores_peligrosa"))
        total = _cuenta(contado.get("motores_total"))
        if peligrosa and total and peligrosa <= total:
            motivos.append(MOTORES_SIN_TIPO.format(cantidad=peligrosa, total=total, nombre=nombre))
    return motivos


def _los_demas(fuentes: tuple[tuple[str, str], ...]) -> list[str]:
    """Lo que dicen los servicios que respondieron y no la marcan."""
    if any(estado == "sospecha" for _, estado in fuentes):
        return []
    otros = sum(
        1 for _, estado in fuentes if estado not in NO_RESPONDIO and estado != "no_concluyente"
    )
    if otros < 1:
        return []
    return [EL_OTRO_NO if otros == 1 else LOS_OTROS_NO.format(cantidad=otros)]


def _lo_revisado(
    veredicto: Veredicto,
    datos: dict[str, str],
    contar_edad: bool,
    consultadas: tuple[tuple[str, str], ...] = (),
    detalles: Mapping[str, dict] | None = None,
) -> list[str]:
    """Motivos con lo que se comprobó de cada categoría.

    En Peligroso y Peligro alto solo entra lo que suma a la alerta. Lo que no se encontró
    («no imita marcas», «la dirección es normal») y lo que no se pudo revisar quedan
    para Seguro y Ten cuidado, donde explican el resultado.
    """
    detalles = detalles or {}
    valores = veredicto.valores
    peligro = veredicto.nivel >= Nivel.PELIGROSO
    motivos = []

    if FUENTES in valores:
        motivos += _motivos_de_fuentes(veredicto, consultadas, detalles, peligro)

    edad_dias = veredicto.senales.edad_dias
    if EDAD in valores and contar_edad and edad_dias is not None:
        if edad_dias < DIAS_WEB_NUEVA:
            motivos.append(MOTIVOS_REGLA["web_nueva"].format(**datos))
        elif edad_dias <= 365:
            motivos.append(WEB_DE_MESES.format(**datos))
        elif not peligro:
            motivos.append(WEB_ANTIGUA.format(edad=_antiguedad(edad_dias)))

    if MARCA in valores:
        marca = valores[MARCA]
        if marca == 0 and not peligro:
            motivos.append(NO_IMITA_MARCAS)
        elif marca and not SENALES_DE_MARCA & set(veredicto.senales.heuristicas):
            motivos.append(IMITA_SIN_SENAL)

    if valores.get(HEURISTICAS) == 0 and not peligro:
        motivos.append(DIRECCION_NORMAL)
    return motivos


def _motivos_de_fuentes(
    veredicto: Veredicto,
    consultadas: tuple[tuple[str, str], ...],
    detalles: Mapping[str, dict],
    peligro: bool,
) -> list[str]:
    fuentes = veredicto.valores[FUENTES]
    respondieron = [nombre for nombre, estado in consultadas if estado not in NO_RESPONDIO]
    en_duda = [nombre for nombre, estado in consultadas if estado == "no_concluyente"]
    if en_duda and not veredicto.senales.fuentes_con_deteccion:
        # Ya lo cuenta la regla «fuente_no_concluyente», con lo que dicen los demás.
        return []
    if fuentes is not None and fuentes > 0:
        sospecha = veredicto.senales.fuentes_con_deteccion == 0
        return [FUENTES_SOSPECHAN] if sospecha else []
    if any(estado == "sospecha" for _, estado in consultadas):
        return [UNA_SOLA_SOSPECHA]
    if peligro:
        return []
    # Sin cupo no es una falla: con esperar unos minutos el resultado mejora. Solo se
    # dice cuando ese servicio habría podido cambiar el resultado.
    sin_cupo = [nombre for nombre, estado in consultadas if estado == "sin_cupo"]
    aviso = []
    if sin_cupo and fuentes is None:
        frase = SIN_CUPO if len(sin_cupo) == 1 else SIN_CUPO_VARIOS
        aviso = [frase.format(nombres=_enumerar(sin_cupo))]
    if not respondieron:
        # Sin servicios configurados no hay nada que contar; si todos fallaron, se dice.
        if aviso:
            return aviso
        return [FUENTES_CAIDAS] if consultadas else (
            [LISTAS_NO_LA_REPORTAN] if fuentes == 0 else []
        )
    nadie = (
        UNO_NO_LA_REPORTA
        if len(respondieron) == 1
        else NADIE_LA_REPORTA.format(cantidad=len(respondieron))
    )
    if fuentes is None:
        return [*aviso, nadie] if aviso else [nadie, NADIE_LA_REVISO]
    motivos = [nadie]
    for nombre in respondieron:
        contado = detalles.get(nombre)
        if not isinstance(contado, Mapping):
            continue
        total = _cuenta(contado.get("web_total")) or _cuenta(contado.get("motores_total"))
        marcada = (_cuenta(contado.get("motores_peligrosa")) or 0) + (
            _cuenta(contado.get("web_peligrosa")) or 0
        )
        if total and not marcada:
            motivos.append(ANTIVIRUS_LIMPIA.format(nombre=nombre, total=total))
            break
    return motivos


def _redirecciones(recorrido: Recorrido | None) -> tuple[tuple[str, str, str], ...]:
    if recorrido is None:
        return ()
    if recorrido.saltos is None:
        valor = SIN_DESTINO
    elif recorrido.saltos == 0:
        valor = "Ninguna"
    elif recorrido.desde:
        valor = f"{recorrido.saltos}, desde {recorrido.desde}"
    else:
        valor = str(recorrido.saltos)
    return (("Redirecciones", valor, NOTA_REDIRECCIONES),)


def _detalle(
    veredicto: Veredicto, consultadas: tuple[tuple[str, str], ...] = ()
) -> tuple[tuple[str, str, str], ...]:
    """Lo que se revisó y qué salió, una fila por cosa."""
    valores = veredicto.valores
    senales = veredicto.senales
    filas = []

    if FUENTES in valores:
        respondieron = sum(1 for _, estado in consultadas if estado not in NO_RESPONDIO)
        reportan = sum(1 for _, estado in consultadas if estado == "deteccion")
        if reportan:
            valor = f"La reportan {reportan} de {respondieron}"
        elif senales.fuentes_con_deteccion:
            valor = f"La reportan {senales.fuentes_con_deteccion}"
        elif respondieron:
            valor = f"Ninguno de {respondieron} la reporta"
        elif consultadas:
            valor = "No respondieron"
        else:
            valor = "No la reportan" if valores[FUENTES] is not None else "Sin consultar"
        filas.append((
            "Servicios de seguridad",
            valor,
            "Reúnen páginas falsas y webs con virus que otras personas ya reportaron.",
        ))

    if EDAD in valores:
        filas.append((
            "Edad de la web",
            "No se pudo saber" if senales.edad_dias is None else _antiguedad(senales.edad_dias),
            "Muchas estafas usan webs creadas hace pocos días.",
        ))

    cantidad = len([codigo for codigo in senales.heuristicas if codigo in DETALLE_SENAL])
    filas.append((
        "Trucos en la dirección",
        {0: "Ninguno", 1: "1 encontrado"}.get(cantidad, f"{cantidad} encontrados"),
        "Formas de escribir una dirección para que parezca la de otra web.",
    ))

    # Sin marcas registradas no hubo comparación: la fila no aparece.
    if valores.get(MARCA) is not None:
        filas.append((
            "Imita a una marca",
            "Sí" if valores[MARCA] else "No",
            "Comparamos el nombre con las webs oficiales de bancos y tiendas.",
        ))
    return tuple(filas)


def _calculo(veredicto: Veredicto) -> tuple[tuple[str, str, str], ...]:
    """Cómo se llegó al nivel: puntaje, información disponible y versión de reglas."""
    return (
        (
            "Puntaje de riesgo",
            f"{veredicto.puntaje} de 100",
            "Hasta 20 es Seguro, hasta 50 Ten cuidado, hasta 80 Peligroso y desde 81 Peligro "
            "alto. Una prueba clara de estafa sube el nivel aunque el puntaje sea menor.",
        ),
        (
            "Información disponible",
            f"{round(veredicto.cobertura)} %",
            "Cuánto de lo que usamos para decidir pudimos revisar. Con menos de 70 % nunca "
            "decimos Seguro.",
        ),
        (
            "Versión de reglas",
            veredicto.version,
            "Con la misma versión y las mismas señales, el resultado es siempre el mismo.",
        ),
    )


def _antiguedad(dias: int) -> str:
    """La edad de una web como la diría una persona: «3 días», «más de un año», «26 años»."""
    if dias >= 730:
        return f"{dias // 365} años"
    if dias > 365:
        return "más de un año"
    return _edad(dias)


def _edad(edad_dias: int | None) -> str:
    if edad_dias is None:
        return ""
    if edad_dias < 1:
        return "menos de un día"
    if edad_dias == 1:
        return "1 día"
    return f"{edad_dias} días"
