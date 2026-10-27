"""DYNAMIC-RETIREMENT-PHASE-001: ``is_retired`` jahresweise statt statisch.

Vorher galt ein einziger Wahrheitswert (``Bewertungsjahr >= retirement_year``)
fuer ALLE Simulationsjahre: keine Phase wechselte bei der Pensionierung. Die
Tests belegen den jahresgenauen Wechsel im Steuerkontext (mit einem
Probe-Regime, das -- wie ein kuenftiges CH-Saeule-3a-Regime -- auf
``ctx.is_retired`` verzweigt), die Aufloesung des Pensionierungsjahrs inkl.
Planungsannahme/Partner, das Vor-Verhalten ohne Pensionierungsjahr (plus
Hinweis) und die Entkopplung von der Steuerbasis.
"""
from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import numpy as np
import pytest

from services.optimizer.scenario_engine import N_BUCKETS, simulate_wealth_paths
from services.retirement_phase import (
    PRIMARY_SOURCE_MANDATE,
    PRIMARY_SOURCE_PLANNING,
    RetirementPhase,
    is_retired_in_year,
    resolve_retirement_phase,
    retirement_phase_note,
    retirement_status_series,
)


@dataclass(frozen=True)
class _WT:
    effective_bps: float
    amount_rappen: float = 0.0


class _PhaseProbeRegime:
    """Vermoegenssteuer 100 bps NUR in der Erwerbsphase (Probe, kein Tarif)."""

    supports_wealth_tax = True

    def __init__(self) -> None:
        self.seen: list[tuple[int, bool]] = []

    def annual_wealth_tax(self, ctx):
        self.seen.append((ctx.year_index, ctx.is_retired))
        return _WT(effective_bps=0.0 if ctx.is_retired else 100.0)


def _flat_paths(n_paths: int, horizon: int) -> np.ndarray:
    return np.ones((n_paths, horizon, N_BUCKETS), dtype=np.float64)


# ── Serie ────────────────────────────────────────────────────────────────


def test_series_switches_exactly_in_retirement_year() -> None:
    assert retirement_status_series(2026, 6, 2029) == (
        False, False, False, True, True, True,
    )
    assert retirement_status_series(2026, 3, 2020) == (True, True, True)
    assert retirement_status_series(2026, 3, 2040) == (False, False, False)
    assert retirement_status_series(2026, 3, None) is None


def test_missing_series_keeps_static_flag() -> None:
    assert is_retired_in_year(None, 7, default=True) is True
    assert is_retired_in_year(None, 7, default=False) is False
    assert is_retired_in_year((False, True), 9) is True  # jenseits: letzter Wert


# ── Rechengroesse: Steuerkontext vor/nach Pensionierung ─────────────────


def test_tax_context_phase_changes_in_retirement_year() -> None:
    regime = _PhaseProbeRegime()
    wealth = simulate_wealth_paths(
        initial_wealth_rappen=1_000_000_00,
        weights=np.full(N_BUCKETS, 1.0 / N_BUCKETS),
        return_paths=_flat_paths(4, 6),
        cashflow_series_rappen=[0] * 6,
        tax_regime=regime,
        base_calendar_year=2026,
        is_retired_series=retirement_status_series(2026, 6, 2029),
    )
    status_by_year = dict(regime.seen)
    assert [status_by_year[t] for t in range(6)] == [
        False, False, False, True, True, True,
    ]
    # Erwerbsphase: 1 % Steuer je Jahr; Ruhestand: keine -> Pfad flach.
    w = wealth[0]
    assert w[1] < w[0] and w[2] < w[1] and w[3] < w[2]
    assert w[3] == pytest.approx(1_000_000_00 * 0.99 ** 3)
    assert w[4] == w[3] and w[5] == w[3] and w[6] == w[3]


def test_static_flag_without_series_is_unchanged_behaviour() -> None:
    """Ohne Serie: altes Verhalten -- ein Status fuer alle Jahre."""
    regime = _PhaseProbeRegime()
    wealth = simulate_wealth_paths(
        initial_wealth_rappen=1_000_000_00,
        weights=np.full(N_BUCKETS, 1.0 / N_BUCKETS),
        return_paths=_flat_paths(2, 4),
        cashflow_series_rappen=[0] * 4,
        tax_regime=regime,
        is_retired=False,
    )
    assert {flag for _t, flag in regime.seen} == {False}
    assert wealth[0][-1] == pytest.approx(1_000_000_00 * 0.99 ** 4)


# ── Aufloesung des Pensionierungsjahrs ──────────────────────────────────


def test_mandate_retirement_year_has_priority() -> None:
    mandate = SimpleNamespace(retirement_year=2031, client_birth_year=1970)
    pa = SimpleNamespace(retirement_age_primary=60, retirement_age_partner=64)
    client = SimpleNamespace(date_of_birth="1970-05-01", partner_date_of_birth="1972-02-02")
    phase = resolve_retirement_phase(mandate, client=client, planning_assumption=pa)
    assert phase == RetirementPhase(2031, PRIMARY_SOURCE_MANDATE, 2036)


