"""Parser and diff unit tests. No database: these run on plain strings and the demo_project folder."""

from pathlib import Path

import pytest

from git0.code.parse import diff_symbols, parse_file, parse_project

DEMO = Path(__file__).resolve().parents[2] / "demo_project"

PRICING = """
def apply_tax(amount):
    return amount * 1.08


def apply_discount(amount, pct):
    return amount * (1 - pct / 100)
"""


def by_id(symbols):
    return {s.id: s for s in symbols}


def demo_files() -> dict[str, str]:
    return {p.relative_to(DEMO).as_posix(): p.read_text() for p in DEMO.rglob("*.py")}


# ── symbols and signatures ───────────────────────────────────────────────────


def test_top_level_functions_are_symbols_with_path_qualified_ids():
    syms = by_id(parse_file("shop/pricing.py", PRICING))
    assert set(syms) == {"shop/pricing.py::apply_tax", "shop/pricing.py::apply_discount"}
    tax = syms["shop/pricing.py::apply_tax"]
    assert (tax.name, tax.path, tax.kind, tax.line, tax.end_line) == (
        "apply_tax",
        "shop/pricing.py",
        "function",
        2,
        3,
    )
    assert tax.signature == "def apply_tax(amount)"


def test_methods_get_class_qualname_and_method_kind():
    src = """
class Cart:
    def total(self):
        return self.subtotal()

    def subtotal(self):
        return 0
"""
    syms = by_id(parse_file("shop/cart.py", src))
    assert syms["shop/cart.py::Cart"].kind == "class"
    assert syms["shop/cart.py::Cart.total"].kind == "method"
    assert syms["shop/cart.py::Cart.total"].name == "total"
    # self.subtotal() inside a method resolves to the sibling method
    assert syms["shop/cart.py::Cart.total"].calls == ("shop/cart.py::Cart.subtotal",)


def test_class_hash_ignores_method_bodies_but_method_hash_does_not():
    before = "class Cart:\n    x = 1\n    def total(self):\n        return 1\n"
    after = "class Cart:\n    x = 1\n    def total(self):\n        return 2\n"
    a, b = by_id(parse_file("c.py", before)), by_id(parse_file("c.py", after))
    assert a["c.py::Cart"].body_hash == b["c.py::Cart"].body_hash
    assert a["c.py::Cart.total"].body_hash != b["c.py::Cart.total"].body_hash


def test_nested_function_calls_belong_to_the_enclosing_symbol():
    src = """
def outer():
    def inner():
        return helper()
    return inner()


def helper():
    return 1
"""
    syms = by_id(parse_file("m.py", src))
    assert set(syms) == {"m.py::outer", "m.py::helper"}
    assert syms["m.py::outer"].calls == ("m.py::helper",)


def test_signature_normalization_ignores_whitespace_and_comments():
    a = "def f(a,b = 1,*args,c:int=2,**kw):\n    return a\n"
    b = "def f(\n    a,  # first\n    b=1,\n    *args,\n    c: int = 2,\n    **kw,\n):\n    return a\n"
    sa, sb = parse_file("m.py", a)[0], parse_file("m.py", b)[0]
    assert sa.signature == sb.signature == "def f(a, b=..., *args, c: int=..., **kw)"
    assert sa.body_hash == sb.body_hash


def test_default_value_change_is_a_body_change_but_not_a_signature_change():
    old = parse_file("m.py", "def f(a, b=1):\n    return a + b\n")
    new = parse_file("m.py", "def f(a, b=2):\n    return a + b\n")
    d = diff_symbols(old, new)
    assert len(d.modified) == 1 and d.signature_changed == []


def test_async_and_return_annotation_are_part_of_the_signature():
    src = "async def f(x: int) -> str:\n    return ''\n"
    assert parse_file("m.py", src)[0].signature == "async def f(x: int) -> str"


def test_syntax_error_is_raised_not_swallowed():
    with pytest.raises(SyntaxError):
        parse_file("bad.py", "def broken(:\n")


def test_path_backslashes_are_normalized():
    syms = parse_file("shop\\pricing.py", "def f():\n    pass\n")
    assert syms[0].id == "shop/pricing.py::f"


# ── call resolution ──────────────────────────────────────────────────────────


def test_from_import_resolves_to_the_defining_module():
    src = "from shop.pricing import apply_tax\n\ndef total(x):\n    return apply_tax(x)\n"
    total = by_id(parse_file("shop/cart.py", src))["shop/cart.py::total"]
    assert total.calls == ("shop/pricing.py::apply_tax",)


def test_import_alias_then_attribute_call_resolves():
    src = "import shop.pricing as p\n\ndef total(x):\n    return p.apply_tax(x)\n"
    total = by_id(parse_file("shop/cart.py", src))["shop/cart.py::total"]
    assert total.calls == ("shop/pricing.py::apply_tax",)


def test_plain_package_import_resolves_full_dotted_call():
    src = "import shop.pricing\n\ndef total(x):\n    return shop.pricing.apply_tax(x)\n"
    total = by_id(parse_file("cart.py", src))["cart.py::total"]
    assert total.calls == ("shop/pricing.py::apply_tax",)


def test_from_package_import_module_then_attribute_call_resolves():
    src = "from shop import pricing\n\ndef total(x):\n    return pricing.apply_tax(x)\n"
    total = by_id(parse_file("checkout.py", src))["checkout.py::total"]
    assert total.calls == ("shop/pricing.py::apply_tax",)


