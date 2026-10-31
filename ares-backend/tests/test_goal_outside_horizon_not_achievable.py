"""GOAL-OUTSIDE-HORIZON-001: ein Ziel jenseits des Horizonts ist nicht "erreicht".

Befund 2026-10-12, gefunden im Ende-zu-Ende-Durchlauf des Mock-Mandanten
"Thierry Goessi" und anschliessend isoliert nachgemessen.

`objective._positive_due_wealth_indices()` liefert eine leere Indexliste fuer
ZWEI voellig verschiedene Zustaende:

    (a) das Ziel hat gar keine positive Verbindlichkeit -- "erreicht" ist
        dann korrekt, es ist nichts zu finanzieren;
    (b) das Ziel HAT Faelligkeiten, aber alle liegen hinter dem Horizont --
        dann wurde es nicht geprueft, sondern nur nicht angesehen.

`_goal_probability_core()` behandelte (b) wie (a) und gab `np.ones(...)`
zurueck: auf jedem Pfad erreicht. Die gemessene Folge am Mock-Mandanten
(CHF 530'000 Beratungsvermoegen, Risikoprofil-Horizont 20 Jahre):

    Ziel                           Betrag            vorher
    ------------------------------ ----------------- -----------------------
    Umbau (einmalig, im Horizont)  CHF 50 Mio        0 bps, nicht_erreichbar
    Ausbildung (einmalig)          CHF  9 Mio        0 bps, nicht_erreichbar
    Pensionsausgabe ab 2046        CHF  5 Mio/JAHR   10000 bps, erreichbar

Also: das haerteste Ziel, Rang 1, in einer Ruhestandsplanung meldete
erfundene Gewissheit, waehrend ein hundertmal kleineres Einmalziel im
Horizont korrekt abgelehnt wurde. Das Aggregat `zielerreichung_bps` reagierte
korrekt (fiel auf 32.71 %) -- nur die Zeile des Ziels nicht.

Die Unterscheidung wird aus dem STRUKTURELLEN Fahrplan gelesen
(`target_year_index`), nicht aus dem Geldpfad zurueckgerechnet: eine Reihe
kann auch dann komplett null sein, wenn der Fahrplan IM Horizont liegt (ein
bedingtes Ziel mit `probability_pct=0`, oder Betraege die pro Bucket auf null
runden) -- derselbe Zahlenwert, ein anderer Zustand.
"""
from __future__ import annotations

import datetime
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.optimizer.certification import (  # noqa: E402
    RELIABILITY_OUTSIDE_HORIZON,
)
from services.optimizer.goal_liabilities import goal_to_liability  # noqa: E402
from services.optimizer.objective import (  # noqa: E402
    GoalLiability,
    chance_constraint_penalty,
    scheduled_outside_wealth_horizon,
)


