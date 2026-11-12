"""Motor de explicación: traduce un veredicto a motivos y acciones en español cotidiano.

Todos los textos que ve la persona están en este módulo, para poder cambiarlos
después de la prueba de comprensión sin buscarlos por el código. Los motivos
empiezan por las reglas que decidieron el nivel, siguen con las señales
encontradas y terminan con lo que se revisó o no se pudo revisar.

Los textos se muestran con el autoescapado de Django: el dominio que se inserta
en un motivo nunca se marca como seguro.
"""

import re
from dataclasses import dataclass
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
    "web_nueva": "La web se creó hace {edad}.",
    "cobertura_baja": "Todavía no tenemos datos suficientes para decir que es segura.",
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

ACCIONES = MappingProxyType({
    Nivel.SEGURO: (
        "Antes de escribir tus datos, fíjate que sea la web que esperabas.",
        "Si te piden claves, códigos o pagos con prisa, detente y confirma por el canal oficial.",
    ),
    Nivel.TEN_CUIDADO: (
        "No escribas claves, códigos ni los datos de tu tarjeta en esa web.",
        "Si dice ser de tu banco o de una tienda, entra tú mismo desde su app o escribiendo su "
        "dirección oficial.",
    ),
    Nivel.PELIGROSO: (
        "No abras el enlace ni respondas el mensaje.",
        "No entregues datos ni hagas pagos que te pidan desde ahí.",
    ),
    Nivel.PELIGRO_ALTO: (
        "No abras el enlace, no respondas y borra el mensaje.",
        "Si ya diste tus claves o pagaste, llama a tu banco con el número de tu tarjeta o de su "
        "app.",
    ),
})

ACLARACION_SEGURO = (
    "Es una orientación, no una garantía. No encontramos señales de riesgo, pero una web puede "
    "cambiar."
)

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
    "sin_detecciones": "La revisó hace menos de un día y no encontró nada",
    "desconocido": "No tiene datos de esta web",
    "fallo": "No respondió",
})
NOTA_FUENTE = "Servicio de seguridad que consultamos. Si no responde, no cuenta como web limpia."
FUENTES_SIN_DATOS = "Los servicios de seguridad que consultamos no tienen datos de esta web."
FUENTES_CAIDAS = "No pudimos consultar los servicios de seguridad."


@dataclass(frozen=True)
class Recorrido:
    """Lo que pasó al seguir el enlace hasta la web donde termina."""

    # Redirecciones seguidas; None si no se pudo llegar al destino.
    saltos: int | None
    # Web del enlace que pegó la persona, si el destino está en otra.
    desde: str = ""


@dataclass(frozen=True)
class Explicacion:
    motivos: tuple[str, ...]
    acciones: tuple[str, ...]
    # Solo en Seguro.
    aclaracion: str | None
    # (nombre, explicación) de cada señal encontrada.
    senales: tuple[tuple[str, str], ...]
    # (término, valor, explicación) del detalle técnico.
    detalle: tuple[tuple[str, str, str], ...]


def explicar(
    veredicto: Veredicto,
    dominio: str,
    recorrido: Recorrido | None = None,
    fuentes: tuple[tuple[str, str], ...] = (),
) -> Explicacion:
    """Arma la explicación de un veredicto.

    `dominio` es la web donde termina el enlace en el navegador. Con `recorrido`, el
    detalle técnico dice cuántas redirecciones hubo. `fuentes` trae el nombre y el
    estado de cada servicio de seguridad consultado.
    """
    return Explicacion(
        motivos=_motivos(veredicto, dominio, fuentes),
        acciones=ACCIONES[veredicto.nivel],
        aclaracion=ACLARACION_SEGURO if veredicto.nivel == Nivel.SEGURO else None,
        senales=tuple(
            DETALLE_SENAL[codigo]
            for codigo in veredicto.senales.heuristicas
            if codigo in DETALLE_SENAL
        ),
        detalle=_redirecciones(recorrido) + _detalle(veredicto) + tuple(
            (nombre, ESTADO_FUENTE[estado], NOTA_FUENTE) for nombre, estado in fuentes
        ),
    )


def aviso_para_compartir(veredicto: Veredicto, dominio: str) -> str:
    """Texto que la persona manda a un familiar. Vacío en Seguro: no hay de qué avisar.

    El dominio va desactivado (`ejemplo[.]com`) para que el chat no lo vuelva un enlace,
    y nunca lleva la dirección del resultado.
    """
    if veredicto.nivel == Nivel.SEGURO:
        return ""
    accion = ACCIONES[veredicto.nivel][0]
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


