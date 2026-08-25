"""Mega-Audit (2026-08-04), Architektur-Dimension: doppelte Top-Level-
Funktionsnamen im Frontend-Monolithen werden durch JS-Hoisting stillschweigend
ueberschrieben -- die spaetere Definition gewinnt, die frueher aufgerufene
(oft die eigentlich gewuenschte) wird tot. Zwei reale Bugs entstanden so:
buildQT()/quoten-Desync (gefixt 2026-08-03, Commit b4201c0) und der
openCashflowEditor-Namenskollisions-Bug (gefixt 2026-08-04), der den
Cashflow-Beta-Editor-Button unbrauchbar machte. Beide wurden durch punktuelle,
nicht systematische Cleanups nicht vollstaendig gefangen.

Dieser Test ist der im Mega-Audit empfohlene systematische Guard: er scannt
JEDE Top-Level-Funktionsdeklaration (`function name(...)` / `async function
name(...)`, Spalte 0) im Frontend-Monolithen und schlaegt fehl, sobald ein
Name mehrfach deklariert wird -- unabhaengig davon, ob der jeweilige Bug
schon bekannt ist oder nicht.
"""
from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

HTML_PATH = (
    Path(__file__).resolve().parents[2]
    / "5eyes-electron"
    / "frontend"
    / "5eyes_v2.html"
)

_TOP_LEVEL_FUNCTION_RE = re.compile(
    r"^(?:async\s+)?function\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(",
    re.MULTILINE,
)


def _top_level_function_names() -> list[str]:
    html = HTML_PATH.read_text(encoding="utf-8")
    return _TOP_LEVEL_FUNCTION_RE.findall(html)


def test_no_duplicate_top_level_function_declarations():
    names = _top_level_function_names()
    assert len(names) > 500, (
        f"Nur {len(names)} Top-Level-Funktionen gefunden -- Regex greift "
        "vermutlich nicht mehr auf die aktuelle Formatierung (Datei-Struktur "
        "geaendert?). Bitte Regex pruefen, statt den Guard stillschweigend "
        "wirkungslos zu lassen."
    )
    counts = Counter(names)
    duplicates = {name: n for name, n in counts.items() if n > 1}
    assert not duplicates, (
        "Doppelte Top-Level-Funktionsdeklaration(en) im Frontend-Monolithen "
        f"gefunden: {duplicates}. JS-Hoisting laesst die SPAETERE Definition "
        "gewinnen -- die frueher aufgerufene Version wird stillschweigend "
        "tot, OHNE Laufzeitfehler (siehe 2026-08-03 buildQT()-Bug und "
        "2026-08-04 openCashflowEditor-Bug). Entweder umbenennen (falls "
        "beide Versionen fachlich unterschiedlich sind, z.B. eine "
        "Zeilen-Editor-Variante mit Argument vs. eine argumentlose "
        "React-Wiring-Bridge) oder die tote Duplikat-Definition entfernen."
    )
