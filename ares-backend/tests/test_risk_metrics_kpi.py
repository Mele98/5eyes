"""Sprint U-96 (2026-06-05): Tests fuer Sortino/Calmar/Information-Ratio.

Pure-Math-Tests + Integration in _expected_metrics-Dict.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = Path(__file__).resolve().parent
for path in (BACKEND_ROOT, TESTS_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from services.risk_metrics_kpi import (
    compute_calmar_ratio_x100,
    compute_extended_risk_metrics,
    compute_information_ratio_x100,
    compute_sortino_ratio_x100,
)


# ---------------------------------------------------------------------------
# Sortino
# ---------------------------------------------------------------------------

def test_sortino_zero_vol_returns_zero():
    assert compute_sortino_ratio_x100(return_bps=500, vol_bps=0, risk_free_bps=80) == 0


def test_sortino_negative_vol_returns_zero():
    assert compute_sortino_ratio_x100(return_bps=500, vol_bps=-100, risk_free_bps=80) == 0


def test_sortino_normal_case_higher_than_sharpe():
    """Sortino sollte hoeher sein als Sharpe (downside_vol < vol)."""
    return_bps, vol_bps, rf = 700, 1000, 100
    sortino = compute_sortino_ratio_x100(return_bps, vol_bps, rf)
    sharpe_implied = ((return_bps - rf) / vol_bps) * 100
    assert sortino > sharpe_implied


def test_sortino_exact_gaussian_factor():
    """Sortino = (return - rf) / (vol/sqrt(2)) * 100."""
    return_bps, vol_bps, rf = 600, 1200, 100
    expected = ((return_bps - rf) / (vol_bps / math.sqrt(2))) * 100
    actual = compute_sortino_ratio_x100(return_bps, vol_bps, rf)
    assert actual == int(round(expected))


def test_sortino_custom_downside_factor():
    """Custom factor=1.0 -> Sortino == Sharpe."""
    return_bps, vol_bps, rf = 600, 1200, 100
    sharpe_x100 = int(round(((return_bps - rf) / vol_bps) * 100))
    custom = compute_sortino_ratio_x100(
        return_bps, vol_bps, rf, downside_factor=1.0,
    )
    assert custom == sharpe_x100


def test_sortino_negative_excess_return_yields_negative():
    """Return < risk_free -> negative Sortino."""
    out = compute_sortino_ratio_x100(return_bps=50, vol_bps=1000, risk_free_bps=200)
    assert out < 0


# ---------------------------------------------------------------------------
# Calmar
# ---------------------------------------------------------------------------

def test_calmar_zero_drawdown_returns_zero():
    assert compute_calmar_ratio_x100(annual_return_bps=600, expected_max_drawdown_bps=0) == 0


def test_calmar_negative_drawdown_returns_zero():
    assert compute_calmar_ratio_x100(annual_return_bps=600, expected_max_drawdown_bps=-100) == 0


def test_calmar_with_explicit_drawdown():
    """Calmar = return/dd * 100."""
    out = compute_calmar_ratio_x100(annual_return_bps=600, expected_max_drawdown_bps=2000)
    assert out == int(round((600 / 2000) * 100))


def test_calmar_estimates_drawdown_from_vol_when_none():
    """Wenn dd=None und vol gegeben -> Schaetzung 2*vol*sqrt(ln(T)/2)."""
    return_bps, vol_bps, T = 600, 1000, 10
    expected_dd = 2 * vol_bps * math.sqrt(math.log(T) / 2)
    expected_calmar = int(round((return_bps / expected_dd) * 100))
    actual = compute_calmar_ratio_x100(
        annual_return_bps=return_bps,
        expected_max_drawdown_bps=None,
        vol_bps=vol_bps,
        horizon_years=T,
    )
    assert actual == expected_calmar


def test_calmar_no_dd_no_vol_returns_zero():
    out = compute_calmar_ratio_x100(
        annual_return_bps=600, expected_max_drawdown_bps=None, vol_bps=None,
    )
    assert out == 0


def test_calmar_short_horizon_clamped_to_horizon_2():
    """Kontrollrunde 2026-09-21: horizon_years < 2 wird auf 2 geklemmt (statt
    einer eigenen 2x-Heuristik), damit sich horizon=1 und horizon=2 am Rand
    treffen -- siehe test_calmar_drawdown_estimate_monotonic_in_horizon."""
    return_bps, vol_bps = 600, 1000
    out_1y = compute_calmar_ratio_x100(
        annual_return_bps=return_bps, expected_max_drawdown_bps=None,
        vol_bps=vol_bps, horizon_years=1,
    )
    out_2y = compute_calmar_ratio_x100(
        annual_return_bps=return_bps, expected_max_drawdown_bps=None,
        vol_bps=vol_bps, horizon_years=2,
    )
    assert out_1y == out_2y
    expected_dd = 2 * vol_bps * math.sqrt(math.log(2) / 2)
    expected_calmar = int(round((return_bps / expected_dd) * 100))
    assert out_1y == expected_calmar


def test_calmar_drawdown_estimate_monotonic_in_horizon():
    """BUG (vor Fix): die flache 2x-Heuristik fuer horizon<2 lieferte einen
    GROESSEREN Drawdown (also KLEINEREN Calmar) als horizon=2-7 -- der
    geschaetzte Drawdown sank beim Uebergang 1->2 Jahre, obwohl ein
    laengerer Horizont nie einen kleineren erwarteten Drawdown ergeben darf
    (Modell-Praemisse: mehr Zeit = mehr Raum fuer eine Brownsche Bewegung
    zum Wandern). Calmar = return/dd, also muss Calmar mit steigendem
    Horizont monoton FALLEN (oder gleich bleiben), nie steigen."""
    return_bps, vol_bps = 600, 1000
    values = [
        compute_calmar_ratio_x100(
            annual_return_bps=return_bps, expected_max_drawdown_bps=None,
            vol_bps=vol_bps, horizon_years=h,
        )
        for h in (1, 2, 3, 5, 7, 10)
    ]
    for earlier, later in zip(values, values[1:]):
        assert later <= earlier, values


# ---------------------------------------------------------------------------
# Information-Ratio
# ---------------------------------------------------------------------------

def test_information_ratio_zero_tracking_error_returns_zero():
    assert compute_information_ratio_x100(
        portfolio_return_bps=700, benchmark_return_bps=500, tracking_error_vol_bps=0,
    ) == 0


def test_information_ratio_positive_when_outperformer():
    out = compute_information_ratio_x100(
        portfolio_return_bps=700, benchmark_return_bps=500, tracking_error_vol_bps=200,
    )
    assert out > 0
    assert out == int(round((200 / 200) * 100))


def test_information_ratio_negative_when_underperformer():
    out = compute_information_ratio_x100(
        portfolio_return_bps=400, benchmark_return_bps=500, tracking_error_vol_bps=200,
    )
    assert out < 0


def test_information_ratio_with_risk_free_equals_sharpe():
    """Wenn Benchmark = Risk-Free + TE = vol -> IR == Sharpe."""
    return_bps, vol_bps, rf = 600, 1200, 100
    sharpe_x100 = int(round(((return_bps - rf) / vol_bps) * 100))
    ir = compute_information_ratio_x100(return_bps, rf, vol_bps)
    assert ir == sharpe_x100


# ---------------------------------------------------------------------------
# Kontrollrunde 2026-09-21: "nicht berechenbar"-Sentinel (0) durfte nicht mit
# einem echt berechneten, sehr kleinen Ratio kollidieren.
# ---------------------------------------------------------------------------

def test_information_ratio_small_positive_value_not_confused_with_not_computable():
    """BUG (vor Fix): wahre IR = 1/200 = 0.005 -> x100 = 0.5, int(round(0.5))
    ist 0 (Python rundet 0.5 per Banker's-Rounding ab) -- kollidierte mit der
    0-Sentinel fuer 'nicht berechenbar', obwohl der Wert echt berechnet ist."""
    out = compute_information_ratio_x100(
        portfolio_return_bps=101, benchmark_return_bps=100, tracking_error_vol_bps=200,
    )
    assert out != 0
    assert out == 1


def test_information_ratio_small_negative_value_not_confused_with_not_computable():
    out = compute_information_ratio_x100(
        portfolio_return_bps=99, benchmark_return_bps=100, tracking_error_vol_bps=200,
    )
    assert out != 0
    assert out == -1


def test_information_ratio_exact_zero_stays_zero():
    """Kein False-Positive: ein ECHT exaktes 0 (Portfolio == Benchmark)
    bleibt 0 -- nur ein von 0 verschiedener Wert wird auf +-1 angehoben."""
    out = compute_information_ratio_x100(
        portfolio_return_bps=100, benchmark_return_bps=100, tracking_error_vol_bps=200,
    )
    assert out == 0


def test_sortino_small_value_not_confused_with_not_computable():
    """Konservatives/Sicherheits-Profil: return_bps sehr nah an risk_free_bps
    -> vorher faelschlich 0 ('—' im Aggregator) statt eines echten, kleinen
    Sortino-Werts."""
    out = compute_sortino_ratio_x100(return_bps=101, vol_bps=283, risk_free_bps=100)
    assert out != 0


def test_calmar_small_value_not_confused_with_not_computable():
    out = compute_calmar_ratio_x100(
        annual_return_bps=1, expected_max_drawdown_bps=200,
    )
    assert out != 0
    assert out == 1


# ---------------------------------------------------------------------------
# Konsolidierter Helper
# ---------------------------------------------------------------------------

def test_extended_metrics_returns_3_keys():
    out = compute_extended_risk_metrics(return_bps=600, vol_bps=1200, risk_free_bps=100)
    assert set(out.keys()) == {"sortino_ratio_x100", "calmar_ratio_x100", "information_ratio_x100"}


def test_extended_metrics_all_ints():
    out = compute_extended_risk_metrics(return_bps=600, vol_bps=1200, risk_free_bps=100)
    for v in out.values():
        assert isinstance(v, int)


def test_extended_metrics_zero_vol_yields_zeros():
    out = compute_extended_risk_metrics(return_bps=600, vol_bps=0, risk_free_bps=100)
    assert out["sortino_ratio_x100"] == 0
    assert out["calmar_ratio_x100"] == 0
    assert out["information_ratio_x100"] == 0


def test_extended_metrics_passes_explicit_drawdown():
    out = compute_extended_risk_metrics(
        return_bps=600, vol_bps=1200, risk_free_bps=100,
        expected_max_drawdown_bps=3000,
    )
    assert out["calmar_ratio_x100"] == int(round((600 / 3000) * 100))


# ---------------------------------------------------------------------------
# Integration in _expected_metrics
# ---------------------------------------------------------------------------

def test_expected_metrics_dict_includes_3_new_keys():
    """_expected_metrics muss die neuen Keys liefern (auch wenn 0)."""
    import services.portfolio_engine as pe
    from types import SimpleNamespace
    cma = SimpleNamespace(
        liquidity_return_bps=80,
        equity_ch_return_bps=620, equity_ch_vol_bps=1450,
        equity_intl_return_bps=620, equity_intl_vol_bps=1450,
        equity_em_return_bps=620, equity_em_vol_bps=1450,
        bonds_chf_ig_return_bps=200, bonds_chf_ig_vol_bps=400,
        bonds_fx_hedged_return_bps=200, bonds_fx_hedged_vol_bps=400,
        bonds_hy_return_bps=200, bonds_hy_vol_bps=400,
        real_estate_ch_return_bps=400, real_estate_ch_vol_bps=900,
        alternatives_gold_return_bps=300, alternatives_gold_vol_bps=1500,
        liquidity_vol_bps=20,
        correlation_matrix_json=None,
        sub_asset_class_assumptions_json=None,
        equities_skewness_bps=None, equities_excess_kurt_bps=None,
        bonds_skewness_bps=None, bonds_excess_kurt_bps=None,
        real_estate_skewness_bps=None, real_estate_excess_kurt_bps=None,
        alternatives_skewness_bps=None, alternatives_excess_kurt_bps=None,
    )
    targets = {"equities": 5000, "bonds": 3000, "real_estate": 1000, "alternatives": 500, "liquidity": 500}
    metrics = pe._expected_metrics(targets, cma)
    # Bestehende Keys
    assert "sharpe_ratio_x100" in metrics
    assert "expected_return_bps" in metrics
    # Neue U-96 Keys
    assert "sortino_ratio_x100" in metrics
    assert "calmar_ratio_x100" in metrics
    assert "information_ratio_x100" in metrics
