"""Prices: tax and discounts. Kept tiny so the demo diffs read at a glance."""

TAX_RATE = 0.08


def apply_tax(amount):
    """Add the flat 8% sales tax."""
    return round(amount * (1 + TAX_RATE), 2)


def apply_discount(amount, pct):
    """Take `pct` percent off `amount`. pct=0 means no discount."""
    return amount * (1 - pct / 100)
