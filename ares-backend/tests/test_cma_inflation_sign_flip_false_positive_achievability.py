"""Red test for CMA-INFLATION-PATH-DOMAIN-001.

Finding (verified against current develop code): a real-value-mode expense
goal (goal_type="Einmalige_Ausgabe") combined with an administratively
reachable, deeply negative CMA inflation series (-200%/year, i.e.
inflation_series_bps=[-20000, -20000]; see sibling domain-validation
finding for how such a value reaches the engine) causes
``services.optimizer.goal_liabilities.goal_to_liability`` to compute a
NEGATIVE liability for what must always be a non-negative expense:

    amount = max(0, int(goal.target_amount_rappen or 0))   # 10000, guarded
    amount = _inflate_at_year(amount, target_year, inflation_series_bps)
    # cumulative factor = 1 + (-20000/10000) = -1.0 -> amount = -10000
    # the max(0, ...) guard above only protected the PRE-inflation input;
    # the POST-inflation amount is never re-clamped.

That negative liability then poisons two independent downstream production
consumers in services/optimizer/:

1. ``scenario_engine.simulate_wealth_paths`` does
   ``wealth[:, t+1] = grown + cashflow[t] - liability[t]``. Subtracting a
   NEGATIVE liability ADDS money to wealth, i.e. a real spending need
   increases simulated wealth instead of decreasing it.

2. ``objective.goal_probability_per_path`` (via
   ``objective._positive_due_wealth_indices``, which only treats
   ``amount > 0`` entries as "due") never registers the negative outflow as
   a due payment at all, so the goal is trivially reported as achieved on
   every single path (probability=1.0) regardless of actual wealth, and
   ``objective.chance_constraint_penalty`` assigns it zero penalty and
   status "erreichbar" -- a real CHF 100 expense goal is reported as a
   costless, 100%-achievable non-event.

This test exercises the real production functions end-to-end (no mocks)
with a trivial zero-growth, zero-cashflow, zero-initial-wealth scenario and
asserts the behaviour that must hold for ANY expense goal: the liability
must never be negative, wealth must never be increased by paying an
expense, and the goal must not be reported as costlessly achievable.

Audit: 2026-10-04-cma-inflation-domain-and-effective-date-integrity-audit.md
(not committed in this repo; round 40 red test).

NACHGESCHAERFT am 2026-10-11 (ADR-2). Dieser Reproducer wurde durch die
Umstellung auf Kalenderjahr-Buckets gruen -- aber aus dem FALSCHEN Grund,
und der Befund ist NICHT behoben:

Das Ziel hatte kein target_date und landete damit in Bucket 1. Seit ADR-2
zaehlt die Inflation ab dem laufenden Kalenderjahr mit Faktor 1.0 (die
B1-Konvention: User-Eingaben sind heutige Rappen), der Exponent in Bucket 1
ist also 0 und der negative Faktor kommt gar nicht zum Tragen. Gemessen mit
derselben Reihe [-20000, -20000]:

    kein Datum (Bucket 1):        [10000, 0, 0, 0, 0]      -> positiv
    Ziel im Folgejahr (Bucket 2): [0, -10000, 0, 0, 0]     -> NEGATIV
    Ziel in 3 Jahren (Bucket 4):  [0, 0, 0, -10000, 0]     -> NEGATIV

Das Ziel traegt deshalb jetzt ein target_date im Folgejahr, womit der
Vorzeichenwechsel weiterhin reproduziert wird. Ein gruener Reproducer haette
hier eine geschlossene Luecke signalisiert, die offen ist.

Der echte Fix ist ADR-6a (Owner-Entscheid 2026-10-11, bestaetigt): ein
gemeinsamer ``parse_inflation_path()`` mit Wertebereich [-1000, 3000] bps,
analog zum bereits etablierten ``schemas/wealth.py::inflation_assumption_bps``.
Eine Reihe von -20000 bps darf die Engine nie erreichen. Ein Preisniveau
kann nicht negativ werden; die Klammerung gehoert an die Eingabe, nicht als
nachgelagerter max(0, ...)-Flicken an jeden Konsumenten.
"""
from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import numpy as np
import pytest

