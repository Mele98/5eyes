"""Bankarbeitstag-Kalender fuer die Depot-Frische (PORTFOLIO-DATA-001).

Im Repo gibt es keinen Bank- oder Boersenfeiertagskalender. Die bestehende
Wochenend-Logik (``services/market_data_daily_refresh._most_recent_business_day``)
modelliert ausdruecklich keine Feiertage. Dieses Modul definiert deshalb nur
die Schnittstelle ``BankCalendar`` und eine Implementierung, die allein
Wochenenden kennt. Feiertage werden hier nicht erfunden.

Owner-Entscheid offen: welcher Bankfeiertagskalender (Quelle, Region,
Pflegeprozess) gilt. Bis dahin ist ``holidays_modelled`` False, und jede
Auswertung traegt diesen Hinweis sichtbar mit. Wirkung der Luecke: ein
Feiertag zaehlt als Bankarbeitstag; die Frische wird also eher zu streng
(ein Tag aelter) als zu grosszuegig beurteilt.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Protocol, runtime_checkable

WEEKEND_ONLY_CALENDAR_ID = "weekend-only/v1"

HOLIDAYS_NOT_MODELLED_NOTE = (
    "Bankfeiertage sind nicht modelliert (nur Wochenenden). Owner-Entscheid "
    "offen: Feiertagskalender und Quelle festlegen. Ein Feiertag zaehlt bis "
    "dahin als Bankarbeitstag; die Frische wird dadurch eher strenger beurteilt."
)


@runtime_checkable
class BankCalendar(Protocol):
    """Schnittstelle eines Bankarbeitstag-Kalenders."""

    calendar_id: str
    holidays_modelled: bool

    def is_business_day(self, day: date) -> bool:  # pragma: no cover - Protocol
        ...


class WeekendOnlyBankCalendar:
    """Montag bis Freitag sind Bankarbeitstage; Feiertage sind nicht modelliert."""

    calendar_id = WEEKEND_ONLY_CALENDAR_ID
    holidays_modelled = False
    limitation_note = HOLIDAYS_NOT_MODELLED_NOTE

    def is_business_day(self, day: date) -> bool:
        return day.weekday() < 5


_CALENDARS: dict[str, type] = {WEEKEND_ONLY_CALENDAR_ID: WeekendOnlyBankCalendar}


def calendar_for_id(calendar_id: str) -> BankCalendar:
    """Kalender zur ID; eine unbekannte ID ist ein Konfigurationsfehler."""
    try:
        return _CALENDARS[calendar_id]()
    except KeyError as exc:
        raise ValueError(f"Unbekannter Bankkalender: {calendar_id!r}") from exc


def business_days_elapsed(calendar: BankCalendar, as_of: date, reference: date) -> int:
    """Anzahl Bankarbeitstage d mit ``as_of < d <= reference``.

    ``as_of == reference`` ergibt 0 (Stichtag T), der letzte Bankarbeitstag
    vor T ergibt 1 (T-1). Ein Stichtag nach ``reference`` ist ungueltig.
    """
    if as_of > reference:
        raise ValueError("Stichtag liegt nach dem Referenzdatum.")
    count = 0
    day = as_of + timedelta(days=1)
    while day <= reference:
        if calendar.is_business_day(day):
            count += 1
        day += timedelta(days=1)
    return count
