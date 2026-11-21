"""KN8 / N-929-01 (H-182-Pruefung, CTO-Nachtrag): Advisory-Report Sektion 16.

Vorher zeigte der letzte Beratungsprotokoll-Eintrag im Kunden-PDF die ersten
16 Zeichen des Integritaets-Hashes und fest «verifiziert» -- auch wenn
``integrity_verified`` (services/advisory_log_service.verify_entry_integrity)
False oder None war. Jetzt:

* Kurzreferenz ueber ``core.customer_terms.short_reference`` (8 Zeichen, wie
  Protokoll, Risikoprofil und Depotcheck); keine Hex-Folge ab 16 Zeichen.
* Pruefergebnis aus ``integrity_verified``: True -> «verifiziert», False ->
  «nicht verifiziert» (Warnfarbe), None/fehlt/anderer Wert -> «nicht geprueft».
  Nie «verifiziert» ohne True.

Gegenprobe: ``test_old_rendering_fails_the_rules`` rendert den alten Text und
zeigt, dass die Regeln hier rot werden.
"""
from __future__ import annotations

import io
import re

import pytest

from tests.test_kn7_customer_suitability_and_references import internal_id_hits

# Synthetischer Testvektor (kein echter Hash eines Eintrags).
INTEGRITY_HASH = "a3f9c2e81b7d4c6f9e0a1b2c3d4e5f60718293a4b5c6d7e8f9a0b1c2d3e4f5a6"
SHORT = INTEGRITY_HASH[:8]
_MISSING = object()


def _payload(integrity_verified=_MISSING, integrity_hash=INTEGRITY_HASH) -> dict:
    from tests.test_advisory_report_pdf import _make_minimal_payload

    entry = {
        "entry_type": "Jahresreview", "title": "Jahresgespräch (fiktiv)",
        "entry_date": "2026-11-20", "status": "Empfohlen", "topics": ["Strategie"],
        "risk_warnings_given": [], "integrity_hash": integrity_hash,
    }
    if integrity_verified is not _MISSING:
        entry["integrity_verified"] = integrity_verified
    payload = _make_minimal_payload()
    payload["beratungsprotokoll"] = {
        "total_active": 1, "retention_audit_ok": True, "latest_entry": entry}
    return payload


def _flat(pdf: bytes) -> str:
    from pypdf import PdfReader

    return " ".join(" ".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(pdf)).pages).split())


def _section16(integrity_verified=_MISSING, **kw) -> str:
    from services.pdf.documents.advisory_report import render_advisory_report_pdf_from_payload

    text = _flat(render_advisory_report_pdf_from_payload(_payload(integrity_verified, **kw)))
    i = text.find("INTEGRIT")
    assert i >= 0, text[-1500:]
    return text[i:i + 120]


def integrity_claim_violations(line: str, integrity_verified) -> list[str]:
    """Regeln fuer die INTEGRITAET-Zeile im Kunden-PDF (auch fuer die Gegenprobe)."""
    found = []
    if internal_id_hits(line):
        found.append("hex>=16")
    says_verified = re.search(r"(?<!nicht )verifiziert", line) is not None
    if says_verified and integrity_verified is not True:
        found.append("verifiziert ohne True")
    if integrity_verified is True and not says_verified:
        found.append("True ohne verifiziert")
    if integrity_verified is False and "nicht verifiziert" not in line:
        found.append("False ohne «nicht verifiziert»")
    if integrity_verified is not True and integrity_verified is not False and "nicht geprüft" not in line:
        found.append("ungeprueft ohne «nicht geprüft»")
    return found


@pytest.mark.parametrize("state,expected", [
    (True, "verifiziert"),
    (False, "nicht verifiziert"),
    (None, "nicht geprüft"),
    (_MISSING, "nicht geprüft"),
    ("true", "nicht geprüft"),  # kein bool -> nie als bestanden gewertet
])
def test_section16_status_follows_integrity_verified(state, expected):
    line = _section16(state)
    assert f"Prüfsumme {SHORT}" in line, line
    assert expected in line, line
    assert integrity_claim_violations(line, state) == [], line
    assert INTEGRITY_HASH[:16] not in line


def test_section16_without_hash_shows_no_integrity_claim():
    from services.pdf.documents.advisory_report import render_advisory_report_pdf_from_payload

    text = _flat(render_advisory_report_pdf_from_payload(_payload(None, integrity_hash=None)))
    assert "INTEGRIT" not in text
    assert "verifiziert" not in text


