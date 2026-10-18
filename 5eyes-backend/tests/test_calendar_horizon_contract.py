"""Shared calendar-year horizon semantics for dated optimizer inputs."""

from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace

from services.calendar_horizon import add_calendar_years, calendar_years_until
from services.optimizer.goal_liabilities import goal_to_liability
from services.portfolio_engine import _simulation_horizon_years


def _dated_goal(target_date: date) -> SimpleNamespace:
    return SimpleNamespace(
        id="calendar-goal",
        label="Calendar goal",
        goal_type="Einmalige_Ausgabe",
        target_amount_rappen=10_000_00,
        target_wealth_rappen=None,
        target_return_bps=None,
        horizon_years=None,
        target_date=target_date.isoformat(),
        start_date=None,
        is_ongoing=0,
        frequency="einmalig",
        hardness="Hart",
        rank=1,
        weight_bps=10_000,
        value_mode="nominal",
        goal_scope="Beratungsvermoegen",
        pension_pillar=None,
    )


def test_calendar_year_horizon_exact_anniversary_then_one_day_over() -> None:
    as_of = date.today()
    exact = add_calendar_years(as_of, 12)

    assert calendar_years_until(exact, as_of=as_of) == 12
    assert calendar_years_until(exact + timedelta(days=1), as_of=as_of) == 13


def test_calendar_year_horizon_handles_february_29_anniversary() -> None:
    as_of = date(2024, 2, 29)

    assert add_calendar_years(as_of, 1) == date(2025, 2, 28)
    assert calendar_years_until(date(2025, 2, 28), as_of=as_of) == 1
    assert calendar_years_until(date(2025, 3, 1), as_of=as_of) == 2


def test_goal_liability_and_monte_carlo_share_calendar_horizon_contract() -> None:
    """Bucket-Index und Simulationshorizont zaehlen in DERSELBEN Einheit.

    UMGESTELLT am 2026-10-11 (ADR-2) -- und dieser Test hat dabei eine echte
    Regression gefangen, keine blosse Konventionsverschiebung:

    Die Liability-Buckets sind jetzt KALENDERJAHRE, der Simulationshorizont
    wurde aber weiter per ``calendar_years_until`` (Jahrestage) bemessen. Ein
    Ziel am exakten 12-Jahres-Jahrestag verlangte damit 12 Buckets, lag aber
    im Kalenderjahr-Bucket 13 -- es fiel aus dem simulierten Fenster und
    bekam eine Verbindlichkeit von NULL, nur begleitet von einem
    "ausserhalb des Horizonts"-Hinweis. Eine CHF-10'000-Ausgabe waere
    lautlos aus der Planung verschwunden.

    Deshalb pruefen die Assertions hier bewusst GLEICHHEIT von Bucket und
    Horizont, nicht zwei fixe Zahlen: solange beide dieselbe Einheit
    zaehlen, kann ein datiertes Ziel nicht aus dem Fenster fallen.

    Beide Faelle liegen jetzt in Bucket 13: der exakte Jahrestag und der
    Tag danach fallen ins selbe Kalenderjahr. Die Unterscheidung
    "Jahrestag erreicht oder nicht" ist eine Horizont-FORMEL-Frage (ADR-1a,
    ``calendar_years_until``, in den Tests darueber geprueft) und keine
    Bucket-Frage.
    """
    today = date.today()
    exact = add_calendar_years(today, 12)

    exact_goal = _dated_goal(exact)
    over_goal = _dated_goal(exact + timedelta(days=1))

    expected_bucket = exact.year - today.year + 1

    for goal in (exact_goal, over_goal):
        liability = goal_to_liability(goal, horizon_years=20)
        horizon = _simulation_horizon_years({}, [goal], None)

        assert liability.target_year_index == expected_bucket
        # Der Horizont muss den Bucket des Ziels enthalten -- sonst ist die
        # Verbindlichkeit still weg.
        assert horizon >= liability.target_year_index
        assert horizon == expected_bucket

        in_horizon = goal_to_liability(goal, horizon_years=horizon)
        assert sum(in_horizon.liability_path_rappen) == goal.target_amount_rappen
        assert in_horizon.evaluation_note is None
