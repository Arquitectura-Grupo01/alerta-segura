"""Estafas frecuentes (tarea 33), acciones por modalidad y canal oficial de la marca (22)."""

import pytest
from django.urls import reverse

from analisis import orquestador
from analisis.models import Analisis
from catalogo.models import CanalOficial, DominioOficial, Marca
from inteligencia import fuentes as modulo_fuentes
from inteligencia.fuentes import Fuente
from motor import modalidades
from motor.explicacion import (
    ESCRIBE_LA_OFICIAL,
    PISTA_MODALIDAD,
    TITULAR_SEGURO_CON_SENALES,
    USA_CANAL_OFICIAL,
    explicar,
)
from motor.explicacion import Marca as MarcaImitada
from motor.modalidades import MODALIDADES, POR_CLAVE, detectar
from motor.riesgo import Nivel, Senales, calcular

PELIGROSO = Senales(heuristicas=("ip_como_dominio", "palabras_sospechosas"))


def test_la_pagina_tiene_las_seis_modalidades_con_sus_tres_partes(client):
    html = client.get(reverse("modalidades")).content.decode()
    assert len(MODALIDADES) == 6
    for modalidad in MODALIDADES:
        seccion = html.split(f'id="{modalidad.clave}"')[1].split("</section>")[0]
        for parte in ("Cómo funciona", "Cómo reconocerla", "Qué hacer"):
            assert parte in seccion
        assert all(texto in seccion for texto in modalidad.que_hacer)
    assert "<form" not in html


def test_la_pagina_se_enlaza_desde_el_pie(client):
    pie = client.get(reverse("inicio")).content.decode().split('<footer class="pie">')[1]
    assert f'href="{reverse("modalidades")}"' in pie


# --- Detección por las palabras de la dirección --------------------------------

@pytest.mark.parametrize(("direccion", "clave"), [
    ("bono-familiar-peru.example /cobrar", "premio-o-bono-falso"),
    ("tienda.example /devolución/sunat", "premio-o-bono-falso"),
    ("cuenta-bloqueada.example /desbloquear", "bloqueo-de-cuenta"),
    ("seguro.example /verificacion", "bloqueo-de-cuenta"),
    ("chat.example /whatsapp-codigo", "codigo-de-whatsapp"),
    ("pagos.example /yape/constancia", "yapeo-por-error"),
    ("ganadinero.example /prestamos-rapidos", "prestamo-o-trabajo-falso"),
    ("ejemplo.example /inicio", ""),
    # «carbono» contiene «bono», pero no empieza con esa palabra.
    ("huella-de-carbono.example /calcular", ""),
])
def test_reconoce_la_modalidad_por_el_comienzo_de_las_palabras(direccion, clave):
    dominio = direccion.split()[0]
    assert detectar([direccion], dominio) == clave


@pytest.mark.parametrize("dominio", ["www.sunat.gob.pe", "gob.pe", "banco-de-prueba.pe"])
def test_una_web_del_estado_o_un_dominio_oficial_nunca_se_marca(dominio):
    assert detectar([f"{dominio} /devolucion/bono"], dominio, ["banco-de-prueba.pe"]) == ""


def test_whatsapp_gana_sobre_las_demas_si_coinciden_varias():
    assert detectar(["x.example /whatsapp/premio/verificar"], "x.example") == "codigo-de-whatsapp"


# --- Lo que muestra el resultado ------------------------------------------------

def test_un_resultado_con_hallazgos_enlaza_a_su_modalidad_y_suma_su_accion():
    explicacion = explicar(calcular(PELIGROSO), "x.example", modalidad="premio-o-bono-falso")
    modalidad = POR_CLAVE["premio-o-bono-falso"]
    assert explicacion.modalidad == (
        modalidad.clave, PISTA_MODALIDAD.format(titulo=modalidad.titulo)
    )
    assert modalidad.accion in explicacion.acciones


@pytest.mark.parametrize("senales", [
    # Seguro: no hay estafa de la que hablar.
    Senales(heuristicas=(), edad_dias=900, marca=0, fuentes=0),
    # Ten cuidado sin nada en contra: sería una acusación sin pruebas.
    Senales(edad_dias=900),
])
def test_sin_hallazgos_no_se_sugiere_ninguna_modalidad(senales):
    explicacion = explicar(calcular(senales), "x.example", modalidad="premio-o-bono-falso")
    assert explicacion.modalidad is None
    assert POR_CLAVE["premio-o-bono-falso"].accion not in explicacion.acciones


def test_una_modalidad_desconocida_se_ignora():
    assert explicar(calcular(PELIGROSO), "x.example", modalidad="otra").modalidad is None


def test_la_marca_imitada_se_nombra_y_se_muestran_sus_canales():
    marca = MarcaImitada("Banco de Prueba", (("Aplicación móvil", "App Banco de Prueba"),))
    senales = Senales(heuristicas=("marca_en_subdominio",), marca=100, edad_dias=5)
    explicacion = explicar(calcular(senales), "falso.example", marca=marca)
    assert "Usa el nombre de Banco de Prueba, pero la web que abre es falso.example." in (
        explicacion.motivos
    )
    assert USA_CANAL_OFICIAL.format(marca="Banco de Prueba") in explicacion.acciones
    assert explicacion.marca == marca


