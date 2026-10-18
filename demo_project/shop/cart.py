"""Cart math. calculate_total is the one place a cart total is computed."""

from shop.pricing import apply_discount, apply_tax


def subtotal(items):
    """Sum of price * qty over all line items."""
    return sum(item["price"] * item["qty"] for item in items)


def calculate_total(items, discount_pct=0):
    """Subtotal, then discount, then tax (tax is charged on the discounted amount)."""
    discounted = apply_discount(subtotal(items), discount_pct)
    return apply_tax(discounted)
