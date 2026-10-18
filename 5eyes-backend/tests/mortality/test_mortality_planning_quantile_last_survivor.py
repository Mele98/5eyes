"""MORTALITY-HORIZON-P80-LS-001 (CIO-Entscheid 2026-10-18).

Befund (Variablen-Audit 2026-10, Abschnitt Lebenserwartung):
1. Der Mortalitaets-Horizont (``use_mortality_simulation`` aktiv) nutzte den
   BFS-MEDIAN der Restlebensdauer -- 50 % der Kunden leben laenger als der
   Plan. Fuer einen Vermoegensverzehr ist das die falsche Richtung.
2. Der Solver-Cutoff (``mortality_solver_kwargs_from_mandate``) rief den
   Horizont OHNE ``client`` auf und ignorierte damit den Partner: bei einem
   Ehepaar endeten Haushaltsausgaben im Modell mit dem Median-Tod des
   Hauptkunden, obwohl der Partner weiterlebt.

CIO-Entscheide:
- Horizont = 80-%-Quantil der Lebensdauer: kleinstes t mit S(t) <= 0.20.
- Paar: 80-%-Quantil des Todes der LETZTVERSTERBENDEN Person,
  S_LS(t) = 1 - (1 - S_A(t)) * (1 - S_B(t)) (Unabhaengigkeitsannahme).
- Fehlende Partnerdaten -> Einzelperson + Hinweis im Reasoning.
- ``use_mortality_simulation`` aus -> Verhalten unveraendert.

Das Orakel in diesen Tests rechnet die Ueberlebensfunktion direkt aus den
einjaehrigen q(x) der Tafel nach -- bewusst NICHT ueber
``survival_curve`` oder den produktiven Helfer, damit ein Fehler in der
Produktionsformel nicht im Orakel gespiegelt wird.
"""
from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from services.mortality.bfs import BFS_2020_2022


REF_YEAR = 2026


