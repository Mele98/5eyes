"""Z3 - C4: Sub-Allocation Splits proportional normalisieren.

Vor dem Fix:
  _build_sub_allocations definiert eq/bond/alt/re-Splits mit Default-Summe
  10000 (=100% des Buckets). Dann werden via Filter (z.B. !bondsHighYield,
  !bondsEmerging, !noEm) einzelne Eintraege ENTFERNT, OHNE die restlichen
  zu reskalieren. _append_split() gibt dem letzten Eintrag den remainder,
  was diesen kuenstlich uebergewichtet.

Nach dem Fix:
  _normalize_splits skaliert nach Filterung proportional auf 10000 mit
  kontrollierter Rest-Verteilung. _append_split nutzt die normalisierte
  Liste. Die Sub-Allocations summieren je Asset-Klasse exakt zum
  Bucket-Target und respektieren das Verhaeltnis der Original-Splits.
"""
from __future__ import annotations
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy.orm import configure_mappers
from database import Base  # noqa: F401
from models import (  # noqa: F401
    allocation, clients, mandates, profiling, review, snapshots, users, wealth,
)
configure_mappers()

from services.portfolio_engine import _build_sub_allocations


def _by_class(subs, asset_class):
    return [s for s in subs if s["asset_class"] == asset_class]


def _sum_bps(subs):
    return sum(int(s["target_weight_bps"] or 0) for s in subs)


def test_c4_bonds_filter_no_hy_no_em_normalizes_proportionally():
    """Default-Bond-Splits: CHF IG 5500, Global Hedged 3500, HY 500, EM 500.
    Mit bondsHighYield=False UND bondsEmerging=False bleiben nur CHF IG +
    Global Hedged. Vorher: Global Hedged bekommt remainder = 3500 +
    HY-EM-Verlust uebergewichtet.
    Nach Fix: proportional 5500/(5500+3500) bzw. 3500/9000 verteilt."""
    targets = {"equities": 4000, "bonds": 3000, "real_estate": 1000,
               "alternatives": 500, "liquidity": 500}
    prefs = {
        "policy": {}, "tilts": {}, "product": {}, "limits": {}, "geo": {},
        "assetClasses": {
            "equitiesGeo": "Schweiz Fokus",
            "bondsDuration": "Langfristig",
            "bondsHighYield": False,
            "bondsEmerging": False,
        },
        "simulation": {},
    }
    subs = _build_sub_allocations(targets, prefs)
    bonds = _by_class(subs, "Obligationen")
    assert _sum_bps(bonds) == targets["bonds"], (
        f"Bonds-Subs muessen exakt {targets['bonds']} bps summieren, sind {_sum_bps(bonds)}"
    )
    by_label = {s["sub_asset_class"]: int(s["target_weight_bps"]) for s in bonds}
    chf_ig = by_label.get("Obligationen CHF IG", 0)
    global_hedged = by_label.get("Obligationen Global Hedged", 0)
    # Erwartet: CHF IG 5500/9000 von 3000 = 1833; Global Hedged 3500/9000 von 3000 = 1167
    # Toleranz fuer Rundung: +-2 bps
    assert 1830 <= chf_ig <= 1836, f"CHF IG sollte ~1833 sein, ist {chf_ig}"
    assert 1164 <= global_hedged <= 1170, f"Global Hedged sollte ~1167 sein, ist {global_hedged}"


def test_c4_bonds_no_filter_keeps_default_proportions():
    """Sanity ohne Filter: Splits bleiben bei Default-Verhaeltnissen
    5500/3500/500/500."""
    targets = {"equities": 4000, "bonds": 4000, "real_estate": 1000,
               "alternatives": 500, "liquidity": 500}
    prefs = {
        "policy": {}, "tilts": {}, "product": {}, "limits": {}, "geo": {},
        "assetClasses": {
            "bondsDuration": "Langfristig",
            "bondsHighYield": True,
            "bondsEmerging": True,
        },
        "simulation": {},
    }
    subs = _build_sub_allocations(targets, prefs)
    bonds = _by_class(subs, "Obligationen")
    assert _sum_bps(bonds) == targets["bonds"]
    by_label = {s["sub_asset_class"]: int(s["target_weight_bps"]) for s in bonds}
    # 5500/10000 von 4000 = 2200
    assert 2198 <= by_label.get("Obligationen CHF IG", 0) <= 2202
    # 3500/10000 von 4000 = 1400
    assert 1398 <= by_label.get("Obligationen Global Hedged", 0) <= 1402


def test_c4_equity_no_em_proportional():
    """noEm filtert Aktien Schwellenlaender raus. Restliche Splits
    sollen proportional skaliert werden, nicht 'remainder dem letzten'."""
    targets = {"equities": 5000, "bonds": 3000, "real_estate": 1000,
               "alternatives": 500, "liquidity": 500}
    prefs = {
        "policy": {}, "tilts": {}, "product": {}, "limits": {},
        "geo": {"noEm": True},
        "assetClasses": {"equitiesGeo": "Schweiz Fokus", "bondsDuration": "Langfristig"},
        "simulation": {},
    }
    subs = _build_sub_allocations(targets, prefs)
    eq = _by_class(subs, "Aktien")
    assert _sum_bps(eq) == targets["equities"]
    labels = [s["sub_asset_class"] for s in eq]
    assert "Aktien Schwellenlaender" not in labels


def test_c4_subsplits_sum_per_bucket_equals_target():
    """Generelle Invariante: ueber JEDEN Filter-Mix muss die Summe der
    Sub-Allocations je Bucket exakt dem target entsprechen."""
    test_cases = [
        # (prefs_overrides, expected_targets)
        ({"bondsHighYield": False}, "Obligationen"),
        ({"bondsEmerging": False}, "Obligationen"),
        ({"bondsHighYield": False, "bondsEmerging": False}, "Obligationen"),
    ]
    for asset_overrides, bucket in test_cases:
        targets = {"equities": 4500, "bonds": 3500, "real_estate": 500,
                   "alternatives": 1000, "liquidity": 500}
        prefs = {
            "policy": {}, "tilts": {}, "product": {}, "limits": {}, "geo": {},
            "assetClasses": {**asset_overrides, "bondsDuration": "Langfristig"},
            "simulation": {},
        }
        subs = _build_sub_allocations(targets, prefs)
        for asset, bucket_key in (
            ("Aktien", "equities"), ("Obligationen", "bonds"),
            ("Immobilien", "real_estate"), ("Alternative", "alternatives"),
            ("Liquiditaet", "liquidity"),
        ):
            actual = _sum_bps(_by_class(subs, asset))
            expected = targets[bucket_key]
            if expected == 0:
                continue
            assert actual == expected, (
                f"Asset {asset} Bucket-Sum {actual} != target {expected} "
                f"(prefs={asset_overrides})"
            )
