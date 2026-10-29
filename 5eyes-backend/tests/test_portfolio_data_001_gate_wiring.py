"""PORTFOLIO-DATA-001 Teil 2: Verdrahtung der Depot-Policy.

- Mit der ausgelieferten Policy (PROPOSED) ist die Auswertung sichtbar
  (Depot-Snapshot-Antwort, Assessment-Endpunkt), blockiert aber nichts; das
  Gate kehrt ohne DB-Zugriff zurueck.
- Mit einer aktiven Policy (APPROVED, alle Rollen) sperren Finalisierung,
  Advisory-PDF, Signatur und Handoff bei veralteten/unbelegten Depotdaten
  oder fehlendem Abgleich (409, PORTFOLIO_DATA_NOT_RELEASABLE).
"""
from __future__ import annotations

import inspect
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import configure_mappers, sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base  # noqa: E402
from models import (  # noqa: E402,F401
    allocation, clients, mandates, profiling, review, snapshots, users, wealth,
)
import models.client_login  # noqa: E402,F401
import models.fx_rate  # noqa: E402,F401
import models.protocol_bausteine  # noqa: E402,F401
import models.tenant  # noqa: E402,F401
configure_mappers()

from models.allocation import OptimizerPolicy, TargetAllocation  # noqa: E402
from models.clients import Client  # noqa: E402
from models.fx_rate import FXRate  # noqa: E402
from models.mandates import Mandate  # noqa: E402
from models.review import (  # noqa: E402
    PriceHistory, Product, RecommendationHolding, RecommendationPosition, RecommendationRun,
)
from models.users import User  # noqa: E402
from models.wealth import WealthPosition  # noqa: E402
from services import portfolio_data_release_gate as gate_mod  # noqa: E402
from services.portfolio_data_policy import (  # noqa: E402
    _default_policy_path,
    parse_portfolio_data_policy,
)

NOW = "2026-10-26T10:00:00.000Z"


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'portfolio_data.db'}", connect_args={"check_same_thread": False},
    )
    sf = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield sf
    finally:
        engine.dispose()


@pytest.fixture()
def active_policy(monkeypatch):
    raw = json.loads(_default_policy_path().read_text(encoding="utf-8"))
    raw["status"] = "APPROVED"
    raw["approvals"] = [
        {"role": role, "approved_by": f"person-{role}", "approved_at": "2026-11-01", "reference": f"REF-{role}"}
        for role in raw["required_approver_roles"]
    ]
    policy = parse_portfolio_data_policy(raw)
    assert policy.is_active
    monkeypatch.setattr(gate_mod, "load_policy_state", lambda: (policy, None))
    return policy


def _seed(s, holdings=(("eq", "Aktien", "CHF"),), *, holding_date=None):
    holding_date = holding_date or date.today().isoformat()
    advisor = User(
        id="adv", username="adv", password_hash="h", full_name="Advisor", role="advisor",
        is_active=1, created_at=NOW, updated_at=NOW,
    )
    client = Client(
        id="cl", client_number="C-1", first_name="Test", last_name="Kunde", advisor_id="adv",
        country_of_residence="CH", created_at=NOW, updated_at=NOW,
    )
    mandate = Mandate(
        id="m", client_id="cl", mandate_number="M-1", mandate_type="Anlageberatung",
        base_currency="CHF", opened_at=NOW, created_at=NOW, updated_at=NOW,
    )
    policy = OptimizerPolicy(
        id="pol", policy_name="p", version=1, is_current=1, valid_from=NOW[:10],
        optimizer_engine="goal_based_v1", max_real_estate_bps=2000, max_alternatives_bps=1000,
        min_liquidity_bps=0, allow_other_assets_for_goals=1, created_by="adv",
        created_at=NOW, updated_at=NOW,
    )
    ta = TargetAllocation(
        id="ta", mandate_id="m", policy_id="pol", version=1, is_current=1,
        target_equities_bps=10000, target_bonds_bps=0, target_real_estate_bps=0,
        target_alternatives_bps=0, target_liquidity_bps=0,
        band_equities_min_bps=10000, band_equities_max_bps=10000,
        band_bonds_min_bps=0, band_bonds_max_bps=0,
        band_real_estate_min_bps=0, band_real_estate_max_bps=0,
        band_alternatives_min_bps=0, band_alternatives_max_bps=0,
        band_liquidity_min_bps=0, band_liquidity_max_bps=0,
        risky_fraction_bps=9000, risky_fraction_bps_at_generation=9000,
        risk_budget_bps_at_generation=9000,
        set_by="adv", set_at=NOW, created_at=NOW, updated_at=NOW,
    )
    run = RecommendationRun(
        id="run", mandate_id="m", client_id="cl", target_allocation_id="ta", policy_id="pol",
        run_type="full", result_status="Final", created_by="adv", created_at=NOW, updated_at=NOW,
    )
    s.add_all([advisor, client, mandate, policy, ta, run])
    s.flush()
    for pid, asset_class, currency in holdings:
        s.add(Product(
            id=f"prod-{pid}", isin=f"CH{pid.upper():0>10}", product_name=f"Fonds {pid}",
            product_type="ETF", asset_class=asset_class, currency=currency, ter_bps=20,
            provider="Test", is_active=1, created_at=NOW, updated_at=NOW,
        ))
        s.flush()
        s.add(RecommendationPosition(
            id=pid, run_id="run", product_id=f"prod-{pid}", target_weight_bps=0,
            created_at=NOW, updated_at=NOW,
        ))
        s.add(RecommendationHolding(
            id=f"h-{pid}", run_id="run", recommendation_position_id=pid, product_id=f"prod-{pid}",
            as_of_date=holding_date, units_milli=1_000_000, source="manual",
            created_at=NOW, updated_at=NOW,
        ))
        s.add(PriceHistory(
            id=f"px-{pid}", product_id=f"prod-{pid}", price_date=date.today().isoformat(),
            price_rappen=10_000, currency=currency, source="test", fetched_at=NOW,
        ))
    s.flush()
    return advisor, mandate


