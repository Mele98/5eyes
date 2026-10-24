"""TOTAL-WEALTH-LIABILITY-001 -- snapshot parity of browser, backend and report.

PR #674 fixed the visible t0 total, but the browser rebuilt the liability
composition and the currency basis from raw live positions:

* every liability was charged against the property floor, whereas the
  backend cascade charges other debt to the financial buckets first and the
  foundation last (``portfolio_engine_gesamtvermoegen._build_total_wealth_allocation``);
* raw ``current_value_rappen`` were summed regardless of ``currency``, and the
  FX-normalized ``total_allocation.total_base_rappen`` was ignored.

Contracts here:

1. With a backend snapshot the browser projection starts on
   ``total_base_rappen`` and uses ``foundation_in_net_wealth_rappen`` as floor
   (audit reproducer of the PR #674 closure review, adopted without xfail).
2. Year 1: financial wealth already consumed by debt earns no return.
3. The backend publishes a hashed, FX-normalized ``projection_basis``; the
   browser takes its year series (only their deltas move the floor).
4. Without a snapshot the browser marks its numbers as ``local_preview``.
5. The report wealth summary (React "Ausgangslage" + advisory PDF) uses the
   same FX conversion as the engine snapshot.
"""
from __future__ import annotations

import json
import re
import subprocess
import uuid
from pathlib import Path

from services.portfolio_engine import PortfolioSummary
from services.portfolio_engine_gesamtvermoegen import (
    PROJECTION_BASIS_SCHEMA,
    _build_total_wealth_allocation,
)

_BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _monolith_path() -> Path:
    """Locate the desktop monolith by structure (a frontend HTML that defines the projection)."""
    repo_root = _BACKEND_ROOT.parent
    for candidate in sorted(repo_root.glob("*/frontend/*.html")):
        try:
            text = candidate.read_text(encoding="utf-8")
        except OSError:
            continue
        if "function wealthProjectionInputs(" in text and "function mortgageLiabilityAndPledgedSeriesRappen(" in text:
            return candidate
    raise AssertionError(f"monolith with wealthProjectionInputs not found below {repo_root}")


HTML_PATH = _monolith_path()


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


