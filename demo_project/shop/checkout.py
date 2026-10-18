"""Checkout: reserve stock, price the cart, build the receipt."""

from shop.cart import calculate_total
from shop.inventory import reserve
from shop.receipts import format_receipt


def checkout(items, user):
    """Reserve stock, price the cart, and return the order summary for `user`."""
    reserve(items)
    total = calculate_total(items)
    return {"user": user, "total": total, "receipt": format_receipt(items, total)}
