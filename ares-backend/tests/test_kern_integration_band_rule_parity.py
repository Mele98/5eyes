"""Kern-Integration Runde 3 (H-172): EINE Bandregel in UI und Backend.

``core/band_rule.py`` (KN3-B Nachtrag 2) und ``kn3-ui.js``
``aresBandOf``/``aresBandStatus`` (KN3-U) muessen dieselbe Regeltabelle
liefern. Die JS-Funktionen laufen unveraendert (aus dem Bundle extrahiert) in
Node und werden Fall fuer Fall gegen die Python-Regel gelegt:

* 0/0 mit Ist > 0 -> verletzt; 0/0 mit Ist = 0 -> im Band;
* Punktband min = max > 0 (Live-Test H6) -> echte Grenze;
* normales Band innen/unter/ueber;
* fehlende Grenze (None) oder min > max -> nicht bewertbar, nie "im Band".

Abbildung: Backend ``in_band`` = UI ``in``; ``below``/``above`` = ``violated``;
``not_evaluable`` = ``none``.

Bewusste Abweichung (nur dokumentiert, nicht in der Tabelle): fehlt der
Ist-Wert, rechnet die UI mit 0 (die Classic-Oberflaeche erhaelt das Ist-Gewicht
immer als Zahl), das Backend meldet "nicht bewertbar".
"""
from __future__ import annotations

from core.band_rule import BAND_ABOVE, BAND_BELOW, BAND_IN, BAND_UNKNOWN, band_status
from tests.livetest_monolith_js import run_js

# (Ist, min, max, erwartet)  erwartet in UI-Begriffen
CASES = [
    (3556, 0, 0, "violated"),      # Kapitalschutz: Aktien 35.6 % bei Band 0/0
    (1, 0, 0, "violated"),
    (0, 0, 0, "in"),
    (10000, 320, 320, "violated"),  # H6: Punktband 3.2 % bei 100 % Ist
    (320, 320, 320, "in"),
    (0, 320, 320, "violated"),
    (5000, 4000, 6000, "in"),
    (3999, 4000, 6000, "violated"),
    (6001, 4000, 6000, "violated"),
    (4000, 4000, 6000, "in"),
    (6000, 4000, 6000, "in"),
    (500, None, 1000, "none"),     # fehlende Grenze
    (500, 0, None, "none"),
    (500, None, None, "none"),
    (0, None, None, "none"),
    (500, 700, 600, "none"),       # min > max ungueltig
]

BACKEND_TO_UI = {BAND_IN: "in", BAND_BELOW: "violated", BAND_ABOVE: "violated", BAND_UNKNOWN: "none"}


def _ui_statuses():
    js_cases = ",".join(
        "[{},{},{}]".format(c, "null" if lo is None else lo, "null" if hi is None else hi)
        for c, lo, hi, _ in CASES
    )
    return run_js(["aresBandOf", "aresBandStatus"],
                  f"return [{js_cases}].map(function(c){{return aresBandStatus(c[0],c[1],c[2]);}});")


def test_ui_and_backend_band_rule_agree_on_every_case():
    ui = _ui_statuses()
    rows = []
    for (current, low, high, expected), ui_status in zip(CASES, ui):
        backend = BACKEND_TO_UI[band_status(current, low, high)]
        rows.append((current, low, high, expected, ui_status, backend))
    mismatches = [r for r in rows if not (r[3] == r[4] == r[5])]
    assert not mismatches, mismatches


def test_counterproof_old_zero_band_rule_would_be_detected():
    """Gegenprobe: die alte Regel "0/0 = keine Grenze" weicht in der Tabelle ab."""
    def old_rule(current, low, high):
        if low is None or high is None or low > high or (low == 0 and high == 0):
            return "none"
        return "in" if low <= current <= high else "violated"

    assert [c for c in CASES if old_rule(*c[:3]) != c[3]], "Tabelle wuerde die alte 0/0-Regel nicht erkennen"


def test_documented_difference_missing_current():
    ui = run_js(["aresBandOf", "aresBandStatus"], "return [aresBandStatus(null,0,0),aresBandStatus(null,100,200)];")
    assert ui == ["in", "violated"]
    assert band_status(None, 0, 0) == BAND_UNKNOWN and band_status(None, 100, 200) == BAND_UNKNOWN
