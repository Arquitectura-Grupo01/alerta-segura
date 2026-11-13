"""Modalidades de estafa frecuentes en el Perú: textos de su página y cómo reconocerlas.

Los textos viven aquí, junto a los del motor de explicación, para medir su legibilidad
con el mismo test y cambiarlos en un solo lugar. No llevan capturas ni datos reales.

Desde un enlace solo se reconoce la modalidad por las palabras de su dirección: es una
pista, no una prueba, y el resultado lo dice así. La de una web del Estado o de un
dominio oficial del catálogo nunca se marca: «sunat» en sunat.gob.pe es lo esperado.
Solo se usan palabras poco comunes fuera de estas estafas: «trabajo», «tarea» o
«regalo» aparecen en demasiadas webs normales.
"""

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class Modalidad:
    clave: str
    titulo: str
    como_funciona: tuple[str, ...]
    como_reconocerla: tuple[str, ...]
    que_hacer: tuple[str, ...]
    # La acción que se suma al resultado cuando el enlace parece de esta modalidad.
    accion: str
    # Comienzos de palabra que la delatan en una dirección. Vacío si no llega por enlace.
    palabras: tuple[str, ...] = ()


MODALIDADES = (
    Modalidad(
        clave="yapeo-por-error",
        titulo="«Te yapeé por error» y pagos falsos por Yape o Plin",
        como_funciona=(
            "Alguien te escribe que te envió dinero por error y te pide que se lo devuelvas.",
            "A veces manda la captura de un pago que nunca llegó.",
            "Otras veces un comprador te muestra una constancia falsa para llevarse lo que "
            "vendes.",
        ),
        como_reconocerla=(
            "Te apura para que devuelvas el dinero o entregues el producto.",
            "La prueba es una captura que llega por chat.",
            "En tu app no aparece el pago.",
        ),
        que_hacer=(
            "Revisa en tu propia app de Yape o Plin si el dinero llegó. Una captura no "
            "prueba nada.",
            "No entregues nada hasta ver el pago en tu app.",
            "Si llegó dinero que no esperabas, no lo devuelvas por tu cuenta. Escribe a Yape "
            "o a tu banco desde su app.",
        ),
        accion="Si te dicen que te yapearon o que confirmes un pago, revisa en tu propia app "
        "si el dinero llegó.",
        palabras=("yape", "plin"),
    ),
    Modalidad(
        clave="falso-asesor",
        titulo="Falso asesor del banco que te llama",
        como_funciona=(
            "Te llaman y dicen que son de tu banco.",
            "Te cuentan que hay un cargo raro o un problema con tu cuenta.",
            "Para ayudarte te piden un código que te llega por SMS, tu clave o que instales "
            "una app.",
        ),
        como_reconocerla=(
            "Tu banco nunca te pide claves ni códigos por teléfono.",
            "Te apuran y no te dejan colgar.",
            "El número que te llama puede parecerse al del banco.",
        ),
        que_hacer=(
            "Cuelga. Llama tú al número que está en tu tarjeta o en la app del banco.",
            "No instales ninguna app que te pidan por teléfono.",
            "Si ya diste un código o una clave, llama a tu banco ahora.",
        ),
        accion="Si te llamaron y dijeron ser de tu banco, cuelga y llama tú al número de tu "
        "tarjeta.",
    ),
    Modalidad(
        clave="bloqueo-de-cuenta",
        titulo="Mensaje de cuenta o tarjeta bloqueada",
        como_funciona=(
            "Te llega un SMS o un correo que dice que tu cuenta o tu tarjeta está bloqueada.",
            "Para desbloquearla te pide entrar a un enlace.",
            "El enlace abre una copia de la web del banco que guarda todo lo que escribes.",
        ),
        como_reconocerla=(
            "El mensaje te asusta y te apura.",
            "El enlace no es la web oficial del banco.",
            "La página te pide tu clave, un código o los datos de tu tarjeta.",
        ),
        que_hacer=(
            "No abras el enlace. Entra tú mismo a la app de tu banco.",
            "Si dudas, llama al número que está en tu tarjeta.",
            "Si ya escribiste tus datos, llama al banco y pide que bloqueen la tarjeta.",
        ),
        accion="Tu banco no bloquea tu cuenta por un mensaje con enlace. Para salir de dudas, "
        "entra tú mismo a su app.",
        palabras=("bloque", "desbloque", "suspend", "reactiv", "verific"),
    ),
    Modalidad(
        clave="codigo-de-whatsapp",
        titulo="Robo de tu WhatsApp con un código",
        como_funciona=(
            "Alguien te escribe, a veces desde el número de un amigo, y dice que te mandó un "
            "código por error.",
            "Te pide que se lo reenvíes.",
            "Con ese código abre tu WhatsApp en otro celular y pide dinero a tus contactos.",
        ),
        como_reconocerla=(
            "Te piden un código de seis números que llegó por SMS.",
            "Insisten y dicen que es urgente.",
            "El mensaje viene de un contacto que escribe distinto a lo normal.",
        ),
        que_hacer=(
            "Nunca compartas ese código, ni con un amigo.",
            "Activa la verificación en dos pasos en los ajustes de WhatsApp.",
            "Si ya lo diste, avisa a tus contactos que no te depositen nada.",
        ),
        accion="Nunca compartas el código de seis números que te llega por SMS, ni con un "
        "amigo.",
        palabras=("whatsapp",),
    ),
    Modalidad(
        clave="premio-o-bono-falso",
        titulo="Premio, bono o devolución de SUNAT falsos",
        como_funciona=(
            "Te dicen que ganaste un premio, que te toca un bono del Estado o que SUNAT "
            "tiene dinero para ti.",
            "Para cobrar te piden tus datos, tu clave o un pago por el trámite.",
        ),
        como_reconocerla=(
            "No participaste en ningún sorteo.",
            "Te piden pagar para recibir dinero.",
            "Las webs del Estado terminan en gob.pe. El enlace que te llegó no.",
        ),
        que_hacer=(
            "No pagues nada para cobrar un premio o un bono.",
            "Busca los bonos solo en gob.pe, escribiendo tú la dirección.",
            "Para una devolución de SUNAT, entra tú mismo a su web oficial.",
        ),
        accion="Nadie te pide pagar para recibir un premio, un bono o una devolución.",
        palabras=("premio", "sorteo", "ganador", "ganaste", "bono", "devolucion", "sunat"),
    ),
    Modalidad(
        clave="prestamo-o-trabajo-falso",
        titulo="Préstamos rápidos y trabajos por tareas",
        como_funciona=(
            "Te ofrecen un préstamo sin requisitos o te pagan por dar me gusta y hacer "
            "tareas.",
            "Al inicio te pagan poco para que confíes.",
            "Después te piden depositar para liberar tus ganancias o pagar antes de recibir "
            "el préstamo.",
        ),
        como_reconocerla=(
            "Te piden pagar por adelantado.",
            "Ganas dinero fácil por algo muy simple.",
            "La app te pide ver tus contactos y tus fotos.",
        ),
        que_hacer=(
            "No pagues nada por adelantado.",
            "Pide préstamos solo a bancos, cajas o financieras que conoces, desde su app.",
            "Si una app de préstamos amenaza a tus contactos, denúncialo en la policía.",
        ),
        accion="No pagues nada por adelantado para recibir un préstamo o un trabajo.",
        palabras=("prestamo",),
    ),
)

