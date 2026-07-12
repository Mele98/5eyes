"""Frontend: Kunden-Register (Suche + A-Z-Gruppierung) in der Sidebar.

Ersetzt das reine Ein-/Ausblenden durch ein echtes alphabetisches Register mit
Suchfeld und sticky Buchstaben-Trennern.
"""
from __future__ import annotations

from pathlib import Path

HTML_PATH = (
    Path(__file__).resolve().parents[2]
    / "5eyes-electron" / "frontend" / "5eyes_v2.html"
)


def _html() -> str:
    return HTML_PATH.read_text(encoding="utf-8")


def test_client_register_has_search_input():
    html = _html()
    assert 'id="client-search"' in html
    assert 'oninput="filterClientRegister(this.value)"' in html


def test_client_register_has_az_grouping_logic():
    html = _html()
    # Sortier-/Gruppierungs-Helfer + sticky Buchstaben-Trenner.
    assert "function _clientSortKey(" in html
    assert "function filterClientRegister(" in html
    assert "client-letter" in html
    # Sortierung alphabetisch (localeCompare, Nachname-Schluessel).
    assert "localeCompare" in html


def test_client_register_css_present():
    html = _html()
    assert ".client-letter{position:sticky" in html
    assert ".sb-search input" in html


def test_client_names_masked_by_default():
    # Privacy-by-Default (Banking-Standard, revDSG Art. 7): Namen sind beim Start
    # maskiert (priv=true wenn keine gespeicherte Wahl vorliegt) + persistiert.
    html = _html()
    assert "localStorage.getItem('sb-privacy')" in html
    assert "v===null ? true" in html  # kein gespeicherter Wert -> maskiert
    assert "function applyPrivacyMode(" in html
    assert "localStorage.setItem('sb-privacy'" in html


def test_search_reveals_only_matches_when_masked():
    # Im Blur-Modus werden nur die Suchtreffer lesbar gemacht (gezielte Enthuellung).
    html = _html()
    assert "el.classList.toggle('reveal', !!q && match)" in html
    assert ".sb-scroll.blurred .client.reveal .client-n" in html
