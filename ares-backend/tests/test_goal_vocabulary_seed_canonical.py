"""RC-CH-1-F1 / N-903-02: Kanonisierung von Zieltyp/-familie/-scope zieht keinen neuen Wuerfel.

Seit die API Legacy-Schreibweisen ("Vermoegensziel", "Vermoegen",
"Gesamtvermoegen") auf den DB-Wert kanonisiert, waere ein Ziel vor und nach
der Umschreibung wirtschaftlich gleich -- der Seed-Fingerabdruck
(``solver.goal_economic_fingerprint``) las die drei Felder aber roh.

Belegt wird:
1. ASCII- und Umlaut-Form ergeben denselben Fingerabdruck und denselben
   Inhalts-Seed (``optimizer_content_seed``).
2. Fuer gespeicherte DB-Werte (Umlaut-Form, CHECK-Werte) ist der
   Fingerabdruck BITGLEICH zur bisherigen Rohdarstellung -- bestehende Seeds
   aendern sich nicht.
3. Wirtschaftlich verschiedene Werte bleiben verschieden; unbekannte Werte
   bleiben roh.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from core.evidence import SCHEME_V1_ASCII, canonical_json  # noqa: E402
from core.goal_vocabulary import (  # noqa: E402
    GOAL_FAMILY_DB_VALUES,
    GOAL_SCOPE_DB_VALUES,
    GOAL_TYPE_DB_VALUES,
)
from services.optimizer.solver import (  # noqa: E402
    GOAL_ECONOMIC_FIELDS,
    goal_economic_fingerprint,
    optimizer_content_seed,
)
from services.optimizer.scenario_engine import ScenarioInputs  # noqa: E402


def _goal(family, goal_type, scope):
    return {
        "goal_family": family, "goal_type": goal_type, "goal_scope": scope,
        "rank": 1, "hardness": "Primär", "value_mode": "nominal",
        "target_wealth_rappen": 300_000_00, "target_date": "2036-06-30",
        "start_date": None, "is_active": 1, "is_included": 1,
    }


ASCII = _goal("Vermoegen", "Vermoegensziel", "Gesamtvermoegen")
UMLAUT = _goal("Vermögen", "Vermögensziel", "Gesamtvermögen")


def _raw_row(goal):
    """Fingerabdruck-Zeile wie vor N-903-02 (Rohwerte, Datum relativ 2026)."""
    row = {name: goal.get(name) for name in GOAL_ECONOMIC_FIELDS}
    row["target_date"] = "Y+10-06-30"
    return canonical_json(row, scheme=SCHEME_V1_ASCII)


def _inputs() -> ScenarioInputs:
    import numpy as np

    return ScenarioInputs(
        mu_bps=np.array([612.0, 188.0, 401.0, 455.0, 61.0]),
        sigma_bps=np.array([1534.0, 412.0, 1088.0, 1210.0, 52.0]),
        skew_bps=np.zeros(5),
        excess_kurt_bps=np.zeros(5),
        cholesky=np.eye(5),
    )


def _seed(goals):
    return optimizer_content_seed(
        scenario_inputs=_inputs(), goals=goals, score_x10=70,
        horizon_years=15, scenario_horizon_years=15, n_paths=500,
    )


def test_ascii_and_umlaut_spelling_share_fingerprint_and_seed():
    fp = goal_economic_fingerprint
    assert fp([ASCII], valuation_year=2026) == fp([UMLAUT], valuation_year=2026)
    assert _seed([ASCII]) == _seed([UMLAUT])


def test_stored_db_values_keep_their_previous_fingerprint_bitwise():
    """Kein Wuerfelwechsel fuer gespeicherte Daten: Umlaut-Form = Rohform von frueher."""
    assert goal_economic_fingerprint([UMLAUT], valuation_year=2026) == [_raw_row(UMLAUT)]


@pytest.mark.parametrize("goal_type", GOAL_TYPE_DB_VALUES)
@pytest.mark.parametrize("family", GOAL_FAMILY_DB_VALUES)
@pytest.mark.parametrize("scope", GOAL_SCOPE_DB_VALUES)
def test_every_db_value_combination_is_unchanged(goal_type, family, scope):
    goal = _goal(family, goal_type, scope)
    assert goal_economic_fingerprint([goal], valuation_year=2026) == [_raw_row(goal)]


def test_economically_different_values_still_differ():
    fp = goal_economic_fingerprint
    other = _goal("Vermögen", "Kapitalerhalt", "Gesamtvermögen")
    assert fp([UMLAUT], valuation_year=2026) != fp([other], valuation_year=2026)
    other_scope = _goal("Vermögen", "Vermögensziel", "Beratungsvermögen")
    assert fp([UMLAUT], valuation_year=2026) != fp([other_scope], valuation_year=2026)


def test_unknown_values_stay_raw():
    goal = _goal("Lebenshaltung", "Vermögensziel", "Gesamtvermögen")
    assert goal_economic_fingerprint([goal], valuation_year=2026) == [_raw_row(goal)]
