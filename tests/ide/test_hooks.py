"""Hook decision mapping (pure: a fake CheckResult in, HookDecision out) and MCP result parsing."""

from mcp_types import CallToolResult, TextContent

from git0.code.relay import CheckResult, ConflictInfo
from git0.ide.hooks import decide_write, describe_notice, tool_payload


def conflict(severity: str, kind: str = "same_symbol", peer_change_id: str | None = "c1") -> ConflictInfo:
    return ConflictInfo(
        kind=kind,
        severity=severity,
        symbol="shop/cart.py::calculate_total",
        peer="A",
        peer_change_id=peer_change_id,
        peer_summary="A changed signature: calculate_total(items) -> calculate_total(items, region)",
        path=["shop/cart.py::calculate_total"],
        message="Alice already changed calculate_total in shop/cart.py.",
    )


def test_no_conflicts_allows() -> None:
    decision = decide_write(CheckResult(conflicts=[], touched=["shop/cart.py::calculate_total"]))
    assert decision.action == "allow"
    assert decision.conflicts == []


def test_intent_only_warning_is_context_not_deny() -> None:
    warn = conflict("warn", kind="intent", peer_change_id=None)
    decision = decide_write(CheckResult(conflicts=[warn], touched=["shop/cart.py::calculate_total"]))
    assert decision.action == "context"
    assert "already changed" in decision.message
    assert decision.conflicts == []  # warnings do not open the human question


def test_blocking_conflict_is_deny_with_dumps() -> None:
    block = conflict("block")
    decision = decide_write(CheckResult(conflicts=[block], touched=["shop/cart.py::calculate_total"]))
    assert decision.action == "deny"
    assert decision.message == block.message
    assert decision.conflicts[0]["peer_change_id"] == "c1"
    assert decision.conflicts[0]["kind"] == "same_symbol"


def test_mixed_conflicts_deny_and_keep_all_in_the_list() -> None:
    decision = decide_write(
        CheckResult(
            conflicts=[conflict("warn", kind="intent", peer_change_id=None), conflict("block")], touched=[]
        )
    )
    assert decision.action == "deny"
    assert len(decision.conflicts) == 2
    assert decision.message == conflict("block").message  # the question only quotes the blocking message


def test_tool_payload_reads_structured_and_wrapped_results() -> None:
    wrapped = CallToolResult(content=[], structured_content={"result": [{"change_id": "x"}]})
    assert tool_payload(wrapped) == [{"change_id": "x"}]
    plain = CallToolResult(content=[], structured_content={"conflicts": [], "touched": []})
    assert tool_payload(plain) == {"conflicts": [], "touched": []}
    as_text = CallToolResult(content=[TextContent(type="text", text='{"ok": 1}')])
    assert tool_payload(as_text) == {"ok": 1}


def test_describe_notice_reads_as_a_heads_up() -> None:
    notice = {"agent": "A", "symbol": "shop/pricing.py::apply_tax", "summary": "signature changed", "ts": 0}
    text = describe_notice(notice, now_ms=40_000)
    assert text == "Heads-up: A changed shop/pricing.py::apply_tax (signature changed), 40s ago."