def test_planning_assumption_fallback_and_partner() -> None:
    mandate = SimpleNamespace(retirement_year=None, client_birth_year=1970)
    pa = SimpleNamespace(retirement_age_primary=63, retirement_age_partner=64)
    client = SimpleNamespace(date_of_birth="1971-05-01", partner_date_of_birth="1973-02-02")
    phase = resolve_retirement_phase(mandate, client=client, planning_assumption=pa)
    # client.date_of_birth geht vor mandate.client_birth_year
    assert phase.retirement_year == 1971 + 63
    assert phase.source == PRIMARY_SOURCE_PLANNING
    assert phase.partner_retirement_year == 1973 + 64
    assert phase.partner_series(2035, 3) == (False, False, True)


def test_missing_retirement_year_keeps_old_behaviour_and_says_so() -> None:
    mandate = SimpleNamespace(retirement_year=None, client_birth_year=None)
    phase = resolve_retirement_phase(mandate, client=None, planning_assumption=None,
                                     load_planning_assumption=False)
    assert phase.retirement_year is None
    assert phase.series(2026, 5) is None
    assert phase.is_retired_at(2100) is False
    note = retirement_phase_note(phase, reference_year=2026, horizon_years=10)
    assert "kein Pensionierungsjahr" in note and "wie bisher" in note


def test_note_names_the_switch_year() -> None:
    phase = RetirementPhase(2030, PRIMARY_SOURCE_MANDATE, 2032)
    note = retirement_phase_note(phase, reference_year=2026, horizon_years=10)
    assert "Erwerbsphase 2026-2029" in note
    assert "Ruhestandsphase ab 2030" in note
    assert "Partner: Pensionierung 2032" in note


# ── Engine-Verdrahtung ──────────────────────────────────────────────────


def _valuation_year_2026():
    """t = 0 ist das Bewertungsjahr des Laufs (GOAL-AXIS-VALUATION-YEAR-001)."""
    from datetime import date

    from services.valuation_clock import bound_valuation_date

    return bound_valuation_date(date(2026, 1, 15))


