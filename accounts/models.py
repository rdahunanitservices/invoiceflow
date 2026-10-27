from django.contrib.auth.models import AbstractUser


class User(AbstractUser):
    """Custom user model from day one, so fields can be added later without a
    painful swap of AUTH_USER_MODEL."""
