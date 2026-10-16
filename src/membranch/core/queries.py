"""Loads every query from the repo-level cypher/ folder. That folder is the single source of truth:
the README's Cypher list is generated from it (scripts/gen_cypher_docs.py)."""

from pathlib import Path

CYPHER_DIR = Path(__file__).resolve().parents[3] / "cypher"


def _load() -> dict[str, str]:
    queries: dict[str, str] = {}
    for path in sorted(CYPHER_DIR.glob("*.cypher")):
        text = path.read_text()
        name = path.stem
        for line in text.splitlines():
            if line.startswith("// name:"):
                name = line.split(":", 1)[1].strip()
                break
        queries[name] = text
    return queries


Q = _load()