def _mandate(**kw):
    base = dict(
        tax_jurisdiction=None, tax_overrides_json=None, opened_at="2026-01-15",
        client_birth_year=None, retirement_year=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def test_solver_kwargs_carry_retirement_year_without_tax_jurisdiction() -> None:
    """Vorher: ohne tax_jurisdiction fehlte is_retired ganz (Steuer-Kopplung)."""
    from services.portfolio_engine import _build_tax_solver_kwargs

    with _valuation_year_2026():
        retired = _build_tax_solver_kwargs(_mandate(retirement_year=2020))
        future = _build_tax_solver_kwargs(_mandate(retirement_year=2030))
    assert retired["is_retired"] is True
    assert retired["retirement_calendar_year"] == 2020
    assert retired["base_calendar_year"] == 2026

    assert "is_retired" not in future
    assert future["retirement_calendar_year"] == 2030


def test_solver_kwargs_with_jurisdiction_keep_start_status() -> None:
    from services.portfolio_engine import _build_tax_solver_kwargs

    with _valuation_year_2026():
        kw = _build_tax_solver_kwargs(
            _mandate(tax_jurisdiction="CH", retirement_year=2029, client_birth_year=1966)
        )
    assert kw["tax_regime"] is not None
    assert kw["retirement_calendar_year"] == 2029
    assert kw["base_calendar_year"] == 2026
    assert "is_retired" not in kw


def test_optimizer_context_builds_series_and_uses_it_in_simulation() -> None:
    from services.optimizer.scenario_cache import get_default_cache
    from services.optimizer.solver import (
        _simulate_context_wealth,
        build_optimizer_context,
    )
    from tests.test_engine_input_sensitivity import _cma, _goal, _hm_wachstum

    get_default_cache().clear()
    regime = _PhaseProbeRegime()
    ctx = build_optimizer_context(
        cma=_cma(id="cma-phase"), goals=[_goal()],
        house_matrix_row=_hm_wachstum(), score_x10=80,
        advisory_wealth_rappen=1_000_000_00,
        cashflow_series_rappen=[0] * 11, horizon_years=10,
        n_paths=60, seed=7,
        tax_regime=regime, base_calendar_year=2026,
        retirement_calendar_year=2030,
    )
    assert ctx.is_retired_series == tuple(2026 + t >= 2030 for t in range(10))
    assert ctx.is_retired is False  # Startjahr = Erwerbsphase

    regime.seen.clear()
    _simulate_context_wealth(ctx, np.full(N_BUCKETS, 1.0 / N_BUCKETS))
    flags = {}
    for t, flag in regime.seen:
        flags.setdefault(t, set()).add(flag)
    assert flags[0] == {False} and flags[3] == {False}
    assert flags[4] == {True} and flags[9] == {True}


def test_retired_at_start_activates_is_without_tax_jurisdiction(monkeypatch) -> None:
    """Bestehende IS-Regel (Decumulation) greift jetzt auch ohne Steuersitz."""
    from config import settings
    from services.optimizer.scenario_cache import get_default_cache
    from services.optimizer.solver import build_optimizer_context
    from services.portfolio_engine import _build_tax_solver_kwargs
    from tests.test_engine_input_sensitivity import _cma, _goal, _hm_wachstum

    monkeypatch.setattr(settings, "mc_importance_sampling_auto_enable", True, raising=False)
    monkeypatch.setattr(settings, "mc_importance_sampling_enabled", False, raising=False)
    get_default_cache().clear()
    kw = _build_tax_solver_kwargs(_mandate(retirement_year=2020))
    ctx = build_optimizer_context(
        cma=_cma(id="cma-phase-is"), goals=[_goal(hardness="Primär")],
        house_matrix_row=_hm_wachstum(), score_x10=80,
        advisory_wealth_rappen=1_000_000_00,
        cashflow_series_rappen=[0] * 11, horizon_years=10,
        n_paths=60, seed=9, **kw,
    )
    assert ctx.is_retired is True
    assert ctx.scenario_weights is not None


# ── Input-Snapshot-Hash (CIO-Entscheid zu #670) ─────────────────────────


@pytest.fixture()
def db_session(tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import configure_mappers, sessionmaker

    from database import Base
    from models import (  # noqa: F401
        allocation, clients, mandates, profiling, review, snapshots, users, wealth,
    )
    from models import tenant as _tenant  # noqa: F401

    configure_mappers()
    engine = create_engine(
        f"sqlite:///{tmp_path / 'retirement_phase_hash.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(
        autocommit=False, autoflush=False, expire_on_commit=False, bind=engine,
    )
    s = factory()
    try:
        yield s
    finally:
        s.close()
        engine.dispose()


def _allocation_under_pre_update_hash(s, monkeypatch, *, retirement_year, pa_age):
    """Foundation-Mandat konfigurieren und die Allokation mit dem Hash-Aufbau
    VOR diesem Update (ohne Phasenfeld) erzeugen."""
    import services.retirement_phase as rp
    from models.allocation import TargetAllocation
    from models.mandates import Mandate
    from models.users import User
    from models.wealth import PlanningAssumption
    from services.foundation_example import (
        FOUNDATION_MANDATE_NUMBER,
        upsert_foundation_example_case,
    )
    from services.portfolio_engine import generate_target_allocation

    monkeypatch.setattr(rp, "retirement_phase_snapshot_fields", lambda mandate: {})
    adv = User(
        id="advisor-1", username="advisor", password_hash="h", full_name="Advisor",
        role="advisor", is_active=1,
        created_at="2026-03-27T00:00:00.000Z", updated_at="2026-03-27T00:00:00.000Z",
    )
    s.add(adv)
    s.commit()
    upsert_foundation_example_case(s, adv)
    s.commit()
    mandate = s.query(Mandate).filter(
        Mandate.mandate_number == FOUNDATION_MANDATE_NUMBER
    ).one()
    mandate.tax_jurisdiction = None
    mandate.tax_overrides_json = None
    mandate.tax_estimate_in_cashflow_enabled = 0
    mandate.retirement_year = retirement_year
    for pa in s.query(PlanningAssumption).filter(
        PlanningAssumption.mandate_id == mandate.id
    ):
        pa.retirement_age_primary = pa_age
        pa.retirement_age_partner = None
    s.commit()
    generate_target_allocation(db=s, mandate=mandate, user_id=adv.id, preferences=None)
    s.commit()
    ta = s.query(TargetAllocation).filter(
        TargetAllocation.mandate_id == mandate.id,
        TargetAllocation.is_current == 1,
        TargetAllocation.deleted_at.is_(None),
    ).one()
    assert ta.input_snapshot_hash
    return mandate, ta


def test_retired_mandate_without_tax_seat_is_stale_after_update(db_session, monkeypatch):
    from services.allocation_input_staleness import allocation_inputs_stale

    mandate, ta = _allocation_under_pre_update_hash(
        db_session, monkeypatch, retirement_year=2020, pa_age=None,
    )
    # Positivkontrolle: unter dem alten Hash-Aufbau ist sie aktuell.
    assert allocation_inputs_stale(db_session, mandate, ta) is False
    monkeypatch.undo()
    assert allocation_inputs_stale(db_session, mandate, ta) is True


def test_mandate_without_retirement_year_stays_current(db_session, monkeypatch):
    from services.allocation_input_staleness import allocation_inputs_stale

    mandate, ta = _allocation_under_pre_update_hash(
        db_session, monkeypatch, retirement_year=None, pa_age=None,
    )
    assert allocation_inputs_stale(db_session, mandate, ta) is False
    monkeypatch.undo()
    assert allocation_inputs_stale(db_session, mandate, ta) is False


def test_snapshot_field_only_with_retirement_year() -> None:
    from services.retirement_phase import retirement_phase_snapshot_fields

    none = SimpleNamespace(retirement_year=None, client_birth_year=1960, client=None)
    assert retirement_phase_snapshot_fields(none) == {}
    some = SimpleNamespace(retirement_year=2031, client_birth_year=1966, client=None)
    assert retirement_phase_snapshot_fields(some)["retirement_phase"][
        "retirement_calendar_year"
    ] == 2031