from services.optimizer.goal_liabilities import goal_to_liability
from services.optimizer.objective import chance_constraint_penalty, goal_probability_per_path
from services.optimizer.scenario_engine import simulate_wealth_paths


def test_deeply_negative_real_inflation_must_not_flip_expense_liability_negative():
    goal = SimpleNamespace(
        id="g1",
        label="t",
        goal_type="Einmalige_Ausgabe",
        target_amount_rappen=10000,
        target_wealth_rappen=None,
        target_return_bps=None,
        horizon_years=None,
        # ADR-2: ein Ziel OHNE Datum liegt in Bucket 1, wo der
        # Inflations-Exponent 0 ist und der negative Faktor nicht greift.
        # Das Zieldatum im Folgejahr haelt den Befund reproduzierbar.
        target_date=date(date.today().year + 1, 6, 1).isoformat(),
        start_date=None,
        is_ongoing=0,
        frequency=None,
        hardness="Primaer",
        rank=1,
        weight_bps=None,
        value_mode="real",
        goal_scope="Beratungsvermoegen",
        pension_pillar=None,
    )

    horizon_years = 5

    # GEFIXT am 2026-10-12 (ADR-6a), fail-closed an ZWEI Grenzen:
    #
    # 1. Am Eingang: cma_validation.parse_inflation_path_json() laesst eine
    #    Reihe von -20000 bps nicht in die CMA. Das ist die Strecke, die in
    #    Produktion zaehlt -- unten als eigener Test.
    # 2. Hier: goal_to_liability() prueft eine uebergebene Reihe selbst.
    #    Ein kaputter ARGUMENT-Wert ist ein anderer Weg als kaputte DATEN,
    #    deshalb eine eigene Pruefung.
    #
    # Der Test erwartete vorher einen RUECKGABEWERT mit nicht-negativer
    # Verbindlichkeit. Abzulehnen ist die staerkere Antwort: es entsteht
    # ueberhaupt keine Verbindlichkeit, also auch keine falsche. Der
    # downstream-Pfad (simulate_wealth_paths / goal_probability_per_path),
    # den dieser Test vorher durchlief, wird nie mehr erreicht.
    #
    # Was ohne die Pruefung passierte: Faktor 1 + (-2.0) = -1.0, aus einer
    # Ausgabe von 10'000 Rappen wurden -10'000. Der Wealth-Pfad buchte das
    # als Mittelzufluss, und objective._positive_due_wealth_indices() sah
    # die Zahlung gar nicht mehr als faellig -- ein echter Ausgabenbedarf
    # galt als kostenlos und zu 100 % erreichbar.
    with pytest.raises(ValueError, match="Baseline-Domaene"):
        goal_to_liability(
            goal, horizon_years=horizon_years,
            inflation_series_bps=[-20000, -20000],
        )


def test_out_of_domain_inflation_cannot_reach_the_engine_through_the_cma():
    """Die Produktionsstrecke: ueber die CMA kommt die Reihe nie an.

    goal_to_liability() bekommt seine Inflationsreihe im Produktionspfad aus
    services/portfolio_engine_cma.py::_inflation_path_series(), und die
    liest die CMA jetzt durch den gemeinsamen Parser. Diese Grenze ist die
    wichtigere -- sie verhindert, dass der Wert ueberhaupt gespeichert oder
    gelesen wird.
    """
    from types import SimpleNamespace

    from services.cma_validation import CMAValidationError
    from services.portfolio_engine_cma import _inflation_path_series

    cma = SimpleNamespace(inflation_path_json='{"2026": -20000}')
    with pytest.raises(CMAValidationError, match="Baseline-Domaene"):
        _inflation_path_series(cma, 5, 2026)