def test_status_display_colors():
    """False in Warnfarbe (wie «nicht gültig» in Sektion 27), None neutral."""
    from services.pdf.documents.advisory_report import integrity_status_display

    assert integrity_status_display(True) == ("verifiziert", "#4E6F58")
    text, color = integrity_status_display(False)
    assert text.startswith("nicht verifiziert") and color == "#9E4747"
    for value in (None, "true", 1, "ok"):
        assert integrity_status_display(value) == ("nicht geprüft", "#7A8395")


def test_old_rendering_fails_the_rules():
    """Gegenprobe: der alte Text (16 Zeichen + festes «verifiziert», Befund-Probe
    H-182) verletzt die Regeln fuer False und None; der neue nicht."""
    old = f"INTEGRITÄT {INTEGRITY_HASH[:16]}… verifiziert"
    assert "hex>=16" in integrity_claim_violations(old, True)
    assert "verifiziert ohne True" in integrity_claim_violations(old, False)
    assert "verifiziert ohne True" in integrity_claim_violations(old, None)
    new_false = f"INTEGRITÄT Prüfsumme {SHORT} · nicht verifiziert – Ihr Berater prüft den Eintrag"
    assert integrity_claim_violations(new_false, False) == []


def _service_entry():
    """Eintrag als echtes (nicht gespeichertes) Modell mit Hash wie beim Erfassen."""
    import json

    from models.review import AdvisoryLog
    from services.advisory_log_integrity import compute_integrity_hash
    from services.advisory_log_service import build_hash_payload

    entry = AdvisoryLog(
        id="kn8-entry-1", mandate_id="kn8-mandate-1", advisor_id="kn8-advisor-1",
        entry_type="Jahresreview", title="Jahresgespräch (fiktiv)",
        description="Strategie und Risiko besprochen, keine Änderung (fiktiv).",
        status="Empfohlen", entry_datetime="2026-11-20T10:00:00.000Z", entry_date="2026-11-20",
        duration_minutes=45, communication_channel="persoenlich", language="de",
        participants_json="[]", topics_json=json.dumps(["Strategie"]),
        risk_warnings_given_json="[]", cost_disclosure_given=True,
        conflict_disclosure_ids_json="[]", client_signed=False, version=1,
    )
    entry.integrity_hash = compute_integrity_hash(payload=build_hash_payload(entry))
    return entry


def test_service_value_reaches_the_pdf():
    """Echte Kette: Hash beim Erfassen -> serialize_response -> PDF. Unveraendert
    «verifiziert»; nach Aenderung eines gehashten Feldes «nicht verifiziert»."""
    from services.advisory_log_service import serialize_response
    from services.pdf.documents.advisory_report import render_advisory_report_pdf_from_payload

    entry = _service_entry()
    for tamper, expected in ((False, True), (True, False)):
        if tamper:
            entry.description = entry.description + " Nachtraeglich geaendert."
        serialized = serialize_response(entry)
        assert serialized["integrity_verified"] is expected
        payload = _payload()
        payload["beratungsprotokoll"]["latest_entry"] = serialized
        text = _flat(render_advisory_report_pdf_from_payload(payload))
        line = text[text.find("INTEGRIT"):text.find("INTEGRIT") + 120]
        assert f"Prüfsumme {entry.integrity_hash[:8]}" in line, line
        assert integrity_claim_violations(line, expected) == [], line
        assert entry.integrity_hash[:16] not in text


def test_every_communication_channel_has_a_display_form():
    """KN8 (Live-Fall): der Kanal steht als Anzeigeform im Kunden-PDF, nie als
    Schluessel mit ASCII-Umschrift («Persoenlich»)."""
    from typing import get_args

    from schemas.review import CommunicationChannel
    from services.pdf.documents.advisory_report import (
        COMMUNICATION_CHANNEL_DISPLAY, render_advisory_report_pdf_from_payload)

    assert set(COMMUNICATION_CHANNEL_DISPLAY) == set(get_args(CommunicationChannel))
    payload = _payload(True)
    payload["beratungsprotokoll"]["latest_entry"]["communication_channel"] = "persoenlich"
    text = _flat(render_advisory_report_pdf_from_payload(payload))
    # (Der Testfixture-Untertitel «Persoenlicher Advisory-Report» ist kein Kanal.)
    assert re.search(r"· Persönlich ·", text), text[-1500:]
    assert not re.search(r"Persoenlich", text)
