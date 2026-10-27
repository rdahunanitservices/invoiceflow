from datetime import timedelta

from django.contrib.auth import authenticate
from django.urls import reverse
from django.utils import timezone

from accounts.models import Organization, User
from billing import services as billing
from billing.models import Client, Invoice, Payment
from demo import services


def test_start_creates_a_private_workspace_and_signs_in(client, db):
    response = client.post(reverse("demo:start"))

    assert response.status_code == 302
    assert response.url == reverse("billing:dashboard")
    user = User.objects.get()
    assert user.organization.is_demo
    assert not user.has_usable_password()
    assert Invoice.objects.for_org(user.organization).count() == 7

    dashboard = client.get(reverse("billing:dashboard")).content.decode()
    assert "Private demo workspace" in dashboard


def test_sample_data_covers_every_status(db):
    org = services.create_workspace().organization
    statuses = set(Invoice.objects.for_org(org).values_list("status", flat=True))
    assert statuses == {"draft", "sent", "paid", "void"}
    assert Invoice.objects.for_org(org).overdue().exists()


def test_each_visitor_gets_their_own_organisation(db):
    first, second = services.create_workspace(), services.create_workspace()
    assert first.organization != second.organization


def test_start_is_post_only(client, db):
    assert client.get(reverse("demo:start")).status_code == 405
    assert not User.objects.exists()


def test_demo_users_cannot_sign_in_with_a_password(db):
    user = services.create_workspace()
    assert authenticate(username=user.username, password="") is None


def test_purge_removes_expired_demos_and_everything_they_own(org, customer):
    old = services.create_workspace().organization
    fresh = services.create_workspace().organization
    Organization.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=2))
    real_invoice = billing.create_invoice(org, customer)

    assert services.purge_expired() == 1

    assert not Organization.objects.filter(pk=old.pk).exists()
    assert not User.objects.filter(organization_id=old.pk).exists()
    assert not Client.objects.filter(organization_id=old.pk).exists()
    assert not Payment.objects.filter(invoice__organization_id=old.pk).exists()
    assert Organization.objects.filter(pk=fresh.pk).exists()
    assert Invoice.objects.filter(pk=real_invoice.pk).exists()  # real orgs are never purged


def test_purge_never_touches_old_real_organisations(org):
    Organization.objects.filter(pk=org.pk).update(created_at=timezone.now() - timedelta(days=30))
    assert services.purge_expired() == 0
    assert Organization.objects.filter(pk=org.pk).exists()


def test_hourly_cap_turns_visitors_away_politely(client, db, monkeypatch):
    monkeypatch.setattr(services, "MAX_NEW_DEMOS_PER_HOUR", 2)
    services.create_workspace()
    services.create_workspace()

    response = client.post(reverse("demo:start"), follow=True)

    assert "The demo is busy" in response.content.decode()
    assert Organization.objects.filter(is_demo=True).count() == 2
