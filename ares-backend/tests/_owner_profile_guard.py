"""H11 Nachtrag 1 (Vorfall 2026-11-14): Session-Waechter fuer das Owner-Profil.

Eine Test-Session darf unter ``~/ares`` und ``~/5eyes`` (Owner-Datenbanken,
Backups, Logs) nichts anlegen oder veraendern. ``conftest`` nimmt beim Start
(Controller, vor jedem Test) einen Schnappschuss (Existenz, Groesse,
mtime_ns je Datei) und vergleicht ihn am Session-Ende; jede neue, geaenderte
oder geloeschte Datei macht den Lauf rot und wird benannt.

Grenze: Ein fremder Prozess, der waehrend des Laufs im Owner-Profil schreibt,
macht den Lauf ebenfalls rot (lieber falsch-rot als still).
"""
from __future__ import annotations

from pathlib import Path

Snapshot = dict[str, tuple[int, int]]


def owner_profile_roots(home: Path | None = None) -> tuple[Path, ...]:
    base = Path.home() if home is None else home
    return (base / "ares", base / "5eyes")


def snapshot(roots) -> Snapshot:
    out: Snapshot = {}
    for root in roots:
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            try:
                if path.is_file():
                    st = path.stat()
                    out[str(path)] = (st.st_size, st.st_mtime_ns)
            except OSError:
                continue
    return out


def changes(before: Snapshot, after: Snapshot) -> list[str]:
    lines = [f"neu: {p}" for p in sorted(set(after) - set(before))]
    lines += [f"veraendert: {p}" for p in sorted(set(after) & set(before)) if after[p] != before[p]]
    lines += [f"geloescht: {p}" for p in sorted(set(before) - set(after))]
    return lines
