# shop (demo project)

A tiny Python shop used by the git0 relay IDE demo. Every function is short on purpose.

- `shop/pricing.py`: `apply_tax(amount)` (flat 8%) and `apply_discount(amount, pct)`
- `shop/cart.py`: `subtotal(items)` and `calculate_total(items, discount_pct=0)`
- `shop/inventory.py`: `STOCK`, `reserve(items)`, `release(items)`
- `shop/receipts.py`: `format_receipt(items, total)`
- `shop/checkout.py`: `checkout(items, user)` reserves stock, prices the cart, builds the receipt

`items` is a list of `{"sku": str, "price": float, "qty": int}`.

Run the tests with `python -m pytest -q` from this folder.