def _add_cash(s, valuation_date=None):
    s.add(WealthPosition(
        id="wp-cash", client_id="cl", label="Privatkonto", position_type="Liquidität",
        assignment="Beratungsvermögen", current_value_rappen=100_000, currency="CHF",
        valuation_date=valuation_date or date.today().isoformat(),
        liquidity_instrument="Kontoguthaben", alloc_liquidity_bps=10000, is_active=1,
        created_at=NOW, updated_at=NOW,
    ))
    s.flush()


# --- PROPOSED: sichtbar, nie blockierend ----------------------------------

def test_shipped_proposed_policy_gate_returns_without_db_access(monkeypatch):
    def _no_assessment(*_args, **_kwargs):
        raise AssertionError("ohne aktive Policy darf nichts ausgewertet werden")

    monkeypatch.setattr(gate_mod, "assess_mandate_portfolio_data", _no_assessment)
    for action in ("finalize", "pdf", "signature", "handoff"):
        assert gate_mod.assert_portfolio_data_release_eligible(None, None, action=action) is None
    with pytest.raises(ValueError):
        gate_mod.assert_portfolio_data_release_eligible(None, None, action="unbekannt")


def test_assessment_with_proposed_policy_warns_but_does_not_block(session_factory):
    with session_factory() as s:
        _advisor, mandate = _seed(s, holdings=(("eq", "Aktien", "CHF"), ("us", "Aktien", "USD")))
        result = gate_mod.assess_mandate_portfolio_data(s, mandate)

    assert result["policy"]["status"] == "PROPOSED"
    assert result["policy"]["active"] is False
    comps = result["freshness"]["components"]
    assert comps["holdings_as_of"]["status"] == "ok"
    assert comps["price_as_of"]["status"] == "ok"
    # USD ohne aktive FX-Zeile: versionierte Default-Kurse belegen keinen Stichtag.
    assert comps["fx_as_of"]["status"] == "missing_as_of"
    # Keine erfasste Liquiditaet ist kein Beleg fuer null.
    assert comps["cash_as_of"]["status"] == "missing_as_of"
    assert comps["cash_as_of"]["source"] is None
    # Fuer Corporate Actions gibt es keine Quelle.
    assert comps["corporate_actions_checked_at"]["status"] == "missing_as_of"
    assert result["freshness"]["usability"] == "blocked"
    assert result["reconciliation"]["status"] == "not_evaluated"
    for action in ("finalize", "pdf", "signature", "handoff"):
        gate = result["gates"][action]
        assert gate["would_block"] is True
        assert gate["blocked"] is False
        assert gate["enforced"] is False
        assert any("PROPOSED" in w for w in gate["warnings"])


def test_components_come_from_snapshot_cash_and_fx_rows(session_factory):
    with session_factory() as s:
        _advisor, mandate = _seed(s, holdings=(("eq", "Aktien", "CHF"), ("us", "Aktien", "USD")))
        _add_cash(s, valuation_date="2026-10-20")
        s.add(FXRate(
            id="fx-usd", currency="USD", rate_x10000=8800, valid_from="2026-10-19", is_current=1,
            source="API", created_at=NOW, updated_at=NOW,
        ))
        s.flush()
        result = gate_mod.assess_mandate_portfolio_data(
            s, mandate, advice_at=datetime(2026, 10, 26, 9, 0, tzinfo=timezone.utc),
        )
    comps = result["freshness"]["components"]
    assert comps["cash_as_of"]["as_of"] == "2026-10-20"
    assert comps["cash_as_of"]["source"] == "wealth_positions"
    assert comps["fx_as_of"]["as_of"] == "2026-10-19"
    assert comps["fx_as_of"]["source"] == "fx_rates:API"


