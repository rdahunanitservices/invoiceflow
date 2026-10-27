from django.contrib import admin

from .models import Client, Invoice, LineItem, Payment


class ReadOnlyAdminMixin:
    """Billing records change only through billing.services, which keep totals,
    numbering, and payment rules consistent. The admin is for looking, not editing."""

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display = ("name", "organization", "email", "abn", "payment_terms_days")
    list_filter = ("organization",)
    search_fields = ("name", "email", "abn")


class LineItemInline(ReadOnlyAdminMixin, admin.TabularInline):
    model = LineItem
    fields = ("description", "quantity", "unit_price", "taxable", "amount", "gst_amount")
    readonly_fields = fields


class PaymentInline(ReadOnlyAdminMixin, admin.TabularInline):
    model = Payment
    fields = ("paid_on", "amount", "method", "reference")
    readonly_fields = fields


@admin.register(Invoice)
class InvoiceAdmin(ReadOnlyAdminMixin, admin.ModelAdmin):
    list_display = ("display_number", "organization", "client", "status", "total", "due_date")
    list_filter = ("organization", "status")
    search_fields = ("client__name",)
    inlines = [LineItemInline, PaymentInline]
