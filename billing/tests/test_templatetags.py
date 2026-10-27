from decimal import Decimal

import pytest

from billing.templatetags.billing_tags import abn, aud


@pytest.mark.parametrize(
    ("value", "expected"),
    [(Decimal("1234.5"), "$1,234.50"), (Decimal("0"), "$0.00"), (None, "$0.00"), (5, "$5.00")],
)
def test_aud(value, expected):
    assert aud(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("51824753556", "51 824 753 556"),
        ("51 824 753 556", "51 824 753 556"),
        ("", ""),
        ("123", "123"),
    ],
)
def test_abn(value, expected):
    assert abn(value) == expected
