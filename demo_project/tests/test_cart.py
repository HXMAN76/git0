from shop.cart import calculate_total, subtotal
from shop.checkout import checkout


def test_total_is_subtotal_then_discount_then_tax():
    items = [{"sku": "apple", "price": 10.0, "qty": 2}]
    assert subtotal(items) == 20.0
    # 20 -> 50% off -> 10 -> +8% tax
    assert calculate_total(items, discount_pct=50) == 10.8


def test_checkout_returns_total_and_receipt():
    items = [{"sku": "bread", "price": 4.0, "qty": 1}]
    result = checkout(items, user="ann")
    assert result["user"] == "ann"
    assert result["total"] == 4.32
    assert "TOTAL 4.32" in result["receipt"]
