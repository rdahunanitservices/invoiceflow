import pytest


@pytest.fixture(autouse=True)
def plain_static_storage(settings):
    """Tests render templates without running collectstatic, so swap the
    manifest storage (which needs a manifest file) for the plain one."""
    settings.STORAGES = {
        **settings.STORAGES,
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
