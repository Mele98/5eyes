"""MD-05 (Audit 2026-06-24): fetch_latest_price schlief bei jedem Retry mit der
UNVERAENDERTEN Basis-Delay-Dauer (time.sleep(retry_delay_seconds)) -- kein
exponentielles Backoff, kein Jitter. Bei einem Rate-Limit/temporaerem Ausfall
klopft der naechste Versuch im selben Takt wieder an, und mehrere parallele
Retries (z.B. mehrere Prozesse/Batches) sind synchron (Thundering-Herd).

Fix (2026-07-23): _retry_backoff_seconds(attempt, base_delay) verdoppelt den
Delay pro Versuch + addiert Jitter (0..50% der Basis). fetch_latest_price
nutzt das jetzt statt des fixen Sleeps.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest import mock

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from main import app  # noqa: E402,F401  (registriert alle Models fuer FK-Aufloesung)
from price_updater import _retry_backoff_seconds  # noqa: E402


def test_backoff_grows_exponentially_without_jitter(monkeypatch):
    # Jitter deterministisch auf 0 setzen, um reinen Exponential-Anteil zu prüfen.
    monkeypatch.setattr("price_updater.random.uniform", lambda a, b: 0.0)
    assert _retry_backoff_seconds(1, 1.0) == pytest.approx(1.0)
    assert _retry_backoff_seconds(2, 1.0) == pytest.approx(2.0)
    assert _retry_backoff_seconds(3, 1.0) == pytest.approx(4.0)


def test_jitter_is_bounded_by_half_base_delay():
    for attempt in (1, 2, 3):
        delay = _retry_backoff_seconds(attempt, 1.0)
        backoff = 1.0 * (2 ** (attempt - 1))
        assert backoff <= delay <= backoff + 0.5 + 1e-9


def test_zero_base_delay_returns_zero():
    assert _retry_backoff_seconds(1, 0.0) == 0.0
    assert _retry_backoff_seconds(5, 0.0) == 0.0


def test_negative_base_delay_is_floored_to_zero():
    assert _retry_backoff_seconds(1, -3.0) == 0.0


def test_fetch_latest_price_uses_growing_backoff_between_retries(monkeypatch):
    """End-to-End: bei einem Fehl-Versuch wird zwischen Attempt 1 und 2 ein von
    _retry_backoff_seconds berechneter (nicht der rohe fixe) Delay geschlafen."""
    import price_updater as pu
    from models.review import Product

    monkeypatch.setattr(pu.settings, "price_refresh_max_attempts", 2, raising=False)
    monkeypatch.setattr(pu.settings, "price_refresh_retry_delay_seconds", 2.0, raising=False)

    sleep_calls: list[float] = []
    monkeypatch.setattr(pu.time, "sleep", lambda s: sleep_calls.append(s))

    class _FakeTicker:
        def __init__(self, symbol):
            pass

        def history(self, **kwargs):
            raise RuntimeError("simulated transient provider failure")

    if pu.yf is not None:
        monkeypatch.setattr(pu.yf, "Ticker", _FakeTicker)
    else:
        pytest.skip("yfinance (yf) nicht installiert -- Fetch-Pfad nicht testbar")

    product = Product(
        id="p-md05", symbol="TEST", isin="CH0000000099",
        product_name="Test", provider="Test", product_type="ETF",
        asset_class="Equities", currency="CHF", is_active=1,
    )
    with mock.patch.object(pu, "resolve_market_profile", return_value={
        "lookup_mode": "direct_symbol",
        "lookup_symbol": "TEST",
    }):
        with pytest.raises(RuntimeError):
            pu.fetch_latest_price(product)

    assert len(sleep_calls) == 1  # max_attempts=2 -> genau 1 Retry-Sleep
    # Erster (und einziger) Retry-Sleep = Basis-Delay (2^0) + Jitter in [0, 1.0).
    assert 2.0 <= sleep_calls[0] < 3.0
