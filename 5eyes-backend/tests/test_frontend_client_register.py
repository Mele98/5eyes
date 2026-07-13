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
    assert ".sb-az .az" in html  # A-Z-Sprungleiste


def test_names_hidden_by_default():
    # Privacy-first (Banking-Standard, revDSG Art. 7): Mandatsnamen sind NICHT auf den
    # ersten Blick sichtbar. Standard = nichts angezeigt, nicht persistiert.
    html = _html()
    assert "var registerShowAll = false" in html
    assert "else vis = false;" in html  # Standard: keine Zeile sichtbar
    assert "Buchstaben wählen oder suchen" in html
    assert "function applyRegisterView(" in html


def test_az_jump_rail():
    # Anklickbare A-Z-Leiste zum Springen (skaliert auf 1000+ Kunden).
    html = _html()
    assert 'id="sb-az"' in html
    assert "function selectRegisterLetter(" in html
    assert "ABCDEFGHIJKLMNOPQRSTUVWXYZ#" in html
    assert "az-off" in html and "az-active" in html


def test_client_letter_folds_diacritics():
    # Bug-Fix: Namen mit Diakritika (é/ç/ñ/à…) muessen unter ihrem ASCII-
    # Grundbuchstaben in der A-Z-Leiste landen, nicht unter '#'. Frueher wurden
    # nur Ä/Ö/Ü behandelt -> z.B. "Celik"->'#' unerreichbar ueber die Leiste.
    html = _html()
    az_block = html.split("function _clientLetter(", 1)[1].split("}", 1)[0]
    assert "normalize('NFD')" in az_block


def test_search_returns_to_private_default():
    # Bug-Fix: Wer aktiv sucht, verlaesst "Alle anzeigen"; das Leeren des
    # Suchfeldes darf NICHT alle Namen re-exponieren (Privacy-by-default).
    html = _html()
    filter_block = html.split("function filterClientRegister(", 1)[1].split("}", 1)[0]
    assert "registerShowAll = false" in filter_block
