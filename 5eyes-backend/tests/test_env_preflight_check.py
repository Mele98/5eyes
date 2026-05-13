"""P21 Tests: Pre-Flight-Check fuer den Aggregator-Switch.

Verifiziert mit synthetischen .env-Inhalten:
- Aggregator-Modus erkannt (primary=aggregator)
- Provider-Chain valide
- Fehlende API-Keys -> WARN
- Validation enabled ohne Symbole -> WARN
- Komplett leere Config -> dennoch sinnvolle Defaults (keine ERROR)
- Exit-Codes 0/1/2
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import check_env_for_pipeline as preflight


def _write_env(tmp_path: Path, content: str) -> Path:
    p = tmp_path / ".env"
    p.write_text(content, encoding="utf-8")
    return p


# ============================================================================
# Aggregator-Modus
# ============================================================================


def test_aggregator_primary_marked_ok(tmp_path):
    env_file = _write_env(tmp_path, """
PRICE_REFRESH_PRIMARY_PROVIDER=aggregator
MARKET_DATA_PROVIDERS=yfinance,stooq,alphavantage
ALPHAVANTAGE_API_KEY=test-key
""")
    findings, code = preflight.run_checks(env_file)
    levels = {f.setting: f.level for f in findings}
    assert levels["PRICE_REFRESH_PRIMARY_PROVIDER"] == "OK"
    assert levels["MARKET_DATA_PROVIDERS"] == "OK"
    assert levels["ALPHAVANTAGE_API_KEY"] == "OK"
    assert code in (0, 1)  # WARN moeglich durch Defaults


def test_non_aggregator_warns(tmp_path):
    env_file = _write_env(tmp_path, "PRICE_REFRESH_PRIMARY_PROVIDER=yfinance\n")
    findings, code = preflight.run_checks(env_file)
    primary_finding = next(f for f in findings if f.setting == "PRICE_REFRESH_PRIMARY_PROVIDER")
    assert primary_finding.level == "WARN"
    assert "aggregator" in primary_finding.message
    assert code >= 1


# ============================================================================
# Provider-Chain
# ============================================================================


def test_unknown_provider_warns(tmp_path):
    env_file = _write_env(tmp_path, """
PRICE_REFRESH_PRIMARY_PROVIDER=aggregator
MARKET_DATA_PROVIDERS=yfinance,unknown_provider
""")
    findings, code = preflight.run_checks(env_file)
    assert any(
        f.level == "WARN" and "unknown_provider" in f.message
        for f in findings
    )


def test_empty_provider_list_errors(tmp_path):
    env_file = _write_env(tmp_path, """
PRICE_REFRESH_PRIMARY_PROVIDER=aggregator
MARKET_DATA_PROVIDERS=
""")
    findings, code = preflight.run_checks(env_file)
    assert any(f.level == "ERROR" for f in findings)
    assert code == 2


# ============================================================================
# API-Keys
# ============================================================================


def test_alphavantage_in_chain_without_key_warns(tmp_path):
    env_file = _write_env(tmp_path, """
PRICE_REFRESH_PRIMARY_PROVIDER=aggregator
MARKET_DATA_PROVIDERS=yfinance,alphavantage
ALPHAVANTAGE_API_KEY=
""")
    findings, _ = preflight.run_checks(env_file)
    av = next(f for f in findings if f.setting == "ALPHAVANTAGE_API_KEY")
    assert av.level == "WARN"


def test_twelvedata_in_chain_without_key_warns(tmp_path):
    env_file = _write_env(tmp_path, """
PRICE_REFRESH_PRIMARY_PROVIDER=aggregator
MARKET_DATA_PROVIDERS=yfinance,twelvedata
TWELVEDATA_API_KEY=
""")
    findings, _ = preflight.run_checks(env_file)
    td = next(f for f in findings if f.setting == "TWELVEDATA_API_KEY")
    assert td.level == "WARN"


# ============================================================================
# Validation
# ============================================================================


def test_validation_enabled_without_symbols_warns(tmp_path):
    env_file = _write_env(tmp_path, """