def _goal(**overrides):
    base = dict(
        id="g-pension",
        label="Pensionsausgaben ab 67",
        goal_type="Pensionsausgabe",
        goal_family="Cashflow",
        target_amount_rappen=5_000_000_00,
        target_wealth_rappen=None,
        target_return_bps=None,
        frequency="jährlich",
        start_date="2046-01-01",
        target_date=None,
        is_ongoing=1,
        horizon_years=None,
        hardness="Hart",
        value_mode="real",
        probability_pct=100,
        rank=1,
        is_included=1,
        is_active=1,
        lifecycle_decision=None,
        weight_bps=None,
        goal_scope=None,
        success_probability_min_x100=None,
        linked_position_id=None,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _liability(*, horizon_years: int, **goal_overrides) -> GoalLiability:
    return goal_to_liability(
        _goal(**goal_overrides),
        horizon_years=horizon_years,
        inflation_series_bps=[70] * (horizon_years + 2),
        as_of=datetime.date(2026, 10, 12),
    )


# ---------------------------------------------------------------------------
# Der gemessene Befund
# ---------------------------------------------------------------------------


def test_pension_entirely_beyond_horizon_has_no_due_payments_in_path():
    """Die Vorbedingung des Befunds, als eigener Test.

    Ohne diese Zeile waere bei einer spaeteren Aenderung der Bucket-Achse
    nicht erkennbar, ob die Tests unten noch den gemeinten Zustand treffen
    oder bloss zufaellig gruen sind.
    """
    liability = _liability(horizon_years=20)
    path = list(liability.liability_path_rappen or ())
    assert len(path) == 20
    assert all(value == 0 for value in path), (
        "Testannahme: die Pensionszahlung ab 2046 liegt komplett hinter einem "
        f"20-Jahres-Horizont ab 2026. Pfad: {path}"
    )
    # Und das strukturelle Signal ist trotzdem da -- genau darauf beruht der Fix.
    assert liability.target_year_index == 21


@pytest.mark.parametrize(
    "horizon_years, expected_outside",
    [
        (20, True),    # Pension ab 2046, Horizont endet 2045
        (21, False),   # erste Zahlung liegt im letzten Bucket
        (25, False),
        (30, False),
    ],
)
def test_outside_horizon_detection_follows_the_schedule(horizon_years, expected_outside):
    liability = _liability(horizon_years=horizon_years)
    assert scheduled_outside_wealth_horizon(
        liability, n_wealth_columns=horizon_years + 1
    ) is expected_outside


def test_goal_beyond_horizon_is_not_reported_as_achievable():
    """Der Kern: kein "erreichbar", keine 100 %, und die Offenlegung dabei."""
    liability = _liability(horizon_years=20)
    # Vermoegen ueberall komfortabel positiv -- der Zustand haengt NICHT am
    # Vermoegen, sondern daran, dass nichts im Horizont faellig ist.
    wealth = np.full((64, 21), 1_000_000_00, dtype=np.float64)

    _penalty, rows = chance_constraint_penalty(wealth, [liability], 530_000_00)

    assert len(rows) == 1
    row = rows[0]
    assert row["status"] == "ausserhalb_horizont", row
    assert row["outside_simulation_horizon"] is True, row
    assert row["probability"] == 0.0, row
    assert row["reliability_verdict"] == RELIABILITY_OUTSIDE_HORIZON, row


def test_beyond_horizon_goal_adds_no_penalty():
    """Offenlegen, nicht bestrafen.

    Eine Strafe wuerde den Solver zwingen, die Allokation fuer ALLE uebrigen
    Ziele gegen einen Fehlbetrag zu verbiegen, der innerhalb des Horizonts
    gar nicht auftritt. Der Befund war die falsche AUSSAGE, nicht eine
    fehlende Strafe.
    """
    liability = _liability(horizon_years=20)
    wealth = np.full((64, 21), 1_000_000_00, dtype=np.float64)
    penalty, _rows = chance_constraint_penalty(wealth, [liability], 530_000_00)
    assert penalty == 0.0


# ---------------------------------------------------------------------------
# Gegenproben: der Fix darf die uebrigen Faelle nicht anfassen
# ---------------------------------------------------------------------------


def test_goal_inside_horizon_is_still_assessed_normally():
    """Dasselbe Ziel bei groesserem Horizont muss ECHT bewertet werden.

    Ohne diese Gegenprobe waere eine Implementierung, die jeden
    Ausgabenstrom als "ausserhalb Horizont" abstempelt, von den Tests oben
    nicht zu unterscheiden.
    """
    liability = _liability(horizon_years=30)
    # Vermoegen tief NEGATIV ab dem Pensionsbeginn: das Ziel ist real nicht
    # finanzierbar und muss das auch sagen.
    wealth = np.full((64, 31), -1_000_000_00, dtype=np.float64)

    _penalty, rows = chance_constraint_penalty(wealth, [liability], 530_000_00)
    row = rows[0]
    assert row["outside_simulation_horizon"] is False, row
    assert row["status"] == "nicht_erreichbar", row
    assert row["probability"] == 0.0, row
    assert row["reliability_verdict"] != RELIABILITY_OUTSIDE_HORIZON, row


def test_affordable_goal_inside_horizon_stays_erreichbar():
    """Und der gute Fall bleibt gut -- sonst waere der Fix eine Dauerwarnung."""
    liability = _liability(horizon_years=30)
    wealth = np.full((64, 31), 50_000_000_00, dtype=np.float64)

    _penalty, rows = chance_constraint_penalty(wealth, [liability], 530_000_00)
    row = rows[0]
    assert row["outside_simulation_horizon"] is False, row
    assert row["status"] == "erreichbar", row
    assert row["probability"] == 1.0, row


def test_goal_without_any_liability_is_untouched():
    """Fall (a) bleibt wie bisher: nichts zu finanzieren heisst erreicht.

    Die beiden leeren Indexlisten duerfen NICHT gleich behandelt werden --
    aber die harmlose Variante darf auch nicht plötzlich blockieren.
    """
    liability = GoalLiability(
        goal_id="g-empty",
        label="Leeres Ziel",
        goal_type="Wiederkehrende_Ausgabe",
        target_kind="outflow_stream",
        target_amount_rappen=0,
        # Innerhalb des Horizonts -- es gibt nur nichts zu zahlen.
        target_year_index=5,
        liability_path_rappen=[0] * 20,
        hardness_key="hart",
    )
    # 64 Pfade: mit 16 greift das ESS-Gate der Zertifizierung
    # (Status 'unreliable') und verdeckt den hier geprueften Zustand.
    wealth = np.full((64, 21), 1_000_000_00, dtype=np.float64)
    _penalty, rows = chance_constraint_penalty(wealth, [liability], 100_000_00)
    row = rows[0]
    assert row["outside_simulation_horizon"] is False, row
    assert row["probability"] == 1.0, row
    assert row["status"] == "erreichbar", row


def test_wealth_and_return_goals_are_not_affected():
    """Nur Ausgaben-Zielarten haben einen Zahlungsplan.

    `wealth_at_t` und `return_rate` werden am Horizontende bewertet und
    klemmen ihren Index bewusst; sie duerfen nicht in den neuen Zustand
    laufen.
    """
    for kind in ("wealth_at_t", "return_rate", "maximize"):
        liability = GoalLiability(
            goal_id=f"g-{kind}",
            label=kind,
            goal_type="Vermoegensziel",
            target_kind=kind,
            target_amount_rappen=1_000_00,
            target_year_index=99,  # weit hinter dem Horizont
            liability_path_rappen=[0] * 20,
            hardness_key="hart",
        )
        wealth = np.full((64, 21), 10_000_000_00, dtype=np.float64)
        _penalty, rows = chance_constraint_penalty(wealth, [liability], 100_000_00)
        assert rows[0]["outside_simulation_horizon"] is False, kind
