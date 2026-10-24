"""Tests und Tools kodieren keine absoluten lokalen Pfade ausserhalb des Repos.

Ein hart kodierter Benutzer- oder Worktree-Pfad (Benutzerprofil, lokales
Temp-/Worktree-Verzeichnis, Dokumentenordner) macht einen Test bzw. ein Tool
maschinenabhaengig und schreibt lokale Ordnernamen ins Repo. Erlaubt sind
repo-relative Pfade (``Path(__file__)``-basiert) oder ein Env-Override; was
ohne externe Ressource nicht laufen kann, ueberspringt sich per
``pytest.skip`` mit Grund.
"""
from __future__ import annotations

import re
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent

SCAN_ROOTS = [
    BACKEND_ROOT / "tests",
    REPO_ROOT / "tools",
    REPO_ROOT / "scripts",
    BACKEND_ROOT / "scripts",
    REPO_ROOT / "ares-desktop" / "frontend" / "reporting" / "src",
    REPO_ROOT / "ares-desktop" / "tests",
]
SUFFIXES = {".py", ".ts", ".tsx", ".js", ".cjs", ".mjs", ".ps1", ".sh"}
SKIP_DIRS = {"node_modules", "__pycache__", ".pytest_cache", "dist", "build"}

# Laufwerk + Benutzer-/Temp-Ordner (beliebige Trenner/Escapes), macOS-Home,
# Dokumentenordner eines Chat-Exports.
ABSOLUTE_LOCAL_PATH = re.compile(
    r"(?i:[a-z]):[\\/]+(?:Users|tmp)[\\/]"
    r"|(?:^|[\s\"'`(=~])/Users/[A-Za-z]"
    r"|Documents[\\/]+ChatGPT"
)


def _candidates():
    this = Path(__file__).resolve()
    for root in SCAN_ROOTS:
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if path.suffix not in SUFFIXES or not path.is_file():
                continue
            if SKIP_DIRS.intersection(path.parts) or path.resolve() == this:
                continue
            yield path


def test_no_hard_coded_absolute_local_paths_in_tests_and_tools():
    hits = []
    for path in _candidates():
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            if ABSOLUTE_LOCAL_PATH.search(line):
                hits.append(f"{path.relative_to(REPO_ROOT)}:{lineno}")
    assert not hits, "Absolute lokale Pfade gefunden:\n" + "\n".join(hits)
