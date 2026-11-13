from django.conf import settings
from django.contrib import admin
from django.urls import path

from analisis import views as analisis
from core import views
from curacion import views as curacion

urlpatterns = [
    path("", views.inicio, name="inicio"),
    path("analizar/", analisis.analizar, name="analizar"),
    path("resultado/<uuid:publico>/", analisis.resultado, name="resultado"),
    path("resultado/<uuid:publico>/reporte/", curacion.reportar, name="reportar"),
    path("guia/", views.guia, name="guia"),
    path("estafas-frecuentes/", analisis.modalidades, name="modalidades"),
    path("privacidad/", views.privacidad, name="privacidad"),
    path("terminos/", views.terminos, name="terminos"),
    path("como-verificamos/", views.como_verificamos, name="como_verificamos"),
    path("contacto/", curacion.contacto, name="contacto"),
    path("contacto/enviar/", curacion.solicitar_revision, name="solicitar_revision"),
    path(".well-known/security.txt", views.security_txt, name="security_txt"),
    path("health/", views.health, name="health"),
    path("ready/", views.ready, name="ready"),
    path(settings.ADMIN_PATH, admin.site.urls),
]
