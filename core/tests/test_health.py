import pytest
from django.db import DatabaseError
from django.urls import reverse


@pytest.mark.django_db
def test_healthz_reports_ok_when_database_is_reachable(client):
    response = client.get(reverse("healthz"))

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.django_db
def test_healthz_hides_error_details_when_database_fails(client, monkeypatch):
    def broken_cursor(*args, **kwargs):
        raise DatabaseError("connection refused: password authentication failed")

    monkeypatch.setattr("core.views.connection.cursor", broken_cursor)

    response = client.get(reverse("healthz"))

    assert response.status_code == 503
    assert response.json() == {"status": "error"}


def test_healthz_rejects_post(client):
    assert client.post(reverse("healthz")).status_code == 405
