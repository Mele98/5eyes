"""H9 Nachtrag 3 -- App und PDF nennen das Endjahr gleich ("Ende JJJJ").

Konvention (wie Horizont-Anzeige "= bis 2040"): Projektionslabels markieren den
Stand zu Jahresbeginn, der letzte Punkt ist der Stand nach dem letzten
inklusiven Jahr -- Label 2041 = "Ende 2040". Zentrale Python-Hilfsfunktion
``format_end_of_year`` (PDF), App ``projectionEndOfYearText``, React
``formatEndOfYear``.
"""
from __future__ import annotations

from io import BytesIO

import pytest

from services.pdf.components.swiss_numbers import format_end_of_year
from tests.livetest_monolith_js import run_js

LABELS = ["2041", 2041, "2061", "2036", "", None, "Horizont"]


def test_python_helper_matches_app_helper_for_every_label():
    import json

    calls = ",".join("projectionEndOfYearText(%s)" % json.dumps(v) for v in LABELS)
    js = run_js(("projectionEndOfYearText",), "return [" + calls + "];")
    py = [format_end_of_year(v) for v in LABELS]
    assert py == js
    assert py[:4] == ["Ende 2040", "Ende 2040", "Ende 2060", "Ende 2035"]


def _pdf_text(flowables) -> str:
    from pypdf import PdfReader
    from reportlab.platypus import SimpleDocTemplate

    buf = BytesIO()
    SimpleDocTemplate(buf).build(list(flowables))
    reader = PdfReader(BytesIO(buf.getvalue()))
    return " ".join(" ".join((p.extract_text() or "").split()) for p in reader.pages)


APP_PRELUDE = r"""
var __labels={};
function aaProjectionHorizonCut(n){return n;}
function aaReserveSockelRappen(){return 0;}
function aaSeriesValueAt(s,cut){return Number(s[Math.max(0,cut-1)]||0);}
function simulationCagrBps(){return 300;}
function formatCompactCHF(v){return 'CHF '+Math.round(v);}
function fmtPct(v){return String(v);}
"""


def test_same_case_app_and_pdf_name_the_same_end_year():
    """Gleiches Monte-Carlo-Ergebnis: App-Endwert-Tabelle und PDF-Kennzahlen
    nennen dasselbe Endjahr."""
    from services.pdf.components.sollist_vergleich import make_sollist_kennzahlen_table

    year_labels = list(range(2026, 2042))  # letzter Punkt 2041
    series = [15_000_000 + i * 100_000 for i in range(len(year_labels))]
    app = run_js(
        ("renderAaProjectionEndValues", "simulationPayload", "monteCarloPayload", "projectionEndOfYearText"),
        "var r={monte_carlo:{year_labels:%s,target_p50_series_rappen:%s,current_p50_series_rappen:%s,"
        "target_p90_series_rappen:%s,target_p10_series_rappen:%s,current_p90_series_rappen:%s,current_p10_series_rappen:%s}};"
        "renderAaProjectionEndValues(r);return document.getElementById('aa-proj-lbl-median').textContent;"
        % (year_labels, series, series, series, series, series, series),
        prelude=APP_PRELUDE,
    )
    assert app.startswith("Endwert Ende 2040 ")
    pdf = _pdf_text(make_sollist_kennzahlen_table(
        target_median_end_rappen=series[-1], target_p90_end_rappen=series[-1], target_p10_end_rappen=series[-1],
        current_median_end_rappen=series[-1], current_p90_end_rappen=series[-1], current_p10_end_rappen=series[-1],
        target_cagr_bps=300, current_cagr_bps=250, target_volatility_1y_bps=900, current_volatility_1y_bps=800,
        end_year_label=str(year_labels[-1]),
    ))
    assert "Erwartetes Endvermögen Ende 2040 (Median)" in pdf
    assert "Endvermögen Ende 2040 optimistisch (P90)" in pdf
    assert "2041" not in pdf
    end_app = app.split(" – ")[0].replace("Endwert ", "")
    assert end_app in pdf  # "Ende 2040" in beiden Kanaelen


def test_pdf_without_year_label_keeps_neutral_text():
    from services.pdf.components.sollist_vergleich import make_sollist_kennzahlen_table

    pdf = _pdf_text(make_sollist_kennzahlen_table(
        target_median_end_rappen=1, target_p90_end_rappen=1, target_p10_end_rappen=1,
        current_median_end_rappen=1, current_p90_end_rappen=1, current_p10_end_rappen=1,
        target_cagr_bps=1, current_cagr_bps=1, target_volatility_1y_bps=1, current_volatility_1y_bps=1,
    ))
    assert "Erwartetes Endvermögen (Median)" in pdf and "Ende" not in pdf


def test_pdf_route_passes_monte_carlo_end_label():
    import inspect

    from routers import pdf_reports
    from services.pdf.documents import anlagestrategie

    src = inspect.getsource(pdf_reports)
    assert 'projection_end_year_label = str(_mc_labels[-1])' in src
    assert "projection_end_year_label=projection_end_year_label" in src
    assert 'end_year_label=getattr(data, "projection_end_year_label", None)' in inspect.getsource(anlagestrategie)


@pytest.mark.parametrize("label,expected", [("2041", "Ende 2040"), ("2041-12", "Ende 2040"), ("", ""), (None, "")])
def test_format_end_of_year_edge_cases(label, expected):
    assert format_end_of_year(label) == expected
