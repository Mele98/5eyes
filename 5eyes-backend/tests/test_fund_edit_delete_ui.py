"""FUND-EDIT-DELETE-UI-MISSING-001 (Kontrollrunde 2026-09-27).

`PUT /products/{id}` existiert im Backend seit U-P10 (schemas/review.py::
ProductUpdate, inkl. is_active-Deaktivierung) -- aber die Fondsuniversum-
Suchergebnis-Tabelle (5eyes_v2.html #pf-search-tbody) war rein lesend. Ein
Berater konnte einen Tippfehler in einem erfassten Fonds (falsche ISIN,
falscher TER) nur ueber einen rohen API-Call oder erneuten CSV-Re-Upload
korrigieren; ein fälschlich angelegter Fonds liess sich gar nicht
deaktivieren.

Reiner Text-Scan-Test analog zum etablierten Muster fuer den HTML/JS-
Monolithen (siehe test_bug13a_frontend_bausteine_modal.py) -- fuehrt kein
JS aus, sperrt aber gegen ein stilles Verschwinden dieser Aktionen.
"""
from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

HTML_PATH = BACKEND_ROOT.parent / "5eyes-electron" / "frontend" / "5eyes_v2.html"


def _html() -> str:
    return HTML_PATH.read_text(encoding="utf-8")


def test_actions_column_exists_in_fund_table_header():
    text = _html()
    assert '<th>Aktionen</th>' in text


def test_edit_button_wired_to_admin_edit_fund():
    text = _html()
    assert "adminEditFund(" in text
    assert "function adminEditFund(productId)" in text


def test_deactivate_toggle_calls_put_with_is_active():
    text = _html()
    assert "function adminToggleFundActive(productId, currentlyActive)" in text
    assert "is_active: currentlyActive ? 0 : 1" in text
    assert "API.put('/products/' + encodeURIComponent(productId)" in text


def test_edit_reuses_put_products_endpoint_not_post():
    """Regression: Bearbeiten muss PUT auf die bestehende ID nutzen, nicht
    versehentlich POST (neuer Datensatz statt Update)."""
    text = _html()
    assert "API.put('/products/' + encodeURIComponent(adminFundEditingId)" in text


def test_edit_form_has_dynamic_title_and_button_label():
    text = _html()
    assert 'id="pf-form-title"' in text
    assert "Neuen Fonds erfassen" in text
    assert "Fonds bearbeiten: " in text
    assert "Aenderungen speichern" in text


def test_edit_state_is_reset_on_cancel_or_reopen():
    """Regression: ohne Reset wuerde ein Abbruch mitten im Bearbeiten-Modus
    den naechsten "+ Neuen Fonds erfassen"-Klick noch im Edit-Zustand
    belassen (falsche ID, falscher Button-Text)."""
    text = _html()
    assert "function adminResetFundForm()" in text
    assert "adminResetFundForm();" in text
    assert "adminFundEditingId = null;" in text


def test_search_results_are_cached_for_edit_lookup_without_extra_request():
    text = _html()
    assert "var adminFundSearchState = { products: [] };" in text
    assert "adminFundSearchState.products = products;" in text


def test_table_colspan_updated_for_new_actions_column():
    """Alle Platzhalter-Zeilen der Fonds-Suchtabelle muessen mit dem neuen
    6. Spalten-Layout uebereinstimmen -- ein vergessenes colspan="5" wuerde
    die Platzhalterzeile optisch verschieben."""
    text = _html()
    table_start = text.find('id="pf-search-tbody"')
    header_start = text.rfind('<thead>', 0, table_start)
    header_html = text[header_start:table_start]
    assert header_html.count("<th>") == 6

    assert 'colspan="6" style="color:var(--n4)">Suchbegriff eingeben' in text
    assert 'colspan="6" style="color:var(--n4)">Keine Fonds gefunden.' in text
    assert "colspan=\"6\">Suche laeuft..." in text
    assert "colspan=\"6\">Fehler</td>" in text


def test_deactivated_funds_are_visually_marked():
    text = _html()
    assert "(deaktiviert)" in text
    assert "opacity:.55" in text