def test_relative_import_resolves_against_the_file_package():
    src = "from .pricing import apply_tax\n\ndef total(x):\n    return apply_tax(x)\n"
    total = by_id(parse_file("shop/cart.py", src))["shop/cart.py::total"]
    assert total.calls == ("shop/pricing.py::apply_tax",)


def test_same_file_call_resolves_to_the_local_symbol():
    src = "def subtotal(x):\n    return x\n\ndef total(x):\n    return subtotal(x)\n"
    syms = by_id(parse_file("cart.py", src))
    assert syms["cart.py::total"].calls == ("cart.py::subtotal",)


def test_builtins_and_unknown_attribute_chains_are_dropped():
    src = "def f(x):\n    print(len(x))\n    x.append(1)\n    return sorted(x)\n"
    assert parse_file("m.py", src)[0].calls == ()


def test_stdlib_calls_are_dropped_without_a_project_index():
    src = "import json\n\ndef f(x):\n    return json.dumps(x)\n"
    assert parse_file("m.py", src)[0].calls == ()


def test_known_index_drops_calls_to_unknown_targets():
    src = "from shop.pricing import apply_tax, missing\n\ndef f(x):\n    return apply_tax(missing(x))\n"
    known = {"shop.pricing.apply_tax": "shop/pricing.py::apply_tax"}
    known["shop/pricing.py::apply_tax"] = "shop/pricing.py::apply_tax"
    assert parse_file("shop/cart.py", src, known)[0].calls == ("shop/pricing.py::apply_tax",)


def test_calls_are_deduplicated_and_self_calls_are_dropped():
    src = "def f(x):\n    return f(x) + f(x)\n"
    assert parse_file("m.py", src)[0].calls == ()


def test_parse_project_resolves_calls_across_files():
    syms = parse_project(
        {
            "shop/pricing.py": PRICING,
            "shop/cart.py": "from shop.pricing import apply_tax\n\ndef total(x):\n    return apply_tax(x)\n",
        }
    )
    total = by_id(syms["shop/cart.py"])["shop/cart.py::total"]
    assert total.calls == ("shop/pricing.py::apply_tax",)


def test_parse_project_ignores_non_python_files():
    syms = parse_project({"README.md": "# hi", "shop/pricing.py": PRICING})
    assert set(syms) == {"shop/pricing.py"}


# ── the demo project ─────────────────────────────────────────────────────────


def test_demo_project_calculate_total_calls_apply_tax():
    syms = by_id([s for group in parse_project(demo_files()).values() for s in group])
    calc = syms["shop/cart.py::calculate_total"]
    assert "shop/pricing.py::apply_tax" in calc.calls
    assert "shop/pricing.py::apply_discount" in calc.calls
    assert "shop/cart.py::subtotal" in calc.calls


def test_demo_project_checkout_calls_the_three_helpers():
    syms = by_id([s for group in parse_project(demo_files()).values() for s in group])
    assert set(syms["shop/checkout.py::checkout"].calls) == {
        "shop/inventory.py::reserve",
        "shop/cart.py::calculate_total",
        "shop/receipts.py::format_receipt",
    }


# ── diff ─────────────────────────────────────────────────────────────────────


def test_diff_detects_added_removed_modified_and_signature_change():
    old = parse_file("shop/pricing.py", PRICING)
    new_src = """
def apply_tax(amount, region):
    return amount * 1.08


def apply_discount(amount, pct):
    return amount * (1 - pct / 100)


def new_helper():
    return 1
"""
    d = diff_symbols(old, parse_file("shop/pricing.py", new_src))
    assert [s.id for s in d.added] == ["shop/pricing.py::new_helper"]
    assert d.removed == []
    assert [(o.id, n.id) for o, n in d.modified] == [
        ("shop/pricing.py::apply_tax", "shop/pricing.py::apply_tax")
    ]
    assert [n.signature for _, n in d.signature_changed] == ["def apply_tax(amount, region)"]


def test_diff_detects_removed_symbols():
    old = parse_file("shop/pricing.py", PRICING)
    d = diff_symbols(old, parse_file("shop/pricing.py", "def apply_tax(amount):\n    return amount\n"))
    assert [s.id for s in d.removed] == ["shop/pricing.py::apply_discount"]
    assert d.added == []


def test_diff_ignores_comment_only_changes():
    old = parse_file("m.py", "def f(x):\n    return x\n")
    d = diff_symbols(old, parse_file("m.py", "# new comment\ndef f(x):\n    # inline\n    return x\n"))
    assert d.added == [] and d.removed == [] and d.modified == [] and d.signature_changed == []


def test_diff_new_calls_come_from_added_and_modified_symbols_only():
    old = parse_file("shop/cart.py", "def total(x):\n    return x\n\ndef other(x):\n    return x\n")
    new_src = (
        "from shop.pricing import apply_tax\n\n"
        "def total(x):\n    return apply_tax(x)\n\n"
        "def other(x):\n    return x\n"
    )
    d = diff_symbols(old, parse_file("shop/cart.py", new_src))
    assert d.new_calls == {"shop/pricing.py::apply_tax"}


def test_diff_with_both_sides_empty_is_empty():
    d = diff_symbols([], [])
    assert d.added == [] and d.removed == [] and d.modified == [] and d.new_calls == set()