def test_base_currency_only_depot_needs_no_fx_date(session_factory):
    with session_factory() as s:
        _advisor, mandate = _seed(s)
        _add_cash(s)
        result = gate_mod.assess_mandate_portfolio_data(s, mandate)
    comps = result["freshness"]["components"]
    assert comps["fx_as_of"]["status"] == "not_applicable"
    assert comps["cash_as_of"]["status"] == "ok"
    assert result["freshness"]["blocking_reasons"] == ["corporate_actions_checked_at:missing_as_of"]


def test_depot_snapshot_response_carries_assessment(session_factory):
    from routers.allocation import create_depot_snapshot, get_portfolio_data_assessment

    with session_factory() as s:
        advisor, mandate = _seed(s)
        request = SimpleNamespace(headers={}, client=SimpleNamespace(host="127.0.0.1"))
        response = create_depot_snapshot(mandate.id, request, db=s, current_user=advisor)
        assert response["portfolio_data"]["snapshot_id"] == response["snapshot"]["snapshot_id"]
        assert response["portfolio_data"]["gates"]["pdf"]["blocked"] is False
        assert response["portfolio_data"]["gates"]["pdf"]["would_block"] is True
        assessment = get_portfolio_data_assessment(mandate.id, db=s, current_user=advisor)
        assert assessment["policy"]["status"] == "PROPOSED"


def test_no_holdings_is_visible_as_freshness_error(session_factory):
    with session_factory() as s:
        _advisor, mandate = _seed(s, holdings=())
        result = gate_mod.assess_mandate_portfolio_data(s, mandate)
    assert result["freshness"] is None
    assert result["freshness_error"]
    assert result["gates"]["handoff"]["reasons"][0] == "freshness_not_evaluated"
    assert result["gates"]["handoff"]["blocked"] is False


# --- Aktive Policy: Finalisierung/PDF/Signatur/Handoff gesperrt -----------

@pytest.mark.parametrize("action", ["finalize", "pdf", "signature", "handoff"])
def test_active_policy_blocks_release_on_unproven_data(session_factory, active_policy, action):
    with session_factory() as s:
        _advisor, mandate = _seed(s)
        with pytest.raises(HTTPException) as exc:
            gate_mod.assert_portfolio_data_release_eligible(s, mandate, action=action)
    assert exc.value.status_code == 409
    detail = exc.value.detail
    assert detail["reason_code"] == "PORTFOLIO_DATA_NOT_RELEASABLE"
    assert detail["policy_version"] == active_policy.version
    assert "freshness_blocked" in detail["reasons"]
    assert "reconciliation_not_evaluated" in detail["reasons"]


def test_active_policy_blocks_advisory_pdf_endpoint_before_rendering(session_factory, active_policy, monkeypatch):
    import routers.pdf_reports as pdf_reports

    def _must_not_render(*_args, **_kwargs):  # pragma: no cover - darf nicht erreicht werden
        raise AssertionError("PDF wurde trotz Depot-Gate gerendert")

    monkeypatch.setattr(pdf_reports, "_enforce_cma_currency_release", _must_not_render)
    with session_factory() as s:
        advisor, mandate = _seed(s)
        with pytest.raises(HTTPException) as exc:
            pdf_reports.get_advisory_report_pdf(mandate.id, db=s, current_user=advisor)
    assert exc.value.status_code == 409
    assert exc.value.detail["reason_code"] == "PORTFOLIO_DATA_NOT_RELEASABLE"
    assert exc.value.detail["action"] == "pdf"


def test_proposed_policy_lets_advisory_pdf_endpoint_pass_the_gate(session_factory, monkeypatch):
    import routers.pdf_reports as pdf_reports

    class _PassedGate(Exception):
        pass

    def _after_gate(*_args, **_kwargs):
        raise _PassedGate()

    monkeypatch.setattr(pdf_reports, "_enforce_cma_currency_release", _after_gate)
    with session_factory() as s:
        advisor, mandate = _seed(s)
        with pytest.raises(_PassedGate):
            pdf_reports.get_advisory_report_pdf(mandate.id, db=s, current_user=advisor)


@pytest.mark.parametrize("module,function,action", [
    ("routers.review", "finalize_recommendation", "finalize"),
    ("routers.review", "sign_document", "signature"),
    ("routers.portfolio_handoff", "create_portfolio_handoff", "handoff"),
    ("routers.pdf_reports", "get_advisory_report_pdf", "pdf"),
])
def test_release_channels_call_the_gate(module, function, action):
    import importlib

    source = inspect.getsource(getattr(importlib.import_module(module), function))
    assert f'assert_portfolio_data_release_eligible(db, mandate, action="{action}")' in source
