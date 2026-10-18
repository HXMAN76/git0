"""Merge check unit tests: plain git plus the static symbol and call checks. No DB, nothing is executed.

Each case is one of the demo's stories: a clean git merge that is semantically wrong (override), the same
merge after an adopt (safe), a signature change that breaks a call merge-induced (call mismatch), a call
already broken in one clone alone (own bug, still safe), and a real overlap that git itself refuses (git
conflict). These tests need the `git` binary, as the endpoint does.
"""

from pathlib import Path

import pytest

from git0.ide.mergecheck import analyze

DEMO = Path(__file__).resolve().parents[2] / "demo_project"
CART = "shop/cart.py"
PRICING = "shop/pricing.py"
CHECKOUT = "shop/checkout.py"

CART_BASE = (DEMO / CART).read_text(encoding="utf-8")
# A changes the signature (def line). B changes the return line, two lines below: non-adjacent, so git merges.
CART_A = CART_BASE.replace(
    "def calculate_total(items, discount_pct=0):", 'def calculate_total(items, discount_pct=0, region="US"):'
)
CART_B = CART_BASE.replace("    return apply_tax(discounted)", "    return apply_tax(discounted) + 5")

PRICING_BASE = "def apply_tax(amount):\n    return round(amount * 1.08, 2)\n"
PRICING_A = "def apply_tax(amount, region):\n    return round(amount * 1.08, 2)\n"
# A clone whose own calls are never judged: its signature takes anything.
PRICING_LOOSE = "def apply_tax(*args, **kwargs):\n    return round(args[0] * 1.08, 2)\n"
CHECKOUT_PLAIN = (
    "def checkout(items, user):\n"
    "    total = sum(item['price'] for item in items)\n"
    "    return {'user': user, 'total': total}\n"
)
CHECKOUT_CALLS = (
    "from shop.pricing import apply_tax\n\n\n"
    "def checkout(items, user):\n"
    "    total = sum(item['price'] for item in items)\n"
    "    return {'user': user, 'total': apply_tax(total)}\n"
)


def semantic_kinds(result: dict) -> list[str]:
    return [item["kind"] for f in result["files"] for item in f["semantic"]]


def file_entry(result: dict, path: str) -> dict:
    return next(f for f in result["files"] if f["path"] == path)


def test_override_case_git_clean_but_both_rewrote_the_same_function() -> None:
    result = analyze({CART: CART_A}, {CART: CART_B}, {CART: CART_BASE}, pulled=set())

    entry = file_entry(result, CART)
    assert entry["git"] == "clean" and entry["git_hunks"] == 0
    assert entry["base"] == "template"
    assert (
        "region" in entry["merged"] and "+ 5" in entry["merged"]
    )  # git kept both edits, so the merge is "clean"
    assert entry["semantic"] == [
        {
            "kind": "both_changed",
            "symbol": "shop/cart.py::calculate_total",
            "side": None,
            "message": (
                "Alice and Bob both rewrote calculate_total; git can only stitch lines together, "
                "so one person's logic may be lost or mixed."
            ),
        }
    ]
    assert result["verdict"]["status"] == "semantic_conflict"
    assert result["verdict"]["headline"] == "Git says CLEAN, but the code would be wrong"


def test_adopt_case_bob_built_on_alices_version_is_safe() -> None:
    # After B's adopt, the pulled base is A's version and A's clone still equals it; B's rework sits on top.
    result = analyze(
        {CART: CART_A},
        {CART: CART_A.replace("    return apply_tax(discounted)", "    return apply_tax(discounted) + 5")},
        {CART: CART_A},
        pulled={CART},
    )

    entry = file_entry(result, CART)
    assert entry["git"] == "clean"
    assert entry["base"] == "pulled"
    assert entry["semantic"] == []
    assert result["verdict"]["status"] == "safe"
    assert result["verdict"]["headline"] == "Safe to merge: Bob built on top of Alice's change"


def test_merge_induced_call_mismatch_alice_changed_signature_bob_added_old_call() -> None:
    # Alice changes apply_tax's signature; Bob adds a call with the old one-argument form. Neither clone is
    # broken on its own (Alice never calls it, Bob's pricing is still the old one), so the merge causes it.
    result = analyze(
        {PRICING: PRICING_A, CHECKOUT: CHECKOUT_PLAIN},
        {PRICING: PRICING_BASE, CHECKOUT: CHECKOUT_CALLS},
        {PRICING: PRICING_BASE, CHECKOUT: CHECKOUT_PLAIN},
        pulled=set(),
    )

    checkout = file_entry(result, CHECKOUT)
    assert checkout["git"] == "clean"
    assert checkout["semantic"] == [
        {
            "kind": "call_mismatch",
            "symbol": "shop/pricing.py::apply_tax",
            "side": None,
            "message": "checkout() calls apply_tax(total) but apply_tax takes (amount, region).",
        }
    ]
    assert file_entry(result, PRICING)["semantic"] == []
    assert result["verdict"]["status"] == "semantic_conflict"


