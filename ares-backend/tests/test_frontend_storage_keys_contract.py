"""W4-a2: Browser-Storage-Schluessel des Monolithen stehen unter ``ares.``.

Vertrag (Register 12, A4-A7):
- Theme und Praesentationsmodus: das Pre-Paint-Inline-Skript am Anfang von
  ``<body>`` liest exakt denselben Schluessel, den die Konstante weiter unten
  schreibt (sonst FOUC bzw. falsche Maske beim Start).
- Cashflow-Reihenfolge und Allokationspraeferenzen nutzen ``ares.``-Praefixe.
- Jeder literale Storage-Schluessel ist entweder ``ares.``-praefixiert oder
  steht in der kleinen Liste neutraler Schluessel.
- Es gibt keinen Rueckfall-Lesepfad: die Uebernahme alter Werte macht nur der
  externe Migrator-Seeder.
"""
from __future__ import annotations

import re
from pathlib import Path
from tests.monolith_source import read_monolith_bundle  # H3/I-04: inkl. ausgelagerter Teile

HTML_PATH = Path(__file__).resolve().parents[2] / "ares-desktop" / "frontend" / "ares.html"

# N-875-08: einfache, doppelte Quotes und Template-Strings (Praefix bis ${...}).
_LITERAL_ACCESS = re.compile(
    r"(?:local|session)Storage\s*\.\s*(?:get|set|remove)Item\s*\(\s*(['\"`])([^'\"`]+)\1"
)
_NEUTRAL_KEYS = {"auto_recompute", "introShown"}


def _html() -> str:
    return read_monolith_bundle()


def _const(html: str, name: str) -> str:
    found = re.findall(r"var " + re.escape(name) + r"='([^']+)';", html)
    assert len(found) == 1, (name, found)
    return found[0]


def _pre_paint_keys(html: str) -> list[str]:
    body_start = html.index("<body>")
    script_end = html.index("</script>", body_start)
    return re.findall(r"localStorage\.getItem\('([^']+)'\)", html[body_start:script_end])


def test_pre_paint_reads_same_keys_as_constants():
    html = _html()
    theme = _const(html, "THEME_STORAGE_KEY")
    mode = _const(html, "PRESENTATION_MODE_STORAGE_KEY")
    assert theme == "ares.theme"
    assert mode == "ares.presentation_mode"
    assert _pre_paint_keys(html) == [theme, mode]


def test_cashflow_order_and_allocation_preference_prefixes():
    html = _html()
    assert _const(html, "allocationPreferenceStoragePrefix") == "ares.allocprefs."
    start = html.index("function cashflowOrderStorageKey(type){")
    body = html[start : html.index("\n}", start)]
    assert "return 'ares.cashflow-order.'+" in body


def _literal_keys(text: str) -> set[str]:
    return {m.group(2) for m in _LITERAL_ACCESS.finditer(text)}


def test_every_literal_storage_key_is_ares_prefixed_or_neutral():
    # N-875-07: Bundle + alle eigenstaendigen Frontend-Module.
    from tests.monolith_source import read_frontend_sources

    keys = _literal_keys(read_frontend_sources())
    assert keys, "keine literalen Storage-Schluessel gefunden"
    unexpected = {k for k in keys if not k.startswith("ares.") and k not in _NEUTRAL_KEYS}
    assert not unexpected, sorted(unexpected)


def test_literal_key_detector_handles_all_quote_styles():
    text = (
        "localStorage.getItem('a.one');localStorage.setItem(\"b.two\",1);"
        "sessionStorage.removeItem(`c.three.${x}`)"
    )
    assert _literal_keys(text) == {"a.one", "b.two", "c.three.${x}"}
