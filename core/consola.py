"""Sitio del admin de Django que sirve de consola interna.

Se entra con usuario, contraseña y código del autenticador (TOTP) o un código de
recuperación, en la ruta de DJANGO_ADMIN_PATH. Una sesión sin el segundo factor
verificado no abre ninguna página. No hay autoregistro: las cuentas las crea un
administrador (ver core/roles.py y el comando crear_cuenta_interna).
"""
from django import forms
from django.contrib import admin
from django.contrib.admin.forms import AdminAuthenticationForm
from django.contrib.auth import authenticate, get_user_model
from django.db import transaction
from django.urls import path
from django_otp import devices_for_user
from django_otp.plugins.otp_static.models import StaticDevice
from django_otp.plugins.otp_totp.models import TOTPDevice

from . import bloqueo
from .auditoria import registrar_evento
from .entrada import INGRESO, limitar
from .models import TipoEvento

# El mismo mensaje para usuario inexistente, contraseña o código incorrectos y cuenta
# bloqueada: ninguna respuesta revela qué cuentas existen ni cuál está bloqueada.
MENSAJE_ERROR = (
    "No pudimos iniciar sesión. Revisa el usuario, la contraseña y el código. "
    "Tras 5 intentos fallidos seguidos, la cuenta se bloquea 15 minutos."
)


def _cuenta_por_nombre(nombre):
    """La cuenta con ese nombre exacto, o None. Solo sirve para el bloqueo y la auditoría."""
    modelo = get_user_model()
    try:
        return modelo._default_manager.get_by_natural_key(nombre)
    except modelo.DoesNotExist:
        return None


def _objeto(cuenta):
    return f"auth.User:{cuenta.pk}" if cuenta is not None else ""


class FormularioIngreso(AdminAuthenticationForm):
    """Usuario, contraseña y código, con bloqueo por cuenta y auditoría de cada intento."""

    otp_token = forms.CharField(
        label="Código del autenticador o de recuperación",
        max_length=16,
        widget=forms.TextInput(attrs={"autocomplete": "one-time-code", "spellcheck": "false"}),
    )

    error_messages = {
        **AdminAuthenticationForm.error_messages,
        "invalid_login": MENSAJE_ERROR,
    }

    def clean(self):
        nombre = self.cleaned_data.get("username")
        clave = self.cleaned_data.get("password")
        codigo = (self.cleaned_data.get("otp_token") or "").replace(" ", "").lower()
        if not nombre or not clave or not codigo:
            # Un campo vacío ya tiene su propio error y no cuenta como intento.
            return self.cleaned_data

        cuenta = _cuenta_por_nombre(nombre)
        # Se verifica la contraseña aunque la cuenta esté bloqueada, para que el tiempo de
        # respuesta tampoco revele el bloqueo.
        usuario = authenticate(self.request, username=nombre, password=clave)
        if cuenta is not None and bloqueo.esta_bloqueada(cuenta.pk):
            self._fallo(cuenta, "cuenta_bloqueada")
        if usuario is None:
            self._fallo(cuenta, "credenciales")
        if not (usuario.is_active and usuario.is_staff):
            self._fallo(cuenta, "sin_acceso")
        dispositivo = _verificar_codigo(usuario, codigo)
        if dispositivo is None:
            self._fallo(cuenta, "codigo")

        bloqueo.limpiar(usuario.pk)
        # django_otp marca la sesión como verificada al iniciar sesión si el usuario trae
        # el dispositivo con el que pasó el segundo factor.
        usuario.otp_device = dispositivo
        self.user_cache = usuario
        registrar_evento(
            TipoEvento.INICIO_SESION, usuario=usuario, objeto=_objeto(usuario),
            detalle={"factor": "recuperacion" if isinstance(dispositivo, StaticDevice)
                     else "autenticador"},
        )
        return self.cleaned_data

    def _fallo(self, cuenta, causa):
        """Registra el intento fallido, bloquea la cuenta al quinto y corta con el error."""
        registrar_evento(
            TipoEvento.FALLO_SESION, usuario=cuenta, objeto=_objeto(cuenta),
            detalle={"causa": causa},
        )
        if cuenta is not None and causa != "cuenta_bloqueada":
            if bloqueo.registrar_fallo(cuenta.pk):
                registrar_evento(
                    TipoEvento.BLOQUEO_CUENTA, usuario=cuenta, objeto=_objeto(cuenta),
                    motivo=f"{bloqueo.MAX_FALLOS} intentos fallidos seguidos",
                    detalle={"minutos": bloqueo.DURACION_BLOQUEO // 60},
                )
        raise self.get_invalid_login_error()


def _verificar_codigo(usuario, codigo):
    """El dispositivo confirmado que acepta el código, o None.

    Seis dígitos van contra el autenticador; lo demás, contra los códigos de recuperación,
    que se borran al usarse. Solo se prueba un tipo, para no sumar un intento fallido al
    otro. Cada fallo queda guardado y activa la espera creciente de django-otp.
    """
    modelo = TOTPDevice if len(codigo) == 6 and codigo.isdigit() else StaticDevice
    with transaction.atomic():
        for dispositivo in devices_for_user(usuario, for_verify=True):
            if isinstance(dispositivo, modelo) and dispositivo.verify_token(codigo):
                return dispositivo
    return None


class ConsolaAdminSite(admin.AdminSite):
    """La consola interna.

    Las demás apps le agregan páginas propias con `agregar_vista` y tarjetas al inicio con
    `agregar_acceso`, desde su admin.py. Así core no importa de ninguna otra app.
    """

    site_header = "Consola de Alerta Segura"
    site_title = "Consola de Alerta Segura"
    index_title = "Inicio"
    login_form = FormularioIngreso
    login_template = "admin/ingreso.html"
    index_template = "admin/consola_inicio.html"
    # Los enlaces "Ver en el sitio" llevarían a la portada pública; no aportan nada aquí.
    site_url = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._vistas = []
        self._accesos = []

    def agregar_vista(self, ruta, vista, nombre):
        """Agrega una página propia de la consola. Pasa por admin_view: exige sesión con
        segundo factor; cada vista revisa además el permiso de su rol."""
        self._vistas.append(path(ruta, self.admin_view(vista), name=nombre))

    def agregar_acceso(self, acceso, orden=50):
        """Agrega una tarjeta al inicio. `acceso(request)` devuelve un diccionario con
        titulo, descripcion, url y cifra (None si no tiene), o None si la cuenta no lo ve.
        Las tarjetas se ordenan por `orden`, de menor a mayor."""
        self._accesos.append((orden, acceso))
        self._accesos.sort(key=lambda par: par[0])

    def get_urls(self):
        # Antes que las del admin, que terminan con una ruta que atrapa todo.
        return [*self._vistas, *super().get_urls()]

    def index(self, request, extra_context=None):
        accesos = [tarjeta for _, acceso in self._accesos if (tarjeta := acceso(request))]
        return super().index(request, {**(extra_context or {}), "accesos": accesos})

    def has_permission(self, request):
        """Cuenta interna activa y con el segundo factor verificado en esta sesión."""
        usuario = request.user
        verificado = getattr(usuario, "is_verified", None)
        return bool(
            usuario.is_active and usuario.is_staff and verificado is not None and verificado()
        )

    def login(self, request, extra_context=None):
        # Cada envío del formulario cuenta para el límite por IP de la capa de entrada,
        # además del bloqueo por cuenta. Ver la página no cuenta.
        if request.method == "POST":
            return limitar(INGRESO)(super().login)(request, extra_context)
        return super().login(request, extra_context)
