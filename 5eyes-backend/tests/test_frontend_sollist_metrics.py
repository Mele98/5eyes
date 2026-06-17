"""Regressions-Sperre: SOLL/IST-Kennzahlen-Tabelle enthaelt P90/P10-Endwerte
(optimistisch/pessimistisch) und die Sharpe-Ratio (Rendite/Risiko), je Spalte
SOLL vs IST, aus dem MC-Payload. Erweiterung #35 + #37.
"""
from pathlib import Path


HTML_PATH = Path(__file__).resolve().parents[2] / "5eyes-electron" / "frontend" / "5eyes_v2.html"


def _html() -> str:
    return HTML_PATH.read_text(encoding="utf-8")


def test_p90_p10_endwert_rows_exist():
    html = _html()
    for cell in ("aa-proj-p90", "aa-proj-current-p90", "aa-proj-p10", "aa-proj-current-p10"):
        assert f'id="{cell}"' in html


def test_sharpe_rows_exist():
    html = _html()
    assert 'id="aa-proj-sharpe"' in html
    assert 'id="aa-proj-current-sharpe"' in html


def test_endwert_filled_from_percentile_series_last_value():
    html = _html()
    assert "target_p90_series_rappen" in html
    assert "target_p10_series_rappen" in html
    assert "current_p90_series_rappen" in html
    # Endwert = letztes Element der Reihe.
    assert "_lastRappen" in html


def test_sharpe_uses_riskfree_80bps_convention():
    html = _html()
    # risk-free = 80 bps (= liquidity_return_bps, Backend-Konvention).
    assert "_RF_BPS=80" in html
    assert "(r-_RF_BPS)/v" in html
    assert "target_annualized_return_p50_bps" in html


def test_new_metrics_get_better_worse_coloring():
    html = _html()
    assert "_colorBetter('aa-proj-p90'" in html
    assert "_colorBetter('aa-proj-p10'" in html
    assert "_colorBetter('aa-proj-sharpe'" in html


def test_sollist_png_export_exists():
    # #104: beide Vergleichsgrafiken als ein PNG fuers Kundengespraech.
    html = _html()
    assert "function exportSollIstComparePng()" in html
    assert "exportSollIstComparePng()" in html  # Button-Verdrahtung
    assert "out.toDataURL('image/png')" in html
    assert "drawImage(cs" in html and "drawImage(ci" in html
