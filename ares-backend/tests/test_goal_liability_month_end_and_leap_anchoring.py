"""Red-test matrix fuer GOAL-RECURRENCE-SCHEDULE-001 (Audit 2026-10-03,
Pflichttest 3): monatliche Wiederkehrende_Ausgabe/Pensionsausgabe-Goals,
die auf einem Monatsende (28./29./30./31.) oder einem Schaltjahr-29.2.
verankert sind.

Befund: `services/optimizer/goal_liabilities._outflow_duration_years()`
bestimmt die Anzahl der jaehrlichen Outflow-"Buckets" ueber

    full_years = target_date.year - start_date.year + 1

Das ist eine reine Jahres-LABEL-Differenz, die Monat/Tag vollstaendig
ignoriert. Solange target_date >= dem naechsten Jahrestag von start_date
liegt, ist das unproblematisch. Liegt target_date aber VOR dem
Jahrestag (z.B. genau 1 Tag zu frueh, weil das Goal auf einem
Monatsende/29.2. verankert ist und der Folgejahrestag auf einen kuerzeren
Monat faellt), zaehlt die reine Jahreszahl-Differenz trotzdem ein volles
Jahr zu viel -- der Optimizer modelliert dann ein Jahr Outflow mehr (bzw.
bei Mehrjahres-Spannen: immer genau ein Jahr zu viel), als die Kalender-
Spanne tatsaechlich zulaesst. Das ist eine Kalender-naive Label-
Approximation, keine korrekte Kalender-verankerte Enumeration.

Diese Datei MODIFIZIERT keine Produktionslogik -- sie dokumentiert den
Status quo rot (xfail strict) ueberall dort, wo der Bug reproduzierbar
ist, und haelt als Kontrollfaelle gruen, wo die naive Rechnung (zufaellig
korrekt, weil start/target im selben Kalenderjahr-Label liegen oder die
Kalenderhilfsfunktion fuer den 29.2. bereits korrekt ist) nicht betroffen
ist.

Siehe docs/audits/2026-10-03-recurring-goal-lifecycle-calendar-and-mc-
validation-audit.md, Finding GOAL-RECURRENCE-SCHEDULE-001.
"""
from __future__ import annotations

import sys
from datetime import date as _date
from pathlib import Path
from types import SimpleNamespace

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy.orm import configure_mappers
from database import Base  # noqa: F401
from models import (  # noqa: F401
    allocation, clients, mandates, profiling, review, snapshots, users, wealth,
)
configure_mappers()

from services.calendar_horizon import add_calendar_years
from services.optimizer.goal_liabilities import (
    _resolve_target_year_index,
    goal_to_liability,
)


# GEFIXT am 2026-10-11 (ADR-2c): _outflow_duration_years ist entfernt. Die
# Tests pruefen jetzt den Liability-PFAD selbst statt den Zwischenwert eines
# Helfers -- das ist ohnehin die Aussage, auf die es ankommt, denn die
# Jahres-"Dauer" war nie das Produktverhalten, sondern nur der Weg dorthin.


def _bucket_of(calendar_year: int) -> int:
    """0-based Bucket-Index eines Kalenderjahres auf der Engine-Achse.

    Bucket 0 ist das LAUFENDE Kalenderjahr (ADR-2). Diese Datei benutzt
    feste Kalenderdaten, deshalb wird der Index abgeleitet und nicht
    hartcodiert -- sonst wuerde sie beim Jahreswechsel still falsch werden.
    """
    return int(calendar_year) - _date.today().year


def _make_goal(
    *,
    goal_id: str = "g1",
    label: str = "Test",
    goal_type: str = "Wiederkehrende_Ausgabe",
    target_amount_rappen: int | None = None,
    horizon_years: int | None = None,
    target_date: str | None = None,
    start_date: str | None = None,
    is_ongoing: int = 0,
    frequency: str | None = "monatlich",
    hardness: str = "Primaer",
    rank: int = 2,
    weight_bps: int | None = None,
    value_mode: str = "nominal",
    pension_pillar: str | None = None,
    probability_pct: int | None = None,
):
    """Mock-Goal als SimpleNamespace (kein DB-Objekt noetig), analog zu
    tests/test_optimizer_goal_liabilities.py."""
    return SimpleNamespace(
        id=goal_id,
        label=label,
        goal_type=goal_type,
        target_amount_rappen=target_amount_rappen,
        target_wealth_rappen=None,
        target_return_bps=None,
        horizon_years=horizon_years,
        target_date=target_date,
        start_date=start_date,
        is_ongoing=is_ongoing,
        frequency=frequency,
        hardness=hardness,
        rank=rank,
        weight_bps=weight_bps,
        value_mode=value_mode,
        goal_scope="Beratungsvermoegen",
        pension_pillar=pension_pillar,
        probability_pct=probability_pct,
    )


