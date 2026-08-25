"""#108: Benannte Stress-Szenarien-Presets im Simulations-Dropdown.

Die Presets bilden historische Stress-Schweregrade auf den Volatilitaets-Multiplikator
(stressMultiplier) ab — reiner Anzeige-/Auswahl-Komfort, Backend-Logik unveraendert
(liest weiterhin den Zahlenwert, geclippt 0.25-2.5).
"""
from pathlib import Path

HTML = (Path(__file__).resolve().parents[2] / "5eyes-electron" / "frontend" / "5eyes_v2.html").read_text(encoding="utf-8")


def test_named_stress_presets_present():
    for label, value in (
        ("Corona-Schock 2020", "1.6"),
        ("Finanzkrise 2008", "1.8"),
        ("Zinsschock", "2.0"),
        ("Normal", "1.0"),
    ):
        assert label in HTML, f"Preset-Label fehlt: {label}"
        assert f'value="{value}"' in HTML, f"Preset-Wert fehlt: {value}"


def test_preset_multipliers_within_backend_clamp():
    # Alle Preset-Werte muessen im Backend-Clamp [0.25, 2.5] liegen.
    import re
    start = HTML.find('id="aa-sim-stress"')
    block = HTML[start:start + 600]
    values = [float(v) for v in re.findall(r'value="([0-9.]+)"', block)]
    assert values, "keine Stress-Optionen gefunden"
    assert all(0.25 <= v <= 2.5 for v in values), f"Preset ausserhalb Clamp: {values}"
