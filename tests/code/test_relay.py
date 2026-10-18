"""CodeRelay integration tests. Needs a real FalkorDB (make db-up); each test gets a throwaway graph.

Not run on the machine that wrote it (no FalkorDB there), so these are the first thing to run once a DB is up.
"""

import uuid
from pathlib import Path

import pytest

from git0.code.relay import CodeRelay

DEMO = Path(__file__).resolve().parents[2] / "demo_project"
PRICING = "shop/pricing.py"
CART = "shop/cart.py"
CHECKOUT = "shop/checkout.py"
PRICING_NEW = (
    (DEMO / PRICING).read_text().replace("def apply_tax(amount):", 'def apply_tax(amount, region="US"):')
)
GIFT_CHECKOUT = '''"""Checkout: reserve stock, price the cart, build the receipt."""

from shop.cart import calculate_total
from shop.inventory import reserve
from shop.pricing import apply_tax
from shop.receipts import format_receipt


def checkout(items, user, gift_card=0):
    """Reserve stock, price the cart, and return the order summary for `user`."""
    reserve(items)
    total = apply_tax(calculate_total(items) - gift_card)
    return {"user": user, "total": total, "receipt": format_receipt(items, total)}
'''
CART_NEW = (
    (DEMO / CART)
    .read_text()
    .replace(
        "def calculate_total(items, discount_pct=0):",
        "def calculate_total(items, discount_pct=0, shipping=5):",
    )
)


def demo_files() -> dict[str, str]:
    return {p.relative_to(DEMO).as_posix(): p.read_text() for p in DEMO.rglob("*.py")}


def src(path: str) -> str:
    return (DEMO / path).read_text()


@pytest.fixture
async def relay(db):
    graph = db.select_graph(f"test_code_{uuid.uuid4().hex[:8]}")
    r = CodeRelay(graph)
    await r.seed(demo_files(), {"A": "Alice", "B": "Bob"})
    yield r
    await graph.delete()


async def test_seed_creates_symbols_calls_and_agents(relay):
    ids = await relay.symbol_ids()
    assert "shop/cart.py::calculate_total" in ids
    assert "shop/pricing.py::apply_tax" in ids
    view = await relay.view()
    labels = {n["label"] for n in view["nodes"]}
    assert {"File", "Symbol", "Agent"} <= labels
    link_types = {link["type"] for link in view["links"]}
    assert {"DEFINES", "CALLS"} <= link_types
    agent_labels = {n["id"]: n["props"].get("label") for n in view["nodes"] if n["label"] == "Agent"}
    assert agent_labels == {"A": "Alice", "B": "Bob"}


async def test_seed_is_idempotent(relay):
    before = await relay.symbol_ids()
    await relay.seed(demo_files(), {"A": "Alice", "B": "Bob"})
    assert await relay.symbol_ids() == before


async def test_same_symbol_conflict_blocks(relay):
    # A changes calculate_total in cart.py and records it
    await relay.record_edit("A", CART, src(CART), CART_NEW, summary="shipping")
    # B now wants to change the same function
    result = await relay.check_edit(
        "B", CART, src(CART), src(CART).replace("discount_pct=0", "discount_pct=5")
    )
    kinds = {c.kind for c in result.conflicts}
    assert "same_symbol" in kinds
    same = next(c for c in result.conflicts if c.kind == "same_symbol")
    assert same.severity == "block" and same.peer == "A" and same.symbol == "shop/cart.py::calculate_total"
    assert result.blocking


async def test_dependency_conflict_when_new_code_calls_a_changed_signature(relay):
    # A changes apply_tax's signature (adds region)
    await relay.record_edit("A", PRICING, src(PRICING), PRICING_NEW)
    # B's gift-card edit calls apply_tax from checkout.py
    result = await relay.check_edit("B", CHECKOUT, src(CHECKOUT), GIFT_CHECKOUT)
    dep = [c for c in result.conflicts if c.kind == "dependency"]
    assert len(dep) == 1
    c = dep[0]
    assert c.severity == "block" and c.peer == "A" and c.peer_change_id
    assert c.path == ["shop/checkout.py::checkout", "shop/pricing.py::apply_tax"]
    assert "changed signature" in c.peer_summary
    assert result.blocking


async def test_reverse_dependency_when_my_signature_change_breaks_peer_code(relay):
    # B already changed calculate_total (which calls apply_tax) and recorded it
    await relay.record_edit("B", CART, src(CART), CART_NEW)
    # A now changes apply_tax's signature; B's recorded code relies on the old one
    result = await relay.check_edit("A", PRICING, src(PRICING), PRICING_NEW)
    rev = [c for c in result.conflicts if c.kind == "reverse_dependency"]
    assert len(rev) == 1
    assert rev[0].severity == "block" and rev[0].peer == "B"
    assert rev[0].symbol == "shop/pricing.py::apply_tax"
    assert rev[0].path == ["shop/cart.py::calculate_total", "shop/pricing.py::apply_tax"]


async def test_no_conflict_when_nothing_overlaps(relay):
    await relay.record_edit("A", PRICING, src(PRICING), PRICING_NEW)
    result = await relay.check_edit("B", "shop/receipts.py", src("shop/receipts.py"), src("shop/receipts.py"))
    assert result.conflicts == [] and not result.blocking


