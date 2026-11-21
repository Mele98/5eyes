"""KN9 (H-184-Pruefung, CTO-Nachtrag): Advisory-Report und Beratungsprotokoll.

* N-931-01 (fail-closed): ein Protokolleintrag mit ``integrity_verified is
  False`` (Pruefsumme passt nicht zum Inhalt) sperrt das Kunden-PDF des
  Advisory-Reports: 409 ``ADVISORY_LOG_INTEGRITY_FAILED`` mit deutscher
  Ursache. Kein Kundentext «Ihr Berater prüft den Eintrag» mehr. True und
  None (Alteintrag ohne Pruefsumme) bleiben erlaubt. Die Berater-Ansicht
  (Classic-Liste, React Sektion 16) warnt beim Eintrag.
* N-931-02: Kanal ohne Anzeigeform -> «—», nie der Rohschluessel.

Gegenprobe: ``test_counterprobe_old_renderer_would_print_the_customer_promise``
und die Kanal-Gegenprobe zeigen, was der alte Code tat.
"""
from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.test_kn8_protocol_integrity_display import (
    INTEGRITY_HASH, _flat, _payload, _service_entry)

REPO_ROOT = Path(__file__).resolve().parents[2]
FINMA_MODULE = REPO_ROOT / "ares-desktop" / "frontend" / "advisory-log-finma.js"
NODE = shutil.which("node")


# --- N-931-01: fail-closed im Renderer ------------------------------------------


def test_false_blocks_the_customer_pdf():
    from services.pdf.documents.advisory_report import (
        ADVISORY_LOG_INTEGRITY_FAILED_MESSAGE, AdvisoryLogIntegrityFailed,
        render_advisory_report_pdf_from_payload)

    payload = _payload(False)
    payload["beratungsprotokoll"]["latest_entry"]["id"] = "kn9-entry"
    with pytest.raises(AdvisoryLogIntegrityFailed) as exc:
        render_advisory_report_pdf_from_payload(payload)
    assert exc.value.entry_id == "kn9-entry"
    assert str(exc.value) == ADVISORY_LOG_INTEGRITY_FAILED_MESSAGE
    # Deutsche Ursache, einfache Sprache, kein Technikwort.
    assert "Prüfsumme" in str(exc.value) and "verändert oder ist beschädigt" in str(exc.value)
    for word in ("Hash", "integrity", "False"):
        assert word not in str(exc.value)


@pytest.mark.parametrize("state", [True, None, "false", 0])
def test_only_false_blocks(state):
    """True und None (Alteintrag) rendern; Nicht-bool-Werte gelten wie bisher
    als ungeprueft (nie «verifiziert»), sperren aber nicht."""
    from services.pdf.documents.advisory_report import render_advisory_report_pdf_from_payload

    pdf = render_advisory_report_pdf_from_payload(_payload(state))
    assert pdf[:4] == b"%PDF"
    text = _flat(pdf)
    assert "Ihr Berater prüft" not in text


def test_without_protocol_entry_nothing_blocks():
    from services.pdf.documents.advisory_report import (
        assert_advisory_log_integrity, render_advisory_report_pdf_from_payload)

    payload = _payload(True)
    payload["beratungsprotokoll"]["latest_entry"] = None
    assert_advisory_log_integrity(payload)
    assert_advisory_log_integrity({})
    assert_advisory_log_integrity({"beratungsprotokoll": None})
    assert render_advisory_report_pdf_from_payload(payload)[:4] == b"%PDF"


def test_real_chain_tampered_entry_blocks_and_untampered_renders():
    """Echte Kette: Hash beim Erfassen -> serialize_response -> PDF-Renderer.
    Unveraendert -> PDF mit «verifiziert»; nach Aenderung -> gesperrt."""
    from services.advisory_log_service import serialize_response
    from services.pdf.documents.advisory_report import (
        AdvisoryLogIntegrityFailed, render_advisory_report_pdf_from_payload)

    entry = _service_entry()
    payload = _payload()
    payload["beratungsprotokoll"]["latest_entry"] = serialize_response(entry)
    text = _flat(render_advisory_report_pdf_from_payload(payload))
    assert f"Prüfsumme {entry.integrity_hash[:8]}" in text and "verifiziert" in text

    entry.description = entry.description + " Nachtraeglich geaendert."
    payload["beratungsprotokoll"]["latest_entry"] = serialize_response(entry)
    assert payload["beratungsprotokoll"]["latest_entry"]["integrity_verified"] is False
    with pytest.raises(AdvisoryLogIntegrityFailed):
        render_advisory_report_pdf_from_payload(payload)


