"""Formularios de la consola del catálogo. Las reglas de fondo viven en servicios.py."""
from django import forms

from .models import Marca

MAX_MOTIVO = 200


def _motivo():
    return forms.CharField(
        label="Motivo", max_length=MAX_MOTIVO, widget=forms.Textarea(attrs={"rows": 3}),
        help_text="Queda en el historial y en la auditoría. Sin enlaces, IP ni datos personales.",
    )


class FormularioMarcaNueva(forms.Form):
    nombre = forms.CharField(label="Nombre", max_length=150)
    tipo = forms.ChoiceField(label="Tipo", choices=Marca.Tipo.choices)
    motivo = _motivo()


class FormularioMarca(forms.Form):
    nombre = forms.CharField(label="Nombre", max_length=150)
    tipo = forms.ChoiceField(label="Tipo", choices=Marca.Tipo.choices)
    activa = forms.BooleanField(label="Activa", required=False)
    motivo = _motivo()


class FormularioMotivo(forms.Form):
    motivo = _motivo()


class FormularioSolicitudDominio(forms.Form):
    marca = forms.ModelChoiceField(label="Marca", queryset=Marca.objects.order_by("nombre"))
    dominio = forms.CharField(
        label="Dominio oficial", max_length=253,
        help_text="Solo el dominio, sin https:// ni rutas. Por ejemplo, ejemplo.com.pe.",
    )
    fuente_verificacion = forms.URLField(
        label="Dónde lo verificaste", max_length=500, assume_scheme="https",
        help_text="La página de la propia entidad que muestra este dominio.",
    )
    motivo = _motivo()


class FormularioReemplazo(forms.Form):
    dominio_nuevo = forms.CharField(label="Dominio nuevo", max_length=253)
    fuente_verificacion = forms.URLField(
        label="Dónde lo verificaste", max_length=500, assume_scheme="https",
    )
    motivo = _motivo()


class FormularioAprobacion(forms.Form):
    codigo = forms.RegexField(
        label="Código de tu autenticador", regex=r"^\d{6}$", max_length=6,
        error_messages={"invalid": "Escribe los 6 dígitos del autenticador."},
        widget=forms.TextInput(attrs={"autocomplete": "one-time-code", "inputmode": "numeric"}),
        help_text="Aprobar un dominio oficial pide el código otra vez. Si acabas de "
                  "ingresar, espera a que la app muestre un código nuevo.",
    )
    motivo = _motivo()

