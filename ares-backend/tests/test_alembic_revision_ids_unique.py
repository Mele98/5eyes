"""Guard (C-890-01 Nachtrag 5): Alembic-Revision-IDs sind eindeutig, und jede
Migrationsdatei heisst wie ihre ``revision`` (``<revision>_<name>.py``).

Anlass: ``c4e8a2f6b9d1`` war auf zwei unveroeffentlichten Branches (C-890 und
E2 ``r5/e2-esg-journey``) mit verschiedenem Inhalt vergeben -- beim
Zusammenfuehren haette Alembic zwei Revisionen mit derselben ID gesehen. Die
C-890-Revision heisst seither ``d66fbf0588e3``. IDs, die auf anderen offenen
Branches belegt sind, stehen in ``RESERVED_ELSEWHERE`` und duerfen hier nicht
(erneut) vergeben werden.
"""
from __future__ import annotations

import re
from pathlib import Path

VERSIONS = Path(__file__).resolve().parents[1] / "alembic" / "versions"
_REVISION = re.compile(r"^revision(?:\s*:\s*[\w\[\], ]+)?\s*=\s*['\"]([0-9A-Za-z_]+)['\"]", re.M)

# Auf anderen offenen Branches belegt (anderer Inhalt): hier nie verwenden.
RESERVED_ELSEWHERE = {
    "c4e8a2f6b9d1": "r5/e2-esg-journey: c4e8a2f6b9d1_contract_document_allocation_binding.py",
}


def _revisions() -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for path in sorted(VERSIONS.glob("*.py")):
        if path.name == "__init__.py":
            continue
        match = _REVISION.search(path.read_text(encoding="utf-8"))
        assert match, f"{path.name}: keine revision gefunden"
        found.setdefault(match.group(1), []).append(path.name)
    return found


def test_revision_ids_are_unique():
    duplicates = {rev: files for rev, files in _revisions().items() if len(files) > 1}
    assert duplicates == {}


def test_every_file_is_named_after_its_revision():
    wrong = [f for rev, files in _revisions().items() for f in files if not f.startswith(f"{rev}_")]
    assert wrong == []


def test_no_revision_id_reserved_on_another_branch_is_reused():
    assert set(_revisions()) & set(RESERVED_ELSEWHERE) == set()


def test_negative_control_detects_a_duplicate(tmp_path, monkeypatch):
    import sys

    module = sys.modules[__name__]
    for name, rev in (("aaaaaaaaaaaa_eins.py", "aaaaaaaaaaaa"), ("bbbbbbbbbbbb_zwei.py", "aaaaaaaaaaaa")):
        (tmp_path / name).write_text(f'revision = "{rev}"\n', encoding="utf-8")
    monkeypatch.setattr(module, "VERSIONS", tmp_path)
    assert {r: f for r, f in _revisions().items() if len(f) > 1} == {
        "aaaaaaaaaaaa": ["aaaaaaaaaaaa_eins.py", "bbbbbbbbbbbb_zwei.py"]}
    wrong = [f for rev, files in _revisions().items() for f in files if not f.startswith(f"{rev}_")]
    assert wrong == ["bbbbbbbbbbbb_zwei.py"]
