#!/usr/bin/env python
"""W1-803-01: In-Repo-Ratsche fuer die Verzeichnisstruktur des Produkt-Repos.

Problem
-------
Die Pfadwelle W1 hat die Produktverzeichnisse auf ``ares-backend/`` und
``ares-desktop/`` umgestellt; alle CI-Jobs laufen mit
``working-directory: ares-backend``. Ein spaeterer Merge koennte eine Datei
wieder unter einem anderen (z. B. veralteten) Top-Level-Verzeichnis anlegen.
Tests dort wuerden von keinem Job gesammelt -- die Suite bliebe gruen, obwohl
der neue Code nie geprueft wurde. Ein externer Scanner ist nur die zweite
Schutzschicht; diese Datei ist die erste, im Repo selbst.

Vertrag (positive Allowlist, keine Verbotsliste)
------------------------------------------------
1. Jeder Top-Level-Knoten aus ``git ls-files`` steht in
   ``ALLOWED_TOP_LEVEL``.
2. Jedes Unterverzeichnis erster Ebene in ``ares-backend/`` und
   ``ares-desktop/`` steht in ``ALLOWED_SUBDIRS`` (Dateien erster Ebene sind
   bewusst frei, Verzeichnisse sind die stabile Struktur).
3. Die Pflichtpfade in ``REQUIRED_PATHS`` existieren im Index (die CI sammelt
   genau dort).
4. Jedes literale ``working-directory:``/``cache-dependency-path:`` sowie jede
   ``matrix.dir``-Liste in ``.github/workflows/*.yml`` zeigt auf einen Pfad im
   Index -- ein veraltetes Arbeitsverzeichnis faellt hier, nicht erst durch
   eine stillschweigend leere Testsammlung.

Ein neuer Knoten ist kein Fehler an sich, er braucht nur eine bewusste
Entscheidung: Allowlist hier im selben PR erweitern und begruenden.

Single Source of Truth fuer CI (.github/workflows/test.yml) und lokale
Nutzung. Nur Standardbibliothek plus ``git`` -- laeuft ohne pip install.

Aufruf (aus beliebigem Verzeichnis im Repo):
    python scripts/check_repo_top_level_layout.py
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

ALLOWED_TOP_LEVEL: frozenset[str] = frozenset(
    {
        ".gitattributes",
        ".github",
        ".gitignore",
        "README.md",
        "api",
        "ares-backend",
        "ares-desktop",
        "docs",
        "scripts",
        "tools",
    }
)

ALLOWED_SUBDIRS: dict[str, frozenset[str]] = {
    "ares-backend": frozenset(
        {
            "alembic",
            "assets",
            "config",
            "core",
            "migrations",
            "models",
            "routers",
            "schemas",
            "scripts",
            "services",
            "tests",
        }
    ),
    "ares-desktop": frozenset(
        {
            "assets",
            "frontend",
            "scripts",
            "tests",
        }
    ),
}

REQUIRED_PATHS: tuple[str, ...] = (
    "ares-backend/requirements.txt",
    "ares-backend/tests/conftest.py",
    "ares-desktop/package.json",
    "ares-desktop/frontend/reporting/package-lock.json",
)

WORKFLOW_DIR = ".github/workflows"

_PATH_KEY_RE = re.compile(
    r"^\s*(?:-\s+)?(working-directory|cache-dependency-path)\s*:\s*['\"]?([^'\"#\s]+)['\"]?"
)
_MATRIX_DIR_RE = re.compile(r"^(\s*)dir\s*:\s*$")
_LIST_ITEM_RE = re.compile(r"^(\s*)-\s+['\"]?([^'\"#\s]+)['\"]?\s*$")


def tracked_files(repo_root: Path = REPO_ROOT) -> list[str]:
    """Alle Pfade im Git-Index (inkl. gestagter, noch nicht committeter)."""
    out = subprocess.run(
        ["git", "-C", str(repo_root), "ls-files", "-z"],
        check=True,
        capture_output=True,
    ).stdout
    return [p for p in out.decode("utf-8").split("\0") if p]


def check_top_level(files: list[str]) -> list[str]:
    nodes = sorted({f.split("/", 1)[0] for f in files})
    return [
        f"Unerwarteter Top-Level-Knoten: '{node}' "
        f"(nicht in ALLOWED_TOP_LEVEL von scripts/check_repo_top_level_layout.py)"
        for node in nodes
        if node not in ALLOWED_TOP_LEVEL
    ]


def check_subdirs(files: list[str]) -> list[str]:
    problems: list[str] = []
    for parent, allowed in ALLOWED_SUBDIRS.items():
        prefix = parent + "/"
        subdirs = sorted(
            {
                f[len(prefix):].split("/", 1)[0]
                for f in files
                if f.startswith(prefix) and "/" in f[len(prefix):]
            }
        )
        problems.extend(
            f"Unerwartetes Unterverzeichnis: '{parent}/{sub}' "
            f"(nicht in ALLOWED_SUBDIRS['{parent}'])"
            for sub in subdirs
            if sub not in allowed
        )
    return problems


def check_required(files: list[str]) -> list[str]:
    present = set(files)
    return [f"Pflichtpfad fehlt im Index: '{p}'" for p in REQUIRED_PATHS if p not in present]


def workflow_paths(text: str) -> list[str]:
    """Literale Pfade aus working-directory/cache-dependency-path/matrix.dir."""
    paths: list[str] = []
    lines = text.splitlines()
    for i, line in enumerate(lines):
        m = _PATH_KEY_RE.match(line)
        if m and "${{" not in line:
            paths.append(m.group(2))
            continue
        d = _MATRIX_DIR_RE.match(line)
        if d:
            indent = len(d.group(1))
            for nxt in lines[i + 1:]:
                item = _LIST_ITEM_RE.match(nxt)
                if not item or len(item.group(1)) < indent:
                    break
                paths.append(item.group(2))
    return paths


def check_workflows(files: list[str], repo_root: Path = REPO_ROOT) -> list[str]:
    present = set(files)
    dirs = {"/".join(f.split("/")[:n]) for f in files for n in range(1, f.count("/") + 1)}
    problems: list[str] = []
    for wf in sorted(f for f in files if f.startswith(WORKFLOW_DIR + "/") and f.endswith((".yml", ".yaml"))):
        text = (repo_root / wf).read_text(encoding="utf-8")
        for path in workflow_paths(text):
            norm = path.rstrip("/")
            if norm not in present and norm not in dirs:
                problems.append(f"Workflow-Pfad existiert nicht im Index: '{path}' in {wf}")
    return problems


def find_problems(files: list[str], repo_root: Path = REPO_ROOT) -> list[str]:
    return (
        check_top_level(files)
        + check_subdirs(files)
        + check_required(files)
        + check_workflows(files, repo_root)
    )


def main() -> int:
    files = tracked_files()
    if not files:
        print("FEHLER: git ls-files lieferte keine Dateien -- Gate kann nichts pruefen.")
        return 2
    problems = find_problems(files)
    if problems:
        print(f"FEHLER: {len(problems)} Verletzung(en) der Repo-Struktur-Ratsche:")
        for line in problems:
            print(f"  - {line}")
        print(
            "Abhilfe: Datei unter einen erlaubten Pfad verschieben oder die Allowlist in "
            "scripts/check_repo_top_level_layout.py im selben PR bewusst erweitern."
        )
        return 1
    top = sorted({f.split("/", 1)[0] for f in files})
    print(f"OK: {len(files)} Dateien, Top-Level-Knoten: {' '.join(top)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