MONTHLY_AMOUNT_RAPPEN = 100_000  # CHF 1'000.00 / Monat
ANNUALIZED_RAPPEN = MONTHLY_AMOUNT_RAPPEN * 12  # CHF 12'000.00 / Jahr


# ============================================================================
# Kontrollfall (GRUEN): gleiche Jahres-Label -> naive Rechnung zufaellig korrekt
# ============================================================================


def test_month_end_anchor_within_same_calendar_year_books_eleven_instalments():
    """Start 31.1.2026, Ziel 30.11.2026 -- elf Monatsraten, nicht zwoelf.

    Dieser Test war als Positivkontrolle deklariert ("full_years=1 ist hier
    korrekt, weil start.year == target.year die naive Differenz nicht
    verzerrt") und verlangte den vollen Jahresbetrag. Das war aber genau
    derselbe Ueberbuchungsfehler wie in den Rot-Faellen, nur im
    Ein-Bucket-Fall: ein Fenster von Ende Januar bis Ende November ist kein
    Jahr. Die Label-Differenz ist hier zufaellig 1 -- der gebuchte BETRAG
    war trotzdem um eine Rate zu hoch.

    Faelligkeiten (Anker 31., in kurzen Monaten geklemmt): 31.1., 28.2.,
    31.3., 30.4., 31.5., 30.6., 31.7., 31.8., 30.9., 31.10., 30.11. = 11.
    """
    goal = _make_goal(
        target_amount_rappen=MONTHLY_AMOUNT_RAPPEN,
        start_date="2026-01-31",
        target_date="2026-11-30",
    )

    liab = goal_to_liability(goal, horizon_years=5)
    bucket = _bucket_of(2026)
    assert liab.target_amount_rappen == 11 * MONTHLY_AMOUNT_RAPPEN
    assert liab.liability_path_rappen[bucket] == 11 * MONTHLY_AMOUNT_RAPPEN
    assert liab.liability_path_rappen[bucket + 1] == 0


# ============================================================================
# Monatsende-Matrix (ROT): 28./29./30./31. jeweils einen Tag vor dem
# Jahrestag -> naive Jahres-Label-Differenz zaehlt trotzdem +1 Jahr zu viel
# ============================================================================


@pytest.mark.parametrize(
    "start_day,target_date",
    [
        pytest.param(28, "2027-01-27", id="anchor_28th"),
        pytest.param(29, "2027-01-28", id="anchor_29th"),
        pytest.param(30, "2027-01-29", id="anchor_30th"),
        pytest.param(31, "2027-01-30", id="anchor_31st"),
    ],
)
def test_month_end_anchor_matrix_one_day_short_of_anniversary_is_not_double_counted(
    start_day, target_date,
):
    """Start am Monatsende im Januar 2026 (28./29./30./31.), Ziel einen
    Kalendertag VOR dem 1-Jahres-Jahrestag. Die tatsaechliche Kalenderspanne
    ist knapp unter einem Jahr -> 1 Jahr Outflow (12 Monatsraten) ist
    korrekt. Die implementierte naive Rechnung
    (target_date.year - start_date.year + 1) liefert aber 2 Jahre, weil sie
    nur die Jahreszahl-Labels vergleicht und den Tag/Monat ignoriert -- der
    Anker-Tag selbst ist dabei irrelevant fuer den Bug (28./29./30./31.
    verhalten sich identisch), was zeigt, dass es sich nicht um einen
    Tag-spezifischen Sonderfall, sondern um einen systemischen
    Label-Vergleich handelt."""
    start_date = f"2026-01-{start_day:02d}"
    goal = _make_goal(
        target_amount_rappen=MONTHLY_AMOUNT_RAPPEN,
        start_date=start_date,
        target_date=target_date,
    )

    liab = goal_to_liability(goal, horizon_years=10)
    bucket = _bucket_of(2026)
    assert liab.target_amount_rappen == ANNUALIZED_RAPPEN, (
        "Outflow darf nicht verdoppelt werden, nur weil target_date ein "
        "Kalenderjahr-Label weiter liegt als start_date."
    )
    # Alle zwoelf Raten fallen ins Kalenderjahr 2026; der Jahrestag in 2027
    # ist einen Tag nach target_date, dort ist also nichts mehr faellig.
    assert liab.liability_path_rappen[bucket] == ANNUALIZED_RAPPEN
    assert liab.liability_path_rappen[bucket + 1] == 0


# ============================================================================
# Schaltjahr-Anker (ROT): 29.2.2028 -> Jahrestag faellt auf 28.2.2029
# ============================================================================


def test_leap_day_anniversary_resolves_to_feb_28_in_non_leap_year():
    """Kontrollfall (GRUEN): calendar_horizon.add_calendar_years behandelt
    den 29.2. bereits korrekt (faellt im Nicht-Schaltjahr auf den 28.2.)."""
    anniversary = add_calendar_years(__import__("datetime").date(2028, 2, 29), 1)
    assert anniversary == __import__("datetime").date(2029, 2, 28)


