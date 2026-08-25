"""P19 Tests: Smoketest-CLI fuer die Market-Data-Pipeline.

Verifiziert mit Mock-Providern (kein Netzwerk):
- check_providers liest healthy-Status korrekt.
- fetch_symbols nutzt Aggregator-Fallback und ueberlebt Exceptions.
- cross_validate sammelt Median + diff_bps + Alert-Flag.
- run_smoketest baut ein SmoketestReport mit allen Sektionen.
- format_report rendert Text und Markdown ohne Crash.
- main() Exit-Codes: 0=OK, 1=fail.
"""
from __future__ import annotations

import sys
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "5eyes-backend"))
sys.path.insert(0, str(ROOT / "scripts"))

import smoketest_market_data as smt
from services.market_data import (
    Bar,
    MarketDataAggregator,
    MarketDataProvider,
    SymbolNotFound,
)


# ============================================================================
# Test-Provider
# ============================================================================


class _ConfigurableProvider(MarketDataProvider):
    def __init__(self, name: str, prices: dict[str, str], healthy: bool = True,
                 raise_on_health: bool = False):
        self.name = name
        self._prices = prices
        self._healthy = healthy
        self._raise = raise_on_health

    def is_healthy(self) -> bool:
        if self._raise:
            raise RuntimeError("health probe failed")
        return self._healthy

    def get_eod(self, symbol, on_date):
        if symbol not in self._prices:
            raise SymbolNotFound(symbol)
        price = Decimal(self._prices[symbol])
        return Bar(
            symbol=symbol, date=on_date,
            open=price, high=price, low=price, close=price,
            currency="CHF", source=self.name,
        )

    def get_history(self, symbol, start, end):
        return []

    def lookup_isin(self, isin):
        raise SymbolNotFound(isin)


# ============================================================================
# check_providers
# ============================================================================


def test_check_providers_marks_healthy_and_unhealthy():
    p1 = _ConfigurableProvider("p1", {}, healthy=True)
    p2 = _ConfigurableProvider("p2", {}, healthy=False)
    agg = MarketDataAggregator(providers=[p1, p2])
    checks = smt.check_providers(agg)
    by_name = {c.name: c for c in checks}
    assert by_name["p1"].healthy is True
    assert by_name["p2"].healthy is False
    assert "is_healthy" in by_name["p2"].notes


def test_check_providers_handles_health_raises():
    p = _ConfigurableProvider("buggy", {}, raise_on_health=True)
    agg = MarketDataAggregator(providers=[p])
    checks = smt.check_providers(agg)
    assert checks[0].healthy is False
    assert "RuntimeError" in checks[0].notes


# ============================================================================
# fetch_symbols
# ============================================================================


def test_fetch_symbols_returns_resolved_for_known_symbol():
    p = _ConfigurableProvider("p1", {"UBSG.SW": "28.75"})
    agg = MarketDataAggregator(providers=[p])
    results = smt.fetch_symbols(agg, ["UBSG.SW"], date(2026, 5, 13))
    assert len(results) == 1
    assert results[0].price == "28.75"
    assert results[0].provider == "p1"
    assert results[0].error is None


def test_fetch_symbols_handles_unknown_symbol():
    p = _ConfigurableProvider("p1", {})
    agg = MarketDataAggregator(providers=[p])
    results = smt.fetch_symbols(agg, ["UNKNOWN"], date(2026, 5, 13))
    assert results[0].price is None
    assert "SymbolNotFound" in (results[0].error or "")


def test_fetch_symbols_uses_aggregator_fallback():
    """Erster Provider failt, zweiter liefert -> Fallback greift."""
    p1 = _ConfigurableProvider("primary", {})  # leer -> SymbolNotFound
    p2 = _ConfigurableProvider("backup", {"UBSG.SW": "28.50"})
    agg = MarketDataAggregator(providers=[p1, p2])
    results = smt.fetch_symbols(agg, ["UBSG.SW"], date(2026, 5, 13))
    assert results[0].price == "28.50"
    assert results[0].provider == "backup"


# ============================================================================
# cross_validate
# ============================================================================


def test_cross_validate_returns_median_when_providers_agree():
    p1 = _ConfigurableProvider("p1", {"UBSG.SW": "28.00"})
    p2 = _ConfigurableProvider("p2", {"UBSG.SW": "28.10"})
    agg = MarketDataAggregator(providers=[p1, p2])
    results = smt.cross_validate(agg, ["UBSG.SW"], date(2026, 5, 13))
    assert results[0].n_providers == 2
    assert results[0].is_alert is False
    assert results[0].median != ""


