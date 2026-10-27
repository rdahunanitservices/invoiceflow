from concurrent.futures import ThreadPoolExecutor

import pytest
from django.db import connection

from billing import services


@pytest.mark.django_db(transaction=True)
def test_parallel_invoice_creation_never_duplicates_numbers(org, customer):
    if connection.vendor != "postgresql":
        pytest.skip("Row locks need PostgreSQL; SQLite serialises writes anyway.")

    def create(_):
        try:
            return services.create_invoice(org, customer).number
        finally:
            connection.close()  # each thread has its own connection

    with ThreadPoolExecutor(max_workers=8) as pool:
        numbers = list(pool.map(create, range(16)))

    assert sorted(numbers) == list(range(1, 17))
