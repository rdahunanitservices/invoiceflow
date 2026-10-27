from rest_framework import mixins, viewsets
from rest_framework.authtoken.views import ObtainAuthToken
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle

from core.api import HasOrganization

from . import services
from .models import Client, Invoice
from .serializers import (
    ClientSerializer,
    InvoiceCreateSerializer,
    InvoiceSerializer,
    LineSerializer,
    PaymentSerializer,
)


class TokenView(ObtainAuthToken):
    """POST username and password, get an API token. Throttled against guessing."""

    throttle_classes = [AnonRateThrottle]


class OrgScopedMixin:
    permission_classes = [IsAuthenticated, HasOrganization]

    @property
    def org(self):
        return self.request.user.organization


class ClientViewSet(
    OrgScopedMixin,
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = ClientSerializer

    def get_queryset(self):
        return Client.objects.for_org(self.org)


class InvoiceViewSet(
    OrgScopedMixin,
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Invoices for your organisation. Filter with `?status=draft|sent|paid|void|overdue`.
    Lines can be added while a draft; payments once sent."""

    def get_queryset(self):
        invoices = (
            Invoice.objects.for_org(self.org)
            .select_related("client")
            .prefetch_related("lines", "payments")
        )
        status = self.request.query_params.get("status")
        if status == "overdue":
            return invoices.overdue()
        if status in Invoice.Status.values:
            return invoices.filter(status=status)
        return invoices

    def get_serializer_class(self):
        if self.action == "create":
            return InvoiceCreateSerializer
        if self.action == "add_line":
            return LineSerializer
        if self.action == "add_payment":
            return PaymentSerializer
        return InvoiceSerializer

    def _invoice_response(self, invoice, status=200):
        fresh = self.get_queryset().get(pk=invoice.pk)
        return Response(
            InvoiceSerializer(fresh, context=self.get_serializer_context()).data, status
        )

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return self._invoice_response(serializer.save(), status=201)

    @action(detail=True, methods=["post"], url_path="lines")
    def add_line(self, request, pk=None):
        invoice = self.get_object()
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.add_line(invoice, **serializer.validated_data)
        return self._invoice_response(invoice, status=201)

    @action(detail=True, methods=["post"], url_path="payments")
    def add_payment(self, request, pk=None):
        invoice = self.get_object()
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.record_payment(invoice, **serializer.validated_data)
        return self._invoice_response(invoice, status=201)

    @action(detail=True, methods=["post"])
    def send(self, request, pk=None):
        return self._invoice_response(services.mark_sent(self.get_object()))

    @action(detail=True, methods=["post"])
    def void(self, request, pk=None):
        return self._invoice_response(services.void_invoice(self.get_object()))
