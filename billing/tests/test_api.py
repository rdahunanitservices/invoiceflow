from decimal import Decimal

import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from accounts.models import User
from billing import services
from billing.models import Client, Invoice


@pytest.fixture(autouse=True)
def reset_throttles():
    cache.clear()


@pytest.fixture
def api(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


@pytest.fixture
def sent(org, customer):
    invoice = services.create_invoice(org, customer)
    services.add_line(invoice, "Workshop", Decimal("1"), Decimal("1000.00"))
    return services.mark_sent(invoice)


@pytest.fixture
def foreign_invoice(other_org, other_customer):
    invoice = services.create_invoice(other_org, other_customer)
    services.add_line(invoice, "Their secret work", Decimal("1"), Decimal("500.00"))
    return invoice


# --- authentication ----------------------------------------------------------


def test_requires_authentication(db):
    assert APIClient().get("/api/invoices/").status_code == 401


def test_token_login_then_use_the_token(user, sent):
    anonymous = APIClient()
    response = anonymous.post(
        "/api/auth/token/", {"username": "alex", "password": "correct-horse-battery"}
    )
    assert response.status_code == 200

    anonymous.credentials(HTTP_AUTHORIZATION=f"Token {response.json()['token']}")
    invoices = anonymous.get("/api/invoices/").json()
    assert [i["number"] for i in invoices["results"]] == ["INV-00001"]


def test_token_endpoint_is_throttled(user):
    anonymous = APIClient()
    codes = [
        anonymous.post("/api/auth/token/", {"username": "alex", "password": "wrong"}).status_code
        for _ in range(11)
    ]
    assert codes[:10] == [400] * 10
    assert codes[10] == 429


def test_account_without_organisation_is_forbidden(db):
    client = APIClient()
    client.force_authenticate(User.objects.create_user("staff", password="x" * 12))
    assert client.get("/api/invoices/").status_code == 403


# --- tenancy -----------------------------------------------------------------


def test_lists_only_own_records(api, sent, foreign_invoice):
    invoices = api.get("/api/invoices/").json()["results"]
    clients = api.get("/api/clients/").json()["results"]
    assert [i["id"] for i in invoices] == [sent.pk]
    assert [c["name"] for c in clients] == ["Coastal Builders"]


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/api/invoices/{id}/"),
        ("post", "/api/invoices/{id}/send/"),
        ("post", "/api/invoices/{id}/void/"),
        ("post", "/api/invoices/{id}/lines/"),
        ("post", "/api/invoices/{id}/payments/"),
    ],
)
def test_another_organisations_invoice_is_not_found(api, foreign_invoice, method, path):
    response = getattr(api, method)(path.format(id=foreign_invoice.pk), {}, format="json")
    assert response.status_code == 404
    foreign_invoice.refresh_from_db()
    assert foreign_invoice.status == Invoice.Status.DRAFT


def test_cannot_invoice_another_organisations_client(api, other_customer):
    response = api.post("/api/invoices/", {"client": other_customer.pk}, format="json")
    assert response.status_code == 400
    assert "client" in response.json()
    assert not Invoice.objects.exists()


def test_cannot_read_or_edit_another_organisations_client(api, other_customer):
    assert api.get(f"/api/clients/{other_customer.pk}/").status_code == 404
    response = api.patch(f"/api/clients/{other_customer.pk}/", {"name": "Hijacked"})
    assert response.status_code == 404
    other_customer.refresh_from_db()
    assert other_customer.name == "Secret Client Pty Ltd"


# --- invoices ----------------------------------------------------------------


def test_create_invoice_with_lines_in_one_request(api, customer):
    response = api.post(
        "/api/invoices/",
        {
            "client": customer.pk,
            "issue_date": "2026-10-01",
            "lines": [
                {"description": "Advisory hours", "quantity": "7.5", "unit_price": "180.00"},
                {"description": "Travel", "quantity": "1", "unit_price": "85.50", "taxable": False},
            ],
        },
        format="json",
    )
    body = response.json()
    assert response.status_code == 201
    assert body["number"] == "INV-00001" and body["status"] == "draft"
    assert body["due_date"] == "2026-10-15"
    assert (body["subtotal"], body["gst"], body["total"]) == ("1435.50", "135.00", "1570.50")
    assert [line["gst_amount"] for line in body["lines"]] == ["135.00", "0.00"]


def test_invalid_line_rolls_back_the_whole_invoice(api, customer):
    response = api.post(
        "/api/invoices/",
        {
            "client": customer.pk,
            "lines": [{"description": "x", "quantity": "0", "unit_price": "1"}],
        },
        format="json",
    )
    assert response.status_code == 400
    assert not Invoice.objects.exists()


def test_totals_are_computed_by_the_server_not_the_client(api, customer):
    response = api.post(
        "/api/invoices/", {"client": customer.pk, "total": "1.00", "status": "paid"}, format="json"
    )
    assert response.status_code == 201
    assert (response.json()["total"], response.json()["status"]) == ("0.00", "draft")


def test_send_then_pay_in_full(api, org, customer):
    invoice = services.create_invoice(org, customer)
    api.post(
        f"/api/invoices/{invoice.pk}/lines/",
        {"description": "Review", "quantity": "1", "unit_price": "500"},
        format="json",
    )
    assert api.post(f"/api/invoices/{invoice.pk}/send/").json()["status"] == "sent"

    response = api.post(
        f"/api/invoices/{invoice.pk}/payments/", {"amount": "550.00", "reference": "EFT 1"}
    )
    assert response.status_code == 201
    assert (response.json()["status"], response.json()["balance"]) == ("paid", "0.00")


def test_business_rule_errors_are_400_with_a_message(api, org, customer, sent):
    empty = services.create_invoice(org, customer)
    response = api.post(f"/api/invoices/{empty.pk}/send/")
    assert response.status_code == 400
    assert response.json() == {"detail": ["Add at least one line with a value before sending."]}

    response = api.post(f"/api/invoices/{sent.pk}/payments/", {"amount": "5000"})
    assert response.status_code == 400
    assert "more than the balance owing ($1,100.00)" in response.json()["detail"][0]


def test_status_filter(api, sent, org, customer):
    services.create_invoice(org, customer)
    Invoice.objects.filter(pk=sent.pk).update(issue_date="2026-01-01", due_date="2026-01-15")

    def numbers(query):
        return [i["number"] for i in api.get(f"/api/invoices/?status={query}").json()["results"]]

    assert numbers("draft") == ["INV-00002"]
    assert numbers("overdue") == ["INV-00001"]
    assert numbers("paid") == []


# --- clients -----------------------------------------------------------------


def test_create_client(api, org):
    response = api.post(
        "/api/clients/", {"name": "Bayside Dental", "abn": "51 824 753 556"}, format="json"
    )
    assert response.status_code == 201
    client = Client.objects.get(name="Bayside Dental")
    assert (client.organization, client.abn) == (org, "51824753556")


@pytest.mark.parametrize(
    ("data", "field"),
    [({"name": "COASTAL BUILDERS"}, "name"), ({"name": "New Co", "abn": "12345678901"}, "abn")],
)
def test_invalid_client_is_400(api, customer, data, field):
    response = api.post("/api/clients/", data, format="json")
    assert response.status_code == 400
    assert field in response.json()


def test_browsable_api_renders_for_signed_in_users(client, user, sent):
    client.force_login(user)
    response = client.get("/api/invoices/", HTTP_ACCEPT="text/html")
    assert response.status_code == 200
    assert "INV-00001" in response.content.decode()
