"""Sprint 2026-06-08 Option C: Goal-Tilt fuer Renditeziele.

User-Feedback 2026-06-08: \"Wieso veraendert sich die Grafik in der SOLL-
Allocation nicht wenn ich das Renditeziel von 2% auf 5% veraendere?\"

Option-C-Loesung: Renditeziel-Target beeinflusst die SAA INNERHALB der
House-Matrix-Bandbreiten (Strategietreue gewahrt, FINMA Art. 6 FIDLEG
konform). Niedriges Target -> Defensiv-Tilt; hohes Target -> Wachstums-Tilt.

# Test-Familien
1. Helper _renditeziel_equity_tilt_bps mit Threshold-Logik
2. Hardness-Filter: nur Primaer-Renditeziele tilten
3. Band-Clipping: Tilt verlaesst nie min/max
4. Multi-Goal-Verhalten: mehrere Renditeziele kumulieren bound
5. Backwards-Compat: ohne Renditeziel keine Aenderung
"""
from __future__ import annotations

from services.portfolio_engine import _renditeziel_equity_tilt_bps


# ===========================================================================
# 1. Helper _renditeziel_equity_tilt_bps — Threshold-Logik
# ===========================================================================


def test_helper_niedriges_target_defensiv_tilt():
    """Target < 250 bps (2.5%) -> negativer Tilt (Aktien reduzieren)."""
    # Equity 5000 bps, room nach unten 4500 bps -> Tilt -150
    tilt = _renditeziel_equity_tilt_bps(
        target_return_bps=200,
        current_equity_bps=5000,
        min_equity_bps=500,
        max_equity_bps=7000,
    )
    assert tilt == -150


def test_helper_mittleres_target_kein_tilt():
    """Target 250-400 bps = Standard-Bereich, kein Tilt."""
    tilt = _renditeziel_equity_tilt_bps(
        target_return_bps=300,
        current_equity_bps=4000,
        min_equity_bps=2500,
        max_equity_bps=5000,
    )
    assert tilt == 0


def test_helper_hohes_target_leichter_wachstums_tilt():
    """Target 400-600 bps -> positiver Tilt +150 bps."""
    tilt = _renditeziel_equity_tilt_bps(
        target_return_bps=500,
        current_equity_bps=4000,
        min_equity_bps=2500,
        max_equity_bps=5000,
    )
    assert tilt == 150


def test_helper_sehr_hohes_target_starker_wachstums_tilt():
    """Target > 600 bps -> positiver Tilt +200 bps."""
    tilt = _renditeziel_equity_tilt_bps(
        target_return_bps=700,
        current_equity_bps=4000,
        min_equity_bps=2500,
        max_equity_bps=5000,
    )
    assert tilt == 200


# ===========================================================================
# 2. Band-Clipping: Tilt respektiert House-Matrix-Bandbreiten
# ===========================================================================


def test_helper_clipping_kein_room_nach_oben():
    """Equity bereits am max → Tilt = 0."""
    tilt = _renditeziel_equity_tilt_bps(
        target_return_bps=700,  # wuerde +200 bps wollen
        current_equity_bps=5000,
        min_equity_bps=2500,
        max_equity_bps=5000,  # voll
    )
    assert tilt == 0


def test_helper_clipping_room_nach_oben_kleiner_als_tilt():
    """Equity hat nur 50 bps room nach oben → Tilt auf 50."""
    tilt = _renditeziel_equity_tilt_bps(
        target_return_bps=700,
        current_equity_bps=4950,
        min_equity_bps=2500,
        max_equity_bps=5000,
    )
    assert tilt == 50


def test_helper_clipping_kein_room_nach_unten():
    """Equity bereits am min → kein Defensiv-Tilt."""
    tilt = _renditeziel_equity_tilt_bps(
        target_return_bps=200,  # wuerde -150 wollen
        current_equity_bps=500,
        min_equity_bps=500,  # bereits am Minimum
        max_equity_bps=2500,
    )
    assert tilt == 0


def test_helper_clipping_room_nach_unten_kleiner():
    """Equity hat nur 100 bps room nach unten → Tilt -100."""
    tilt = _renditeziel_equity_tilt_bps(
        target_return_bps=200,
        current_equity_bps=600,
        min_equity_bps=500,
        max_equity_bps=2500,
    )
    assert tilt == -100


# ===========================================================================
# 3. Edge-Cases
# ===========================================================================


