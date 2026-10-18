"""Workspace sandbox: every repo path the agents send must stay inside their own clone."""

import os
from pathlib import Path

import pytest

from git0.ide.harness import SandboxError, resolve_in_workspace


@pytest.mark.parametrize(
    "rel",
    [
        "../secret.txt",
        "shop/../../secret.txt",
        "/etc/passwd",
        "\\windows\\system32",
        "C:/Users/x/file.py",
        "c:file.py",
        "shop\\cart.py",
        "./shop/cart.py",
        ".git/config",
        "",
        "   ",
        "shop/\x00cart.py",
    ],
)
def test_rejects_paths_outside_or_malformed(tmp_path: Path, rel: str) -> None:
    with pytest.raises(SandboxError):
        resolve_in_workspace(tmp_path, rel)


def test_accepts_repo_relative_paths(tmp_path: Path) -> None:
    target = resolve_in_workspace(tmp_path, "shop/cart.py")
    assert target == tmp_path.resolve() / "shop" / "cart.py"


@pytest.mark.skipif(os.name == "nt", reason="symlink creation needs admin or developer mode on Windows")
def test_rejects_symlink_escape(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (ws / "link").symlink_to(outside, target_is_directory=True)
    with pytest.raises(SandboxError):
        resolve_in_workspace(ws, "link/evil.py")
