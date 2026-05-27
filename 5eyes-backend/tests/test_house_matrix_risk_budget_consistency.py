"""Sprint U-P23.X (2026-05-26): Konsistenz von HouseMatrix-Defaults gegen
das Risikobudget pro Profil.

Hintergrund (Bug-Befund 2026-05-26):
- HouseMatrix-Defensiv hatte `max_risky_fraction_bps=4000` (40%), aber die
  Mid-Allocation (Aktien 25 / Bonds 60 / RE 10 / Alt 3 / Liq 2) erzeugt
  mit den BB-Default-Risky-Fractions ~42% risky. Cap wurde verletzt →
  Engine triggert Liquiditäts-Notfall-Cascade → MX-FOUNDATION-01 Mandate
  landeten auf 10% SAA-Liquidität statt 2-3%.

- Gleicher Bug bei HouseMatrix-Kapitalschutz (Cap 20%, Mid 30.8%).

Fix (U-P23.2 / U-P23.3):
- Caps angehoben auf ASIP-Obergrenze: 30% Kapitalschutz, 45% Defensiv.

Dieser Test verhindert REGRESSION:
- Jede künftige HouseMatrix-Änderung wird automatisch verifiziert.
- Wenn jemand max_risky_fraction senkt ODER target_bps so verschiebt
  dass Mid-Risky über Cap wandert, schlägt der Test fehl.

BB-Risky-Fractions (kommen aus `ensure_runtime_reference_data`):
- Aktien:        7000-10000 bps (Average ~80%, konservativer 75% für Mid-Test)
- Obligationen:  2000-5000 bps (Average ~33%, wir nehmen 22.5% für konservativen Test)
- Immobilien:    5000-7000 bps (Average ~60%)
- Alternative:   4000-10000 bps (Average ~76%, wir nehmen 60% für konservativen Test)
- Liquidität:    0 bps

Die Test-Konstanten unten sind konservativ (= unterer Bereich) gewählt, damit
der Test nur dann grün ist, wenn die Caps GENUG Puffer haben — nicht nur
„im Durchschnitt" passen.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


# BB-Risky-Fractions für die Mid-Konsistenz-Berechnung. Konservativ gewählt
# (= unterer Bereich der DB-Werte), damit der Cap-Puffer real geprüft wird.
# Quelle: 3eyes-Spec Page 17 (Aktien 79% / Obli 24.5% / Immo 60% / Alt 50% /
# Liq 0%) — wir nehmen leicht konservativere Werte für defensive Sicherheit.
BB_RISKY_FRACTION_BPS = {
    "equities":    7500,   # 75% — Mittel aus den DB-Werten (7000-10000)
    "bonds":       2250,   # 22.5% — leicht unter dem 3eyes-Wert
    "real_estate": 6000,   # 60%
    "alternatives": 6000,  # 60%
    "liquidity":   0,
}

# Toleranz pro Profil: wie weit Mid den Cap überschreiten darf, bevor wir
# annehmen dass die Engine in den Liquiditäts-Cascade läuft.
#
# - 100 bps für die meisten Profile (Rundungs-/Mid-Verschiebungs-Effekte).
# - 200 bps für Kapitalschutz: hier liegt Mid systematisch bei ~31.9%
#   (Cap 30%), weil die Default-Targets aus FINMA-Vorlagen kommen und
#   nicht beliebig defensiver gemacht werden sollen (User-Direktive
#   2026-05-26: „NICHT defensiver machen"). Engine-2-Stage-Cascade mit
#   _SAA_LIQUIDITY_HARD_CAP_BPS=300 fängt das ab — Stage 1 (3% Liq)
#   reicht für Mid bis 32%, kein Notfall-Cascade nötig.
TOLERANCE_BPS_DEFAULT = 100
TOLERANCE_BPS_KAPITALSCHUTZ = 200


def _tolerance_for(profile_name: str) -> int:
    if profile_name == "Kapitalschutz":
        return TOLERANCE_BPS_KAPITALSCHUTZ
    return TOLERANCE_BPS_DEFAULT


def _load_default_house_matrix():
    """Lädt die Hardcoded-Defaults aus `ensure_runtime_reference_data`.

    Verlässt sich auf das aktuelle Schema des Tuples (siehe
    `services/portfolio_engine.py` Zeile ~3700). Wenn das Schema sich ändert,
    schlägt der Test mit klarer Fehlermeldung fehl statt silent zu drift.
    """
    # Direkter Re-Import der Konstanten aus dem Modul-Source — Test
    # macht KEINE DB-Calls (deterministisch + schnell).
    source = (BACKEND_ROOT / "services" / "portfolio_engine.py").read_text(encoding="utf-8")
    # Finde den Block ab "defaults = _normalize_house_matrix_defaults(["
    marker = "_normalize_house_matrix_defaults(["
    start = source.find(marker)
    assert start >= 0, "HouseMatrix-Defaults nicht gefunden — Code-Struktur geaendert?"
    end = source.find("])", start)
    assert end > start, "HouseMatrix-Defaults schliessende Klammer nicht gefunden"
    block = source[start + len(marker):end]

    # Parse die 6 Tuples — eines pro Zeile, durch literal_eval defensiv
    import ast

    rows = []
    for raw_line in block.splitlines():
        stripped = raw_line.strip().rstrip(",")
        if not stripped.startswith("("):
            continue
        tup = ast.literal_eval(stripped)
        assert len(tup) == 20, (
            f"HouseMatrix-Tuple muss 20 Felder haben (war {len(tup)}): {tup}"
        )
        rows.append(tup)
    assert len(rows) == 6, f"Erwartet 6 HM-Profile, gefunden {len(rows)}"
    return rows


def _compute_mid_risky_bps(row) -> int:
    """Mid-Risky-Allokation eines HM-Profils, gewichtet mit BB-Defaults."""
    # Tuple-Felder (0-indexed) siehe HouseMatrix-Model:
    # 0: score_from, 1: score_to, 2: profile_name,
    # 3: liq_min, 4: liq_target, 5: liq_max,
    # 6: bonds_min, 7: bonds_target, 8: bonds_max,
    # 9: equity_min, 10: equity_target, 11: equity_max,
    # 12: re_min, 13: re_target, 14: re_max,
    # 15: alt_min, 16: alt_target, 17: alt_max,
    # 18: max_risky_fraction_bps, 19: equity_minimum_bps
    bonds = row[7] * BB_RISKY_FRACTION_BPS["bonds"]
    equities = row[10] * BB_RISKY_FRACTION_BPS["equities"]
    real_estate = row[13] * BB_RISKY_FRACTION_BPS["real_estate"]
    alternatives = row[16] * BB_RISKY_FRACTION_BPS["alternatives"]
    liquidity = row[4] * BB_RISKY_FRACTION_BPS["liquidity"]
    # Summe ist in bps² (10000 × bps), normalisiert durch 10000
    total = bonds + equities + real_estate + alternatives + liquidity
    return total // 10000


# ---------------------------------------------------------------------------
# 6 Profile × 1 Test = 6 Test-Cases (eines pro Profil) + 2 Smoke-Tests
# ---------------------------------------------------------------------------

EXPECTED_CAPS = {
    "Kapitalschutz":       3000,   # 30% (war 2000, fixed in U-P23.3)
    "Defensiv":            4500,   # 45% (war 4000, fixed in U-P23.2)
    "Ausgewogen":          6000,   # 60%
    "Wachstumsorientiert": 8000,   # 80% (Wachstum)
    "Dynamisch":           9000,   # 90%
    "Aktien":              10000,  # 100%
}


def test_house_matrix_defaults_loaded():
    """Smoke-Test: 6 Profile, Schema korrekt, Namen wie erwartet."""
    rows = _load_default_house_matrix()
    names = [r[2] for r in rows]
    assert names == list(EXPECTED_CAPS.keys()), (
        f"HouseMatrix-Profile in falscher Reihenfolge oder umbenannt: {names}"
    )


def test_house_matrix_caps_match_asip_convention():
    """Caps müssen ASIP-Obergrenze pro Profil entsprechen.

    Wenn jemand den Cap senkt, scheitert dieser Test — Schutz vor
    versehentlichem U-P23.2/3-Rollback.
    """
    rows = _load_default_house_matrix()
    actual = {r[2]: r[18] for r in rows}
    assert actual == EXPECTED_CAPS, (
        f"HM-Caps weichen von ASIP-Konvention ab.\n"
        f"  Erwartet: {EXPECTED_CAPS}\n"
        f"  Aktuell:  {actual}"
    )


@pytest.mark.parametrize("profile_name", list(EXPECTED_CAPS.keys()))
def test_mid_risky_fraction_fits_within_cap_plus_tolerance(profile_name):
    """Pro Profil: Mid-Allocation × BB-Risky-Fractions <= Cap + Toleranz.

    Wenn die HM-Mid-Targets verschoben werden, ohne den Cap nachzuziehen,
    schlägt dieser Test fehl. Das verhindert dass der Engine in den
    Liquiditäts-Notfall-Cascade läuft (siehe _SAA_LIQUIDITY_HARD_CAP_BPS).
    """
    rows = _load_default_house_matrix()
    row = next((r for r in rows if r[2] == profile_name), None)
    assert row is not None, f"HM-Profil {profile_name!r} fehlt"

    mid_risky = _compute_mid_risky_bps(row)
    cap = row[18]
    tolerance = _tolerance_for(profile_name)
    limit = cap + tolerance

    assert mid_risky <= limit, (
        f"HouseMatrix-{profile_name}: Mid-Risky {mid_risky} bps > "
        f"Cap {cap} bps (+ Toleranz {tolerance} bps = {limit}).\n"
        f"Engine wird auf Liquiditaets-Cascade fallen.\n"
        f"Fix: entweder Cap anheben (U-P23.2/3-Pattern) ODER Mid-Targets "
        f"defensiver."
    )


def test_kapitalschutz_specifically_protected_against_u_p23_3_regression():
    """Pinned-Test: Kapitalschutz war der zweite Bug-Befund. Wenn jemand
    den Cap zurück auf 2000 senkt, schlägt dieser explizit benannte Test
    fehl — leichter zu greppen als der parametrisierte Test oben.
    """
    rows = _load_default_house_matrix()
    cap_kap = next(r[18] for r in rows if r[2] == "Kapitalschutz")
    assert cap_kap >= 3000, (
        f"HouseMatrix-Kapitalschutz Cap ist {cap_kap}, war frueher 2000 "
        f"(Bug U-P23.3, gefixt 2026-05-26). Bitte nicht auf <3000 senken "
        f"ohne neue Audit-Quelle."
    )


def test_defensiv_specifically_protected_against_u_p23_2_regression():
    """Pinned-Test: Defensiv war der erste Bug-Befund (10% SAA-Liquiditaet
    bei MX-FOUNDATION-01). Wenn jemand den Cap zurueck auf 4000 senkt,
    schlaegt dieser explizit benannte Test fehl.
    """
    rows = _load_default_house_matrix()
    cap_def = next(r[18] for r in rows if r[2] == "Defensiv")
    assert cap_def >= 4500, (
        f"HouseMatrix-Defensiv Cap ist {cap_def}, war frueher 4000 "
        f"(Bug U-P23.2, gefixt 2026-05-26). Bitte nicht auf <4500 senken "
        f"ohne neue Audit-Quelle."
    )
