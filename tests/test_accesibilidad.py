"""Accesibilidad (tarea 30): colores medidos, áreas táctiles y estructura de cada página.

Estas pruebas no reemplazan la revisión con axe-core del CI (ver scripts/accesibilidad/):
miden lo que axe no puede medir sin un navegador real, que es la paleta propia del sitio
en sus dos modos, y verifican la estructura que sí se puede leer del HTML renderizado.
Cada color nuevo en static/css/sitio.css debe pasar por aquí antes de usarse.
"""

import os
import re
from dataclasses import asdict
from html.parser import HTMLParser
from pathlib import Path

import pytest
from django.urls import reverse

from analisis.models import Analisis
from motor.riesgo import VERSION_INICIAL, Nivel, Senales, calcular

CSS = Path(__file__).resolve().parent.parent / "static" / "css" / "sitio.css"
JS = Path(__file__).resolve().parent.parent / "static" / "js" / "accesibilidad.js"

COLORES_DE_TEXTO = (
    "texto", "cuerpo", "secundario", "titulo-tenue", "placeholder", "error",
    "seguro", "cuidado", "peligroso", "alto",
)
FONDOS = ("noche", "superficie")


# --- Contraste ---------------------------------------------------------------------------


def _bloque(patron):
    css = CSS.read_text(encoding="utf-8")
    inicio = css.index(patron)
    return css[css.index("{", inicio):css.index("}", inicio)]


def _variables(bloque):
    return dict(re.findall(r"--([a-z-]+):\s*(#[0-9a-fA-F]{6})\s*;", bloque))


def _luminancia(color):
    canales = [int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    lineal = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in canales]
    return 0.2126 * lineal[0] + 0.7152 * lineal[1] + 0.0722 * lineal[2]


def contraste(color_a, color_b):
    mas_claro, mas_oscuro = sorted((_luminancia(color_a), _luminancia(color_b)), reverse=True)
    return (mas_claro + 0.05) / (mas_oscuro + 0.05)


NORMAL = _variables(_bloque(":root {"))
ALTO = {**NORMAL, **_variables(_bloque('html[data-contraste="alto"] {'))}


def test_la_formula_de_contraste_da_los_valores_conocidos():
    assert contraste("#000000", "#ffffff") == pytest.approx(21.0)
    assert contraste("#777777", "#ffffff") == pytest.approx(4.48, abs=0.01)


@pytest.mark.parametrize("fondo", FONDOS)
@pytest.mark.parametrize("color", COLORES_DE_TEXTO)
def test_todo_texto_del_modo_normal_pasa_4_5_a_1(color, fondo):
    assert contraste(NORMAL[color], NORMAL[fondo]) >= 4.5, (color, fondo)


@pytest.mark.parametrize("fondo", FONDOS)
@pytest.mark.parametrize("color", COLORES_DE_TEXTO)
def test_el_alto_contraste_pasa_7_a_1(color, fondo):
    assert contraste(ALTO[color], ALTO[fondo]) >= 7, (color, fondo)


@pytest.mark.parametrize("modo", [NORMAL, ALTO], ids=["normal", "alto"])
def test_el_anillo_de_foco_y_el_boton_activo_se_ven(modo):
    # El foco usa var(--texto) sobre el fondo, y la opción activa invierte los dos colores.
    assert contraste(modo["texto"], modo["noche"]) >= 4.5


def test_el_alto_contraste_redefine_todos_los_colores_de_texto():
    redefinidos = _variables(_bloque('html[data-contraste="alto"] {'))
    assert set(COLORES_DE_TEXTO) <= set(redefinidos)


# --- Áreas táctiles de 48 px ------------------------------------------------------------

CONTROLES = (
    ".marca", ".nav a", ".campo input", ".boton-pegar", ".boton-analizar", ".detalle summary",
    ".situaciones a", ".pie-enlaces a", ".boton-avisar", ".boton-reporte", ".contacto-campo",
    ".guia-indice a", ".guia-ruta a", ".ajustes-abrir", ".ajustes-opcion", ".saltar",
)


def _alto_minimo(selector):
    css = re.sub(r"/\*.*?\*/", "", CSS.read_text(encoding="utf-8"), flags=re.S)
    altos = []
    for seleccion, cuerpo in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
        if selector in [s.strip() for s in seleccion.split(",")]:
            altos += [
                int(valor)
                for propiedad, valor in re.findall(r"(min-height|height)\s*:\s*(\d+)px", cuerpo)
                if propiedad
            ]
    return max(altos, default=0)


@pytest.mark.parametrize("selector", CONTROLES)
def test_cada_control_mide_al_menos_48_px_de_alto(selector):
    assert _alto_minimo(selector) >= 48, selector


