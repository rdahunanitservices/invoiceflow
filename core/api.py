from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import BasePermission
from rest_framework.views import exception_handler as drf_exception_handler


def exception_handler(exc, context):
    """Business rules raise Django's ValidationError (see billing.services).
    Return those as a 400 with their user-safe messages instead of a 500."""
    if isinstance(exc, DjangoValidationError):
        exc = ValidationError({"detail": exc.messages})
    return drf_exception_handler(exc, context)


class HasOrganization(BasePermission):
    message = "This account isn't linked to an organisation."

    def has_permission(self, request, view):
        return getattr(request.user, "organization_id", None) is not None
