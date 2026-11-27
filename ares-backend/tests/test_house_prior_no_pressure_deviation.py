"""HOUSE-PRIOR-APPROVAL-001 / N-857-1: Abweichung SAA zur Hausquote ohne Zieldruck.

ADR-015 nennt die Wirkung des Haus-Priors ohne Zieldruck. Dieser Test misst
sie reproduzierbar ueber die Hausmatrix-Profile 1-10 (Default-Hausmatrix aus
``house_matrix_loader``) und prueft die Zahl, nicht nur den ADR-Text:

* ohne Ziele (Gradient der Zielebene = 0) und
* mit einem Ziel, das die Hausquote sicher erreicht (Zielwahrscheinlichkeit 1),

liegt die publizierte SAA je Anlageklasse hoechstens
``NO_GOAL_MAX_DEVIATION_BPS`` (gemessen 2 bp) von der projizierten Hausquote
entfernt, also klar innerhalb der +-0.5 pp aus Audit 01/B2
(``NO_PRESSURE_MAX_DEVIATION_BPS``). Die Solver-Toleranz
``HOUSE_ANCHOR_NUMERICAL_TOLERANCE_BPS`` ist 1 bp; darueber liegende 1-2 bp
stammen aus der Bag-Mittelung und der bps-Rundung.
Gegenbeispiel (kein "ohne Zieldruck"): ein Entnahmemandat mit fast sicherem
Ziel weicht deutlich ab -- dort wirkt Zieldruck.

Gemessen wird gegen die PROJIZIERTE Hausquote (Anker des Priors). Die rohe
Hausmatrix-Zielquote kann schon vor dem Optimierer abweichen (Projektion auf
die zulaessige Menge, z. B. Liquiditaetsreserve); das weist
``deviation_vs_house_raw_bps`` getrennt aus.

``python -m pytest tests/test_house_prior_no_pressure_deviation.py -s`` druckt
die Messtabelle (Quelle der Zahlen in ADR-015).
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = Path(__file__).resolve().parent
for _p in (BACKEND_ROOT, TESTS_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import services.optimizer.solver as solver_module  # noqa: E402
from services.house_matrix_loader import load_house_matrix_default_tuples  # noqa: E402
from test_engine_reference_mandates import _base_cma  # noqa: E402
from test_house_prior_shrinkage import _inputs  # noqa: E402

# ADR-015, Abschnitt "Wirkung" (gemessen 2026-11-03, Windows: ohne Ziele und mit
# sicherem Ziel max 2 bp; Spielraum fuer BLAS-/Plattformunterschiede):
NO_GOAL_MAX_DEVIATION_BPS = 5
# +-0.5 pp (Audit 01/B2) als obere Schranke fuer "ohne Zieldruck".
NO_PRESSURE_MAX_DEVIATION_BPS = 50
WEALTH_CHF = 500_000
HORIZON = 12
# Ziel = 20 % des heutigen Vermoegens in 12 Jahren: mit jeder Hausquote sicher.
GOAL_SHARE = 0.2


def _row(entry: tuple) -> SimpleNamespace:
    (_f, _t, name, lq_min, lq_t, lq_max, b_min, b_t, b_max, e_min, e_t, e_max,
     re_min, re_t, re_max, a_min, a_t, a_max, risky, _eq_min) = entry
    return SimpleNamespace(
        profile_name=name,
        equity_min_bps=e_min, equity_max_bps=e_max, equity_target_bps=e_t,
        bonds_min_bps=b_min, bonds_max_bps=b_max, bonds_target_bps=b_t,
        real_estate_min_bps=re_min, real_estate_max_bps=re_max, real_estate_target_bps=re_t,
        alt_min_bps=a_min, alt_max_bps=a_max, alt_target_bps=a_t,
        liq_min_bps=lq_min, liq_max_bps=lq_max, liq_target_bps=lq_t,
        max_risky_fraction_bps=risky,
    )


def _profile_rows() -> dict[int, SimpleNamespace]:
    rows = {}
    for entry in load_house_matrix_default_tuples():
        for score in range(int(entry[0]), int(entry[1]) + 1):
            rows[score] = _row(entry)
    return rows


PROFILE_ROWS = _profile_rows()


def _certain_goal(score: int):
    year = date.today().year
    return SimpleNamespace(
        id=f"p{score}-ziel", label=f"Ziel Profil {score}", goal_type="Vermoegensziel",
        target_amount_rappen=int(GOAL_SHARE * WEALTH_CHF) * 100,
        target_wealth_rappen=int(GOAL_SHARE * WEALTH_CHF) * 100,
        target_return_bps=None, horizon_years=None,
        start_date=f"{year}-01-01", target_date=f"{year + HORIZON}-06-30",
        is_ongoing=0, frequency="jaehrlich", hardness="Hart", rank=1,
        weight_bps=5000, value_mode="real",
    )


_CACHE: dict = {}


def _measure(score: int, with_goal: bool) -> dict:
    key = (score, with_goal)
    if key not in _CACHE:
        inputs = dict(
            cma=_base_cma(),
            goals=[_certain_goal(score)] if with_goal else [],
            house_matrix_row=PROFILE_ROWS[score],
            score_x10=score * 10,
            # wie die Produktion (portfolio_engine_optimizer_integration):
            # Risky-Cap aus der Hausmatrix-Zeile.
            max_risky_fraction_bps=int(PROFILE_ROWS[score].max_risky_fraction_bps),
            advisory_wealth_rappen=WEALTH_CHF * 100,
            cashflow_series_rappen=[0] * HORIZON,
            horizon_years=HORIZON,
            n_paths=2000,
        )
        result = solver_module.run_solver(**inputs)
        block = result.resampling["house_prior"]
        probabilities = [
            float(r["probability"]) for r in result.goal_achievability if r.get("goal_id")
        ]
        _CACHE[key] = {
            "max_dev_bps": max(abs(int(v)) for v in block["deviation_vs_house_bps"].values()),
            "max_raw_bps": max(abs(int(v)) for v in block["deviation_vs_house_raw_bps"].values()),
            "probabilities": probabilities,
            "reason": block["reason"],
            "block": block,
        }
    return _CACHE[key]


def test_profiles_cover_scores_1_to_10():
    assert sorted(PROFILE_ROWS) == list(range(1, 11))


@pytest.mark.parametrize("score", range(1, 11))
def test_no_goals_deviation_within_bound(score):
    m = _measure(score, with_goal=False)
    print(f"\nProfil {score:2d} ohne Ziele: max |SAA - Hausquote(proj.)| = "
          f"{m['max_dev_bps']} bp, max |SAA - Hausmatrix roh| = {m['max_raw_bps']} bp ({m['reason']})")
    assert m["max_dev_bps"] <= NO_GOAL_MAX_DEVIATION_BPS
    block = m["block"]
    assert sum(block["deviation_vs_house_bps"].values()) == 0


@pytest.mark.parametrize("score", range(1, 11))
def test_certain_goal_deviation_within_bound(score):
    m = _measure(score, with_goal=True)
    print(f"\nProfil {score:2d} Ziel sicher (P={m['probabilities']}): max |SAA - Hausquote(proj.)| = "
          f"{m['max_dev_bps']} bp, roh {m['max_raw_bps']} bp ({m['reason']})")
    assert m["probabilities"] and min(m["probabilities"]) == 1.0
    assert m["max_dev_bps"] <= NO_GOAL_MAX_DEVIATION_BPS <= NO_PRESSURE_MAX_DEVIATION_BPS


def test_near_certain_withdrawal_goal_is_not_without_pressure():
    """Gegenprobe: Entnahmemandat E, Ziel fast sicher (P ~ 0.998) -> Zieldruck,
    Abweichung deutlich ueber der Schranke. ``ohne Zieldruck`` heisst also
    nicht ``Ziel fast sicher``."""
    inputs = _inputs("E_ausgewogen_entnahme", 0.40)
    result = solver_module.run_solver(**inputs)
    deviation = result.resampling["house_prior"]["deviation_vs_house_bps"]
    max_dev = max(abs(int(v)) for v in deviation.values())
    print(f"\nE_ausgewogen_entnahme 0.40: max |SAA - Hausquote(proj.)| = {max_dev} bp")
    assert max_dev > NO_PRESSURE_MAX_DEVIATION_BPS
