"""Z4 - C3: Weighted bucket metrics.

Vor dem Fix:
  _asset_class_expected_metrics() berechnete Bucket-Returns als CMA
  bucket fields (z.B. (equity_ch + equity_intl) / 2), aber ueberschrieb
  diese dann mit dem UNGEWICHTETEN Durchschnitt aller Sub-Asset-Class-
  Assumptions im sub_asset_class_assumptions_json. Dadurch:
  1. Tatsaechliche Sub-Allocation-Gewichte (target_weight_bps) wurden
     ignoriert.
  2. Hinzufuegen einer einzigen Sub-Asset-Class verzerrte das Mittel.

Nach dem Fix:
  _asset_class_expected_metrics() liefert nur noch CMA-bucket-Defaults.
  Neue Funktion _weighted_bucket_metrics(cma, sub_allocations) berechnet
  pro Bucket gewichteten Return/Vol aus den tatsaechlichen
  Sub-Allocation-Gewichten. _expected_metrics, _build_simulation_payload,
  _run_allocation_monte_carlo nutzen diese Funktion.
"""
from __future__ import annotations
import sys
import json
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

from models.allocation import CapitalMarketAssumption


def _make_cma(**overrides):
    """Produziert eine CMA mit Sub-Asset-Class-Annahmen (Aktien CH 5%, Aktien
    Welt 7%, Aktien EM 9%) so dass weighted vs ungewichtet sichtbar abweicht."""
    sub_assumptions = {
        "Aktien Schweiz": {"asset_class": "Aktien", "expected_return_bps": 500, "expected_volatility_bps": 1450},
        "Aktien Global": {"asset_class": "Aktien", "expected_return_bps": 700, "expected_volatility_bps": 1500},
        "Aktien Schwellenlaender": {"asset_class": "Aktien", "expected_return_bps": 900, "expected_volatility_bps": 1900},
        "Obligationen CHF IG": {"asset_class": "Obligationen", "expected_return_bps": 180, "expected_volatility_bps": 350},
        "Obligationen Global Hedged": {"asset_class": "Obligationen", "expected_return_bps": 220, "expected_volatility_bps": 450},
        "Obligationen High Yield": {"asset_class": "Obligationen", "expected_return_bps": 420, "expected_volatility_bps": 950},
    }
    base = dict(
        id="cma-z4", assumption_set_name="Test", version=1, valid_from="2026-01-01",
        is_current=1,
        bonds_chf_ig_return_bps=180, bonds_chf_ig_vol_bps=350,
        bonds_fx_hedged_return_bps=220, bonds_fx_hedged_vol_bps=450,
        equity_ch_return_bps=500, equity_ch_vol_bps=1450,
        equity_intl_return_bps=700, equity_intl_vol_bps=1500,
        real_estate_ch_return_bps=330, real_estate_ch_vol_bps=820,
        alternatives_gold_return_bps=300, alternatives_gold_vol_bps=1200,
        liquidity_return_bps=80, liquidity_vol_bps=15,
        sub_asset_class_assumptions_json=json.dumps(sub_assumptions),
        created_by="advisor-1",
        created_at="2026-01-01T00:00:00Z", updated_at="2026-01-01T00:00:00Z",
    )
    base.update(overrides)
    return CapitalMarketAssumption(**base)


# ============================================================================
# C3 - _asset_class_expected_metrics liefert reine CMA-Defaults
# ============================================================================

def test_c3_asset_class_metrics_returns_pure_cma_defaults():
    """Nach Fix darf _asset_class_expected_metrics NICHT mehr durch
    Sub-Annahmen modifiziert werden. Equity bucket bleibt
    (500 + 700) / 2 = 600, NICHT (500+700+900)/3 = 700."""
    from services.portfolio_engine import _asset_class_expected_metrics
    cma = _make_cma()
    returns, vols = _asset_class_expected_metrics(cma)
    # (equity_ch + equity_intl) / 2 = (500 + 700) / 2 = 600
    assert returns["equities"] == 600, f"Expected 600 (CMA-Default), got {returns['equities']}"
    # (bonds_chf_ig + bonds_fx_hedged) / 2 = (180 + 220) / 2 = 200
    assert returns["bonds"] == 200, f"Expected 200, got {returns['bonds']}"


# ============================================================================
# C3 - _weighted_bucket_metrics(cma, sub_allocations) bei tatsaechlichen Gewichten
# ============================================================================

