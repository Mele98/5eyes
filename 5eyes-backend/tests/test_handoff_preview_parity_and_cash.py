"""HANDOFF-PREVIEW-PARITY-001 und HANDOFF-CASH-BASIS-001.

* Vorschau: Die Handelsliste im Monolithen rechnete clientseitig aus den
  Live-Drifts und zeigte nicht gehaltene Produkte ohne Kauf, waehrend der
  weitergeleitete Snapshot den Kauf enthielt. Soll: ein read-only
  Vorschau-Endpunkt ueber dieselbe Funktion wie die Snapshot-Erzeugung, ohne
  Persistieren. Vorschau-Zeilen == Snapshot-Zeilen bei gleichen Eingaben.
* Cash-Basis (CIO-Entscheid): Bewertete Liquiditaetspositionen des
  Beratungsvermoegens zaehlen bei erfasstem Depot als Cash-IST in der Basis;
  ohne Stichtag/Waehrung oder ohne FX-Kurs fail-closed (409).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from models.portfolio_handoff import PortfolioHandoff  # noqa: E402
from models.review import AuditLog  # noqa: E402
from models.wealth import WealthPosition  # noqa: E402
from routers.portfolio_handoff import preview_portfolio_handoff  # noqa: E402
from schemas.portfolio_handoff import PortfolioHandoffResponse  # noqa: E402
from services.currency.fx_rates import FXRateSource  # noqa: E402

from test_handoff_new_product_zero_holding import (  # noqa: E402
    _create,
    _entry,
    _existing_depot_with_new_product,
    _neugeld,
    _patch,
    _payload,
)
from test_portfolio_handoff import (  # noqa: E402
    _seed_mandate_and_run,
    advisor_user,
    session_factory,
)


def _preview(session, advisor_user, confirm=False, mandate_id="mandate-1"):
    return preview_portfolio_handoff(
        mandate_id=mandate_id, run_id="run-1", confirm_no_existing_holdings=confirm,
        db=session, current_user=advisor_user,
    )


def _add_cash(session_factory, wp_id="wp-cash", value=200_000, currency="CHF",
              valuation_date="2026-10-20", assignment="Beratungsvermögen", is_active=1):
    with session_factory() as session:
        session.add(WealthPosition(
            id=wp_id, client_id="client-1", label="Privatkonto", position_type="Liquidität",
            assignment=assignment, current_value_rappen=value, currency=currency,
            valuation_date=valuation_date, liquidity_instrument="Kontoguthaben",
            alloc_liquidity_bps=10000, is_active=is_active,
            created_at="2026-08-08T00:00:00.000Z", updated_at="2026-08-08T00:00:00.000Z",
        ))
        session.commit()


def _rows(handoff) -> list[dict]:
    return json.loads(handoff.trade_list_snapshot_json)


def _assert_parity(preview, handoff):
    assert preview.trades == _rows(handoff)
    assert preview.snapshot_sha256 == handoff.snapshot_sha256
    assert preview.live_total_value_rappen == handoff.live_total_value_rappen
    assert preview.holdings_basis == handoff.holdings_basis
    assert preview.position_count == handoff.position_count


# ---------------------------------------------------------------------------
# HANDOFF-PREVIEW-PARITY-001
# ---------------------------------------------------------------------------


def test_preview_shows_new_product_buy_and_equals_snapshot(session_factory, advisor_user, monkeypatch):
    _seed_mandate_and_run(session_factory, advisor_user)
    _patch(monkeypatch, _payload(_existing_depot_with_new_product()))

    with session_factory() as session:
        preview = _preview(session, advisor_user)
    by_product = {t["product_id"]: t for t in preview.trades}
    assert by_product["C"]["holding_origin"] == "not_held"
    assert by_product["C"]["rebalance_action_code"] == "BUY"
    assert by_product["C"]["current_market_value_rappen"] == 0

    with session_factory() as session:
        handoff = _create(session, advisor_user)
    _assert_parity(preview, handoff)


def test_preview_with_new_money_confirmation_equals_snapshot(session_factory, advisor_user, monkeypatch):
    _seed_mandate_and_run(session_factory, advisor_user)
    _patch(monkeypatch, _payload(_neugeld(), investable_rappen=1_200_000))

    with session_factory() as session:
        preview = _preview(session, advisor_user, confirm=True)
    assert preview.holdings_basis == "confirmed_no_holdings"
    assert preview.confirm_no_existing_holdings is True
    with session_factory() as session:
        handoff = _create(session, advisor_user, confirm_no_existing_holdings=True)
    _assert_parity(preview, handoff)


def test_preview_persists_nothing(session_factory, advisor_user, monkeypatch):
    _seed_mandate_and_run(session_factory, advisor_user)
    _patch(monkeypatch, _payload(_existing_depot_with_new_product()))

    with session_factory() as session:
        _preview(session, advisor_user)
        assert not session.new and not session.dirty and not session.deleted
        session.rollback()
        assert session.query(PortfolioHandoff).count() == 0
        assert session.query(AuditLog).count() == 0


def test_preview_new_money_without_confirmation_names_reason_code(session_factory, advisor_user, monkeypatch):
    _seed_mandate_and_run(session_factory, advisor_user)
    _patch(monkeypatch, _payload(_neugeld()))

    with session_factory() as session:
        with pytest.raises(HTTPException) as exc:
            _preview(session, advisor_user)
    assert exc.value.status_code == 409
    assert exc.value.detail["reason_code"] == "NO_HOLDINGS_CONFIRMATION_REQUIRED"


def test_preview_incomplete_valuation_is_409_with_reason(session_factory, advisor_user, monkeypatch):
    _seed_mandate_and_run(session_factory, advisor_user)
    _patch(monkeypatch, _payload(_existing_depot_with_new_product(), stale_positions_count=1))

    with session_factory() as session:
        with pytest.raises(HTTPException) as exc:
            _preview(session, advisor_user)
    assert exc.value.status_code == 409
    assert exc.value.detail["reason_code"] == "HOLDINGS_VALUATION_INCOMPLETE"


def test_preview_is_available_for_advisory_mandate(session_factory, advisor_user, monkeypatch):
    """Die Handelsliste wird auch bei Anlageberatung angezeigt; nur die
    Weiterleitung selbst ist der Vermoegensverwaltung vorbehalten."""
    _seed_mandate_and_run(session_factory, advisor_user, mandate_type="Anlageberatung")
    _patch(monkeypatch, _payload(_existing_depot_with_new_product()))

    with session_factory() as session:
        preview = _preview(session, advisor_user)
    assert preview.position_count == len(preview.trades) > 0


def test_preview_unknown_mandate_is_404(session_factory, advisor_user, monkeypatch):
    _seed_mandate_and_run(session_factory, advisor_user)
    _patch(monkeypatch, _payload(_existing_depot_with_new_product()))

    with session_factory() as session:
        with pytest.raises(HTTPException) as exc:
            _preview(session, advisor_user, mandate_id="mandate-x")
    assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# HANDOFF-CASH-BASIS-001
# ---------------------------------------------------------------------------


def test_advisory_cash_counts_as_ist_in_recorded_depot_basis(session_factory, advisor_user, monkeypatch):
    _seed_mandate_and_run(session_factory, advisor_user)
    _add_cash(session_factory)
    _patch(monkeypatch, _payload(_existing_depot_with_new_product()))

    with session_factory() as session:
        handoff = _create(session, advisor_user)
        PortfolioHandoffResponse.model_validate(handoff)

    # Basis = Depot CHF 10'000 + Konto CHF 2'000.
    assert handoff.live_total_value_rappen == 1_200_000
    trades = {t["product_id"] or t["wealth_position_id"]: t for t in _rows(handoff)}
    cash = trades["wp-cash"]
    assert cash["holding_origin"] == "advisory_cash"
    assert cash["current_market_value_rappen"] == 200_000
    assert cash["target_amount_rappen"] == 0
    assert cash["rebalance_amount_rappen"] == -200_000
    assert cash["rebalance_action_code"] == "SELL"
    assert trades["C"]["rebalance_amount_rappen"] == trades["C"]["target_amount_rappen"] == 240_000
    for trade in trades.values():
        assert trade["current_market_value_rappen"] + trade["rebalance_amount_rappen"] == trade["target_amount_rappen"]
    assert sum(t["rebalance_amount_rappen"] for t in trades.values()) == 0


def test_advisory_cash_is_included_when_every_product_is_held(session_factory, advisor_user, monkeypatch):
    _seed_mandate_and_run(session_factory, advisor_user)
    _add_cash(session_factory)
    _patch(monkeypatch, _payload([_entry("A", 5000, 500_000, 600_000), _entry("B", 5000, 500_000, 400_000)]))

    with session_factory() as session:
        handoff = _create(session, advisor_user)

    assert handoff.live_total_value_rappen == 1_200_000
    trades = {t["product_id"] or t["wealth_position_id"]: t for t in _rows(handoff)}
    assert trades["wp-cash"]["rebalance_amount_rappen"] == -200_000
    assert sum(t["rebalance_amount_rappen"] for t in trades.values()) == 0


def test_advisory_cash_in_foreign_currency_uses_model_fx_basis(session_factory, advisor_user, monkeypatch):
    _seed_mandate_and_run(session_factory, advisor_user)
    _add_cash(session_factory, currency="EUR", value=100_000)
    _patch(monkeypatch, _payload(_existing_depot_with_new_product()))

    with session_factory() as session:
        expected = int(round(100_000 * FXRateSource.from_db_for_model(session).cross_rate("EUR", "CHF")))
        handoff = _create(session, advisor_user)
    cash = next(t for t in _rows(handoff) if t.get("wealth_position_id") == "wp-cash")
    assert cash["current_market_value_rappen"] == expected
    assert handoff.live_total_value_rappen == 1_000_000 + expected


@pytest.mark.parametrize("variant", ["missing_valuation_date", "missing_currency", "unknown_currency"])
def test_unvalued_advisory_cash_is_fail_closed(session_factory, advisor_user, monkeypatch, variant):
    _seed_mandate_and_run(session_factory, advisor_user)
    if variant == "missing_valuation_date":
        _add_cash(session_factory, valuation_date=None)
    elif variant == "missing_currency":
        _add_cash(session_factory, currency="")
    else:
        _add_cash(session_factory, currency="ZZZ")
    _patch(monkeypatch, _payload(_existing_depot_with_new_product()))

    with session_factory() as session:
        with pytest.raises(HTTPException) as exc:
            _create(session, advisor_user)
        assert exc.value.status_code == 409
        assert "Liquiditaetsposition" in str(exc.value.detail)
        assert session.query(PortfolioHandoff).count() == 0
    with session_factory() as session:
        with pytest.raises(HTTPException) as exc:
            _preview(session, advisor_user)
        assert exc.value.detail["reason_code"] == "HOLDINGS_VALUATION_INCOMPLETE"


def test_cash_outside_advisory_wealth_or_inactive_is_not_counted(session_factory, advisor_user, monkeypatch):
    _seed_mandate_and_run(session_factory, advisor_user)
    _add_cash(session_factory, wp_id="wp-other", assignment="Anderes Vermögen", valuation_date=None)
    _add_cash(session_factory, wp_id="wp-inactive", is_active=0, valuation_date=None)
    _patch(monkeypatch, _payload(_existing_depot_with_new_product()))

    with session_factory() as session:
        handoff = _create(session, advisor_user)
    assert handoff.live_total_value_rappen == 1_000_000
    assert all(t.get("holding_origin") != "advisory_cash" for t in _rows(handoff))


def test_new_money_basis_does_not_add_cash_twice(session_factory, advisor_user, monkeypatch):
    """Bei bestaetigtem Neugeld ist die Liquiditaet bereits im investierbaren
    Beratungsvermoegen enthalten."""
    _seed_mandate_and_run(session_factory, advisor_user)
    _add_cash(session_factory)
    _patch(monkeypatch, _payload(_neugeld(), investable_rappen=1_200_000))

    with session_factory() as session:
        handoff = _create(session, advisor_user, confirm_no_existing_holdings=True)
    assert handoff.live_total_value_rappen == 1_200_000
    assert all(t["holding_origin"] == "not_held" for t in _rows(handoff))


def test_preview_with_advisory_cash_equals_snapshot(session_factory, advisor_user, monkeypatch):
    _seed_mandate_and_run(session_factory, advisor_user)
    _add_cash(session_factory)
    _patch(monkeypatch, _payload(_existing_depot_with_new_product()))

    with session_factory() as session:
        preview = _preview(session, advisor_user)
    with session_factory() as session:
        handoff = _create(session, advisor_user)
    _assert_parity(preview, handoff)


def test_cash_row_carries_no_free_text_label(session_factory, advisor_user, monkeypatch):
    """Red-Team 2026-10-28 Befund 3: der unveraenderliche Snapshot traegt keine
    Freitext-Bezeichnung der Liquiditaetsposition, nur Instrumenttyp + Waehrung."""
    _seed_mandate_and_run(session_factory, advisor_user)
    _add_cash(session_factory)
    _patch(monkeypatch, _payload(_existing_depot_with_new_product()))

    with session_factory() as session:
        handoff = _create(session, advisor_user)

    cash = next(t for t in _rows(handoff) if t.get("wealth_position_id") == "wp-cash")
    assert cash["product_name"] == "Liquiditaet Kontoguthaben CHF"
    assert "Privatkonto" not in handoff.trade_list_snapshot_json