def test_sin_canales_verificados_se_pide_escribir_la_direccion_oficial():
    senales = Senales(heuristicas=("dominio_parecido",), marca=100, edad_dias=5)
    explicacion = explicar(calcular(senales), "x.example", marca=MarcaImitada("Banco de Prueba"))
    assert ESCRIBE_LA_OFICIAL.format(marca="Banco de Prueba") in explicacion.acciones
    assert "Su nombre se parece mucho al de Banco de Prueba" in explicacion.motivos[0]


def test_sin_marca_conocida_el_texto_no_queda_con_un_hueco():
    senales = Senales(heuristicas=("marca_en_subdominio",), marca=100, edad_dias=5)
    motivos = explicar(calcular(senales), "x.example").motivos
    assert "Usa el nombre de una marca conocida, pero la web que abre es x.example." in motivos
    assert not any("{" in motivo for motivo in motivos)


def test_un_seguro_con_un_truco_en_la_direccion_no_dice_que_no_hay_senales():
    senales = Senales(heuristicas=("usuario_en_url",), edad_dias=900, marca=0, fuentes=0)
    veredicto = calcular(senales)
    if veredicto.nivel == Nivel.SEGURO:
        assert explicar(veredicto, "x.example").titular == TITULAR_SEGURO_CON_SENALES


# --- De punta a punta -----------------------------------------------------------

class Detecta(Fuente):
    nombre = "detecta"
    titulo = "Lista de prueba"

    def _consultar(self, url):
        return self.deteccion(datos={"tipos": ["pagina_falsa"]})


@pytest.fixture
def catalogo(db):
    marca = Marca.objects.create(nombre="Banco de Prueba", tipo=Marca.Tipo.BANCO)
    DominioOficial.objects.create(
        marca=marca, dominio="bancodeprueba.pe", estado=DominioOficial.Estado.APROBADO,
        fuente_verificacion="https://registro.example/ficha",
    )
    CanalOficial.objects.create(
        marca=marca, tipo=CanalOficial.Tipo.APP, valor="App Banco de Prueba", activo=True,
        fuente_verificacion="https://registro.example/app",
    )
    CanalOficial.objects.create(
        marca=marca, tipo=CanalOficial.Tipo.TELEFONO, valor="01 000 0000", activo=False,
        fuente_verificacion="https://registro.example/telefono",
    )
    return marca


def analizar(client, enlace):
    return client.post(reverse("analizar"), {"enlace": enlace}, follow=True).content.decode()


@pytest.mark.django_db
def test_el_resultado_enlaza_a_la_seccion_de_su_modalidad(client, monkeypatch):
    monkeypatch.setattr(modulo_fuentes, "_FUENTES", [Detecta()])
    html = analizar(client, "https://bono-del-estado.example/cobrar")
    assert Analisis.objects.get().modalidad == "premio-o-bono-falso"
    assert f'href="{reverse("modalidades")}#premio-o-bono-falso"' in html
    assert POR_CLAVE["premio-o-bono-falso"].accion in html


@pytest.mark.django_db
def test_el_resultado_muestra_solo_los_canales_activos_de_la_marca(client, catalogo, monkeypatch):
    monkeypatch.setattr(orquestador, "edad_en_dias", lambda dominios: 4)
    html = analizar(client, "https://bancodeprueba.pe.sitio-falso.example/inicio")
    assert Analisis.objects.get().marca_suplantada == "Banco de Prueba"
    assert "Canales oficiales de Banco de Prueba" in html
    assert "<dd>App Banco de Prueba</dd>" in html
    assert "01 000 0000" not in html
    assert "Usa el nombre de Banco de Prueba" in html


@pytest.mark.django_db
def test_la_web_oficial_no_se_marca_como_imitacion(client, catalogo):
    analizar(client, "https://bancodeprueba.pe/verificacion")
    analisis = Analisis.objects.get()
    assert (analisis.marca_suplantada, analisis.modalidad) == ("", "")


def test_detectar_ignora_mayusculas_y_tildes():
    assert modalidades.detectar(["X.EXAMPLE /DEVOLUCIÓN"], "x.example") == "premio-o-bono-falso"


def test_toda_modalidad_que_llega_por_enlace_tiene_prioridad_y_viceversa():
    con_palabras = {modalidad.clave for modalidad in MODALIDADES if modalidad.palabras}
    assert set(modalidades.PRIORIDAD) == con_palabras


def test_si_imita_a_una_marca_en_una_web_nueva_el_titular_lo_dice():
    from motor.explicacion import TITULAR_IMITA

    senales = Senales(heuristicas=("marca_en_subdominio",), marca=100, edad_dias=4)
    explicacion = explicar(calcular(senales), "x.example", marca=MarcaImitada("Banco de Prueba"))
    assert explicacion.titular == TITULAR_IMITA
    assert "Imita a Banco de Prueba en una web creada hace 4 días." in explicacion.motivos
