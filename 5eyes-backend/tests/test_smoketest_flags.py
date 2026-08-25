"""P24 Tests: --json, --strict, --no-validation Flags des Smoketest-CLI.

Verifiziert mit Mock-Aggregator (kein Netzwerk):
- skip_validation=True ueberspringt cross_validate
- report_to_dict produziert JSON-serialisierbares dict
- has_unhealthy_provider erkennt unhealthy
- --json schreibt JSON statt Text
- --strict gibt Exit 1 bei unhealthy provider auch wenn summary_ok
- --no-validation laesst Validations-Liste leer
- --report-file mit .json-Endung schreibt JSON
"""
from __future__ import annotations

import json
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


class _Provider(MarketDataProvider):
    def __init__(self, name, prices, healthy=True):
        self.name = name
        self._prices = prices
        self._h = healthy

    def is_healthy(self):
        return self._h

    def get_eod(self, symbol, on_date):
        if symbol not in self._prices:
            raise SymbolNotFound(symbol)
        p = Decimal(self._prices[symbol])
        return Bar(symbol=symbol, date=on_date, open=p, high=p, low=p, close=p,
                   currency="CHF", source=self.name)

    def get_history(self, symbol, start, end):
        return []

    def lookup_isin(self, isin):
        raise SymbolNotFound(isin)


# ============================================================================
# report_to_dict
# ============================================================================


def test_report_to_dict_serializes_all_sections():
    fake_agg = MarketDataAggregator(providers=[_Provider("p1", {"X": "100"})])
    from services.market_data import factory as f
    with patch.object(f, "build_default_aggregator", return_value=fake_agg):
        rpt = smt.run_smoketest(symbols=["X"], no_network=False)
    d = smt.report_to_dict(rpt)
    assert set(d.keys()) >= {"started_at", "finished_at", "summary_ok",
                              "summary_notes", "providers", "fetches",
                              "validations"}
    # Muss JSON-serialisierbar sein
    json.dumps(d)


def test_report_to_dict_provider_structure():
    fake_agg = MarketDataAggregator(providers=[_Provider("p1", {}, healthy=False)])
    from services.market_data import factory as f
    with patch.object(f, "build_default_aggregator", return_value=fake_agg):
        rpt = smt.run_smoketest(no_network=True)
    d = smt.report_to_dict(rpt)
    assert d["providers"][0]["name"] == "p1"
    assert d["providers"][0]["healthy"] is False


# ============================================================================
# has_unhealthy_provider
# ============================================================================


def test_has_unhealthy_provider_true_when_one_unhealthy():
    fake_agg = MarketDataAggregator(providers=[
        _Provider("p1", {}, healthy=True),
        _Provider("p2", {}, healthy=False),
    ])
    from services.market_data import factory as f
    with patch.object(f, "build_default_aggregator", return_value=fake_agg):
        rpt = smt.run_smoketest(no_network=True)
    assert smt.has_unhealthy_provider(rpt) is True


def test_has_unhealthy_provider_false_when_all_healthy():
    fake_agg = MarketDataAggregator(providers=[
        _Provider("p1", {}, healthy=True),
        _Provider("p2", {}, healthy=True),
    ])
    from services.market_data import factory as f
    with patch.object(f, "build_default_aggregator", return_value=fake_agg):
        rpt = smt.run_smoketest(no_network=True)
    assert smt.has_unhealthy_provider(rpt) is False


# ============================================================================
# skip_validation
# ============================================================================


def test_skip_validation_leaves_validations_empty():
    fake_agg = MarketDataAggregator(providers=[
        _Provider("p1", {"X": "100"}), _Provider("p2", {"X": "101"}),
    ])
    from services.market_data import factory as f
    with patch.object(f, "build_default_aggregator", return_value=fake_agg):
        rpt = smt.run_smoketest(symbols=["X"], no_network=False, skip_validation=True)
    assert rpt.validations == []
    # Fetches sollten trotzdem laufen
    assert len(rpt.fetches) == 1


