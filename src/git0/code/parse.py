"""Python source -> code symbols and call edges, stdlib `ast` only, for the IDE's code-context graph.

Why so shallow: the graph only has to answer "does this edit call that function, or change its contract?".
So a call resolves through imports, same-file names and `self.method`, and nothing else. Unresolvable calls
(builtins, attribute chains on unknown objects, stdlib) are dropped.

Symbol ids are "<path>::<qualname>", e.g. "shop/cart.py::calculate_total"; methods are "Class.method".
"""

from __future__ import annotations

import ast
import copy
import hashlib
import sys
from dataclasses import dataclass

_FUNC = (ast.FunctionDef, ast.AsyncFunctionDef)
_DEF = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


@dataclass(frozen=True)
class SymbolInfo:
    id: str
    name: str
    path: str
    kind: str  # function | class | method
    signature: str  # normalized "def name(args)"; annotations kept, defaults shown as "..."
    body_hash: str  # sha1 of ast.dump: ignores comments and formatting
    line: int
    end_line: int
    calls: tuple[str, ...]  # resolved symbol ids this symbol calls (self-calls dropped)


def parse_file(path: str, source: str, known: dict[str, str] | None = None) -> list[SymbolInfo]:
    """Symbols of one file. Raises SyntaxError on bad source; the caller decides what to do.

    `known` maps dotted names ("shop.pricing.apply_tax") and/or ids to symbol ids. When given, only calls
    that land on a known id are kept. When None, imports resolve optimistically (any non-stdlib dotted name
    becomes an id); the graph MATCH then drops the ones that do not exist.
    """
    path = _norm(path)
    tree = ast.parse(source, filename=path)
    local = {qual for _, qual, _, _ in _walk_defs(tree.body, "", False)}
    aliases = _import_aliases(tree, path)
    ids = set(known.values()) if known is not None else None
    out: list[SymbolInfo] = []
    for node, qual, kind, owner in _walk_defs(tree.body, "", False):
        ident = f"{path}::{qual}"
        calls: list[str] = []
        for call in _calls_in(node):
            target = _resolve_call(call.func, path, owner, local, aliases, known, ids)
            if target and target != ident and target not in calls:
                calls.append(target)
        out.append(
            SymbolInfo(
                id=ident,
                name=node.name,
                path=path,
                kind=kind,
                signature=_signature(node),
                body_hash=_body_hash(node),
                line=node.lineno,
                end_line=node.end_lineno or node.lineno,
                calls=tuple(calls),
            )
        )
    return out


def project_index(files: dict[str, str]) -> dict[str, str]:
    """Dotted names and ids of every project def -> symbol id (the `known` argument of parse_file)."""
    known: dict[str, str] = {}
    for raw, src in files.items():
        path = _norm(raw)
        if not path.endswith(".py"):
            continue
        for _, qual, _, _ in _walk_defs(ast.parse(src).body, "", False):
            ident = f"{path}::{qual}"
            known[ident] = ident
            known[f"{_dotted(path)}.{qual}"] = ident
    return known


def parse_project(files: dict[str, str]) -> dict[str, list[SymbolInfo]]:
    """Parse every *.py in `files` ({path: source}). Two passes so calls resolve across files."""
    py = {_norm(p): src for p, src in files.items() if _norm(p).endswith(".py")}
    known = project_index(py)
    return {path: parse_file(path, src, known) for path, src in py.items()}


@dataclass(frozen=True)
class CallSite:
    caller: str  # symbol id whose body holds the call
    callee: str  # project symbol id the call resolves to
    call: ast.Call  # the AST node, so the caller can check its arguments


def call_sites(path: str, source: str, known: dict[str, str]) -> list[CallSite]:
    """Every call in one file that resolves to a project symbol, with its AST node.

    Why a separate function from parse_file: SymbolInfo.calls keeps only target ids, but the merge check needs
    the arguments to compare them with the callee's parameters. Raises SyntaxError like parse_file.
    """
    path = _norm(path)
    tree = ast.parse(source, filename=path)
    local = {qual for _, qual, _, _ in _walk_defs(tree.body, "", False)}
    aliases = _import_aliases(tree, path)
    ids = set(known.values())
    out: list[CallSite] = []
    for node, qual, _kind, owner in _walk_defs(tree.body, "", False):
        caller = f"{path}::{qual}"
        for call in _calls_in(node):
            target = _resolve_call(call.func, path, owner, local, aliases, known, ids)
            if target:
                out.append(CallSite(caller, target, call))
    return out