def test_render_advisory_report_pdf_blocks_on_the_aggregated_entry(monkeypatch):
    """render_advisory_report_pdf (Route-Pfad) nimmt den Eintrag aus dem
    Aggregator und sperrt ihn vor dem Rendern."""
    import services.pdf.documents.advisory_report as ar
    from services.advisory_log_service import serialize_response

    entry = _service_entry()
    entry.title = entry.title + " (geaendert)"
    payload = _payload()
    payload["beratungsprotokoll"]["latest_entry"] = serialize_response(entry)
    payload["cost_disclosure"] = {"lines": []}
    monkeypatch.setattr(ar, "compute_advisory_report", lambda db, mandate, advisor=None: payload)
    monkeypatch.setattr(ar, "_resolve_advisory_report_provisional_notice", lambda db, mandate: None)
    with pytest.raises(ar.AdvisoryLogIntegrityFailed) as exc:
        ar.render_advisory_report_pdf(None, SimpleNamespace(id="m-kn9"), None)
    assert exc.value.entry_id == "kn8-entry-1"


def test_route_maps_the_failure_to_409_with_catalogued_code(monkeypatch):
    """get_advisory_report_pdf: AdvisoryLogIntegrityFailed -> 409
    ADVISORY_LOG_INTEGRITY_FAILED mit deutscher Ursache (Gates hier neutral,
    sie sind eigene Tests)."""
    from fastapi import HTTPException

    import routers.pdf_reports as pr
    import services.portfolio_data_release_gate as pdg
    import services.recommendation_release_gate as rrg
    from core.reason_codes import ReasonCode
    from services.pdf.documents.advisory_report import (
        ADVISORY_LOG_INTEGRITY_FAILED_MESSAGE, AdvisoryLogIntegrityFailed)

    mandate = SimpleNamespace(id="m-kn9", mandate_number="M-KN9")
    monkeypatch.setattr(pr, "get_mandate_for_user_or_404", lambda mid, db, user: mandate)
    monkeypatch.setattr(pr, "_assert_client_pdf_kyc_review", lambda *a, **k: None)
    monkeypatch.setattr(pr, "gate_block_audit", lambda *a, **k: None)
    monkeypatch.setattr(rrg, "assert_recommendation_release_eligible", lambda *a, **k: None)
    monkeypatch.setattr(pdg, "assert_portfolio_data_release_eligible", lambda *a, **k: None)
    monkeypatch.setattr(pr, "_enforce_cma_currency_release", lambda *a, **k: None)
    monkeypatch.setattr(pr, "customer_document_watermark", lambda *a, **k: None)
    monkeypatch.setattr(pr, "evaluate_channel_envelope", lambda *a, **k: SimpleNamespace(
        applicable=False, ok=True, footer_ref=lambda: None))
    monkeypatch.setattr(pr, "kyc_release_is_draft", lambda *a, **k: False)

    def _raise(*_a, **_k):
        raise AdvisoryLogIntegrityFailed("log-kn9")

    monkeypatch.setattr(pr, "render_advisory_report_pdf", _raise)
    with pytest.raises(HTTPException) as exc:
        pr.get_advisory_report_pdf("m-kn9", db=None, current_user=SimpleNamespace(id="u"))
    assert exc.value.status_code == 409
    assert exc.value.detail == {
        "reason_code": ReasonCode.ADVISORY_LOG_INTEGRITY_FAILED.value,
        "message": ADVISORY_LOG_INTEGRITY_FAILED_MESSAGE,
        # L2c / N-936-06: neutral entry_id + entry_kind; advisory_log_id nur
        # bei echten Protokolleintraegen (hier ja).
        "entry_id": "log-kn9",
        "entry_kind": "advisory_log",
        "advisory_log_id": "log-kn9",
    }


def test_customer_promise_text_is_gone():
    """«Ihr Berater prüft den Eintrag» steht nirgends mehr im Renderer."""
    from services.pdf.documents import advisory_report as ar

    source = Path(ar.__file__).read_text(encoding="utf-8")
    assert "Ihr Berater prüft den Eintrag" not in source
    assert ar.integrity_status_display(False) == ("nicht verifiziert", "#9E4747")


def test_counterprobe_old_renderer_would_print_the_customer_promise():
    """Gegenprobe: ohne Sperre (alter Pfad = direkter Abschnitts-Render) steht
    der Eintrag mit «nicht verifiziert» im Kunden-PDF. Die Sperre ist also der
    einzige Grund, dass False das PDF nicht erreicht."""
    from services.pdf.documents import advisory_report as ar

    entry = _payload(False)["beratungsprotokoll"]["latest_entry"]
    block = ar._bp_latest_entry_block(entry, ar.make_advisory_styles())
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import SimpleDocTemplate

    buf = io.BytesIO()
    ar.register_editorial_fonts()
    SimpleDocTemplate(buf, pagesize=A4).build([block])
    text = _flat(buf.getvalue())
    assert "nicht verifiziert" in text and INTEGRITY_HASH[:8] in text


# --- N-931-02: Kanal-Fallback ----------------------------------------------------


@pytest.mark.parametrize("raw,expected", [
    ("persoenlich", "Persönlich"), ("telefon", "Telefon"), ("hybrid", "Hybrid"),
    (" video ", "Video"),
    ("vor_ort", "—"), ("Persoenlich", "—"), ("", "—"), (None, "—"),
])
def test_channel_display_never_shows_the_raw_key(raw, expected):
    from services.pdf.documents.advisory_report import communication_channel_display

    assert communication_channel_display(raw) == expected


