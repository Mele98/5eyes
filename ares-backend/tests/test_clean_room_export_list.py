"""Clean-Room-Exportliste (scripts/clean_room_export_list.py, docs/DOCS_MANIFEST.md).

Der Export nimmt alles ausser ARCHIVE. Tests, die Doku zur Laufzeit lesen,
duerfen nur auf exportierte Dateien zeigen, sonst brechen sie im Clean-Room.
"""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
TESTS_DIR = Path(__file__).resolve().parent
SCRIPT = REPO_ROOT / "scripts" / "clean_room_export_list.py"


def _load():
    spec = importlib.util.spec_from_file_location("clean_room_export_list", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def mod():
    return _load()


@pytest.fixture(scope="module")
def exported(mod):
    return mod.export_list(REPO_ROOT, "HEAD")


def test_manifest_classifies_every_doc_file(mod):
    assert mod.check(REPO_ROOT, "HEAD") == []


def test_export_list_is_sorted_and_deterministic(mod, exported):
    assert exported == sorted(exported)
    assert len(exported) == len(set(exported))
    assert mod.export_list(REPO_ROOT, "HEAD") == exported


def test_export_list_drops_archive_and_keeps_product_docs(exported):
    keep = set(exported)
    for path in (
        "docs/DOCS_MANIFEST.md",
        "docs/GLOSSAR.md",
        "docs/adr/README.md",
        "docs/audits/2026-06-02-monolith-inventory.json",
        "README.md",
        "scripts/clean_room_export_list.py",
    ):
        assert path in keep, path
    for path in (
        "docs/planning/README.md",
        "docs/CODEX_WIP.md",
        "docs/REPO_HYGIENE_2026-06-04.md",
        "ares-backend/tests/test_archived_docs_contract.py",
    ):
        assert path not in keep, path
    assert not any(p.startswith(("docs/planning/", "docs/design/", "docs/bugs/")) for p in keep)
    assert [p for p in keep if p.startswith("docs/audits/")] == [
        "docs/audits/2026-06-02-monolith-inventory.json"
    ]


def test_rules_and_file_entries(mod):
    rules = [("docs/planning/", "ARCHIVE"), ("docs/*.docx", "ARCHIVE")]
    files = {"docs/planning/keep.md": "KEEP", "tools/x.py": "ARCHIVE"}
    assert mod.classify("docs/planning/a/b.md", rules, files) == "ARCHIVE"
    assert mod.classify("docs/planning/keep.md", rules, files) == "KEEP"
    assert mod.classify("docs/x.docx", rules, files) == "ARCHIVE"
    assert mod.classify("docs/sub/x.docx", rules, files) is None
    assert mod.classify("docs/new.md", rules, files) is None
    assert mod.classify("pkg/NOTES.md", rules, files) is None
    assert mod.classify("pkg/code.py", rules, files) == "KEEP"
    assert mod.classify("tools/x.py", rules, files) == "ARCHIVE"


def test_duplicate_manifest_entry_is_rejected(mod):
    text = "## Dateien\n\n| `a.md` | KEEP | x |\n| `a.md` | ARCHIVE | y |\n"
    with pytest.raises(mod.ManifestError):
        mod.parse_manifest(text)


_DOCS_REF = re.compile(r'"docs"((?:\s*/\s*"[^"]+")+)')


def test_doc_reading_tests_only_reference_exported_docs(exported):
    """Jeder ``REPO_ROOT / "docs" / ...``-Pfad in exportierten Tests zeigt auf
    eine exportierte Datei bzw. ein Verzeichnis mit exportierten Dateien."""
    keep = set(exported)
    missing = []
    for test_file in sorted(TESTS_DIR.rglob("test_*.py")):
        rel = test_file.relative_to(REPO_ROOT).as_posix()
        if rel not in keep:
            continue
        for m in _DOCS_REF.finditer(test_file.read_text(encoding="utf-8")):
            parts = re.findall(r'"([^"]+)"', m.group(1))
            target = "/".join(["docs", *parts])
            if target in keep or any(p.startswith(target + "/") for p in keep):
                continue
            missing.append(f"{rel}: {target}")
    assert missing == []