def test_el_texto_escala_con_rem_y_hay_tres_tamanos():
    css = CSS.read_text(encoding="utf-8")
    assert 'html[data-texto="grande"] { font-size: 112.5%; }' in css
    assert 'html[data-texto="muy-grande"] { font-size: 125%; }' in css
    # El cuerpo parte de rem: si fuera px, el cambio en <html> no lo escalaría.
    assert re.search(r"body \{[^}]*font-size: 1\.0625rem", css)


# --- Estructura de cada página ----------------------------------------------------------


class Lector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.etiquetas = []
        self.texto_de = {}
        self._abiertas = []

    def handle_starttag(self, etiqueta, atributos):
        elemento = {"tag": etiqueta, "attrs": dict(atributos), "texto": ""}
        self.etiquetas.append(elemento)
        if etiqueta not in {"meta", "link", "input", "br", "img", "use", "path", "circle", "rect"}:
            self._abiertas.append(elemento)

    def handle_endtag(self, etiqueta):
        for i in range(len(self._abiertas) - 1, -1, -1):
            if self._abiertas[i]["tag"] == etiqueta:
                del self._abiertas[i:]
                return

    def handle_data(self, datos):
        for elemento in self._abiertas:
            elemento["texto"] += datos


def leer(html):
    lector = Lector()
    lector.feed(html)
    return lector.etiquetas


def de(etiquetas, tag):
    return [e for e in etiquetas if e["tag"] == tag]


def _guardar_analisis(nivel, senales):
    veredicto = calcular(senales)
    return Analisis.objects.create(
        tipo_entrada=Analisis.Tipo.ENLACE,
        dominio="web-de-prueba.example",
        redirecciones=0,
        nivel=int(veredicto.nivel),
        puntaje=veredicto.puntaje,
        cobertura=veredicto.cobertura,
        version_reglas=VERSION_INICIAL.numero,
        senales=asdict(senales),
        reglas=list(veredicto.reglas),
        fuentes=[],
    )


SENALES = {
    Nivel.SEGURO: Senales(heuristicas=(), edad_dias=4000, marca=0, fuentes=0),
    Nivel.TEN_CUIDADO: Senales(heuristicas=("acortador",)),
    Nivel.PELIGROSO: Senales(fuentes=100, fuentes_con_deteccion=1),
    Nivel.PELIGRO_ALTO: Senales(fuentes=100, fuentes_con_deteccion=2),
}
RUTAS = ["inicio", "guia", "modalidades", "privacidad", "terminos", "como_verificamos", "contacto"]


def paginas(client):
    """Todas las páginas que ve un ciudadano, como (nombre, html)."""
    resultado = [(nombre, client.get(reverse(nombre)).content.decode()) for nombre in RUTAS]
    resultado.append(("404", client.get("/ruta-que-no-existe/").content.decode()))
    for nivel, senales in SENALES.items():
        analisis = _guardar_analisis(nivel, senales)
        pagina = client.get(reverse("resultado", args=[analisis.publico])).content.decode()
        resultado.append((f"resultado-{nivel.clave}", pagina))
    return resultado


pytestmark_db = pytest.mark.django_db


@pytest.fixture
def todas(client, db):
    return paginas(client)


def test_cada_pagina_declara_idioma_titulo_y_un_solo_h1(todas):
    for nombre, html in todas:
        etiquetas = leer(html)
        assert de(etiquetas, "html")[0]["attrs"].get("lang") == "es", nombre
        assert de(etiquetas, "title")[0]["texto"].strip(), nombre
        assert len(de(etiquetas, "h1")) == 1, nombre


def test_el_enlace_para_saltar_es_el_primero_y_apunta_al_contenido(todas):
    for nombre, html in todas:
        etiquetas = leer(html)
        primer_enlace = de(etiquetas, "a")[0]
        assert primer_enlace["attrs"]["href"] == "#contenido", nombre
        assert "Saltar al contenido" in primer_enlace["texto"], nombre
        principales = de(etiquetas, "main")
        assert len(principales) == 1, nombre
        assert principales[0]["attrs"]["id"] == "contenido", nombre
        assert principales[0]["attrs"].get("tabindex") == "-1", nombre


def test_los_ids_son_unicos_y_las_referencias_existen(todas):
    for nombre, html in todas:
        etiquetas = leer(html)
        ids = [e["attrs"]["id"] for e in etiquetas if "id" in e["attrs"]]
        assert len(ids) == len(set(ids)), (nombre, [i for i in ids if ids.count(i) > 1])
        for e in etiquetas:
            for atributo in ("aria-controls", "aria-describedby", "aria-labelledby"):
                for referencia in e["attrs"].get(atributo, "").split():
                    assert referencia in ids, (nombre, atributo, referencia)
            href = e["attrs"].get("href", "")
            if e["tag"] == "a" and href.startswith("#") and len(href) > 1:
                assert href[1:] in ids, (nombre, href)


