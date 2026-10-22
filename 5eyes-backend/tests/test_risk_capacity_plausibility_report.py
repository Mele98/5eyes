"""RISK-CAPACITY-REPORT-001: Plausibilitaetspruefung Risikofaehigkeit im
Advisory-Report (Payload + PDF) und im Strategie-PDF (Anlagestrategie).

Befund: der Status der Plausibilitaetspruefung (consistent/partial/
inconsistent/not_evaluable) war nur im Monolith und im Risikoprofil-PDF
sichtbar. Advisory-Report-PDF und Strategie-PDF hatten bei ``partial`` und
``inconsistent`` keinen Hinweis. Der Hinweis gehoert in den Beraterteil, ohne
Betraege und ohne Aussage ueber den Kunden.

CIO-Entscheid 2026-10-21: der Hinweis gehoert NUR in den internen
Advisory-Report (und die React-Berateransicht), NICHT in das vom Kunden
unterzeichnete Anlagestrategie-PDF; ``not_evaluable`` erhaelt ebenfalls einen
Hinweis (fehlende Daten bleiben nie stumm); die Pruefung laeuft ueber den
Aggregator-Cache (keine Zusatz-Queries).
"""
from __future__ import annotations

import re
import sys
from datetime import date
from io import BytesIO
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = Path(__file__).resolve().parent
for _p in (BACKEND_ROOT, TESTS_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from main import app  # noqa: F401,E402  (Modell-Registrierung)
from services import risk_capacity_plausibility as rcp  # noqa: E402
from services.risk_capacity_plausibility_report import (  # noqa: E402
    NOT_EVALUABLE_NOTE,
    PDF_NOTE_PREFIX,
    advisor_report_note,
    compact_view,
)


def _result(status: str, *, findings=(), open_checks=(), **extra) -> dict:
    base = {
        "version": rcp.PLAUSIBILITY_RULES_VERSION,
        "status": status,
        "reason_code": rcp.REASON_CODE if findings else None,
        "findings": [
            {
                "check": c,
                "question_number": 3,
                "declared": "CHF 12'000 bis 20'000",
                "recorded": "CHF 4'000",
                "message": "Frage 3: erfasst CHF 4'000 pro Monat.",
            }
            for c in findings
        ],
        "not_evaluable": [
            {"check": c, "question_number": 5, "reason": "Keine Ausgaben erfasst."}
            for c in open_checks
        ],
        "coverage": {},
        "capacity_binding": True,
        "override_down": False,
        "thresholds": {},
        "data_basis": {"gross_income_monthly_rappen": 400_000},
        "advisor_text": "",
    }
    base.update(extra)
    return base


INCONSISTENT = _result("inconsistent", findings=(rcp.CHECK_INCOME, rcp.CHECK_LEVERAGE))
PARTIAL = _result("partial", open_checks=(rcp.CHECK_OBLIGATIONS, rcp.CHECK_SAVINGS))
CONSISTENT = _result("consistent")
NOT_EVALUABLE = _result("not_evaluable", open_checks=("ALL",))

_AMOUNT_RE = re.compile(r"(CHF|EUR|USD|Rappen|\d+'\d{3}|\d+\s*%|\d{4,})")
_CLIENT_CLAIM_RE = re.compile(r"(Kunde|Kundin|Verlusttragf|Garantie|garantiert)", re.I)


# ---------------------------------------------------------------------------
# Hinweistext: nur partial/inconsistent, betragsfrei, neutral
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "result", [INCONSISTENT, PARTIAL, NOT_EVALUABLE],
    ids=["inconsistent", "partial", "not_evaluable"],
)
def test_note_is_neutral_and_amount_free(result):
    note = advisor_report_note(result)
    assert note.startswith(PDF_NOTE_PREFIX)
    assert "Beraterhinweis" in note
    assert "nicht automatisch verändert" in note
    assert not _AMOUNT_RE.search(note), note
    assert not _CLIENT_CLAIM_RE.search(note), note


def test_not_evaluable_note_asks_for_financial_data():
    note = advisor_report_note(NOT_EVALUABLE)
    assert note == NOT_EVALUABLE_NOTE
    assert "mangels Daten nicht prüfbar" in note
    assert "Finanzdaten erfassen" in note


def test_inconsistent_note_names_affected_checks_without_messages():
    note = advisor_report_note(INCONSISTENT)
    assert "weichen" in note
    assert "Frage 3 Einkommen" in note and "Verschuldung" in note
    assert "erfasst CHF" not in note


def test_partial_note_names_open_checks():
    note = advisor_report_note(PARTIAL)
    assert "noch nicht vollständig geprüft" in note
    assert "Frage 5 Verpflichtungen" in note and "Frage 7 Sparquote" in note


@pytest.mark.parametrize(
    "result", [CONSISTENT, None, {}, {"status": "kaputt"}],
    ids=["consistent", "none", "empty", "unknown"],
)
def test_no_note_for_consistent_or_missing_result(result):
    assert advisor_report_note(result) == ""


