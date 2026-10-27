from django.contrib import admin
from django.urls import include, path

from core import views as core_views

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("django.contrib.auth.urls")),
    path("api/", include("billing.api_urls")),
    path("demo/", include("demo.urls")),
    path("healthz", core_views.healthz, name="healthz"),
    path("", include("billing.urls")),
]
