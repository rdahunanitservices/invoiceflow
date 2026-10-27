from django.contrib.auth.models import AbstractUser
from django.db import models

from core.validators import validate_abn


class Organization(models.Model):
    """A business using InvoiceFlow. Every business record belongs to one."""

    name = models.CharField(max_length=200)
    abn = models.CharField("ABN", max_length=14, blank=True, validators=[validate_abn])
    # Allocated under a row lock in billing.services.create_invoice.
    next_invoice_number = models.PositiveIntegerField(default=1, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class User(AbstractUser):
    """Custom user model from day one, so fields can be added later without a
    painful swap of AUTH_USER_MODEL."""

    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="members",
        null=True,
        blank=True,
        help_text="Empty only for platform staff accounts.",
    )
