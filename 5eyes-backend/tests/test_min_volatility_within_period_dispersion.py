"""MIN-VOLATILITY-WITHIN-PERIOD-001 -- deterministische Periodenmittel sind keine Vola.

CIO-Entscheid 2026-10-25: Das Risikomass von ``min_volatility`` misst nur die
stochastische Streuung um den PERIODENSPEZIFISCHEN Erwartungswert (gepoolte
Innerhalb-Perioden-Varianz). Die Streuung der Periodenmittel ueber die Zeit
(Zinsstruktur, Mean-Pfad, Regime-Mittel) ist deterministisch und zaehlt nicht.

Vorher poolte ``_one_period_return_dispersion`` alle Pfad-Jahr-Beobachtungen
um EINEN globalen Mittelwert und mass damit

    Var(R) = E_t[Var(R_t | t)] + Var_t(E[R_t | t])

-- der zweite Summand ist kein Marktrisiko. Gegenbeispiel (Codex-Reproducer
2026-10-14): identische Innerhalb-Perioden-Schocks, einmal stationaer, einmal
mit der Kurve -20/0/+20 %: 0.0816 gegen 0.1826.

Soll (Oracle):

    sigma = sqrt( (1/T) * sum_t s_t^2 ),
    s_t^2 = sum_i w_i (r_it - m_t)^2 / (1 - sum_i w_i^2),  m_t = sum_i w_i r_it

mit normierten Pfadgewichten ``w`` (uniform: ``w_i = 1/n``, dann ist ``s_t^2``
die Stichprobenvarianz mit ``ddof=1``). Fuer stationaere Wuerfel ist das der
klassische gepoolte Within-Group-Schaetzer; bei zeitvariabler Vola das
quadratische Mittel der Periodenvolas.
"""
from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import numpy as np
import pytest

from services.optimizer.objective_variants import (
    MIN_VOLATILITY_ESTIMATOR_VERSION,
    OBJECTIVE_GOAL_SHORTFALL,
    OBJECTIVE_MIN_VOLATILITY,
    ObjectiveDomainError,
    objective_basis,
    primary_objective,
)


def _min_volatility(factors: np.ndarray, weights: np.ndarray | None = None) -> float:
    return primary_objective(
        OBJECTIVE_MIN_VOLATILITY,
        goal_shortfall_value=0.0,
        portfolio_return_factors=factors,
        weights=weights,
    )


def _oracle(returns: np.ndarray, weights: np.ndarray | None = None) -> float:
    """Unabhaengige Nachrechnung per Schleife, ohne Produkt-Hilfsfunktionen."""
    returns = np.asarray(returns, dtype=np.float64)
    n_paths, n_periods = returns.shape
    if weights is None:
        w = np.full(n_paths, 1.0 / n_paths)
    else:
        w = np.asarray(weights, dtype=np.float64) / float(np.sum(weights))
    correction = 1.0 - float(np.sum(w * w))
    variances = []
    for t in range(n_periods):
        column = returns[:, t]
        mean_t = sum(w[i] * column[i] for i in range(n_paths))
        ss_t = sum(w[i] * (column[i] - mean_t) ** 2 for i in range(n_paths))
        variances.append(ss_t / correction)
    return float(np.sqrt(sum(variances) / n_periods))


# ── 1. Codex-Reproducer (vorher strikter xfail) ─────────────────────────────


def test_deterministic_period_means_do_not_become_portfolio_volatility() -> None:
    """Gleiche Innerhalb-Perioden-Abweichungen -> gleiches stochastisches Risiko."""
    path_shocks = np.array([-0.10, 0.00, 0.10], dtype=np.float64)[:, None]
    stationary_returns = np.repeat(path_shocks, repeats=3, axis=1)
    deterministic_term_structure = np.array(
        [-0.20, 0.00, 0.20], dtype=np.float64
    )[None, :]
    shifted_returns = stationary_returns + deterministic_term_structure

    # Voraussetzung: nach Zentrierung je Periode sind beide Wuerfel gleich.
    np.testing.assert_allclose(
        stationary_returns - stationary_returns.mean(axis=0),
        shifted_returns - shifted_returns.mean(axis=0),
        rtol=0.0,
        atol=1e-15,
    )

    stationary_value = _min_volatility(1.0 + stationary_returns)
    shifted_value = _min_volatility(1.0 + shifted_returns)

    assert shifted_value == pytest.approx(stationary_value, rel=0.0, abs=1e-15), (
        "deterministic period means were counted as stochastic volatility: "
        f"stationary={stationary_value}, shifted={shifted_value}"
    )
    # Positivkontrolle: der Wert ist nicht trivial 0 (sonst waere die
    # Gleichheit auch mit einem kaputten Mass erfuellt).
    assert stationary_value == pytest.approx(0.1, rel=0.0, abs=1e-15)