def _run_projection(
    tmp_path: Path,
    *,
    snapshot: dict | None,
    other_debt: dict,
    years: int = 2,
    with_baseline: bool = False,
) -> dict:
    html = HTML_PATH.read_text(encoding="utf-8")
    helpers = [
        _extract_js_function(html, "mortgageLiabilityAndPledgedSeriesRappen"),
        _extract_js_function(html, "wealthProjectionInputs"),
    ]
    if with_baseline:
        helpers.append(_extract_js_function(html, "buildBaselineProjectionFromComponentSeries"))
    allocation = (
        "null"
        if snapshot is None
        else "{asset_class_assumptions:[],total_allocation:" + json.dumps(snapshot, ensure_ascii=False) + "}"
    )
    tail = (
        "var rows=[];for(var i=0;i<"
        + str(years)
        + ";i++)rows.push({recurringNetRappen:0,capitalNetRappen:0,netCashflowRappen:0});\n"
        "var proj=buildBaselineProjectionFromComponentSeries(inputs.startRappen,rows,inputs.expectedReturnBps,null,{\n"
        "  sockelRappen:inputs.sockelRappen,sockelGrossRappen:inputs.sockelGrossRappen,\n"
        "  mortgageLiabilityYearSeriesRappen:inputs.mortgageLiabilityYearSeriesRappen,\n"
        "  mortgagePledgedYearSeriesRappen:inputs.mortgagePledgedYearSeriesRappen,\n"
        "  sockelIndexBps:inputs.sockelIndexBps,consumableReturnBps:inputs.consumableReturnBps});\n"
        "inputs.projectionSeriesRappen=proj.seriesRappen;\n"
        if with_baseline
        else ""
    )
    script = f"""
const assets = [
  {{position_type:'Depot', assignment:'Beratungsvermögen', current_value_rappen:10000000,
    currency:'CHF'}},
  {{position_type:'Immobilien', assignment:'Anderes Vermögen', current_value_rappen:80000000,
    currency:'CHF', asset_expected_return_bps:0}}
];
const liabilities = [
  {{position_type:'Hypothek', assignment:'Verbindlichkeit', current_value_rappen:30000000,
    currency:'CHF'}},
  {json.dumps(other_debt, ensure_ascii=False)}
];
const strategyState = {{allocation:{allocation}}};
const ADMIN_CMA_DEFAULTS = {{equity_intl_return_bps:690,bonds_fx_hedged_return_bps:220,
  real_estate_ch_return_bps:450,alternatives_gold_return_bps:300}};
function isExternalPensionPosition(pos) {{ return false; }}
function pensionProjectionRateBps(pos) {{ return null; }}
function wealthScopePositions(scope) {{ return assets; }}
function activeClientWealthPositions() {{ return assets.concat(liabilities); }}
function activeClientCashflowSummary() {{ return {{}}; }}
function summaryRecurringNetCashflowRappen() {{ return 0; }}
function summaryCapitalNetCashflowRappen() {{ return 0; }}
function summaryTotalNetCashflowRappen() {{ return 0; }}
function projectionYearLabels(a, years, labels) {{ return labels || []; }}
function projectionSeriesCagrBps() {{ return 0; }}
function inferPositionBucketMixBps(pos) {{
  if (pos.position_type === 'Immobilien') return {{equities:0,bonds:0,realEstate:10000,liquidity:0,alternatives:0}};
  return {{equities:10000,bonds:0,realEstate:0,liquidity:0,alternatives:0}};
}}
{chr(10).join(helpers)}
var inputs = wealthProjectionInputs('total', {years});
{tail}process.stdout.write(JSON.stringify(inputs));
"""
    script_path = tmp_path / "total_wealth_snapshot_parity.mjs"
    script_path.write_text(script, encoding="utf-8")
    completed = subprocess.run(
        ["node", str(script_path)],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    return json.loads(completed.stdout)


_CHF_OTHER_DEBT = {
    "position_type": "Custom",
    "assignment": "Verbindlichkeit",
    "current_value_rappen": 20_000_000,
    "currency": "CHF",
}
_CASCADE_SNAPSHOT = {
    "total_base_rappen": 40_000_000,
    "foundation_rappen": 50_000_000,
    "foundation_in_net_wealth_rappen": 40_000_000,
    "foundation_charged_other_liabilities_rappen": 10_000_000,
}


# --- 1. audit reproducer (adopted without xfail) ------------------------------


def test_projection_uses_backend_liability_cascade_for_net_foundation(tmp_path: Path) -> None:
    """Other debt consumes financial buckets before the property foundation."""
    result = _run_projection(tmp_path, snapshot=_CASCADE_SNAPSHOT, other_debt=_CHF_OTHER_DEBT)

    assert result["startRappen"] == _CASCADE_SNAPSHOT["total_base_rappen"]
    assert result["sockelRappen"] == _CASCADE_SNAPSHOT["foundation_in_net_wealth_rappen"], result
    assert result["basisSource"] == "backend_snapshot"


def test_projection_uses_currency_normalized_backend_total_snapshot(tmp_path: Path) -> None:
    """Raw foreign-currency rappen must not replace the backend base-currency basis."""
    snapshot = {
        # Example: USD 200k liability converted by the backend to CHF 160k.
        "total_base_rappen": 44_000_000,
        "foundation_rappen": 50_000_000,
        "foundation_in_net_wealth_rappen": 44_000_000,
    }
    result = _run_projection(
        tmp_path,
        snapshot=snapshot,
        other_debt={**_CHF_OTHER_DEBT, "currency": "USD"},
    )

    assert result["startRappen"] == snapshot["total_base_rappen"], result


# --- 2./3./4. year path, server series, preview marker ----------------------


def test_year_one_gives_no_return_to_debt_covered_financial_wealth(tmp_path: Path) -> None:
    result = _run_projection(
        tmp_path, snapshot=_CASCADE_SNAPSHOT, other_debt=_CHF_OTHER_DEBT, with_baseline=True
    )
    # CHF 100k depot is fully consumed by the CHF 200k other debt (backend
    # cascade); with 0 % property appreciation and no cashflows the total
    # stays at the CHF 400k foundation. The old browser path grew a CHF 100k
    # financial block at 6.9 % on top of a CHF 300k floor (CHF 406'900).
    assert result["projectionSeriesRappen"][:3] == [40_000_000, 40_000_000, 40_000_000], result


def test_server_projection_basis_series_drive_the_floor(tmp_path: Path) -> None:
    """FX-normalized backend series replace the raw local ones; only deltas move the floor."""
    snapshot = {
        "total_base_rappen": 44_000_000,
        "foundation_rappen": 50_000_000,
        "foundation_in_net_wealth_rappen": 44_000_000,
        "projection_basis": {
            "schema": PROJECTION_BASIS_SCHEMA,
            # CHF 300k mortgage amortized directly by CHF 10k p.a. plus a
            # USD loan converted to CHF 160k (constant).
            "property_series_rappen": [80_000_000, 80_000_000, 80_000_000],
            "liability_series_rappen": [46_000_000, 45_000_000, 44_000_000],
            "pledged_asset_series_rappen": [0, 0, 0],
        },
    }
    result = _run_projection(
        tmp_path,
        snapshot=snapshot,
        other_debt={**_CHF_OTHER_DEBT, "currency": "USD"},
        with_baseline=True,
    )
    assert result["startRappen"] == 44_000_000
    assert result["sockelRappen"] == 44_000_000
    assert result["sockelGrossRappen"] == 80_000_000
    # Direct amortization is balance-neutral for the floor: debt falls by
    # CHF 10k a year -> floor rises by CHF 10k (cash outflow is in cashflows).
    assert result["projectionSeriesRappen"][:3] == [44_000_000, 45_000_000, 46_000_000], result


def test_without_snapshot_the_local_projection_is_marked_preview(tmp_path: Path) -> None:
    result = _run_projection(tmp_path, snapshot=None, other_debt=_CHF_OTHER_DEBT)
    assert result["basisSource"] == "local_preview"
    assert result["startRappen"] == 40_000_000  # PR #674 t0 fix stays


# --- backend snapshot --------------------------------------------------------


def _summary(**amounts_chf):
    full = {k: 0 for k in ("equities", "bonds", "real_estate", "alternatives", "liquidity")}
    full.update({k: v * 100 for k, v in amounts_chf.items()})
    return PortfolioSummary(amounts_rappen=full, total_rappen=sum(full.values()))


def test_backend_publishes_hashed_fx_normalized_projection_basis():
    foundation_projection = {
        "property_series_rappen": [80_000_000, 81_000_000],
        "liability_series_rappen": [50_000_000, 50_000_000],
        "pledged_asset_series_rappen": [0, 0],
    }
    payload = _build_total_wealth_allocation(
        _summary(equities=100_000, real_estate=800_000),
        30_000_000,
        40_000_000,
        {"equities": 6000, "bonds": 3000, "real_estate": 0, "alternatives": 500, "liquidity": 500},
        other_liabilities_rappen=20_000_000,
        foundation_projection=foundation_projection,
    )
    basis = payload["projection_basis"]
    assert basis["schema"] == PROJECTION_BASIS_SCHEMA
    assert basis["start_rappen"] == payload["total_base_rappen"] == 40_000_000
    assert basis["foundation_in_net_wealth_rappen"] == payload["foundation_in_net_wealth_rappen"] == 40_000_000
    assert basis["foundation_charged_other_liabilities_rappen"] == 10_000_000
    assert basis["financial_net_rappen"] == 0
    assert basis["property_series_rappen"] == [80_000_000, 81_000_000]
    assert basis["liability_series_rappen"] == [50_000_000, 50_000_000]
    assert len(basis["basis_hash"]) == 64
    # Direct property comes from the same projection (year 0) as before.
    explicit = _build_total_wealth_allocation(
        _summary(equities=100_000, real_estate=800_000),
        30_000_000,
        40_000_000,
        {"equities": 6000, "bonds": 3000, "real_estate": 0, "alternatives": 500, "liquidity": 500},
        direct_property_rappen=80_000_000,
        other_liabilities_rappen=20_000_000,
    )
    assert {k: v for k, v in payload.items() if k != "projection_basis"} == explicit
    # Hash binds the content.
    changed = dict(foundation_projection, liability_series_rappen=[50_000_000, 49_000_000])
    other = _build_total_wealth_allocation(
        _summary(equities=100_000, real_estate=800_000), 30_000_000, 40_000_000,
        {"equities": 6000, "bonds": 3000, "real_estate": 0, "alternatives": 500, "liquidity": 500},
        other_liabilities_rappen=20_000_000, foundation_projection=changed,
    )
    assert other["projection_basis"]["basis_hash"] != basis["basis_hash"]


def test_engine_call_sites_pass_the_foundation_projection():
    source = (_BACKEND_ROOT / "services" / "portfolio_engine.py").read_text(encoding="utf-8")
    assert source.count("= _build_total_wealth_allocation(") == 2
    assert len(re.findall(r"(?<![\w])foundation_projection=external_foundation_projection,", source)) == 2
    assert "direct_property_rappen=external_foundation_projection" not in source


# --- 5. report wealth summary ------------------------------------------------


def test_report_wealth_summary_uses_engine_fx_conversion(tmp_path, monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    import services.currency.fx_rates as fx_rates
    from database import Base
    from models.clients import Client
    from models.mandates import Mandate
    from models.users import User
    from models.wealth import WealthPosition
    from services.advisory_report import _build_wealth_summary

    class _Fx:
        def cross_rate(self, from_currency: str, to_currency: str) -> float:
            assert (from_currency, to_currency) == ("USD", "CHF")
            return 0.8

    monkeypatch.setattr(fx_rates.FXRateSource, "from_db", classmethod(lambda cls, db: _Fx()))
    engine = create_engine(f"sqlite:///{tmp_path / 'report_fx.db'}")
    Base.metadata.create_all(bind=engine)
    now = "2026-10-24T00:00:00.000Z"
    try:
        with sessionmaker(bind=engine, expire_on_commit=False)() as s:
            advisor = User(id=str(uuid.uuid4()), username="adv-fx", password_hash="h", full_name="A",
                           role="advisor", is_active=1, created_at=now, updated_at=now)
            client = Client(id=str(uuid.uuid4()), client_number="C-fx", first_name="F", last_name="X",
                            advisor_id=advisor.id, country_of_residence="CH", created_at=now, updated_at=now)
            mandate = Mandate(id=str(uuid.uuid4()), client_id=client.id, mandate_number="M-fx",
                              mandate_type="Anlageberatung", opened_at=now, created_at=now, updated_at=now,
                              base_currency="CHF")
            s.add_all([advisor, client, mandate])
            s.flush()
            for label, ptype, assignment, value, currency in (
                ("Depot", "Depot", "Beratungsvermögen", 10_000_000, "CHF"),
                ("Haus", "Immobilien", "Anderes Vermögen", 80_000_000, "CHF"),
                ("Hypothek", "Hypothek", "Verbindlichkeit", 30_000_000, "CHF"),
                ("USD-Kredit", "Custom", "Verbindlichkeit", 20_000_000, "USD"),
            ):
                s.add(WealthPosition(id=str(uuid.uuid4()), client_id=client.id, label=label, position_type=ptype,
                                     assignment=assignment, current_value_rappen=value, currency=currency,
                                     is_active=1, created_at=now, updated_at=now))
            s.commit()
            summary = _build_wealth_summary(s, mandate, client)
    finally:
        engine.dispose()
    # USD 200k -> CHF 160k: net 900k - 300k - 160k = 440k (same basis as the
    # engine's FX-normalized total_base_rappen), not raw 400k.
    assert summary["kredite_rappen"] == 46_000_000
    assert summary["gesamtvermoegen_rappen"] == 44_000_000
