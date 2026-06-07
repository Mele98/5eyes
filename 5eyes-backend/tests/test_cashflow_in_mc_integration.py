"""Sprint A3 (2026-06-07): Cashflow-in-MC Integration Drift-Tests.

Pin-Tests die das aktuell-korrekte Cashflow-Verhalten in simulate_wealth_paths
schuetzen vor zukuenftiger Regression. Komplementaer zum Audit-Doc
docs/audits/2026-06-07-cashflow-in-mc-audit.md.

# Was getestet wird (positive Befunde aus Audit)
F1: CF ist 1D (pro Jahr), broadcasted auf alle Pfade gleich
F2: CF wird POST-Growth + POST-Tax addiert (Reihenfolge)
F3: Inflation wird PRE-MC angewendet via cashflow_timeline.py
F4: Mortalitaets-Maske zeroisiert CF nach Todesjahr
F7: Negative Wealth (Lebensluecke) blockt Growth+Tax, aber CF wirkt

# Was hier NICHT getestet wird
F5 Multi-Currency-Gap → wartet auf B3-Sprint, dort Drift-Test
F6 Engine-Pfad-Drift → bereits durch test_engine_reference_mandates.py + dedizierte
   portfolio_engine-Tests abgedeckt

# Drift-Resistenz
Statt brittle absolute Werte verifizieren wir strukturelle Invarianten der
CF-Integration. So koennen Engine-Verbesserungen (z.B. neue Steuer-Plugins)
weiter aufgebaut werden ohne diese Tests zu brechen.
"""
from __future__ import annotations

import numpy as np
import pytest

from services.optimizer.scenario_engine import (
    N_BUCKETS,
    ScenarioInputs,
    build_scenario_paths,
    simulate_wealth_paths,
)


# ===========================================================================
# Test-Helpers
# ===========================================================================


def _flat_inputs(mu_bps: float = 200, sigma_bps: float = 100) -> ScenarioInputs:
    """Flat-Return-Universum fuer deterministische Wealth-Trajectories."""
    return ScenarioInputs(
        mu_bps=np.full(N_BUCKETS, mu_bps, dtype=np.float64),
        sigma_bps=np.full(N_BUCKETS, sigma_bps, dtype=np.float64),
        skew_bps=np.zeros(N_BUCKETS, dtype=np.float64),
        excess_kurt_bps=np.zeros(N_BUCKETS, dtype=np.float64),
        cholesky=np.eye(N_BUCKETS, dtype=np.float64),
    )


def _equal_weights() -> np.ndarray:
    """Gleichgewichtete Allocation 20% pro Bucket."""
    return np.full(N_BUCKETS, 1.0 / N_BUCKETS, dtype=np.float64)


def _make_paths(n_paths: int, horizon: int, seed: int = 42, mu_bps: float = 200) -> np.ndarray:
    """Stochastische Return-Pfade fuer Tests."""
    return build_scenario_paths(
        _flat_inputs(mu_bps=mu_bps),
        horizon_years=horizon,
        n_paths=n_paths,
        seed=seed,
        antithetic=True,
    )


# ===========================================================================
# F1 — CF ist 1D pro Jahr, gleich fuer alle Pfade
# ===========================================================================


def test_f1_cashflow_broadcasted_gleich_auf_alle_pfade():
    """CF[t] wird zu jedem Pfad gleich addiert. Verifizieren via Differenz-
    Vergleich: wealth_with_cf[p, t] - wealth_no_cf[p, t] muss fuer alle p
    gleich sein (modulo Pfad-spezifischem Wachstum)."""
    n_paths, horizon = 100, 5
    initial = 1_000_000_00
    paths = _make_paths(n_paths, horizon)
    w_zero_cf = simulate_wealth_paths(
        initial_wealth_rappen=initial,
        weights=_equal_weights(),
        return_paths=paths,
        cashflow_series_rappen=[0] * horizon,
    )
    w_with_cf = simulate_wealth_paths(
        initial_wealth_rappen=initial,
        weights=_equal_weights(),
        return_paths=paths,
        cashflow_series_rappen=[100_00] * horizon,  # 100 CHF/J jeden Pfad
    )
    # Wealth-Differenz im Jahr 1 (t=1) ist genau die CF des ersten Jahres
    # (CF wird POST-Growth addiert, Growth-Faktor pfad-spezifisch, aber CF konstant)
    diff_t1 = w_with_cf[:, 1] - w_zero_cf[:, 1]
    # Im Jahr 1 wurde noch keine kumulative Verzinsung der CFs, also alle gleich = 100_00
    assert np.allclose(diff_t1, 100_00, atol=1e-6), (
        f"CF nicht gleich auf alle Pfade — Std={diff_t1.std()}"
    )