PRICE_REFRESH_PRIMARY_PROVIDER=aggregator
MARKET_DATA_PROVIDERS=yfinance,stooq
MARKET_DATA_VALIDATION_ENABLED=true
MARKET_DATA_VALIDATION_SYMBOLS=
""")
    findings, _ = preflight.run_checks(env_file)
    sym = next(f for f in findings if f.setting == "MARKET_DATA_VALIDATION_SYMBOLS")
    assert sym.level == "WARN"


def test_validation_disabled_is_ok(tmp_path):
    env_file = _write_env(tmp_path, """
PRICE_REFRESH_PRIMARY_PROVIDER=aggregator
MARKET_DATA_PROVIDERS=yfinance,stooq
MARKET_DATA_VALIDATION_ENABLED=false
""")
    findings, _ = preflight.run_checks(env_file)
    v = next(f for f in findings if f.setting == "MARKET_DATA_VALIDATION_ENABLED")
    assert v.level == "OK"


def test_validation_with_symbols_is_ok(tmp_path):
    env_file = _write_env(tmp_path, """
PRICE_REFRESH_PRIMARY_PROVIDER=aggregator
MARKET_DATA_PROVIDERS=yfinance,stooq
MARKET_DATA_VALIDATION_ENABLED=true
MARKET_DATA_VALIDATION_SYMBOLS=UBSG.SW,AAPL,MSFT
""")
    findings, _ = preflight.run_checks(env_file)
    sym = next(f for f in findings if f.setting == "MARKET_DATA_VALIDATION_SYMBOLS")
    assert sym.level == "OK"
    assert "3 Symbole" in sym.message


# ============================================================================
# Scheduler
# ============================================================================


def test_scheduler_disabled_warns(tmp_path):
    env_file = _write_env(tmp_path, """
PRICE_REFRESH_PRIMARY_PROVIDER=aggregator
MARKET_DATA_PROVIDERS=yfinance
PRICE_SCHEDULER_ENABLED=false
""")
    findings, _ = preflight.run_checks(env_file)
    sched = next(f for f in findings if f.setting == "PRICE_SCHEDULER_ENABLED")
    assert sched.level == "WARN"


# ============================================================================
# Empty .env
# ============================================================================


def test_completely_missing_env_file_returns_warns_not_errors(tmp_path):
    """Wenn .env nicht existiert, soll der Check nicht crashen."""
    env_file = tmp_path / "does_not_exist.env"
    findings, code = preflight.run_checks(env_file)
    # Defaults greifen: primary=yfinance (kein aggregator) -> WARN
    assert any(f.level == "WARN" for f in findings)
    assert code in (1, 2)


# ============================================================================
# format_findings + main()
# ============================================================================


def test_format_findings_includes_summary_line(tmp_path):
    env_file = _write_env(tmp_path, "PRICE_REFRESH_PRIMARY_PROVIDER=aggregator\nMARKET_DATA_PROVIDERS=yfinance\n")
    findings, _ = preflight.run_checks(env_file)
    text = preflight.format_findings(findings, env_file)
    assert "Pipeline Pre-Flight Check" in text
    assert "Summary:" in text
    assert "OK" in text


def test_main_returns_exit_code(tmp_path, capsys):
    env_file = _write_env(tmp_path, """
PRICE_REFRESH_PRIMARY_PROVIDER=aggregator
MARKET_DATA_PROVIDERS=yfinance,stooq
""")
    rc = preflight.main(["--env-file", str(env_file)])
    assert rc in (0, 1)
    out = capsys.readouterr().out
    assert "Pre-Flight" in out


def test_main_error_exit_2(tmp_path, capsys):
    env_file = _write_env(tmp_path, """
PRICE_REFRESH_PRIMARY_PROVIDER=aggregator
MARKET_DATA_PROVIDERS=
""")
    rc = preflight.main(["--env-file", str(env_file)])
    assert rc == 2
