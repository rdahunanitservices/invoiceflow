from django.urls import path
from rest_framework.routers import DefaultRouter

from .api import ClientViewSet, InvoiceViewSet, TokenView

router = DefaultRouter()
router.register("clients", ClientViewSet, basename="api-client")
router.register("invoices", InvoiceViewSet, basename="api-invoice")

urlpatterns = [
    path("auth/token/", TokenView.as_view(), name="api-token"),
    *router.urls,
]