def definitions(path: str, source: str) -> dict[str, tuple[ast.FunctionDef | ast.AsyncFunctionDef, bool]]:
    """Function and method nodes of one file: symbol id -> (node, is_method). Classes are left out, since a
    class call goes through __init__, which the merge check does not model."""
    path = _norm(path)
    tree = ast.parse(source, filename=path)
    return {
        f"{path}::{qual}": (node, kind == "method")
        for node, qual, kind, _owner in _walk_defs(tree.body, "", False)
        if kind != "class"
    }


@dataclass(frozen=True)
class EditDiff:
    added: list[SymbolInfo]
    removed: list[SymbolInfo]
    modified: list[tuple[SymbolInfo, SymbolInfo]]  # (old, new), body_hash differs
    signature_changed: list[tuple[SymbolInfo, SymbolInfo]]  # subset of modified whose signature differs
    new_calls: set[str]  # ids called by the new versions of added + modified symbols


def diff_symbols(old: list[SymbolInfo], new: list[SymbolInfo]) -> EditDiff:
    old_by = {s.id: s for s in old}
    new_by = {s.id: s for s in new}
    added = [s for s in new if s.id not in old_by]
    removed = [s for s in old if s.id not in new_by]
    modified: list[tuple[SymbolInfo, SymbolInfo]] = []
    signature_changed: list[tuple[SymbolInfo, SymbolInfo]] = []
    for s in new:
        prev = old_by.get(s.id)
        if prev is None or prev.body_hash == s.body_hash:
            continue
        modified.append((prev, s))
        if prev.signature != s.signature:
            signature_changed.append((prev, s))
    new_calls = {c for s in [*added, *(n for _, n in modified)] for c in s.calls}
    return EditDiff(added, removed, modified, signature_changed, new_calls)


# ── internals ────────────────────────────────────────────────────────────────


def _norm(path: str) -> str:
    return path.replace("\\", "/")


def _dotted(path: str) -> str:
    """'shop/pricing.py' -> 'shop.pricing'; 'shop/__init__.py' -> 'shop'."""
    parts = _norm(path)[:-3].split("/") if path.endswith(".py") else _norm(path).split("/")
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _walk_defs(body: list[ast.stmt], prefix: str, in_class: bool):
    """Yield (node, qualname, kind, owner_class_qualname) for top-level defs, class-level methods and nested
    classes. Defs nested inside functions are not symbols: their calls belong to the enclosing symbol."""
    for node in body:
        if isinstance(node, _FUNC):
            kind = "method" if in_class else "function"
            yield node, prefix + node.name, kind, (prefix[:-1] if in_class else None)
        elif isinstance(node, ast.ClassDef):
            qual = prefix + node.name
            yield node, qual, "class", None
            yield from _walk_defs(node.body, qual + ".", True)


def _from_module(node: ast.ImportFrom, path: str) -> str | None:
    """Absolute dotted module of a `from ... import` (resolves relative dots against the file's package)."""
    if node.level == 0:
        return node.module or ""
    pkg = _norm(path)[:-3].split("/")[:-1]
    keep = len(pkg) - (node.level - 1)
    if keep < 0:
        return None
    return ".".join([*pkg[:keep], *(node.module.split(".") if node.module else [])])


def _import_aliases(tree: ast.Module, path: str) -> dict[str, str]:
    """Local name -> dotted target, e.g. `import shop.pricing as p` gives p -> shop.pricing."""
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.asname:
                    aliases[a.asname] = a.name
                else:  # `import a.b` binds only `a`, so `a.b.f()` is written as a chain from `a`
                    head = a.name.split(".")[0]
                    aliases[head] = head
        elif isinstance(node, ast.ImportFrom):
            base = _from_module(node, path)
            if base is None:
                continue
            for a in node.names:
                if a.name != "*":
                    aliases[a.asname or a.name] = ".".join(p for p in (base, a.name) if p)
    return aliases


