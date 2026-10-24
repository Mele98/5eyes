"""MORT-CHANNEL-001 (Codex-Review PR #644, Vertrag 2): Feature-off-Paritaet.

Ist ``Mandate.use_mortality_simulation`` aus, wendet der Solver bewusst
KEINE Mortalitaets-Transformation an (``mortality_solver_kwargs_from_mandate``
liefert ``{}``). Jeder andere Consumer -- deterministische Zielanalyse im
Allocation-Payload (API/PDF), Report-Monte-Carlo -- muss dieselbe Semantik
haben: ``disabled`` heisst ueberall "kein Cutoff". Vorher schnitt die
Report-Zielanalyse trotz Feature-off am BFS-Median ab (Minimalmandat:
20 Jahre), d.h. derselbe Mandatszustand hatte zwei Mortalitaetsmodelle.

Uebernommen aus dem Codex-Reproducer
``docs/audits/reproducers/test_2026_10_18_mortality_p80_last_survivor_pr644_adversarial.py``
(nur Vertrag 2; Vertrag 1 -- Priority-Rekonstruktion -- liegt in
``services/optimizer/objective.py`` und wird separat bearbeitet).
"""
from __future__ import annotations

from datetime import date

import numpy as np
import pytest

from services.mandate_model_inputs import mortality_solver_kwargs_from_mandate
from services.mortality.horizon import resolve_mortality_cutoff
from services.portfolio_engine_payload import (
    _build_goal_analysis,
    _expected_death_year_offset_from_mandate,
)
from tests.mortality.test_mortality_planning_quantile_last_survivor import (
    _couple_client,
    _mandate,
)


# ---------------------------------------------------------------------------
# Codex-Vertrag (ohne xfail)
# ---------------------------------------------------------------------------


def test_feature_off_report_and_solver_share_the_same_mortality_contract():
    """Feature-off cannot mean no solver cutoff but a report-side median."""
    mandate = _mandate(use_mortality_simulation=0)

    assert mortality_solver_kwargs_from_mandate(mandate) == {}
    assert _expected_death_year_offset_from_mandate(mandate) is None


# ---------------------------------------------------------------------------
# Ein Resolver, explizite Modi
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "overrides",
    [
        {},
        {"client": _couple_client()},
        # Auch ein gepflegter Berater-Override ist bei Feature-off KEIN Cutoff:
        # der Solver ignoriert ihn ebenfalls (kwargs == {}).
        {"life_expectancy_year": date.today().year + 7},
        {"jurisdiction": "DE"},
    ],
)
def test_disabled_mode_is_explicit_and_cutoff_free_for_every_input(overrides):
    mandate = _mandate(use_mortality_simulation=0, **overrides)

    assert resolve_mortality_cutoff(mandate) == ("disabled", None)
    assert _expected_death_year_offset_from_mandate(mandate) is None
    assert mortality_solver_kwargs_from_mandate(mandate) == {}


@pytest.mark.parametrize("flag", [0, None, False])
def test_every_off_representation_is_disabled(flag):
    assert resolve_mortality_cutoff(_mandate(use_mortality_simulation=flag)) == (
        "disabled", None,
    )


def test_enabled_planning_quantile_matches_solver_cutoff():
    mandate = _mandate(client=_couple_client())
    mode, offset = resolve_mortality_cutoff(mandate)

    assert mode == "planning_quantile"
    assert offset == mortality_solver_kwargs_from_mandate(mandate)[
        "mortality_fixed_offset_years"
    ]
    assert _expected_death_year_offset_from_mandate(mandate) == offset


def test_enabled_override_is_named_fixed_override_and_matches_solver():
    mandate = _mandate(opened_at=None, life_expectancy_year=date.today().year + 9)
    mode, offset = resolve_mortality_cutoff(mandate)

    assert mode == "fixed_override"
    assert offset == 9
    assert offset == mortality_solver_kwargs_from_mandate(mandate)[
        "mortality_fixed_offset_years"
    ]


# ---------------------------------------------------------------------------
# Deterministische Zielanalyse (Allocation-Payload -> API/PDF)
# ---------------------------------------------------------------------------


