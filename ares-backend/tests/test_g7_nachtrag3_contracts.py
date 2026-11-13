"""G7 / H-153 Nachtrag 3 -- N-894-07..11.

* N-894-09: Review-Seite zeigt beim ERSTEN Aufruf (kein vorbelegter globaler
  Zustand) die apportionierten Soll-Anteile der dargestellten Allokation.
* N-894-08: Faecher-Saetze (Classic) in Mandatswaehrung.
* N-894-11: toter Projektions-KPI-Zweig entfernt.
* Rebalancing-Delta aus den angezeigten Werten.
* N-894-07: Ganzzahlpruefung strikt und kanalgleich (React/Classic separat).
"""
from __future__ import annotations

import html as html_lib
import json

import pytest

from core import presentation_rounding as R
from tests.livetest_monolith_js import run_js
from tests.monolith_source import read_monolith_bundle

BUCKETS = [
    {"asset_class": "Aktien", "target_weight_bps": 6933, "target_amount_rappen": 36394300},
    {"asset_class": "Obligationen", "target_weight_bps": 1751, "target_amount_rappen": 9191800},
    {"asset_class": "Immobilien", "target_weight_bps": 551, "target_amount_rappen": 2892400},
    {"asset_class": "Alternative", "target_weight_bps": 563, "target_amount_rappen": 2955400},
    {"asset_class": "Liquiditaet", "target_weight_bps": 202, "target_amount_rappen": 1060400},
]
STUBS = r"""
function currentPersistedRiskForMandate(){return null;}
function getActiveMandateId(){return 'M1';}
function goalSuccessSummary(){return {scored:0};}
function goalSuccessSubText(){return '';}
function goalSuccessAmpel(){return 'g';}
function goalSuccessPct(){return null;}
function goalSuccessIsEstimate(){return false;}
function setGoalSuccessTile(){}
function projectionHorizonYearLabel(){return '2046';}
function riskAssessmentReadyForStrategy(){return true;}
function simulationPayload(){return null;}
function strategyMedianProjectionRappen(){return 0;}
function renderStrategySummary(){}
function assetClassCssVar(){return 'var(--x)';}
// Erstaufruf nach Kundenwahl: globaler Zustand existiert, ist aber noch LEER.
var strategyState={allocation:null,recommendation:null};
"""


def _plain(text: str) -> str:
    return html_lib.unescape(text).replace("−", "-").replace(" ", " ")


def test_review_first_call_shows_apportioned_soll_without_global_state():
    """N-894-09: Harness belegt strategyState.allocation NICHT vor -- wie beim ersten Aufruf nach
    Kundenwahl. Aktien 69.33 % muss 69.4 % zeigen (wie PDF/AA-Seite), nicht 69.3 %."""
    out = run_js(
        ("renderSrApiSummary", "assetDisplayName", "formatBpsPercent", "fmtPct", "fmtNumber", "formatRappen",
         "formatCompactCHFAmount", "formatCompactCHF", "fmtProbPct"),
        "renderSrApiSummary({final_profile:'Ausgewogen'},{buckets:" + json.dumps(BUCKETS)
        + ",advisory_wealth_rappen:53000000,total_wealth_rappen:60000000},null,null,[]);"
        "return {bars: document.getElementById('sr-allocation-bars').innerHTML,"
        " empty: strategyState.allocation===null};",
        prelude=STUBS,
    )
    assert out["empty"] is True
    bars = _plain(out["bars"])
    expected = R.apportion_bucket_bps({"equities": 6933, "bonds": 1751, "real_estate": 551,
                                       "alternatives": 563, "liquidity": 202})
    assert "69.4 %" in bars and "69.3 %" not in bars
    for key in ("equities", "bonds", "real_estate", "alternatives", "liquidity"):
        assert f"{expected[key]} %" in bars, key