POR_CLAVE = {modalidad.clave: modalidad for modalidad in MODALIDADES}
# Si una dirección coincide con varias, gana la más específica. «Verifica» aparece en
# casi toda página falsa, así que la cuenta bloqueada va al final.
PRIORIDAD = (
    "codigo-de-whatsapp",
    "yapeo-por-error",
    "premio-o-bono-falso",
    "prestamo-o-trabajo-falso",
    "bloqueo-de-cuenta",
)

# Webs del Estado peruano: ahí las palabras de una modalidad son lo esperado.
SUFIJO_ESTADO = ".gob.pe"

_SEPARADOR = re.compile(r"[^a-z0-9]+")


def detectar(direcciones: Iterable[str], dominio: str, oficiales: Iterable[str] = ()) -> str:
    """Clave de la modalidad que sugieren las palabras de las direcciones, o vacío.

    `direcciones` son el nombre de la web y la ruta, sin parámetros. Si coinciden varias,
    gana la primera de PRIORIDAD.
    """
    dominio = dominio.lower().rstrip(".")
    if dominio.endswith(SUFIJO_ESTADO) or dominio == SUFIJO_ESTADO[1:]:
        return ""
    if any(dominio == oficial or dominio.endswith("." + oficial) for oficial in oficiales):
        return ""
    palabras = {palabra for texto in direcciones for palabra in _palabras(texto)}
    for clave in PRIORIDAD:
        inicios = POR_CLAVE[clave].palabras
        if any(palabra.startswith(inicio) for palabra in palabras for inicio in inicios):
            return clave
    return ""


def _palabras(texto: str) -> list[str]:
    sin_tildes = unicodedata.normalize("NFKD", texto.lower())
    sin_tildes = "".join(letra for letra in sin_tildes if not unicodedata.combining(letra))
    return [palabra for palabra in _SEPARADOR.split(sin_tildes) if palabra]
