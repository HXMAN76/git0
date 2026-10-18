"""Merge check for the IDE demo: what plain git says, and what the code says, about A's and B's clones.

Why two layers: `git merge-file` is line-based. Two people rewriting the same function on different lines
merge CLEAN and can still mix their logic, so git alone calls a broken result safe. The symbol and call checks
here catch what git cannot see. Static analysis only: the agents' code is parsed with `ast`, never run.
"""

from __future__ import annotations

import ast
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from git0.code.parse import EditDiff, call_sites, definitions, diff_symbols, parse_file, project_index

LABELS = {"A": "Alice", "B": "Bob"}
SKIP_DIRS = {".git", "__pycache__"}


class GitUnavailable(RuntimeError):
    """`git` is not on PATH, so `git merge-file` cannot run (the API maps this to 501)."""


class MergeToolError(RuntimeError):
    """`git merge-file` failed for a reason other than a conflict. Loud: we never guess a merge result."""


def run(workspaces: dict[str, Path], pull_base: dict[str, bytes], template: Path) -> dict[str, Any]:
    """Read both clones, the template and any pulled versions, then analyse. Does blocking file and git work:
    call it through asyncio.to_thread."""
    if shutil.which("git") is None:
        raise GitUnavailable("git is not installed on this server: merge-check needs `git merge-file`")
    ours = _read_tree(workspaces["A"])
    theirs = _read_tree(workspaces["B"])
    tpl = _read_tree(template)
    pulled = {rel: data.decode("utf-8", "replace") for rel, data in pull_base.items()}
    # Base = the pulled version when one exists (after an adopt, the clones share it), else the template.
    base = {rel: pulled[rel] if rel in pulled else tpl[rel] for rel in set(tpl) | set(pulled)}
    return analyze(ours, theirs, base, set(pulled))


def analyze(
    ours: dict[str, str], theirs: dict[str, str], base: dict[str, str], pulled: set[str]
) -> dict[str, Any]:
    """The contract: {files: [...], verdict: {...}}. Pure except for the `git merge-file` subprocess.

    `base` lacks a path when neither the template nor a pull has it: the file was added by a clone, so its
    base is "". A file present in only one clone takes the base on the other side, which makes it "unchanged"
    there, so the add is merged cleanly.
    """
    entries: dict[str, dict[str, Any]] = {}
    tree: dict[str, str] = {}  # the merged project, for the call check
    a_changed: set[str] = set()
    b_changed: set[str] = set()
    for rel in sorted(set(ours) | set(theirs) | set(base)):
        bs = base.get(rel, "")
        a = ours.get(rel, bs)
        b = theirs.get(rel, bs)
        if a != bs:
            a_changed.add(rel)
        if b != bs:
            b_changed.add(rel)
        if a == bs and b == bs:
            tree[rel] = bs
            continue
        status, hunks, merged = _git_merge(a, bs, b)
        entries[rel] = _entry(rel, status, hunks, merged, pulled, _semantic(rel, a, bs, b))
        if status == "clean":
            tree[rel] = (
                merged  # a conflicted file has no single merged text, so it stays out of the call check
            )

    # A call broken in the merged tree is merge-induced only if neither clone already had it on its own.
    own = {who: {key for _, key, _ in _call_check(t)} for who, t in (("A", ours), ("B", theirs))}
    by_file: dict[str, list[dict[str, Any]]] = {}
    for rel, key, item in _call_check(tree):
        if item["kind"] == "call_mismatch" and (key in own["A"] or key in own["B"]):
            for who in ("A", "B"):
                if key in own[who]:
                    by_file.setdefault(rel, []).append(_own_bug(who, item))
        else:
            by_file.setdefault(rel, []).append(item)

    for rel, items in by_file.items():
        if rel not in entries:  # an unchanged file that calls a function a teammate changed: still reported
            entries[rel] = _entry(rel, "clean", 0, tree[rel], pulled, [])
        existing = entries[rel]["semantic"]
        for item in items:
            # A file whose own side already fails to parse needs no second syntax report for the same file.
            if item["kind"] == "syntax_error" and any(e["kind"] == "syntax_error" for e in existing):
                continue
            existing.append(item)

    files = [entries[p] for p in sorted(entries)]
    return {
        "files": files,
        "verdict": _verdict(files, bool(a_changed), bool(b_changed), bool(pulled)),
    }


