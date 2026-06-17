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


def test_save_button_present_and_dispatches_by_mode():
    """Expliziter 'Speichern'-Knopf neben dem Horizont-Control, mehrfach nutzbar.
    saveAaHorizon dispatcht je nach Modus auf die bestehenden apply-Funktionen."""
    html = _html()
    assert 'onclick="saveAaHorizon()"' in html, "Speichern-Button fehlt"
    assert ">Speichern<" in html
    start = html.find("function saveAaHorizon(")
    assert start != -1
    body = html[start:start + 700]
    assert "applyIstHorizonAge(" in body
    assert "applyAaHorizonEndYear(" in body
    assert "applyIstHorizonOverride(" in body
    assert "resetIstHorizonOverride()" in body


def test_aa_horizon_control_synced_from_override_source():
    """syncAaHorizonControl wird aus syncIstHorizonOverrideInput aufgerufen ->
    der Balken bleibt mit dem (gemeinsamen) Override synchron."""
    html = _html()
    start = html.find("function syncIstHorizonOverrideInput(")
    assert start != -1
    body = html[start:start + 900]
    assert "syncAaHorizonControl()" in body


def test_chart_render_honors_horizon_override():
    """Damit 'Speichern' die Grafik wirklich aendert: updateProjectionChartsFromSimulation
    muss den Override VOR der vollen Engine-Laenge beruecksichtigen."""
    html = _html()
    start = html.find("function updateProjectionChartsFromSimulation(")
    assert start != -1
    body = html[start:start + 900]
    assert "loadIstHorizonOverride" in body, "Override wird im Chart-Render nicht gelesen"
    assert "_hOv&&_hOv>0" in body, "Override hat keinen Vorrang vor der Engine-Laenge"


def test_fan_chart_truncates_to_override():
    """Der SOLL-Faecher (Best/Haupt/Worst) muss ebenfalls auf den Override
    getrunkiert werden, sonst bleibt er in voller Engine-Laenge."""
    html = _html()
    start = html.find("function upgradeFanChartWithMonteCarlo(")
    assert start != -1
    body = html[start:start + 1400]
    assert "loadIstHorizonOverride" in body
    assert "_hCut" in body


def test_override_apply_rerenders_fan():
    """applyIstHorizonOverride muss nach dem Chart-Update auch den Faecher neu
    zeichnen (sonst bliebe nur die deterministische Linie)."""
    html = _html()
    start = html.find("async function applyIstHorizonOverride(")
    assert start != -1
    body = html[start:start + 1400]
    assert "upgradeFanChartWithMonteCarlo(" in body
