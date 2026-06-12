"""#AA-7 (2026-06-12): Themen-Tilt im Per-Bucket-Raum, groessenunabhaengig.

Vor dem Fix: theme_total = 0.15 * targets["equities"] (Portfolio-Raum). Da
eq_splits aber im Per-Bucket-Raum leben (Summe 10000, in _append_split
renormalisiert), haengt die EFFEKTIVE Themen-Gewichtung von der Aktienquote
des Risikoprofils ab (eq=8000 -> ~12%, eq=5000 -> ~7.5%, eq=2000 -> ~3%).
Eine explizite "overweight"-Praeferenz wirkt damit fuer konservative Profile
deutlich schwaecher als fuer offensive — inkonsistent.

Nach dem Fix: theme_total relativ zu 10000 (Per-Bucket), Cap 1200 (12%) bleibt
-> konstante 12% des Aktien-Buckets unabhaengig von der Aktienquote.
"""
from __future__ import annotations
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import pytest
from services.portfolio_engine import _build_sub_allocations


def _theme_fraction(equities_bps: int, theme_label: str = "Thema Verteidigung",
                    tilt_key: str = "defense") -> float:
    targets = {"equities": equities_bps, "bonds": 10000 - equities_bps - 1000,
               "real_estate": 0, "alternatives": 0, "liquidity": 1000}
    subs = _build_sub_allocations(targets, {"tilts": {tilt_key: "overweight"}})
    theme = sum(s["target_weight_bps"] for s in subs
                if s["asset_class"] == "Aktien" and s["sub_asset_class"] == theme_label)
    eq_total = sum(s["target_weight_bps"] for s in subs if s["asset_class"] == "Aktien")
    assert eq_total > 0
    return theme / eq_total


@pytest.mark.parametrize("equities_bps", [8000, 5000, 2000])
def test_theme_tilt_fraction_independent_of_equity_share(equities_bps):
    """Der Themen-Anteil am Aktien-Bucket ist groessenunabhaengig (~12%)."""
    frac = _theme_fraction(equities_bps)
    assert abs(frac - 0.12) < 0.005, f"eq={equities_bps}: Anteil {frac*100:.2f}% != 12%"


def test_theme_tilt_consistent_across_equity_levels():
    """Direkter Konsistenz-Check: Anteil bei hoher vs niedriger Aktienquote gleich."""
    high = _theme_fraction(8000)
    low = _theme_fraction(2000)
    assert abs(high - low) < 0.005, f"high={high*100:.2f}% vs low={low*100:.2f}% — groessenabhaengig!"


def test_multiple_themes_split_the_bucket_cap():
    """Mehrere Themen teilen sich den 12%-Cap (3 Themen -> je ~4%)."""
    targets = {"equities": 5000, "bonds": 4000, "real_estate": 0,
               "alternatives": 0, "liquidity": 1000}
    subs = _build_sub_allocations(
        targets, {"tilts": {"defense": "overweight", "tobacco": "overweight", "alcohol": "overweight"}})
    eq_total = sum(s["target_weight_bps"] for s in subs if s["asset_class"] == "Aktien")
    theme_total = sum(s["target_weight_bps"] for s in subs
                      if s["asset_class"] == "Aktien" and s["sub_asset_class"].startswith("Thema "))
    # Gesamt-Themen ~12% des Buckets, auf 3 Themen verteilt.
    assert abs(theme_total / eq_total - 0.12) < 0.01