def test_c3_weighted_bucket_metrics_uses_sub_allocation_weights():
    """Bei sub_allocations 50% CH (500), 50% Global (700) → 600.
    Bei 30% CH, 30% Global, 40% EM → 0.3*500 + 0.3*700 + 0.4*900 = 720."""
    from services.portfolio_engine import _weighted_bucket_metrics
    cma = _make_cma()
    # Szenario 1: 50/50 CH+Global
    subs1 = [
        {"asset_class": "Aktien", "sub_asset_class": "Aktien Schweiz", "target_weight_bps": 5000, "rationale": ""},
        {"asset_class": "Aktien", "sub_asset_class": "Aktien Global", "target_weight_bps": 5000, "rationale": ""},
    ]
    returns1, _ = _weighted_bucket_metrics(cma, subs1)
    assert 595 <= returns1["equities"] <= 605, (
        f"50/50 CH+Global expected ~600, got {returns1['equities']}"
    )
    # Szenario 2: 30/30/40 mit EM
    subs2 = [
        {"asset_class": "Aktien", "sub_asset_class": "Aktien Schweiz", "target_weight_bps": 3000, "rationale": ""},
        {"asset_class": "Aktien", "sub_asset_class": "Aktien Global", "target_weight_bps": 3000, "rationale": ""},
        {"asset_class": "Aktien", "sub_asset_class": "Aktien Schwellenlaender", "target_weight_bps": 4000, "rationale": ""},
    ]
    returns2, _ = _weighted_bucket_metrics(cma, subs2)
    # 0.3*500 + 0.3*700 + 0.4*900 = 150+210+360 = 720
    assert 715 <= returns2["equities"] <= 725, (
        f"30/30/40 expected ~720, got {returns2['equities']}"
    )
    # Szenario 2 muss HOEHER sein als Szenario 1 (EM-Tilt)
    assert returns2["equities"] > returns1["equities"]


def test_c3_weighted_bucket_metrics_falls_back_to_cma_without_sub_allocations():
    """Ohne sub_allocations -> reiner CMA bucket field default."""
    from services.portfolio_engine import _weighted_bucket_metrics
    cma = _make_cma()
    returns, _ = _weighted_bucket_metrics(cma, [])
    assert returns["equities"] == 600  # = _asset_class_expected_metrics result
    assert returns["bonds"] == 200


def test_c3_weighted_bucket_metrics_bonds_high_yield_tilt():
    """Bonds: 80% CHF IG (180), 20% HY (420) -> 0.8*180 + 0.2*420 = 228."""
    from services.portfolio_engine import _weighted_bucket_metrics
    cma = _make_cma()
    subs = [
        {"asset_class": "Obligationen", "sub_asset_class": "Obligationen CHF IG", "target_weight_bps": 8000, "rationale": ""},
        {"asset_class": "Obligationen", "sub_asset_class": "Obligationen High Yield", "target_weight_bps": 2000, "rationale": ""},
    ]
    returns, _ = _weighted_bucket_metrics(cma, subs)
    # 0.8*180 + 0.2*420 = 144 + 84 = 228
    assert 225 <= returns["bonds"] <= 231, (
        f"80% IG / 20% HY expected ~228, got {returns['bonds']}"
    )


# ============================================================================
# C3 - _expected_metrics fuehrt sub_allocations weiter
# ============================================================================

def test_c3_expected_metrics_uses_weighted_when_sub_allocations_given():
    """_expected_metrics(targets, cma, sub_allocations) muss die gewichteten
    Bucket-Returns nutzen. Bei reiner Aktien-Allokation 100% mit EM-Tilt
    ist expected_return hoeher als ohne Tilt."""
    from services.portfolio_engine import _expected_metrics
    cma = _make_cma()
    targets = {"equities": 10000, "bonds": 0, "real_estate": 0, "alternatives": 0, "liquidity": 0}
    # Ohne Sub-Allocations: CMA Equity Default = 600
    metrics_default = _expected_metrics(targets, cma)
    # Mit EM-tilt: hoeher
    subs = [
        {"asset_class": "Aktien", "sub_asset_class": "Aktien Schwellenlaender", "target_weight_bps": 10000, "rationale": ""},
    ]
    metrics_em = _expected_metrics(targets, cma, sub_allocations=subs)
    assert metrics_em["expected_return_bps"] > metrics_default["expected_return_bps"]
    assert metrics_em["expected_return_bps"] == 900  # exakt EM
