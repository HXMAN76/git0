"""Plain-text receipts shown to the customer at the end of checkout."""


def format_receipt(items, total):
    """One line per item, then the total. Plain text so it prints anywhere."""
    lines = [f"{item['qty']} x {item['sku']} @ {item['price']:.2f}" for item in items]
    lines.append(f"TOTAL {total:.2f}")
    return "\n".join(lines)