class _Goal:
    def __init__(self, **kw):
        defaults = dict(
            id="g-1", label="Entnahme", goal_type="Vermoegensziel",
            rank=1, hardness="weich", target_wealth_rappen=10_000_000,
            target_amount_rappen=0, target_return_bps=None,
            target_date=f"{date.today().year + 30}-12-31",
            start_date=None, is_ongoing=0, frequency=None,
            goal_scope=None, probability_bps=None, weight_bps=0,
            pension_pillar=None, deleted_at=None, inflation_adjusted=0,
        )
        defaults.update(kw)
        for key, value in defaults.items():
            setattr(self, key, value)


def test_goal_analysis_without_cutoff_counts_all_cashflows_when_feature_off():
    """Feature-off-Mandat -> Wrapper None -> die volle Cashflow-Reihe fliesst
    in die deterministische Projektion, exakt wie im Solver (keine Maske)."""
    from models.allocation import OptimizerPolicy

    mandate = _mandate(use_mortality_simulation=0)
    offset = _expected_death_year_offset_from_mandate(mandate)
    policy = OptimizerPolicy(goal_score_alpha_bps=5000) if hasattr(
        OptimizerPolicy, "goal_score_alpha_bps"
    ) else OptimizerPolicy()
    kwargs = dict(
        goals=[_Goal()],
        advisory_wealth_rappen=0,
        total_wealth_rappen=0,
        cashflow_projection_series_rappen=[100_000] * 40,
        inflation_series_bps=[0] * 40,
        expected_return_bps=0,
        reserve_needed_rappen=0,
        policy=policy,
    )
    feature_off = _build_goal_analysis(**kwargs, expected_death_year_offset=offset)
    no_cutoff = _build_goal_analysis(**kwargs, expected_death_year_offset=None)
    median_cutoff = _build_goal_analysis(**kwargs, expected_death_year_offset=20)

    assert feature_off == no_cutoff
    # Gegenprobe: ein Cutoff waere sichtbar (der Test misst also etwas).
    assert median_cutoff != no_cutoff


# ---------------------------------------------------------------------------
# Report-Monte-Carlo: derselbe Vertrag wie der Solver
# ---------------------------------------------------------------------------


def test_report_mc_core_masks_cashflows_only_when_cutoff_given(session_factory):
    """Mit Cutoff-Index werden Netto-Cashflows ab dem Index (wie im Solver,
    ``simulate_wealth_paths(death_year_index_per_path=...)``) nicht mehr
    gebucht; ohne Cutoff (Feature-off) laufen sie ueber den ganzen Horizont."""
    from services.monte_carlo_paths import _compute_paths_core
    from tests.test_monte_carlo_paths import _seed_advisor, _seed_cma

    with session_factory() as s:
        advisor = _seed_advisor(s)
        cma = _seed_cma(s, advisor)
        s.commit()
        common = dict(
            initial_wealth_rappen=50_000_000,
            horizon_years=20,
            weights=np.array([0.4, 0.35, 0.1, 0.1, 0.05]),
            cma=cma,
            cashflow_series=[-2_000_000] * 20,
            n_paths=200,
            seed=7,
        )
        disabled = _compute_paths_core(**common)
        explicit_none = _compute_paths_core(**common, death_year_index=None)
        cut = _compute_paths_core(**common, death_year_index=5)

    assert disabled == explicit_none
    # Bis zum Cutoff identisch (dieselben Renditepfade, dieselben Abfluesse) ...
    assert cut["p50"][:6] == disabled["p50"][:6]
    # ... danach keine Entnahmen mehr -> hoeheres Endvermoegen.
    assert cut["p50"][-1] > disabled["p50"][-1]


@pytest.fixture()
def session_factory(tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    import tests.test_monte_carlo_paths  # noqa: F401  (Mapper/Modelle laden)
    from database import Base

    engine = create_engine(
        f"sqlite:///{tmp_path / 'mort_parity.db'}",
        connect_args={"check_same_thread": False},
    )
    SF = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield SF
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_report_mc_death_index_matches_solver_clip_convention():
    from services.monte_carlo_paths import report_mc_death_year_index

    assert report_mc_death_year_index(None, horizon_years=20) is None
    # Solver: np.clip(offset, 1, horizon)
    for offset in (0, 1, 5, 20, 99):
        assert report_mc_death_year_index(offset, horizon_years=20) == int(
            np.clip(offset, 1, 20)
        )
