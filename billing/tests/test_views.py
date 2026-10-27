from decimal import Decimal

import pytest
from django.urls import reverse

from accounts.models import User
from billing import services
from billing.models import Client, Invoice

HTMX = {"HTTP_HX_REQUEST": "true"}


@pytest.fixture
def signed_in(client, user):
    client.force_login(user)
    return client


@pytest.fixture
def draft(org, customer):
    return services.create_invoice(org, customer)


@pytest.fixture
def sent(draft):
    services.add_line(draft, "Workshop", Decimal("1"), Decimal("1000.00"))
    return services.mark_sent(draft)


@pytest.fixture
def foreign_invoice(other_org, other_customer):
    invoice = services.create_invoice(other_org, other_customer)
    services.add_line(invoice, "Their secret work", Decimal("1"), Decimal("500.00"))
    return invoice


def url(name, *args):
    return reverse(f"billing:{name}", args=args)


# --- access ------------------------------------------------------------------


@pytest.mark.parametrize("name", ["dashboard", "client_list", "invoice_list", "invoice_create"])
def test_pages_require_sign_in(client, db, name):
    response = client.get(url(name))
    assert response.status_code == 302
    assert response.url.startswith(reverse("login"))


def test_account_without_organisation_is_refused(client, db):
    client.force_login(User.objects.create_user("staff", password="x" * 12))
    assert client.get(url("dashboard")).status_code == 403


@pytest.mark.parametrize("name", ["dashboard", "client_list", "invoice_list", "invoice_create"])
def test_pages_render(signed_in, sent, name):
    assert signed_in.get(url(name)).status_code == 200


def test_post_only_actions_refuse_get(signed_in, draft):
    assert signed_in.get(url("invoice_send", draft.pk)).status_code == 405


# --- tenancy -----------------------------------------------------------------


def test_another_organisations_invoice_is_not_found(signed_in, foreign_invoice):
    assert signed_in.get(url("invoice_detail", foreign_invoice.pk)).status_code == 404


@pytest.mark.parametrize("name", ["line_add", "invoice_send", "invoice_void", "payment_add"])
def test_cannot_act_on_another_organisations_invoice(signed_in, foreign_invoice, name):
    response = signed_in.post(url(name, foreign_invoice.pk), {"description": "x", "amount": "1"})
    assert response.status_code == 404
    foreign_invoice.refresh_from_db()
    assert foreign_invoice.status == Invoice.Status.DRAFT
    assert foreign_invoice.lines.count() == 1


def test_cannot_delete_a_line_through_someone_elses_invoice(signed_in, draft, foreign_invoice):
    their_line = foreign_invoice.lines.get()
    response = signed_in.post(url("line_delete", draft.pk, their_line.pk))
    assert response.status_code == 404
    assert foreign_invoice.lines.exists()


def test_cannot_create_invoice_for_another_organisations_client(
    signed_in, customer, other_customer
):
    response = signed_in.post(
        url("invoice_create"), {"client": other_customer.pk, "issue_date": "2026-10-01"}
    )
    assert response.status_code == 200  # form re-rendered with an error
    assert "Select a valid choice" in response.content.decode()
    assert not Invoice.objects.exists()


def test_lists_only_show_own_records(signed_in, sent, foreign_invoice):
    invoices = signed_in.get(url("invoice_list")).content.decode()
    clients = signed_in.get(url("client_list")).content.decode()
    assert "Coastal Builders" in invoices and "Secret Client" not in invoices
    assert "Coastal Builders" in clients and "Secret Client" not in clients


# --- invoices with htmx ------------------------------------------------------


def test_create_invoice_redirects_to_the_draft(signed_in, customer):
    response = signed_in.post(
        url("invoice_create"), {"client": customer.pk, "issue_date": "2026-10-01"}
    )
    invoice = Invoice.objects.get()
    assert response.status_code == 302
    assert response.url == url("invoice_detail", invoice.pk)
    assert invoice.due_date.isoformat() == "2026-10-15"


def test_htmx_add_line_returns_the_refreshed_invoice_body(signed_in, draft):
    response = signed_in.post(
        url("line_add", draft.pk),
        {"description": "Advisory hours", "quantity": "2", "unit_price": "150", "taxable": "on"},
        **HTMX,
    )
    html = response.content.decode()
    assert response.status_code == 200
    assert 'id="invoice-body"' in html and "<html" not in html
    assert "Advisory hours" in html and "$330.00" in html  # 300 + 30 GST


def test_htmx_invalid_line_is_422_with_field_errors(signed_in, draft):
    response = signed_in.post(
        url("line_add", draft.pk), {"description": "", "quantity": "0", "unit_price": "5"}, **HTMX
    )
    assert response.status_code == 422
    assert "This field is required" in response.content.decode()
    assert not draft.lines.exists()


def test_plain_form_post_still_works_without_javascript(signed_in, draft):
    response = signed_in.post(
        url("line_add", draft.pk), {"description": "Report", "quantity": "1", "unit_price": "99"}
    )
    assert response.status_code == 302
    assert draft.lines.get().gst_amount == Decimal("0.00")  # unchecked box = GST-free


def test_htmx_overpayment_is_422_with_the_reason(signed_in, sent):
    response = signed_in.post(
        url("payment_add", sent.pk),
        {"amount": "5000", "paid_on": "2026-10-20", "method": "bank"},
        **HTMX,
    )
    assert response.status_code == 422
    assert "more than the balance owing ($1,100.00)" in response.content.decode()


def test_htmx_full_payment_marks_invoice_paid(signed_in, sent):
    response = signed_in.post(
        url("payment_add", sent.pk),
        {"amount": "1100.00", "paid_on": "2026-10-20", "method": "bank", "reference": "EFT"},
        **HTMX,
    )
    assert response.status_code == 200
    assert ">Paid<" in response.content.decode()
    sent.refresh_from_db()
    assert sent.status == Invoice.Status.PAID


def test_sending_an_empty_invoice_shows_the_rule(signed_in, draft):
    response = signed_in.post(url("invoice_send", draft.pk), **HTMX)
    assert response.status_code == 422
    assert "Add at least one line" in response.content.decode()


def test_status_filter_shows_overdue(signed_in, sent):
    Invoice.objects.filter(pk=sent.pk).update(issue_date="2026-01-01", due_date="2026-01-15")
    html = signed_in.get(url("invoice_list") + "?status=overdue", **HTMX).content.decode()
    assert sent.display_number in html and "Overdue" in html


# --- clients with htmx -------------------------------------------------------


def test_htmx_add_client(signed_in, org):
    response = signed_in.post(
        url("client_list"),
        {"name": "Bayside Dental", "abn": "51 824 753 556", "payment_terms_days": "30"},
        **HTMX,
    )
    assert response.status_code == 200
    assert "Bayside Dental" in response.content.decode()
    assert Client.objects.get(name="Bayside Dental").abn == "51824753556"


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ({"name": "coastal builders", "payment_terms_days": "14"}, "already have a client"),
        ({"name": "New Co", "abn": "12345678901", "payment_terms_days": "14"}, "valid ABN"),
    ],
)
def test_htmx_invalid_client_is_422(signed_in, customer, data, message):
    response = signed_in.post(url("client_list"), data, **HTMX)
    assert response.status_code == 422
    assert message in response.content.decode()


def test_same_client_name_is_fine_in_another_organisation(signed_in, other_org):
    Client.objects.create(organization=other_org, name="Coastal Builders")
    response = signed_in.post(
        url("client_list"), {"name": "Coastal Builders", "payment_terms_days": "14"}, **HTMX
    )
    assert response.status_code == 200
