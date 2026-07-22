"""Mutations-Tests fuer services/cashflow_timeline.py (Roadmap #86).

Zweck (siehe tests/_mutation_helpers.py fuer die volle Methodik-Erklaerung):
Diese Tests beweisen, dass die Formeln in ``contribution_for_year`` und
``_compound_inflation_factor`` NICHT durch eine plausible Ein-Zeichen-/
Ein-Operator-Aenderung kaputt gemacht werden koennten, ohne dass eine
bestehende oder hier reproduzierte Assertion anschlaegt.

Fuer jede Mutation wird:
  1. die ECHTE Funktion via ``tests._mutation_helpers.mutate`` an genau einer
     Stelle bewusst falsch abgeaendert (Vorzeichen-Fehler, Off-by-One, falscher
     Operator, vertauschter Vergleich -- die klassischen mutmut-Mutationsarten),
  2. die mutierte Funktion mit denselben Eingaben wie die echte Funktion
     aufgerufen,
  3. gezeigt, dass Original und Mutant auf DIESEN Eingaben unterschiedliche
     Ergebnisse liefern, UND dass das Original weiterhin den in
     tests/test_cashflow_timeline.py gepinnten Erwartungswert trifft.

Wo eine Mutation exakt einen bestehenden Test aus test_cashflow_timeline.py
trifft, ist das im Kommentar genannt (z.B. ``test_monatlich_ganzes_jahr``).
Das ist der eigentliche Beweis: "Waere die Formel X statt Y, wuerde Test Z das
MERKEN" -- nicht nur, dass die Zeile ausgefuehrt wurde (Line-Coverage haette
das nicht gezeigt, denn beide Varianten fuehren dieselben Zeilen aus).

Was das NICHT abdeckt
----------------------
- Nur die hier gewaehlten Mutationen, keine erschoepfende Exploration.
- ``_add_months``, ``normalize_frequency``/``normalize_nature`` selbst werden
  nicht mutiert (sind bereits direkt in test_cashflow_timeline.py abgedeckt).
- Kein Ersatz fuer einen echten ``mutmut run`` unter WSL (siehe
  tests/_mutation_helpers.py, warum das hier nativ auf Windows nicht geht).
"""
from __future__ import annotations

from services import cashflow_timeline as ct
from tests._mutation_helpers import mutate


# ── contribution_for_year ──────────────────────────────────────────────────

def test_mutation_end_before_start_guard_removed():
    """Guard ``end < start -> return 0`` durch ``end > start`` ersetzt.

    Fuer einmalige Cashflows mit vertauschten Daten (valid_from NACH
    valid_until) muss die Funktion defensiv 0 liefern. Mit der kaputten
    Guard-Bedingung wuerde stattdessen der (spaetere) valid_from als
    Event-Datum durchgereicht und der Betrag faelschlich gezaehlt.
    """
    mutant = mutate(
        ct,
        "contribution_for_year",
        "if end and start and end < start:",
        "if end and start and end > start:",
    )
    kwargs = dict(
        amount_rappen=100_000_00,
        frequency="einmalig",
        nature="einmalig",
        valid_from="2026-06-15",
        valid_until="2025-01-01",
        year=2026,
    )
    expected = 0  # defensiv: vertauschter Datumsbereich -> kein Beitrag
    assert ct.contribution_for_year(**kwargs) == expected
    assert mutant(**kwargs) != expected
    assert mutant(**kwargs) == 100_000_00  # zaehlt faelschlich den vollen Betrag


def test_mutation_occurrence_amount_multiplication_to_addition():
    """``amount * occurrences`` durch ``amount + occurrences`` ersetzt.

    Klassische arithmetische Mutation (mutmut: ArithmeticOperator).
    Bricht ``test_monatlich_ganzes_jahr`` (erwartet 12 * 1'000.00 CHF-Rappen).
    """
    mutant = mutate(
        ct,
        "contribution_for_year",
        "return amount * occurrences",
        "return amount + occurrences",
    )
    kwargs = dict(
        amount_rappen=1_000_00,
        frequency="monatlich",
        nature="wiederkehrend",
        valid_from=None,
        valid_until=None,
        year=2026,
    )
    expected = 12 * 1_000_00  # == test_monatlich_ganzes_jahr
    assert ct.contribution_for_year(**kwargs) == expected
    assert mutant(**kwargs) != expected


def test_mutation_einmalig_year_equality_flipped():
    """``event_date.year == year`` durch ``!=`` ersetzt (RelationalOperator).

    Bricht ``test_einmalig_richtiges_jahr``: der einmalige Cashflow im
    richtigen Jahr wuerde mit der Mutation auf 0 statt den vollen Betrag
    kollabieren.
    """
    mutant = mutate(
        ct,
        "contribution_for_year",
        "return amount if event_date.year == year else 0",
        "return amount if event_date.year != year else 0",
    )
    kwargs = dict(
        amount_rappen=100_000_00,
        frequency="einmalig",
        nature="einmalig",
        valid_from="2026-06-15",
        valid_until="2026-06-15",
        year=2026,
    )
    expected = 100_000_00  # == test_einmalig_richtiges_jahr
    assert ct.contribution_for_year(**kwargs) == expected
    assert mutant(**kwargs) != expected
    assert mutant(**kwargs) == 0


