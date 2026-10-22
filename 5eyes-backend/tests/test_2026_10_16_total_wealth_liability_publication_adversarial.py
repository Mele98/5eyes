r"""Residual TOTAL-WEALTH-LIABILITY-001 cross-consumer publication contract."""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest


# Produktwurzel = dieses Repo (tests/ -> 5eyes-backend/ -> Repo-Wurzel); die
# Umgebungsvariable bleibt als Override fuer externe Pruefungen erhalten. Kein
# fest verdrahteter App-Ordner mehr (las sonst still einen fremden Checkout).
PRODUCT_ROOT = Path(
    os.environ.get("FIVEEYES_PRODUCT_ROOT") or Path(__file__).resolve().parents[2]
).resolve()
HTML_PATH = PRODUCT_ROOT / "5eyes-electron" / "frontend" / "5eyes_v2.html"
if not HTML_PATH.is_file():
    pytest.skip("5eyes_v2.html nicht gefunden", allow_module_level=True)


def _extract_js_function(source: str, name: str) -> str:
    marker = f"function {name}("
    start = source.index(marker)
    brace = source.index("{", start)
    depth = 0
    quote: str | None = None
    escaped = False
    for idx in range(brace, len(source)):
        char = source[idx]
        if quote is not None:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            continue
        if char in ("'", '"', "`"):
            quote = char
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[start : idx + 1]
    raise AssertionError(f"unterminated JavaScript function {name}")


def test_total_wealth_projection_subtracts_non_mortgage_liabilities(tmp_path: Path) -> None:
    """The visible total projection must start from the same net wealth.

    Assets are CHF 900k, mortgage CHF 300k and consumer loan CHF 200k.  The
    canonical net basis is CHF 400k.  The current browser helper only sends
    mortgages through its liability series, so it starts at CHF 600k.
    """
    html = HTML_PATH.read_text(encoding="utf-8")
    mortgage_helper = _extract_js_function(
        html, "mortgageLiabilityAndPledgedSeriesRappen"
    )
    projection_helper = _extract_js_function(html, "wealthProjectionInputs")
    script = f"""
const assets = [
  {{position_type:'Depot', assignment:'Beratungsvermögen', current_value_rappen:10000000}},
  {{position_type:'Immobilien', assignment:'Anderes Vermögen', current_value_rappen:80000000,
    asset_expected_return_bps:0}}
];
const liabilities = [
  {{position_type:'Hypothek', assignment:'Verbindlichkeit', current_value_rappen:30000000}},
  {{position_type:'Custom', assignment:'Verbindlichkeit', current_value_rappen:20000000}}
];
const strategyState = {{allocation:{{asset_class_assumptions:[]}}}};
const ADMIN_CMA_DEFAULTS = {{equity_intl_return_bps:690,bonds_fx_hedged_return_bps:220,
  real_estate_ch_return_bps:450,alternatives_gold_return_bps:300}};
// Harness-Stubs (A13): seit VORSORGE-PROJECTION-001 ruft wealthProjectionInputs
// diese Helfer auf; keine Vorsorgeposition im Szenario.
function isExternalPensionPosition(pos) {{ return false; }}
function pensionProjectionRateBps(pos) {{ return null; }}
function wealthScopePositions(scope) {{ return assets; }}
function activeClientWealthPositions() {{ return assets.concat(liabilities); }}
function activeClientCashflowSummary() {{ return {{}}; }}
function summaryRecurringNetCashflowRappen() {{ return 0; }}
function summaryCapitalNetCashflowRappen() {{ return 0; }}
function summaryTotalNetCashflowRappen() {{ return 0; }}
function inferPositionBucketMixBps(pos) {{
  if (pos.position_type === 'Immobilien') return {{equities:0,bonds:0,realEstate:10000,liquidity:0,alternatives:0}};
  return {{equities:10000,bonds:0,realEstate:0,liquidity:0,alternatives:0}};
}}
{mortgage_helper}
{projection_helper}
process.stdout.write(JSON.stringify(wealthProjectionInputs('total', 2)));
"""
    script_path = tmp_path / "total_wealth_projection_contract.mjs"
    script_path.write_text(script, encoding="utf-8")
    completed = subprocess.run(
        ["node", str(script_path)],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    result = json.loads(completed.stdout)
    assert result["grossRappen"] == 90_000_000
    assert result["startRappen"] == 40_000_000, result


def test_classic_context_uses_net_foundation_and_surfaces_uncovered_debt() -> None:
    """Classic UI must not claim a foundation larger than net wealth."""
    html = HTML_PATH.read_text(encoding="utf-8")
    block = html.split(
        "function syncAllocationDonutFromStrategyState()", 1
    )[1].split("\nlet charts=", 1)[0]

    assert "foundation_in_net_wealth_rappen" in block, block
    assert "net_wealth_non_positive" in block, block
    assert "uncovered_liabilities_rappen" in block, block
    assert "foundation_rappen||0" not in block, block
