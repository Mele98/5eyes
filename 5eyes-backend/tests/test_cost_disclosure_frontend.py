"""FIDLEG Art. 8/9 Ex-ante Kostenausweis — Frontend-Source-Parse.

Backend-Tests (PR 1 + PR 2) decken Endpoint + PDF; hier nur Drift-Wache
fuer den Portfolio-Tab-Button, das Modal und die JS-Handler im 5eyes_v2.html.
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


def test_portfolio_header_hat_kostenausweis_button():
    text = _html()
    assert 'id="btn-po-cost-disclosure"' in text
    assert "openCostDisclosureModal()" in text
    # Tooltip nennt FIDLEG-Basis, damit Berater versteht wofuer der Button.
    assert "FIDLEG Art. 8/9" in text


def test_modal_html_existiert():
    text = _html()
    assert 'id="m-cost-disclosure"' in text
    assert 'id="cd-status"' in text
    assert 'id="cd-content"' in text
    assert 'id="cd-summary"' in text
    assert 'id="cd-items"' in text
    assert 'id="cd-warnings"' in text


def test_js_funktionen_vorhanden():
    text = _html()
    for fn in [
        "function openCostDisclosureModal(",
        "function renderCostDisclosure(",
        "function downloadCostDisclosurePdf(",
        "function _formatRappenChf(",
    ]:
        assert fn in text, f"Funktion fehlt: {fn}"


def test_modal_laedt_endpoint():
    text = _html()
    assert "API.get('/mandates/'" in text
    assert "/cost-disclosure/ex-ante" in text


def test_pdf_download_route_in_downloadServerPdf_whitelist():
    """downloadServerPdf hat eine reportType-Whitelist (defensive); 'cost-disclosure'
    muss drin sein, sonst zeigt der Button nur eine Konsolen-Fehlermeldung."""
    text = _html()
    # Suche im downloadServerPdf-Block.
    idx = text.find("async function downloadServerPdf(")
    assert idx > 0
    # Whitelist sitzt am Anfang der Funktion (innerhalb der ersten ~2kB).
    block = text[idx:idx + 2500]
    assert "'cost-disclosure'" in block


def test_audit_auto_flag_setzt_cost_disclosure_given():
    """Bei PDF-Download wird ein AdvisoryLog-Eintrag mit
    cost_disclosure_given=true erzeugt (FINMA-Audit-Trail)."""
    text = _html()
    fn_start = text.find("async function downloadCostDisclosurePdf(")
    assert fn_start > 0
    block = text[fn_start:fn_start + 2200]
    assert "cost_disclosure_given: true" in block
    # FIDLEG-konforme Pflichtfelder im Payload.
    assert "entry_type: 'Sonstiges'" in block
    assert "entry_datetime:" in block
    assert "duration_minutes:" in block
    assert "communication_channel: 'persoenlich'" in block
    assert "topics: ['Ex-ante Kostenausweis']" in block


def test_audit_flag_ist_non_blocking_bei_fehler():
    """Wenn der Audit-Eintrag scheitert, darf der PDF-Download-Flow
    nicht crashen — try/catch + console.warn."""
    text = _html()
    fn_start = text.find("async function downloadCostDisclosurePdf(")
    block = text[fn_start:fn_start + 2000]
    assert "console.warn" in block
    assert "Audit-Auto-Flag fehlgeschlagen" in block


def test_modal_rendert_warnings_bei_pending():
    """renderCostDisclosure baut Warnings-UI nur wenn warnings.length>0."""
    text = _html()
    fn_start = text.find("function renderCostDisclosure(")
    block = text[fn_start:fn_start + 2000]
    assert "warnings.length" in block
    assert "Annahmen und Datenqualitaet" in block