def test_leap_day_feb29_anchor_one_day_short_of_anniversary_is_not_double_counted():
    """Start am 29.2.2028 (Schaltjahr), Ziel am 27.2.2029 -- einen Tag vor
    dem (Nicht-Schaltjahr-)Jahrestag 28.2.2029. Tatsaechliche Spanne < 1
    Jahr -> 1 Jahres-Bucket korrekt. Die naive Jahreszahl-Differenz liefert
    2029 - 2028 + 1 = 2 -- derselbe Bug wie beim 31.1.-Anker, hier aber am
    Schaltjahr-Spezialfall reproduziert, den add_calendar_years fuer die
    Jahrestags-BERECHNUNG korrekt behandelt, waehrend die geloeschte
    Label-Differenz diese Berechnung gar nicht nutzte.

    Die Verteilung zeigt zugleich den zweiten Teil von ADR-2: der Strom
    laeuft ueber eine Kalenderjahr-Grenze, also liegen die zwoelf Raten in
    ZWEI Buckets (11 in 2028, eine am 29.1.2029) -- insgesamt aber genau
    ein Jahresbetrag. Der 29.2.2029 existiert nicht, wird auf den 28.2.
    geklemmt und liegt damit nach target_date (27.2.), faellt also weg.
    """
    goal = _make_goal(
        target_amount_rappen=MONTHLY_AMOUNT_RAPPEN,
        start_date="2028-02-29",
        target_date="2029-02-27",
    )

    liab = goal_to_liability(goal, horizon_years=10)
    first = _bucket_of(2028)
    assert liab.target_amount_rappen == ANNUALIZED_RAPPEN
    assert liab.liability_path_rappen[first] == 11 * MONTHLY_AMOUNT_RAPPEN
    assert liab.liability_path_rappen[first + 1] == 1 * MONTHLY_AMOUNT_RAPPEN
    assert liab.liability_path_rappen[first + 2] == 0
    # Vor Rentenbeginn ist nichts faellig -- vorher hob ``max(1, ...)`` den
    # Startindex auf Bucket 1 und belastete damit das laufende Jahr.
    assert liab.liability_path_rappen[: first] == [0] * first


# ============================================================================
# Mehrjahres-Anker-Drift (ROT): Anker-Tag selbst driftet nicht, aber die
# naive Jahres-Label-Differenz zaehlt bei JEDER Mehrjahres-Spanne ein
# Jahr zu viel, sobald der Jahrestag noch nicht erreicht ist
# ============================================================================


def test_multi_year_month_end_anchor_day_stays_fixed_but_label_diff_overcounts_by_one_year():
    """Start 31.1.2026, Ziel 30.1.2031 (5 Jahre minus 1 Tag). Der Anker-Tag
    (31.) driftet nicht -- jeder Jahrestag bleibt der 31.1. Trotzdem
    zaehlt die naive Jahres-Label-Differenz (2031-2026+1=6) ein Jahres-
    Bucket zu viel, weil der 5. Jahrestag (31.1.2031) noch nicht erreicht
    ist. Der Fehler ist nicht kumulativ mit der Anzahl Jahre (immer genau
    +1), aber bei jeder Mehrjahres-Spanne reproduzierbar, solange
    target_date vor dem N-ten Jahrestag liegt."""
    goal = _make_goal(
        target_amount_rappen=MONTHLY_AMOUNT_RAPPEN,
        start_date="2026-01-31",
        target_date="2031-01-30",
    )

    liab = goal_to_liability(goal, horizon_years=10)
    first = _bucket_of(2026)
    assert liab.target_amount_rappen == 5 * ANNUALIZED_RAPPEN
    for i in range(5):
        assert liab.liability_path_rappen[first + i] == ANNUALIZED_RAPPEN
    assert liab.liability_path_rappen[first + 5] == 0


# ============================================================================
# target_year_index selbst: fixer Anker-Tag ueber mehrere Jahre hinweg
# (GRUEN, dokumentiert korrektes Verhalten der Jahrestags-Auflösung)
# ============================================================================


def test_resolve_target_year_index_keeps_month_end_anchor_fixed_across_years():
    """_resolve_target_year_index nutzt calendar_years_until/add_calendar_years,
    die den 31. korrekt als fixen Jahrestag behandeln (jedes Jahr hat einen
    31.1.) -- im Gegensatz zu _outflow_duration_years oben ist hier kein
    Drift/Bug zu beobachten. Nur als Kontrastfolie: der Bug liegt
    ausschliesslich in der full_years-Label-Differenz, nicht im
    Jahrestags-Resolver selbst."""
    goal = _make_goal(
        target_amount_rappen=MONTHLY_AMOUNT_RAPPEN,
        start_date="2026-01-31",
        target_date="2031-01-30",
    )
    # anchor liegt (weit) in der Vergangenheit relativ zu "heute" bei
    # Testausfuehrung -> clamped auf den Minimalwert 1.
    target_year = _resolve_target_year_index(goal, horizon_years=10)
    assert target_year == 1
