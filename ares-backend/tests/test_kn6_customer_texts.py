"""KN6 (H-177-Pruefung): Kundentexte nach Pruefgrundlage und ohne interne Begriffe.

* N-917R5-01: Der Kundentext der Geeignetheitspruefung richtet sich nach
  ``suitability_basis``. Execution-only und institutionelle Kunden sind von der
  Pruefpflicht ausgenommen -- dort steht, dass KEINE Pruefung durchgefuehrt
  wurde. Eine unbekannte/fehlende Grundlage ergibt «Pruefgrundlage nicht
  dokumentiert» mit Hinweis fuer den Berater, nie «liegt vor».
* N-917R5-02/-03: Bestandsstichtag + Pruefsumme statt Snapshot-UUID/Hash,
  kundengerechte Texte (Herfindahl-Index, Nachhaltigkeitsrichtlinie, keine
  «Matrix-Faktor»/«Override»/«Single-Country»/«Optimierer-Fallback»).

Gegenprobe: ``test_old_rule_would_claim_a_check_for_exempt_clients`` zeigt,
dass die alte Regel (nur ``is_compliant``) fuer Ausnahmekunden «liegt vor»
behauptete.
"""
from __future__ import annotations

import io

import pytest

from services.pdf.components.compliance_audit import (
    CUSTOMER_SUITABILITY_UNDOCUMENTED,
    customer_suitability_text,
)

CLAIM = "liegt die erforderliche Geeignetheitsprüfung vor"


def _audit(mandate_type: str, classification: str | None = None):
    """Echter Audit (services.suitability_audit) fuer die Ausnahmepfade, die
    ohne Datenbankzugriff auf das Risikoprofil enden."""
    from types import SimpleNamespace

    from services.suitability_audit import audit_mandate_suitability

    class _NoLogs:
        def query(self, *_a, **_k):
            raise RuntimeError("keine Datenbank im Unit-Test")

    mandate = SimpleNamespace(id="m-kn6", mandate_type=mandate_type,
                              client=SimpleNamespace(client_classification=classification or "Privatkunde"))
    return audit_mandate_suitability(_NoLogs(), mandate, include_sustainability_preference=False)


def _pdf_text(suitability: dict) -> str:
    from pypdf import PdfReader

    from services.pdf.documents.advisory_report import render_advisory_report_pdf_from_payload
    from tests.test_advisory_report_pdf import _make_minimal_payload

    payload = _make_minimal_payload()
    payload["suitability_compliance"] = suitability
    pdf = render_advisory_report_pdf_from_payload(payload)
    return " ".join(" ".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(pdf)).pages).split())


# -- N-917R5-01: je Pruefgrundlage ------------------------------------------


def test_geeignetheit_compliant_claims_the_check():
    status, text = customer_suitability_text({"suitability_basis": "risk_assessment", "is_compliant": True})
    assert status == "ok" and CLAIM in text


def test_geeignetheit_missing_says_missing():
    status, text = customer_suitability_text({"suitability_basis": "risk_assessment", "is_compliant": False})
    assert status == "missing" and "fehlt eine gültige Geeignetheitsprüfung" in text and CLAIM not in text


def test_angemessenheit_never_reads_as_geeignetheit():
    status, text = customer_suitability_text({"suitability_basis": "appropriateness", "is_compliant": True})
    assert status == "ok" and "Angemessenheitsprüfung" in text and "Art. 11 FIDLEG" in text
    assert CLAIM not in text
    status, text = customer_suitability_text({"suitability_basis": "appropriateness", "is_compliant": False})
    assert status == "missing" and "fehlt eine gültige Angemessenheitsprüfung" in text


def test_execution_only_from_real_audit_states_no_check():
    audit = _audit("Execution-only")
    assert audit["suitability_basis"] == "execution_only_exempt" and audit["is_compliant"] is True
    status, text = customer_suitability_text(audit)
    assert status == "not_required"
    assert text.startswith("Keine Geeignetheits- oder Angemessenheitsprüfung durchgeführt")
    assert "Execution-only" in text and CLAIM not in text


def test_institutional_from_real_audit_states_no_check():
    audit = _audit("Anlageberatung", "Institutioneller Kunde")
    assert audit["suitability_basis"] == "institutional_client_exempt" and audit["is_compliant"] is True
    status, text = customer_suitability_text(audit)
    assert status == "not_required"
    assert text.startswith("Keine Geeignetheitsprüfung durchgeführt") and "institutioneller Kunde" in text
    assert CLAIM not in text


