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


def test_missing_client_salutation_falls_back_to_mandate_client_sex():
    """Kontrollrunde 2026-09-21: mandate.client_sex-Fallback war toter Code
    (feuerte nur wenn kein Geburtsjahr aufloeste, nie wenn nur salutation
    fehlte). client.salutation fehlt hier, mandate.client_sex="M" ist
    gesetzt -> muss jetzt die Maenner-Konstante (+83 -> 2043) nutzen statt
    der Default-Konstante (+85 -> 2045)."""
    client = _client(date_of_birth="1960-03-20", salutation=None)
    mandate = _mandate(client, client_sex="M")
    assert life_expectancy_year_for(mandate=mandate) == 2043


def test_client_salutation_takes_priority_over_mandate_client_sex():
    """Wenn client.salutation vorhanden ist, bleibt es massgeblich, auch
    wenn mandate.client_sex widersprechen wuerde."""
    client = _client(date_of_birth="1960-03-20", salutation="Frau")
    mandate = _mandate(client, client_sex="M")
    assert life_expectancy_year_for(mandate=mandate) == 2045


def test_manual_mandate_year_has_priority():
    client = _client(date_of_birth="1960-03-20", salutation="Herr")
    mandate = _mandate(client, life_expectancy_year=2050)
    assert life_expectancy_year_for(mandate=mandate) == 2050


def test_simulation_default_uses_derived_life_expectancy_inclusive():
    """Kontrollrunde 2026-09-23 (Phase 2, Mortalitaetsmodell-
    Vereinheitlichung): _simulation_horizon_years nutzt jetzt
    services.mortality.horizon (BFS-2020-2022-Sterbetafel) statt
    services.planning_horizon (flach) fuer diesen internen Modell-Floor --
    siehe test_mortality_horizon_client_partner_support.py fuer die
    Modell-Details. 1960 geboren, maennlich, reference_year=2026
    (mandate.opened_at) -> Sterbejahr 2046 (bestaetigtes Audit-Beispiel),
    nicht mehr 2043 (altes flaches Modell)."""
    client = _client(date_of_birth="1960-03-20", salutation="Herr")
    mandate = _mandate(client, opened_at="2026-01-01")
    expected = 2046 - 2026 + 1
    assert _simulation_horizon_years({}, [], mandate) == max(10, expected)


def test_simulation_horizon_de_mandate_falls_back_to_generic_floor():
    """Kontrollrunde 2026-09-23 (Phase 2): die BFS-Sterbetafel ist CH-only
    (bewusstes Jurisdiktions-Gate, siehe test_bfs_mortality_jurisdiction_
    gate.py). Das alte flache Modell (planning_horizon) hatte KEINE
    Jurisdiktions-Pruefung und wandte die CH-Konstanten (83/85) blind auch
    auf DE/AT-Mandate an -- fachlich falsch. Nach dem Swap liefert ein DE-
    Mandat keinen Lebenserwartungs-Floor mehr (None -> 0), der generische
    7-Jahre-Minimum bleibt die einzige Untergrenze."""
    from services.portfolio_engine import DEFAULT_SIMULATION_HORIZON_YEARS

    client = _client(date_of_birth="1960-03-20", salutation="Herr")
    mandate = _mandate(client, opened_at="2026-01-01", jurisdiction="DE")
    assert _simulation_horizon_years({}, [], mandate) == max(7, DEFAULT_SIMULATION_HORIZON_YEARS)


def test_explicit_simulation_horizon_has_priority_over_life_default():
    client = _client(date_of_birth="1990-03-20", salutation="Frau")
    mandate = _mandate(client)
    assert _simulation_horizon_years({"horizonYears": "12"}, [], mandate) == 12


def test_dated_pension_goal_extends_horizon_even_without_horizon_years():
    future_year = date.today().year + 30
    goal = SimpleNamespace(
        horizon_years=None,
        start_date=f"{date.today().year + 5}-01-01",
        target_date=f"{future_year}-12-31",
    )
    horizon = _simulation_horizon_years({"horizonYears": "12"}, [goal], None)
    assert horizon >= 30
