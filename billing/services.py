"""Billing rules. The HTML views and the API both call these functions, so
every rule lives in exactly one place. Each write runs in a transaction and
locks the rows it depends on, so two requests can't race each other into a
duplicate invoice number or an overpayment."""

from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from accounts.models import Organization

from .models import ZERO, Client, Invoice, LineItem, Payment

GST_RATE = Decimal("0.10")
CENT = Decimal("0.01")


class BillingError(ValidationError):
    """A business rule refused the change. The message is safe to show users."""


def money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def line_amounts(quantity: Decimal, unit_price: Decimal, taxable: bool) -> tuple[Decimal, Decimal]:
    """Amount and GST for one line, each rounded to the cent."""
    amount = money(quantity * unit_price)
    gst = money(amount * GST_RATE) if taxable else ZERO
    return amount, gst


def _locked(invoice: Invoice) -> Invoice:
    return Invoice.objects.select_for_update().get(pk=invoice.pk)


def _recalculate(invoice: Invoice) -> None:
    lines = invoice.lines.aggregate(subtotal=Sum("amount"), gst=Sum("gst_amount"))
    invoice.subtotal = lines["subtotal"] or ZERO
    invoice.gst = lines["gst"] or ZERO
    invoice.total = invoice.subtotal + invoice.gst
    invoice.amount_paid = invoice.payments.aggregate(paid=Sum("amount"))["paid"] or ZERO
    if invoice.status == Invoice.Status.SENT and invoice.total and not invoice.balance:
        invoice.status = Invoice.Status.PAID
    invoice.save(update_fields=["subtotal", "gst", "total", "amount_paid", "status"])


@transaction.atomic
def create_invoice(
    org: Organization,
    client: Client,
    issue_date: date | None = None,
    due_date: date | None = None,
    notes: str = "",
) -> Invoice:
    if client.organization_id != org.pk:
        # Same message as a missing client, so ids from other orgs reveal nothing.
        raise BillingError("Client not found.")
    issue_date = issue_date or timezone.localdate()
    due_date = due_date or issue_date + timedelta(days=client.payment_terms_days)
    if due_date < issue_date:
        raise BillingError("The due date can't be before the issue date.")

    locked_org = Organization.objects.select_for_update().get(pk=org.pk)
    number = locked_org.next_invoice_number
    locked_org.next_invoice_number = number + 1
    locked_org.save(update_fields=["next_invoice_number"])

    return Invoice.objects.create(
        organization=org,
        client=client,
        number=number,
        issue_date=issue_date,
        due_date=due_date,
        notes=notes,
    )


@transaction.atomic
def add_line(
    invoice: Invoice,
    description: str,
    quantity: Decimal,
    unit_price: Decimal,
    taxable: bool = True,
) -> LineItem:
    invoice = _locked(invoice)
    if invoice.status != Invoice.Status.DRAFT:
        raise BillingError("Only draft invoices can be edited.")
    if quantity <= 0:
        raise BillingError("Quantity must be more than zero.")
    if unit_price < 0:
        raise BillingError("Unit price can't be negative.")
    amount, gst = line_amounts(quantity, unit_price, taxable)
    line = invoice.lines.create(
        description=description,
        quantity=quantity,
        unit_price=unit_price,
        taxable=taxable,
        amount=amount,
        gst_amount=gst,
    )
    _recalculate(invoice)
    return line


@transaction.atomic
def remove_line(line: LineItem) -> Invoice:
    invoice = _locked(line.invoice)
    if invoice.status != Invoice.Status.DRAFT:
        raise BillingError("Only draft invoices can be edited.")
    line.delete()
    _recalculate(invoice)
    return invoice


@transaction.atomic
def mark_sent(invoice: Invoice) -> Invoice:
    invoice = _locked(invoice)
    if invoice.status != Invoice.Status.DRAFT:
        raise BillingError("Only draft invoices can be sent.")
    if invoice.total <= 0:
        raise BillingError("Add at least one line with a value before sending.")
    invoice.status = Invoice.Status.SENT
    invoice.save(update_fields=["status"])
    return invoice


@transaction.atomic
def record_payment(
    invoice: Invoice,
    amount: Decimal,
    paid_on: date | None = None,
    method: str = Payment.Method.BANK_TRANSFER,
    reference: str = "",
) -> Payment:
    invoice = _locked(invoice)
    if invoice.status != Invoice.Status.SENT:
        raise BillingError("Payments can only be recorded against sent, unpaid invoices.")
    if amount <= 0:
        raise BillingError("Payment amount must be more than zero.")
    if amount > invoice.balance:
        raise BillingError(f"Payment is more than the balance owing (${invoice.balance:,.2f}).")
    payment = invoice.payments.create(
        amount=amount, paid_on=paid_on or timezone.localdate(), method=method, reference=reference
    )
    _recalculate(invoice)
    return payment


@transaction.atomic
def void_invoice(invoice: Invoice) -> Invoice:
    invoice = _locked(invoice)
    if invoice.status not in (Invoice.Status.DRAFT, Invoice.Status.SENT):
        raise BillingError("Only draft or sent invoices can be voided.")
    if invoice.payments.exists():
        raise BillingError("This invoice has payments recorded, so it can't be voided.")
    invoice.status = Invoice.Status.VOID
    invoice.save(update_fields=["status"])
    return invoice