def test_soll_pct_requires_the_displayed_buckets_and_never_falls_back_to_single_rounding():
    out = run_js(
        ("fmtPct", "fmtNumber"),
        "var b=" + json.dumps(BUCKETS) + ";"
        "return {a:sollPct('Aktien',6933,b), l:sollPct('Liquidität',202,b), missing:sollPct('Aktien',6933,[]),"
        " zero:sollPct('Gold',0,b)};",
    )
    assert _plain(out["a"]) == "69.4 %"
    assert _plain(out["l"]) == "2.0 %"
    assert out["missing"] == "—"  # kein stilles 69.3 % aus Einzelrundung
    assert _plain(out["zero"]) == "0.0 %"
    html = read_monolith_bundle()
    calls = [c for c in html.split("sollPct(")[1:]]
    for c in calls:
        head = c.split(")", 1)[0]
        if head.startswith("cls,bps"):
            continue  # Definition
        assert head.count(",") >= 2 or "buckets" in head, head


def test_review_card_delta_is_built_from_displayed_values():
    rows = [
        {"assetKey": "aktien", "currentWeightBps": 4670, "targetWeightBps": 6933},
        {"assetKey": "obligationen", "currentWeightBps": 2550, "targetWeightBps": 1751},
        {"assetKey": "immobilien", "currentWeightBps": 430, "targetWeightBps": 551},
        {"assetKey": "alternative", "currentWeightBps": 420, "targetWeightBps": 563},
        {"assetKey": "liquiditaet", "currentWeightBps": 1930, "targetWeightBps": 202},
    ]
    out = run_js((), "return AresRounding.istSollText(" + json.dumps(rows) + ",'aktien',{typography:'plain'});")
    assert out == "IST 46.7 % → SOLL 69.4 % · Delta -22.7 %"  # Roh-bps-Delta waere -22.6 %
    html = read_monolith_bundle()
    assert "AresRounding.istSollText(reviewStrategyComparisonRows(allocation),item.assetKey" in html


@pytest.mark.parametrize("currency", ["EUR", "JPY"])
def test_classic_fan_sentences_use_mandate_currency(currency):
    out = run_js(
        ("fanRangeSentence", "fanAboveScaleText", "formatCompactCHFAmount", "_fanFinite", "aaChartCurrency"),
        "return {r:fanRangeSentence(2046,2290000,5610000), a:fanAboveScaleText(5000000)};",
        prelude="var currentMandateData={base_currency:'" + currency + "'};",
    )
    assert _plain(out["r"]) == f"In 8 von 10 Verläufen liegt Ihr Vermögen 2046 zwischen {currency} 2.29 und 5.61 Mio."
    assert _plain(out["a"]) == f"▲ {currency} 5.00 Mio. über Skala"


def test_dead_projection_kpi_branch_removed():
    assert "kpi-card-projection" not in read_monolith_bundle()


# --- N-894-10 / CHF-Guard: PDF-Komponenten in Mandatswaehrung ---------------------------

def _drawing_texts(drawing) -> list[str]:
    out = []
    stack = list(getattr(drawing, "contents", []))
    while stack:
        node = stack.pop()
        if hasattr(node, "text"):
            out.append(str(node.text))
        stack.extend(getattr(node, "contents", []) or [])
    return out


@pytest.mark.parametrize("currency", ["EUR", "JPY"])
def test_pdf_mc_axis_and_wealth_chart_use_mandate_currency(currency):
    from services.pdf.components.mc_paths_chart import make_y_tick_formatter
    from services.pdf.components.wealth_chart import make_wealth_chart

    fmt = make_y_tick_formatter(600_000_000, 200_000_000, currency)
    assert fmt(200_000_000) == f"{currency} 2 Mio."  # identisch zu React makeYTickFormatter
    assert fmt(0) == f"{currency} 0"
    texts = _drawing_texts(make_wealth_chart([(2020, 10_000_000), (2021, 11_000_000)], currency=currency))
    assert any(t.startswith(currency + " ") for t in texts), texts
    assert not any("CHF" in t for t in texts), texts


def test_pdf_backtest_fee_row_and_reference_currency_text():
    from services.pdf.components.text_sections import make_anlageuniversum_section
    from services.pdf.documents.backtest import _fee_row

    row = _fee_row(label="Strategie", fee_bps=100, gross_path=[(2020, 0), (2021, 12_345_600)],
                   net_path=[(2020, 0), (2021, 12_000_000)], currency="EUR")
    assert "EUR 123'456" in row and "CHF" not in row
    paras = " ".join(getattr(f, "text", "") for f in make_anlageuniversum_section("EUR"))
    assert "Die Referenzwährung ist der EUR." in paras
    assert "{currency}" not in paras
