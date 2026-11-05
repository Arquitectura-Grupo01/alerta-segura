from django.conf import settings
from django.contrib import admin
from django.urls import path
from django.views.generic import TemplateView

from core import views

urlpatterns = [
    # Página de inicio. Pasará a una vista de analisis cuando exista el orquestador (tarea 25).
    path("", TemplateView.as_view(template_name="inicio.html"), name="inicio"),
    path("health/", views.health, name="health"),
    path("ready/", views.ready, name="ready"),
    path(settings.ADMIN_PATH, admin.site.urls),
]
