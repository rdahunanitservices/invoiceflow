"""One-click demo workspaces. Each visitor gets a private organisation with
sample data, so nobody sees or changes anyone else's demo. Workspaces older
than a day are purged whenever a new one is created; there's no cron to run."""

import secrets
from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from accounts.models import Organization, User
from billing import services
from billing.models import Client, Invoice, Payment

DEMO_LIFETIME = timedelta(days=1)
MAX_NEW_DEMOS_PER_HOUR = 30
ATO_EXAMPLE_ABN = "51824753556"  # the ATO's published example, not a real business


class DemoBusy(Exception):
    """Too many demo workspaces were created in the last hour."""


def purge_expired(now=None) -> int:
    """Delete demo organisations older than DEMO_LIFETIME. Children go first
    because invoices and payments are PROTECTed from cascading deletes."""
    cutoff = (now or timezone.now()) - DEMO_LIFETIME
    orgs = Organization.objects.filter(is_demo=True, created_at__lt=cutoff)
    with transaction.atomic():
        Payment.objects.filter(invoice__organization__in=orgs).delete()
        Invoice.objects.filter(organization__in=orgs).delete()
        Client.objects.filter(organization__in=orgs).delete()
        _, per_model = orgs.delete()  # users cascade
    return per_model.get(Organization._meta.label, 0)


@transaction.atomic
def create_workspace() -> User:
    """Create a demo organisation, its sample data, and a user who can only
    sign in through the demo button (no usable password)."""
    purge_expired()
    recent = Organization.objects.filter(
        is_demo=True, created_at__gte=timezone.now() - timedelta(hours=1)
    )
    if recent.count() >= MAX_NEW_DEMOS_PER_HOUR:
        raise DemoBusy

    org = Organization.objects.create(name="Harbour Advisory (demo)", is_demo=True)
    user = User(username=f"demo-{secrets.token_hex(5)}", organization=org)
    user.set_unusable_password()
    user.save()
    load_sample_data(org)
    return user


def load_sample_data(org) -> None:
    today = timezone.localdate()
    D = Decimal

    clients = {
        key: Client.objects.create(organization=org, **fields)
        for key, fields in {
            "coastal": {
                "name": "Coastal Builders Pty Ltd",
                "email": "accounts@coastalbuilders.example",
                "abn": ATO_EXAMPLE_ABN,
                "payment_terms_days": 14,
            },
            "bayside": {
                "name": "Bayside Dental Group",
                "email": "admin@baysidedental.example",
                "payment_terms_days": 30,
            },
            "northshore": {
                "name": "Northshore Logistics",
                "email": "ap@northshore.example",
                "payment_terms_days": 14,
            },
            "greenleaf": {"name": "Greenleaf Cafe Co.", "payment_terms_days": 7},
        }.items()
    }

    def invoice(client, days_ago, lines, send=True, paid=None, void=False):
        issued = today - timedelta(days=days_ago)
        inv = services.create_invoice(org, clients[client], issue_date=issued)
        for description, quantity, price, taxable in lines:
            services.add_line(inv, description, D(quantity), D(price), taxable)
        if send:
            services.mark_sent(inv)
        if paid:
            paid_on = min(issued + timedelta(days=10), today)
            services.record_payment(inv, D(paid), paid_on=paid_on, reference="EFT")
        if void:
            services.void_invoice(inv)

    invoice(
        "coastal",
        40,
        [
            ("Cash-flow review workshop", "1", "2400.00", True),
            ("Follow-up advisory hours", "6", "220.00", True),
        ],
        paid="3982.00",
    )
    invoice(
        "northshore",
        35,
        [
            ("Process mapping (2 days)", "2", "1650.00", True),
            ("Travel to Newcastle", "1", "180.50", False),
        ],
    )
    invoice("bayside", 20, [("Monthly advisory retainer", "1", "3000.00", True)], paid="1500.00")
    invoice("greenleaf", 12, [("Pricing review", "4", "180.00", True)])
    invoice("coastal", 9, [("Quarterly board report", "1", "1800.00", True)], paid="1980.00")
    invoice("northshore", 25, [("Cancelled engagement", "1", "500.00", True)], void=True)
    invoice("coastal", 2, [("Board pack preparation", "1", "1200.00", True)], send=False)
