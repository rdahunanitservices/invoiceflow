from django.urls import path

from . import views

app_name = "billing"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("clients/", views.client_list, name="client_list"),
    path("invoices/", views.invoice_list, name="invoice_list"),
    path("invoices/new/", views.invoice_create, name="invoice_create"),
    path("invoices/<int:pk>/", views.invoice_detail, name="invoice_detail"),
    path("invoices/<int:pk>/lines/", views.line_add, name="line_add"),
    path("invoices/<int:pk>/lines/<int:line_pk>/delete/", views.line_delete, name="line_delete"),
    path("invoices/<int:pk>/send/", views.invoice_send, name="invoice_send"),
    path("invoices/<int:pk>/void/", views.invoice_void, name="invoice_void"),
    path("invoices/<int:pk>/payments/", views.payment_add, name="payment_add"),
]
