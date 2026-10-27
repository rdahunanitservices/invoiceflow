import pytest


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
