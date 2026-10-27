from django.core.exceptions import ValidationError

# ATO weighting for the ABN checksum:
# https://abr.business.gov.au/Help/AbnFormat
ABN_WEIGHTS = (10, 1, 3, 5, 7, 9, 11, 13, 15, 17, 19)


def normalize_abn(value: str) -> str:
    return "".join(value.split())


def validate_abn(value: str) -> None:
    """Reject anything that isn't a valid 11-digit Australian Business Number."""
    abn = normalize_abn(value)
    if len(abn) != 11 or not abn.isdigit():
        raise ValidationError("An ABN has 11 digits.", code="abn_format")
    digits = [int(d) for d in abn]
    digits[0] -= 1
    if sum(w * d for w, d in zip(ABN_WEIGHTS, digits, strict=True)) % 89:
        raise ValidationError("This isn't a valid ABN. Check the digits.", code="abn_checksum")
