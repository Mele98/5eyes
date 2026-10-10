"""OPT-1: combined_objective_two_phase muss `weights` auch in die
chance_constraint_penalty durchreichen (nicht nur in shortfall_/volatility_objective).

Reiner Test ohne DB. Mit primary_weight=0 und volatility_weight=0 reduziert sich
der Rückgabewert auf den Chance-Penalty-Term — so lässt sich isoliert nachweisen,
dass die Importance-Sampling-Gewichte den Strafterm verändern. Vor dem Fix war der
Term gewichtsunabhängig (uniformes Sample-Mean) -> dieser Test schlüge fehl.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.optimizer.certification import wilson_lower_bound
from services.optimizer.goal_liabilities import GoalLiability
from services.optimizer.objective import combined_objective_two_phase


def _hard_goal() -> GoalLiability:
    return GoalLiability(
        goal_id="g1",
        label="Vermögensziel",
        goal_type="Vermoegensziel",
        target_kind="wealth_at_t",
        target_amount_rappen=100_000_00,
        target_year_index=5,
        liability_path_rappen=[0] * 11,
        hardness_key="hart",          # bindend -> Penalty greift
        weight_bps=10000,
        success_probability_min_x100=8000,  # tau = 0.80
    )


def _paths(n_paths: int = 2, n_success: int = 1) -> np.ndarray:
    """n_paths Pfade, 11 Spalten. Bei idx5 erreichen die ersten n_success
    Pfade das Ziel (150k), die uebrigen nicht (50k)."""
    p = np.full((n_paths, 11), 100_000_00, dtype=np.float64)
    p[:n_success, 5] = 150_000_00
    p[n_success:, 5] = 50_000_00
    return p


def _chance_only(weights, paths: np.ndarray | None = None):
    return combined_objective_two_phase(
        [_hard_goal()],
        _paths() if paths is None else paths,
        initial_wealth_rappen=100_000_00,
        horizon_years=10,
        primary_weight=0.0,      # Primary ausblenden
        volatility_weight=0.0,   # Vol ausblenden -> Rückgabe == Chance-Penalty
        lambda_chance=1.0,
        weights=weights,
    )


def test_opt1_weights_change_chance_penalty():
    """Kernaussage von OPT-1: die IS-Gewichte erreichen den Strafterm und
    bewegen ihn in die richtige Richtung."""
    uniform = _chance_only(None)
    mass_on_pass = _chance_only(np.array([0.99, 0.01]))
    mass_on_fail = _chance_only(np.array([0.01, 0.99]))

    # Gewichte müssen den Strafterm bewegen — und zwar in die richtige Richtung.
    # Das ist die eigentliche OPT-1-Zusicherung.
    assert mass_on_pass < uniform < mass_on_fail

    # Hier stand frueher `mass_on_fail > uniform * 2`. Der Faktor war ein
    # Artefakt der alten, in p linearen Shortfall-Formel. Seit die Strafe an
    # der unteren Konfidenzgrenze haengt, ist der Wertebereich bei nur zwei
    # Pfaden stark komprimiert (schon der uniforme Fall hat einen grossen
    # Shortfall, weil zwei Pfade fast keine Evidenz sind) -- ein fester
    # Faktor ist dort keine sinnvolle Zusicherung mehr. Geprueft wird
    # stattdessen ein klarer, aber formelunabhaengiger Abstand.
    assert mass_on_fail > uniform * 1.25

    # OPTIMIZER-POST-SELECTION-CERTIFICATION-001 (2026-10-10): hier stand
    # frueher `mass_on_pass == 0.0 or mass_on_pass < 1e-6`. Bei ZWEI Pfaden
    # ist das nicht mehr erreichbar, und zwar korrekt: das effektive
    # Stichprobenmass liegt hier bei ~1, damit laesst sich ueberhaupt nichts
    # zertifizieren -- auch nicht ein Punktschaetzer von 0.99. Die
    # Strafe haengt jetzt an der unteren Konfidenzgrenze, und die ist bei
    # einem effektiven Pfad weit von tau entfernt. Die Eigenschaft
    # "bestehend -> keine Strafe" wird deshalb im Test unten bei
    # statistisch ausreichender Stichprobe geprueft, wo sie fachlich
    # ueberhaupt gelten darf.
    assert mass_on_pass > 0.0


def test_opt1_passing_goal_has_no_penalty_at_adequate_sample_size():
    """Gegenstueck zum Test oben: bei ausreichender Stichprobe fuehrt ein
    klar bestandenes Ziel zu KEINER Strafe -- die schaetzer-bewusste Regel
    ist also keine pauschale Verschaerfung, sie verlangt nur genug Evidenz.

    2000 Pfade, 1900 davon erfolgreich (p_hat = 0.95 gegen tau = 0.80). Die
    Gewichte beguenstigen die Erfolgspfade zusaetzlich, halten das
    effektive Stichprobenmass aber nahe der Pfadzahl (~1975), sodass die
    ESS-Schwelle sauber erfuellt ist.
    """
    n_paths, n_success = 2000, 1900
    paths = _paths(n_paths=n_paths, n_success=n_success)
    weights = np.full(n_paths, 1.0)
    weights[:n_success] = 2.0

    penalty = _chance_only(weights, paths=paths)
    assert penalty == 0.0

    # Und die Richtungsaussage gilt auch hier: Masse auf die Fehlpfade
    # verschieben erzeugt eine Strafe.
    weights_on_fail = np.full(n_paths, 1.0)
    weights_on_fail[n_success:] = 50.0
    assert _chance_only(weights_on_fail, paths=paths) > 0.0


def test_opt1_uniform_matches_unweighted_mean():
    """Ohne Gewichte liegt P(success) bei 0.5 (ein von zwei Pfaden).

    OPTIMIZER-POST-SELECTION-CERTIFICATION-001 (2026-10-10): hier stand
    `penalty == 1.0 * 0.3^2 = 0.09`, also der Shortfall gegen den
    Punktschaetzer. Die Strafe haengt jetzt an der unteren
    Konfidenzgrenze; bei zwei Pfaden liegt die weit unter 0.5, der Term ist
    also deutlich groesser. Bewusst aus dem Produktions-Schaetzer
    abgeleitet statt als neue Magic Number eingetragen.
    """
    expected_shortfall = 0.8 - wilson_lower_bound(0.5, 2)
    assert abs(_chance_only(None) - expected_shortfall ** 2) < 1e-9