def test_skip_validation_false_runs_validation():
    fake_agg = MarketDataAggregator(providers=[
        _Provider("p1", {"X": "100"}), _Provider("p2", {"X": "101"}),
    ])
    from services.market_data import factory as f
    with patch.object(f, "build_default_aggregator", return_value=fake_agg):
        rpt = smt.run_smoketest(symbols=["X"], no_network=False, skip_validation=False)
    assert len(rpt.validations) == 1


# ============================================================================
# --json Flag
# ============================================================================


def test_json_flag_outputs_valid_json(capsys):
    fake_agg = MarketDataAggregator(providers=[_Provider("p1", {})])
    from services.market_data import factory as f
    with patch.object(f, "build_default_aggregator", return_value=fake_agg):
        rc = smt.main(["--no-network", "--json"])
    out = capsys.readouterr().out
    # Muss als JSON parsbar sein
    data = json.loads(out)
    assert "summary_ok" in data
    assert "providers" in data


def test_json_flag_does_not_print_text(capsys):
    fake_agg = MarketDataAggregator(providers=[_Provider("p1", {})])
    from services.market_data import factory as f
    with patch.object(f, "build_default_aggregator", return_value=fake_agg):
        smt.main(["--no-network", "--json"])
    out = capsys.readouterr().out
    # Default-Text-Header darf nicht auftauchen
    assert "Smoketest Market Data Pipeline" not in out


# ============================================================================
# --strict Flag
# ============================================================================


def test_strict_returns_1_when_provider_unhealthy_even_if_summary_ok(capsys):
    """Im no-network-Mode mit 1 healthy + 1 unhealthy: summary_ok kann True
    sein, aber --strict erkennt unhealthy."""
    fake_agg = MarketDataAggregator(providers=[
        _Provider("p1", {}, healthy=True),
        _Provider("p2", {}, healthy=False),
    ])
    from services.market_data import factory as f
    with patch.object(f, "build_default_aggregator", return_value=fake_agg):
        rc = smt.main(["--no-network", "--strict"])
    # Mit p1 healthy ist summary_ok=True, aber strict -> 1
    assert rc == 1


def test_strict_returns_0_when_all_healthy():
    fake_agg = MarketDataAggregator(providers=[
        _Provider("p1", {}, healthy=True),
        _Provider("p2", {}, healthy=True),
    ])
    from services.market_data import factory as f
    with patch.object(f, "build_default_aggregator", return_value=fake_agg):
        rc = smt.main(["--no-network", "--strict"])
    assert rc == 0


# ============================================================================
# --no-validation Flag
# ============================================================================


def test_no_validation_flag_via_main(capsys):
    fake_agg = MarketDataAggregator(providers=[
        _Provider("p1", {"X": "100"}), _Provider("p2", {"X": "101"}),
    ])
    from services.market_data import factory as f
    with patch.object(f, "build_default_aggregator", return_value=fake_agg):
        rc = smt.main(["--symbols", "X", "--no-validation", "--json"])
    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["validations"] == []


# ============================================================================
# --report-file mit .json-Endung
# ============================================================================


def test_report_file_json_writes_json(tmp_path):
    out_file = tmp_path / "out.json"
    fake_agg = MarketDataAggregator(providers=[_Provider("p1", {})])
    from services.market_data import factory as f
    with patch.object(f, "build_default_aggregator", return_value=fake_agg):
        smt.main(["--no-network", "--report-file", str(out_file)])
    content = out_file.read_text(encoding="utf-8")
    # Muss als JSON parsbar sein
    data = json.loads(content)
    assert "summary_ok" in data


def test_report_file_md_writes_markdown(tmp_path):
    out_file = tmp_path / "out.md"
    fake_agg = MarketDataAggregator(providers=[_Provider("p1", {})])
    from services.market_data import factory as f
    with patch.object(f, "build_default_aggregator", return_value=fake_agg):
        smt.main(["--no-network", "--report-file", str(out_file)])
    content = out_file.read_text(encoding="utf-8")
    # Markdown enthaelt das #-Heading
    assert "# Smoketest" in content
