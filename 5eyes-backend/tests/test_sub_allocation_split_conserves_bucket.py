"""SUB-SPLIT-ROUNDING-001 (Assetallocation-Audit 2026-10-14).

``_build_sub_allocations`` splits each bucket into sleeves by rounding every
sleeve in sequence and giving the last one the remainder. For small buckets the
rounded sleeves can already exceed the bucket; the remainder turns negative,
the last sleeve is dropped (``if weight <= 0: continue``) and the bucket keeps
the overshoot. Example: equities 13 bps with three theme tilts ->
6+4+1+1+1+1 = 14 bps. Reachable via manual band overrides in the
deterministic path (incl. the House fallback).

Oracle: bps conservation -- the sleeves of a bucket sum to exactly the bucket
weight, none negative, for EVERY bucket weight 1..10000.
"""
from __future__ import annotations

from collections import defaultdict

import pytest

from services.portfolio_engine_house_matrix import _build_sub_allocations

LABEL = {"equities": "Aktien", "bonds": "Obligationen", "real_estate": "Immobilien",
         "alternatives": "Alternative", "liquidity": "Liquiditaet"}

PREFS = {
    "three_theme_tilts": {
        "assetClasses": {"equitiesGeo": "Schweiz Fokus"},
        "tilts": {"defense": "overweight", "fossil": "overweight", "tobacco": "overweight"},
    },
    "wide_alternatives": {
        "assetClasses": {"altsGold": True, "altsLiquidAlts": True, "altsHedge": True,
                         "altsPe": True, "altsCrypto": True},
    },
    "wide_bonds": {
        "assetClasses": {"bondsInvestmentGrade": True, "bondsHighYield": True, "bondsEmerging": True},
    },
}


def _sums(rows):
    out = defaultdict(int)
    for row in rows:
        assert int(row["target_weight_bps"]) >= 0, row
        out[row["asset_class"]] += int(row["target_weight_bps"])
    return dict(out)


def test_reported_case_small_equity_bucket():
    rows = _build_sub_allocations(
        {"equities": 13, "bonds": 0, "real_estate": 0, "alternatives": 0, "liquidity": 0},
        PREFS["three_theme_tilts"],
    )
    assert _sums(rows) == {"Aktien": 13}


@pytest.mark.parametrize("prefs_key", sorted(PREFS))
@pytest.mark.parametrize("bucket", ["equities", "bonds", "alternatives"])
def test_every_bucket_weight_is_conserved(prefs_key, bucket):
    prefs = PREFS[prefs_key]
    bad = []
    for weight in range(1, 10001):
        targets = {k: 0 for k in LABEL}
        targets[bucket] = weight
        got = _sums(_build_sub_allocations(dict(targets), prefs)).get(LABEL[bucket], 0)
        if got != weight:
            bad.append((weight, got))
    assert not bad, f"{len(bad)} weights not conserved, first: {bad[:5]}"
