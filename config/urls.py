from django.contrib import admin
from django.urls import path

from core import views as core_views

urlpatterns = [
    path("admin/", admin.site.urls),
    path("healthz", core_views.healthz, name="healthz"),
]
