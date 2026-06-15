from datetime import date
from types import SimpleNamespace

from services.planning_horizon import life_expectancy_year_for
from services.portfolio_engine import _simulation_horizon_years


def _client(**values):
    defaults = {
        "date_of_birth": None,
        "salutation": None,
        "partner_date_of_birth": None,
        "partner_salutation": None,
    }
    defaults.update(values)
    return SimpleNamespace(**defaults)


def _mandate(client=None, **values):
    defaults = {
        "client": client,
        "life_expectancy_year": None,
        "client_birth_year": None,
        "client_sex": None,
    }
    defaults.update(values)
    return SimpleNamespace(**defaults)


def test_man_1960_has_life_expectancy_year_2043():
    client = _client(date_of_birth="1960-03-20", salutation="Herr")
    assert life_expectancy_year_for(client=client) == 2043


def test_woman_1960_has_life_expectancy_year_2045():
    client = _client(date_of_birth="1960-03-20", salutation="Frau")
    assert life_expectancy_year_for(client=client) == 2045


def test_couple_uses_later_calendar_life_expectancy_year():
    client = _client(
        date_of_birth="1960-03-20",
        salutation="Herr",
        partner_date_of_birth="1955-04-10",
        partner_salutation="Frau",
    )
    # Mann: 2043, Frau: 2040. Der Haushalt laeuft bis zum spaeteren Jahr.
    assert life_expectancy_year_for(client=client) == 2043


def test_unknown_salutation_uses_conservative_plus_85():
    client = _client(date_of_birth="1960-03-20", salutation=None)
    assert life_expectancy_year_for(client=client) == 2045


def test_manual_mandate_year_has_priority():
    client = _client(date_of_birth="1960-03-20", salutation="Herr")
    mandate = _mandate(client, life_expectancy_year=2050)
    assert life_expectancy_year_for(mandate=mandate) == 2050


def test_simulation_default_uses_derived_life_expectancy_inclusive():
    client = _client(date_of_birth="1960-03-20", salutation="Herr")
    mandate = _mandate(client)
    expected = 2043 - date.today().year + 1
    assert _simulation_horizon_years({}, [], mandate) == max(10, expected)


def test_explicit_simulation_horizon_has_priority_over_life_default():
    client = _client(date_of_birth="1990-03-20", salutation="Frau")
    mandate = _mandate(client)
    assert _simulation_horizon_years({"horizonYears": "12"}, [], mandate) == 12
