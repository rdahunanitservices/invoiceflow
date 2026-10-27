from decimal import Decimal

from django import template

register = template.Library()


@register.filter
def aud(value) -> str:
    """Format an amount as Australian dollars: 1234.5 -> $1,234.50."""
    return f"${Decimal(value or 0):,.2f}"


@register.filter
def abn(value) -> str:
    """Group an 11-digit ABN the way the ATO prints it: 51 824 753 556."""
    digits = "".join(str(value or "").split())
    if len(digits) != 11:
        return digits
    return f"{digits[:2]} {digits[2:5]} {digits[5:8]} {digits[8:]}"