def _chain(expr: ast.expr) -> list[str] | None:
    """`a.b.c` -> ["a", "b", "c"]; anything else (calls, subscripts) -> None."""
    if isinstance(expr, ast.Name):
        return [expr.id]
    if isinstance(expr, ast.Attribute):
        base = _chain(expr.value)
        return None if base is None else [*base, expr.attr]
    return None


def _resolve_dotted(dotted: str, known: dict[str, str] | None, ids: set[str] | None) -> str | None:
    if known is not None and dotted in known:
        return known[dotted]
    parts = dotted.split(".")
    if len(parts) < 2 or not parts[0]:
        return None
    if known is None:
        # No project index: assume the module is the whole prefix. Only the call's own symbol name is
        # taken from the last part, so `pkg.mod.func` -> pkg/mod.py::func.
        if parts[0] in sys.stdlib_module_names:
            return None
        return f"{'/'.join(parts[:-1])}.py::{parts[-1]}"
    # Longest module prefix first: "pkg.mod.Cls.method" can be module pkg.mod + qualname Cls.method.
    for k in range(len(parts) - 1, 0, -1):
        cand = f"{'/'.join(parts[:k])}.py::{'.'.join(parts[k:])}"
        if ids is not None and cand in ids:
            return cand
    return None


def _resolve_call(
    func: ast.expr,
    path: str,
    owner: str | None,
    local: set[str],
    aliases: dict[str, str],
    known: dict[str, str] | None,
    ids: set[str] | None,
) -> str | None:
    chain = _chain(func)
    if not chain:
        return None
    head = chain[0]
    if head == "self" and owner and len(chain) == 2:  # self.method() inside a class
        qual = f"{owner}.{chain[1]}"
        return f"{path}::{qual}" if qual in local else None
    if head in aliases:  # imported name, or a module attribute like p.apply_tax
        return _resolve_dotted(".".join([aliases[head], *chain[1:]]), known, ids)
    qual = ".".join(chain)  # same-file function, class, or Class.method
    return f"{path}::{qual}" if qual in local else None


def _calls_in(node: ast.AST) -> list[ast.Call]:
    """Every Call under a symbol, in source order. A class's own nested defs are separate symbols."""
    skip_defs = isinstance(node, ast.ClassDef)
    calls: list[ast.Call] = []
    stack = list(ast.iter_child_nodes(node))
    while stack:
        cur = stack.pop()
        if skip_defs and isinstance(cur, _DEF):
            continue
        if isinstance(cur, ast.Call):
            calls.append(cur)
        stack.extend(ast.iter_child_nodes(cur))
    return sorted(calls, key=lambda c: (c.lineno, c.col_offset))


def _signature(node: ast.AST) -> str:
    if isinstance(node, ast.ClassDef):
        bases = ", ".join(ast.unparse(b) for b in node.bases)
        return f"class {node.name}({bases})" if bases else f"class {node.name}"
    assert isinstance(node, _FUNC)
    a = node.args

    def fmt(arg: ast.arg) -> str:
        return arg.arg + (f": {ast.unparse(arg.annotation)}" if arg.annotation else "")

    parts: list[str] = []
    positional = [*a.posonlyargs, *a.args]
    first_default = len(positional) - len(a.defaults)
    for i, arg in enumerate(positional):
        parts.append(fmt(arg) + ("=..." if i >= first_default else ""))
        if a.posonlyargs and i == len(a.posonlyargs) - 1:
            parts.append("/")
    if a.vararg:
        parts.append("*" + fmt(a.vararg))
    elif a.kwonlyargs:
        parts.append("*")
    for arg, default in zip(a.kwonlyargs, a.kw_defaults, strict=True):
        parts.append(fmt(arg) + ("=..." if default is not None else ""))
    if a.kwarg:
        parts.append("**" + fmt(a.kwarg))
    keyword = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
    sig = f"{keyword} {node.name}({', '.join(parts)})"
    if node.returns is not None:
        sig += f" -> {ast.unparse(node.returns)}"
    return sig


def _body_hash(node: ast.AST) -> str:
    target = node
    if isinstance(node, ast.ClassDef):
        # Methods are their own symbols; leaving them in would make every method edit also "modify" the class.
        target = copy.copy(node)
        target.body = [s for s in node.body if not isinstance(s, _DEF)]
    return hashlib.sha1(ast.dump(target, include_attributes=False).encode()).hexdigest()
