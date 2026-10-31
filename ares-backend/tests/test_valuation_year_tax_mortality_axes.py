"""GOAL-AXIS-VALUATION-YEAR-001: Steuer-, Alters- und Mortalitaetsachse ab dem
Bewertungsjahr des Laufs (CIO-Entscheid a, konsistent zu ADR-2).

Vorher rechneten Steuerkontext (``base_calendar_year``, ``mandate_age_at_start``),
Ruhestandsphase und Mortalitaets-Offset ab dem Eroeffnungsjahr des Mandats
(``opened_at``), waehrend Cashflow-, Ziel- und Reserve-Achse seit Engine v17
ab dem gebundenen Bewertungsstichtag laufen. Bei einem Mandat aus einem
Vorjahr lagen Steuerjahr, Alter und Sterbejahr-Cutoff damit um
(Bewertungsjahr - Eroeffnungsjahr) Jahre versetzt zur Spalte ``t``.

Jetzt gibt es genau eine Uhr: ``services.valuation_clock``. Diese Tests
binden einen Stichtag im Jahr Y, eroeffnen das Mandat im Jahr X = Y - 4 und
pruefen, dass jede Achse in Y beginnt -- im Solver, in der Zielanalyse und im
Bericht (Report-MC), auch beim Replay unter einer Wanduhr im Folgejahr.
"""
from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from services.mortality.horizon import (
    expected_death_year_offset_from_mandate,
    life_expectancy_year_from_mandate,
    mandate_reference_year,
    resolve_mortality_cutoff,
)
from services.portfolio_engine_optimizer_integration import (
    _build_retirement_phase_kwargs,
    _build_tax_solver_kwargs,
)
from services.valuation_clock import bound_valuation_date

VALUATION_DAY = date(2026, 5, 4)
Y = VALUATION_DAY.year
X = Y - 4


def _mandate(**kw):
    base = dict(
        opened_at=f"{X}-03-01",
        tax_jurisdiction="CH",
        tax_overrides_json=None,
        client_birth_year=Y - 60,
        client_sex="M",
        retirement_year=Y + 3,
        life_expectancy_year=None,
        jurisdiction="CH",
        use_mortality_simulation=1,
        client=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


# ── Einheiten: jede Achse aus derselben gebundenen Uhr ─────────────────────


def test_reference_year_is_the_bound_valuation_year_not_the_opening_year():
    with bound_valuation_date(VALUATION_DAY):
        assert mandate_reference_year(_mandate()) == Y


def test_tax_axis_and_age_start_in_valuation_year():
    with bound_valuation_date(VALUATION_DAY):
        kw = _build_tax_solver_kwargs(_mandate())
    assert kw["base_calendar_year"] == Y
    assert kw["mandate_age_at_start"] == 60


def test_retirement_phase_axis_starts_in_valuation_year():
    with bound_valuation_date(VALUATION_DAY):
        kw = _build_retirement_phase_kwargs(_mandate())
        retired_kw = _build_retirement_phase_kwargs(_mandate(retirement_year=Y - 1))
    assert kw["base_calendar_year"] == Y
    assert "is_retired" not in kw
    # Pensioniert im Vorjahr des Laufs, aber NACH der Eroeffnung: im
    # Bewertungsjahr ist die Person pensioniert.
    assert retired_kw["is_retired"] is True


def test_mortality_offset_counts_from_valuation_year():
    with bound_valuation_date(VALUATION_DAY):
        override = _mandate(life_expectancy_year=Y + 22)
        assert expected_death_year_offset_from_mandate(override) == 22
        assert resolve_mortality_cutoff(override) == ("fixed_override", 22)
        # BFS-Pfad: das absolute Sterbejahr haengt nicht vom Eroeffnungsjahr ab.
        old = life_expectancy_year_from_mandate(_mandate())
        same_year = life_expectancy_year_from_mandate(_mandate(opened_at=f"{Y}-01-02"))
    assert old == same_year


# ── End-to-End: Solver vs. Zielanalyse vs. Bericht, Replay im Folgejahr ────


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'valuation_year_axes.db'}",
        connect_args={"check_same_thread": False},
    )
    factory = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    from database import Base

    Base.metadata.create_all(bind=engine)
    try:
        yield factory
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


