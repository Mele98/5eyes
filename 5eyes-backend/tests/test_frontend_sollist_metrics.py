"""Regressions-Sperre: SOLL/IST-Kennzahlen-Tabelle enthaelt P90/P10-Endwerte
(optimistisch/pessimistisch) und die Sharpe-Ratio (Rendite/Risiko), je Spalte
SOLL vs IST, aus dem MC-Payload. Erweiterung #35 + #37.
"""
from pathlib import Path


HTML_PATH = Path(__file__).resolve().parents[2] / "5eyes-electron" / "frontend" / "5eyes_v2.html"


def _html() -> str:
    return HTML_PATH.read_text(encoding="utf-8")


def _end_values_body() -> str:
    # AA-UX-NUMBERS-001: Endwerte/Faerbung/Reserve leben jetzt in
    # renderAaProjectionEndValues (auch bei Horizont-Wechsel neu gerendert).
    html = _html()
    start = html.find("function renderAaProjectionEndValues(")
    assert start != -1
    end = html.find("\nfunction ", start + 10)
    return html[start:end]


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
    # AA-UX-NUMBERS-001: Endwert = Element am ANGEZEIGTEN Horizont (ohne
    # Grafik-Ausschnitt = letztes Element). Verhalten: test_aa_view_numbers_and_labels.
    body = _end_values_body()
    assert "aaSeriesValueAt(mc.target_p90_series_rappen,cut)" in body
    assert "aaSeriesValueAt(mc.current_p10_series_rappen,cut)" in body


def test_sharpe_uses_riskfree_80bps_convention():
    html = _html()
    # risk-free = 80 bps (= liquidity_return_bps, Backend-Konvention).
    assert "_RF_BPS=80" in html
    assert "(r-_RF_BPS)/v" in html
    assert "target_annualized_return_p50_bps" in html


def test_new_metrics_get_better_worse_coloring():
    html = _html()
    body = _end_values_body()
    assert "paint('aa-proj-p90'" in body
    assert "paint('aa-proj-p10'" in body
    assert "_colorBetter('aa-proj-sharpe'" in html


def test_reserve_sockel_added_to_soll_curve_and_metrics():
    # User-Fachentscheid 2026-06-17: SOLL & IST starten am vollen Vermoegen.
    # RESERVE-FUNDING-LEDGER-001: neue Payloads fuehren die externe Reserve als
    # Reservekonto IM SOLL-Pfad (reserve_accounting_basis) -- ein zusaetzlicher
    # Sockel waere eine Doppelzaehlung. Der Sockel wird deshalb NUR noch fuer
    # Alt-Payloads ohne reserve_accounting_basis aufgeschlagen; der Zweck des
    # Entscheids (gleiche Startbasis) bleibt in beiden Faellen erfuellt.
    html = _html()
    assert (
        "function aaReserveSockelRappen(result,mc){"
        "if(mc&&mc.reserve_accounting_basis)return 0;"
        "return Number((result&&result.external_reserve_rappen)||0);}"
    ) in html
    # Chart: Sockel in RAPPEN auf die Serie, ERST DANN runden (sonst +-1k-Versatz).
    assert "_withSockel" in html and "_reserveR=aaReserveSockelRappen(result,mc)" in html
    assert "p90=_prep(mc.target_p90_series_rappen)" in html
    # Kennzahlen konsistent mit dem Chart (renderAaProjectionEndValues).
    body = _end_values_body()
    assert "aaReserveSockelRappen(result,mc)" in body
    assert "withRes(mc.target_p50_series_rappen)" in body
    assert "if(tP90)tP90+=res" in body and "if(tP10)tP10+=res" in body


def test_sollist_png_export_exists():
    # #104: beide Vergleichsgrafiken als ein PNG fuers Kundengespraech.
    html = _html()
    assert "function exportSollIstComparePng()" in html
    assert "exportSollIstComparePng()" in html  # Button-Verdrahtung
    assert "out.toDataURL('image/png')" in html
    assert "drawImage(cs" in html and "drawImage(ci" in html