def test_unknown_check_ids_are_not_printed_raw():
    note = advisor_report_note(_result("partial", open_checks=("ALL", "FUTURE_CHECK")))
    assert "ALL" not in note and "FUTURE_CHECK" not in note
    assert note.endswith("nicht automatisch verändert.")


def test_compact_view_is_amount_free_and_tolerates_new_optional_fields():
    future = _result(
        "partial", open_checks=(rcp.CHECK_OBLIGATIONS,),
        verification_code="RISK_CAPACITY_NOT_VERIFIED",
        resolution_actions=["Ausgaben erfassen oder Vollstaendigkeit bestaetigen."],
        coverage_attestation={"status": "missing"},
    )
    view = compact_view(future)
    assert view["status"] == "partial"
    assert view["open_checks"] == [rcp.CHECK_OBLIGATIONS]
    assert view["finding_checks"] == []
    assert view["verification_code"] == "RISK_CAPACITY_NOT_VERIFIED"
    assert "resolution_actions" not in view  # freie Texte nicht in den Report-Payload
    assert view["note"] == advisor_report_note(future)
    assert "data_basis" not in view and "findings" not in view

    legacy = compact_view(INCONSISTENT)
    assert legacy["reason_code"] == rcp.REASON_CODE
    assert legacy["finding_checks"] == [rcp.CHECK_INCOME, rcp.CHECK_LEVERAGE]
    assert legacy["verification_code"] is None


def test_compact_view_unknown_status_is_never_consistent():
    view = compact_view({"status": "irgendwas"})
    assert view["status"] == "not_evaluable"
    assert view["note"] == NOT_EVALUABLE_NOTE
    assert compact_view(None) is None


# ---------------------------------------------------------------------------
# Advisory-Report: Payload (Aggregator) + PDF-Sektion Eignungspruefung
# ---------------------------------------------------------------------------

