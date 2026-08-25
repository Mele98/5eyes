"""Bug-#13a (2026-06-07): Frontend-Source-Parse fuer Baustein-Modal.

Backend-CRUD ist in PR #244 (test_bug13a_protocol_bausteine.py) gedeckt.
Hier nur Drift-Wache fuer das Modal + JS-Handler im 5eyes_v2.html.
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


def test_bug13a_marker_vorhanden():
    assert "Bug-#13a (2026-06-07)" in _html()


def test_modal_html_existiert():
    text = _html()
    assert 'id="m-bausteine"' in text
    assert ">Protokoll-Bausteine<" in text
    assert 'id="bausteine-list"' in text
    assert 'id="bausteine-status"' in text


def test_review_header_hat_button():
    text = _html()
    # Button im Review-Tab ph-more-Menue.
    assert ">Protokoll-Bausteine<" in text
    assert "openBausteineModal()" in text


def test_js_funktionen_vorhanden():
    text = _html()
    for fn in [
        "function openBausteineModal(",
        "function renderBausteineList(",
        "function toggleBausteinSelection(",
        "function createBausteinFromModal(",
        "function deleteBausteinFromModal(",
        "function saveMandateBausteinSelection(",
    ]:
        assert fn in text, f"Funktion fehlt: {fn}"


def test_js_ruft_backend_endpoints_richtig_auf():
    text = _html()
    # GET-Lib + GET-Selection
    assert "API.get('/protocol-bausteine')" in text
    assert "API.get('/mandates/'" in text and "protocol-bausteine" in text
    # POST-Create
    assert "API.post('/protocol-bausteine'" in text
    # DELETE
    assert "API.del('/protocol-bausteine/'" in text
    # PUT-Replace-Selection
    assert "API.put('/mandates/'" in text


def test_modal_inline_create_form_felder():
    text = _html()
    assert 'id="baustein-new-title"' in text
    assert 'id="baustein-new-content"' in text
    assert 'id="baustein-new-category"' in text


def test_globaler_baustein_nicht_loeschbar_in_ui():
    """Source-Parse: Render-Funktion unterscheidet zwischen advisor_id und
    global; nur fuer advisor-eigene Bausteine wird der Loesch-Button gerendert.
    Drift-Wache verhindert versehentliche UI-Loeschung globaler Bausteine."""
    text = _html()
    # Render-Block enthaelt: '(isGlobal?'':'<button class="btn-ico d"' usw.
    assert "isGlobal=!b.advisor_id" in text
    assert "isGlobal?'':'<button class=\"btn-ico d\"" in text