async def test_intent_warns_but_does_not_block(relay):
    await relay.announce_intent("A", "add region tax", ["shop/cart.py::calculate_total"])
    result = await relay.check_edit("B", CART, src(CART), CART_NEW)
    intents = [c for c in result.conflicts if c.kind == "intent"]
    assert len(intents) == 1 and intents[0].severity == "warn"
    assert not result.blocking


async def test_a_new_intent_deactivates_the_previous_one(relay):
    await relay.announce_intent("A", "first", ["shop/cart.py::calculate_total"])
    await relay.announce_intent("A", "second", ["shop/cart.py::subtotal"])
    result = await relay.check_edit("B", CART, src(CART), CART_NEW)
    assert [c for c in result.conflicts if c.kind == "intent"] == []


async def test_acknowledge_clears_the_conflict(relay):
    rec = await relay.record_edit("A", CART, src(CART), CART_NEW)
    assert len(rec.change_ids) == 1
    before = await relay.check_edit("B", CART, src(CART), CART_NEW.replace("shipping=5", "shipping=6"))
    assert any(c.kind == "same_symbol" for c in before.conflicts)

    assert await relay.acknowledge("B", rec.change_ids) == 1
    after = await relay.check_edit("B", CART, src(CART), CART_NEW.replace("shipping=5", "shipping=6"))
    assert not any(c.kind == "same_symbol" for c in after.conflicts)


async def test_unseen_changes_lists_peer_changes_until_acknowledged(relay):
    rec = await relay.record_edit("A", PRICING, src(PRICING), PRICING_NEW)
    seen = await relay.unseen_changes("B")
    assert [n.change_id for n in seen] == rec.change_ids
    assert all(n.agent == "A" for n in seen)
    assert [n.kind for n in seen] == ["signature"]
    assert await relay.unseen_changes("A") == []  # own changes are never "unseen"

    await relay.acknowledge("B", rec.change_ids)
    assert await relay.unseen_changes("B") == []


async def test_record_edit_marks_removed_symbols_and_drops_their_defines(relay):
    removed_src = "def apply_tax(amount):\n    return amount\n"
    rec = await relay.record_edit("A", PRICING, src(PRICING), removed_src)
    assert "removed apply_discount" in rec.summary
    assert "shop/pricing.py::apply_discount" not in await relay.symbol_ids()


def link_set(view: dict) -> set[tuple[str, str, str]]:
    return {(link["source"], link["target"], link["type"]) for link in view["links"]}


async def test_record_conflicts_puts_conflict_nodes_in_the_graph(relay):
    rec = await relay.record_edit("A", CART, src(CART), CART_NEW)
    result = await relay.check_edit("B", CART, src(CART), CART_NEW.replace("shipping=5", "shipping=6"))
    assert result.blocking
    ids = await relay.record_conflicts("B", result.conflicts)
    assert len(ids) == len(result.conflicts)

    view = await relay.view()
    conflict_nodes = {n["id"]: n for n in view["nodes"] if n["label"] == "Conflict"}
    assert set(conflict_nodes) == set(ids)
    for n in conflict_nodes.values():
        assert n["props"]["agent"] == "B" and n["props"]["resolution"] == "pending"
        assert n["props"]["ts"] > 0 and n["props"]["message"]

    same = next(i for i, c in zip(ids, result.conflicts, strict=True) if c.kind == "same_symbol")
    links = link_set(view)
    assert ("B", same, "RAISED") in links
    assert (same, "shop/cart.py::calculate_total", "ON") in links
    peer_change = next(c.peer_change_id for c in result.conflicts if c.kind == "same_symbol")
    assert peer_change == rec.change_ids[0]
    assert (same, peer_change, "AGAINST") in links


async def test_intent_conflict_is_recorded_without_an_against_link(relay):
    await relay.announce_intent("A", "add region tax", ["shop/cart.py::calculate_total"])
    result = await relay.check_edit("B", CART, src(CART), CART_NEW)
    ids = await relay.record_conflicts("B", result.conflicts)
    assert len(ids) == 1 and result.conflicts[0].kind == "intent"

    links = link_set(await relay.view())
    assert (ids[0], "shop/cart.py::calculate_total", "ON") in links
    assert not any(src_id == ids[0] and kind == "AGAINST" for src_id, _, kind in links)


async def test_record_conflicts_with_nothing_writes_nothing(relay):
    assert await relay.record_conflicts("B", []) == []


async def test_resolve_conflicts_stores_the_human_choice(relay):
    await relay.record_edit("A", CART, src(CART), CART_NEW)
    result = await relay.check_edit("B", CART, src(CART), CART_NEW.replace("shipping=5", "shipping=6"))
    ids = await relay.record_conflicts("B", result.conflicts)

    assert await relay.resolve_conflicts(ids, "override") == len(ids)
    resolutions = {
        n["id"]: n["props"]["resolution"] for n in (await relay.view())["nodes"] if n["label"] == "Conflict"
    }
    assert set(resolutions.values()) == {"override"}

    assert await relay.resolve_conflicts([], "adopt") == 0
    with pytest.raises(ValueError):
        await relay.resolve_conflicts(ids, "maybe")
