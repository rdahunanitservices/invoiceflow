from decimal import Decimal

from django.db import transaction
from rest_framework import serializers

from core.validators import normalize_abn

from . import services
from .models import Client, Invoice, LineItem, Payment


def _org(serializer):
    return serializer.context["request"].user.organization


class ClientSerializer(serializers.ModelSerializer):
    class Meta:
        model = Client
        fields = ["id", "name", "email", "abn", "payment_terms_days", "created_at"]
        read_only_fields = ["id", "created_at"]

    def validate_name(self, value):
        value = value.strip()
        clients = Client.objects.for_org(_org(self)).filter(name__iexact=value)
        if self.instance:
            clients = clients.exclude(pk=self.instance.pk)
        if clients.exists():
            raise serializers.ValidationError("You already have a client with this name.")
        return value

    def validate_abn(self, value):
        return normalize_abn(value)

    def create(self, validated_data):
        return Client.objects.create(organization=_org(self), **validated_data)


class LineSerializer(serializers.ModelSerializer):
    class Meta:
        model = LineItem
        fields = ["id", "description", "quantity", "unit_price", "taxable", "amount", "gst_amount"]
        read_only_fields = ["id", "amount", "gst_amount"]
        extra_kwargs = {
            "quantity": {"min_value": Decimal("0.01")},
            "unit_price": {"min_value": Decimal("0")},
            "taxable": {"default": True},
        }


class PaymentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Payment
        fields = ["id", "amount", "paid_on", "method", "reference", "created_at"]
        read_only_fields = ["id", "created_at"]
        extra_kwargs = {
            "amount": {"min_value": Decimal("0.01")},
            "paid_on": {"required": False},
        }


class InvoiceSerializer(serializers.ModelSerializer):
    number = serializers.CharField(source="display_number", read_only=True)
    client_name = serializers.CharField(source="client.name", read_only=True)
    balance = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    lines = LineSerializer(many=True, read_only=True)
    payments = PaymentSerializer(many=True, read_only=True)

    class Meta:
        model = Invoice
        fields = [
            "id", "number", "client", "client_name", "status", "is_overdue",
            "issue_date", "due_date", "notes",
            "subtotal", "gst", "total", "amount_paid", "balance",
            "lines", "payments", "created_at",
        ]  # fmt: skip
        read_only_fields = fields


class InvoiceCreateSerializer(serializers.Serializer):
    """Create a draft invoice, optionally with its lines, in one request."""

    client = serializers.PrimaryKeyRelatedField(queryset=Client.objects.none())
    issue_date = serializers.DateField(required=False)
    due_date = serializers.DateField(required=False)
    notes = serializers.CharField(required=False, allow_blank=True, default="")
    lines = LineSerializer(many=True, required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Another organisation's client id fails as "Invalid pk", like a missing one.
        self.fields["client"].queryset = Client.objects.for_org(_org(self))

    @transaction.atomic
    def create(self, validated_data):
        lines = validated_data.pop("lines", [])
        invoice = services.create_invoice(_org(self), **validated_data)
        for line in lines:
            services.add_line(invoice, **line)
        return invoice
