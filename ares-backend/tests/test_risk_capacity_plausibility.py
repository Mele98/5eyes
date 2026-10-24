"""RISK-CAPACITY-PLAUSIBILITY-001: Fragebogen-Risikofaehigkeit vs. erfasste Daten.

Befund (Variablen-Audit 2026-10-18, P0): die Risikofaehigkeit stammte nur aus
dem Fragebogen und wurde nie gegen Vermoegen, Verschuldung, Cashflows und
Ziele plausibilisiert. Die Pruefung meldet Widersprueche (Reason-Code
RISK_CAPACITY_INCONSISTENT), aendert aber nie das Profil und blockiert nichts.
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base  # noqa: E402
import models.allocation  # noqa: E402,F401  (FK-Aufloesung)
from models.clients import Client  # noqa: E402
from models.mandates import Mandate  # noqa: E402
from models.review import AuditLog  # noqa: E402
from models.tenant import Tenant  # noqa: E402,F401  (FK-Aufloesung)
from models.users import User  # noqa: E402
from models.wealth import Cashflow, Goal, WealthPosition  # noqa: E402
from services.risk_capacity_plausibility import (  # noqa: E402
    CHECK_FREE_WEALTH,
    CHECK_INCOME,
    CHECK_LEVERAGE,
    CHECK_NEAR_TERM_GOALS,
    CHECK_OBLIGATIONS,
    CHECK_SAVINGS,
    PDF_ADVISOR_NOTE,
    PLAUSIBILITY_RULES_VERSION,
    REASON_CODE,
    THRESHOLDS,
    DeclaredCapacity,
    RecordedFinancials,
    assess_plausibility,
    attach_to_strategy_payload,
    declared_capacity_from_assessment,
    load_recorded_financials,
    pdf_advisor_note,
    strategy_reasoning_lines,
)
from tests.risk_fixture_helpers import CURRENT_RISK_ANSWERS  # noqa: E402

CHF = 100  # Rappen
TODAY = date(2026, 10, 18)
NOW = "2026-10-18T00:00:00.000Z"


def _declared(**overrides) -> DeclaredCapacity:
    base = dict(
        income_band=3,        # CHF 12'000 bis 20'000
        obligations_band=1,   # CHF 3'000 bis 5'000
        free_wealth_band=3,   # CHF 1 Mio bis 2 Mio
        savings_band=3,       # 25 bis 50 %
        capacity_band=5,      # Dynamisch
        horizon_years=15,
        capacity_score_x10=100,
        willingness_score_x10=70,
        final_score_x10=70,
    )
    base.update(overrides)
    return DeclaredCapacity(**base)


def _recorded(**overrides) -> RecordedFinancials:
    base = dict(
        gross_income_monthly_rappen=15_000 * CHF,
        recurring_expense_monthly_rappen=4_000 * CHF,
        liquid_assets_rappen=1_500_000 * CHF,
        gross_assets_rappen=1_800_000 * CHF,
        direct_property_rappen=0,
        mortgage_liabilities_rappen=0,
        other_liabilities_rappen=0,
        near_term_goal_need_rappen=0,
        position_count=3,
        income_cashflow_count=1,
        expense_cashflow_count=2,
        # Restbefund A (PR #653): "consistent" verlangt eine gueltige
        # Vollstaendigkeits-Bestaetigung; Zeilen ohne Bestaetigung sind nur
        # eine Untergrenze (tests/test_risk_capacity_coverage_attestation.py).
        expense_coverage_attested=True,
    )
    base.update(overrides)
    return RecordedFinancials(**base)


def _checks(result: dict) -> set[str]:
    return {f["check"] for f in result["findings"]}


# ---------------------------------------------------------------------------
# Kernregeln (rein, ohne DB)
# ---------------------------------------------------------------------------

def test_consistent_answers_produce_no_reason_code():
    result = assess_plausibility(_declared(), _recorded())
    assert result["status"] == "consistent"
    assert result["reason_code"] is None
    assert result["findings"] == []
    assert result["version"] == PLAUSIBILITY_RULES_VERSION
    assert strategy_reasoning_lines(result) == []
    assert pdf_advisor_note(result) == ""


def test_income_band_above_recorded_income_is_flagged_with_concrete_reason():
    result = assess_plausibility(
        _declared(), _recorded(gross_income_monthly_rappen=8_000 * CHF,
                               recurring_expense_monthly_rappen=2_000 * CHF),
    )
    assert result["status"] == "inconsistent"
    assert result["reason_code"] == REASON_CODE == "RISK_CAPACITY_INCONSISTENT"
    finding = next(f for f in result["findings"] if f["check"] == CHECK_INCOME)
    assert finding["question_number"] == 3
    assert "CHF 12'000 bis CHF 20'000" in finding["message"]
    assert "CHF 8'000" in finding["message"]


def test_income_within_tolerance_is_not_flagged():
    # Untergrenze 12'000, Toleranz 10 % -> erst unter 10'800 ein Befund.
    result = assess_plausibility(
        _declared(), _recorded(gross_income_monthly_rappen=11_000 * CHF,
                               recurring_expense_monthly_rappen=3_000 * CHF),
    )
    assert CHECK_INCOME not in _checks(result)


def test_understated_capacity_is_never_a_finding():
    # Angabe tiefer als die Daten: konservativ, kein Widerspruch.
    result = assess_plausibility(
        _declared(income_band=0, obligations_band=4, free_wealth_band=0,
                  savings_band=0, capacity_band=1, horizon_years=2),
        _recorded(),
    )
    assert result["findings"] == []


def test_obligations_below_recorded_expenses_are_flagged():
    result = assess_plausibility(
        _declared(obligations_band=0),  # bis CHF 3'000
        _recorded(recurring_expense_monthly_rappen=4_000 * CHF),
    )
    finding = next(f for f in result["findings"] if f["check"] == CHECK_OBLIGATIONS)
    assert finding["question_number"] == 5
    assert "CHF 4'000" in finding["message"]
    within = assess_plausibility(
        _declared(obligations_band=0),
        _recorded(recurring_expense_monthly_rappen=3_200 * CHF),
    )
    assert CHECK_OBLIGATIONS not in _checks(within)


def test_free_wealth_upper_bound_subtracts_debt_and_near_term_goals():
    # 1.5 Mio liquide - 300k Konsumkredit - 200k ungedeckte Hypothek
    # - 400k Ziele <= 3 J. = 600k < 1 Mio (Untergrenze Band 3).
    recorded = _recorded(
        other_liabilities_rappen=300_000 * CHF,
        mortgage_liabilities_rappen=700_000 * CHF,
        direct_property_rappen=500_000 * CHF,
        gross_assets_rappen=2_000_000 * CHF,
        near_term_goal_need_rappen=400_000 * CHF,
    )
    result = assess_plausibility(_declared(), recorded)
    finding = next(f for f in result["findings"] if f["check"] == CHECK_FREE_WEALTH)
    assert finding["question_number"] == 6
    assert result["data_basis"]["free_wealth_upper_bound_rappen"] == 600_000 * CHF
    assert "CHF 600'000" in finding["message"]


def test_negative_budget_contradicts_any_declared_savings_rate():
    result = assess_plausibility(
        _declared(savings_band=1, obligations_band=4),  # 1 bis 10 %
        _recorded(gross_income_monthly_rappen=10_000 * CHF,
                  recurring_expense_monthly_rappen=10_500 * CHF),
    )
    finding = next(f for f in result["findings"] if f["check"] == CHECK_SAVINGS)
    assert finding["question_number"] == 7
    assert "-5 %" in finding["recorded"]


def test_savings_rate_tolerance_in_percentage_points():
    # Band 25-50 %: Befund erst unter 20 %.
    ok = assess_plausibility(
        _declared(obligations_band=4),
        _recorded(gross_income_monthly_rappen=10_000 * CHF,
                  recurring_expense_monthly_rappen=7_800 * CHF),
    )
    assert CHECK_SAVINGS not in _checks(ok)
    flagged = assess_plausibility(
        _declared(obligations_band=4),
        _recorded(gross_income_monthly_rappen=10_000 * CHF,
                  recurring_expense_monthly_rappen=8_100 * CHF),
    )
    assert CHECK_SAVINGS in _checks(flagged)


def test_high_leverage_contradicts_medium_or_high_capacity():
    recorded = _recorded(
        liquid_assets_rappen=150_000 * CHF,
        gross_assets_rappen=1_000_000 * CHF,
        direct_property_rappen=850_000 * CHF,
        mortgage_liabilities_rappen=800_000 * CHF,
    )
    result = assess_plausibility(_declared(free_wealth_band=1), recorded)
    finding = next(f for f in result["findings"] if f["check"] == CHECK_LEVERAGE)
    assert "80 %" in finding["recorded"]
    assert "Dynamisch" in finding["message"]
    # Tiefe Faehigkeit und kurzer Horizont: kein Widerspruch.
    low = assess_plausibility(
        _declared(free_wealth_band=1, capacity_band=2, horizon_years=2), recorded,
    )
    assert CHECK_LEVERAGE not in _checks(low)


def test_large_near_term_goals_contradict_long_horizon_capacity():
    recorded = _recorded(
        liquid_assets_rappen=1_000_000 * CHF,
        near_term_goal_need_rappen=600_000 * CHF,
    )
    result = assess_plausibility(_declared(free_wealth_band=1), recorded)
    finding = next(f for f in result["findings"] if f["check"] == CHECK_NEAR_TERM_GOALS)
    assert "60 %" in finding["recorded"]
    below = assess_plausibility(
        _declared(free_wealth_band=1),
        _recorded(liquid_assets_rappen=1_000_000 * CHF,
                  near_term_goal_need_rappen=400_000 * CHF),
    )
    assert CHECK_NEAR_TERM_GOALS not in _checks(below)


def test_missing_data_is_reported_as_not_evaluable_never_as_consistent():
    result = assess_plausibility(
        _declared(),
        RecordedFinancials(),  # nichts erfasst
    )
    assert result["status"] == "not_evaluable"
    skipped = {row["check"] for row in result["not_evaluable"]}
    assert {CHECK_INCOME, CHECK_FREE_WEALTH, CHECK_SAVINGS} <= skipped


def test_only_derived_investment_income_does_not_make_income_checkable():
    # Nur Zins-/Mietertraege aus Positionen, kein erfasster Lohn/Rente:
    # Frage 3 und 7 sind dann nicht pruefbar statt "Einkommen viel zu tief".
    result = assess_plausibility(
        _declared(),
        _recorded(gross_income_monthly_rappen=300 * CHF, income_cashflow_count=0),
    )
    assert CHECK_INCOME not in _checks(result)
    assert CHECK_SAVINGS not in _checks(result)
    skipped = {row["check"] for row in result["not_evaluable"]}
    assert {CHECK_INCOME, CHECK_SAVINGS} <= skipped


def test_points_outside_answer_options_are_not_guessed_into_a_band():
    assessment = SimpleNamespace(
        q_income_points=3, q_obligations_points=3, q_wealth_points=5,
        q_savings_points=9, investment_horizon_label="Mehr als 12 Jahre",
        risk_capacity_profile="Dynamisch", risk_capacity_score_x10=100,
        risk_willingness_score_x10=70, final_score_x10=70, is_overridden=0,
        override_score_x10=None,
    )
    declared = declared_capacity_from_assessment(assessment)
    assert declared.free_wealth_band is None
    result = assess_plausibility(declared, _recorded(liquid_assets_rappen=1 * CHF))
    assert CHECK_FREE_WEALTH not in _checks(result)
    assert any(row["check"] == CHECK_FREE_WEALTH for row in result["not_evaluable"])


def test_override_down_and_binding_willingness_are_stated_in_advisor_text():
    declared = _declared(is_overridden=True, override_score_x10=40, final_score_x10=70)
    result = assess_plausibility(
        declared, _recorded(gross_income_monthly_rappen=5_000 * CHF,
                            recurring_expense_monthly_rappen=2_000 * CHF),
    )
    assert result["override_down"] is True
    assert "Override nach unten ist dokumentiert" in result["advisor_text"]
    assert result["capacity_binding"] is False
    assert "Risikobereitschaft bindend" in result["advisor_text"]
    assert "nicht automatisch geändert" in result["advisor_text"]


def test_thresholds_are_versioned_and_documented_as_cio_default():
    source = (BACKEND_ROOT / "services" / "risk_capacity_plausibility.py").read_text(encoding="utf-8")
    assert "CIO-Default, Compliance zu bestaetigen" in source
    assert THRESHOLDS["leverage_ratio_max"] == pytest.approx(2 / 3)
    assert THRESHOLDS["near_term_goal_years"] == 3


# ---------------------------------------------------------------------------
# Strategie-Reasoning und PDF
# ---------------------------------------------------------------------------

def _inconsistent_result() -> dict:
    return assess_plausibility(
        _declared(), _recorded(gross_income_monthly_rappen=8_000 * CHF,
                               recurring_expense_monthly_rappen=2_000 * CHF),
    )


def test_strategy_payload_gets_summary_first_and_details_last():
    payload = {"reasoning": ["Ausgangspunkt ist die House Matrix fuer Score 7.", "Zweiter Punkt."]}
    result = _inconsistent_result()
    attach_to_strategy_payload(payload, result)
    assert payload["risk_capacity_plausibility"] is result
    assert REASON_CODE in payload["reasoning"][0]
    assert "Frage 3 Einkommen" in payload["reasoning"][0]
    assert payload["reasoning"][1] == "Ausgangspunkt ist die House Matrix fuer Score 7."
    assert payload["reasoning"][-1].startswith("Frage 3 (Einkommen)")
    # Idempotent: zweimal anhaengen dupliziert nichts.
    attach_to_strategy_payload(payload, result)
    assert sum(REASON_CODE in line for line in payload["reasoning"]) == 1


def test_strategy_payload_unchanged_when_consistent():
    payload = {"reasoning": ["A", "B"]}
    attach_to_strategy_payload(payload, assess_plausibility(_declared(), _recorded()))
    assert payload["reasoning"] == ["A", "B"]


def test_pdf_note_is_neutral_without_amounts_or_client_claims():
    note = pdf_advisor_note(_inconsistent_result())
    assert note == PDF_ADVISOR_NOTE
    assert "CHF" not in note
    assert "Kunde" not in note  # keine Aussage ueber den Kunden
    assert "nicht automatisch verändert" in note


def test_pdf_renders_note_in_advisor_section():
    from services.pdf.base import PDFContext, RisikoprofilData
    from services.pdf.documents.risikoprofil import build_risikoprofil_flowables

    ctx = PDFContext(
        mandate_name="Test", advisor_name="Berater",
        report_date=date(2026, 10, 18),
    )
    data = RisikoprofilData(
        risk_profile_label="Ausgewogen", risk_capacity_score=60,
        risk_tolerance_score=60, capacity_plausibility_note=PDF_ADVISOR_NOTE,
    )
    texts = [getattr(f, "text", "") for f in build_risikoprofil_flowables(ctx, data)]
    assert any("Plausibilitätsprüfung (Beraterhinweis)" in t for t in texts)
    assert any("Beraterdokumentation" in t for t in texts)


def test_generate_response_schema_exposes_plausibility_field():
    from schemas.allocation import TargetAllocationGenerateResponse

    assert "risk_capacity_plausibility" in TargetAllocationGenerateResponse.model_fields


# ---------------------------------------------------------------------------
# DB-Integration: Datenbasis, Endpoint, Audit, keine Profilaenderung
# ---------------------------------------------------------------------------

@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'risk_capacity_plausibility.db'}",
        connect_args={"check_same_thread": False},
    )
    sf = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield sf
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


class _FakeRequest:
    def __init__(self):
        self.headers = {}
        self.client = SimpleNamespace(host="127.0.0.1")


def _seed(session) -> User:
    advisor = User(
        id="adv-rcp", username="adv-rcp", password_hash="hash", full_name="Advisor RCP",
        role="advisor", is_active=1, created_at=NOW, updated_at=NOW,
    )
    session.add(advisor)
    session.add(Client(
        id="cl-rcp", client_number="C-RCP", first_name="Max", last_name="Muster",
        country_of_residence="CH", language="DE", household_type="Einzelperson",
        client_classification="Privatkunde", is_professional_opt_out=0,
        is_qualified_investor=0, advisor_id=advisor.id, created_at=NOW, updated_at=NOW,
    ))
    session.add(Mandate(
        id="m-rcp", client_id="cl-rcp", mandate_number="M-RCP",
        mandate_type="Anlageberatung", status="Aktiv", base_currency="CHF",
        advisory_language="DE", opened_at="2026-01-01", created_at=NOW, updated_at=NOW,
    ))
    session.commit()
    return advisor


def _position(pid, ptype, assignment, value_chf, currency="CHF", **extra):
    return WealthPosition(
        id=pid, client_id="cl-rcp", label=pid, position_type=ptype, assignment=assignment,
        current_value_rappen=int(value_chf * CHF), currency=currency,
        created_at=NOW, updated_at=NOW, **extra,
    )


def _cashflow(cid, cf_type, amount_chf, frequency="monatlich", **extra):
    return Cashflow(
        id=cid, client_id="cl-rcp", cashflow_type=cf_type, label=cid,
        amount_rappen=int(amount_chf * CHF), currency=extra.pop("currency", "CHF"),
        frequency=frequency, nature=extra.pop("nature", "wiederkehrend"),
        created_at=NOW, updated_at=NOW, **extra,
    )


def _risk_body(**overrides):
    from schemas.profiling import RiskAssessmentCreate

    body = dict(
        q_income_points=3,           # CHF 12'000 bis 20'000
        q_obligations_points=3,      # CHF 3'000 bis 5'000
        q_savings_points=9,          # 25 bis 50 %
        q_wealth_points=9,           # CHF 1 Mio bis 2 Mio
        investment_horizon_label="Mehr als 12 Jahre",
        investment_horizon_years=15,
        q_investment_goal_points=3,
        q_risk_preference_points=3,
        q_risk_behavior_points=3,
        knowledge_services_json="{}",
        knowledge_instruments_json="{}",
        income_sources_json='["Berufliche Taetigkeit"]',
        answers=[
            {"question_number": n, "question_section": "Risikoprofil",
             "answer_label": label, "answer_points": points}
            for n, label, points in CURRENT_RISK_ANSWERS
        ],
    )
    body.update(overrides)
    return RiskAssessmentCreate(**body)


def _plausibility_audit_rows(session):
    return session.query(AuditLog).filter(
        AuditLog.field_name == "risk_capacity_plausibility"
    ).all()


def test_load_recorded_financials_reads_cashflows_positions_goals(session_factory):
    with session_factory() as session:
        _seed(session)
        session.add_all([
            _cashflow("salary", "Income", 9_000, gross_amount_rappen=11_000 * CHF),
            _cashflow("bonus-annual", "Income", 12_000, frequency="jährlich"),
            _cashflow("rent", "Expense", 2_500),
            _cashflow("excluded", "Expense", 9_999, is_included=0),
            _cashflow("ended", "Income", 50_000, valid_until="2025-12-31"),
            _cashflow("one-off", "Income", 100_000, frequency="einmalig", nature="einmalig"),
            _position("depot", "Depot", "Beratungsvermögen", 400_000),
            _position("usd-cash", "Liquidität", "Anderes Vermögen", 10_000, currency="USD"),
            _position("pk", "Vorsorge", "Anderes Vermögen", 300_000),
            _position("house", "Immobilien", "Anderes Vermögen", 1_000_000),
            _position("mortgage", "Hypothek", "Verbindlichkeit", 600_000,
                      mortgage_interest_rate_bps=200),
            Goal(id="car", mandate_id="m-rcp", client_id="cl-rcp", goal_family="Konsum",
                 goal_type="Einmalige Ausgabe", label="Auto", rank=1,
                 goal_scope="Beratungsvermögen", value_mode="nominal",
                 target_amount_rappen=80_000 * CHF, target_date="2028-06-30",
                 hardness="Primär", created_at=NOW, updated_at=NOW),
            Goal(id="far", mandate_id="m-rcp", client_id="cl-rcp", goal_family="Konsum",
                 goal_type="Einmalige Ausgabe", label="Weit weg", rank=2,
                 goal_scope="Beratungsvermögen", value_mode="nominal",
                 target_amount_rappen=500_000 * CHF, target_date="2040-01-01",
                 hardness="Primär", created_at=NOW, updated_at=NOW),
        ])
        session.commit()
        mandate = session.get(Mandate, "m-rcp")
        recorded = load_recorded_financials(session, mandate, today=TODAY)

    # 11'000 brutto + 1'000 (Bonus/12) ; beendete/einmalige Cashflows zaehlen nicht.
    assert recorded.gross_income_monthly_rappen == 12_000 * CHF
    # 2'500 Miete + Hypothekarzins 600k*2%/12 = 1'000; ausgeschlossener CF zaehlt nicht.
    assert recorded.recurring_expense_monthly_rappen == 3_500 * CHF
    assert recorded.mortgage_liabilities_rappen == 600_000 * CHF
    assert recorded.direct_property_rappen == 1_000_000 * CHF
    # Depot + USD-Liquiditaet (FX); Vorsorge und Immobilie nicht liquide.
    assert 400_000 * CHF < recorded.liquid_assets_rappen < 420_000 * CHF
    assert recorded.gross_assets_rappen > 1_700_000 * CHF
    assert recorded.near_term_goal_need_rappen == 80_000 * CHF
    assert recorded.near_term_goal_labels == ("Auto",)
    # Erfasst: Lohn + Bonus (Income), Miete (Expense); Hypothekarzins ist abgeleitet.
    assert recorded.income_cashflow_count == 2
    assert recorded.expense_cashflow_count == 1


def test_create_risk_assessment_audits_inconsistency_without_changing_profile(session_factory):
    from routers.profiling import create_risk_assessment, get_risk_capacity_plausibility
    from services.risk_scoring import compute_scores

    with session_factory() as session:
        advisor = _seed(session)
        session.add_all([
            _cashflow("salary", "Income", 7_000),
            _cashflow("living", "Expense", 6_500),
            _position("depot", "Depot", "Beratungsvermögen", 150_000),
        ])
        session.commit()
        body = _risk_body()
        ra = create_risk_assessment(
            mandate_id="m-rcp", body=body, request=_FakeRequest(), db=session,
            current_user=advisor,
        )
        expected = compute_scores(
            q_income_points=3, q_obligations_points=3, q_savings_points=9,
            q_wealth_points=9, investment_horizon_label="Mehr als 12 Jahre",
            q_investment_goal_points=3, q_risk_preference_points=3,
            q_risk_behavior_points=3,
        )
        # Profil unveraendert: keine automatische Aenderung durch die Pruefung.
        assert ra.final_score_x10 == expected.final_score_x10
        assert ra.risk_capacity_score_x10 == expected.risk_capacity_score_x10
        assert ra.is_overridden == 0

        rows = _plausibility_audit_rows(session)
        assert len(rows) == 1
        assert rows[0].table_name == "risk_assessments"
        assert rows[0].record_id == ra.id
        payload = json.loads(rows[0].new_value)
        assert payload["reason_code"] == REASON_CODE
        assert payload["version"] == PLAUSIBILITY_RULES_VERSION
        assert {CHECK_INCOME, CHECK_OBLIGATIONS, CHECK_FREE_WEALTH, CHECK_SAVINGS} <= set(payload["checks"])

        result = get_risk_capacity_plausibility(
            mandate_id="m-rcp", db=session, current_user=advisor,
        )
        assert result["status"] == "inconsistent"
        assert result["reason_code"] == REASON_CODE
        assert result["risk_assessment_id"] == ra.id
        assert all(f["message"] for f in result["findings"])


def test_consistent_profile_writes_no_plausibility_audit(session_factory):
    from routers.profiling import create_risk_assessment
    from services.financial_coverage_attestation import create_attestation

    with session_factory() as session:
        advisor = _seed(session)
        session.add_all([
            _cashflow("salary", "Income", 15_000),
            _cashflow("living", "Expense", 4_000),
            _position("depot", "Depot", "Beratungsvermögen", 1_500_000),
        ])
        session.commit()
        # "consistent" erst mit gueltiger Vollstaendigkeits-Bestaetigung.
        create_attestation(
            session, session.get(Mandate, "m-rcp"), actor=advisor,
            household_persons=["Max Muster"], income_complete=True,
            expenses_complete=True, obligations_complete=True,
            irregular_expenses_reviewed=True, as_of_date=date.today().isoformat(),
            source="Kundengespräch",
        )
        session.commit()
        create_risk_assessment(
            mandate_id="m-rcp", body=_risk_body(), request=_FakeRequest(), db=session,
            current_user=advisor,
        )
        assert _plausibility_audit_rows(session) == []


def test_generate_endpoint_adds_reasoning_and_audit_but_does_not_block(session_factory, monkeypatch):
    import routers.allocation as allocation_router
    from routers.profiling import create_risk_assessment

    with session_factory() as session:
        advisor = _seed(session)
        session.add_all([
            _cashflow("salary", "Income", 7_000),
            _cashflow("living", "Expense", 6_500),
            _position("depot", "Depot", "Beratungsvermögen", 150_000),
        ])
        session.commit()
        ra = create_risk_assessment(
            mandate_id="m-rcp", body=_risk_body(), request=_FakeRequest(), db=session,
            current_user=advisor,
        )

        fake_ta = SimpleNamespace(id="ta-rcp")
        monkeypatch.setattr(
            allocation_router, "generate_target_allocation",
            lambda **kwargs: {
                "target_allocation": fake_ta,
                "risk_assessment": ra,
                "reasoning": ["Ausgangspunkt ist die House Matrix fuer Score 7."],
            },
        )
        monkeypatch.setattr(allocation_router, "refresh_system_review_triggers", lambda *a, **k: None)
        monkeypatch.setattr(session, "refresh", lambda obj: None)
        body = allocation_router.TargetAllocationGenerateRequest()
        result = allocation_router.generate_target_allocation_endpoint(
            mandate_id="m-rcp", body=body, request=_FakeRequest(), db=session,
            current_user=advisor,
        )
        assert result["risk_capacity_plausibility"]["reason_code"] == REASON_CODE
        assert REASON_CODE in result["reasoning"][0]
        assert result["reasoning"][1] == "Ausgangspunkt ist die House Matrix fuer Score 7."
        rows = [r for r in _plausibility_audit_rows(session) if r.table_name == "target_allocations"]
        assert len(rows) == 1 and rows[0].record_id == "ta-rcp"


# ---------------------------------------------------------------------------
# Monolith: Anzeige beim Risikoprofil (bestehende Banner-Komponente)
# ---------------------------------------------------------------------------

HTML = (BACKEND_ROOT.parent / "ares-desktop" / "frontend" / "ares.html").read_text(encoding="utf-8")


def _js_function(name: str) -> str:
    marker = f"function {name}("
    assert marker in HTML, f"{name} fehlt"
    start = HTML.index(marker)
    return HTML[start:HTML.index("\n}\n", start)]


def test_monolith_risk_view_has_plausibility_banner_reusing_warning_component():
    assert 'id="rp-capacity-plausibility" class="al-banner-warning"' in HTML
    banner = HTML.split('id="rp-capacity-plausibility"', 1)[1][:600]
    assert "al-banner-title" in banner and "al-banner-body" in banner
    # Steht in der Auswertung vor der Strategie-Box.
    assert HTML.index('id="rp-capacity-plausibility"') < HTML.index('<div class="resbox">')


def test_monolith_renders_findings_escaped_and_open_states_visible():
    render = _js_function("renderRiskCapacityPlausibility")
    assert "result.status==='inconsistent'" in render
    assert "escapeHtml(" in render
    assert "reason_code" in render
    refresh = _js_function("refreshRiskCapacityPlausibility")
    assert "'/mandates/'+requested+'/risk-capacity-plausibility'" in refresh
    assert "getActiveMandateId()" in refresh  # Mandatswechsel-Guard


def test_monolith_refreshes_after_load_save_and_override():
    assert "refreshRiskCapacityPlausibility(" in _js_function("saveRiskProfile")
    assert "refreshRiskCapacityPlausibility(" in _js_function("loadCurrentRiskAssessment")
    assert "renderRiskCapacityPlausibility(null)" in _js_function("loadCurrentRiskAssessment")
    override_block = HTML.split("/risk-assessments/'+raId+'/override'", 1)[1][:900]
    assert "refreshRiskCapacityPlausibility(mid)" in override_block


# ---------------------------------------------------------------------------
# RISK-CAPACITY-COVERAGE-001 (Codex-Review PR #647, 2026-10-19):
# regelweise Datenabdeckung und Vorausfenster fuer Verpflichtungen.
# Uebernimmt den Gegenvertrag docs/audits/reproducers/
# test_2026_10_19_pr647_risk_capacity_plausibility_adversarial.py
# (Assertions unveraendert, zusaetzlich verschaerft).
# ---------------------------------------------------------------------------

def _declared_high_capacity(**overrides) -> DeclaredCapacity:
    return _declared(obligations_band=0, **overrides)  # Frage 5: bis CHF 3'000


def _skipped(result: dict) -> set[str]:
    return {row["check"] for row in result["not_evaluable"]}


def test_missing_expense_coverage_is_not_certified_consistent():
    """Keine Ausgabenzeile = unbekannte Verpflichtungen, nicht verifizierte Null."""
    recorded = RecordedFinancials(
        gross_income_monthly_rappen=15_000 * CHF,
        recurring_expense_monthly_rappen=0,
        liquid_assets_rappen=1_500_000 * CHF,
        gross_assets_rappen=1_500_000 * CHF,
        position_count=1,
        income_cashflow_count=1,
        expense_cashflow_count=0,
    )
    result = assess_plausibility(_declared_high_capacity(), recorded)

    assert result["status"] != "consistent"
    assert result["status"] == "partial"
    assert {CHECK_OBLIGATIONS, CHECK_SAVINGS} <= _skipped(result)
    assert result["reason_code"] is None
    assert result["coverage"][CHECK_OBLIGATIONS] == "missing"
    assert result["coverage"][CHECK_SAVINGS] == "missing"
    assert result["coverage"][CHECK_INCOME] == "recorded"
    # Restbefund B (Codex-Closure-Review PR #653): "partial" ist NICHT still,
    # sondern "noch nicht verifiziert" mit Aufloesungsauftrag in Reasoning
    # und Berater-PDF (kein Widerspruchs-Reason-Code).
    lines = strategy_reasoning_lines(result)
    assert len(lines) == 1 and "noch nicht verifiziert" in lines[0]
    assert "Ausgaben vollständig als Cashflow erfassen" in lines[0]
    note = pdf_advisor_note(result)
    assert note and note != PDF_ADVISOR_NOTE and "verifiziert" in note


def test_derived_only_expenses_below_limit_are_not_evaluable():
    # Nur abgeleiteter Hypothekarzins (CHF 1'000), keine erfasste Ausgabe:
    # Betrag ist eine Untergrenze, belegt aber keine Haushaltsabdeckung.
    result = assess_plausibility(
        _declared_high_capacity(),
        _recorded(recurring_expense_monthly_rappen=1_000 * CHF, expense_cashflow_count=0),
    )
    assert result["status"] == "partial"
    assert {CHECK_OBLIGATIONS, CHECK_SAVINGS} <= _skipped(result)
    assert result["coverage"][CHECK_OBLIGATIONS] == "derived_only"
    assert result["data_basis"]["recurring_expense_monthly_rappen"] == 1_000 * CHF


def test_derived_only_expenses_above_limit_still_flag_as_lower_bound():
    # Einweg-Logik: schon die Untergrenze widerspricht der Angabe -> Befund.
    result = assess_plausibility(
        _declared_high_capacity(),
        _recorded(gross_income_monthly_rappen=10_000 * CHF,
                  recurring_expense_monthly_rappen=9_000 * CHF, expense_cashflow_count=0),
    )
    assert result["status"] == "inconsistent"
    assert {CHECK_OBLIGATIONS, CHECK_SAVINGS} <= _checks(result)
    assert not ({CHECK_OBLIGATIONS, CHECK_SAVINGS} & _skipped(result))


def test_ambiguous_answer_makes_overall_status_partial_not_consistent():
    result = assess_plausibility(_declared(free_wealth_band=None), _recorded())
    assert result["findings"] == []
    assert result["status"] == "partial"
    assert result["coverage"][CHECK_FREE_WEALTH] == "answer_unmapped"


def test_full_coverage_remains_consistent():
    result = assess_plausibility(_declared(), _recorded())
    assert result["status"] == "consistent"
    assert result["not_evaluable"] == []
    assert result["coverage"][CHECK_OBLIGATIONS] == "recorded"


def test_forward_window_is_versioned_cio_default():
    assert THRESHOLDS["obligation_forward_window_months"] == 12
    assert PLAUSIBILITY_RULES_VERSION == "RCP-2026-10-20.v3"


def _load(session_factory, rows, *, today=TODAY):
    with session_factory() as session:
        _seed(session)
        session.add_all(rows)
        session.commit()
        return load_recorded_financials(session, session.get(Mandate, "m-rcp"), today=today)


def test_recorded_near_term_future_expense_participates_in_capacity_check(session_factory):
    """Frage 5 umfasst ausdruecklich kuenftig absehbare Verpflichtungen."""
    recorded = _load(session_factory, [
        _cashflow("salary", "Income", 15_000),
        _cashflow("known-future-obligation", "Expense", 13_000, valid_from="2026-11-01"),
        _position("depot", "Depot", "Beratungsvermögen", 1_500_000),
    ])
    result = assess_plausibility(_declared_high_capacity(), recorded)

    assert recorded.recurring_expense_monthly_rappen == 13_000 * CHF
    assert recorded.current_expense_monthly_rappen == 0
    assert recorded.peak_expense_from == "2026-11-01"
    assert recorded.expense_cashflow_count == 1
    assert {CHECK_OBLIGATIONS, CHECK_SAVINGS} <= _checks(result)
    message = next(f for f in result["findings"] if f["check"] == CHECK_OBLIGATIONS)["message"]
    assert "CHF 13'000" in message and "11.2026" in message


def test_obligation_outside_forward_window_is_documented_not_counted(session_factory):
    recorded = _load(session_factory, [
        _cashflow("salary", "Income", 15_000),
        _cashflow("living", "Expense", 2_000),
        _cashflow("far-future", "Expense", 13_000, valid_from="2027-10-19"),  # 1 Tag zu spaet
        _position("depot", "Depot", "Beratungsvermögen", 1_500_000),
    ])
    assert recorded.recurring_expense_monthly_rappen == 2_000 * CHF
    assert recorded.outside_window_expense_count == 1
    result = assess_plausibility(_declared_high_capacity(), recorded)
    assert CHECK_OBLIGATIONS not in _checks(result)
    assert result["data_basis"]["outside_window_expense_count"] == 1


def test_forward_window_end_day_is_inclusive(session_factory):
    recorded = _load(session_factory, [
        _cashflow("salary", "Income", 15_000),
        _cashflow("edge", "Expense", 13_000, valid_from="2027-10-18"),  # genau +12 Monate
    ])
    assert recorded.recurring_expense_monthly_rappen == 13_000 * CHF
    assert recorded.outside_window_expense_count == 0


def test_time_profile_takes_peak_month_not_sum_of_sequential_obligations(session_factory):
    recorded = _load(session_factory, [
        _cashflow("salary", "Income", 15_000),
        _cashflow("old-loan", "Expense", 5_000, valid_until="2026-11-30"),
        _cashflow("new-loan", "Expense", 6_000, valid_from="2026-12-01"),
        _cashflow("overlap", "Expense", 1_000, valid_from="2027-03-01", valid_until="2027-03-31"),
    ])
    # Okt/Nov 5'000, Dez-Feb 6'000, Maerz 7'000 -> Peak 7'000 (nicht 12'000).
    assert recorded.recurring_expense_monthly_rappen == 7_000 * CHF
    assert recorded.current_expense_monthly_rappen == 5_000 * CHF
    assert recorded.peak_expense_from == "2027-03-01"


def test_expense_ended_before_today_is_not_counted(session_factory):
    recorded = _load(session_factory, [
        _cashflow("salary", "Income", 15_000),
        _cashflow("ended", "Expense", 9_000, valid_until="2026-10-17"),
        _cashflow("ends-today", "Expense", 2_000, valid_until="2026-10-18"),  # inklusiv
    ])
    assert recorded.recurring_expense_monthly_rappen == 2_000 * CHF
    assert recorded.expense_cashflow_count == 1


def test_short_intra_month_future_obligation_is_seen(session_factory):
    recorded = _load(session_factory, [
        _cashflow("salary", "Income", 15_000),
        _cashflow("short", "Expense", 4_000, valid_from="2027-01-10", valid_until="2027-01-20"),
    ])
    assert recorded.recurring_expense_monthly_rappen == 4_000 * CHF


def test_future_annual_obligation_uses_monthly_equivalent(session_factory):
    recorded = _load(session_factory, [
        _cashflow("salary", "Income", 15_000),
        _cashflow("school-fee", "Expense", 24_000, frequency="jährlich", valid_from="2027-08-01"),
    ])
    assert recorded.recurring_expense_monthly_rappen == 2_000 * CHF


def test_future_income_is_not_credited(session_factory):
    # Einweg-Logik: kuenftiges Einkommen entlastet die Pruefung nicht.
    recorded = _load(session_factory, [
        _cashflow("salary", "Income", 5_000),
        _cashflow("future-raise", "Income", 10_000, valid_from="2026-11-01"),
        _cashflow("living", "Expense", 2_000),
    ])
    assert recorded.gross_income_monthly_rappen == 5_000 * CHF
    assert recorded.income_cashflow_count == 1


def test_leap_day_valuation_date_window(session_factory):
    recorded = _load(session_factory, [
        _cashflow("salary", "Income", 15_000),
        _cashflow("in", "Expense", 3_000, valid_from="2029-02-28"),
        _cashflow("out", "Expense", 9_000, valid_from="2029-03-01"),
    ], today=date(2028, 2, 29))
    assert recorded.recurring_expense_monthly_rappen == 3_000 * CHF
    assert recorded.outside_window_expense_count == 1


def test_no_expense_rows_end_to_end_is_partial_via_endpoint(session_factory):
    from routers.profiling import create_risk_assessment, get_risk_capacity_plausibility

    with session_factory() as session:
        advisor = _seed(session)
        session.add_all([
            _cashflow("salary", "Income", 15_000),
            _position("depot", "Depot", "Beratungsvermögen", 1_500_000),
        ])
        session.commit()
        create_risk_assessment(
            mandate_id="m-rcp", body=_risk_body(), request=_FakeRequest(), db=session,
            current_user=advisor,
        )
        result = get_risk_capacity_plausibility(mandate_id="m-rcp", db=session, current_user=advisor)
        assert result["status"] == "partial"
        assert {CHECK_OBLIGATIONS, CHECK_SAVINGS} <= _skipped(result)
        # Restbefund B (PR #653): auch "partial" wird append-only auditiert.
        rows = _plausibility_audit_rows(session)
        assert len(rows) == 1
        assert json.loads(rows[0].new_value)["status"] == "partial"


# ---------------------------------------------------------------------------
# CIO-Entscheid 2026-10-19: Einkommen im Vorausfenster konservativ werten.
# F3/F7 nutzen das TIEFSTE Monatseinkommen im 12-Monats-Fenster; die Sparquote
# wird je Monatssegment aus Einkommen und Belastung DESSELBEN Monats gebildet.
# ---------------------------------------------------------------------------

def test_income_drop_within_window_uses_lowest_month(session_factory):
    recorded = _load(session_factory, [
        _cashflow("salary", "Income", 15_000, valid_until="2027-02-28"),
        _cashflow("pension", "Income", 5_000),
        _cashflow("living", "Expense", 4_500),
    ])
    assert recorded.current_income_monthly_rappen == 20_000 * CHF
    assert recorded.gross_income_monthly_rappen == 5_000 * CHF
    assert recorded.income_min_from == "2027-03-01"
    result = assess_plausibility(_declared(), recorded)
    income = next(f for f in result["findings"] if f["check"] == CHECK_INCOME)
    assert "ab 03.2027 sinkt das erfasste Einkommen auf CHF 5'000" in income["message"]
    savings = next(f for f in result["findings"] if f["check"] == CHECK_SAVINGS)
    assert savings["recorded"] == "10 %"
    assert "ungünstigster Monat ab 03.2027" in savings["message"]


@pytest.mark.parametrize("until", ["2027-10-19", "2027-10-18"])  # nach / genau Fensterende (inklusiv)
def test_income_drop_outside_window_is_not_counted(session_factory, until):
    recorded = _load(session_factory, [
        _cashflow("salary", "Income", 15_000, valid_until=until),
        _cashflow("living", "Expense", 4_000),
    ])
    assert recorded.gross_income_monthly_rappen == 15_000 * CHF
    result = assess_plausibility(_declared(), recorded)
    assert CHECK_INCOME not in _checks(result)
    assert CHECK_SAVINGS not in _checks(result)


def test_multiple_incomes_dropping_at_different_months(session_factory):
    recorded = _load(session_factory, [
        _cashflow("a", "Income", 6_000, valid_until="2026-12-31"),
        _cashflow("b", "Income", 4_000, valid_until="2027-05-31"),
        _cashflow("c", "Income", 3_000),
        _cashflow("future", "Income", 9_000, valid_from="2027-06-01"),  # zaehlt nie
        _cashflow("living", "Expense", 1_000),
    ])
    assert recorded.current_income_monthly_rappen == 13_000 * CHF
    assert recorded.gross_income_monthly_rappen == 3_000 * CHF
    assert recorded.income_min_from == "2027-06-01"
    assert recorded.income_cashflow_count == 3


def test_savings_worst_month_pairs_income_and_expense_of_same_month(session_factory):
    recorded = _load(session_factory, [
        _cashflow("salary", "Income", 5_000, valid_until="2027-02-28"),
        _cashflow("base", "Income", 10_000),
        _cashflow("living", "Expense", 2_000),
        _cashflow("one-month", "Expense", 8_000, valid_from="2026-11-01", valid_until="2026-11-30"),
    ])
    # Nov: 15'000 / 10'000 -> 33 %; ab Maerz: 10'000 / 2'000 -> 80 %.
    # Falsch kombiniert (Min-Einkommen + Max-Belastung) waere 0 %.
    assert recorded.savings_worst_from == "2026-11-01"
    assert recorded.savings_worst_income_monthly_rappen == 15_000 * CHF
    assert recorded.savings_worst_expense_monthly_rappen == 10_000 * CHF
    result = assess_plausibility(_declared(income_band=2, obligations_band=4), recorded)
    assert CHECK_SAVINGS not in _checks(result)
    assert CHECK_INCOME not in _checks(result)


def test_all_income_ending_in_window_is_a_finding_not_a_skip(session_factory):
    recorded = _load(session_factory, [
        _cashflow("salary", "Income", 15_000, valid_until="2027-01-31"),
        _cashflow("living", "Expense", 2_000),
    ])
    assert recorded.gross_income_monthly_rappen == 0
    result = assess_plausibility(_declared(), recorded)
    assert {CHECK_INCOME, CHECK_SAVINGS} <= _checks(result)
    assert not ({CHECK_INCOME, CHECK_SAVINGS} & _skipped(result))
    income = next(f for f in result["findings"] if f["check"] == CHECK_INCOME)
    assert "ab 02.2027 sinkt das erfasste Einkommen auf CHF 0" in income["message"]
