from decimal import Decimal

from django.db import models
from django.db.models import F, Q
from django.utils import timezone

from accounts.models import Organization
from core.validators import validate_abn

ZERO = Decimal("0.00")


class OrgQuerySet(models.QuerySet):
    def for_org(self, org):
        """The only way views and the API should start a query. See AGENTS.md."""
        return self.filter(organization=org)


class Client(models.Model):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="clients")
    name = models.CharField(max_length=200)
    email = models.EmailField(blank=True)
    abn = models.CharField("ABN", max_length=14, blank=True, validators=[validate_abn])
    payment_terms_days = models.PositiveSmallIntegerField(
        default=14, help_text="Days from issue date to due date."
    )
    created_at = models.DateTimeField(auto_now_add=True)

    objects = OrgQuerySet.as_manager()

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["organization", "name"], name="unique_client_per_org"),
        ]

    def __str__(self):
        return self.name


class InvoiceQuerySet(OrgQuerySet):
    def overdue(self, today=None):
        today = today or timezone.localdate()
        return self.filter(status=Invoice.Status.SENT, due_date__lt=today)

    def outstanding(self):
        return self.filter(status=Invoice.Status.SENT)


class Invoice(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        SENT = "sent", "Sent"
        PAID = "paid", "Paid"
        VOID = "void", "Void"

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="invoices"
    )
    client = models.ForeignKey(Client, on_delete=models.PROTECT, related_name="invoices")
    number = models.PositiveIntegerField(editable=False)
    status = models.CharField(max_length=5, choices=Status, default=Status.DRAFT)
    issue_date = models.DateField(default=timezone.localdate)
    due_date = models.DateField()
    notes = models.TextField(blank=True)
    # Kept in step with the lines and payments by billing.services; never set directly.
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=ZERO, editable=False)
    gst = models.DecimalField(max_digits=12, decimal_places=2, default=ZERO, editable=False)
    total = models.DecimalField(max_digits=12, decimal_places=2, default=ZERO, editable=False)
    amount_paid = models.DecimalField(max_digits=12, decimal_places=2, default=ZERO, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = InvoiceQuerySet.as_manager()

    class Meta:
        ordering = ["-number"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "number"], name="unique_invoice_number_per_org"
            ),
            models.CheckConstraint(
                condition=Q(due_date__gte=F("issue_date")), name="invoice_due_on_or_after_issue"
            ),
            models.CheckConstraint(
                condition=Q(amount_paid__lte=F("total")), name="invoice_not_overpaid"
            ),
        ]

    def __str__(self):
        return self.display_number

    @property
    def display_number(self):
        return f"INV-{self.number:05d}"

    @property
    def balance(self):
        return self.total - self.amount_paid

    @property
    def is_overdue(self):
        return self.status == self.Status.SENT and self.due_date < timezone.localdate()


class LineItem(models.Model):
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="lines")
    description = models.CharField(max_length=300)
    quantity = models.DecimalField(max_digits=10, decimal_places=2)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    taxable = models.BooleanField(default=True, help_text="Charge 10% GST on this line.")
    # Rounded per line by billing.services.line_amounts.
    amount = models.DecimalField(max_digits=12, decimal_places=2, editable=False)
    gst_amount = models.DecimalField(max_digits=12, decimal_places=2, editable=False)

    class Meta:
        ordering = ["id"]
        constraints = [
            models.CheckConstraint(condition=Q(quantity__gt=0), name="line_quantity_positive"),
            models.CheckConstraint(
                condition=Q(unit_price__gte=0), name="line_unit_price_not_negative"
            ),
        ]

    def __str__(self):
        return self.description


class PaymentQuerySet(models.QuerySet):
    def for_org(self, org):
        return self.filter(invoice__organization=org)


class Payment(models.Model):
    class Method(models.TextChoices):
        BANK_TRANSFER = "bank", "Bank transfer"
        CARD = "card", "Card"
        CASH = "cash", "Cash"
        OTHER = "other", "Other"

    invoice = models.ForeignKey(Invoice, on_delete=models.PROTECT, related_name="payments")
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    paid_on = models.DateField(default=timezone.localdate)
    method = models.CharField(max_length=5, choices=Method, default=Method.BANK_TRANSFER)
    reference = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = PaymentQuerySet.as_manager()

    class Meta:
        ordering = ["paid_on", "id"]
        constraints = [
            models.CheckConstraint(condition=Q(amount__gt=0), name="payment_amount_positive"),
        ]

    def __str__(self):
        return f"{self.amount} on {self.paid_on}"