def _motivos(
    veredicto: Veredicto, dominio: str, fuentes: tuple[tuple[str, str], ...] = ()
) -> tuple[str, ...]:
    datos = {"dominio": dominio, "edad": _edad(veredicto.senales.edad_dias)}
    reemplazadas = {
        reemplazada
        for regla in veredicto.reglas
        for reemplazada in REEMPLAZA.get(regla, ())
    }
    # Las reglas del mismo nivel que el resultado van primero si subieron el nivel y, si el
    # puntaje ya llegaba a ese nivel, después de las señales. Las de nivel menor no decidieron
    # nada: su dato sale en el estado de la categoría.
    del_nivel = [
        regla
        for regla in veredicto.reglas
        if NIVEL_DE_REGLA[regla] == veredicto.nivel and regla not in reemplazadas
    ]
    subieron_el_nivel = veredicto.nivel_puntaje < veredicto.nivel
    textos_reglas = [MOTIVOS_REGLA[regla].format(**datos) for regla in del_nivel]
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
    candidatos += _estado_de_categorias(veredicto, datos, contar_edad, fuentes)
    motivos = _sin_repetir(candidatos)

    # Si faltan motivos, las reglas de nivel menor también explican el resultado.
    if len(motivos) < MINIMO_MOTIVOS:
        menores = [
            MOTIVOS_REGLA[regla].format(**datos)
            for regla in veredicto.reglas
            if regla not in del_nivel and regla not in reemplazadas
        ]
        motivos = _sin_repetir(motivos + menores)
    return tuple(motivos[:MAXIMO_MOTIVOS])


def _sin_repetir(textos: list[str]) -> list[str]:
    return list(dict.fromkeys(textos))


def _estado_de_categorias(
    veredicto: Veredicto,
    datos: dict[str, str],
    contar_edad: bool,
    consultadas: tuple[tuple[str, str], ...] = (),
) -> list[str]:
    """Un motivo por categoría aplicable, para decir también lo que no se pudo revisar."""
    valores = veredicto.valores
    estados = []

    if FUENTES in valores:
        fuentes = valores[FUENTES]
        if fuentes is None and not consultadas:
            estados.append("Todavía no la buscamos en listas de seguridad.")
        elif fuentes is None:
            caidas = all(estado == "fallo" for _, estado in consultadas)
            estados.append(FUENTES_CAIDAS if caidas else FUENTES_SIN_DATOS)
        elif fuentes == 0:
            estados.append("Las listas de seguridad que consultamos no la tienen reportada.")
        elif veredicto.senales.fuentes_con_deteccion == 0:
            estados.append("Un servicio de seguridad la marca como sospechosa.")

    if EDAD in valores and contar_edad:
        edad_dias = veredicto.senales.edad_dias
        if edad_dias is None:
            estados.append("No sabemos cuándo se creó la web.")
        elif edad_dias <= 365:
            estados.append(MOTIVOS_REGLA["web_nueva"].format(**datos))
        else:
            estados.append("La web existe desde hace más de un año.")

    if MARCA in valores:
        marca = valores[MARCA]
        if marca is None:
            estados.append("Todavía no la comparamos con las webs oficiales de bancos y tiendas.")
        elif marca == 0:
            estados.append("No imita el nombre de las marcas que tenemos registradas.")
        elif not SENALES_DE_MARCA & set(veredicto.senales.heuristicas):
            estados.append("Usa el nombre de una marca conocida, pero no es su web oficial.")

    if HEURISTICAS in valores and valores[HEURISTICAS] == 0:
        estados.append("No encontramos trucos en la dirección.")

    return estados


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


def _detalle(veredicto: Veredicto) -> tuple[tuple[str, str, str], ...]:
    valores = veredicto.valores
    senales = veredicto.senales
    filas = []

    if FUENTES in valores:
        if valores[FUENTES] is None:
            valor = "Sin datos todavía"
        elif senales.fuentes_con_deteccion:
            valor = f"La reportan {senales.fuentes_con_deteccion}"
        else:
            valor = "No la reportan"
        filas.append((
            "Listas de seguridad",
            valor,
            "Listas que reúnen páginas falsas y webs con virus.",
        ))

    if EDAD in valores:
        filas.append((
            "Edad de la web",
            "No disponible" if senales.edad_dias is None else _edad(senales.edad_dias),
            "Muchas estafas usan webs creadas hace pocos días.",
        ))

    if MARCA in valores:
        marca = valores[MARCA]
        filas.append((
            "Parecido con una marca",
            "Sin catálogo todavía" if marca is None else ("Sí" if marca else "No"),
            "Comparamos el nombre con las webs oficiales de bancos y tiendas.",
        ))

    filas.append((
        "Información disponible",
        f"{round(veredicto.cobertura)} %",
        "Cuánto de lo que usamos para decidir pudimos revisar. Con menos de 70 % nunca decimos "
        "Seguro.",
    ))
    filas.append((
        "Puntaje",
        f"{veredicto.puntaje} de 100",
        "Hasta 20 es Seguro, hasta 50 Ten cuidado, hasta 80 Peligroso y desde 81 Peligro alto.",
    ))
    filas.append((
        "Versión de reglas",
        veredicto.version,
        "Con la misma versión y las mismas señales, el resultado es siempre el mismo.",
    ))
    return tuple(filas)


def _edad(edad_dias: int | None) -> str:
    if edad_dias is None:
        return ""
    if edad_dias < 1:
        return "menos de un día"
    if edad_dias == 1:
        return "1 día"
    return f"{edad_dias} días"