# ── git ──────────────────────────────────────────────────────────────────────


def _git_merge(ours: str, base: str, theirs: str) -> tuple[str, int, str]:
    """`git merge-file -p --diff3 A base B`. Exit code = number of conflict hunks (0 is clean)."""
    with tempfile.TemporaryDirectory(prefix="git0-merge-") as tmp:
        paths = {}
        for name, text in (("a", ours), ("base", base), ("b", theirs)):
            p = Path(tmp) / name
            p.write_bytes(text.encode("utf-8"))  # bytes, not text mode: no CRLF translation on Windows
            paths[name] = str(p)
        proc = subprocess.run(
            [
                "git",
                "merge-file",
                "-p",
                "--diff3",
                "-L",
                "A",
                "-L",
                "base",
                "-L",
                "B",
                paths["a"],
                paths["base"],
                paths["b"],
            ],
            capture_output=True,
            check=False,
        )
    # git reports real errors as 255 or as a negative code; a conflict count stays small.
    if proc.returncode < 0 or proc.returncode >= 128:
        raise MergeToolError(f"git merge-file failed: {proc.stderr.decode(errors='replace').strip()}")
    merged = proc.stdout.decode("utf-8", "replace")
    if proc.returncode == 0:
        return "clean", 0, merged
    return "conflict", proc.returncode, merged


# ── semantic checks on the two sides ─────────────────────────────────────────


def _semantic(rel: str, ours: str, base: str, theirs: str) -> list[dict[str, Any]]:
    if not rel.endswith(".py"):
        return []
    try:
        base_syms = parse_file(rel, base)
    except SyntaxError as exc:
        return [_syntax_item(f"The base version of {rel}", rel, exc)]
    sides: dict[str, list] = {}
    for who, text in (("A", ours), ("B", theirs)):
        try:
            sides[who] = parse_file(rel, text)
        except SyntaxError as exc:
            return [_syntax_item(f"{LABELS[who]}'s version of {rel}", rel, exc)]

    ta = _touch_map(diff_symbols(base_syms, sides["A"]))
    tb = _touch_map(diff_symbols(base_syms, sides["B"]))
    out: list[dict[str, Any]] = []
    for sid in sorted(set(ta) & set(tb)):
        if ta[sid] == tb[sid]:  # both made the identical edit (or both removed it): nothing gets mixed
            continue
        verb = "rewrote" if ta[sid] and tb[sid] else "changed"
        name = sid.split("::", 1)[1]
        out.append(
            {
                "kind": "both_changed",
                "symbol": sid,
                "side": None,
                "message": (
                    f"{LABELS['A']} and {LABELS['B']} both {verb} {name}; git can only stitch lines "
                    "together, so one person's logic may be lost or mixed."
                ),
            }
        )
    return out


def _touch_map(diff: EditDiff) -> dict[str, str | None]:
    """symbol id -> its new body_hash, or None when this side removed it. Only touched symbols appear."""
    out: dict[str, str | None] = {s.id: s.body_hash for s in diff.added}
    out.update({new.id: new.body_hash for _, new in diff.modified})
    out.update({s.id: None for s in diff.removed})
    return out


def _syntax_item(what: str, rel: str, exc: SyntaxError) -> dict[str, Any]:
    return {
        "kind": "syntax_error",
        "symbol": rel,
        "side": None,
        "message": f"{what} does not parse (line {exc.lineno}): {exc.msg}.",
    }