def test_unknown_channel_in_the_pdf_shows_a_dash():
    from services.pdf.documents.advisory_report import render_advisory_report_pdf_from_payload

    payload = _payload(True)
    payload["beratungsprotokoll"]["latest_entry"]["communication_channel"] = "vor_ort"
    text = _flat(render_advisory_report_pdf_from_payload(payload))
    assert "vor_ort" not in text and "Vor_ort" not in text
    assert "· — ·" in text, text[-1500:]
    # Gegenprobe: die alte Regel (capitalize) haette den Rohschluessel gezeigt.
    assert "vor_ort".capitalize() == "Vor_ort"


# --- N-931-01: Berater-Ansicht Classic (Liste) ---------------------------------


def test_monolith_list_uses_the_module_card():
    from tests.monolith_source import read_monolith_bundle

    html = read_monolith_bundle()
    assert "root.innerHTML=items.map(advisoryLogCardHtml).join('');" in html
    assert "function advisoryLogCardHtml(" not in html
    source = FINMA_MODULE.read_text(encoding="utf-8")
    assert source.count("function advisoryLogCardHtml(") == 1
    assert "integrity_verified!==false" in source


def _card_html(entries: list[dict]) -> list[str]:
    script = (
        "function escapeHtml(v){return String(v==null?'':v).replace(/&/g,'&amp;')"
        ".replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/\"/g,'&quot;');}\n"
        "function formatDateSwiss(v){return String(v||'');}\n"
        + FINMA_MODULE.read_text(encoding="utf-8")
        + "\nconsole.log(JSON.stringify(" + json.dumps(entries) + ".map(advisoryLogCardHtml)));\n"
    )
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "run.js"
        path.write_text(script, encoding="utf-8")
        proc = subprocess.run([NODE, str(path)], capture_output=True, text=True,
                              encoding="utf-8", timeout=60, env=dict(os.environ))
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


@pytest.mark.skipif(NODE is None, reason="node nicht verfuegbar")
def test_classic_list_warns_only_at_the_failed_entry():
    base = {"title": "Jahresgespräch (fiktiv)", "status": "Empfohlen", "entry_date": "2026-11-20",
            "description": "Strategie besprochen (fiktiv)."}
    cards = _card_html([
        {**base, "id": "a", "integrity_verified": True},
        {**base, "id": "b", "integrity_verified": False},
        {**base, "id": "c", "integrity_verified": None},
        {**base, "id": "d"},
    ])
    assert ['role="alert"' in card for card in cards] == [False, True, False, False]
    warning = cards[1]
    assert "Prüfsumme passt nicht zum Inhalt" in warning
    assert "nicht als Kunden-PDF erzeugt" in warning
    # KN9a / N-934-01..02: Warnung nennt alle gesperrten Kundenkanaele.
    for channel in ("Beratungsprotokoll", "Beratungsentscheid", "Advisory-Report", "Kundenportal"):
        assert channel in warning, channel
    # Karte sonst unveraendert (Titel, Status-Knopf).
    for card in cards:
        assert "Jahresgespräch (fiktiv)" in card and "Beschlossen setzen" in card


# --- N-927T-01: Kommentar zum SQLite-Laufzeitpatch (Beleg der Aussage) ----------


def test_n927t01_old_sqlite_row_breaks_the_seal_so_the_chain_is_invalid():
    """Eine Freigabezeile von vor der H-179-Fixrunde wurde ohne die vier
    eingefrorenen Spalten gesiegelt. Der Laufzeitpatch fuegt sie mit NULL an;
    row_seal rechnet ueber ALLE Spalten -> das Siegel passt nicht mehr, und
    resolve_owner_content meldet kette_ungueltig (nicht bloss «Glied
    unwirksam»). Gegenprobe: dieselbe Zeile ohne die neuen Spalten passt."""
    from database import ensure_runtime_columns  # noqa: F401  (Patch existiert)
    from services.recommendation_release_gate import row_seal

    frozen = ("approver_role", "approver_ready", "approver_mailbox_digest", "creator_mailbox_digest")
    old_row = {
        "id": "appr-1", "tenant_id": "t-1", "content_key": "datenschutz.zwecke",
        "content_row_id": "row-1", "predecessor_approval_id": "GENESIS", "approved_by": "u-2",
        "approved_at": "2026-11-20T10:00:00Z", "approval_reference": "ref", "content_hash": "c" * 64,
    }
    old_seal = row_seal(old_row, "approval_hash")
    assert row_seal({**old_row, "approval_hash": old_seal}, "approval_hash") == old_seal
    patched = {**old_row, **{name: None for name in frozen}, "approval_hash": old_seal}
    assert row_seal(patched, "approval_hash") != old_seal

    source = (Path(__file__).resolve().parents[1] / "database.py").read_text(encoding="utf-8")
    block = source[source.index("H-179 N-927R-01 / N-927S-01"):source.index("'owner_content_approvals': [")]
    assert "kette_ungueltig" in block and "solche Glieder sind unwirksam" not in block
