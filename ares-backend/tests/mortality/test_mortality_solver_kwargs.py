"""Kontrollrunde 2026-09-19: mandate_model_inputs.mortality_solver_kwargs_from_mandate.

Deckt den deterministischen Offset ab, der seit dem Mortalitaets-Fix in den
Solver einfliesst (statt eines pro-Pfad stochastisch gesampelten Sterbealters).
"""
from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from services.mandate_model_inputs import (
    MandateModelInputError,
    mortality_solver_kwargs_from_mandate,
)
from services.valuation_clock import bound_valuation_date


@pytest.fixture(autouse=True)
def _valuation_year_2026():
    """Die Mortalitaetsachse beginnt im Bewertungsjahr des Laufs
    (GOAL-AXIS-VALUATION-YEAR-001); die Faelle unten sind fuer 2026 gerechnet."""
    with bound_valuation_date(date(2026, 1, 15)):
        yield


def _mandate(**kw):
    base = dict(
        jurisdiction="CH",
        use_mortality_simulation=1,
        client_birth_year=1960,
        client_sex="M",
        life_expectancy_year=None,
        opened_at="2026-01-15",
    )
    base.update(kw)
    return SimpleNamespace(**base)


def test_feature_off_returns_empty_dict():
    assert mortality_solver_kwargs_from_mandate(
        _mandate(use_mortality_simulation=0)
    ) == {}


def test_feature_on_includes_deterministic_offset_matching_shared_helper():
    from services.mortality.horizon import expected_death_year_offset_from_mandate

    mandate = _mandate()
    kwargs = mortality_solver_kwargs_from_mandate(mandate)
    assert kwargs["use_mortality_simulation"] is True
    assert kwargs["client_birth_year"] == 1960
    assert kwargs["client_sex"] == "M"
    # Dieselbe Quelle wie der Report-Sterbe-Marker -- keine zweite,
    # potenziell abweichende Berechnung.
    assert kwargs["mortality_fixed_offset_years"] == (
        expected_death_year_offset_from_mandate(mandate)
    )
    assert kwargs["mortality_fixed_offset_years"] is not None


def test_manual_life_expectancy_year_takes_priority_over_bfs_default():
    mandate = _mandate(life_expectancy_year=2027)  # Bewertungsjahr 2026 -> 1 Jahr
    kwargs = mortality_solver_kwargs_from_mandate(mandate)
    assert kwargs["mortality_fixed_offset_years"] == 1


def test_offset_resolution_failure_fails_closed(monkeypatch):
    """Ein Fehler beim Ermitteln des Offsets darf ein aktiviertes,
    bereits validiertes Feature nicht still auf 'kein Cutoff' zurueckfallen
    lassen -- muss als MandateModelInputError propagieren."""
    import services.mandate_model_inputs as mmi

    def _broken(*_a, **_kw):
        raise RuntimeError("mortality table unavailable")

    monkeypatch.setattr(
        "services.mortality.horizon.expected_death_year_offset_from_mandate",
        _broken,
    )
    with pytest.raises(MandateModelInputError, match="death-year offset"):
        mortality_solver_kwargs_from_mandate(_mandate())


def test_reference_year_anchored_to_valuation_date_not_opened_at():
    """GOAL-AXIS-VALUATION-YEAR-001: das Bezugsjahr ist das Jahr des
    gebundenen Bewertungsstichtags. Ein anderes Eroeffnungsjahr aendert den
    Offset nicht; ein anderer Stichtag schon (BFS-Restlebenserwartung sinkt
    mit dem Alter, der fruehere Stichtag ergibt ein juengeres current_age)."""
    opened_long_ago = mortality_solver_kwargs_from_mandate(
        _mandate(opened_at="2000-01-15")
    )
    opened_this_year = mortality_solver_kwargs_from_mandate(
        _mandate(opened_at="2026-01-15")
    )
    assert (
        opened_long_ago["mortality_fixed_offset_years"]
        == opened_this_year["mortality_fixed_offset_years"]
    )
    with bound_valuation_date(date(2000, 1, 15)):
        earlier_valuation = mortality_solver_kwargs_from_mandate(_mandate())
    assert (
        earlier_valuation["mortality_fixed_offset_years"]
        != opened_this_year["mortality_fixed_offset_years"]
    )