@pytest.mark.parametrize("data", [
    {},
    {"is_compliant": True},
    {"suitability_basis": None, "is_compliant": True},
    {"suitability_basis": "unbekannt_xyz", "is_compliant": True},
    {"suitability_basis": "risk_assessment", "is_compliant": None},
])
def test_unknown_basis_is_neutral_with_advisor_hint(data):
    status, text = customer_suitability_text(data)
    assert status == "undocumented" and text == CUSTOMER_SUITABILITY_UNDOCUMENTED
    assert text.startswith("Prüfgrundlage nicht dokumentiert") and "Hinweis für den Berater" in text
    assert CLAIM not in text


def test_degraded_audit_is_not_a_claim():
    status, text = customer_suitability_text({"audit_degraded": True, "is_compliant": None,
                                              "suitability_basis": "degraded"})
    assert status == "degraded" and "Prüfung nicht möglich" in text


@pytest.mark.parametrize("suitability,expected,pill", [
    ({"suitability_basis": "execution_only_exempt", "is_compliant": True},
     "Keine Geeignetheits- oder Angemessenheitsprüfung durchgeführt", "nicht erforderlich"),
    ({"suitability_basis": "institutional_client_exempt", "is_compliant": True},
     "Keine Geeignetheitsprüfung durchgeführt", "nicht erforderlich"),
    ({"is_compliant": True}, "Prüfgrundlage nicht dokumentiert", "nicht dokumentiert"),
    ({"suitability_basis": "risk_assessment", "is_compliant": True}, CLAIM, "grün"),
])
def test_rendered_customer_pdf_per_basis(suitability, expected, pill):
    text = _pdf_text(suitability)
    assert expected in text and pill in text
    if expected != CLAIM:
        assert CLAIM not in text
    assert "Sektion 19 Compliance-Audit" in text and "Sektionen 19-23" not in text


def test_old_rule_would_claim_a_check_for_exempt_clients():
    """Gegenprobe: die alte Regel wertete nur ``is_compliant`` aus -> fuer
    Execution-only und institutionelle Kunden stand «liegt … vor»."""
    def old_rule(data):
        return (CLAIM if bool(data.get("is_compliant", True)) else "fehlt")

    for audit in (_audit("Execution-only"), _audit("Anlageberatung", "Institutioneller Kunde")):
        assert CLAIM in old_rule(audit)
        assert CLAIM not in customer_suitability_text(audit)[1]


# -- N-917R5-02/-03: Kundentexte ---------------------------------------------


def test_depotcheck_identity_line_is_stichtag_and_checksum():
    from services.pdf.base import DepotCheckData
    from services.pdf.documents.depotcheck import _snapshot_identity_line

    line = _snapshot_identity_line(DepotCheckData(
        mandate_number="M-KN6", analysis_snapshot_id="dca-0123456789abcdef01234567",
        snapshot_id="dps-abcdef0123456789abcdef01", snapshot_hash="0a1b2c3d" + "f" * 56, as_of="2026-10-26"))
    assert line == "Datenstand: Bestandsstichtag 26.10.2026, Prüfsumme 0a1b2c3d."
    assert "dps-" not in line and "dca-" not in line and "Snapshot" not in line


def test_matrix_factor_suffix_is_not_customer_text():
    from services.pdf.components.eignungspruefung import _answer_text

    for stored in ("Mehr als 12 Jahre · Matrix-Faktor", "Mehr als 12 Jahre - Matrix-Faktor"):
        assert _answer_text(8, {"answer_label": stored}, {}, {}) == "Mehr als 12 Jahre"
    assert _answer_text(9, {"answer_label": "Hoch"}, {}, {}) == "Hoch"


def test_concentration_texts_explain_the_herfindahl_index():
    from services.advisory_report import _check_branchen_konzentration, _check_diversifikation

    for hhi in (1000, 2000, 3000):
        country = _check_diversifikation({"concentration_hhi": {"country": hhi}})
        sector = _check_branchen_konzentration({"concentration_hhi": {"sector": hhi}})
        joined = " ".join(str(v) for v in (*country.values(), *sector.values()))
        assert f"Länderkonzentration (Herfindahl-Index) {hhi}" in joined
        assert f"Branchenkonzentration (Herfindahl-Index) {hhi}" in joined
        assert "HHI" not in joined and "Sleeve" not in joined


def test_limiting_factor_solver_label_is_customer_text():
    from services.pdf.components.goal_achievability import LIMITING_FACTOR_LABELS

    label = LIMITING_FACTOR_LABELS["solver_konvergenz"]
    assert "Optimierer" not in label and "Fallback" not in label


def test_contract_signoff_has_no_override_wording():
    import inspect

    from services.pdf.documents import contract_signoff

    source = inspect.getsource(contract_signoff)
    customer_strings = [line for line in source.splitlines() if '"' in line and "Override" in line
                        and not line.strip().startswith("#")]
    assert customer_strings == [], customer_strings

