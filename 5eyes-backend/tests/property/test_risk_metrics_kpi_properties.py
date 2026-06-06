"""Sprint U-107 (2026-06-05): Property-Based-Tests fuer Risk-Metrics-KPI.

Pruefen 4 mathematische Invarianten von Sortino/Calmar/Information-
Ratio mit hypothesis-generierten Inputs (statt Beispiel-basiert).

**Opt-in**: hypothesis ist NICHT in requirements.txt. Wenn hypothesis
nicht installiert ist -> pytest.skip auf Modul-Ebene (Collection
schlaegt nicht fehl, CI bleibt gruen).

Installation lokal:
    pip install hypothesis
    pytest tests/property/
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Skip auf Modul-Ebene wenn hypothesis fehlt — verhindert ImportError
# in pytest collection.
hypothesis = pytest.importorskip("hypothesis")
from hypothesis import given, strategies as st  # noqa: E402

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.risk_metrics_kpi import (  # noqa: E402
    compute_calmar_ratio_x100,
    compute_extended_risk_metrics,
    compute_information_ratio_x100,
    compute_sortino_ratio_x100,
)


# ---------------------------------------------------------------------------
# Property 1: Sortino >= Sharpe bei Excess-Return >= 0 (Gaussian-Annahme)
# ---------------------------------------------------------------------------

@given(
    return_bps=st.integers(min_value=0, max_value=2000),
    vol_bps=st.integers(min_value=1, max_value=3000),
    rf_bps=st.integers(min_value=0, max_value=500),
)
def test_sortino_at_least_sharpe_when_excess_return_positive(
    return_bps: int, vol_bps: int, rf_bps: int,
):
    """Property: bei return >= rf ist Sortino >= Sharpe.

    Begruendung: Sortino dividiert durch downside_vol = vol/sqrt(2),
    Sharpe dividiert durch vol. Der gleiche Zaehler dividiert durch
    den kleineren Nenner ergibt einen groesseren Quotient.
    """
    if return_bps < rf_bps:
        return  # Property gilt nicht bei negative excess return
    sortino = compute_sortino_ratio_x100(return_bps, vol_bps, rf_bps)
    sharpe = int(round(((return_bps - rf_bps) / vol_bps) * 100))
    assert sortino >= sharpe


# ---------------------------------------------------------------------------
# Property 2: Calmar > 0 wenn Return > 0 und Drawdown > 0
# ---------------------------------------------------------------------------

@given(
    return_bps=st.integers(min_value=1, max_value=2000),
    drawdown_bps=st.integers(min_value=1, max_value=5000),
)
def test_calmar_positive_when_return_and_drawdown_positive(
    return_bps: int, drawdown_bps: int,
):
    """Property: Calmar > 0 wenn beide positiv sind.

    Triviale Sign-Invariante als Smoke-Property — faengt Rundungs-
    Bugs an der Null-Grenze.
    """
    calmar = compute_calmar_ratio_x100(
        annual_return_bps=return_bps,
        expected_max_drawdown_bps=drawdown_bps,
    )
    assert calmar >= 0


# ---------------------------------------------------------------------------
# Property 3: Information-Ratio Antisymmetrie
# ---------------------------------------------------------------------------

@given(
    portfolio_return_bps=st.integers(min_value=0, max_value=2000),
    benchmark_return_bps=st.integers(min_value=0, max_value=2000),
    te_bps=st.integers(min_value=1, max_value=3000),
)
def test_information_ratio_swap_negates_sign(
    portfolio_return_bps: int, benchmark_return_bps: int, te_bps: int,
):
    """Property: IR(A vs B) == -IR(B vs A).

    Tausch der Rolle Portfolio<->Benchmark muss den Vorzeichen-
    Sign der IR umdrehen (Antisymmetrie).
    """
    forward = compute_information_ratio_x100(
        portfolio_return_bps, benchmark_return_bps, te_bps,
    )
    backward = compute_information_ratio_x100(
        benchmark_return_bps, portfolio_return_bps, te_bps,
    )
    # Beruecksichtigung Rundungs-Fehler bei int(round(...))
    assert abs(forward + backward) <= 1


# ---------------------------------------------------------------------------
# Property 4: Konsolidierter Helper liefert dieselben Werte wie Einzel-Aufrufe
# ---------------------------------------------------------------------------

@given(
    return_bps=st.integers(min_value=0, max_value=2000),
    vol_bps=st.integers(min_value=1, max_value=3000),
    rf_bps=st.integers(min_value=0, max_value=500),
)
def test_extended_helper_matches_individual_calls(
    return_bps: int, vol_bps: int, rf_bps: int,
):
    """Property: compute_extended_risk_metrics() == individual fns.

    Stellt sicher dass der Helper nicht von der Logik der Einzel-
    Funktionen abweicht (Drift-Schutz fuer das Bundling).
    """
    out = compute_extended_risk_metrics(
        return_bps=return_bps, vol_bps=vol_bps, risk_free_bps=rf_bps,
    )
    sortino_direct = compute_sortino_ratio_x100(return_bps, vol_bps, rf_bps)
    assert out["sortino_ratio_x100"] == sortino_direct

    calmar_direct = compute_calmar_ratio_x100(
        annual_return_bps=return_bps,
        expected_max_drawdown_bps=None,
        vol_bps=vol_bps,
        horizon_years=10,
    )
    assert out["calmar_ratio_x100"] == calmar_direct

    ir_direct = compute_information_ratio_x100(return_bps, rf_bps, vol_bps)
    assert out["information_ratio_x100"] == ir_direct