def test_helper_target_null_kein_tilt():
    """target_return_bps=0 → kein Tilt."""
    tilt = _renditeziel_equity_tilt_bps(
        target_return_bps=0,
        current_equity_bps=4000,
        min_equity_bps=2500,
        max_equity_bps=5000,
    )
    assert tilt == 0


def test_helper_target_negativ_kein_tilt():
    """Negative target werden defensiv abgewiesen."""
    tilt = _renditeziel_equity_tilt_bps(
        target_return_bps=-100,
        current_equity_bps=4000,
        min_equity_bps=2500,
        max_equity_bps=5000,
    )
    assert tilt == 0


# ===========================================================================
# 4. Threshold-Boundaries
# ===========================================================================


def test_helper_target_exakt_250_kein_tilt():
    """250 bps ist die untere Grenze des Standard-Bereichs."""
    tilt = _renditeziel_equity_tilt_bps(
        target_return_bps=250,
        current_equity_bps=4000,
        min_equity_bps=2500,
        max_equity_bps=5000,
    )
    assert tilt == 0  # standard, kein Tilt


def test_helper_target_exakt_400_wachstum():
    """400 bps ist die untere Grenze des Wachstums-Bereichs."""
    tilt = _renditeziel_equity_tilt_bps(
        target_return_bps=400,
        current_equity_bps=4000,
        min_equity_bps=2500,
        max_equity_bps=5000,
    )
    assert tilt == 150


def test_helper_target_exakt_600_starker_wachstum():
    """600 bps ist die Grenze zum starken Wachstums-Bereich."""
    tilt = _renditeziel_equity_tilt_bps(
        target_return_bps=600,
        current_equity_bps=4000,
        min_equity_bps=2500,
        max_equity_bps=5000,
    )
    assert tilt == 200


# ===========================================================================
# 5. Integration-Tests via _apply_goal_and_reserve_tilts
# ===========================================================================


def test_integration_hohes_renditeziel_erhoeht_equity():
    """E2E: Renditeziel mit Hardness=Primaer und Target 500 bps erhoeht Equity."""
    from services.portfolio_engine import _apply_goal_and_reserve_tilts
    from types import SimpleNamespace

    targets = {"equities": 4000, "bonds": 4500, "real_estate": 500,
               "alternatives": 300, "liquidity": 200}
    minimums = {"equities": 2500, "bonds": 3500, "real_estate": 0,
                "alternatives": 0, "liquidity": 300}
    maximums = {"equities": 5000, "bonds": 6000, "real_estate": 1500,
                "alternatives": 1000, "liquidity": 2000}
    eq_before = targets["equities"]
    goals = [SimpleNamespace(
        id="g-rendite-prim", label="Rendite-Ziel 5%",
        goal_type="Renditeziel", hardness="Primär",
        target_return_bps=500, target_amount_rappen=None,
        target_wealth_rappen=None, horizon_years=10,
        target_date=None, start_date=None, weight_bps=5000,
        is_ongoing=0, frequency=None, rank=2,
        success_probability_min_x100=None, probability_pct=100,
        pension_pillar=None, value_mode="nominal",
        is_inflation_linked=0, notes=None,
    )]
    reasoning: list[str] = []
    _apply_goal_and_reserve_tilts(
        targets=targets, minimums=minimums, maximums=maximums,
        goals=goals, limits_prefs={}, asset_class_prefs={},
        recurring_net_cashflow_rappen=0,
        recurring_cashflow_projection_series_rappen=[0] * 11,
        advisory_wealth_rappen=1_000_000_00, reasoning=reasoning,
    )
    # Equity sollte um 150 bps gestiegen sein
    assert targets["equities"] == eq_before + 150
    # Bonds entsprechend reduziert
    assert any("Renditeziel" in r and "Aktien" in r for r in reasoning)


