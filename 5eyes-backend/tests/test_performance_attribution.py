"""Sprint U-97 (2026-06-06): Tests fuer Brinson-Performance-Attribution.

Pure-Math-Tests fuer compute_brinson_attribution + Integration in
Aggregator-Sektion 25 (performance_attribution).
"""
from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = Path(__file__).resolve().parent
for path in (BACKEND_ROOT, TESTS_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from services.performance_attribution import (
    BUCKET_KEYS,
    AttributionResult,
    BucketAttribution,
    compute_brinson_attribution,
)
from test_optimizer_shadow_mode import session_factory  # noqa: F401


# ---------------------------------------------------------------------------
# Brinson-Math
# ---------------------------------------------------------------------------

def test_bucket_keys_constant():
    assert BUCKET_KEYS == ("equities", "bonds", "real_estate", "alternatives", "liquidity")


def test_identical_portfolio_and_benchmark_yields_zero_effects():
    """Wenn P == B in Weights und Returns -> alle Effekte 0."""
    weights = {"equities": 5000, "bonds": 3000, "real_estate": 1000, "alternatives": 500, "liquidity": 500}
    returns = {"equities": 700, "bonds": 200, "real_estate": 400, "alternatives": 300, "liquidity": 80}
    result = compute_brinson_attribution(
        portfolio_weights_bps=weights,
        benchmark_weights_bps=weights,
        portfolio_returns_bps=returns,
    )
    assert result.total_allocation_effect_bps == 0
    assert result.total_selection_effect_bps == 0
    assert result.total_interaction_effect_bps == 0
    assert result.total_excess_return_bps == 0


def test_more_equities_in_portfolio_yields_positive_allocation_effect():
    """P hat +1000 bps Equity-Tilt vs B. Equities hat hoehere Rendite als
    Liquidity, daher positiver Allocation-Effekt."""
    portfolio = {"equities": 6000, "bonds": 3000, "real_estate": 0, "alternatives": 0, "liquidity": 1000}
    benchmark = {"equities": 5000, "bonds": 3000, "real_estate": 0, "alternatives": 0, "liquidity": 2000}
    returns = {"equities": 700, "bonds": 200, "real_estate": 400, "alternatives": 300, "liquidity": 80}
    result = compute_brinson_attribution(
        portfolio_weights_bps=portfolio,
        benchmark_weights_bps=benchmark,
        portfolio_returns_bps=returns,
    )
    assert result.total_allocation_effect_bps > 0
    # Selection = 0 in 5eyes' forward-looking-Default
    assert result.total_selection_effect_bps == 0
    assert result.total_interaction_effect_bps == 0


def test_selection_effect_non_zero_when_returns_differ():
    """Wenn portfolio_returns != benchmark_returns -> Selection != 0."""
    weights = {"equities": 5000, "bonds": 5000, "real_estate": 0, "alternatives": 0, "liquidity": 0}
    portfolio_r = {"equities": 800, "bonds": 200, "real_estate": 0, "alternatives": 0, "liquidity": 0}
    benchmark_r = {"equities": 700, "bonds": 200, "real_estate": 0, "alternatives": 0, "liquidity": 0}
    result = compute_brinson_attribution(
        portfolio_weights_bps=weights,
        benchmark_weights_bps=weights,
        portfolio_returns_bps=portfolio_r,
        benchmark_returns_bps=benchmark_r,
    )
    # Selection: w_b * (r_p - r_b) = 5000 * (800-700) / 10000 = 50
    assert result.total_selection_effect_bps == 50
    # Allocation = 0 weil Weights gleich
    assert result.total_allocation_effect_bps == 0
    # Interaction = 0 weil (w_p - w_b) = 0
    assert result.total_interaction_effect_bps == 0


def test_total_excess_equals_total_p_minus_total_b():
    portfolio = {"equities": 7000, "bonds": 2000, "real_estate": 500, "alternatives": 200, "liquidity": 300}
    benchmark = {"equities": 5000, "bonds": 3000, "real_estate": 1000, "alternatives": 500, "liquidity": 500}
    returns = {"equities": 700, "bonds": 200, "real_estate": 400, "alternatives": 300, "liquidity": 80}
    result = compute_brinson_attribution(
        portfolio_weights_bps=portfolio,
        benchmark_weights_bps=benchmark,
        portfolio_returns_bps=returns,
    )
    expected_excess = result.total_portfolio_return_bps - result.total_benchmark_return_bps
    assert result.total_excess_return_bps == expected_excess


def test_brinson_decomposition_sums_to_total_excess_when_no_selection():
    """In 5eyes' Default (gleiche Returns) gilt: Allocation == Excess."""
    portfolio = {"equities": 6000, "bonds": 2500, "real_estate": 500, "alternatives": 500, "liquidity": 500}
    benchmark = {"equities": 5000, "bonds": 3000, "real_estate": 1000, "alternatives": 500, "liquidity": 500}
    returns = {"equities": 700, "bonds": 200, "real_estate": 400, "alternatives": 300, "liquidity": 80}
    result = compute_brinson_attribution(
        portfolio_weights_bps=portfolio,
        benchmark_weights_bps=benchmark,
        portfolio_returns_bps=returns,
    )
    # selection + interaction = 0 weil bench_returns = portfolio_returns
    assert result.total_selection_effect_bps == 0
    assert result.total_interaction_effect_bps == 0
    # Allocation = Excess (Identitaet)
    assert result.total_allocation_effect_bps == result.total_excess_return_bps


def test_bucket_breakdown_has_one_entry_per_bucket():
    weights = {"equities": 5000, "bonds": 3000, "real_estate": 1000, "alternatives": 500, "liquidity": 500}
    returns = {"equities": 700, "bonds": 200, "real_estate": 400, "alternatives": 300, "liquidity": 80}
    result = compute_brinson_attribution(
        portfolio_weights_bps=weights,
        benchmark_weights_bps=weights,
        portfolio_returns_bps=returns,
    )
    assert len(result.buckets) == 5
    bucket_keys_found = [b.bucket for b in result.buckets]
    assert bucket_keys_found == list(BUCKET_KEYS)


def test_to_dict_serializable():
    weights = {"equities": 5000, "bonds": 5000, "real_estate": 0, "alternatives": 0, "liquidity": 0}
    returns = {"equities": 700, "bonds": 200, "real_estate": 0, "alternatives": 0, "liquidity": 0}
    result = compute_brinson_attribution(
        portfolio_weights_bps=weights,
        benchmark_weights_bps=weights,
        portfolio_returns_bps=returns,
    )
    d = result.to_dict()
    assert set(d.keys()) >= {
        "buckets",
        "total_portfolio_return_bps",
        "total_benchmark_return_bps",
        "total_excess_return_bps",
        "total_allocation_effect_bps",
        "total_selection_effect_bps",
        "total_interaction_effect_bps",
    }
    # Bucket-Inner-Dict
    first_bucket = d["buckets"][0]
    assert set(first_bucket.keys()) == {
        "bucket",
        "weight_portfolio_bps",
        "weight_benchmark_bps",
        "return_portfolio_bps",
        "return_benchmark_bps",
        "allocation_effect_bps",
        "selection_effect_bps",
        "interaction_effect_bps",
    }


def test_empty_inputs_yield_zero_totals():
    result = compute_brinson_attribution(
        portfolio_weights_bps={},
        benchmark_weights_bps={},
        portfolio_returns_bps={},
    )
    assert result.total_portfolio_return_bps == 0
    assert result.total_benchmark_return_bps == 0
    assert result.total_excess_return_bps == 0


def test_negative_excess_when_portfolio_underweights_winners():
    """P unter-gewichtet Aktien (hoeher rendierender Bucket)."""
    portfolio = {"equities": 3000, "bonds": 6000, "real_estate": 500, "alternatives": 0, "liquidity": 500}
    benchmark = {"equities": 5000, "bonds": 4000, "real_estate": 500, "alternatives": 0, "liquidity": 500}
    returns = {"equities": 700, "bonds": 200, "real_estate": 400, "alternatives": 0, "liquidity": 80}
    result = compute_brinson_attribution(
        portfolio_weights_bps=portfolio,
        benchmark_weights_bps=benchmark,
        portfolio_returns_bps=returns,
    )
    assert result.total_excess_return_bps < 0
    assert result.total_allocation_effect_bps < 0


# ---------------------------------------------------------------------------
# Aggregator-Integration
# ---------------------------------------------------------------------------

def test_aggregator_includes_performance_attribution_key(session_factory):
    """Sektion 25 muss im Aggregator-Output erscheinen."""
    from test_optimizer_shadow_mode import _seed_realistic_mandate
    from services.advisory_report import compute_advisory_report
    from models.mandates import Mandate
    from models.users import User

    advisor_id, _cid, mid, _aid, _gid = _seed_realistic_mandate(session_factory, suffix="u97agg")
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        advisor = s.query(User).filter(User.id == advisor_id).first()
        report = compute_advisory_report(s, mandate, advisor=advisor)
    assert "performance_attribution" in report
    data = report["performance_attribution"]
    # Default-Schluessel auch bei degraded
    assert "method" in data
    assert "benchmark_source" in data
    assert "fidleg_basis" in data
    assert data["method"] == "brinson_fachler_hood_1986"


def test_aggregator_preserves_all_25_sections(session_factory):
    from test_optimizer_shadow_mode import _seed_realistic_mandate
    from services.advisory_report import compute_advisory_report
    from models.mandates import Mandate
    from models.users import User

    advisor_id, _cid, mid, _aid, _gid = _seed_realistic_mandate(session_factory, suffix="u97all")
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        advisor = s.query(User).filter(User.id == advisor_id).first()
        report = compute_advisory_report(s, mandate, advisor=advisor)
    # 5 Schluessel pre-Sektionen + Sektion-Keys: total ~28 (incl mandate_id etc)
    expected_keys = {
        "schema_version", "mandate_id", "generated_at",
        "cover", "disclaimer", "inhaltsverzeichnis", "ausgangslage",
        "positionen", "pruefpunkte", "erkenntnisse",
        "asset_allocation", "risikowaehrungen", "branchen",
        "goal_based_investing", "risikoprofilierung", "building_blocks",
        "statement_pm", "weiteres_vorgehen",
        "beratungsprotokoll", "stress_replay", "conflict_disclosures",
        "suitability_compliance", "methodology_models",
        "recommendation_methodology", "mandate_lock_status",
        "liquidity_cascade", "optimizer_run_history",
        "performance_attribution",
    }
    assert expected_keys.issubset(set(report.keys()))


# ---------------------------------------------------------------------------
# Type-Hints helper
# ---------------------------------------------------------------------------

def test_bucket_attribution_is_frozen():
    """Dataclass ist frozen -> immutable."""
    import pytest
    b = BucketAttribution(
        bucket="equities", weight_portfolio_bps=5000, weight_benchmark_bps=5000,
        return_portfolio_bps=700, return_benchmark_bps=700,
        allocation_effect_bps=0, selection_effect_bps=0, interaction_effect_bps=0,
    )
    with pytest.raises(Exception):
        b.bucket = "bonds"  # type: ignore[misc]