def _own_bug(who: str, item: dict[str, Any]) -> dict[str, Any]:
    """A broken call that already exists in one clone alone: the merge did not cause it."""
    return {
        "kind": "own_bug",
        "symbol": item["symbol"],
        "side": who,
        "message": (
            f"{LABELS[who]}'s own clone already has this bug (not caused by the merge): {item['message']}"
        ),
    }


# ── call check on one tree ───────────────────────────────────────────────────


def _call_check(tree: dict[str, str]) -> list[tuple[str, tuple, dict[str, Any]]]:
    """Every call whose arguments do not fit the callee's parameters, as (file, identity, item).
    The identity (file, caller, callee, arguments) lets the same call be found in another tree.
    Syntax errors come back too."""
    out: list[tuple[str, tuple, dict[str, Any]]] = []
    parsed: dict[str, str] = {}
    for rel, src in tree.items():
        if not rel.endswith(".py"):
            continue
        try:
            ast.parse(src, filename=rel)
        except SyntaxError as exc:
            out.append((rel, ("syntax", rel), _syntax_item(f"The merged {rel}", rel, exc)))
            continue
        parsed[rel] = src

    known = project_index(parsed)
    defs: dict[str, tuple[ast.FunctionDef | ast.AsyncFunctionDef, bool]] = {}
    for rel, src in parsed.items():
        defs.update(definitions(rel, src))
    for rel, src in parsed.items():
        for site in call_sites(rel, src, known):
            if site.callee not in defs:
                continue
            fn, is_method = defs[site.callee]
            if not _arguments_mismatch(fn, is_method, site.call):
                continue
            caller = site.caller.split("::", 1)[1]
            callee = site.callee.split("::", 1)[1]
            args = _call_args_text(site.call)
            params = _params_text(fn, is_method)
            item = {
                "kind": "call_mismatch",
                "symbol": site.callee,
                "side": None,
                "message": f"{caller}() calls {callee}({args}) but {callee} takes ({params}).",
            }
            out.append((rel, (rel, site.caller, site.callee, args), item))
    return out


def _arguments_mismatch(fn: ast.FunctionDef | ast.AsyncFunctionDef, is_method: bool, call: ast.Call) -> bool:
    """True when the call cannot bind to the def: too many positionals, a missing required argument, a
    keyword the def does not take, or one given twice. Calls with *args or **kwargs are not judged."""
    if fn.decorator_list:  # a decorator can change the real signature, so the def text is not the contract
        return False
    if any(isinstance(a, ast.Starred) for a in call.args) or any(k.arg is None for k in call.keywords):
        return False
    positional, kwonly, vararg, kwarg = _params(fn, is_method)
    names = [n for n, _ in positional]
    kwnames = [n for n, _ in kwonly]
    if len(call.args) > len(positional) and vararg is None:
        return True
    bound = set(names[: len(call.args)])
    for kw in call.keywords:
        if kw.arg in bound:
            return True  # given twice
        if kw.arg in names or kw.arg in kwnames:
            bound.add(kw.arg)
        elif kwarg is None:
            return True  # unknown keyword
    required = [n for n, default in [*positional, *kwonly] if default is None]
    return any(name not in bound for name in required)


def _params(fn: ast.FunctionDef | ast.AsyncFunctionDef, is_method: bool):
    """(positional [(name, default|None)], kwonly, vararg, kwarg). A method's self is bound by the call."""
    a = fn.args
    full = [*a.posonlyargs, *a.args]
    defaults: list[ast.expr | None] = [None] * (len(full) - len(a.defaults)) + list(a.defaults)
    if is_method and full:
        full, defaults = full[1:], defaults[1:]
    positional = [(p.arg, d) for p, d in zip(full, defaults, strict=True)]
    kwonly = [(p.arg, d) for p, d in zip(a.kwonlyargs, a.kw_defaults, strict=True)]
    return positional, kwonly, a.vararg, a.kwarg


