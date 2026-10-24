"""P14: Test fuer price_updater.py-Migration auf den Multi-Source-Aggregator.

Verifiziert:
- `_fetch_aggregator_symbol_points()` ruft `fetch_latest_prices_via_aggregator`
  und konvertiert das Output in das interne `(price_date, price_rappen, source)`-
  Tripel-Format.
- Provider-Routing: primary_provider="aggregator" und
  fallback_provider="aggregator" beide implementiert.
- Fehler im Aggregator-Layer werden als symbol_errors zurueckgegeben.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import price_updater


# ============================================================================
# _fetch_aggregator_symbol_points
# ============================================================================


def test_aggregator_symbol_points_maps_resolved_to_tuples():
    fake_resolved = {
        "UBSG.SW": {"price_date": "2026-05-08", "price_rappen": 2875, "source": "yfinance"},
        "AAPL": {"price_date": "2026-05-08", "price_rappen": 25010, "source": "stooq"},
    }
    fake_failures: dict[str, str] = {}
    with patch.object(
        price_updater, "fetch_latest_prices_via_aggregator",
        return_value=(fake_resolved, fake_failures),
    ):
        points, errors = price_updater._fetch_aggregator_symbol_points(["UBSG.SW", "AAPL"])
    assert points == {
        "UBSG.SW": ("2026-05-08", 2875, "yfinance"),
        "AAPL": ("2026-05-08", 25010, "stooq"),
    }
    assert errors == {}


def test_aggregator_symbol_points_passes_failures_through():
    with patch.object(
        price_updater, "fetch_latest_prices_via_aggregator",
        return_value=({}, {"XX": "symbol-not-found: XX"}),
    ):
        points, errors = price_updater._fetch_aggregator_symbol_points(["XX"])
    assert points == {}
    assert errors == {"XX": "symbol-not-found: XX"}


def test_aggregator_symbol_points_handles_aggregator_crash():
    """Wenn fetch_latest_prices_via_aggregator selbst eine Exception wirft,
    werden alle Symbole als Fehler zurueckgegeben — kein Crash."""
    with patch.object(
        price_updater, "fetch_latest_prices_via_aggregator",
        side_effect=RuntimeError("aggregator init failed"),
    ):
        points, errors = price_updater._fetch_aggregator_symbol_points(["A", "B"])
    assert points == {}
    assert set(errors.keys()) == {"A", "B"}
    assert "aggregator init failed" in errors["A"]


def test_aggregator_symbol_points_empty_source_falls_back_to_aggregator_label():
    """Wenn die source leer ist, sollte 'aggregator' als Label gesetzt werden."""
    with patch.object(
        price_updater, "fetch_latest_prices_via_aggregator",
        return_value=({"X": {"price_date": "2026-05-08", "price_rappen": 100, "source": ""}}, {}),
    ):
        points, _ = price_updater._fetch_aggregator_symbol_points(["X"])
    assert points["X"][2] == "aggregator"


# ============================================================================
# Provider-Routing: PRICE_SOURCE / FALLBACK_PRICE_SOURCE = "aggregator"
# ============================================================================


def test_primary_provider_aggregator_routes_to_aggregator(monkeypatch):
    monkeypatch.setattr(price_updater, "PRICE_SOURCE", "aggregator")
    captured = {}
    def fake_agg(symbols):
        captured["symbols"] = list(symbols)
        return {"UBSG.SW": ("2026-05-08", 2875, "yfinance")}, {}
    monkeypatch.setattr(price_updater, "_fetch_aggregator_symbol_points", fake_agg)
    points, errors = price_updater._fetch_primary_symbol_points(
        ["UBSG.SW"], product_by_symbol={"UBSG.SW": []},
    )
    assert captured["symbols"] == ["UBSG.SW"]
    assert points["UBSG.SW"] == ("2026-05-08", 2875, "yfinance")
    assert errors == {}


def test_fallback_provider_aggregator_routes_to_aggregator(monkeypatch):
    """Fallback-Provider = 'aggregator' (primary ist anderes) muss
    den Aggregator-Pfad waehlen."""
    monkeypatch.setattr(price_updater, "PRICE_SOURCE", "yfinance")
    monkeypatch.setattr(price_updater, "FALLBACK_PRICE_SOURCE", "aggregator")
    captured = {}
    def fake_agg(symbols):
        captured["symbols"] = list(symbols)
        return {"AAPL": ("2026-05-07", 25010, "stooq")}, {}
    monkeypatch.setattr(price_updater, "_fetch_aggregator_symbol_points", fake_agg)
    points, _ = price_updater._fetch_fallback_symbol_points(
        ["AAPL"], product_by_symbol={"AAPL": []},
    )
    assert captured["symbols"] == ["AAPL"]
    assert points["AAPL"] == ("2026-05-07", 25010, "stooq")


def test_fallback_aggregator_skipped_if_same_as_primary(monkeypatch):
    """Wenn primary == fallback == 'aggregator', laeuft Fallback NICHT
    (waere doppelte Anfrage). Existierendes Verhalten wird beibehalten."""
    monkeypatch.setattr(price_updater, "PRICE_SOURCE", "aggregator")
    monkeypatch.setattr(price_updater, "FALLBACK_PRICE_SOURCE", "aggregator")
    points, errors = price_updater._fetch_fallback_symbol_points(
        ["X"], product_by_symbol={"X": []},
    )
    assert points == {}
    assert errors == {}


def test_unknown_provider_returns_friendly_error(monkeypatch):
    monkeypatch.setattr(price_updater, "PRICE_SOURCE", "nonexistent")
    points, errors = price_updater._fetch_primary_symbol_points(
        ["X"], product_by_symbol={"X": []},
    )
    assert points == {}
    assert "nicht implementiert" in errors["X"]