def test_integration_niedriges_renditeziel_reduziert_equity():
    """E2E: Renditeziel mit Hardness=Primaer und Target 200 bps senkt Equity."""
    from services.portfolio_engine import _apply_goal_and_reserve_tilts
    from types import SimpleNamespace

    targets = {"equities": 4000, "bonds": 4500, "real_estate": 500,
               "alternatives": 300, "liquidity": 200}
    minimums = {"equities": 2500, "bonds": 3500, "real_estate": 0,
                "alternatives": 0, "liquidity": 300}
    maximums = {"equities": 5000, "bonds": 6000, "real_estate": 1500,
                "alternatives": 1000, "liquidity": 2000}
    eq_before = targets["equities"]
    goals = [SimpleNamespace(
        id="g-rendite-def", label="Rendite-Ziel 2%",
        goal_type="Renditeziel", hardness="Primär",
        target_return_bps=200, target_amount_rappen=None,
        target_wealth_rappen=None, horizon_years=10,
        target_date=None, start_date=None, weight_bps=5000,
        is_ongoing=0, frequency=None, rank=2,
        success_probability_min_x100=None, probability_pct=100,
        pension_pillar=None, value_mode="nominal",
        is_inflation_linked=0, notes=None,
    )]
    reasoning: list[str] = []
    _apply_goal_and_reserve_tilts(
        targets=targets, minimums=minimums, maximums=maximums,
        goals=goals, limits_prefs={}, asset_class_prefs={},
        recurring_net_cashflow_rappen=0,
        recurring_cashflow_projection_series_rappen=[0] * 11,
        advisory_wealth_rappen=1_000_000_00, reasoning=reasoning,
    )
    # Equity um 150 bps gesenkt
    assert targets["equities"] == eq_before - 150


def test_integration_opportunistisches_renditeziel_kein_tilt():
    """ADR: Opportunistische Goals tilten die Allocation NICHT."""
    from services.portfolio_engine import _apply_goal_and_reserve_tilts
    from types import SimpleNamespace

    targets = {"equities": 4000, "bonds": 4500, "real_estate": 500,
               "alternatives": 300, "liquidity": 200}
    minimums = {"equities": 2500, "bonds": 3500, "real_estate": 0,
                "alternatives": 0, "liquidity": 300}
    maximums = {"equities": 5000, "bonds": 6000, "real_estate": 1500,
                "alternatives": 1000, "liquidity": 2000}
    eq_before = targets["equities"]
    goals = [SimpleNamespace(
        id="g-rendite-opp", label="Rendite-Ziel 5%",
        goal_type="Renditeziel", hardness="Opportunistisch",
        target_return_bps=500, target_amount_rappen=None,
        target_wealth_rappen=None, horizon_years=10,
        target_date=None, start_date=None, weight_bps=2000,
        is_ongoing=0, frequency=None, rank=3,
        success_probability_min_x100=None, probability_pct=100,
        pension_pillar=None, value_mode="nominal",
        is_inflation_linked=0, notes=None,
    )]
    reasoning: list[str] = []
    _apply_goal_and_reserve_tilts(
        targets=targets, minimums=minimums, maximums=maximums,
        goals=goals, limits_prefs={}, asset_class_prefs={},
        recurring_net_cashflow_rappen=0,
        recurring_cashflow_projection_series_rappen=[0] * 11,
        advisory_wealth_rappen=1_000_000_00, reasoning=reasoning,
    )
    # Allocation unveraendert
    assert targets["equities"] == eq_before


def test_integration_kein_renditeziel_kein_tilt():
    """Backwards-Compat: ohne Renditeziel keine Aenderung."""
    from services.portfolio_engine import _apply_goal_and_reserve_tilts
    from types import SimpleNamespace

    targets = {"equities": 4000, "bonds": 4500, "real_estate": 500,
               "alternatives": 300, "liquidity": 200}
    minimums = {"equities": 2500, "bonds": 3500, "real_estate": 0,
                "alternatives": 0, "liquidity": 300}
    maximums = {"equities": 5000, "bonds": 6000, "real_estate": 1500,
                "alternatives": 1000, "liquidity": 2000}
    eq_before = targets["equities"]
    goals = [SimpleNamespace(
        id="g-wealth", label="Vermoegen", goal_type="Vermoegensziel",
        hardness="Hart", target_return_bps=None,
        target_amount_rappen=1_000_000_00,
        target_wealth_rappen=1_000_000_00, horizon_years=10,
        target_date=None, start_date=None, weight_bps=5000,
        is_ongoing=0, frequency=None, rank=1,
        success_probability_min_x100=None, probability_pct=100,
        pension_pillar=None, value_mode="nominal",
        is_inflation_linked=0, notes=None,
    )]
    reasoning: list[str] = []
    _apply_goal_and_reserve_tilts(
        targets=targets, minimums=minimums, maximums=maximums,
        goals=goals, limits_prefs={}, asset_class_prefs={},
        recurring_net_cashflow_rappen=0,
        recurring_cashflow_projection_series_rappen=[0] * 11,
        advisory_wealth_rappen=1_000_000_00, reasoning=reasoning,
    )
    # Kein Renditeziel → Equity unveraendert (kein Renditeziel-Tilt)
    # Hinweis: Vermoegensziel hat horizon=10 > 5J → kein Vermoegens-Tilt
    assert targets["equities"] == eq_before
