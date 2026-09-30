from django.conf import settings
from django.contrib import admin
from django.urls import path

from core import views

urlpatterns = [
    path("health/", views.health, name="health"),
    path("ready/", views.ready, name="ready"),
    path(settings.ADMIN_PATH, admin.site.urls),
]
