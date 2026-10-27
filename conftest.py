import pytest

from accounts.models import Organization, User
from billing.models import Client


@pytest.fixture(autouse=True)
def plain_static_storage(settings):
    """Tests render templates without running collectstatic, so swap the
    manifest storage (which needs a manifest file) for the plain one."""
    settings.STORAGES = {
        **settings.STORAGES,
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }


@pytest.fixture(autouse=True)
def plain_http_test_client(settings):
    """CI runs with production settings, where SECURE_SSL_REDIRECT would bounce
    every test request to https://. Keep tests the same in every environment."""
    settings.SECURE_SSL_REDIRECT = False


@pytest.fixture(autouse=True)
def fast_password_hashing(settings):
    """Real hashers are slow on purpose; tests don't need that."""
    settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]


@pytest.fixture
def org(db):
    return Organization.objects.create(name="Harbour Advisory")


@pytest.fixture
def other_org(db):
    return Organization.objects.create(name="Rival Consulting")


@pytest.fixture
def user(org):
    return User.objects.create_user("alex", password="correct-horse-battery", organization=org)


@pytest.fixture
def other_user(other_org):
    return User.objects.create_user("sam", password="correct-horse-battery", organization=other_org)


@pytest.fixture
def customer(org):
    return Client.objects.create(organization=org, name="Coastal Builders", payment_terms_days=14)


@pytest.fixture
def other_customer(other_org):
    return Client.objects.create(organization=other_org, name="Secret Client Pty Ltd")
