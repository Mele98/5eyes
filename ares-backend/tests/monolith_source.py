"""Gesamtquelle des Frontend-Monolithen inkl. ausgelagerter Teile (H3/I-04).

``ares.html`` hat ein Groessen-Budget (test_frontend_monolith_size_budget).
Um Spielraum zu schaffen, wurden drei in sich geschlossene Bloecke 1:1 in
eigene Dateien ausgelagert (verhaltensneutral: gleiche Position im Dokument,
klassische synchrone Skripte bzw. Stylesheet an derselben Stelle):

* ``ares.css``              -- der grosse Haupt-``<style>``-Block im ``<head>``
* ``intro-sequence.js``     -- Intro-Animation + arrMin/arrMax-Helfer
* ``goal-review-runtime.js``-- letzter Skriptblock (Ziele/Allokation/Review)

Quelltext-Vertragstests, die Code aus diesen Bloecken pruefen, lesen ueber
:func:`read_monolith_bundle` die rekonstruierte Gesamtquelle: jede Einbindung
wird durch den Dateiinhalt im urspruenglichen Inline-Format ersetzt. Das
Ergebnis ist byte-identisch zum Monolithen vor der Auslagerung, d. h.
Positions-/Reihenfolge-Pruefungen bleiben gueltig.
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_DIR = _REPO_ROOT / "ares-desktop" / "frontend"
MONOLITH_PATH = FRONTEND_DIR / "ares.html"

_SCRIPTS_ROOT = _REPO_ROOT / "scripts"
if str(_SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_ROOT))

# (Dateiname, Art) in Dokumentreihenfolge -- eine Quelle fuer Inventar und Tests.
from audit_html_monolith import EXTRACTED_MONOLITH_PARTS as EXTRACTED_PARTS  # noqa: E402


def include_tag(name: str, kind: str) -> str:
    if kind == "css":
        return f'<link rel="stylesheet" href="./{name}">'
    return f'<script src="./{name}"></script>'


def _inline(name: str, kind: str) -> str:
    body = (FRONTEND_DIR / name).read_text(encoding="utf-8").replace("\r\n", "\n")
    if kind == "css":
        return f"<style>\n{body}</style>"
    return f"<script>\n{body}</script>"


def read_monolith_bundle() -> str:
    """``ares.html`` mit wieder eingesetzten ausgelagerten Teilen (LF)."""
    html = MONOLITH_PATH.read_text(encoding="utf-8").replace("\r\n", "\n")
    for name, kind in EXTRACTED_PARTS:
        tag = include_tag(name, kind)
        assert html.count(tag) == 1, f"Einbindung {tag!r} nicht genau einmal in ares.html"
        html = html.replace(tag, _inline(name, kind))
    return html


def read_extracted_sources() -> dict[str, str]:
    return {
        name: (FRONTEND_DIR / name).read_text(encoding="utf-8")
        for name, _kind in EXTRACTED_PARTS
    }
