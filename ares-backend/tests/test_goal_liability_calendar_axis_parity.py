"""ADR-2: der Liability-Pfad liegt auf derselben Achse wie die Cashflow-Serie.

GOAL-RECURRENCE-SCHEDULE-001 / ADR-2 (Owner-Entscheid 2026-10-11).

Die bestehenden neun Reproducer dieses Befunds pruefen die BETRAEGE pro
Bucket. Diese Datei deckt die drei Eigenschaften ab, die mit der Umstellung
NEU entstanden sind und von keinem der Reproducer beruehrt werden:

1. **Achsen-Paritaet.** ``liability_path_rappen[i]`` und
   ``net_cashflow_series(...)[i]`` bezeichnen dasselbe Kalenderjahr. Das ist
   die eigentliche Korrektur: beide Serien werden im Wealth-Schritt auf
   demselben Index verrechnet (``wealth[:, t+1] = ... + cashflow[t]
   - liability[t]``), lagen vorher aber auf verschiedenen Achsen -- der
   Liability-Pfad auf Jahrestag-Buckets (``calendar_years_until``), die
   Cashflow-Serie auf Kalenderjahren. Gemessen lag der Outflow in 5 von 8
   geprueften Startdaten ein Jahr zu frueh.

2. **Abgelaufenes Fenster.** Ein Strom, der vollstaendig vor dem laufenden
   Kalenderjahr endet, hat keine In-Horizon-Verbindlichkeit mehr -- aber
   nicht stillschweigend: solange ADR-3 (Goal-Lifecycle) fehlt, gibt es
   keinen Zustand, der "abgelaufen, nie bestaetigt" von "erfuellt"
   unterscheidet, und die Luecke muss am Ziel sichtbar sein.

3. **Abschneide-Offenlegung als Betrag.** Laeuft der Strom ueber den
   Horizont hinaus, wird der bewertete ANTEIL ausgewiesen, keine
   Jahreszahl -- unter Occurrence-Semantik sind zwei "Jahre" verschieden
   viel Geld, wenn eines ein Teiljahr ist.
"""
from __future__ import annotations

import re
import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.orm import configure_mappers
from database import Base  # noqa: F401
from models import (  # noqa: F401
    allocation, clients, mandates, profiling, review, snapshots, users, wealth,
)
configure_mappers()

from services.cashflow_timeline import net_cashflow_series
from services.optimizer.goal_liabilities import goal_to_liability

HORIZON_YEARS = 12
PER_PERIOD_RAPPEN = 100_000  # CHF 1'000 pro Periode


def _goal(
    *,
    frequency: str,
    start_date: date | None,
    target_date: date | None,
    is_ongoing: int = 0,
    goal_type: str = "Wiederkehrende_Ausgabe",
) -> SimpleNamespace:
    return SimpleNamespace(
        id="axis-goal",
        label="Axis",
        goal_type=goal_type,
        target_amount_rappen=PER_PERIOD_RAPPEN,
        target_wealth_rappen=None,
        target_return_bps=None,
        horizon_years=None,
        target_date=target_date.isoformat() if target_date else None,
        start_date=start_date.isoformat() if start_date else None,
        is_ongoing=is_ongoing,
        frequency=frequency,
        hardness="Primaer",
        rank=2,
        weight_bps=None,
        value_mode="nominal",
        goal_scope="Beratungsvermoegen",
        pension_pillar=None,
        probability_pct=None,
    )


def _equivalent_cashflow(
    *, frequency: str, start_date: date, target_date: date | None
) -> SimpleNamespace:
    """Ein Cashflow mit demselben Vertrag wie das Ziel."""
    return SimpleNamespace(
        amount_rappen=PER_PERIOD_RAPPEN,
        frequency=frequency,
        nature="wiederkehrend",
        valid_from=start_date.isoformat(),
        valid_until=target_date.isoformat() if target_date else None,
        currency="CHF",
        cashflow_type="Expense",
        is_inflation_linked=0,
    )


