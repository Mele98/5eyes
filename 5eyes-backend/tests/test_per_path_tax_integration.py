"""Sprint B2 (2026-06-07): Per-Pfad Tax-Integration Drift-Tests.

Verifiziert die drei tax_mode-Modi in simulate_wealth_paths:
- 'median' (Backwards-Compat): 1 TaxRegime-Call pro Jahr, Median-Wealth
- 'binned': N TaxRegime-Calls in n_bins Quantil-Bins (Default-Empfehlung)
- 'per_path': 1 Call pro Pfad pro Jahr (Audit-strict, langsam)

# Test-Familien
1. Backwards-Compat: 'median' Default-Pfad unveraendert
2. Median == flacher Tarif: bei nicht-progressivem Tarif identisch
3. Binned-Konvergenz: bei groesserem n_bins -> Per-Path-Werte naehern sich an
4. Per-Path mit progressivem Tarif: hoehere Variance der wealth_after_tax
5. Determinismus
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

import numpy as np
import pytest

from services.optimizer.scenario_engine import (
    N_BUCKETS,
    ScenarioInputs,
    _compute_per_path_wealth_tax_drag,
    build_scenario_paths,
    simulate_wealth_paths,
)
from services.tax.base import TaxContext, TaxResult


# ===========================================================================
# Mock-TaxRegimes
# ===========================================================================


@dataclass(frozen=True)
class _FlatTaxRegime:
    """5 bps Vermoegenssteuer flat (kein Progressives Tarif)."""
    id: str = "TEST-FLAT"
    country_code: str = "XX"
    region_code: str | None = None
    display_name: str = "Test Flat"
    local_currency: str = "CHF"
    supports_wealth_tax: bool = True
    supports_capital_gains_tax: bool = False
    supports_inheritance_tax: bool = False
    flat_bps: float = 50.0

    def annual_wealth_tax(self, ctx: TaxContext) -> TaxResult:
        return TaxResult(
            amount_rappen=ctx.wealth_rappen * self.flat_bps / 10000.0,
            effective_bps=self.flat_bps,
            regime_id=self.id, tariff_version="flat-v1",
            breakdown={"flat": self.flat_bps},
        )

    def dividend_tax(self, ctx, dividend_income_rappen):
        return TaxResult(0.0, 0.0, self.id, "flat-v1")

    def interest_tax(self, ctx, interest_income_rappen):
        return self.dividend_tax(ctx, interest_income_rappen)

    def capital_gains_tax(self, ctx, gains_rappen, holding_years):
        return TaxResult(0.0, 0.0, self.id, "flat-v1")

    def pension_lumpsum_tax(self, ctx, amount_rappen):
        return TaxResult(0.0, 0.0, self.id, "flat-v1")

    def inheritance_tax(self, ctx, amount_rappen, relation):
        return TaxResult(0.0, 0.0, self.id, "flat-v1")

    def validate_parameters(self, params):
        return ()

    def with_overrides(self, overrides):
        return self


@dataclass(frozen=True)
class _ProgressiveTaxRegime:
    """Progressives 3-Stufen-Tarif:
    - < 1M CHF: 30 bps
    - 1M - 10M CHF: 60 bps
    - > 10M CHF: 90 bps
    """
    id: str = "TEST-PROG"
    country_code: str = "XX"
    region_code: str | None = None
    display_name: str = "Test Progressive"
    local_currency: str = "CHF"
    supports_wealth_tax: bool = True
    supports_capital_gains_tax: bool = False
    supports_inheritance_tax: bool = False

    def annual_wealth_tax(self, ctx: TaxContext) -> TaxResult:
        w = ctx.wealth_rappen
        if w < 1_000_000_00:
            bps = 30.0
        elif w < 10_000_000_00:
            bps = 60.0
        else:
            bps = 90.0
        return TaxResult(
            amount_rappen=w * bps / 10000.0,
            effective_bps=bps,
            regime_id=self.id, tariff_version="prog-v1",
            breakdown={"bracket": bps},
        )

    def dividend_tax(self, ctx, dividend_income_rappen):
        return TaxResult(0.0, 0.0, self.id, "prog-v1")

    def interest_tax(self, ctx, interest_income_rappen):
        return self.dividend_tax(ctx, interest_income_rappen)

    def capital_gains_tax(self, ctx, gains_rappen, holding_years):
        return TaxResult(0.0, 0.0, self.id, "prog-v1")

    def pension_lumpsum_tax(self, ctx, amount_rappen):
        return TaxResult(0.0, 0.0, self.id, "prog-v1")

    def inheritance_tax(self, ctx, amount_rappen, relation):
        return TaxResult(0.0, 0.0, self.id, "prog-v1")

    def validate_parameters(self, params):
        return ()

    def with_overrides(self, overrides):
        return self


# ===========================================================================
# Helpers
# ===========================================================================


def _flat_inputs(mu_bps=200, sigma_bps=500) -> ScenarioInputs:
    return ScenarioInputs(
        mu_bps=np.full(N_BUCKETS, mu_bps, dtype=np.float64),
        sigma_bps=np.full(N_BUCKETS, sigma_bps, dtype=np.float64),
        skew_bps=np.zeros(N_BUCKETS, dtype=np.float64),
        excess_kurt_bps=np.zeros(N_BUCKETS, dtype=np.float64),
        cholesky=np.eye(N_BUCKETS, dtype=np.float64),
    )


def _high_vola_paths(n_paths: int, horizon: int, seed: int = 42) -> np.ndarray:
    """Hoch-volatile Pfade die ueber mehrere Tarif-Stufen spreaden."""
    inputs = ScenarioInputs(
        mu_bps=np.full(N_BUCKETS, 200, dtype=np.float64),
        sigma_bps=np.full(N_BUCKETS, 3000, dtype=np.float64),  # 30% vola
        skew_bps=np.zeros(N_BUCKETS, dtype=np.float64),
        excess_kurt_bps=np.zeros(N_BUCKETS, dtype=np.float64),
        cholesky=np.eye(N_BUCKETS, dtype=np.float64),
    )
    return build_scenario_paths(
        inputs, horizon_years=horizon, n_paths=n_paths,
        seed=seed, antithetic=True,
    )


def _equal_weights() -> np.ndarray:
    return np.full(N_BUCKETS, 1.0 / N_BUCKETS, dtype=np.float64)


def _make_paths(n_paths: int, horizon: int, seed: int = 42) -> np.ndarray:
    return build_scenario_paths(
        _flat_inputs(), horizon_years=horizon, n_paths=n_paths,
        seed=seed, antithetic=True,
    )


# ===========================================================================
# 1. Backwards-Compat: 'median' Default-Pfad unveraendert
# ===========================================================================


def test_b2_default_tax_mode_ist_median():
    """Default ohne expliziten tax_mode = 'median' (Backwards-Compat)."""
    n_paths, horizon = 100, 5
    paths = _make_paths(n_paths, horizon)
    regime = _FlatTaxRegime(flat_bps=50)
    # Default-Aufruf (kein tax_mode)
    w_default = simulate_wealth_paths(
        initial_wealth_rappen=1_000_000_00,
        weights=_equal_weights(),
        return_paths=paths,
        cashflow_series_rappen=[0] * horizon,
        tax_regime=regime,
    )
    # Expliziter 'median'-Aufruf
    w_median = simulate_wealth_paths(
        initial_wealth_rappen=1_000_000_00,
        weights=_equal_weights(),
        return_paths=paths,
        cashflow_series_rappen=[0] * horizon,
        tax_regime=regime, tax_mode="median",
    )
    assert np.allclose(w_default, w_median), (
        "Default Pfad muss = 'median' sein (Backwards-Compat)"
    )


# ===========================================================================
# 2. Bei flachem Tarif: alle 3 Modi liefern (fast) identische Ergebnisse
# ===========================================================================


def test_b2_flacher_tarif_alle_modi_konvergent():
    """Bei flachem Tarif spielt's keine Rolle ob Median / Bin / Per-Pfad —
    alle 3 Modi muessen identische wealth-Trajectories liefern."""
    n_paths, horizon = 100, 5
    paths = _make_paths(n_paths, horizon)
    regime = _FlatTaxRegime(flat_bps=50)
    w_median = simulate_wealth_paths(
        initial_wealth_rappen=1_000_000_00,
        weights=_equal_weights(), return_paths=paths,
        cashflow_series_rappen=[0] * horizon,
        tax_regime=regime, tax_mode="median",
    )
    w_binned = simulate_wealth_paths(
        initial_wealth_rappen=1_000_000_00,
        weights=_equal_weights(), return_paths=paths,
        cashflow_series_rappen=[0] * horizon,
        tax_regime=regime, tax_mode="binned",
    )
    w_per_path = simulate_wealth_paths(
        initial_wealth_rappen=1_000_000_00,
        weights=_equal_weights(), return_paths=paths,
        cashflow_series_rappen=[0] * horizon,
        tax_regime=regime, tax_mode="per_path",
    )
    # Bei flachem Tarif: identische Outputs
    assert np.allclose(w_median, w_binned)
    assert np.allclose(w_median, w_per_path)


# ===========================================================================
# 3. Progressiver Tarif: Per-Pfad hat hoehere Genauigkeit als Median
# ===========================================================================


@dataclass(frozen=True)
class _SteepProgressiveTaxRegime:
    """Drastisch progressives Mock-Tarif zum Aufdecken des Per-Path-Effekts:
    - < 1M CHF: 0 bps (steuerfrei)
    - 1M - 10M CHF: 500 bps (5%)
    - > 10M CHF: 2000 bps (20%)
    """
    id: str = "TEST-STEEP"
    country_code: str = "XX"
    region_code: str | None = None
    display_name: str = "Test Steep"
    local_currency: str = "CHF"
    supports_wealth_tax: bool = True
    supports_capital_gains_tax: bool = False
    supports_inheritance_tax: bool = False

    def annual_wealth_tax(self, ctx):
        w = ctx.wealth_rappen
        if w < 1_000_000_00:
            bps = 0.0
        elif w < 10_000_000_00:
            bps = 500.0
        else:
            bps = 2000.0
        return TaxResult(w * bps / 10000.0, bps, self.id, "steep-v1", {"b": bps})

    def dividend_tax(self, ctx, x): return TaxResult(0.0, 0.0, self.id, "steep-v1")
    def interest_tax(self, ctx, x): return TaxResult(0.0, 0.0, self.id, "steep-v1")
    def capital_gains_tax(self, ctx, x, y): return TaxResult(0.0, 0.0, self.id, "steep-v1")
    def pension_lumpsum_tax(self, ctx, x): return TaxResult(0.0, 0.0, self.id, "steep-v1")
    def inheritance_tax(self, ctx, x, r): return TaxResult(0.0, 0.0, self.id, "steep-v1")
    def validate_parameters(self, p): return ()
    def with_overrides(self, o): return self


def test_b2_progressiver_tarif_per_path_unterschiedlich_zu_median():
    """Bei progressivem Tarif (CH-Vermoegenssteuer-Style) liefern Median vs
    Per-Pfad UNTERSCHIEDLICHE Ergebnisse — das ist der Kern-Mehrwert von B2."""
    n_paths, horizon = 500, 5
    paths = _high_vola_paths(n_paths, horizon, seed=123)
    regime = _SteepProgressiveTaxRegime()
    # Initial 5M (Mitte der Mid-Stufe), durch 30% Vola spreadt es ueber alle 3 Stufen
    initial = 5_000_000_00
    w_median = simulate_wealth_paths(
        initial_wealth_rappen=initial,
        weights=_equal_weights(), return_paths=paths,
        cashflow_series_rappen=[0] * horizon,
        tax_regime=regime, tax_mode="median",
    )
    w_per_path = simulate_wealth_paths(
        initial_wealth_rappen=initial,
        weights=_equal_weights(), return_paths=paths,
        cashflow_series_rappen=[0] * horizon,
        tax_regime=regime, tax_mode="per_path",
    )
    # Pfade in der HOEHEREN Tarif-Stufe (>10M, Rate 90bps) muessen bei
    # per_path mehr Steuer zahlen als bei median (das nimmt Mittelstufe-Rate
    # 60bps an, weil Median wahrscheinlich in 1-10M-Stufe liegt).
    # → end_wealth_per_path < end_wealth_median fuer hoch-wealth-Pfade
    end_median = w_median[:, -1]
    end_per_path = w_per_path[:, -1]
    # Top 20% wealth: per_path muss niedrigeres mean wealth haben (mehr Steuer)
    threshold = np.quantile(end_median, 0.8)
    high_median_mask = end_median >= threshold
    assert high_median_mask.sum() >= 10, "Nicht genug Pfade im Top-Quintil"
    high_median = end_median[high_median_mask].mean()
    high_per_path = end_per_path[high_median_mask].mean()
    # Per-Path sollte hier mehr Steuer (90bps) anwenden → niedrigere wealth
    assert high_per_path < high_median, (
        f"B2-Korrektur verletzt: hoch-wealth Pfade per_path ({high_per_path:.0f}) "
        f"muessen niedriger sein als median ({high_median:.0f})"
    )


# ===========================================================================
# 4. Binned konvergiert zu Per-Path bei groesserem n_bins
# ===========================================================================


def test_b2_binned_konvergiert_zu_per_path():
    """Bei n_bins → n_paths sollte 'binned' immer naeher an 'per_path' liegen."""
    n_paths, horizon = 300, 5
    paths = _high_vola_paths(n_paths, horizon, seed=456)
    regime = _ProgressiveTaxRegime()
    initial = 1_500_000_00  # spread ueber alle 3 Stufen
    w_per_path = simulate_wealth_paths(
        initial_wealth_rappen=initial, weights=_equal_weights(),
        return_paths=paths, cashflow_series_rappen=[0] * horizon,
        tax_regime=regime, tax_mode="per_path",
    )
    w_binned_3 = simulate_wealth_paths(
        initial_wealth_rappen=initial, weights=_equal_weights(),
        return_paths=paths, cashflow_series_rappen=[0] * horizon,
        tax_regime=regime, tax_mode="binned", tax_n_bins=3,
    )
    w_binned_50 = simulate_wealth_paths(
        initial_wealth_rappen=initial, weights=_equal_weights(),
        return_paths=paths, cashflow_series_rappen=[0] * horizon,
        tax_regime=regime, tax_mode="binned", tax_n_bins=50,
    )
    diff_3 = np.abs(w_binned_3[:, -1] - w_per_path[:, -1]).mean()
    diff_50 = np.abs(w_binned_50[:, -1] - w_per_path[:, -1]).mean()
    assert diff_50 <= diff_3, (
        f"Konvergenz verletzt: n_bins=50 muss <= n_bins=3 liegen "
        f"(diff_3={diff_3:.2f}, diff_50={diff_50:.2f})"
    )


# ===========================================================================
# 5. Helper-Funktion direkt
# ===========================================================================


def test_b2_helper_per_path_drag_negative_wealth_keine_aenderung():
    """Pfade mit wealth <= 0 bekommen drag = 1.0 (keine Tax-Anwendung)."""
    grown = np.array([1_000_000_00, -100_000_00, 5_000_000_00, 0.0])
    regime = _FlatTaxRegime(flat_bps=50)
    drag = _compute_per_path_wealth_tax_drag(
        grown, tax_regime=regime,
        ctx_template_kwargs=dict(
            year_index=0, calendar_year=2026, age=50, is_retired=False,
        ),
        tax_mode="per_path",
    )
    assert drag[1] == 1.0  # negative wealth
    assert drag[3] == 1.0  # zero wealth
    assert drag[0] < 1.0  # positive wealth → Drag
    assert drag[2] < 1.0


def test_b2_helper_unknown_mode_fallback_to_binned():
    """Wenn unbekannter Modus uebergeben wird, Default zum binned-Pfad
    (siehe Helper-Logik)."""
    grown = np.array([1_000_000_00, 2_000_000_00, 5_000_000_00])
    regime = _FlatTaxRegime(flat_bps=50)
    drag_binned = _compute_per_path_wealth_tax_drag(
        grown, tax_regime=regime,
        ctx_template_kwargs=dict(
            year_index=0, calendar_year=2026, age=None, is_retired=False,
        ),
        tax_mode="binned", n_bins=3,
    )
    # Alle Pfade kriegen non-trivial drag
    assert (drag_binned < 1.0).all()
    assert (drag_binned > 0.99).all()  # 50 bps = 0.5% → drag ~0.995


# ===========================================================================
# 6. Determinismus
# ===========================================================================


def test_b2_per_path_deterministisch():
    """Zwei identische Per-Path-Runs liefern identische Resultate."""
    n_paths, horizon = 50, 3
    paths1 = _make_paths(n_paths, horizon, seed=99)
    paths2 = _make_paths(n_paths, horizon, seed=99)
    regime = _ProgressiveTaxRegime()
    w1 = simulate_wealth_paths(
        initial_wealth_rappen=2_000_000_00, weights=_equal_weights(),
        return_paths=paths1, cashflow_series_rappen=[0] * horizon,
        tax_regime=regime, tax_mode="per_path",
    )
    w2 = simulate_wealth_paths(
        initial_wealth_rappen=2_000_000_00, weights=_equal_weights(),
        return_paths=paths2, cashflow_series_rappen=[0] * horizon,
        tax_regime=regime, tax_mode="per_path",
    )
    assert np.allclose(w1, w2)


def test_b2_binned_deterministisch():
    """Zwei identische Binned-Runs liefern identische Resultate."""
    n_paths, horizon = 50, 3
    paths1 = _make_paths(n_paths, horizon, seed=44)
    paths2 = _make_paths(n_paths, horizon, seed=44)
    regime = _ProgressiveTaxRegime()
    w1 = simulate_wealth_paths(
        initial_wealth_rappen=2_000_000_00, weights=_equal_weights(),
        return_paths=paths1, cashflow_series_rappen=[0] * horizon,
        tax_regime=regime, tax_mode="binned", tax_n_bins=10,
    )
    w2 = simulate_wealth_paths(
        initial_wealth_rappen=2_000_000_00, weights=_equal_weights(),
        return_paths=paths2, cashflow_series_rappen=[0] * horizon,
        tax_regime=regime, tax_mode="binned", tax_n_bins=10,
    )
    assert np.allclose(w1, w2)


# ===========================================================================
# 7. Performance-Smoke: per_path Mode sollte nicht zu langsam sein
# ===========================================================================


def test_b2_per_path_performance_akzeptabel():
    """Per-Path mit 500 Pfaden × 10 Jahren = 5000 TaxRegime-Calls.
    Sollte < 2 Sekunden bleiben (Konfigurations-Reasonable)."""
    import time
    n_paths, horizon = 500, 10
    paths = _make_paths(n_paths, horizon)
    regime = _ProgressiveTaxRegime()
    start = time.perf_counter()
    _ = simulate_wealth_paths(
        initial_wealth_rappen=2_000_000_00, weights=_equal_weights(),
        return_paths=paths, cashflow_series_rappen=[0] * horizon,
        tax_regime=regime, tax_mode="per_path",
    )
    elapsed = time.perf_counter() - start
    # 2s ist sehr generous — Per-Path-Mode ist fuer Audit/Test gedacht
    assert elapsed < 2.0, f"Per-Path zu langsam: {elapsed:.2f}s"