def test_mutation_occurrence_index_off_by_one():
    """Anker-Offset ``k * months_per_occurrence`` durch ``(k + 1) * ...`` ersetzt.

    Verschiebt jede Occurrence um einen Monat und verliert dadurch genau eine
    Occurrence pro Jahr (11 statt 12 bei monatlicher Zahlung). Bricht
    ``test_monatlich_ganzes_jahr``.
    """
    mutant = mutate(
        ct,
        "contribution_for_year",
        "occ = _add_months(anchor, k * months_per_occurrence)",
        "occ = _add_months(anchor, (k + 1) * months_per_occurrence)",
    )
    kwargs = dict(
        amount_rappen=1_000_00,
        frequency="monatlich",
        nature="wiederkehrend",
        valid_from=None,
        valid_until=None,
        year=2026,
    )
    expected = 12 * 1_000_00  # == test_monatlich_ganzes_jahr
    assert ct.contribution_for_year(**kwargs) == expected
    assert mutant(**kwargs) != expected
    assert mutant(**kwargs) == 11 * 1_000_00


def test_mutation_occurrence_boundary_strict_to_inclusive():
    """Boundary-Mutation: ``occ > effective_end`` durch ``occ >= effective_end``.

    Fuer einen Cashflow, dessen einzige Occurrence GENAU auf effective_end
    faellt (valid_from == valid_until, monatlich), zaehlt das Original diese
    eine Occurrence noch; die Mutation bricht VOR dem Zaehlen ab -> 0 statt
    dem vollen Betrag. Kein direkt-benannter bestehender Test deckt exakt
    diese Grenze ab; der Erwartungswert ist hier analytisch hergeleitet
    (1 Occurrence * Betrag) und durch die Formel selbst nachvollziehbar.
    """
    mutant = mutate(
        ct,
        "contribution_for_year",
        "if occ > effective_end:",
        "if occ >= effective_end:",
    )
    kwargs = dict(
        amount_rappen=1_000_00,
        frequency="monatlich",
        nature="wiederkehrend",
        valid_from="2026-06-15",
        valid_until="2026-06-15",
        year=2026,
    )
    expected = 1_000_00  # genau 1 Occurrence am 15.06.
    assert ct.contribution_for_year(**kwargs) == expected
    assert mutant(**kwargs) != expected
    assert mutant(**kwargs) == 0


# ── _compound_inflation_factor ─────────────────────────────────────────────

def test_mutation_inflation_compounding_sign_flipped():
    """``1.0 + inflation/10000`` durch ``1.0 - inflation/10000`` ersetzt.

    Klassischer Vorzeichen-Fehler: Inflation wuerde Kaufkraft/Betraege
    SENKEN statt kumulativ ERHOEHEN. Bei 3 Jahren mit je 5% (500 bps) muss
    der Faktor > 1 sein (1.05^3 approx 1.1576); die Mutation liefert < 1.
    """
    mutant = mutate(
        ct,
        "_compound_inflation_factor",
        "factor *= 1.0 + (int(inflation or 0) / 10000.0)",
        "factor *= 1.0 - (int(inflation or 0) / 10000.0)",
    )
    args = ([500, 500, 500], 2026, 2029)
    expected = 1.05 ** 3
    real = ct._compound_inflation_factor(*args)
    assert abs(real - expected) < 1e-9
    mutated = mutant(*args)
    assert mutated != real
    assert mutated < 1.0  # Inflation wuerde Betrag faelschlich schrumpfen


def test_mutation_inflation_loop_bound_off_by_one():
    """``range(offset)`` durch ``range(offset + 1)`` ersetzt (Off-by-One).

    Kumuliert einen Inflationsschritt zu viel -> Faktor zu hoch fuer
    dasselbe Zieljahr.
    """
    mutant = mutate(
        ct,
        "_compound_inflation_factor",
        "for i in range(offset):",
        "for i in range(offset + 1):",
    )
    args = ([500, 500, 500], 2026, 2029)
    expected = 1.05 ** 3
    real = ct._compound_inflation_factor(*args)
    assert abs(real - expected) < 1e-9
    mutated = mutant(*args)
    assert mutated != real
    assert abs(mutated - 1.05 ** 4) < 1e-9  # ein Jahr zu viel kumuliert


def test_mutation_inflation_offset_sign_flipped():
    """``target_year - base`` durch ``target_year + base`` ersetzt.

    Zerstoert die Offset-Berechnung komplett (riesige statt kleine
    Jahresdifferenz) -- der Faktor explodiert fuer jedes realistische
    Zieljahr weit ausserhalb des plausiblen Bereichs.
    """
    mutant = mutate(
        ct,
        "_compound_inflation_factor",
        "offset = int(target_year) - base",
        "offset = int(target_year) + base",
    )
    args = ([500, 500, 500], 2026, 2029)
    expected = 1.05 ** 3
    real = ct._compound_inflation_factor(*args)
    assert abs(real - expected) < 1e-9
    mutated = mutant(*args)
    assert mutated != real
    assert mutated > 1e10  # voellig unplausibler Faktor
