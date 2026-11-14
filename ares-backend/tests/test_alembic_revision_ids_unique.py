"""Guard (C-890-01 Nachtrag 5, H11): Alembic-Revision-IDs sind eindeutig -- ueber
ALLE Migrationsdateien im Tree, nicht ueber eine statische Reserveliste.

Anlass: ``c4e8a2f6b9d1`` war auf zwei unveroeffentlichten Branches (C-890 und
E2) mit verschiedenem Inhalt vergeben. Die erste Fassung dieses Guards pruefte
nur ``alembic/versions`` und eine Hand-Liste ``RESERVED_ELSEWHERE`` (E1 fehlte
darin). H11 (Hygiene-Folgepunkt C-890, N-897-19): Gescannt wird jetzt jede
Python-Datei im Repository mit einer Modul-Zuweisung ``revision = ...`` und
``down_revision = ...`` (AST, keine Docstrings). Verlangt wird:

* jede Revision-ID genau einmal im ganzen Tree;
* jede Migrationsdatei liegt in ``ares-backend/alembic/versions`` und heisst
  ``<revision>_<name>.py`` (eine abgelegte Kopie anderswo ist eine Kollision);
* der Graph ist geschlossen: jede ``down_revision`` existiert, genau ein Head.

Kollisionen zwischen offenen Branches erkennt jeder Branch spaetestens beim
Zusammenfuehren, weil dann beide Dateien im selben Tree liegen; vor dem Push
werden die IDs zusaetzlich gegen ``origin/r5/*`` geprueft (Arbeitsregel).
"""
from __future__ import annotations

import ast
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
VERSIONS = REPO / "ares-backend" / "alembic" / "versions"
SKIP_PARTS = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", "site-packages"}


def _assigned(tree: ast.Module, name: str):
    for node in tree.body:
        targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, ast.AnnAssign) else []
        if any(isinstance(t, ast.Name) and t.id == name for t in targets) and node.value is not None:
            try:
                return True, ast.literal_eval(node.value)
            except ValueError:
                return True, None
    return False, None


def _migration_files(root: Path = REPO) -> dict[Path, tuple[str, object]]:
    """Alle Dateien mit Modul-Zuweisungen ``revision`` UND ``down_revision``."""
    out: dict[Path, tuple[str, object]] = {}
    for path in sorted(root.rglob("*.py")):
        if SKIP_PARTS & set(path.relative_to(root).parts):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if "revision" not in text or "down_revision" not in text:
            continue
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        has_rev, rev = _assigned(tree, "revision")
        has_down, down = _assigned(tree, "down_revision")
        if has_rev and has_down and isinstance(rev, str):
            out[path] = (rev, down)
    return out


def _by_revision(files: dict[Path, tuple[str, object]]) -> dict[str, list[Path]]:
    found: dict[str, list[Path]] = {}
    for path, (rev, _down) in files.items():
        found.setdefault(rev, []).append(path)
    return found


def _problems(files: dict[Path, tuple[str, object]], versions: Path) -> dict[str, list]:
    by_rev = _by_revision(files)
    downs = {d for _r, down in files.values() for d in ((down,) if isinstance(down, str) else (down or ()))}
    return {
        "duplicates": sorted(rev for rev, paths in by_rev.items() if len(paths) > 1),
        "outside_versions": sorted(str(p) for p in files if p.parent != versions),
        "misnamed": sorted(p.name for p, (rev, _d) in files.items() if not p.name.startswith(f"{rev}_")),
        "dangling": sorted(d for d in downs if d not in by_rev),
        "heads": sorted(rev for rev in by_rev if rev not in downs),
    }


def test_tree_wide_scan_finds_the_migrations():
    files = _migration_files()
    assert len([p for p in files if p.parent == VERSIONS]) == len(
        [p for p in VERSIONS.glob("*.py") if p.name != "__init__.py"])
    assert len(files) >= 80


def test_revision_ids_unique_in_whole_tree_and_graph_closed():
    problems = _problems(_migration_files(), VERSIONS)
    assert problems["duplicates"] == [] and problems["outside_versions"] == [] and problems["misnamed"] == []
    assert problems["dangling"] == []
    assert len(problems["heads"]) == 1, problems["heads"]


def test_negative_control_duplicate_stray_copy_and_second_head(tmp_path):
    versions = tmp_path / "ares-backend" / "alembic" / "versions"
    versions.mkdir(parents=True)
    other = tmp_path / "docs" / "alt"
    other.mkdir(parents=True)
    (versions / "aaaaaaaaaaaa_eins.py").write_text('"""revision = "zzz" im Docstring"""\nrevision = "aaaaaaaaaaaa"\n'
                                                  "down_revision = None\n", encoding="utf-8")
    (versions / "bbbbbbbbbbbb_zwei.py").write_text('revision: str = "aaaaaaaaaaaa"\ndown_revision = "aaaaaaaaaaaa"\n',
                                                  encoding="utf-8")
    (versions / "cccccccccccc_drei.py").write_text('revision = "cccccccccccc"\ndown_revision = "aaaaaaaaaaaa"\n',
                                                  encoding="utf-8")
    (other / "dddddddddddd_kopie.py").write_text('revision = "dddddddddddd"\ndown_revision = "ffffffffffff"\n',
                                                encoding="utf-8")
    problems = _problems(_migration_files(tmp_path), versions)
    assert problems["duplicates"] == ["aaaaaaaaaaaa"]
    assert problems["outside_versions"] == [str(other / "dddddddddddd_kopie.py")]
    assert problems["misnamed"] == ["bbbbbbbbbbbb_zwei.py"]
    assert problems["dangling"] == ["ffffffffffff"]
    assert set(problems["heads"]) == {"cccccccccccc", "dddddddddddd"}


def test_no_static_reserve_list_anymore():
    import sys

    assert not hasattr(sys.modules[__name__], "RESERVED_ELSEWHERE")
