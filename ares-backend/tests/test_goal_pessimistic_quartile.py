"""3eyes-Parität: der pessimistische CHF-Fehlbetrag eines Vermoegensziels basiert
auf dem SCHLECHTESTEN QUARTIL (P25), nicht mehr auf P10.

Methodik (Q&A iSAA): fuer Nicht-Cashflow-Ziele wird das schlechteste Quartil
ausgewiesen. Vorher nutzte 5eyes P10 (untere 10%) — strenger als die Methodik.
Dieser Test fixiert die Umstellung target − P25 und sichert, dass NICHT mehr
target − P10 verwendet wird.
"""
from types import SimpleNamespace

from services.portfolio_engine import _monte_carlo_goal_summary, _percentile

from test_goal_scoring_horizon import _make_policy


# Streuung mit klar unterschiedlichem P10 vs P25 (1..20 Mio).
_SPREAD = [k * 1_000_000 for k in range(1, 21)]
_TARGET = 30_000_000  # ueber allen Pfaden -> Fehlbetrag immer positiv


def _wealth_goal():
    return SimpleNamespace(
        id="wg-1",
        label="Vermoegensziel",
        goal_type="Vermoegensziel",
        goal_scope="Beratungsvermoegen",
        rank=1,
        target_amount_rappen=0,
        target_wealth_rappen=_TARGET,
        target_return_bps=0,
        start_date="2026-01-01",
        target_date="2031-12-31",
        horizon_years=None,
        is_ongoing=0,
        frequency="einmalig",
    )


def _summary():
    return _monte_carlo_goal_summary(
        _wealth_goal(),
        path_values_by_year=[list(_SPREAD) for _ in range(11)],
        annualized_return_samples_bps=[450],
        inflation_series_bps=[0] * 11,
        advisory_wealth_rappen=10_000_000,
        total_wealth_rappen=10_000_000,
        start_year=2026,
        horizon_years=10,
        policy=_make_policy(),
    )


def test_pessimistic_shortfall_uses_worst_quartile_p25():
    summary = _summary()
    expected_p25 = int(_percentile(_SPREAD, 0.25))
    assert summary["pessimistic_shortfall_rappen"] == _TARGET - expected_p25


def test_pessimistic_shortfall_is_not_p10_based_anymore():
    summary = _summary()
    p10 = int(_percentile(_SPREAD, 0.10))
    p25 = int(_percentile(_SPREAD, 0.25))
    # Sanity: die beiden Perzentile unterscheiden sich in dieser Streuung.
    assert p25 > p10
    # Der Fehlbetrag darf NICHT mehr auf P10 basieren (das war strenger).
    assert summary["pessimistic_shortfall_rappen"] != _TARGET - p10


def test_summary_exposes_p25_projection():
    summary = _summary()
    assert summary["projected_value_p25_rappen"] == int(_percentile(_SPREAD, 0.25))
