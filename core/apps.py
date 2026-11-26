from django.apps import AppConfig
from django.contrib.admin import apps as admin_apps


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core"


class ConsolaAdminConfig(admin_apps.AdminConfig):
    """Reemplaza a django.contrib.admin en INSTALLED_APPS: admin.site pasa a ser la
    consola con segundo factor obligatorio (core/consola.py)."""

    # AdminConfig se declara por defecto para su propio módulo. Aquí no: la configuración
    # por defecto de la app core sigue siendo CoreConfig.
    default = False
    default_site = "core.consola.ConsolaAdminSite"
