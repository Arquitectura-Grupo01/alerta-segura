"""Formularios de la consola de curación. La validación de fondo vive en servicios.py."""
from django import forms

from analisis.normalizacion import LARGO_MAXIMO
from core.auditoria import MAX_LARGO_MOTIVO

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
