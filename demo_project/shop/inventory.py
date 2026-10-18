"""Stock levels. Reserving is all-or-nothing: if any line is short, nothing is taken."""

STOCK = {"apple": 10, "bread": 5, "milk": 3}


def reserve(items):
    """Take `qty` of each sku out of STOCK. Raises ValueError and changes nothing if any line is short."""
    for item in items:
        if STOCK.get(item["sku"], 0) < item["qty"]:
            raise ValueError(f"out of stock: {item['sku']}")
    for item in items:
        STOCK[item["sku"]] -= item["qty"]


def release(items):
    """Put reserved stock back (used when a checkout is cancelled)."""
    for item in items:
        STOCK[item["sku"]] = STOCK.get(item["sku"], 0) + item["qty"]
