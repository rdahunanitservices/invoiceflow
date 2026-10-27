from django.urls import path

from . import views

app_name = "demo"

urlpatterns = [
    path("start/", views.start, name="start"),
]