# ── 2. Soll-Invariante: deterministischer Pfad hat Vola 0 ───────────────────


def test_purely_deterministic_period_returns_have_zero_volatility() -> None:
    """Alle Pfade identisch, Renditen je Periode verschieden -> exakt 0.

    Mit dem globalen Pooling war das die Streuung der Kurve selbst
    (hier ~0.2055), obwohl kein einziger Zufallsfaktor im Wuerfel steckt.
    """
    curve = np.array([0.10, -0.20, 0.30, 0.02, -0.05], dtype=np.float64)
    factors = np.tile(1.0 + curve, (6, 1))
    assert float(np.std(factors - 1.0)) > 0.15  # Kurve streut sichtbar
    assert _min_volatility(factors) == 0.0
    weights = np.array([1.0, 2.0, 3.0, 4.0, 5.0, 6.0])
    assert _min_volatility(factors, weights) == 0.0


# ── 3. Metamorph: Mean-Verschiebung je Periode aendert nichts ───────────────


@pytest.mark.parametrize("use_weights", [False, True])
def test_period_mean_shift_is_invariant(use_weights: bool) -> None:
    rng = np.random.default_rng(20261025)
    returns = rng.normal(0.04, 0.15, size=(400, 10))
    shift = rng.normal(0.0, 0.25, size=10)  # beliebige deterministische Kurve
    weights = rng.uniform(0.2, 5.0, size=400) if use_weights else None

    base = _min_volatility(1.0 + returns, weights)
    shifted = _min_volatility(1.0 + returns + shift[None, :], weights)
    assert shifted == pytest.approx(base, rel=1e-12, abs=0.0)
    # Gegenprobe: das globale Pooling haette sich deutlich bewegt.
    assert float(np.std(returns + shift)) > float(np.std(returns)) * 1.2


def test_constant_covariance_with_time_varying_means_equals_constant_means() -> None:
    """Gleiche Kovarianz je Periode: Wert unabhaengig vom Mean-Pfad (Regression 6)."""
    rng = np.random.default_rng(7)
    shocks = rng.normal(0.0, 0.12, size=(3000, 8))
    constant = _min_volatility(1.05 + shocks)
    term_structure = np.linspace(-0.03, 0.09, 8)[None, :]
    varying = _min_volatility(1.0 + term_structure + shocks)
    assert varying == pytest.approx(constant, rel=1e-12, abs=0.0)


# ── 4. Oracle ───────────────────────────────────────────────────────────────


def test_hand_computed_oracle() -> None:
    """3 Pfade x 2 Perioden, von Hand gerechnet.

    Periode 1: 0.0/0.1/0.2 -> Mittel 0.1, SS 0.02, s^2 = 0.02/2 = 0.01
    Periode 2: 0.0/0.3/0.6 -> Mittel 0.3, SS 0.18, s^2 = 0.18/2 = 0.09
    sigma = sqrt((0.01 + 0.09)/2) = sqrt(0.05)
    """
    returns = np.array([[0.0, 0.0], [0.1, 0.3], [0.2, 0.6]])
    assert _min_volatility(1.0 + returns) == pytest.approx(
        np.sqrt(0.05), rel=1e-14, abs=0.0
    )


@pytest.mark.parametrize("use_weights", [False, True])
def test_matches_independent_oracle(use_weights: bool) -> None:
    rng = np.random.default_rng(11)
    returns = rng.normal(0.03, 0.2, size=(57, 7)) + np.linspace(-0.1, 0.1, 7)
    weights = rng.uniform(0.1, 3.0, size=57) if use_weights else None
    assert _min_volatility(1.0 + returns, weights) == pytest.approx(
        _oracle(returns, weights), rel=1e-12, abs=0.0
    )


def test_unweighted_equals_numpy_ddof1_and_uniform_weights() -> None:
    rng = np.random.default_rng(3)
    returns = rng.normal(0.02, 0.1, size=(120, 5))
    expected = float(np.sqrt(np.mean(np.var(returns, axis=0, ddof=1))))
    assert _min_volatility(1.0 + returns) == pytest.approx(expected, rel=1e-13)
    assert _min_volatility(1.0 + returns, np.full(120, 7.0)) == pytest.approx(
        expected, rel=1e-13
    )


