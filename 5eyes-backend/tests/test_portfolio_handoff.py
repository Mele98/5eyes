"""Weiterleitung ans Asset Management (User-Direktive, 2026-08-08).

5eyes berechnet nur die Zielallokation/Handelsliste; die Ausfuehrung liegt bei
der Depotbank/dem internen Asset Management. Diese Tests sperren den
Nachweis-Mechanismus: unveraenderlicher Trade-Snapshot (0.5%-Schwelle wie
openTradeList() im Frontend), Status-Lebenszyklus Gesendet->Ausgefuehrt/
Storniert (nur aus dem offenen Zustand, kein Doppel-Transition), Audit-Log-
Eintraege, Tenant-Isolation ueber die Mandat-Kette.

Der teure Engine-Aufruf (build_recommendation_payload_from_run, braucht
Risikoprofil+Soll-Allokation+CMA+Policy+Produkte+Preise) wird monkeypatcht --
identisches, im Repo etabliertes Muster wie
test_runtime_contracts.py::test_generate_recommendation_run_endpoint_reuses_result_allocation_payload
(dort wird services.portfolio_engine.generate_recommendation_run gepatcht statt
den vollen Fixture-Baum aufzubauen).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base
from models.clients import Client
from models.mandates import Mandate
from models.portfolio_handoff import PortfolioHandoff
from models.review import AuditLog, RecommendationRun
from models.users import User

import routers.portfolio_handoff as portfolio_handoff_router
import services.portfolio_handoff as portfolio_handoff_service
from routers.portfolio_handoff import (
    cancel_portfolio_handoff,
    create_portfolio_handoff,
    list_portfolio_handoffs,
    mark_portfolio_handoff_executed,
)
from schemas.portfolio_handoff import (
    PortfolioHandoffCancel,
    PortfolioHandoffCreate,
    PortfolioHandoffMarkExecuted,
)


class _FakeRequest:
    """Minimaler Request-Stub -- identisches Muster zu
    test_runtime_contracts.py::_FakeSignRequest (_extract_client_ip() braucht
    nur .headers.get(...) und .client.host)."""
    def __init__(self, host="127.0.0.1"):
        self.headers = {}
        self.client = type("C", (), {"host": host})()


@pytest.fixture()
def session_factory(tmp_path):
    db_path = tmp_path / "test_portfolio_handoff.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield testing_session_local
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture()
def advisor_user():
    return User(
        id="advisor-1", username="advisor", password_hash="hash", full_name="Advisor User",
        role="advisor", is_active=1,
        created_at="2026-08-08T00:00:00.000Z", updated_at="2026-08-08T00:00:00.000Z",
    )


def _seed_mandate_and_run(session_factory, advisor_user, mandate_id="mandate-1", run_id="run-1", mandate_type="Vermögensverwaltung") -> None:
    with session_factory() as session:
        session.add(User(
            id=advisor_user.id, username=advisor_user.username, password_hash=advisor_user.password_hash,
            full_name=advisor_user.full_name, role=advisor_user.role, is_active=advisor_user.is_active,
            created_at=advisor_user.created_at, updated_at=advisor_user.updated_at,
        ))
        session.add(Client(
            id="client-1", client_number="C-100001", first_name="Max", last_name="Muster",
            country_of_residence="CH", language="DE", household_type="Einzelperson",
            client_classification="Privatkunde", is_professional_opt_out=0, is_qualified_investor=0,
            advisor_id=advisor_user.id,
            created_at="2026-08-08T00:00:00.000Z", updated_at="2026-08-08T00:00:00.000Z",
        ))
        session.add(Mandate(
            id=mandate_id, client_id="client-1", mandate_number="M-100001",
            mandate_type=mandate_type, status="Aktiv", base_currency="CHF",
            advisory_language="DE", opened_at="2026-08-08",
            created_at="2026-08-08T00:00:00.000Z", updated_at="2026-08-08T00:00:00.000Z",
        ))
        session.add(RecommendationRun(
            id=run_id, mandate_id=mandate_id, client_id="client-1", policy_id="policy-1",
            run_type="Initial", result_status="Final", created_by=advisor_user.id,
            created_at="2026-08-08T00:00:00.000Z", updated_at="2026-08-08T00:00:00.000Z",
        ))
        session.commit()


def _fake_payload(drifts: list[dict], total_value_rappen: int) -> dict:
    return {"live_rebalancing": {"live_total_value_rappen": total_value_rappen, "position_drifts": drifts}}


def _drift(product_id: str, rebalance_amount_rappen: int, **overrides) -> dict:
    entry = {
        "product_id": product_id,
        "product_name": f"Produkt {product_id}",
        "asset_class": "Aktien",
        "sub_asset_class": "Aktien Global",
        "product_currency": "CHF",
        "rebalance_action": "BUY" if rebalance_amount_rappen > 0 else "SELL",
        "rebalance_action_code": "BUY" if rebalance_amount_rappen > 0 else "SELL",
        "current_market_value_rappen": 100_000,
        "target_amount_rappen": 100_000 + rebalance_amount_rappen,
        "rebalance_amount_rappen": rebalance_amount_rappen,
        "current_weight_bps": 1000,
        "target_weight_bps": 1200,
        "reference_price_rappen": 9999,  # nicht Teil der kuratierten Snapshot-Felder
    }
    entry.update(overrides)
    return entry


# ===========================================================================
# services/portfolio_handoff.py::snapshot_handoff_trades — reine Logik-Tests
# ===========================================================================


def test_snapshot_filters_trades_below_half_percent_threshold(session_factory, advisor_user, monkeypatch):
    _seed_mandate_and_run(session_factory, advisor_user)
    # Gesamtsumme 1'000'000 Rappen -> Schwelle 5'000 Rappen (0.5%).
    payload = _fake_payload(
        drifts=[
            _drift("prod-big", 50_000),      # klar ueber der Schwelle
            _drift("prod-tiny", 2_000),      # unter der Schwelle -> muss rausfallen
            _drift("prod-boundary", -5_000), # exakt an der Schwelle -> muss bleiben (>=)
        ],
        total_value_rappen=1_000_000,
    )
    monkeypatch.setattr(portfolio_handoff_service, "build_recommendation_payload_from_run", lambda **kw: payload)

    with session_factory() as session:
        mandate = session.query(Mandate).filter(Mandate.id == "mandate-1").one()
        run = session.query(RecommendationRun).filter(RecommendationRun.id == "run-1").one()
        trades, total = portfolio_handoff_service.snapshot_handoff_trades(session, mandate, run, advisor_user.id)

    assert total == 1_000_000
    ids = {t["product_id"] for t in trades}
    assert ids == {"prod-big", "prod-boundary"}
    # Sortiert nach absolutem Betrag absteigend.
    assert [t["product_id"] for t in trades] == ["prod-big", "prod-boundary"]
    # Nur kuratierte Felder im Snapshot -- kein reference_price_rappen etc.
    assert set(trades[0].keys()) == set(portfolio_handoff_service._SNAPSHOT_TRADE_FIELDS)


def test_snapshot_raises_when_no_trades_above_threshold(session_factory, advisor_user, monkeypatch):
    _seed_mandate_and_run(session_factory, advisor_user)
    payload = _fake_payload(drifts=[_drift("prod-tiny", 100)], total_value_rappen=1_000_000)
    monkeypatch.setattr(portfolio_handoff_service, "build_recommendation_payload_from_run", lambda **kw: payload)

    with session_factory() as session:
        mandate = session.query(Mandate).filter(Mandate.id == "mandate-1").one()
        run = session.query(RecommendationRun).filter(RecommendationRun.id == "run-1").one()
        with pytest.raises(portfolio_handoff_service.NoTradeListAvailableError):
            portfolio_handoff_service.snapshot_handoff_trades(session, mandate, run, advisor_user.id)


def test_snapshot_raises_when_no_live_rebalancing_data(session_factory, advisor_user, monkeypatch):
    _seed_mandate_and_run(session_factory, advisor_user)
    monkeypatch.setattr(portfolio_handoff_service, "build_recommendation_payload_from_run", lambda **kw: {"live_rebalancing": {}})

    with session_factory() as session:
        mandate = session.query(Mandate).filter(Mandate.id == "mandate-1").one()
        run = session.query(RecommendationRun).filter(RecommendationRun.id == "run-1").one()
        with pytest.raises(portfolio_handoff_service.NoTradeListAvailableError):
            portfolio_handoff_service.snapshot_handoff_trades(session, mandate, run, advisor_user.id)


# ===========================================================================
# routers/portfolio_handoff.py — Router-/Statuslogik-Tests
# ===========================================================================


def _patch_engine(monkeypatch, drifts, total_value_rappen=1_000_000):
    payload = _fake_payload(drifts=drifts, total_value_rappen=total_value_rappen)
    monkeypatch.setattr(portfolio_handoff_service, "build_recommendation_payload_from_run", lambda **kw: payload)


def test_create_handoff_persists_snapshot_and_writes_audit_log(session_factory, advisor_user, monkeypatch):
    _seed_mandate_and_run(session_factory, advisor_user)
    _patch_engine(monkeypatch, [_drift("prod-1", 50_000)])

    with session_factory() as session:
        result = create_portfolio_handoff(
            mandate_id="mandate-1", run_id="run-1",
            body=PortfolioHandoffCreate(recipient_name="Bank XY Trading Desk", recipient_channel="E-Mail", note="Quartalsrebalancing"),
            request=_FakeRequest(), db=session, current_user=advisor_user,
        )
        assert result.status == "Gesendet"
        assert result.position_count == 1
        assert result.live_total_value_rappen == 1_000_000
        assert result.recipient_name == "Bank XY Trading Desk"
        snapshot = json.loads(result.trade_list_snapshot_json)
        assert snapshot[0]["product_id"] == "prod-1"

        audit_rows = session.query(AuditLog).filter(AuditLog.table_name == "portfolio_handoffs").all()
        assert len(audit_rows) == 1
        assert audit_rows[0].action == "CREATE"
        assert audit_rows[0].mandate_id == "mandate-1"


def test_create_handoff_raises_409_when_no_tradeable_positions(session_factory, advisor_user, monkeypatch):
    _seed_mandate_and_run(session_factory, advisor_user)
    _patch_engine(monkeypatch, [])

    with session_factory() as session:
        with pytest.raises(HTTPException) as exc:
            create_portfolio_handoff(
                mandate_id="mandate-1", run_id="run-1",
                body=PortfolioHandoffCreate(recipient_name="Bank XY"),
                request=_FakeRequest(), db=session, current_user=advisor_user,
            )
    assert exc.value.status_code == 409


def test_create_handoff_403_for_non_discretionary_mandate(session_factory, advisor_user, monkeypatch):
    """mandate_type ist die Compliance-Untergrenze (wie
    _reviewIsDiscretionaryMandate() im Frontend und
    services.advisory_report._erkenntnisse_is_discretionary_mandate) -- reine
    Anlageberatung hat keine Ausfuehrungsbefugnis und darf keine Weiterleitung
    an die Depotstelle erzeugen, auch nicht per direktem API-Aufruf."""
    _seed_mandate_and_run(session_factory, advisor_user, mandate_type="Anlageberatung")
    _patch_engine(monkeypatch, [_drift("prod-1", 50_000)])

    with session_factory() as session:
        with pytest.raises(HTTPException) as exc:
            create_portfolio_handoff(
                mandate_id="mandate-1", run_id="run-1",
                body=PortfolioHandoffCreate(recipient_name="Bank XY"),
                request=_FakeRequest(), db=session, current_user=advisor_user,
            )
    assert exc.value.status_code == 403


def test_create_handoff_404_for_unknown_run(session_factory, advisor_user, monkeypatch):
    _seed_mandate_and_run(session_factory, advisor_user)
    _patch_engine(monkeypatch, [_drift("prod-1", 50_000)])

    with session_factory() as session:
        with pytest.raises(HTTPException) as exc:
            create_portfolio_handoff(
                mandate_id="mandate-1", run_id="run-does-not-exist",
                body=PortfolioHandoffCreate(recipient_name="Bank XY"),
                request=_FakeRequest(), db=session, current_user=advisor_user,
            )
    assert exc.value.status_code == 404


def _create_handoff(session, advisor_user):
    return create_portfolio_handoff(
        mandate_id="mandate-1", run_id="run-1",
        body=PortfolioHandoffCreate(recipient_name="Bank XY"),
        request=_FakeRequest(), db=session, current_user=advisor_user,
    )


def test_mark_executed_transitions_status_and_is_not_repeatable(session_factory, advisor_user, monkeypatch):
    _seed_mandate_and_run(session_factory, advisor_user)
    _patch_engine(monkeypatch, [_drift("prod-1", 50_000)])

    with session_factory() as session:
        created = _create_handoff(session, advisor_user)
        executed = mark_portfolio_handoff_executed(
            mandate_id="mandate-1", handoff_id=created.id,
            body=PortfolioHandoffMarkExecuted(executed_note="Bank bestaetigt per Telefon"),
            request=_FakeRequest(), db=session, current_user=advisor_user,
        )
        assert executed.status == "Ausgeführt"
        assert executed.executed_by == advisor_user.id
        assert executed.executed_note == "Bank bestaetigt per Telefon"

        # Zweiter Aufruf auf denselben (nicht mehr offenen) Handoff -> 409, kein Doppel-Transition.
        with pytest.raises(HTTPException) as exc:
            mark_portfolio_handoff_executed(
                mandate_id="mandate-1", handoff_id=created.id,
                body=PortfolioHandoffMarkExecuted(),
                request=_FakeRequest(), db=session, current_user=advisor_user,
            )
        assert exc.value.status_code == 409


def test_cancel_requires_reason_and_blocks_after_execution(session_factory, advisor_user, monkeypatch):
    _seed_mandate_and_run(session_factory, advisor_user)
    _patch_engine(monkeypatch, [_drift("prod-1", 50_000)])

    with session_factory() as session:
        created = _create_handoff(session, advisor_user)
        mark_portfolio_handoff_executed(
            mandate_id="mandate-1", handoff_id=created.id,
            body=PortfolioHandoffMarkExecuted(),
            request=_FakeRequest(), db=session, current_user=advisor_user,
        )
        # Ein bereits ausgefuehrter Handoff darf nicht mehr storniert werden.
        with pytest.raises(HTTPException) as exc:
            cancel_portfolio_handoff(
                mandate_id="mandate-1", handoff_id=created.id,
                body=PortfolioHandoffCancel(cancelled_reason="Testabbruch"),
                request=_FakeRequest(), db=session, current_user=advisor_user,
            )
    assert exc.value.status_code == 409


def test_cancel_open_handoff_records_reason(session_factory, advisor_user, monkeypatch):
    _seed_mandate_and_run(session_factory, advisor_user)
    _patch_engine(monkeypatch, [_drift("prod-1", 50_000)])

    with session_factory() as session:
        created = _create_handoff(session, advisor_user)
        cancelled = cancel_portfolio_handoff(
            mandate_id="mandate-1", handoff_id=created.id,
            body=PortfolioHandoffCancel(cancelled_reason="Kunde hat Order storniert"),
            request=_FakeRequest(), db=session, current_user=advisor_user,
        )
        assert cancelled.status == "Storniert"
        assert cancelled.cancelled_reason == "Kunde hat Order storniert"
        assert cancelled.cancelled_by == advisor_user.id


def test_list_handoffs_orders_newest_first(session_factory, advisor_user, monkeypatch):
    _seed_mandate_and_run(session_factory, advisor_user)
    _patch_engine(monkeypatch, [_drift("prod-1", 50_000)])

    with session_factory() as session:
        h1 = PortfolioHandoff(
            id="handoff-old", mandate_id="mandate-1", recommendation_run_id="run-1",
            trade_list_snapshot_json="[]", live_total_value_rappen=1, position_count=0,
            recipient_name="A", status="Gesendet", created_by=advisor_user.id,
            created_at="2026-08-08T08:00:00.000Z", updated_at="2026-08-08T08:00:00.000Z",
        )
        h2 = PortfolioHandoff(
            id="handoff-new", mandate_id="mandate-1", recommendation_run_id="run-1",
            trade_list_snapshot_json="[]", live_total_value_rappen=1, position_count=0,
            recipient_name="B", status="Gesendet", created_by=advisor_user.id,
            created_at="2026-08-08T09:00:00.000Z", updated_at="2026-08-08T09:00:00.000Z",
        )
        session.add_all([h1, h2])
        session.commit()

        results = list_portfolio_handoffs(mandate_id="mandate-1", db=session, current_user=advisor_user)
        assert [r.id for r in results] == ["handoff-new", "handoff-old"]


def test_handoff_endpoints_404_for_foreign_mandate(session_factory, advisor_user, monkeypatch):
    _seed_mandate_and_run(session_factory, advisor_user)
    _patch_engine(monkeypatch, [_drift("prod-1", 50_000)])

    with session_factory() as session:
        with pytest.raises(HTTPException) as exc:
            create_portfolio_handoff(
                mandate_id="mandate-does-not-exist", run_id="run-1",
                body=PortfolioHandoffCreate(recipient_name="Bank XY"),
                request=_FakeRequest(), db=session, current_user=advisor_user,
            )
    assert exc.value.status_code == 404
