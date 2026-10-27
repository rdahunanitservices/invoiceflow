from django.contrib import messages
from django.contrib.auth import login
from django.shortcuts import redirect
from django.views.decorators.http import require_POST

from . import services


@require_POST
def start(request):
    """Create a private sample workspace and sign the visitor straight into it."""
    try:
        user = services.create_workspace()
    except services.DemoBusy:
        messages.error(request, "The demo is busy right now. Please try again in a few minutes.")
        return redirect("login")
    login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    request.session.set_expiry(services.DEMO_LIFETIME)
    return redirect("billing:dashboard")