def _mandate(**kw):
    base = dict(
        jurisdiction="CH",
        use_mortality_simulation=1,
        client_birth_year=1960,
        client_sex="M",
        life_expectancy_year=None,
        opened_at=f"{REF_YEAR}-01-15",
        client=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def _client(**kw):
    base = dict(
        date_of_birth=None,
        salutation=None,
        partner_date_of_birth=None,
        partner_salutation=None,
        partner_first_name=None,
        partner_last_name=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def _couple_client():
    # Hauptkunde Mann 1960 (66 J. in 2026), Partnerin Frau 1962 (64 J.).
    return _client(
        partner_date_of_birth="1962-03-01",
        partner_salutation="Frau",
        partner_first_name="Anna",
    )


# ---------------------------------------------------------------------------
# Unabhaengiges Orakel
# ---------------------------------------------------------------------------

def _oracle_survival(age: int, sex: str, t: int) -> float:
    s = 1.0
    for k in range(t):
        s *= 1.0 - float(BFS_2020_2022.qx(age + k, sex))
    return s


def _oracle_quantile_offset(persons, threshold=0.20) -> int:
    """Kleinstes t >= 1, bei dem P(mindestens eine Person lebt) <= threshold."""
    for t in range(1, 200):
        p_all_dead = 1.0
        for age, sex in persons:
            p_all_dead *= 1.0 - _oracle_survival(age, sex, t)
        if 1.0 - p_all_dead <= threshold:
            return t
    raise AssertionError("Orakel fand kein Quantil")


# ---------------------------------------------------------------------------
# Konstante + reine Mathematik
# ---------------------------------------------------------------------------

def test_planning_quantile_constant_is_versioned_80_percent():
    from services.mortality import horizon

    assert horizon.MORTALITY_PLANNING_QUANTILE == 0.80
    assert isinstance(horizon.MORTALITY_PLANNING_QUANTILE_VERSION, str)
    assert horizon.MORTALITY_PLANNING_QUANTILE_VERSION


def test_quantile_offset_uses_less_or_equal_on_discrete_survival():
    from services.mortality.horizon import quantile_offset_from_survival

    # S(0)=1, S(1)=0.9, S(2)=0.5, S(3)=0.2, S(4)=0.1
    survival = [1.0, 0.9, 0.5, 0.2, 0.1]
    # P80: kleinstes t mit S(t) <= 0.20 -> t=3 (Grenzwert inklusive)
    assert quantile_offset_from_survival(survival, 0.80) == 3
    # Kurve erreicht die Schwelle nie -> erstes Jahr nach Tafelende
    assert quantile_offset_from_survival([1.0, 0.9, 0.8], 0.80) == 3


def test_last_survivor_combination_formula():
    from services.mortality.horizon import last_survivor_survival

    a = [1.0, 0.5, 0.2]
    b = [1.0, 0.4]  # kuerzere Tafel: danach 0
    combined = last_survivor_survival([a, b])
    assert combined == pytest.approx([1.0, 1 - 0.5 * 0.6, 1 - 0.8 * 1.0])


# ---------------------------------------------------------------------------
# Feature AN: P80 statt Median, Einzelperson
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "sex,expected_p80,legacy_median",
    [("M", 26, 20), ("F", 29, 23)],
)
def test_feature_on_single_uses_p80_instead_of_median(sex, expected_p80, legacy_median):
    from services.mortality.horizon import expected_death_year_offset_from_mandate

    on = expected_death_year_offset_from_mandate(_mandate(client_sex=sex))
    off = expected_death_year_offset_from_mandate(
        _mandate(client_sex=sex, use_mortality_simulation=0)
    )
    assert on == expected_p80 == _oracle_quantile_offset([(66, sex)])
    assert off == legacy_median  # Feature AUS: unveraendert


@pytest.mark.parametrize("age,sex", [(40, "M"), (50, "F"), (80, "M"), (95, "F")])
def test_feature_on_single_matches_independent_oracle(age, sex):
    from services.mortality.horizon import expected_death_year_offset_from_mandate

    mandate = _mandate(client_birth_year=REF_YEAR - age, client_sex=sex)
    assert expected_death_year_offset_from_mandate(mandate) == (
        _oracle_quantile_offset([(age, sex)])
    )


# ---------------------------------------------------------------------------
# Feature AN: Paar = last survivor
# ---------------------------------------------------------------------------

def test_feature_on_couple_uses_last_survivor_p80():
    from services.mortality.horizon import expected_death_year_offset_from_mandate

    mandate = _mandate(client=_couple_client())
    offset = expected_death_year_offset_from_mandate(mandate)
    assert offset == _oracle_quantile_offset([(66, "M"), (64, "F")]) == 32
    # Joint-life ist strenger als das Maximum der Einzel-Quantile (31):
    # die Chance, dass MINDESTENS einer noch lebt, ist hoeher.
    assert offset > max(
        _oracle_quantile_offset([(66, "M")]), _oracle_quantile_offset([(64, "F")])
    )


@pytest.mark.parametrize("partner_age,partner_sex", [(60, "F"), (70, "M"), (45, "F")])
def test_feature_on_couple_matches_independent_oracle(partner_age, partner_sex):
    from services.mortality.horizon import expected_death_year_offset_from_mandate

    client = _client(
        partner_date_of_birth=f"{REF_YEAR - partner_age}-07-01",
        partner_salutation="Herr" if partner_sex == "M" else "Frau",
    )
    mandate = _mandate(client=client)
    assert expected_death_year_offset_from_mandate(mandate) == (
        _oracle_quantile_offset([(66, "M"), (partner_age, partner_sex)])
    )


def test_feature_off_couple_keeps_legacy_max_of_medians():
    from services.mortality.horizon import expected_death_year_offset_from_mandate

    mandate = _mandate(client=_couple_client(), use_mortality_simulation=0)
    # Legacy-Semantik (explizit uebergebener client): max(20, 24) = 24
    assert expected_death_year_offset_from_mandate(
        mandate, client=mandate.client
    ) == 24
    # Legacy ohne client-Argument: Partner wird (wie bisher) nicht gelesen
    assert expected_death_year_offset_from_mandate(mandate) == 20


def test_manual_override_still_wins_with_feature_on():
    from services.mortality.horizon import expected_death_year_offset_from_mandate

    mandate = _mandate(life_expectancy_year=2040, client=_couple_client())
    assert expected_death_year_offset_from_mandate(mandate) == 14


def test_non_ch_still_has_no_cutoff_with_feature_on():
    from services.mortality.horizon import expected_death_year_offset_from_mandate

    assert expected_death_year_offset_from_mandate(_mandate(jurisdiction="DE")) is None


# ---------------------------------------------------------------------------
# Solver-Cutoff: Partner wird jetzt beruecksichtigt
# ---------------------------------------------------------------------------

def test_solver_kwargs_include_partner_via_mandate_client():
    from services.mandate_model_inputs import mortality_solver_kwargs_from_mandate

    kwargs = mortality_solver_kwargs_from_mandate(_mandate(client=_couple_client()))
    assert kwargs["mortality_fixed_offset_years"] == 32


def test_solver_kwargs_feature_off_unchanged():
    from services.mandate_model_inputs import mortality_solver_kwargs_from_mandate

    assert mortality_solver_kwargs_from_mandate(
        _mandate(use_mortality_simulation=0, client=_couple_client())
    ) == {}


def test_report_marker_matches_solver_cutoff_for_couple():
    """Report-Sterbe-Marker und Solver-Cutoff duerfen nicht divergieren."""
    from services.mandate_model_inputs import mortality_solver_kwargs_from_mandate
    from services.portfolio_engine_payload import _expected_death_year_offset_from_mandate

    mandate = _mandate(client=_couple_client())
    assert _expected_death_year_offset_from_mandate(mandate) == (
        mortality_solver_kwargs_from_mandate(mandate)["mortality_fixed_offset_years"]
    )


# ---------------------------------------------------------------------------
# Projektionshorizont muss den Cutoff tragen (sonst waere P80 wirkungslos)
# ---------------------------------------------------------------------------

def test_simulation_horizon_extends_to_p80_last_survivor_when_feature_on():
    from services.portfolio_engine_mc_simulation import _simulation_horizon_years

    today = date.today()
    client = _client(
        partner_date_of_birth=f"{today.year - 64}-03-01", partner_salutation="Frau",
    )
    common = dict(
        opened_at=today.isoformat(), client_birth_year=today.year - 66, client=client,
    )
    on = _simulation_horizon_years({}, [], _mandate(**common))
    off = _simulation_horizon_years(
        {}, [], _mandate(use_mortality_simulation=0, **common)
    )
    assert off == 24 + 1  # legacy: max der Mediane (inkl. Partner) + 1
    assert on == 32 + 1   # P80 last survivor + 1


# ---------------------------------------------------------------------------
# Hinweis im Reasoning
# ---------------------------------------------------------------------------

def test_note_mentions_last_survivor_for_couple():
    from services.mortality.horizon import mortality_planning_horizon_note

    note = mortality_planning_horizon_note(_mandate(client=_couple_client()))
    assert note is not None
    assert "80" in note and "Letztversterbend" in note
    assert "Unabhaengigkeit" in note


def test_note_flags_single_person_when_partner_data_incomplete():
    from services.mortality.horizon import (
        expected_death_year_offset_from_mandate,
        mortality_planning_horizon_note,
    )

    client = _client(partner_first_name="Anna", partner_salutation="Frau")
    mandate = _mandate(client=client)
    assert expected_death_year_offset_from_mandate(mandate) == 26
    note = mortality_planning_horizon_note(mandate)
    assert "Einzelperson" in note and "Partner" in note


def test_note_is_none_when_feature_off():
    from services.mortality.horizon import mortality_planning_horizon_note

    assert mortality_planning_horizon_note(_mandate(use_mortality_simulation=0)) is None


def test_note_reaches_optimizer_reasoning(monkeypatch):
    import services.optimizer.solver as solver_module
    import services.portfolio_engine as pe
    from services.optimizer.solver import SolverTechnicalError
    from services.portfolio_engine_optimizer_integration import (
        _run_stochastic_optimizer_pass,
    )

    buckets = ("equities", "bonds", "real_estate", "alternatives", "liquidity")
    captured = {}

    def _capture(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(seed=7, n_paths=4)

    def _raise(**_kwargs):
        raise SolverTechnicalError("synthetic")

    monkeypatch.setattr(pe, "_OPTIMIZER_N_PATHS_DEFAULT", 4)
    monkeypatch.setattr(solver_module, "build_optimizer_context", _capture)
    monkeypatch.setattr(solver_module, "run_solver", _raise)
    mandate = _mandate(
        client=_couple_client(), tax_jurisdiction=None, tax_overrides_json=None,
        retirement_year=None,
    )
    reasoning: list[str] = []
    _run_stochastic_optimizer_pass(
        optimizer_mode="stochastic",
        apply_targets=True,
        cma=SimpleNamespace(id="mortality-note-cma"),
        goals=[],
        house_matrix=SimpleNamespace(max_risky_fraction_bps=10_000),
        assessment=SimpleNamespace(
            final_score_x10=50, final_profile="Ausgewogen", is_overridden=0
        ),
        advisory_wealth_rappen=100_000_00,
        cashflow_projection_series_rappen=[0] * 40,
        inflation_series_bps=[100] * 40,
        targets={b: 2000 for b in buckets},
        minimums={b: 0 for b in buckets},
        maximums={b: 10_000 for b in buckets},
        reasoning=reasoning,
        risky_fraction_per_bucket={b: 0.5 for b in buckets},
        effective_bounds_bps={b: (0, 10_000) for b in buckets},
        mandate=mandate,
    )
    assert captured["mortality_fixed_offset_years"] == 32
    assert any("Letztversterbend" in line for line in reasoning)