def test_f1_cashflow_1d_shape_korrekt_geprueft():
    """Pad/Trim Logik wenn cashflow_series-Laenge != horizon."""
    n_paths, horizon = 10, 5
    paths = _make_paths(n_paths, horizon)
    # CF zu kurz: wird gepaddet mit 0
    w_short = simulate_wealth_paths(
        initial_wealth_rappen=1_000_000_00,
        weights=_equal_weights(),
        return_paths=paths,
        cashflow_series_rappen=[100_00, 100_00],  # nur 2 Jahre
    )
    assert w_short.shape == (n_paths, horizon + 1)


# ===========================================================================
# F2 — Reihenfolge: Growth → Tax → CF
# ===========================================================================


def test_f2_positiver_cf_erhoeht_wealth_im_jahr():
    """Positive CF in Jahr t muss wealth[t+1] vs wealth[t] netto erhoehen
    (modulo Wachstum). Strukturelle Sanity-Check."""
    n_paths, horizon = 50, 3
    initial = 1_000_000_00
    paths = _make_paths(n_paths, horizon, mu_bps=0)  # 0% return -> kein Wachstum
    w = simulate_wealth_paths(
        initial_wealth_rappen=initial,
        weights=_equal_weights(),
        return_paths=paths,
        cashflow_series_rappen=[50_000_00, 50_000_00, 50_000_00],
    )
    # Mit mu=0: wealth[t+1] ≈ wealth[t] + 50_000_00 (Median ueber Pfade)
    median_diff = np.median(w[:, 1] - w[:, 0])
    assert abs(median_diff - 50_000_00) < 5_000_00, (
        f"Erwarteter Median-Diff ~5M Rappen, war {median_diff}"
    )


def test_f2_negativer_cf_reduziert_wealth():
    """Negative CF (Entnahme) muss wealth nach unten ziehen."""
    n_paths, horizon = 50, 3
    initial = 1_000_000_00
    paths = _make_paths(n_paths, horizon, mu_bps=0)
    w_no_cf = simulate_wealth_paths(
        initial_wealth_rappen=initial,
        weights=_equal_weights(),
        return_paths=paths,
        cashflow_series_rappen=[0, 0, 0],
    )
    w_neg_cf = simulate_wealth_paths(
        initial_wealth_rappen=initial,
        weights=_equal_weights(),
        return_paths=paths,
        cashflow_series_rappen=[-50_000_00, -50_000_00, -50_000_00],
    )
    # End-Wealth mit Entnahme MUSS niedriger sein
    assert np.median(w_neg_cf[:, -1]) < np.median(w_no_cf[:, -1])


# ===========================================================================
# F3 — Inflation wird PRE-MC angewendet (via cashflow_timeline)
# ===========================================================================


def test_f3_inflation_wird_in_cashflow_timeline_appliziert():
    """net_cashflow_series produziert bereits inflationierte Werte —
    simulate_wealth_paths sieht NUR die Endwerte."""
    from datetime import date
    from types import SimpleNamespace
    from services.cashflow_timeline import net_cashflow_series

    income_cf = SimpleNamespace(
        amount_rappen=100_000_00,  # 1k CHF/Jahr nominal
        frequency="jaehrlich",
        nature=None,
        valid_from=None,
        valid_until=None,
        cashflow_type="Income",
        is_inflation_linked=1,
    )
    today_year = date.today().year
    # 2% Inflation p.a., 5 Jahre
    series = net_cashflow_series(
        [income_cf], years=5, start_year=today_year,
        inflation_series_bps=[200] * 5,
    )
    # Jahr 0: nominal, Jahr 1: ×1.02, Jahr 2: ×1.02², usw.
    assert series[0] == 100_000_00
    expected_t2 = int(round(100_000_00 * 1.02 ** 2))
    assert abs(series[2] - expected_t2) < 100, f"Inflation falsch: {series[2]} vs {expected_t2}"


