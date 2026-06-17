"""2026-06-17: Benutzerfreundlicher Prognose-Horizont direkt bei den SOLL/IST-Charts.

Der Berater kann den Horizont per "bis Alter X" / "bis Jahr" / "Anzahl Jahre" setzen.
Wichtig: das aendert NUR die Grafik-Laenge (gleicher client-Override wie die
Cashflow-Seite -> Projektion neu laden + Charts neu zeichnen), NICHT die SAA/Renditen.
"""
from pathlib import Path

HTML_PATH = Path(__file__).resolve().parents[2] / "5eyes-electron" / "frontend" / "5eyes_v2.html"


def _html() -> str:
    return HTML_PATH.read_text(encoding="utf-8")


def test_horizon_control_present_at_charts():
    html = _html()
    for el in ("aa-horizon-mode", "aa-horizon-age", "aa-horizon-endyear", "aa-horizon-years", "aa-horizon-eff"):
        assert f'id="{el}"' in html, f"Horizont-Control-Element {el} fehlt"
    assert 'onchange="setAaHorizonMode(this.value)"' in html
    assert 'onchange="applyIstHorizonAge(this.value)"' in html
    assert 'onchange="applyAaHorizonEndYear(this.value)"' in html


def test_reassurance_text_returns_unchanged():
    # Macht dem Berater optisch klar, dass nur die Grafik betroffen ist.
    assert "ändert nur die Grafik-Länge, nicht die Renditen" in _html()


def test_age_mode_reuses_override_not_a_new_return_path():
    """applyIstHorizonAge MUSS ueber applyIstHorizonOverride laufen (gleicher
    Display-Override, keine Engine-/Rendite-Neuberechnung)."""
    html = _html()
    start = html.find("function applyIstHorizonAge(")
    assert start != -1
    body = html[start:start + 600]
    assert "applyIstHorizonOverride(" in body, "applyIstHorizonAge muss den bestehenden Override nutzen"
    assert "_horizonBirthYear()" in body, "Zielalter muss ueber das Geburtsjahr umgerechnet werden"


def test_aa_horizon_control_synced_from_override_source():
    """syncAaHorizonControl wird aus syncIstHorizonOverrideInput aufgerufen ->
    der Balken bleibt mit dem (gemeinsamen) Override synchron."""
    html = _html()
    start = html.find("function syncIstHorizonOverrideInput(")
    assert start != -1
    body = html[start:start + 900]
    assert "syncAaHorizonControl()" in body