def _params_text(fn: ast.FunctionDef | ast.AsyncFunctionDef, is_method: bool) -> str:
    """'items, discount_pct=0, region='US'' as the message shows it."""
    positional, kwonly, vararg, kwarg = _params(fn, is_method)
    parts = [n if d is None else f"{n}={ast.unparse(d)}" for n, d in positional]
    if vararg is not None:
        parts.append(f"*{vararg.arg}")
    elif kwonly:
        parts.append("*")
    parts += [n if d is None else f"{n}={ast.unparse(d)}" for n, d in kwonly]
    if kwarg is not None:
        parts.append(f"**{kwarg.arg}")
    return ", ".join(parts)


def _call_args_text(call: ast.Call) -> str:
    parts = [ast.unparse(a) for a in call.args]
    parts += [f"{k.arg}={ast.unparse(k.value)}" for k in call.keywords]
    return ", ".join(parts)


# ── verdict ──────────────────────────────────────────────────────────────────


def _verdict(files: list[dict[str, Any]], a_any: bool, b_any: bool, has_pull: bool) -> dict[str, str]:
    conflicted = [f["path"] for f in files if f["git"] == "conflict"]
    if conflicted:
        return {
            "status": "git_conflict",
            "headline": "Git would stop you with merge conflict markers",
            "detail": (
                f"Both people edited the same lines of {', '.join(conflicted)}, so git cannot pick one "
                "version without a human."
            ),
        }
    problems = [item for f in files for item in f["semantic"] if item["kind"] != "own_bug"]
    if problems:
        more = len(problems) - 1
        detail = problems[0]["message"] + (f" {more} more problem(s) found." if more else "")
        return {
            "status": "semantic_conflict",
            "headline": "Git says CLEAN, but the code would be wrong",
            "detail": detail,
        }
    if not a_any and not b_any:
        return {
            "status": "safe",
            "headline": "Nothing to merge: neither clone has changed",
            "detail": "Both clones still match the base, so there is nothing to combine.",
        }
    own_bugs = [item for f in files for item in f["semantic"] if item["kind"] == "own_bug"]
    if own_bugs:
        # Not the merge's fault, so the merge is still safe; the bug is named so someone fixes that clone.
        more = len(own_bugs) - 1
        detail = own_bugs[0]["message"] + (f" {more} more problem(s) found." if more else "")
        return {
            "status": "safe",
            "headline": "Safe to merge — but one clone has its own bug",
            "detail": detail,
        }
    if has_pull and a_any != b_any:
        # The side that did not change still holds the peer's version that was pulled, so the other side
        # built on top of it.
        who, other = ("Bob", "Alice") if b_any else ("Alice", "Bob")
        headline = f"Safe to merge: {who} built on top of {other}'s change"
    else:
        headline = "Safe to merge: the two sets of changes do not clash"
    return {
        "status": "safe",
        "headline": headline,
        "detail": (
            "Git merged every file cleanly, no function was rewritten by both sides, and every call "
            "matches its definition."
        ),
    }


# ── helpers ──────────────────────────────────────────────────────────────────


def _entry(
    rel: str, status: str, hunks: int, merged: str, pulled: set[str], semantic: list[dict[str, Any]]
) -> dict[str, Any]:
    return {
        "path": rel,
        "git": status,
        "git_hunks": hunks,
        "merged": merged,
        "base": "pulled" if rel in pulled else "template",
        "semantic": semantic,
    }


def _read_tree(root: Path) -> dict[str, str]:
    """Every file under `root` as {repo-relative posix path: text}. Reads only; nothing is executed."""
    out: dict[str, str] = {}
    if not root.is_dir():
        return out
    for p in root.rglob("*"):
        rel = p.relative_to(root)
        if not p.is_file() or SKIP_DIRS & set(rel.parts):
            continue
        out[rel.as_posix()] = p.read_bytes().decode("utf-8", "replace")
    return out
