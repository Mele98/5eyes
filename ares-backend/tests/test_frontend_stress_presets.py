"""#108: Presets im Simulations-Dropdown fuer den Volatilitaets-Multiplikator.

Die Presets setzen den Volatilitaets-Multiplikator (stressMultiplier) -- reiner
Anzeige-/Auswahl-Komfort, Backend-Logik unveraendert (liest weiterhin den
Zahlenwert, geclippt 0.25-2.5).

AA-UX-NUMBERS-001 (UX-Audit Befund 7): Die Presets hiessen frueher nach
historischen Krisen ("Corona-Schock 2020", "Finanzkrise 2008", "Zinsschock /
Stagflation"). Ein Faktor auf die Volatilitaet bildet aber weder Verlaufsmuster
noch Korrelationsbruch oder Zinsreaktion einer Krise ab, und die echte
historische Stress-Tabelle traegt dieselben Namen mit anderen Zahlen. Die
Presets sind deshalb jetzt ehrlich als "Volatilitaet xN" benannt; die Werte
(gespeicherter Vertrag) sind unveraendert.
"""
import re
from pathlib import Path

HTML = (Path(__file__).resolve().parents[2] / "ares-desktop" / "frontend" / "ares.html").read_text(encoding="utf-8")


def _stress_block() -> str:
    return re.search(r'<select[^>]*id="aa-sim-stress"[^>]*>.*?</select>', HTML, re.S).group(0)


def test_volatility_presets_present():
    block = _stress_block()
    for label, value in (
        ("Volatilität ×0.75 (gedämpft)", "0.75"),
        ("Volatilität ×1.0 (normal)", "1.0"),
        ("Volatilität ×1.5 (erhöht)", "1.5"),
        ("Volatilität ×1.6 (deutlich erhöht)", "1.6"),
        ("Volatilität ×1.8 (stark erhöht)", "1.8"),
        ("Volatilität ×2.0 (extrem erhöht)", "2.0"),
    ):
        assert f'<option value="{value}"' in block, f"Preset-Wert fehlt: {value}"
        assert label in block, f"Preset-Label fehlt: {label}"


def test_presets_carry_no_historical_crisis_names():
    block = _stress_block()
    for crisis in ("Corona", "Finanzkrise", "Zinsschock", "Stagflation"):
        assert crisis not in block


def test_preset_multipliers_within_backend_clamp():
    # Alle Preset-Werte muessen im Backend-Clamp [0.25, 2.5] liegen.
    values = [float(v) for v in re.findall(r'value="([0-9.]+)"', _stress_block())]
    assert values, "keine Stress-Optionen gefunden"
    assert all(0.25 <= v <= 2.5 for v in values), f"Preset ausserhalb Clamp: {values}"
