"""Formularios de la consola de curación. La validación de fondo vive en servicios.py."""
from django import forms

from analisis.models import Analisis
from analisis.normalizacion import LARGO_MAXIMO
from core.auditoria import MAX_LARGO_MOTIVO

from .estadisticas import MAX_DIAS, Filtros
from .servicios import Alcance, Decision


class FormularioInvalidacion(forms.Form):
    alcance = forms.ChoiceField(
        label="Qué invalidar", choices=Alcance.choices, initial=Alcance.DOMINIO,
        widget=forms.RadioSelect,
    )
    valor = forms.CharField(
        label="Enlace o dominio", max_length=LARGO_MAXIMO,
        widget=forms.TextInput(attrs={"spellcheck": "false", "autocomplete": "off"}),
    )
    motivo = forms.CharField(
        label="Motivo", max_length=MAX_LARGO_MOTIVO,
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text="Queda en la auditoría. Sin enlaces, IP ni datos personales.",
    )


class FormularioDecision(forms.Form):
    decision = forms.ChoiceField(
        label="Decisión", choices=Decision.choices, widget=forms.RadioSelect,
    )
    solo_direcciones = forms.BooleanField(
        label="Aplicar solo a las direcciones reportadas, no a toda la web",
        required=False,
        help_text="Para alojamientos compartidos. Solo hay direcciones de los análisis "
                  "Peligroso o superiores.",
    )
    justificacion = forms.CharField(
        label="Justificación", max_length=MAX_LARGO_MOTIVO,
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text="Queda en la auditoría. Sin enlaces, IP ni datos personales.",
    )


class FormularioFiltros(forms.Form):
    """Filtros del panel de estadísticas. Todo llega por GET y se valida aquí."""

    # El campo de fecha del navegador lee y escribe AAAA-MM-DD, sin importar el idioma.
    desde = forms.DateField(
        label="Desde", required=False,
        widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
    )
    hasta = forms.DateField(
        label="Hasta", required=False,
        widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
    )
    tipo = forms.ChoiceField(
        label="Tipo de entrada", required=False,
        choices=[("", "Todos"), *Analisis.Tipo.choices],
    )
    dominio = forms.CharField(
        label="Web que contiene", required=False, max_length=253,
        widget=forms.TextInput(attrs={"spellcheck": "false", "autocomplete": "off"}),
    )

    def clean(self):
        datos = super().clean()
        por_defecto = Filtros.por_defecto()
        desde = datos.get("desde") or por_defecto.desde
        hasta = datos.get("hasta") or por_defecto.hasta
        if desde > hasta:
            raise forms.ValidationError("La fecha «Desde» debe ser anterior a «Hasta».")
        if (hasta - desde).days + 1 > MAX_DIAS:
            raise forms.ValidationError(f"El período puede tener hasta {MAX_DIAS} días.")
        datos["filtros"] = Filtros(
            desde=desde, hasta=hasta, tipo=datos.get("tipo") or "",
            dominio=(datos.get("dominio") or "").strip().lower(),
        )
        return datos