def test_cross_validate_alerts_when_providers_diverge():
    p1 = _ConfigurableProvider("p1", {"UBSG.SW": "28.00"})
    p2 = _ConfigurableProvider("p2", {"UBSG.SW": "32.00"})  # +14% Diff
    agg = MarketDataAggregator(providers=[p1, p2])
    results = smt.cross_validate(agg, ["UBSG.SW"], date(2026, 5, 13), threshold_bps=300)
    assert results[0].is_alert is True
    assert results[0].diff_bps > 300


def test_cross_validate_insufficient_data_when_only_one_provider():
    p1 = _ConfigurableProvider("p1", {"UBSG.SW": "28.00"})
    agg = MarketDataAggregator(providers=[p1])
    results = smt.cross_validate(agg, ["UBSG.SW"], date(2026, 5, 13))
    assert results[0].note == "insufficient_data"


# ============================================================================
# run_smoketest (Integration)
# ============================================================================


def test_run_smoketest_no_network_skips_fetches():
    fake_agg = MarketDataAggregator(providers=[
        _ConfigurableProvider("p1", {}, healthy=True),
    ])
    with patch.object(smt, "build_default_aggregator", create=True):
        from services.market_data import factory as f
        with patch.object(f, "build_default_aggregator", return_value=fake_agg):
            rpt = smt.run_smoketest(no_network=True, symbols=["UBSG.SW"])
    assert rpt.fetches == []
    assert rpt.validations == []
    assert rpt.providers and rpt.providers[0].name == "p1"


def test_run_smoketest_aggregator_construct_failure():
    """Wenn build_default_aggregator crasht, summary_ok=False."""
    from services.market_data import factory as f
    with patch.object(f, "build_default_aggregator", side_effect=RuntimeError("boom")):
        rpt = smt.run_smoketest(no_network=True)
    assert rpt.summary_ok is False
    assert any("build_default_aggregator failed" in n for n in rpt.summary_notes)


def test_run_smoketest_no_healthy_providers_fails():
    fake_agg = MarketDataAggregator(providers=[
        _ConfigurableProvider("p1", {}, healthy=False),
    ])
    from services.market_data import factory as f
    with patch.object(f, "build_default_aggregator", return_value=fake_agg):
        rpt = smt.run_smoketest(no_network=True)
    assert rpt.summary_ok is False
    assert any("Kein Provider" in n for n in rpt.summary_notes)


def test_run_smoketest_all_fetches_fail_marks_summary_fail():
    fake_agg = MarketDataAggregator(providers=[
        _ConfigurableProvider("p1", {}, healthy=True),  # liefert SymbolNotFound
    ])
    from services.market_data import factory as f
    with patch.object(f, "build_default_aggregator", return_value=fake_agg):
        rpt = smt.run_smoketest(no_network=False, symbols=["AAPL"])
    assert rpt.summary_ok is False
    assert any("abgerufen werden" in n for n in rpt.summary_notes)


# ============================================================================
# format_report
# ============================================================================


def test_format_report_text_contains_all_sections():
    rpt = smt.run_smoketest(no_network=True)  # builds default agg live
    text = smt.format_report(rpt, markdown=False)
    assert "Smoketest Market Data Pipeline" in text
    assert "Provider" in text
    assert "Preisabruf" in text
    assert "Cross-Validation" in text


def test_format_report_markdown_uses_headings():
    rpt = smt.run_smoketest(no_network=True)
    text = smt.format_report(rpt, markdown=True)
    assert "# Smoketest" in text
    assert "## Provider" in text


# ============================================================================
# main() — Exit-Codes
# ============================================================================


def test_main_returns_0_when_all_ok(capsys):
    fake_agg = MarketDataAggregator(providers=[
        _ConfigurableProvider("p1", {"AAPL": "100"}, healthy=True),
        _ConfigurableProvider("p2", {"AAPL": "100.5"}, healthy=True),
    ])
    from services.market_data import factory as f
    with patch.object(f, "build_default_aggregator", return_value=fake_agg):
        rc = smt.main(["--symbols", "AAPL"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "AAPL" in out


def test_main_returns_1_on_failure(capsys):
    from services.market_data import factory as f
    with patch.object(f, "build_default_aggregator",
                       side_effect=RuntimeError("boom")):
        rc = smt.main(["--no-network"])
    assert rc == 1
