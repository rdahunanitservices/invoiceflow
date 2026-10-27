from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction

from billing import services
from billing.models import Invoice, Payment
from billing.services import BillingError

D = Decimal


@pytest.fixture
def draft(org, customer):
    return services.create_invoice(org, customer, issue_date=date(2026, 10, 1))


@pytest.fixture
def sent(draft):
    services.add_line(draft, "Strategy workshop", D("1"), D("1000.00"))
    return services.mark_sent(draft)


# --- amounts and GST -------------------------------------------------------


@pytest.mark.parametrize(
    ("quantity", "unit_price", "taxable", "amount", "gst"),
    [
        (D("1"), D("100.00"), True, D("100.00"), D("10.00")),
        (D("3"), D("33.33"), True, D("99.99"), D("10.00")),  # 9.999 rounds up
        (D("0.5"), D("0.05"), True, D("0.03"), D("0.00")),  # 0.025 rounds half up
        (D("2"), D("250.00"), False, D("500.00"), D("0.00")),  # GST-free line
    ],
)
def test_line_amounts_round_each_line_to_the_cent(quantity, unit_price, taxable, amount, gst):
    assert services.line_amounts(quantity, unit_price, taxable) == (amount, gst)


def test_invoice_totals_follow_lines_as_they_change(draft):
    services.add_line(draft, "Advisory hours", D("7.5"), D("180.00"))
    line = services.add_line(draft, "Travel (GST-free)", D("1"), D("85.50"), taxable=False)
    draft.refresh_from_db()
    assert (draft.subtotal, draft.gst, draft.total) == (D("1435.50"), D("135.00"), D("1570.50"))

    services.remove_line(line)
    draft.refresh_from_db()
    assert (draft.subtotal, draft.gst, draft.total) == (D("1350.00"), D("135.00"), D("1485.00"))


# --- numbering and tenancy -------------------------------------------------


def test_invoice_numbers_are_sequential_per_organisation(org, customer, other_org, other_customer):
    first = services.create_invoice(org, customer)
    second = services.create_invoice(org, customer)
    elsewhere = services.create_invoice(other_org, other_customer)

    assert (first.number, second.number) == (1, 2)
    assert elsewhere.number == 1
    assert second.display_number == "INV-00002"


def test_cannot_invoice_another_organisations_client(org, other_customer):
    with pytest.raises(BillingError, match="Client not found"):
        services.create_invoice(org, other_customer)
    assert not Invoice.objects.exists()


def test_for_org_only_returns_that_organisations_records(org, customer, other_org, other_customer):
    mine = services.create_invoice(org, customer)
    services.create_invoice(other_org, other_customer)

    assert list(Invoice.objects.for_org(org)) == [mine]


def test_due_date_defaults_to_client_payment_terms(org, customer):
    invoice = services.create_invoice(org, customer, issue_date=date(2026, 10, 1))
    assert invoice.due_date == date(2026, 10, 15)


def test_due_date_before_issue_date_is_refused(org, customer):
    with pytest.raises(BillingError):
        services.create_invoice(
            org, customer, issue_date=date(2026, 10, 10), due_date=date(2026, 10, 1)
        )


def test_database_rejects_duplicate_invoice_numbers(draft):
    with pytest.raises(IntegrityError), transaction.atomic():
        Invoice.objects.create(
            organization=draft.organization,
            client=draft.client,
            number=draft.number,
            due_date=draft.due_date,
        )


# --- status changes ---------------------------------------------------------


def test_cannot_send_an_empty_invoice(draft):
    with pytest.raises(BillingError, match="Add at least one line"):
        services.mark_sent(draft)


def test_sent_invoices_cannot_be_edited(sent):
    with pytest.raises(BillingError, match="Only draft"):
        services.add_line(sent, "Extra", D("1"), D("10.00"))
    with pytest.raises(BillingError, match="Only draft"):
        services.remove_line(sent.lines.get())


@pytest.mark.parametrize(("quantity", "unit_price"), [(D("0"), D("10")), (D("1"), D("-1"))])
def test_invalid_line_values_are_refused(draft, quantity, unit_price):
    with pytest.raises(BillingError):
        services.add_line(draft, "Bad line", quantity, unit_price)


def test_overdue_means_sent_and_past_due(sent):
    after_due = sent.due_date + timedelta(days=1)
    assert list(Invoice.objects.overdue(today=after_due)) == [sent]
    assert not Invoice.objects.overdue(today=sent.due_date).exists()


# --- payments ---------------------------------------------------------------


def test_part_then_full_payment_marks_invoice_paid(sent):
    services.record_payment(sent, D("400.00"), reference="EFT 1")
    sent.refresh_from_db()
    assert (sent.status, sent.amount_paid, sent.balance) == ("sent", D("400.00"), D("700.00"))

    services.record_payment(sent, D("700.00"), reference="EFT 2")
    sent.refresh_from_db()
    assert (sent.status, sent.balance) == ("paid", D("0.00"))


def test_overpayment_is_refused(sent):
    with pytest.raises(BillingError, match=r"more than the balance owing \(\$1,100.00\)"):
        services.record_payment(sent, D("1100.01"))
    assert not Payment.objects.exists()


@pytest.mark.parametrize("amount", [D("0"), D("-5")])
def test_payment_must_be_positive(sent, amount):
    with pytest.raises(BillingError):
        services.record_payment(sent, amount)


def test_no_payments_on_drafts_or_paid_invoices(org, customer, sent):
    another_draft = services.create_invoice(org, customer)
    with pytest.raises(BillingError):
        services.record_payment(another_draft, D("1"))
    services.record_payment(sent, sent.total)
    with pytest.raises(BillingError):
        services.record_payment(sent, D("1"))


def test_invoice_with_payments_cannot_be_voided(sent):
    services.record_payment(sent, D("100.00"))
    with pytest.raises(BillingError, match="can't be voided"):
        services.void_invoice(sent)


def test_void_a_sent_invoice_without_payments(sent):
    assert services.void_invoice(sent).status == Invoice.Status.VOID
