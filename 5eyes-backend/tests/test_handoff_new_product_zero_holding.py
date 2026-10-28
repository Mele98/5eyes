"""HANDOFF-NEW-PRODUCT-001: Erst-Umsetzung mit neuen Produkten.

Nach HANDOFF-VALUATION-001 blockierte jede Position ohne erfassten Bestand
den Handoff (sie war nur aus dem Zielbetrag abgeleitet, "implied"). Ein
Produkt im SOLL, das der Kunde noch nicht haelt, liess sich aber gar nicht als
Nullbestand erfassen -- jede reale Erst-Umsetzung (Kauf neuer Produkte) war
damit blockiert.

CIO-Entscheid: Ein SOLL-Produkt, das im erfassten Depot nicht vorkommt, hat
IST = 0 -- aber nur, wenn das Depot nachweislich vollstaendig erfasst ist
(jede gehaltene Position bewertet und mit Bestands-Stichtag, Preise/FX
aktuell). Dann ist der Kauf ein normaler Trade mit IST = 0 und
``holding_origin = "not_held"``. Ein Mandat ganz ohne Bestand (Neugeld)
braucht die ausdrueckliche Bestaetigung ``confirm_no_existing_holdings``;
ein stiller Default existiert nicht. Alles andere bleibt fail-closed (409).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from models.portfolio_handoff import PortfolioHandoff  # noqa: E402
from models.wealth import WealthPosition  # noqa: E402
from routers.portfolio_handoff import create_portfolio_handoff  # noqa: E402
from schemas.portfolio_handoff import PortfolioHandoffCreate, PortfolioHandoffResponse  # noqa: E402
import services.portfolio_handoff as portfolio_handoff_service  # noqa: E402
from services.portfolio_engine_live_rebalancing import _build_live_position_drifts  # noqa: E402

from test_portfolio_handoff import (  # noqa: E402
    _FakeRequest,
    _seed_mandate_and_run,
    advisor_user,
    session_factory,
)

_PRICE = 10_000  # CHF 100.00 je Anteil


def _entry(product_id: str, weight_bps: int, run_target_rappen: int, held_value_rappen: int | None,
           *, as_of: str | None = "2026-10-20") -> dict:
    """Live-Rebalancing-Eintrag wie services/portfolio_engine_live_rebalancing.py
    ihn baut: ohne Bestand ist IST = Zielbetrag (implied_from_target)."""
    held = held_value_rappen is not None
    current = held_value_rappen if held else run_target_rappen
    return {
        "id": f"pos-{product_id}",
        "product_id": product_id,
        "product_name": f"Produkt {product_id}",
        "asset_class": "Aktien",
        "sub_asset_class": "Aktien Global",
        "product_currency": "CHF",
        "target_weight_bps": weight_bps,
        "target_amount_rappen": run_target_rappen,
        "reference_price_rappen": _PRICE,
        "latest_price_rappen": _PRICE,
        "holding_present": held,
        "holding_as_of_date": as_of if held else None,
        "holding_custody_account_number": "CH-DEPOT-1" if held else None,
        "valuation_basis": "actual_holding_units" if held else "implied_from_target",
        "current_units_milli": current * 1000 // _PRICE,
        "current_market_value_rappen": current,
    }


def _payload(entries: list[dict], *, investable_rappen: int = 1_000_000, **coverage) -> dict:
    """Payload so, wie build_recommendation_payload_from_run ihn liefert."""
    total = sum(e["current_market_value_rappen"] for e in entries)
    held = sum(1 for e in entries if e["holding_present"])
    live = {
        "live_total_value_rappen": total,
        "position_drifts": _build_live_position_drifts(entries, total),
        "holding_positions_count": held,
        "implied_positions_count": len(entries) - held,
        "missing_prices_count": 0,
        "stale_positions_count": 0,
        "fx_conversion_failed_count": 0,
    }
    live.update(coverage)
    return {"investable_advisory_wealth_rappen": investable_rappen, "live_rebalancing": live}


def _patch(monkeypatch, payload: dict) -> None:
    monkeypatch.setattr(portfolio_handoff_service, "build_recommendation_payload_from_run", lambda **kw: payload)


def _create(session, advisor_user, **body):
    return create_portfolio_handoff(
        mandate_id="mandate-1", run_id="run-1",
        body=PortfolioHandoffCreate(recipient_name="Bank XY", **body),
        request=_FakeRequest(), db=session, current_user=advisor_user,
    )


def _existing_depot_with_new_product() -> list[dict]:
    # Run auf CHF 10'000 Beratungsvermoegen: A 50 %, B 30 %, C 20 % (neu).
    return [
        _entry("A", 5000, 500_000, 600_000),
        _entry("B", 3000, 300_000, 400_000),
        _entry("C", 2000, 200_000, None),
    ]


def _neugeld() -> list[dict]:
    return [
        _entry("A", 5000, 500_000, None),
        _entry("B", 3000, 300_000, None),
        _entry("C", 2000, 200_000, None),
    ]


def _by_product(handoff) -> dict:
    return {t["product_id"]: t for t in json.loads(handoff.trade_list_snapshot_json)}


# ---------------------------------------------------------------------------
# Erst-Umsetzung mit vollstaendig erfasstem Depot
# ---------------------------------------------------------------------------


def test_complete_depot_with_new_product_creates_handoff_with_zero_ist(session_factory, advisor_user, monkeypatch):
    _seed_mandate_and_run(session_factory, advisor_user)
    _patch(monkeypatch, _payload(_existing_depot_with_new_product()))

    with session_factory() as session:
        handoff = _create(session, advisor_user)
        PortfolioHandoffResponse.model_validate(handoff)

    assert handoff.holdings_basis == "recorded_depot"
    # Basis = Summe der echten Bestaende (CHF 10'000), nicht der implizite Wert von C.
    assert handoff.live_total_value_rappen == 1_000_000
    trades = _by_product(handoff)
    new = trades["C"]
    assert new["holding_origin"] == "not_held"
    assert new["current_market_value_rappen"] == 0
    assert new["current_units_milli"] == 0
    assert new["rebalance_action_code"] == "BUY"
    assert new["rebalance_amount_rappen"] == new["target_amount_rappen"] == 200_000
    assert trades["A"]["holding_origin"] == "held"
    assert trades["A"]["rebalance_amount_rappen"] == -100_000
    assert trades["B"]["rebalance_amount_rappen"] == -100_000
    for trade in trades.values():
        # HANDOFF-MATH-001 bleibt gewahrt: IST + Delta = SOLL.
        assert trade["current_market_value_rappen"] + trade["rebalance_amount_rappen"] == trade["target_amount_rappen"]
    assert sum(t["rebalance_amount_rappen"] for t in trades.values()) == 0


def test_fully_held_depot_keeps_previous_snapshot_and_marks_rows_held(session_factory, advisor_user, monkeypatch):
    _seed_mandate_and_run(session_factory, advisor_user)
    entries = [_entry("A", 5000, 500_000, 600_000), _entry("B", 5000, 500_000, 400_000)]
    payload = _payload(entries)
    _patch(monkeypatch, payload)

    with session_factory() as session:
        handoff = _create(session, advisor_user)

    trades = _by_product(handoff)
    assert {t["holding_origin"] for t in trades.values()} == {"held"}
    assert handoff.live_total_value_rappen == payload["live_rebalancing"]["live_total_value_rappen"]
    assert trades["A"]["rebalance_amount_rappen"] == -100_000


# ---------------------------------------------------------------------------
# Unvollstaendiges/veraltetes Depot bleibt fail-closed
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("variant", [
    "missing_as_of", "stale_price", "missing_price", "fx_failed", "count_mismatch", "unmarked_rows",
])
def test_incomplete_depot_with_new_product_stays_409(session_factory, advisor_user, monkeypatch, variant):
    _seed_mandate_and_run(session_factory, advisor_user)
    entries = _existing_depot_with_new_product()
    coverage = {}
    if variant == "missing_as_of":
        entries[0] = _entry("A", 5000, 500_000, 600_000, as_of=None)
    elif variant == "stale_price":
        coverage["stale_positions_count"] = 1
    elif variant == "missing_price":
        coverage["missing_prices_count"] = 1
    elif variant == "fx_failed":
        coverage["fx_conversion_failed_count"] = 1
    elif variant == "count_mismatch":
        coverage["implied_positions_count"] = 2
    payload = _payload(entries, **coverage)
    if variant == "unmarked_rows":
        for drift in payload["live_rebalancing"]["position_drifts"]:
            drift.pop("holding_present")
    _patch(monkeypatch, payload)

    with session_factory() as session:
        with pytest.raises(HTTPException) as exc:
            _create(session, advisor_user)
        assert exc.value.status_code == 409
        assert session.query(PortfolioHandoff).count() == 0


# ---------------------------------------------------------------------------
# Neugeld: kein Bestand nur mit ausdruecklicher Bestaetigung
# ---------------------------------------------------------------------------


def test_create_schema_has_no_silent_no_holdings_default():
    assert PortfolioHandoffCreate(recipient_name="Bank XY").confirm_no_existing_holdings is False
    with pytest.raises(ValidationError):
        PortfolioHandoffCreate(recipient_name="Bank XY", confirm_no_existing_holdings="vielleicht")


def test_new_money_mandate_without_confirmation_is_409(session_factory, advisor_user, monkeypatch):
    _seed_mandate_and_run(session_factory, advisor_user)
    _patch(monkeypatch, _payload(_neugeld()))

    with session_factory() as session:
        with pytest.raises(HTTPException) as exc:
            _create(session, advisor_user)
        assert exc.value.status_code == 409
        assert "confirm_no_existing_holdings" in str(exc.value.detail)
        assert session.query(PortfolioHandoff).count() == 0


def test_new_money_mandate_with_confirmation_creates_buy_list(session_factory, advisor_user, monkeypatch):
    _seed_mandate_and_run(session_factory, advisor_user)
    _patch(monkeypatch, _payload(_neugeld(), investable_rappen=1_200_000))

    with session_factory() as session:
        handoff = _create(session, advisor_user, confirm_no_existing_holdings=True)
        PortfolioHandoffResponse.model_validate(handoff)

    assert handoff.holdings_basis == "confirmed_no_holdings"
    # Basis = investierbares Beratungsvermoegen, nicht die impliziten Zielwerte.
    assert handoff.live_total_value_rappen == 1_200_000
    trades = _by_product(handoff)
    assert {t["holding_origin"] for t in trades.values()} == {"not_held"}
    assert {t["rebalance_action_code"] for t in trades.values()} == {"BUY"}
    assert [trades[p]["rebalance_amount_rappen"] for p in "ABC"] == [600_000, 360_000, 240_000]
    assert all(t["current_market_value_rappen"] == 0 for t in trades.values())


def test_new_money_confirmation_without_investable_wealth_is_409(session_factory, advisor_user, monkeypatch):
    _seed_mandate_and_run(session_factory, advisor_user)
    _patch(monkeypatch, _payload(_neugeld(), investable_rappen=0))

    with session_factory() as session:
        with pytest.raises(HTTPException) as exc:
            _create(session, advisor_user, confirm_no_existing_holdings=True)
        assert exc.value.status_code == 409


def test_new_money_confirmation_rejected_when_advisory_wealth_holds_a_depot(session_factory, advisor_user, monkeypatch):
    """Ein Mandat, dessen Beratungsvermoegen ein Wertschriftendepot enthaelt,
    muss Bestand haben -- die Neugeld-Bestaetigung widerspricht dem."""
    _seed_mandate_and_run(session_factory, advisor_user)
    with session_factory() as session:
        session.add(WealthPosition(
            id="wp-depot", client_id="client-1", label="Wertschriftendepot", position_type="Depot",
            assignment="Beratungsvermögen", current_value_rappen=1_000_000, currency="CHF",
            alloc_equities_bps=10000,
            created_at="2026-08-08T00:00:00.000Z", updated_at="2026-08-08T00:00:00.000Z",
        ))
        session.commit()
    _patch(monkeypatch, _payload(_neugeld()))

    with session_factory() as session:
        with pytest.raises(HTTPException) as exc:
            _create(session, advisor_user, confirm_no_existing_holdings=True)
        assert exc.value.status_code == 409
        assert session.query(PortfolioHandoff).count() == 0


def test_no_holdings_confirmation_contradicting_recorded_holdings_is_409(session_factory, advisor_user, monkeypatch):
    _seed_mandate_and_run(session_factory, advisor_user)
    _patch(monkeypatch, _payload(_existing_depot_with_new_product()))

    with session_factory() as session:
        with pytest.raises(HTTPException) as exc:
            _create(session, advisor_user, confirm_no_existing_holdings=True)
        assert exc.value.status_code == 409
