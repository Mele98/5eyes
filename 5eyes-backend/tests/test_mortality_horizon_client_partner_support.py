"""Kontrollrunde 2026-09-21/23 (Phase 1, Mortalitaetsmodell-Vereinheitlichung).

services.mortality.horizon.expected_death_year_offset_from_mandate() nimmt
jetzt optional ein `client`-Objekt entgegen (Tagesgenaues Geburtsdatum +
Partner-Beruecksichtigung), um Feature-Paritaet mit
services.planning_horizon.life_expectancy_year_for() zu erreichen, ohne
dessen bestehende Aufrufer (services/portfolio_engine_payload.py,
services/mandate_model_inputs.py) zu beeinflussen (client=None per Default,
identisches Verhalten wie vor dieser Aenderung).
"""
from __future__ import annotations

from types import SimpleNamespace

from services.mortality.horizon import (
    expected_death_year_offset_from_mandate,
    mandate_reference_year,
)


def _mandate(**kwargs):
    defaults = dict(
        opened_at="2026-01-01",
        life_expectancy_year=None,
        jurisdiction="CH",
        client_birth_year=1960,
        client_sex="M",
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _client(**kwargs):
    defaults = dict(
        date_of_birth=None,
        salutation=None,
        partner_date_of_birth=None,
        partner_salutation=None,
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


# ---------------------------------------------------------------------------
# Rueckwaertskompatibilitaet: client=None (Default) -- identisch zu vorher.
# ---------------------------------------------------------------------------

def test_backward_compatible_without_client_argument():
    mandate = _mandate()
    assert expected_death_year_offset_from_mandate(mandate) == 20


def test_backward_compatible_matches_confirmed_audit_example():
    """Bestaetigtes Beispiel aus der Kontrollrunde-2026-09-21-Analyse:
    1960 geboren, Mandat eroeffnet 2026-01-01 -> Sterbejahr 2046."""
    mandate = _mandate()
    ref = mandate_reference_year(mandate)
    offset = expected_death_year_offset_from_mandate(mandate)
    assert ref + offset == 2046


# ---------------------------------------------------------------------------
# client uebergeben, aber ohne zusaetzliche Daten (leere Felder) -> identisch
# zum reinen Mandate-Pfad (Fallback auf mandate.client_birth_year/client_sex).
# ---------------------------------------------------------------------------

def test_client_with_no_data_falls_back_to_mandate_fields():
    mandate = _mandate()
    client = _client()
    assert expected_death_year_offset_from_mandate(mandate, client=client) == 20


# ---------------------------------------------------------------------------
# client.date_of_birth bevorzugt vor mandate.client_birth_year (identisches
# Jahr -> identisches Ergebnis, reiner Praezisions-Check).
# ---------------------------------------------------------------------------

def test_client_date_of_birth_same_year_matches_mandate_fallback():
    mandate = _mandate()
    client = _client(date_of_birth="1960-06-15", salutation="Herr")
    assert expected_death_year_offset_from_mandate(mandate, client=client) == 20


def test_client_date_of_birth_different_year_overrides_mandate_birth_year():
    """mandate.client_birth_year ist absichtlich falsch/veraltet --
    client.date_of_birth muss gewinnen."""
    mandate = _mandate(client_birth_year=1900)
    client = _client(date_of_birth="1960-06-15", salutation="Herr")
    assert expected_death_year_offset_from_mandate(mandate, client=client) == 20


def test_client_salutation_overrides_mandate_client_sex():
    mandate = _mandate(client_sex="M")
    client = _client(date_of_birth="1960-06-15", salutation="Frau")
    offset_female = expected_death_year_offset_from_mandate(mandate, client=client)
    offset_male = expected_death_year_offset_from_mandate(mandate)
    # Frauen haben in der BFS-Tafel eine hoehere Restlebenserwartung.
    assert offset_female > offset_male


# ---------------------------------------------------------------------------
# Partner: Haushalts-Horizont = das SPAETERE der beiden Sterbejahre.
# ---------------------------------------------------------------------------

def test_younger_partner_extends_household_horizon():
    mandate = _mandate()
    client = _client(
        date_of_birth="1960-06-15", salutation="Herr",
        partner_date_of_birth="1965-01-01", partner_salutation="Frau",
    )
    primary_only = expected_death_year_offset_from_mandate(
        mandate, client=_client(date_of_birth="1960-06-15", salutation="Herr"),
    )
    household = expected_death_year_offset_from_mandate(mandate, client=client)
    assert household > primary_only


def test_older_partner_does_not_shorten_household_horizon():
    """max()-Semantik: ein AELTERER Partner (kuerzere eigene Restlebens-
    erwartung) darf den Haushalts-Horizont NICHT verkuerzen."""
    mandate = _mandate()
    primary_only = expected_death_year_offset_from_mandate(
        mandate, client=_client(date_of_birth="1960-06-15", salutation="Herr"),
    )
    client_with_older_partner = _client(
        date_of_birth="1960-06-15", salutation="Herr",
        partner_date_of_birth="1950-01-01", partner_salutation="Frau",
    )
    household = expected_death_year_offset_from_mandate(mandate, client=client_with_older_partner)
    assert household >= primary_only


def test_partner_without_primary_birth_data_still_counted():
    """Falls nur der Partner Geburtsdaten hat (Edge-Case), muss dessen
    Sterbejahr trotzdem einfliessen statt stillschweigend None zu liefern."""
    mandate = SimpleNamespace(
        opened_at="2026-01-01", life_expectancy_year=None, jurisdiction="CH",
        client_birth_year=None, client_sex=None,
    )
    client = _client(partner_date_of_birth="1965-01-01", partner_salutation="Frau")
    assert expected_death_year_offset_from_mandate(mandate, client=client) is not None


# ---------------------------------------------------------------------------
# Manueller Override (Prioritaet 1) bleibt unveraendert massgeblich, auch
# mit client uebergeben.
# ---------------------------------------------------------------------------

def test_manual_override_still_wins_with_client_argument():
    mandate = _mandate(life_expectancy_year=2050)
    client = _client(
        date_of_birth="1960-06-15", salutation="Herr",
        partner_date_of_birth="1990-01-01", partner_salutation="Frau",
    )
    ref = mandate_reference_year(mandate)
    assert expected_death_year_offset_from_mandate(mandate, client=client) == 2050 - ref


# ---------------------------------------------------------------------------
# Jurisdiktions-Gate bleibt unveraendert, auch mit client uebergeben.
# ---------------------------------------------------------------------------

def test_non_ch_jurisdiction_still_returns_none_even_with_client():
    mandate = _mandate(jurisdiction="DE")
    client = _client(date_of_birth="1960-06-15", salutation="Herr")
    assert expected_death_year_offset_from_mandate(mandate, client=client) is None
