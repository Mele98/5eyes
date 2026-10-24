"""Groessen-Budget des Monolithen (Electron-Frontend, eine HTML-Datei).

Ratchet, nur sinkend: neue Fachlogik gehoert in Module bzw. die React-App,
nicht in den Monolithen. Die Grenze ist die Zeilenzahl beim Einfuehren
des Budgets, Toleranz 0. Wer den Monolithen verkleinert, senkt
``MONOLITH_MAX_LINES`` im selben PR auf den neuen Stand; anheben ist nicht
vorgesehen (nur per ausdruecklichem Owner-Entscheid).
"""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MONOLITH = REPO_ROOT / "5eyes-electron" / "frontend" / "5eyes_v2.html"

MONOLITH_MAX_LINES = 31461
TOLERANCE_LINES = 0


def _line_count(path: Path) -> int:
    return len(path.read_bytes().splitlines())


def test_monolith_does_not_grow_beyond_budget():
    actual = _line_count(MONOLITH)
    assert actual <= MONOLITH_MAX_LINES + TOLERANCE_LINES, (
        f"Monolith hat {actual} Zeilen, Budget {MONOLITH_MAX_LINES} (Toleranz "
        f"{TOLERANCE_LINES}). Logik auslagern statt den Monolithen zu vergroessern."
    )


def test_budget_has_no_tolerance():
    assert TOLERANCE_LINES == 0