def test_f3_inflation_linked_flag_steuert_anwendung():
    """is_inflation_linked=0 -> kein Inflations-Faktor, auch wenn Series gesetzt."""
    from datetime import date
    from types import SimpleNamespace
    from services.cashflow_timeline import net_cashflow_series

    cf_nominal = SimpleNamespace(
        amount_rappen=100_000_00,
        frequency="jaehrlich", nature=None,
        valid_from=None, valid_until=None,
        cashflow_type="Income", is_inflation_linked=0,  # NICHT inflationiert
    )
    today_year = date.today().year
    series = net_cashflow_series(
        [cf_nominal], years=5, start_year=today_year,
        inflation_series_bps=[200] * 5,
    )
    # Alle Jahre identisch (nominal)
    assert all(s == 100_000_00 for s in series), f"Nominal-CF wurde inflationiert: {series}"


# ===========================================================================
# F4 — Mortalitaets-Maske
# ===========================================================================


def test_f4_mortality_zeroisiert_cf_nach_tod():
    """death_year_index[p]=d => CF=0 fuer t>=d, Wealth-Wachstum laeuft weiter."""
    n_paths, horizon = 100, 10
    initial = 1_000_000_00
    paths = _make_paths(n_paths, horizon, mu_bps=0)
    # Halbe Pfade sterben in Jahr 5, andere in Jahr 10 (= leben durch)
    death_idx = np.array([5] * 50 + [10] * 50, dtype=np.int32)
    w = simulate_wealth_paths(
        initial_wealth_rappen=initial,
        weights=_equal_weights(),
        return_paths=paths,
        cashflow_series_rappen=[-100_000_00] * horizon,  # 100k/J Entnahme
        death_year_index_per_path=death_idx,
    )
    # Pfade die in Jahr 5 sterben haben hoeheres End-Wealth (5 Jahre weniger Entnahme)
    early_dying = w[:50, -1]
    late_dying = w[50:, -1]
    assert np.median(early_dying) > np.median(late_dying), (
        "Frueh-Sterbende muessten mehr Wealth haben (weniger Entnahme)"
    )


def test_f4_mortality_kein_effekt_bei_death_idx_horizon():
    """death_year=horizon = lebt durch == kein Mortality-Effekt."""
    n_paths, horizon = 50, 5
    initial = 1_000_000_00
    paths = _make_paths(n_paths, horizon, mu_bps=0)
    w_no_death = simulate_wealth_paths(
        initial_wealth_rappen=initial, weights=_equal_weights(),
        return_paths=paths, cashflow_series_rappen=[-10_000_00] * horizon,
    )
    w_with_death = simulate_wealth_paths(
        initial_wealth_rappen=initial, weights=_equal_weights(),
        return_paths=paths, cashflow_series_rappen=[-10_000_00] * horizon,
        death_year_index_per_path=np.full(n_paths, horizon, dtype=np.int32),
    )
    # Identische Wealth-Trajectories
    assert np.allclose(w_no_death, w_with_death)


# ===========================================================================
# F7 — Lebensluecke (Negative Wealth blockt Growth + Tax)
# ===========================================================================


def test_f7_negative_wealth_kein_growth():
    """Wenn Wealth negativ wird (Lebensluecke), MUSS Growth=Identity sein —
    sonst wuerde -100 × 1.05 = -105 als Schuldzins-Effekt entstehen."""
    n_paths, horizon = 30, 3
    initial = 100_00  # Sehr klein: 100 CHF
    # Massive Entnahme -> Wealth wird negativ
    paths = _make_paths(n_paths, horizon, mu_bps=500)  # 5% Wachstum
    w = simulate_wealth_paths(
        initial_wealth_rappen=initial,
        weights=_equal_weights(),
        return_paths=paths,
        cashflow_series_rappen=[-200_00] * horizon,  # 200 CHF/J Entnahme
    )
    # Wenn Wealth in Jahr t negativ ist, sollte Wealth[t+1] = Wealth[t] + CF[t]
    # (kein Wachstum), nicht Wealth[t] × growth + CF[t]
    for p in range(n_paths):
        for t in range(horizon):
            if w[p, t] < 0:
                expected = w[p, t] - 200_00  # nur CF abgezogen
                actual = w[p, t + 1]
                # Toleranz fuer Float-Rundung
                assert abs(actual - expected) < 1.0, (
                    f"Pfad {p} Jahr {t}: w[{t}]={w[p,t]}, w[{t+1}]={actual}, expected ~{expected}"
                )