def test_own_bug_only_bob_changed_signature_and_left_a_caller_is_safe() -> None:
    # Bob alone changes apply_tax to take region and never updates checkout(). The bug is already in his
    # clone, so the merge is safe, but the verdict names it.
    result = analyze(
        {PRICING: PRICING_BASE, CHECKOUT: CHECKOUT_CALLS},
        {PRICING: PRICING_A, CHECKOUT: CHECKOUT_CALLS},
        {PRICING: PRICING_BASE, CHECKOUT: CHECKOUT_CALLS},
        pulled=set(),
    )

    checkout = file_entry(result, CHECKOUT)
    assert checkout["semantic"] == [
        {
            "kind": "own_bug",
            "symbol": "shop/pricing.py::apply_tax",
            "side": "B",
            "message": (
                "Bob's own clone already has this bug (not caused by the merge): checkout() calls "
                "apply_tax(total) but apply_tax takes (amount, region)."
            ),
        }
    ]
    assert file_entry(result, PRICING)["semantic"] == []
    assert result["verdict"]["status"] == "safe"
    assert result["verdict"]["headline"] == "Safe to merge — but one clone has its own bug"
    assert "Bob's own clone already has this bug" in result["verdict"]["detail"]


@pytest.mark.parametrize(
    ("call", "problem"),
    [
        ("apply_tax(total, 'EU')", False),  # fits: region passed positionally
        ("apply_tax(total, region='EU')", False),  # fits: region passed by keyword
        ("apply_tax(total)", True),  # missing required region
        ("apply_tax(total, 'EU', 'x')", True),  # too many positional arguments
        ("apply_tax(total, zone='EU')", True),  # keyword the def does not take
        ("apply_tax(total, 'EU', region='EU')", True),  # region given twice
        ("apply_tax(*totals)", False),  # starred arguments are not judged
    ],
)
def test_call_arguments_are_checked_against_the_merged_signature(call: str, problem: bool) -> None:
    # Only Bob adds the call, and his clone's apply_tax accepts anything, so any mismatch is merge-induced.
    checkout = CHECKOUT_CALLS.replace("apply_tax(total)", call)
    result = analyze(
        {PRICING: PRICING_A, CHECKOUT: CHECKOUT_PLAIN},
        {PRICING: PRICING_LOOSE, CHECKOUT: checkout},
        {PRICING: PRICING_LOOSE, CHECKOUT: CHECKOUT_PLAIN},
        pulled=set(),
    )
    kinds = semantic_kinds(result)
    assert ("call_mismatch" in kinds) is problem
    assert "own_bug" not in kinds


def test_real_overlap_is_a_git_conflict() -> None:
    a = CART_BASE.replace("    return apply_tax(discounted)", "    return apply_tax(discounted) + 1")
    b = CART_BASE.replace("    return apply_tax(discounted)", "    return apply_tax(discounted) + 2")
    result = analyze({CART: a}, {CART: b}, {CART: CART_BASE}, pulled=set())

    entry = file_entry(result, CART)
    assert entry["git"] == "conflict" and entry["git_hunks"] >= 1
    assert "<<<<<<< A" in entry["merged"] and ">>>>>>> B" in entry["merged"]
    assert result["verdict"]["status"] == "git_conflict"
    assert result["verdict"]["headline"] == "Git would stop you with merge conflict markers"


def test_a_file_added_by_one_clone_has_an_empty_base_and_merges_cleanly() -> None:
    added = "def helper():\n    return 1\n"
    result = analyze({"shop/extra.py": added}, {}, {}, pulled=set())

    entry = file_entry(result, "shop/extra.py")
    assert entry["git"] == "clean" and entry["merged"] == added
    assert entry["semantic"] == []  # nothing on the other side to clash with
    assert result["verdict"]["status"] == "safe"


def test_nothing_changed_is_safe_with_nothing_to_merge() -> None:
    result = analyze({CART: CART_BASE}, {CART: CART_BASE}, {CART: CART_BASE}, pulled=set())
    assert result["files"] == []
    assert result["verdict"]["status"] == "safe"
    assert result["verdict"]["headline"] == "Nothing to merge: neither clone has changed"