def test_todo_control_tiene_nombre_accesible(todas):
    for nombre, html in todas:
        etiquetas = leer(html)
        etiquetados = {e["attrs"].get("for") for e in de(etiquetas, "label")}
        for e in de(etiquetas, "button") + de(etiquetas, "a"):
            nombre_accesible = e["texto"].strip() or e["attrs"].get("aria-label")
            assert nombre_accesible, (nombre, e["attrs"])
        for e in de(etiquetas, "input") + de(etiquetas, "textarea") + de(etiquetas, "select"):
            if e["attrs"].get("type") in {"hidden", "submit"}:
                continue
            assert (
                e["attrs"].get("id") in etiquetados
                or e["attrs"].get("aria-label")
                or e["attrs"].get("aria-labelledby")
            ), (nombre, e["attrs"])


def test_los_iconos_son_decorativos_y_nadie_fuerza_el_orden_del_teclado(todas):
    for nombre, html in todas:
        etiquetas = leer(html)
        for e in de(etiquetas, "svg"):
            if e["attrs"].get("class") == "sprite":
                continue
            assert e["attrs"].get("aria-hidden") == "true" or e["attrs"].get("aria-label"), nombre
        for e in etiquetas:
            assert int(e["attrs"].get("tabindex", 0)) <= 0, (nombre, e["tag"])


def test_ninguna_pagina_usa_estilos_ni_scripts_en_linea(todas):
    # La CSP prohíbe lo que va en línea; si algo así llegara, el navegador lo bloquearía.
    for nombre, html in todas:
        etiquetas = leer(html)
        assert not any("style" in e["attrs"] for e in etiquetas), nombre
        assert all(e["attrs"].get("src") for e in de(etiquetas, "script")), nombre


def test_cada_pagina_carga_las_preferencias_antes_de_pintar(todas):
    for nombre, html in todas:
        etiquetas = leer(html)
        scripts = de(etiquetas, "script")
        propio = [e for e in scripts if "accesibilidad" in e["attrs"].get("src", "")]
        assert propio, nombre
        # Sin defer ni async: tiene que correr antes del primer pintado.
        assert "defer" not in propio[0]["attrs"] and "async" not in propio[0]["attrs"], nombre


def test_el_panel_de_ajustes_empieza_oculto_y_no_hace_falta_para_leer(client, db):
    etiquetas = leer(client.get(reverse("inicio")).content.decode())
    ajustes = [e for e in etiquetas if "data-ajustes" in e["attrs"]]
    assert "hidden" in ajustes[0]["attrs"]
    panel = [e for e in etiquetas if "data-ajustes-panel" in e["attrs"]]
    assert "hidden" in panel[0]["attrs"]


# --- El veredicto nunca depende solo del color --------------------------------------------


@pytest.mark.parametrize("nivel", list(Nivel), ids=lambda nivel: nivel.clave)
def test_el_veredicto_lleva_color_icono_y_texto(client, db, nivel):
    analisis = _guardar_analisis(nivel, SENALES[nivel])
    html = client.get(reverse("resultado", args=[analisis.publico])).content.decode()
    etiquetas = leer(html)
    articulos = de(etiquetas, "article")
    principal = next(e for e in articulos if "resultado-principal" in e["attrs"]["class"])
    assert f"nivel-{nivel.clave}" in principal["attrs"]["class"]  # color
    assert f'href="#i-{nivel.clave}"' in html  # ícono propio de cada nivel
    palabra = next(e for e in de(etiquetas, "h1"))
    assert palabra["texto"].strip()  # texto
    # El color del nivel sale de una variable que los tests de contraste miden en los dos modos.
    assert f".nivel-{nivel.clave} {{ --color-nivel: var(--{nivel.clave}); }}" in CSS.read_text(
        encoding="utf-8"
    )
    assert nivel.clave in COLORES_DE_TEXTO


# --- JS de preferencias -------------------------------------------------------------------


def test_las_preferencias_van_a_localstorage_y_no_a_una_cookie():
    codigo = JS.read_text(encoding="utf-8")
    assert "localStorage" in codigo
    assert "document.cookie" not in codigo
    assert "alerta.texto" in codigo and "alerta.contraste" in codigo


# --- Volcado para el revisor automático (axe-core) ------------------------------------------


@pytest.mark.skipif(
    not os.environ.get("ALERTA_VOLCAR_HTML"), reason="solo lo corre el job de accesibilidad del CI"
)
def test_volcar_paginas_para_axe(client, db):
    destino = Path(os.environ["ALERTA_VOLCAR_HTML"])
    destino.mkdir(parents=True, exist_ok=True)
    for nombre, html in paginas(client):
        (destino / f"{nombre}.html").write_text(html, encoding="utf-8")