def test_time_varying_volatility_aggregates_as_quadratic_mean() -> None:
    """Zeitvariable Vola: quadratisches Mittel der Periodenvolas (Regression 7).

    Halber Horizont 5 %, halber 15 % -> sqrt((0.0025 + 0.0225)/2) = 0.1118,
    nicht das arithmetische Mittel 0.10 und unabhaengig von der Horizontlaenge.
    """
    rng = np.random.default_rng(42)
    for half in (2, 6):
        calm = rng.normal(0.0, 0.05, size=(200_000, half))
        rough = rng.normal(0.0, 0.15, size=(200_000, half))
        value = _min_volatility(1.0 + np.concatenate([calm, rough], axis=1))
        assert value == pytest.approx(np.sqrt(0.0125), rel=3e-3)
        assert value > 0.10 * 1.05  # klar ueber dem arithmetischen Mittel


def test_stationary_scale_is_preserved() -> None:
    """Stationaere Sigmas werden weiter in korrekter Skala getroffen (Regression 2)."""
    for sigma in (0.03, 0.12, 0.24):
        rng = np.random.default_rng(606)
        factors = 1.0 + rng.normal(0.05, sigma, size=(4000, 12))
        assert _min_volatility(factors) == pytest.approx(sigma, rel=0.02)


def test_importance_weights_are_normalised_per_period() -> None:
    """IS-Gewichte: Mittelwert je Periode unter der Zielverteilung (Regression 4).

    Ein globaler gewichteter Mittelwert wuerde die zwei Periodenmittel
    vermischen; per Periode zentriert ist das Ergebnis exakt das Oracle.
    """
    returns = np.array([[0.00, 0.50], [0.10, 0.70], [0.40, 0.90]])
    weights = np.array([1.0, 1.0, 2.0])
    assert _min_volatility(1.0 + returns, weights) == pytest.approx(
        _oracle(returns, weights), rel=1e-14
    )


def test_path_and_period_permutation_invariance() -> None:
    """Regression 9: Pfad- und periodenerhaltende Jahrespermutation."""
    rng = np.random.default_rng(5)
    returns = rng.normal(0.03, 0.15, size=(90, 6)) + np.linspace(0, 0.2, 6)
    weights = rng.uniform(0.5, 2.0, size=90)
    base = _min_volatility(1.0 + returns, weights)
    path_perm = rng.permutation(90)
    year_perm = rng.permutation(6)
    assert _min_volatility(1.0 + returns[path_perm], weights[path_perm]) == (
        pytest.approx(base, rel=1e-12)
    )
    assert _min_volatility(1.0 + returns[:, year_perm], weights) == (
        pytest.approx(base, rel=1e-12)
    )


# ── 5. Fail-closed ──────────────────────────────────────────────────────────


def test_single_path_is_not_estimable() -> None:
    """Aus einem Pfad ist keine Innerhalb-Perioden-Streuung schaetzbar."""
    with pytest.raises(ObjectiveDomainError) as excinfo:
        _min_volatility(np.array([[1.1, 0.9, 1.2]]))
    assert excinfo.value.reason_code == "objective_dispersion_not_estimable"


def test_all_mass_on_one_path_is_not_estimable() -> None:
    factors = 1.0 + np.array([[0.1, 0.2], [0.3, -0.1], [0.0, 0.05]])
    with pytest.raises(ObjectiveDomainError) as excinfo:
        _min_volatility(factors, np.array([0.0, 4.0, 0.0]))
    assert excinfo.value.reason_code == "objective_dispersion_not_estimable"


def test_wrong_weight_length_names_the_path_count() -> None:
    factors = 1.0 + np.zeros((5, 3))
    with pytest.raises(ValueError, match="n_paths=5"):
        _min_volatility(factors, np.ones(3))


# ── 6. Nachweis ─────────────────────────────────────────────────────────────


def test_objective_basis_names_the_estimator_for_min_volatility_only() -> None:
    basis = objective_basis(OBJECTIVE_MIN_VOLATILITY)
    assert basis["risk_measure_estimator"] == MIN_VOLATILITY_ESTIMATOR_VERSION
    assert MIN_VOLATILITY_ESTIMATOR_VERSION == "within_period_pooled_variance_v1"
    # Default-Nachweis bleibt bytegleich (kein neues Feld).
    assert "risk_measure_estimator" not in objective_basis(OBJECTIVE_GOAL_SHORTFALL)


def test_engine_version_is_v16() -> None:
    from services.optimizer.solver import OPTIMIZER_ENGINE_VERSION

    assert OPTIMIZER_ENGINE_VERSION == "saa_resampled_v16"
