"""2026-07-27 (WealthPosition-FX-Fix): current_value_rappen floss bisher OHNE
FX-Konvertierung nach pos.currency direkt in die SAA-/MC-Basis-Aggregation
(_summarize_positions) ein -- eine USD-Position wurde faktisch als CHF-Betrag
behandelt. Fix: 1:1 nach dem Vorbild des bereits produktiv laufenden
Cashflow-FX-Pfads (services.cashflow_timeline._convert_cf_amount_to_target_currency).

Reine Pure-Function-Unit-Tests, keine DB noetig (WealthPosition-Instanzen
werden nicht committet, nur als Python-Objekte konstruiert).
"""
from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from main import app  # noqa: F401  -- registriert alle Modelle (FK/Relationship-Aufloesung)
from models.wealth import WealthPosition
from services.currency.fx_rates import DEFAULT_FX_RATES, FXRateSource
from services.portfolio_engine import (
    _convert_position_amount_to_target_currency,
    _summarize_positions,
)


def _position(**overrides) -> WealthPosition:
    base = dict(
        position_type="Liquiditaet", assignment="Beratungsvermögen",
        current_value_rappen=100_000, currency="CHF",
    )
    base.update(overrides)
    return WealthPosition(**base)


# ── _convert_position_amount_to_target_currency ─────────────────────────────

def test_backwards_compat_no_fx_source_returns_raw_amount():
    """fx_source=None -- alte Behavior, Waehrung wird komplett ignoriert."""
    pos = _position(current_value_rappen=100_000, currency="USD")
    assert _convert_position_amount_to_target_currency(pos, None, "CHF") == 100_000


def test_same_currency_as_target_returns_raw_amount():
    pos = _position(current_value_rappen=100_000, currency="CHF")
    fx = FXRateSource()
    assert _convert_position_amount_to_target_currency(pos, fx, "CHF") == 100_000


def test_usd_position_converted_to_chf():
    pos = _position(current_value_rappen=100_000, currency="USD")
    fx = FXRateSource()
    usd_rate = DEFAULT_FX_RATES["USD"]
    expected = round(100_000 * usd_rate)
    assert _convert_position_amount_to_target_currency(pos, fx, "CHF") == expected
    assert expected != 100_000  # Sicherstellen dass der Test ueberhaupt etwas prueft


def test_zero_amount_short_circuits():
    pos = _position(current_value_rappen=0, currency="USD")
    fx = FXRateSource()
    assert _convert_position_amount_to_target_currency(pos, fx, "CHF") == 0


def test_unknown_currency_falls_back_to_raw_amount():
    pos = _position(current_value_rappen=100_000, currency="XXX")
    fx = FXRateSource()
    assert _convert_position_amount_to_target_currency(pos, fx, "CHF") == 100_000


def test_missing_currency_defaults_to_chf():
    pos = _position(current_value_rappen=100_000, currency=None)
    fx = FXRateSource()
    assert _convert_position_amount_to_target_currency(pos, fx, "CHF") == 100_000


# ── _summarize_positions ────────────────────────────────────────────────────

def test_summarize_positions_backwards_compat_default_no_fx():
    """Ohne fx_source/target_currency-Argumente (Default) bleibt das
    Verhalten fuer reine CHF-Portfolios exakt unveraendert."""
    positions = [_position(current_value_rappen=100_000, currency="CHF")]
    summary = _summarize_positions(positions)
    assert summary.total_rappen == 100_000


def test_summarize_positions_converts_foreign_currency():
    fx = FXRateSource()
    usd_rate = DEFAULT_FX_RATES["USD"]
    positions = [
        _position(current_value_rappen=100_000, currency="CHF"),
        _position(current_value_rappen=100_000, currency="USD"),
    ]
    summary = _summarize_positions(positions, fx_source=fx, target_currency="CHF")
    expected = 100_000 + round(100_000 * usd_rate)
    assert summary.total_rappen == expected


def test_summarize_positions_mixed_currencies_with_chf_target_matches_manual_sum():
    fx = FXRateSource()
    eur_rate = DEFAULT_FX_RATES["EUR"]
    gbp_rate = DEFAULT_FX_RATES["GBP"]
    positions = [
        _position(current_value_rappen=200_000, currency="EUR"),
        _position(current_value_rappen=300_000, currency="GBP"),
    ]
    summary = _summarize_positions(positions, fx_source=fx, target_currency="CHF")
    expected = round(200_000 * eur_rate) + round(300_000 * gbp_rate)
    assert summary.total_rappen == expected


def test_summarize_positions_non_chf_target_currency():
    """Mandate.base_currency muss nicht CHF sein -- cross_rate ist bereits
    waehrungsagnostisch (siehe FXRateSource.cross_rate)."""
    fx = FXRateSource()
    positions = [_position(current_value_rappen=100_000, currency="CHF")]
    summary = _summarize_positions(positions, fx_source=fx, target_currency="USD")
    chf_rate = DEFAULT_FX_RATES["CHF"]
    usd_rate = DEFAULT_FX_RATES["USD"]
    expected = round(100_000 * (chf_rate / usd_rate))
    assert summary.total_rappen == expected
