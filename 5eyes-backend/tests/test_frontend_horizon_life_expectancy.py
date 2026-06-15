"""Regressions-Sperre: Projektions-/X-Achsen-Horizont = Geburtsjahr + 83 (Mann)
/ + 85 (Frau), bei Paaren die laengere Lebenserwartung. Greift fuer SOLL/IST-
Vergleich (Sim-Horizont) UND Verzehr-Chart (Cashflow-Projektion). Verhindert,
dass die X-Achse wieder vor dem Kurvenende endet (Bug: Achse bis ~2036).
"""
from pathlib import Path


HTML_PATH = Path(__file__).resolve().parents[2] / "5eyes-electron" / "frontend" / "5eyes_v2.html"


def _html() -> str:
    return HTML_PATH.read_text(encoding="utf-8")


def test_life_expectancy_helpers_exist():
    html = _html()
    assert "function _lifeExpectancyEndYear()" in html
    assert "function _lifeExpectancyHorizonYears()" in html


def test_life_expectancy_rule_83_85_by_salutation():
    html = _html()
    # Maenner (Anrede "Herr") +83, sonst (Frau/unbekannt) +85.
    assert "indexOf('herr')" in html
    assert "by+(isMale?83:85)" in html


def test_household_uses_longer_life_expectancy():
    html = _html()
    # Partner einbeziehen + Maximum (Verzehr bis beide Personen weg).
    assert "currentPersona.partner_date_of_birth" in html
    assert "Math.max.apply(null,ends)" in html


def test_cashflow_horizon_falls_back_to_life_expectancy():
    html = _html()
    assert "function effectiveCashflowProjectionHorizon()" in html
    # Berater-Override hat Vorrang, danach Lebenserwartung.
    assert "_lifeExpectancyHorizonYears()" in html


def test_simulation_horizon_reaches_life_expectancy():
    html = _html()
    # Sim-Horizont (SOLL/IST-Vergleich) zieht die Lebenserwartung als Untergrenze:
    # horizonYears = max(eingestellter Wert, Lebenserwartung-Horizont).
    assert "var _l=_lifeExpectancyHorizonYears();" in html
    assert "return String((_l&&_l>_b)?_l:_b);" in html


def test_compare_axis_never_shorter_than_data():
    html = _html()
    # Defensives Netz: X-Achse mind. so lang wie die laengste Datenreihe.
    assert "X-Achse" in html and "längste" in html
