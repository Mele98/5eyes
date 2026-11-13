"""Gesamtquelle des Frontend-Monolithen inkl. ausgelagerter Teile (H3/I-04).

``ares.html`` hat ein Groessen-Budget (test_frontend_monolith_size_budget).
Um Spielraum zu schaffen, wurden drei in sich geschlossene Bloecke 1:1 in
eigene Dateien ausgelagert (verhaltensneutral: gleiche Position im Dokument,
klassische synchrone Skripte bzw. Stylesheet an derselben Stelle):

* ``ares.css``              -- der grosse Haupt-``<style>``-Block im ``<head>``
* ``intro-sequence.js``     -- Intro-Animation + arrMin/arrMax-Helfer
* ``goal-review-runtime.js``-- letzter Skriptblock (Ziele/Allokation/Review)

H6 (Asset-Allocation-Grafik) fuehrt zwei neue Teile nach derselben Regel:
``aa-chart.css`` (direkt nach ``ares.css``) und ``aa-chart.js`` (direkt nach
``intro-sequence.js``). Sie waren nie inline; die Rekonstruktion setzt sie wie
die anderen Teile an ihrer Einbindung ein (die sha256-Aussage unten gilt fuer
den Stand vor H6).

Quelltext-Vertragstests, die Code aus diesen Bloecken pruefen, lesen ueber
:func:`read_monolith_bundle` die rekonstruierte Gesamtquelle: jede Einbindung
wird durch den Dateiinhalt im urspruenglichen Inline-Format ersetzt. Das
Ergebnis ist byte-identisch zum Monolithen vor der Auslagerung (sha256 gleich
dem Stand 2e5dfcc3), d. h. Positions-/Reihenfolge-Pruefungen bleiben gueltig.

N-875-01: ALLE Tests, die den Monolithen als Quelltext lesen, gehen ueber
:func:`read_monolith_bundle` -- insbesondere die "darf nirgends vorkommen"-
Guards (native Dialoge, Token-Speicher, Storage-Key-Praefix, Claims,
Kundentexte, Fenstertitel). test_frontend_monolith_bundle_coverage erzwingt
das statisch und per Mutation.

N-875-04 (Hinweis, kein Verhaltensunterschied heute): Unter ``file://``
(Electron ``loadFile``) gilt ``ares.css`` als cross-origin --
``document.styleSheets[i].cssRules`` wirft dort ``SecurityError`` (inline ging
das). Aktuell liest kein Frontend-Code ``cssRules``; kuenftiger Code (z. B. ein
Theme-/Druck-Export) darf sich nicht darauf verlassen.
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
from audit_html_monolith import STANDALONE_FRONTEND_MODULES  # noqa: E402


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


def read_standalone_modules() -> dict[str, str]:
    """Die vorbestehenden eigenstaendigen Module (ohne vendor/), Name -> Quelltext."""
    return {
        name: (FRONTEND_DIR / name).read_text(encoding="utf-8").replace("\r\n", "\n")
        for name in sorted(STANDALONE_FRONTEND_MODULES)
    }


def read_frontend_sources() -> str:
    """N-875-07: ALLE lokal eingebundenen Nicht-Vendor-Frontendquellen.

    Monolith-Bundle (ares.html + ausgelagerte Teile) plus jedes Modul aus
    STANDALONE_FRONTEND_MODULES. Fuer die globalen "darf nirgends vorkommen"-
    Guards (native Dialoge, Token-/Storage-Keys, Kundentexte, Claims,
    Fenstertitel) -- nicht fuer Positions-/Reihenfolge-Pruefungen.
    """
    parts = [read_monolith_bundle()]
    for name, text in read_standalone_modules().items():
        parts.append(f"\n/* ---- frontend module: {name} ---- */\n{text}")
    return "".join(parts)


ROUNDING_MODULE = "presentation-rounding.js"


def rounding_module_source() -> str:
    """G7: Quelltext von presentation-rounding.js (definiert ``AresRounding``).

    Node-Harnesses, die Monolith-Formatter (fmtPct/fmtNumber/formatRappen ...)
    extrahieren, muessen ihn voranstellen -- wie ares.html ihn vor dem
    Inline-Skript laedt.
    """
    module = (FRONTEND_DIR / ROUNDING_MODULE).read_text(encoding="utf-8").replace("\r\n", "\n")
    # N-894-05: App-Geldformatter fragen die Mandatswaehrung ueber appCurrency()
    # ab (ares.html); ohne Mandat/aa-chart.js liefert sie "CHF".
    html = MONOLITH_PATH.read_text(encoding="utf-8")
    lines = []
    for name in ("function sollPct(", "function appCurrency(){"):
        start = html.index(name)
        lines.append(html[start:html.index("\n", start)])
    return module + "\n" + "\n".join(lines) + "\n"
