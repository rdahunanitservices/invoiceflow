from datetime import timedelta
from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Count, F, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST

from . import services
from .forms import ClientForm, InvoiceForm, LineForm, PaymentForm
from .models import ZERO, Client, Invoice, LineItem, Payment
from .services import BillingError

UNPROCESSABLE = 422  # htmx is configured in base.html to swap 422 responses


def org_required(view):
    """Logged in and linked to an organisation. Passes the organisation in."""

    @login_required
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        org = request.user.organization
        if org is None:
            raise PermissionDenied("This account isn't linked to an organisation.")
        return view(request, org, *args, **kwargs)

    return wrapper


def _invoice(org, pk):
    # Another organisation's invoice is a 404, so ids reveal nothing.
    return get_object_or_404(Invoice.objects.for_org(org).select_related("client"), pk=pk)


@require_http_methods(["GET"])
@org_required
def dashboard(request, org):
    today = timezone.localdate()
    invoices = Invoice.objects.for_org(org)
    balance = Sum(F("total") - F("amount_paid"))
    outstanding = invoices.outstanding().aggregate(count=Count("id"), amount=balance)
    overdue = invoices.overdue(today).aggregate(count=Count("id"), amount=balance)
    paid_30 = Payment.objects.for_org(org).filter(paid_on__gt=today - timedelta(days=30))
    context = {
        "outstanding": outstanding,
        "overdue": overdue,
        "paid_last_30": paid_30.aggregate(amount=Sum("amount"))["amount"] or ZERO,
        "drafts": invoices.filter(status=Invoice.Status.DRAFT).count(),
        "overdue_invoices": invoices.overdue(today)
        .select_related("client")
        .order_by("due_date")[:5],
        "recent_invoices": invoices.select_related("client")[:5],
    }
    return render(request, "billing/dashboard.html", context)


@require_http_methods(["GET", "POST"])
@org_required
def client_list(request, org):
    form = ClientForm(request.POST or None, org=org)
    if request.method == "POST":
        if form.is_valid():
            client = form.save()
            if not request.htmx:
                messages.success(request, f"Added {client.name}.")
                return redirect("billing:client_list")
            form = ClientForm(org=org)  # fresh form after a successful add
        elif request.htmx:
            return render(
                request,
                "billing/partials/client_section.html",
                {"form": form, "clients": _clients(org)},
                status=UNPROCESSABLE,
            )
    template = "billing/partials/client_section.html" if request.htmx else "billing/clients.html"
    return render(request, template, {"form": form, "clients": _clients(org)})


def _clients(org):
    return Client.objects.for_org(org).annotate(invoice_count=Count("invoices"))


@require_http_methods(["GET"])
@org_required
def invoice_list(request, org):
    status = request.GET.get("status", "")
    invoices = Invoice.objects.for_org(org).select_related("client")
    if status == "overdue":
        invoices = invoices.overdue()
    elif status in Invoice.Status.values:
        invoices = invoices.filter(status=status)
    else:
        status = ""
    context = {"invoices": invoices, "status": status, "filters": _filters()}
    template = "billing/partials/invoice_table.html" if request.htmx else "billing/invoices.html"
    return render(request, template, context)


def _filters():
    return [("", "All"), *Invoice.Status.choices[:3], ("overdue", "Overdue"), ("void", "Void")]


@require_http_methods(["GET", "POST"])
@org_required
def invoice_create(request, org):
    form = InvoiceForm(request.POST or None, org=org, initial={"issue_date": timezone.localdate()})
    if request.method == "POST" and form.is_valid():
        try:
            invoice = services.create_invoice(org, **form.cleaned_data)
        except BillingError as error:
            form.add_error(None, error)
        else:
            return redirect(invoice_url(invoice))
    has_clients = Client.objects.for_org(org).exists()
    return render(request, "billing/invoice_form.html", {"form": form, "has_clients": has_clients})


def invoice_url(invoice):
    return reverse("billing:invoice_detail", args=[invoice.pk])


@require_http_methods(["GET"])
@org_required
def invoice_detail(request, org, pk):
    invoice = _invoice(org, pk)
    return render(request, "billing/invoice_detail.html", _body_context(invoice))


def _body_context(invoice, line_form=None, payment_form=None, error=None):
    return {
        "invoice": invoice,
        "lines": invoice.lines.all(),
        "payments": invoice.payments.all(),
        "line_form": line_form or LineForm(),
        "payment_form": payment_form
        or PaymentForm(initial={"amount": invoice.balance, "paid_on": timezone.localdate()}),
        "error": error,
    }


def _respond(request, invoice, status=200, **forms):
    """htmx gets the refreshed invoice body; a plain form post gets a redirect."""
    if not request.htmx:
        if status != 200 and forms.get("error"):
            messages.error(request, forms["error"])
        return redirect(invoice_url(invoice))
    invoice.refresh_from_db()
    return render(
        request,
        "billing/partials/invoice_body.html",
        _body_context(invoice, **forms),
        status=status,
    )


@require_POST
@org_required
def line_add(request, org, pk):
    invoice = _invoice(org, pk)
    form = LineForm(request.POST)
    if not form.is_valid():
        return _respond(request, invoice, UNPROCESSABLE, line_form=form)
    try:
        services.add_line(invoice, **form.cleaned_data)
    except BillingError as error:
        return _respond(request, invoice, UNPROCESSABLE, line_form=form, error=error.message)
    return _respond(request, invoice)


@require_POST
@org_required
def line_delete(request, org, pk, line_pk):
    invoice = _invoice(org, pk)
    line = get_object_or_404(LineItem, pk=line_pk, invoice=invoice)
    try:
        services.remove_line(line)
    except BillingError as error:
        return _respond(request, invoice, UNPROCESSABLE, error=error.message)
    return _respond(request, invoice)


@require_POST
@org_required
def invoice_send(request, org, pk):
    invoice = _invoice(org, pk)
    try:
        services.mark_sent(invoice)
    except BillingError as error:
        return _respond(request, invoice, UNPROCESSABLE, error=error.message)
    return _respond(request, invoice)


@require_POST
@org_required
def invoice_void(request, org, pk):
    invoice = _invoice(org, pk)
    try:
        services.void_invoice(invoice)
    except BillingError as error:
        return _respond(request, invoice, UNPROCESSABLE, error=error.message)
    return _respond(request, invoice)


@require_POST
@org_required
def payment_add(request, org, pk):
    invoice = _invoice(org, pk)
    form = PaymentForm(request.POST)
    if not form.is_valid():
        return _respond(request, invoice, UNPROCESSABLE, payment_form=form)
    try:
        services.record_payment(invoice, **form.cleaned_data)
    except BillingError as error:
        return _respond(request, invoice, UNPROCESSABLE, payment_form=form, error=error.message)
    return _respond(request, invoice)
