"""Weiterleitung ans Asset Management (User-Direktive, 2026-08-08).

Ares berechnet nur die Zielallokation/Handelsliste; die Ausfuehrung liegt bei
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

import hashlib
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


# HANDOFF-DB-INVARIANT-001: neue Zeilen brauchen einen gueltigen Snapshot-Hash.
_EMPTY_SNAPSHOT_SHA = hashlib.sha256(b"[]").hexdigest()


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


def _budget_compliant_allocation(mandate_id: str, set_by: str, allocation_id: str):
    """RISK-BUDGET-RELEASE-GATE (2026-10-21): create_portfolio_handoff ruft
    das zentrale Freigabe-Gate auf, das die im Run verankerte Allokation
    samt Risikobudget-Nachweis verlangt. Ein Run ohne Allokation ist in
    Produktion ohnehin nicht weiterleitbar (build_recommendation_payload_from_run
    wirft dann); die Fixtures verankern darum eine budgetkonforme TA."""
    from models.allocation import TargetAllocation

    ts = "2026-08-08T00:00:00.000Z"
    return TargetAllocation(
        id=allocation_id, mandate_id=mandate_id, version=1, is_current=1,
        target_equities_bps=5500, target_bonds_bps=2500,
        target_real_estate_bps=1000, target_alternatives_bps=500,
        target_liquidity_bps=500,
        band_equities_min_bps=5000, band_equities_max_bps=6000,
        band_bonds_min_bps=2000, band_bonds_max_bps=3000,
        band_real_estate_min_bps=500, band_real_estate_max_bps=1500,
        band_alternatives_min_bps=0, band_alternatives_max_bps=1000,
        band_liquidity_min_bps=0, band_liquidity_max_bps=1000,
        risk_budget_bps_at_generation=7000, risky_fraction_bps_at_generation=6000,
        policy_id="policy-1", set_by=set_by, set_at=ts,
        created_at=ts, updated_at=ts,
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
        session.add(_budget_compliant_allocation(mandate_id, advisor_user.id, f"ta-{run_id}"))
        session.add(RecommendationRun(
            id=run_id, mandate_id=mandate_id, client_id="client-1", policy_id="policy-1",
            target_allocation_id=f"ta-{run_id}",
            run_type="Initial", result_status="Final", created_by=advisor_user.id,
            created_at="2026-08-08T00:00:00.000Z", updated_at="2026-08-08T00:00:00.000Z",
        ))
        session.commit()


def _full_valuation_coverage(position_count: int) -> dict:
    """HANDOFF-VALUATION-001: der Snapshot verlangt die Coverage-Aggregate
    von build_live_rebalancing_payload (echte Bestaende, frische Preise,
    erfolgreiche FX). Positivfaelle bilden vollstaendige Abdeckung ab."""
    return {
        "holding_positions_count": position_count,
        "implied_positions_count": 0,
        "missing_prices_count": 0,
        "stale_positions_count": 0,
        "fx_conversion_failed_count": 0,
    }


def _fake_payload(drifts: list[dict], total_value_rappen: int) -> dict:
    return {"live_rebalancing": {
        "live_total_value_rappen": total_value_rappen,
        "position_drifts": drifts,
        **_full_valuation_coverage(len(drifts)),
    }}


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
    # HANDOFF-INSTRUCTION-001: kuratierte Felder plus die von der Quelle
    # gelieferten Instruktionsfelder (hier nur der Referenzpreis) und die
    # Einstufung der Zeile -- keine weiteren internen Engine-Felder.
    allowed = (
        set(portfolio_handoff_service._SNAPSHOT_TRADE_FIELDS)
        | set(portfolio_handoff_service._SNAPSHOT_INSTRUCTION_FIELDS)
        | {"instruction_kind", "missing_instruction_fields"}
    )
    assert set(portfolio_handoff_service._SNAPSHOT_TRADE_FIELDS) <= set(trades[0].keys()) <= allowed
    assert trades[0]["reference_price_rappen"] == 9999
    # Ohne ISIN/Konto/Menge ist die Zeile eine Empfehlung, keine Instruktion.
    assert trades[0]["instruction_kind"] == "rebalancing_recommendation"
    assert trades[0]["missing_instruction_fields"] == ["isin", "custody_account_id", "current_units_milli"]


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
        assert result.status == "Vorbereitet"
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


# HANDOFF-EXECUTION-001: manuelle Ausfuehrungsbestaetigung mit Referenz.
# Ausfuehrungsdatum = Anlagedatum der Weiterleitung: nie davor und nie in der
# Zukunft -- unabhaengig davon, ob der Testlauf ueber Mitternacht (UTC) laeuft.
# (Ein beim Import fixiertes "heute" wurde nach Mitternacht zum Vortag -> 422.)
def _evidence(handoff, reference="ORD-4700", note=None):
    return PortfolioHandoffMarkExecuted(
        external_order_reference=reference,
        executed_on=str(handoff.created_at)[:10],
        executed_note=note,
    )


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
            body=_evidence(created, "ORD-4711", "Bank bestaetigt per Telefon"),
            request=_FakeRequest(), db=session, current_user=advisor_user,
        )
        assert executed.status == "Ausgeführt"
        assert executed.executed_by == advisor_user.id
        assert executed.executed_note == "Bank bestaetigt per Telefon"
        assert executed.execution_evidence_kind == "manual_attestation"
        assert executed.execution_external_reference == "ORD-4711"
        assert executed.execution_confirmed_on == str(created.created_at)[:10]

        # Zweiter Aufruf auf denselben (nicht mehr offenen) Handoff -> 409, kein Doppel-Transition.
        with pytest.raises(HTTPException) as exc:
            mark_portfolio_handoff_executed(
                mandate_id="mandate-1", handoff_id=created.id,
                body=_evidence(created),
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
            body=_evidence(created),
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


def test_concurrent_mark_executed_and_cancel_do_not_both_succeed(session_factory, advisor_user, monkeypatch):
    """REC-005 (Codex-Audit 2026-08-25): simuliert zwei nahezu gleichzeitige
    Aufrufe (Doppelklick, zwei Tabs) ueber ZWEI unabhaengige DB-Sessions
    (wie zwei echte HTTP-Requests) gegen denselben offenen Handoff. Vor dem
    Fix haette Session B den Vorzustand noch als 'Gesendet' im Speicher
    gehabt und ihren eigenen Endzustand klaglos durchgesetzt (Last-Write-
    Wins). Das atomare UPDATE...WHERE status=OPEN muss das verhindern --
    nur EINE Transition darf durchkommen, die andere bekommt 409."""
    _seed_mandate_and_run(session_factory, advisor_user)
    _patch_engine(monkeypatch, [_drift("prod-1", 50_000)])

    with session_factory() as setup_session:
        created = _create_handoff(setup_session, advisor_user)
        handoff_id = created.id

    # Zwei unabhaengige Sessions, wie zwei separate HTTP-Requests.
    with session_factory() as session_a, session_factory() as session_b:
        # Beide "sehen" den offenen Zustand, bevor irgendeine committet.
        _get_handoff_or_404 = portfolio_handoff_router._get_handoff_or_404
        seen_by_a = _get_handoff_or_404("mandate-1", handoff_id, session_a, advisor_user)
        seen_by_b = _get_handoff_or_404("mandate-1", handoff_id, session_b, advisor_user)
        assert seen_by_a.status == seen_by_b.status == "Vorbereitet"

        executed = mark_portfolio_handoff_executed(
            mandate_id="mandate-1", handoff_id=handoff_id,
            body=_evidence(created, "ORD-4712", "Bank bestaetigt"),
            request=_FakeRequest(), db=session_a, current_user=advisor_user,
        )
        assert executed.status == "Ausgeführt"

        with pytest.raises(HTTPException) as exc:
            cancel_portfolio_handoff(
                mandate_id="mandate-1", handoff_id=handoff_id,
                body=PortfolioHandoffCancel(cancelled_reason="Zu spaet"),
                request=_FakeRequest(), db=session_b, current_user=advisor_user,
            )
        assert exc.value.status_code == 409
        assert "Ausgeführt" in str(exc.value.detail)

    # Endgueltiger Zustand: genau EINE Transition hat gewonnen, nicht
    # "der letzte Schreiber".
    with session_factory() as verify_session:
        final = verify_session.query(PortfolioHandoff).filter(PortfolioHandoff.id == handoff_id).first()
        assert final.status == "Ausgeführt"
        assert final.cancelled_at is None
        assert final.cancelled_reason is None


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
            snapshot_sha256=_EMPTY_SNAPSHOT_SHA,  # HANDOFF-DB-INVARIANT-001
            holdings_basis="recorded_depot",  # Basis Pflicht fuer neue Zeilen
            recipient_name="A", status="Gesendet", created_by=advisor_user.id,
            created_at="2026-08-08T08:00:00.000Z", updated_at="2026-08-08T08:00:00.000Z",
        )
        h2 = PortfolioHandoff(
            id="handoff-new", mandate_id="mandate-1", recommendation_run_id="run-1",
            trade_list_snapshot_json="[]", live_total_value_rappen=1, position_count=0,
            snapshot_sha256=_EMPTY_SNAPSHOT_SHA,  # HANDOFF-DB-INVARIANT-001
            holdings_basis="recorded_depot",  # Basis Pflicht fuer neue Zeilen
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


# ===========================================================================
# HANDOFF-VALUATION-001 -- Bewertungsabdeckung blockiert fail-closed
# ===========================================================================


@pytest.mark.parametrize("blocker", [
    "implied_positions_count", "missing_prices_count",
    "stale_positions_count", "fx_conversion_failed_count",
])
def test_snapshot_blocks_on_each_coverage_gap(session_factory, advisor_user, monkeypatch, blocker):
    _seed_mandate_and_run(session_factory, advisor_user)
    payload = _fake_payload([_drift("prod-1", 50_000)], 1_000_000)
    payload["live_rebalancing"][blocker] = 1
    monkeypatch.setattr(portfolio_handoff_service, "build_recommendation_payload_from_run", lambda **kw: payload)

    with session_factory() as session:
        mandate = session.query(Mandate).filter(Mandate.id == "mandate-1").one()
        run = session.query(RecommendationRun).filter(RecommendationRun.id == "run-1").one()
        with pytest.raises(portfolio_handoff_service.HoldingsValuationIncompleteError):
            portfolio_handoff_service.snapshot_handoff_trades(session, mandate, run, advisor_user.id)


def test_snapshot_blocks_when_coverage_aggregates_are_missing(session_factory, advisor_user, monkeypatch):
    """Ein Payload ohne Coverage-Aggregate belegt keine Abdeckung -- kein
    stilles 'vollstaendig'."""
    _seed_mandate_and_run(session_factory, advisor_user)
    payload = {"live_rebalancing": {
        "live_total_value_rappen": 1_000_000, "position_drifts": [_drift("prod-1", 50_000)],
    }}
    monkeypatch.setattr(portfolio_handoff_service, "build_recommendation_payload_from_run", lambda **kw: payload)

    with session_factory() as session:
        mandate = session.query(Mandate).filter(Mandate.id == "mandate-1").one()
        run = session.query(RecommendationRun).filter(RecommendationRun.id == "run-1").one()
        with pytest.raises(portfolio_handoff_service.HoldingsValuationIncompleteError):
            portfolio_handoff_service.snapshot_handoff_trades(session, mandate, run, advisor_user.id)


def test_create_handoff_409_without_persisting_when_valuation_incomplete(session_factory, advisor_user, monkeypatch):
    _seed_mandate_and_run(session_factory, advisor_user)
    payload = _fake_payload([_drift("prod-1", 50_000)], 1_000_000)
    payload["live_rebalancing"]["implied_positions_count"] = 1
    monkeypatch.setattr(portfolio_handoff_service, "build_recommendation_payload_from_run", lambda **kw: payload)

    with session_factory() as session:
        with pytest.raises(HTTPException) as exc:
            _create_handoff(session, advisor_user)
        assert exc.value.status_code == 409
        assert session.query(PortfolioHandoff).count() == 0


# ===========================================================================
# HANDOFF-INSTRUCTION-001 -- Instruktionsfelder aus den echten Quellfeldern
# ===========================================================================


def test_snapshot_maps_live_source_fields_to_executable_instruction(session_factory, advisor_user, monkeypatch):
    """Das Live-Rebalancing liefert das Depotkonto als
    holding_custody_account_number und kennt die ISIN nur ueber das Produkt
    -- beides landet im Snapshot, die Zeile gilt dann als ausfuehrbar."""
    from models.review import Product

    _seed_mandate_and_run(session_factory, advisor_user)
    with session_factory() as session:
        session.add(Product(
            id="prod-1", product_name="Produkt prod-1", product_type="ETF", asset_class="Aktien",
            isin="CH0012032048", currency="CHF",
            created_at="2026-08-08T00:00:00.000Z", updated_at="2026-08-08T00:00:00.000Z",
        ))
        session.commit()
    drift = _drift(
        "prod-1", 50_000,
        holding_custody_account_number="CH93-0076-2011-6238-5295-7",
        current_units_milli=12_000, valuation_basis="actual_holding_units",
    )
    _patch_engine(monkeypatch, [drift])

    with session_factory() as session:
        mandate = session.query(Mandate).filter(Mandate.id == "mandate-1").one()
        run = session.query(RecommendationRun).filter(RecommendationRun.id == "run-1").one()
        trades, _ = portfolio_handoff_service.snapshot_handoff_trades(session, mandate, run, advisor_user.id)

    trade = trades[0]
    assert trade["isin"] == "CH0012032048"
    assert trade["custody_account_id"] == "CH93-0076-2011-6238-5295-7"
    assert trade["current_units_milli"] == 12_000
    assert trade["instruction_kind"] == "executable_instruction"
    assert trade["missing_instruction_fields"] == []
    # Nicht gelieferte Felder werden nicht erfunden.
    assert "order_type" not in trade and "fx_rate" not in trade


# ===========================================================================
# HANDOFF-DELIVERY-001 -- lokaler Insert behauptet keinen Versand
# ===========================================================================


def test_legacy_sent_handoff_stays_closable(session_factory, advisor_user, monkeypatch):
    """Vor dem Fix angelegte Zeilen tragen 'Gesendet' -- sie bleiben ein
    offener Altbestand und lassen sich weiterhin abschliessen."""
    _seed_mandate_and_run(session_factory, advisor_user)
    with session_factory() as session:
        session.add(PortfolioHandoff(
            id="handoff-legacy", mandate_id="mandate-1", recommendation_run_id="run-1",
            trade_list_snapshot_json="[]", live_total_value_rappen=1, position_count=0,
            snapshot_sha256=_EMPTY_SNAPSHOT_SHA,  # HANDOFF-DB-INVARIANT-001
            holdings_basis="recorded_depot",  # Basis Pflicht fuer neue Zeilen
            recipient_name="A", status="Gesendet", created_by=advisor_user.id,
            created_at="2026-08-08T08:00:00.000Z", updated_at="2026-08-08T08:00:00.000Z",
        ))
        session.commit()
        cancelled = cancel_portfolio_handoff(
            mandate_id="mandate-1", handoff_id="handoff-legacy",
            body=PortfolioHandoffCancel(cancelled_reason="Altbestand bereinigt"),
            request=_FakeRequest(), db=session, current_user=advisor_user,
        )
        assert cancelled.status == "Storniert"
        audit = session.query(AuditLog).filter(
            AuditLog.table_name == "portfolio_handoffs", AuditLog.action == "UPDATE",
        ).one()
        assert audit.old_value == "Gesendet"



# ===========================================================================
# HANDOFF-EXECUTION-001 -- Ausfuehrung nur mit Evidence
# ===========================================================================


@pytest.mark.parametrize("payload", [
    {},
    {"executed_note": "Bank bestaetigt"},
    {"external_order_reference": "  ", "executed_on": "2026-08-09"},
    {"external_order_reference": "ORD-1"},
    {"external_order_reference": "ORD-1", "executed_on": "2999-01-01"},
])
def test_mark_executed_schema_rejects_missing_or_implausible_evidence(payload):
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        PortfolioHandoffMarkExecuted(**payload)


def test_mark_executed_rejects_execution_before_handoff_creation(session_factory, advisor_user, monkeypatch):
    _seed_mandate_and_run(session_factory, advisor_user)
    _patch_engine(monkeypatch, [_drift("prod-1", 50_000)])

    with session_factory() as session:
        created = _create_handoff(session, advisor_user)
        with pytest.raises(HTTPException) as exc:
            mark_portfolio_handoff_executed(
                mandate_id="mandate-1", handoff_id=created.id,
                body=PortfolioHandoffMarkExecuted(external_order_reference="ORD-1", executed_on="2020-01-01"),
                request=_FakeRequest(), db=session, current_user=advisor_user,
            )
        assert exc.value.status_code == 422
        session.expire_all()
        assert session.query(PortfolioHandoff).filter(PortfolioHandoff.id == created.id).one().status == "Vorbereitet"


# ===========================================================================
# HANDOFF-IDEMPOTENCY-001 -- genau eine offene Weiterleitung je Identitaet
# ===========================================================================


def _create(session, advisor_user, **body):
    return create_portfolio_handoff(
        mandate_id="mandate-1", run_id="run-1",
        body=PortfolioHandoffCreate(**{"recipient_name": "Bank XY", **body}),
        request=_FakeRequest(), db=session, current_user=advisor_user,
    )


def test_identical_retry_returns_same_handoff_without_second_audit_row(session_factory, advisor_user, monkeypatch):
    _seed_mandate_and_run(session_factory, advisor_user)
    _patch_engine(monkeypatch, [_drift("prod-1", 50_000)])

    with session_factory() as session:
        first = _create(session, advisor_user, note="Q4")
        second = _create(session, advisor_user, note="Q4")
        assert second.id == first.id
        # Gleiche fachliche Identitaet (Empfaenger normalisiert), aber anderer
        # Request -> 409 statt zweiter offener Weiterleitung.
        with pytest.raises(HTTPException) as exc:
            _create(session, advisor_user, recipient_name="bank   XY", note="Q4")
        assert exc.value.status_code == 409
        assert first.business_key_hash and len(first.business_key_hash) == 64
        assert session.query(PortfolioHandoff).count() == 1
        assert session.query(AuditLog).filter(AuditLog.table_name == "portfolio_handoffs").count() == 1


def test_same_identity_with_different_request_is_409(session_factory, advisor_user, monkeypatch):
    _seed_mandate_and_run(session_factory, advisor_user)
    _patch_engine(monkeypatch, [_drift("prod-1", 50_000)])

    with session_factory() as session:
        first = _create(session, advisor_user, note="Q4")
        with pytest.raises(HTTPException) as exc:
            _create(session, advisor_user, note="anderer Auftrag")
        assert exc.value.status_code == 409
        assert exc.value.detail["reason_code"] == "HANDOFF_ALREADY_OPEN"
        assert exc.value.detail["handoff_id"] == first.id
        assert session.query(PortfolioHandoff).count() == 1


def test_changed_trades_or_closed_handoff_allow_a_new_one(session_factory, advisor_user, monkeypatch):
    _seed_mandate_and_run(session_factory, advisor_user)
    _patch_engine(monkeypatch, [_drift("prod-1", 50_000)])

    with session_factory() as session:
        first = _create(session, advisor_user)
        cancel_portfolio_handoff(
            mandate_id="mandate-1", handoff_id=first.id,
            body=PortfolioHandoffCancel(cancelled_reason="neu erfassen"),
            request=_FakeRequest(), db=session, current_user=advisor_user,
        )
        again = _create(session, advisor_user)
        assert again.id != first.id
        # Neuer fachlicher Inhalt -> neuer Schluessel, neue Zeile.
        _patch_engine(monkeypatch, [_drift("prod-1", 60_000)])
        changed = _create(session, advisor_user)
        assert changed.id not in {first.id, again.id}
        assert changed.business_key_hash != again.business_key_hash


def test_concurrent_identical_create_resolves_to_existing_via_unique_index(session_factory, advisor_user, monkeypatch):
    """Zwei parallele identische Requests: beide bestehen die Vorpruefung,
    der partielle Unique-Index laesst nur EINEN Insert zu, der Verlierer
    liefert das Ergebnis des Gewinners."""
    _seed_mandate_and_run(session_factory, advisor_user)
    _patch_engine(monkeypatch, [_drift("prod-1", 50_000)])

    with session_factory() as session_a:
        winner = _create(session_a, advisor_user)

    real_lookup = portfolio_handoff_router._open_handoff_with_business_key
    calls = {"n": 0}

    def _stale_first_lookup(db, mandate_id, business_key):
        calls["n"] += 1
        if calls["n"] == 1:
            return None  # Vorpruefung lief, bevor der Gewinner committet hat
        return real_lookup(db, mandate_id, business_key)

    monkeypatch.setattr(portfolio_handoff_router, "_open_handoff_with_business_key", _stale_first_lookup)
    with session_factory() as session_b:
        loser = _create(session_b, advisor_user)
        assert loser.id == winner.id
        assert session_b.query(PortfolioHandoff).count() == 1
    assert calls["n"] == 2


# ===========================================================================
# HANDOFF-INTEGRITY-001 -- Response liefert nur in sich stimmige Datensaetze
# ===========================================================================


def _response_dict(**overrides) -> dict:
    snapshot = json.dumps([{"product_id": "p"}], ensure_ascii=False)
    base = dict(
        id="h", mandate_id="mandate-1", recommendation_run_id="run-1",
        trade_list_snapshot_json=snapshot, live_total_value_rappen=1, position_count=1,
        recipient_name="A", recipient_channel=None, note=None, status="Vorbereitet",
        created_by="u", created_at="t", updated_at="t",
        executed_at=None, executed_by=None, executed_note=None,
        cancelled_at=None, cancelled_by=None, cancelled_reason=None,
        snapshot_sha256=__import__("hashlib").sha256(snapshot.encode("utf-8")).hexdigest(),
    )
    base.update(overrides)
    return base


@pytest.mark.parametrize("overrides", [
    {"status": "BROKEN"},
    {"trade_list_snapshot_json": "not-json"},
    {"trade_list_snapshot_json": "{\"a\": 1}", "snapshot_sha256": None},
    {"position_count": 2},
    {"snapshot_sha256": "0" * 64},
    {"status": "Ausgeführt"},                      # ohne executed_at
    {"executed_at": "t"},                          # offen, aber "ausgefuehrt"
    {"status": "Storniert"},                       # ohne cancelled_at
])
def test_response_rejects_incoherent_handoff(overrides):
    from pydantic import ValidationError
    from schemas.portfolio_handoff import PortfolioHandoffResponse

    with pytest.raises(ValidationError):
        PortfolioHandoffResponse.model_validate(_response_dict(**overrides))


def test_created_and_closed_handoffs_validate_with_their_snapshot_hash(session_factory, advisor_user, monkeypatch):
    from schemas.portfolio_handoff import PortfolioHandoffResponse

    _seed_mandate_and_run(session_factory, advisor_user)
    _patch_engine(monkeypatch, [_drift("prod-1", 50_000)])
    with session_factory() as session:
        created = _create_handoff(session, advisor_user)
        assert created.snapshot_sha256 and len(created.snapshot_sha256) == 64
        PortfolioHandoffResponse.model_validate(created)
        executed = mark_portfolio_handoff_executed(
            mandate_id="mandate-1", handoff_id=created.id, body=_evidence(created),
            request=_FakeRequest(), db=session, current_user=advisor_user,
        )
        PortfolioHandoffResponse.model_validate(executed)
        # Legacy-Zeilen ohne Hash bleiben lesbar.
        PortfolioHandoffResponse.model_validate(_response_dict(snapshot_sha256=None, status="Gesendet"))