def _pdf_text(pdf_bytes: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(BytesIO(pdf_bytes))
    return " ".join(" ".join((page.extract_text() or "").split()) for page in reader.pages)


@pytest.mark.parametrize("has_check", [True, False])
def test_advisory_report_pdf_shows_note_in_suitability_section(has_check):
    from services.pdf.documents.advisory_report import (
        render_advisory_report_pdf_from_payload,
    )
    from test_advisory_report_pdf import _make_minimal_payload

    payload = _make_minimal_payload()
    ss = dict(payload.get("suitability_summary") or {})
    ss["has_check"] = has_check
    ss["risk_capacity_plausibility"] = compact_view(PARTIAL)
    payload["suitability_summary"] = ss
    text = _pdf_text(render_advisory_report_pdf_from_payload(payload))
    assert "Plausibilitätsprüfung Risikofähigkeit (Beraterhinweis)" in text
    assert "Frage 5 Verpflichtungen" in text


def test_advisory_report_pdf_without_note_has_no_plausibility_text():
    from services.pdf.documents.advisory_report import (
        render_advisory_report_pdf_from_payload,
    )
    from test_advisory_report_pdf import _make_minimal_payload

    payload = _make_minimal_payload()
    ss = dict(payload.get("suitability_summary") or {})
    ss["risk_capacity_plausibility"] = compact_view(CONSISTENT)
    payload["suitability_summary"] = ss
    text = _pdf_text(render_advisory_report_pdf_from_payload(payload))
    assert "Plausibilitätsprüfung Risikofähigkeit" not in text


from test_optimizer_integration import _seed_realistic_mandate, session_factory  # noqa: F401,E402


def test_advisory_report_payload_carries_compact_plausibility(session_factory, monkeypatch):
    from models.mandates import Mandate
    from services.advisory_report import compute_advisory_report

    seen = {}

    def _fake(db, mandate, assessment, **_kw):
        seen["assessment_id"] = getattr(assessment, "id", None)
        return INCONSISTENT

    monkeypatch.setattr(rcp, "evaluate_mandate_safely", _fake)
    _adv, _cid, mid, aid = _seed_realistic_mandate(session_factory, "rcr-ar")
    with session_factory() as db:
        mandate = db.query(Mandate).filter(Mandate.id == mid).one()
        report = compute_advisory_report(db, mandate)
    block = report["suitability_summary"]["risk_capacity_plausibility"]
    assert seen["assessment_id"] == aid
    assert block["status"] == "inconsistent"
    assert block["reason_code"] == rcp.REASON_CODE
    assert block["note"] == advisor_report_note(INCONSISTENT)
    assert "data_basis" not in block


def test_advisory_report_payload_without_current_assessment_is_none(session_factory):
    from models.mandates import Mandate
    from models.profiling import RiskAssessment
    from services.advisory_report import compute_advisory_report

    _adv, _cid, mid, _aid = _seed_realistic_mandate(session_factory, "rcr-nora")
    with session_factory() as db:
        db.query(RiskAssessment).filter(RiskAssessment.mandate_id == mid).update(
            {RiskAssessment.is_current: 0}
        )
        db.commit()
        mandate = db.query(Mandate).filter(Mandate.id == mid).one()
        report = compute_advisory_report(db, mandate)
    assert report["suitability_summary"]["risk_capacity_plausibility"] is None


# ---------------------------------------------------------------------------
# Advisory-Report: not_evaluable sichtbar, Aggregator-Cache, keine Zusatz-Queries
# ---------------------------------------------------------------------------

def test_advisory_report_pdf_shows_not_evaluable_note():
    from services.pdf.documents.advisory_report import (
        render_advisory_report_pdf_from_payload,
    )
    from test_advisory_report_pdf import _make_minimal_payload

    payload = _make_minimal_payload()
    ss = dict(payload.get("suitability_summary") or {})
    ss["risk_capacity_plausibility"] = compact_view(NOT_EVALUABLE)
    payload["suitability_summary"] = ss
    text = _pdf_text(render_advisory_report_pdf_from_payload(payload))
    assert "mangels Daten nicht prüfbar" in text


def test_report_evaluation_uses_cached_rows_and_matches_db_result(session_factory):
    """Mit vorgeladenen Cache-Zeilen identisches Ergebnis, aber ohne eigene
    Cashflow-/Ziel-Queries; der Preload wird danach wieder entfernt."""
    from sqlalchemy import event
    from sqlalchemy.engine import Engine

    from models.mandates import Mandate
    from models.profiling import RiskAssessment
    from services.advisory_report import _cached_active_cashflows, _cached_active_goals
    from services.risk_capacity_plausibility_report import evaluate_for_assessment

    _adv, _cid, mid, aid = _seed_realistic_mandate(session_factory, "rcr-cache")
    with session_factory() as db:
        mandate = db.query(Mandate).filter(Mandate.id == mid).one()
        ra = db.query(RiskAssessment).filter(RiskAssessment.id == aid).one()
        direct = rcp.evaluate_mandate_safely(db, mandate, ra)
        rows = {
            "cashflows": _cached_active_cashflows(db, str(mandate.client_id)),
            "goals": _cached_active_goals(db, mandate),
        }
        statements: list[str] = []

        def _count(conn, cursor, statement, *_a):
            statements.append(statement.upper())

        event.listen(Engine, "before_cursor_execute", _count)
        try:
            cached = evaluate_for_assessment(db, mandate, ra, preloaded_rows=rows)
        finally:
            event.remove(Engine, "before_cursor_execute", _count)
        assert rcp.PRELOADED_ROWS_KEY not in db.info
    assert cached == direct
    assert not [x for x in statements if "FROM CASHFLOWS" in x], statements
    assert not [x for x in statements if "FROM GOALS" in x], statements


def test_preloaded_rows_for_other_mandate_are_ignored():
    from types import SimpleNamespace

    db = SimpleNamespace(info={rcp.PRELOADED_ROWS_KEY: {
        "mandate_id": "m-a", "client_id": "c-a", "cashflows": [], "goals": [],
    }})
    assert rcp._preloaded_rows(db, SimpleNamespace(id="m-b", client_id="c-a")) is None
    assert rcp._preloaded_rows(db, SimpleNamespace(id="m-a", client_id="c-a")) is not None


# ---------------------------------------------------------------------------
# Strategie-PDF (Anlagestrategie, vom Kunden unterzeichnet): KEIN Hinweis
# ---------------------------------------------------------------------------

def _ctx():
    from services.pdf.base import PDFContext

    return PDFContext(
        mandate_name="Beispiel", advisor_name="Berater Beispiel",
        report_date=date(2026, 10, 21),
    )


def test_strategy_pdf_data_has_no_plausibility_field():
    import dataclasses

    from services.pdf.base import AnlagestrategieData

    names = {f.name for f in dataclasses.fields(AnlagestrategieData)}
    assert not [n for n in names if "plausibility" in n], names


@pytest.mark.parametrize(
    "result", [PARTIAL, INCONSISTENT, NOT_EVALUABLE],
    ids=["partial", "inconsistent", "not_evaluable"],
)
def test_client_signed_strategy_pdf_never_shows_plausibility_note(
    session_factory, monkeypatch, result,
):
    from models.mandates import Mandate
    from routers.pdf_reports import _build_anlagestrategie_data
    from services.pdf.reportlab_renderer import ReportLabRenderer
    from test_band_override_house_matrix_disclosure import _generate

    adv, _cid, mid, _aid = _seed_realistic_mandate(
        session_factory, "rcr-sp-" + str(result["status"]),
    )
    _generate(session_factory, mid, adv, {})
    monkeypatch.setattr(rcp, "evaluate_mandate_safely", lambda *a, **k: result)
    with session_factory() as db:
        mandate = db.query(Mandate).filter(Mandate.id == mid).one()
        data = _build_anlagestrategie_data(mandate, db)
    text = _pdf_text(ReportLabRenderer().render_anlagestrategie(_ctx(), data))
    assert "Plausibilitätsprüfung" not in text
    assert "Beraterhinweis" not in text