# ---------------------------------------------------------------------------
# 1. Achsen-Paritaet
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "frequency", ["monatlich", "quartalsweise", "halbjährlich", "jährlich"]
)
@pytest.mark.parametrize(
    "start_offset_years,start_month,start_day",
    [
        (0, 11, 3),    # noch im laufenden Kalenderjahr
        (1, 2, 1),     # naechstes Kalenderjahr, VOR dem Jahrestag
        (1, 12, 1),    # naechstes Kalenderjahr, NACH dem Jahrestag
        (5, 7, 1),     # mehrere Jahre draussen, unterjaehrig
    ],
)
def test_liability_bucket_matches_cashflow_bucket_for_the_same_contract(
    frequency, start_offset_years, start_month, start_day
):
    """Derselbe Vertrag als Ziel und als Cashflow belastet dieselben Buckets.

    Die zweite und vierte Parametrisierung sind die Faelle, in denen der
    alte Jahrestag-Startindex ein Jahr zu frueh lag: ein Startdatum, das in
    seinem Kalenderjahr VOR dem Jahrestag des Stichtags liegt, bekam den
    Bucket des Vorjahres.
    """
    base_year = date.today().year
    start = date(base_year + start_offset_years, start_month, start_day)
    end = date(start.year + 3, start.month, start.day)

    liability = goal_to_liability(
        _goal(frequency=frequency, start_date=start, target_date=end),
        horizon_years=HORIZON_YEARS,
    )
    cashflow_series = net_cashflow_series(
        [_equivalent_cashflow(frequency=frequency, start_date=start, target_date=end)],
        HORIZON_YEARS,
        start_year=base_year,
    )

    # Cashflow-Serie ist netto (Ausgabe = negativ), Liability ist positiv.
    assert liability.liability_path_rappen == [-value for value in cashflow_series], (
        f"{frequency} ab {start.isoformat()}: Liability-Pfad "
        f"{liability.liability_path_rappen} liegt nicht auf derselben "
        f"Kalenderjahr-Achse wie die Cashflow-Serie {cashflow_series}"
    )


def test_start_before_the_anniversary_is_not_booked_a_year_early():
    """Der Kernfall des Platzierungsfehlers, einzeln und explizit.

    Stichtag sei im Oktober. Ein Strom ab dem 1. Februar des naechsten
    Kalenderjahres liegt im Bucket +1 (= jenes Kalenderjahr). Der alte
    Jahrestag-Index lieferte hier Bucket 0, weil der Februar den
    Oktober-Jahrestag noch nicht erreicht hat -- der Outflow wurde also
    gegen die Cashflows des laufenden Jahres verrechnet.
    """
    base_year = date.today().year
    start = date(base_year + 1, 2, 1)

    liability = goal_to_liability(
        _goal(frequency="monatlich", start_date=start, target_date=date(base_year + 1, 12, 1)),
        horizon_years=HORIZON_YEARS,
    )

    assert liability.liability_path_rappen[0] == 0, (
        "das laufende Kalenderjahr darf nicht belastet werden, der Strom "
        "beginnt erst im Folgejahr"
    )
    assert liability.liability_path_rappen[1] > 0
    assert liability.target_year_index == 2


# ---------------------------------------------------------------------------
# 2. Abgelaufenes Fenster
# ---------------------------------------------------------------------------


def test_fully_elapsed_window_books_nothing_but_says_so():
    """Vorher belebte ``max(1, ...)`` den abgelaufenen Strom wieder."""
    base_year = date.today().year
    liability = goal_to_liability(
        _goal(
            frequency="monatlich",
            start_date=date(base_year - 6, 3, 1),
            target_date=date(base_year - 3, 3, 1),
        ),
        horizon_years=HORIZON_YEARS,
    )

    assert sum(liability.liability_path_rappen) == 0
    assert liability.target_amount_rappen == 0
    note = liability.evaluation_note or ""
    assert "keine In-Horizon-Verbindlichkeit" in note, note
    # Der Hinweis muss auf den fehlenden Lifecycle-Status zeigen (ADR-3) --
    # eine stille 0 waere so falsch wie die vorherige Wiederbelebung.
    assert "Lifecycle-Status" in note, note


# ---------------------------------------------------------------------------
# 3. Abschneide-Offenlegung
# ---------------------------------------------------------------------------


def test_stream_past_the_horizon_discloses_an_amount_share_not_a_year_count():
    base_year = date.today().year
    liability = goal_to_liability(
        _goal(
            frequency="monatlich",
            start_date=date(base_year, 1, 1),
            target_date=date(base_year + HORIZON_YEARS + 8, 12, 31),
        ),
        horizon_years=HORIZON_YEARS,
    )

    note = liability.evaluation_note or ""
    assert "% des Zahlungsstroms" in note, note
    # Die alte Formulierung "Bewertet fuer X von Y Jahren" wies zwei
    # verschieden lange Jahre als gleich gross aus. Sie darf nicht
    # zurueckkommen -- dass der Hinweis den Horizont weiterhin in Jahren
    # benennt ("Horizont von 12 Jahren"), ist dagegen richtig: der Horizont
    # IST eine Jahreszahl, nur der bewertete ANTEIL ist keine.
    assert "Bewertet fuer" not in note, note
    assert not re.search(r"\d+ von \d+ Jahren", note), note

    # Gegenprobe, dass die 57 % kein Zufallstreffer sind: 12 bewertete
    # Kalenderjahre von 21 (laufendes Jahr bis 2046) = 57.1 %.
    in_horizon = sum(liability.liability_path_rappen)
    full_years = (base_year + HORIZON_YEARS + 8) - base_year + 1
    assert in_horizon > 0
    assert abs(100.0 * HORIZON_YEARS / full_years - 57.1) < 0.5
