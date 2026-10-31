"""2026-08-07 (CEO/CFO/CIO-Audit): BFS_2020_2022 ist eine Schweizer
Sterbetafel (services/mortality/bfs.py). Sowohl
_expected_death_year_offset_from_mandate (portfolio_engine_payload.py) als
auch der Mortalitaets-Kwargs-Aufbau in
portfolio_engine_optimizer_integration.py nutzten sie fuer JEDES Mandat mit
client_birth_year+client_sex, unabhaengig von mandate.jurisdiction. Fuer ein
DE/AT-Mandat (typische Lebenserwartung von der Schweiz abweichend) waere das
Sterbealter -- und damit das simulierte Verzehr-/Depletion-Risiko in der
Monte-Carlo-Simulation -- systematisch falsch. Da keine DE/AT-Sterbetafel
vorliegt, ist "kein Mortalitaets-Cutoff" (konservativ) korrekt statt einer
falschen CH-Annahme.
"""
from __future__ import annotations

from types import SimpleNamespace

from services.portfolio_engine_payload import _expected_death_year_offset_from_mandate


def _mandate(**kwargs):
    defaults = dict(
        life_expectancy_year=None,
        client_birth_year=1960,
        client_sex="M",
        jurisdiction=None,
        use_mortality_simulation=1,
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def test_ch_mandate_uses_bfs_mortality_table():
    mandate = _mandate(jurisdiction="CH")
    offset = _expected_death_year_offset_from_mandate(mandate)
    assert offset is not None and offset > 0


def test_null_jurisdiction_defaults_to_ch_bfs_table():
    mandate = _mandate(jurisdiction=None)
    offset = _expected_death_year_offset_from_mandate(mandate)
    assert offset is not None and offset > 0


def test_de_mandate_does_not_use_ch_bfs_table():
    mandate = _mandate(jurisdiction="DE")
    assert _expected_death_year_offset_from_mandate(mandate) is None


def test_at_mandate_does_not_use_ch_bfs_table():
    mandate = _mandate(jurisdiction="AT")
    assert _expected_death_year_offset_from_mandate(mandate) is None


def test_manual_life_expectancy_year_still_works_for_non_ch_mandate():
    """Priorität 1 (manuell vom Berater gepflegt) ist NICHT CH-spezifisch --
    bleibt fuer jede Jurisdiktion wirksam."""
    from datetime import date
    mandate = _mandate(jurisdiction="DE", life_expectancy_year=date.today().year + 12)
    assert _expected_death_year_offset_from_mandate(mandate) == 12
