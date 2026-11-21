"""L2b (H-190): Beratungsvertrag in der Classic-Vertragsmaske im echten Browser.

Isoliertes Backend (Wegwerf-DB/HOME/APPDATA/KEK, freier Port), echte App
``/app/ares.html``, echter Login, echte Klicks:

1. Berater/Admin: Review & Abschluss > Dokumente > «Beratungsvertrag». Die
   Maske zeigt den Mandatstyp und «Vertragsvorlage nicht freigegeben».
2. Speichern ohne Ort -> deutsche Meldung (CONTRACT_PLACE_MISSING), nichts
   gespeichert (kein Vorgabe-Ort).
3. Mit Ort speichern -> Quelldokument «Beratungsvertrag» mit Ort.
4. Vorschau -> Entwurf mit Wasserzeichen (Server-Header), Gruende auf Deutsch,
   nichts archiviert, nichts signierbar.
5. Signatur-Sperre der Vertragsschicht: deutsche Ursache je Befund.
6. Rolle «Lesend»: sieht Mandatstyp und Status, kein Speichern/Vorschau; die
   API verweigert das Anlegen (403).

Keine Owner-Texte: die Vorlage bleibt unfreigegeben (Grundsatz: Ares erfindet
keinen Vertragstext). Pflichtlauf im CI-Job «Frontend Reporting Tests».
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from tests.test_livetest_k2_kernkette_ui import CLOSE, _Api, _load, _open, _sync_api
from tests.test_livetest_kern_integration_r2 import _backend
from tests.test_livetest_kn3_u_ui import _new_client, _page

BACKEND = Path(__file__).resolve().parents[1]
RO_USER, RO_PWD, RO_PWD2 = "l2b.lesend", "L2b-Lesend-Passwort-2026!x", "L2b-Lesend-Neu-2026!y"


@pytest.fixture(scope="module")
def server():
    _sync_api()
    with _backend(frozen=False) as srv:
        yield srv


def test_ci_runs_this_ui_test_with_playwright_required():
    workflow = (BACKEND.parent / ".github" / "workflows" / "test.yml").read_text(encoding="utf-8")
    job = workflow[workflow.index("\n  vitest:"):]
    assert "tests/test_livetest_l2b_advice_contract_ui.py" in job
    assert 'ARES_REQUIRE_PLAYWRIGHT: "1"' in job


def _contract_docs(api, mid):
    st, docs = api("GET", f"/mandates/{mid}/documents")
    assert st == 200, docs
    return [d for d in docs if d.get("document_type") == "Beratungsvertrag"]


def _pdf_headers(api, mid, doc_id) -> dict:
    import urllib.request

    req = urllib.request.Request(f"{api.base}/mandates/{mid}/reports/vertrag.pdf?document_id={doc_id}")
    req.add_header("Authorization", "Bearer " + api.token)
    with urllib.request.urlopen(req, timeout=120) as resp:
        assert resp.status == 200 and resp.read(5) == b"%PDF-"
        return {k.lower(): v for k, v in resp.headers.items()}


def _open_contract_mask(page):
    page.wait_for_selector("#btn-rv-advice-contract", state="visible", timeout=30000)
    page.click("#btn-rv-advice-contract")
    page.wait_for_selector("#m-advice-contract.open", timeout=15000)
    page.wait_for_function("() => /Mandatstyp:/.test(document.getElementById('ac-template').innerText)", timeout=30000)


def test_advisor_creates_contract_place_required_preview_is_draft(server):
    sync_api = _sync_api()
    api = _Api(server["base"]).login()
    cid, mid, _ = _new_client(api, "Lea", "Vertrag-Fiktiv", "1979-05-05", [], risk=False,
                              mandate_type="Anlageberatung")
    assert _contract_docs(api, mid) == []
    with sync_api.sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        errors: list[str] = []
        try:
            page = _page(browser, server, sync_api, errors)
            _load(page, cid, "rv")
            _open_contract_mask(page)
            template = page.inner_text("#ac-template")
            assert "Mandatstyp: Anlageberatung" in template, template
            assert "Vertragsvorlage nicht freigegeben" in template, template
            assert page.input_value("#ac-place") == ""  # kein Vorgabe-Ort
            assert page.is_disabled("#btn-ac-preview")

            # 2. ohne Ort: Meldung, nichts gespeichert.
            page.click("#btn-ac-save")
            page.wait_for_selector("#ac-error", state="visible")
            assert "Ort der Unterzeichnung fehlt" in page.inner_text("#ac-error")
            assert _contract_docs(api, mid) == []

            # 3. mit Ort: Quelldokument gespeichert.
            page.fill("#ac-place", "Testort (fiktiv)")
            page.click("#btn-ac-save")
            page.wait_for_function("() => /Entwurf gespeichert/.test(document.getElementById('ac-result').innerText)",
                                   timeout=30000)
            docs = _contract_docs(api, mid)
            assert len(docs) == 1 and docs[0]["status"] == "Entwurf" and not docs[0]["has_pdf"], docs
            assert docs[0]["title"] == "Beratungsvertrag – Anlageberatung"
            # Der Ort ist gespeichert: der Server nennt ihn nicht mehr als Entwurfsgrund.
            headers = _pdf_headers(api, mid, docs[0]["id"])
            assert headers["x-ares-draft"] == "vertragsvorlage", headers
            assert "CONTRACT_PLACE_MISSING" not in headers["x-ares-draft-reasons"], headers
            assert "CONTRACT_TEMPLATE_UNAPPROVED" in headers["x-ares-draft-reasons"], headers

            # 4. Vorschau: Entwurf mit Wasserzeichen, Gruende auf Deutsch.
            page.wait_for_selector("#btn-ac-preview:not([disabled])", timeout=30000)
            page.click("#btn-ac-preview")
            page.wait_for_function("() => /Entwurf \\(Wasserzeichen/.test(document.getElementById('ac-result').innerText)",
                                   timeout=60000)
            result = page.inner_text("#ac-result")
            assert "nicht signierbar" in result and "Vertragsvorlage für diesen Mandatstyp" in result, result
            assert "CONTRACT_" not in result, result  # keine Rohcodes fuer den Berater
            docs = _contract_docs(api, mid)
            assert len(docs) == 1 and not docs[0]["has_pdf"], docs  # nichts archiviert

            # Dokumentliste: Quelldokument mit «Vertrag erstellen (PDF)», ohne Signieren.
            page.evaluate(CLOSE)
            page.wait_for_selector("button[data-doc-action='advice-contract-preview']", timeout=30000)
            assert page.locator("button[data-doc-action='sign-advisor']").count() == 0

            # 5. Signatur-Sperre der Vertragsschicht: deutsche Ursache je Befund
            #    (Befunde vom echten Server, Form wie die 409 der Signatur).
            message = page.evaluate("""async (mid) => {
              const s = await API.get('/mandates/' + mid + '/contract-layer');
              const body = JSON.stringify({detail: {reason_code: 'CONTRACT_LAYER_INCOMPLETE',
                message: 'Signatur nicht möglich', findings: s.findings}});
              return releaseGateMessage({body: body});
            }""", mid)
            assert message.startswith("Vertragsabschluss gesperrt"), message
            assert "Vertragsvorlage" in message and "(" in message, message
            outdated = page.evaluate("""() => releaseGateMessage({body: JSON.stringify({detail:
              {reason_code: 'CONTRACT_LAYER_INCOMPLETE', findings: [{reason_code: 'CONTRACT_TEMPLATE_OUTDATED'}]}})})""")
            assert "nicht auf der aktuell freigegebenen Vertragsvorlage" in outdated, outdated
        finally:
            browser.close()
    assert not errors, errors


def test_readonly_sees_status_but_cannot_write(server):
    """«Lesend» sieht Kunden, denen er zugeordnet ist (Sichtbarkeit wie im
    Bestand: advisor_id), und darf dort nicht schreiben."""
    sync_api = _sync_api()
    api = _Api(server["base"]).login()
    st, body = api("POST", "/users", {"username": RO_USER, "password": RO_PWD, "full_name": "Lesend Fiktiv",
                                      "role": "readonly"})
    assert st == 201, body
    ro_id = body["id"]
    ro = _Api(server["base"])
    st, body = ro("POST", "/auth/login", {"username": RO_USER, "password": RO_PWD})
    assert st == 200, body
    ro.token = body["access_token"]
    # Erst-Passwortwechsel (must_change_password), danach normal angemeldet.
    st, body = ro("POST", "/auth/change-password", {"current_password": RO_PWD, "new_password": RO_PWD2})
    assert st == 200, body
    st, body = ro("POST", "/auth/login", {"username": RO_USER, "password": RO_PWD2})
    assert st == 200, body
    ro.token = body["access_token"]
    stamp = time.time_ns()
    st, client = api("POST", "/clients", {"client_number": f"L2B-{stamp}", "first_name": "Rea",
                                          "last_name": "Lesend-Fiktiv", "advisor_id": ro_id,
                                          "household_type": "Einzelperson", "date_of_birth": "1981-06-06"})
    assert st == 201, client
    cid = client["id"]
    st, mandate = api("POST", f"/clients/{cid}/mandates", {"mandate_number": f"M-L2B-{stamp}",
                                                          "mandate_type": "Vermögensverwaltung"})
    assert st == 201, mandate
    mid = mandate["id"]
    # Server: «Lesend» sieht das Mandat, legt aber keinen Vertrag an (Rolle, nicht Sichtbarkeit).
    assert ro("GET", f"/mandates/{mid}/contract-layer")[0] == 200
    st, body = ro("POST", f"/mandates/{mid}/documents", {"document_type": "Beratungsvertrag", "title": "x",
                                                        "content_json": json.dumps({"ort_unterzeichnung": "x"})})
    assert st == 403 and b"Schreibberechtigung" in body, body
    with sync_api.sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        errors: list[str] = []
        try:
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.on("pageerror", lambda exc: errors.append(str(exc)))
            _open(page, server["base"], sync_api)
            page.fill("#login-username", RO_USER)
            page.fill("#login-password", RO_PWD2)
            page.evaluate("document.getElementById('btn-login-submit').click()")
            page.wait_for_function("() => typeof currentUser !== 'undefined' && !!currentUser && currentUser.role === 'readonly'",
                                   timeout=30000)
            page.wait_for_timeout(1500)
            _load(page, cid, "rv")
            _open_contract_mask(page)
            assert "Mandatstyp: Vermögensverwaltung" in page.inner_text("#ac-template")
            assert page.is_visible("#ac-readonly")
            assert not page.is_visible("#btn-ac-save") and not page.is_visible("#btn-ac-preview")
            assert page.is_disabled("#ac-place")
            page.evaluate(CLOSE)
            assert page.locator("button[data-doc-action='advice-contract-preview']").count() == 0
        finally:
            browser.close()
    assert _contract_docs(api, mid) == []
    time.sleep(0.1)
    assert not errors, errors


# --- L2c (H-192): N-936-02/-03 -- «final» ueber die Pruefsumme ---------------

def test_l2c_final_is_detected_by_checksum_and_archived_contract_button(server):
    """Die Server-Antworten werden im Browser nachgestellt (die Vorlage bleibt
    unfreigegeben, Ares erfindet keinen Vertragstext):

    a) Wiederholter finaler Abruf (Dedupe, keine neue Archiv-ID): PDF ohne
       X-Ares-Draft, Pruefsumme = checksum_sha256 eines archivierten Vertrags
       -> «final» (vorher faelschlich «Entwurf», N-936-02).
    b) Race: X-Ares-Draft gesetzt, gleichzeitig fremdes Archiv mit derselben
       Pruefsumme -> «Entwurf» (Header hat Vorrang, N-936-03).
    c) Pruefsumme passt zu keinem Archiv -> «Entwurf».
    d) Dokumentliste: finalisierter Entwurf zeigt «Archivierten Vertrag
       öffnen» statt «Vertrag erstellen (PDF)».
    """
    import hashlib

    sync_api = _sync_api()
    api = _Api(server["base"]).login()
    cid, mid, _ = _new_client(api, "Mia", "Pruefsumme-Fiktiv", "1980-02-02", [], risk=False,
                              mandate_type="Anlageberatung")
    st, draft = api("POST", f"/mandates/{mid}/documents", {
        "document_type": "Beratungsvertrag", "title": "Beratungsvertrag – Anlageberatung",
        "content_json": json.dumps({"ort_unterzeichnung": "Testort (fiktiv)"})})
    assert st == 201, draft
    final_pdf = b"%PDF-1.4\n% L2c final (fiktiv)\n%%EOF\n"
    checksum = hashlib.sha256(final_pdf).hexdigest()
    archived = {"id": "arch-l2c", "mandate_id": mid, "document_type": "Beratungsvertrag",
                "title": "Beratungsvertrag – Anlageberatung", "status": "Archiviert", "signed_by_advisor": 0,
                "signed_by_client": 0, "signed_at": None, "version": 2, "supersedes_id": None, "pdf_path": None,
                "checksum_sha256": checksum, "has_pdf": True, "source_document_id": draft["id"],
                "created_by": "x", "created_at": "2026-11-21T10:00:00.000Z", "updated_at": "2026-11-21T10:00:00.000Z"}
    mode = {"draft_header": False, "with_archive": True}

    def _pdf(route):
        headers = {"Content-Type": "application/pdf", "Content-Disposition": 'attachment; filename="vertrag.pdf"'}
        if mode["draft_header"]:
            headers.update({"X-Ares-Draft": "vertragsvorlage", "X-Ares-Draft-Reasons": "CONTRACT_TEMPLATE_UNAPPROVED"})
        route.fulfill(status=200, headers=headers, body=final_pdf if mode["with_archive"] else b"%PDF-anders")

    def _docs(route):
        if route.request.method != "GET":
            return route.continue_()
        resp = route.fetch()
        data = resp.json()
        route.fulfill(response=resp, json=([archived] + data) if mode["with_archive"] else data)

    with sync_api.sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        errors: list[str] = []
        try:
            page = _page(browser, server, sync_api, errors)
            page.route("**/reports/vertrag.pdf*", _pdf)
            page.route(f"**/mandates/{mid}/documents", _docs)
            _load(page, cid, "rv")

            def _preview():
                page.evaluate("() => { const r = document.getElementById('ac-result'); if (r) r.textContent = ''; }")
                page.evaluate("(id) => openAdviceContractModal(id).then(() => previewAdviceContract(id))", draft["id"])
                page.wait_for_function("() => (document.getElementById('ac-result').innerText || '').length > 0",
                                       timeout=60000)
                return page.inner_text("#ac-result")

            text_a = _preview()
            assert text_a.startswith("Vertrag final erstellt und archiviert"), text_a
            mode["draft_header"] = True
            text_b = _preview()
            assert text_b.startswith("Entwurf (Wasserzeichen"), text_b
            mode.update(draft_header=False, with_archive=False)
            text_c = _preview()
            assert text_c.startswith("Entwurf (Wasserzeichen"), text_c

            mode["with_archive"] = True
            page.evaluate(CLOSE)
            page.evaluate("(mid) => refreshReviewUI(mid)", mid)
            page.wait_for_selector("button[data-doc-action='advice-contract-open-archived']", timeout=30000)
            assert page.inner_text("button[data-doc-action='advice-contract-open-archived']") == "Archivierten Vertrag öffnen"
            assert page.locator("button[data-doc-action='advice-contract-preview']").count() == 0
        finally:
            browser.close()
    assert not errors, errors
