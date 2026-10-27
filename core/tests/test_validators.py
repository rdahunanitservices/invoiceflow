import pytest
from django.core.exceptions import ValidationError

from core.validators import validate_abn


@pytest.mark.parametrize("abn", ["51824753556", "51 824 753 556", "53 004 085 616"])
def test_accepts_valid_abns(abn):
    validate_abn(abn)


@pytest.mark.parametrize(
    ("abn", "code"),
    [
        ("51824753557", "abn_checksum"),
        ("12345678901", "abn_checksum"),
        ("5182475355", "abn_format"),
        ("51824753556X", "abn_format"),
        ("", "abn_format"),
    ],
)
def test_rejects_invalid_abns(abn, code):
    with pytest.raises(ValidationError) as exc:
        validate_abn(abn)
    assert exc.value.code == code