class _NextYearClock(date):
    @classmethod
    def today(cls):
        return date(Y + 1, 1, 15)


def test_generate_solver_goal_analysis_and_report_share_the_valuation_year(
    session_factory, monkeypatch,
):
    import services.advisory_report as advisory_report
    import services.optimizer.solver as solver_module
    import services.portfolio_engine as portfolio_engine
    import services.valuation_clock as valuation_clock
    from models.mandates import Mandate
    from services.monte_carlo_paths import report_mc_death_year_index
    from services.portfolio_engine_mc_simulation import _simulation_horizon_derivation
    from tests.test_golden_snapshot_ch_regression import _seed_ch_mandate

    advisor_id, _cid, mid, _aid = _seed_ch_mandate(
        session_factory, suffix="valyear", score_x10=50,
    )
    life_expectancy_year = Y + 22
    with session_factory() as s:
        mandate = s.get(Mandate, mid)
        mandate.opened_at = f"{X}-03-01"
        mandate.tax_jurisdiction = "CH"
        mandate.client_birth_year = Y - 60
        mandate.client_sex = "M"
        mandate.retirement_year = Y + 3
        mandate.use_mortality_simulation = 1
        mandate.life_expectancy_year = life_expectancy_year
        s.commit()

    contexts: list[dict] = []
    goal_offsets: list = []
    original_context = solver_module.build_optimizer_context
    original_goal_analysis = portfolio_engine._build_goal_analysis

    def _spy_context(**kwargs):
        contexts.append(dict(kwargs))
        return original_context(**kwargs)

    def _spy_goal_analysis(*args, **kwargs):
        goal_offsets.append(kwargs.get("expected_death_year_offset"))
        return original_goal_analysis(*args, **kwargs)

    monkeypatch.setattr(solver_module, "build_optimizer_context", _spy_context)
    monkeypatch.setattr(portfolio_engine, "_build_goal_analysis", _spy_goal_analysis)

    expected_offset = life_expectancy_year - Y
    with session_factory() as s:
        mandate = s.get(Mandate, mid)
        with bound_valuation_date(VALUATION_DAY):
            result = portfolio_engine.generate_target_allocation(
                s, mandate, advisor_id, preferences=None,
            )
        allocation = result["target_allocation"]
        s.commit()
        assert allocation.valuation_date == VALUATION_DAY.isoformat()

        # Solver: Steuerjahr, Alter, Ruhestandsphase und Sterbe-Cutoff ab Y.
        assert contexts, "Solver-Kontext wurde nicht gebaut"
        solver_kw = contexts[0]
        assert solver_kw["base_calendar_year"] == Y
        assert solver_kw["mandate_age_at_start"] == 60
        assert solver_kw["retirement_calendar_year"] == Y + 3
        assert solver_kw["mortality_fixed_offset_years"] == expected_offset
        # Zielanalyse: derselbe Cutoff wie der Solver.
        assert goal_offsets and set(goal_offsets) == {expected_offset}
        reasoning = " ".join(str(line) for line in result.get("reasoning") or [])
        assert f"Mortalitaets-Horizont bis {life_expectancy_year}" in reasoning

        # Bericht (Report-MC) unter einer Wanduhr im Folgejahr: liest den
        # gespeicherten Stichtag, Cutoff und Horizont bleiben auf Y.
        monkeypatch.setattr(valuation_clock, "date", _NextYearClock)
        section = advisory_report._build_monte_carlo_paths_section(s, mandate)
        with bound_valuation_date(VALUATION_DAY):
            horizon = _simulation_horizon_derivation(
                [], mandate,
            )
        assert horizon["components"]["life_expectancy"] == life_expectancy_year - Y + 1
        assert section["projection_status"] == "current"
        assert section["mortality_mode"] == "fixed_override"
        assert section["mortality_cutoff_year_index"] == report_mc_death_year_index(
            expected_offset, horizon_years=int(section["horizon_years"]),
        ) == expected_offset
