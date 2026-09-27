"""BASE-CURRENCY-HARDCODED-001 (Kontrollrunde 2026-09-27).

Die "Neues Mandat anlegen"-Maske (5eyes_v2.html, Modal #m-nc) verdrahtete
`base_currency` im createNewMandate()-Payload fest auf 'CHF' -- obwohl das
Backend (routers/mandates.py, schemas/mandates.py) base_currency frei pro
Mandat entgegennimmt. Jedes ueber die Standard-UI angelegte Fremdwaehrungs-
Mandat (z.B. EUR fuer ein DE-Mandat) blieb dadurch fuer immer auf CHF
eingefroren -- es gab im gesamten Frontend keinen einzigen UI-Pfad, um das
Feld je mit einem anderen Wert zu befuellen (weder bei Anlage noch
nachtraeglich).

Reiner Text-Scan-Test analog zum etablierten Muster fuer den HTML/JS-
Monolithen (siehe test_bug13a_frontend_bausteine_modal.py) -- fuehrt kein
JS aus, sperrt aber gegen ein stilles Zurueckkehren des Hardcodings.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

HTML_PATH = BACKEND_ROOT.parent / "5eyes-electron" / "frontend" / "5eyes_v2.html"


def _html() -> str:
    return HTML_PATH.read_text(encoding="utf-8")


def test_currency_selector_exists_in_new_mandate_modal():
    text = _html()
    assert 'id="nc-currency"' in text
    for expected_option in ('"CHF"', '"EUR"', '"USD"', '"GBP"', '"JPY"'):
        assert expected_option in text


def test_hardcoded_chf_literal_no_longer_used_in_payload():
    """Die urspruengliche Regression: base_currency: 'CHF' direkt im
    mandatePayload-Objektliteral -- muss verschwunden sein."""
    text = _html()
    assert "base_currency: 'CHF'" not in text


def test_payload_reads_currency_from_select_element():
    text = _html()
    assert "getElementById('nc-currency')" in text
    assert "base_currency: baseCurrency" in text


def test_currency_selector_appears_before_payload_construction():
    """Sanity: die Variable muss VOR ihrer Verwendung im Payload gelesen
    werden (keine Referenz auf eine spaeter deklarierte Variable)."""
    text = _html()
    read_pos = text.find("getElementById('nc-currency')")
    payload_pos = text.find("base_currency: baseCurrency")
    assert read_pos != -1
    assert payload_pos != -1
    assert read_pos < payload_pos


def test_default_option_is_chf_for_backwards_compatibility():
    """Erste <option> im Select muss CHF sein -- Default fuer bestehende
    CH-only-Kanzleien bleibt unveraendert (kein Verhaltensbruch, nur eine
    zusaetzliche, jetzt nutzbare Wahlmoeglichkeit)."""
    text = _html()
    select_start = text.find('id="nc-currency"')
    assert select_start != -1
    first_option_match = re.search(r'<option value="([A-Z]{3})"', text[select_start:])
    assert first_option_match is not None
    assert first_option_match.group(1) == "CHF"