def test_f7_positive_cf_kann_wealth_aus_luecke_holen():
    """In der Lebensluecke (negative Wealth) muss positive CF Wealth zurueck
    ins Positive bringen koennen."""
    n_paths, horizon = 20, 5
    initial = 1_000_00  # 1000 CHF Start
    paths = _make_paths(n_paths, horizon, mu_bps=0)  # keine Volatilitaet, keine Returns
    # Erst Entnahme bis Lebensluecke, dann massive Einnahme
    cfs = [-2_000_00, -2_000_00, 10_000_00, 0, 0]  # -2k, -2k, +10k, 0, 0
    w = simulate_wealth_paths(
        initial_wealth_rappen=initial,
        weights=_equal_weights(),
        return_paths=paths,
        cashflow_series_rappen=cfs,
    )
    # Nach Jahr 2 (CF 10k): wealth muss >= 7k sein (1k - 2k - 2k + 10k = 7k)
    # (modulo Wachstum bei positiven Werten)
    assert np.median(w[:, 3]) >= 6_500_00, (
        f"Lebensluecke wurde nicht von positiver CF rausgeholt: median={np.median(w[:,3])}"
    )


# ===========================================================================
# F5 — Multi-Currency-Gap (DOKUMENTIERT als XFAIL für B3)
# ===========================================================================


@pytest.mark.xfail(
    reason="P4/B3 noch nicht implementiert: cashflow_timeline.py ignoriert "
           "Cashflow.currency-Feld. Wird in Sprint B3 behoben.",
    strict=True,  # XPASS => Test soll fehlschlagen wenn B3 done und xfail veraltet
)
def test_f5_multi_currency_usd_zu_chf_konversion():
    """B3-Reminder: USD-Income muss zu CHF konvertiert werden (FX-Kurs).
    Aktuell wird currency-Feld ignoriert -> 100k USD wird als 100k CHF behandelt.

    Wenn dieser Test PASSED (xfail wird zu xpass), ist B3 implementiert und
    der xfail-Marker kann entfernt werden.
    """
    from datetime import date
    from types import SimpleNamespace
    from services.cashflow_timeline import net_cashflow_series

    # 100k USD/J = ca. 90k CHF bei 0.90 USD/CHF
    usd_income = SimpleNamespace(
        amount_rappen=100_000_00,
        currency="USD",
        frequency="jaehrlich", nature=None,
        valid_from=None, valid_until=None,
        cashflow_type="Income", is_inflation_linked=0,
    )
    today_year = date.today().year
    series = net_cashflow_series(
        [usd_income], years=3, start_year=today_year,
    )
    # Wenn currency korrekt konvertiert wird, MUSS der Wert != 100_000_00 sein
    # (ausser bei perfektem USD/CHF=1.0 was wir hier nicht erwarten)
    assert series[0] != 100_000_00, (
        "Multi-Currency-Gap geschlossen: USD-Income != CHF-Wert in der Series"
    )


# ===========================================================================
# Determinismus-Test fuer CF-Integration
# ===========================================================================


def test_cashflow_integration_deterministisch():
    """Gleiche Inputs (Seed + CF + Weights) muessen identische Wealth-Pfade liefern."""
    n_paths, horizon = 50, 5
    initial = 1_000_000_00
    paths1 = _make_paths(n_paths, horizon, seed=77)
    paths2 = _make_paths(n_paths, horizon, seed=77)
    cf = [10_000_00] * horizon
    w1 = simulate_wealth_paths(
        initial_wealth_rappen=initial, weights=_equal_weights(),
        return_paths=paths1, cashflow_series_rappen=cf,
    )
    w2 = simulate_wealth_paths(
        initial_wealth_rappen=initial, weights=_equal_weights(),
        return_paths=paths2, cashflow_series_rappen=cf,
    )
    assert np.allclose(w1, w2), "CF-Integration nicht deterministisch"
