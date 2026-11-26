"""KN6 (Integrations-CI 44840465176): feste Wanduhr fuer Testmodule, die beim
Import die Uhr lesen (``TODAY = date.today()``, ``NOW = datetime.now(...)``).

Befund: Der Import (Sammelphase) lag vor Mitternacht, der Test lief danach.
«Morgen» aus Modulsicht war dann schon heute (``'OK' != 'FUTURE_VALUATION_DATE'``
in ``test_stale_fx_and_valuation_after_cutoff_block``). KN5 hatte nur einen Test
der Datei fixiert.

Regel: Jedes Modul mit einer Import-Uhr bindet ``fixed_import_clock(...)`` als
autouse-Fixture. Jeder Test laeuft dann am Importtag (bei einem Datum 12:00 UTC,
bei einem Zeitpunkt genau ab diesem Zeitpunkt), weiterlaufend (``tick=True``).
Der Waechter ``test_import_day_clock_guard.py`` findet neue Module ohne Bindung.
"""
from __future__ import annotations

from datetime import date, datetime, time, timezone

import pytest


def _instant(anchor) -> datetime:
    if isinstance(anchor, str):
        # KN7 / N-928-04: ein reiner Datums-String («2026-11-21») ist ein Datum
        # -> 12:00 UTC wie ein date-Objekt (vorher 00:00 UTC = 01:00 Zuerich,
        # wenige Minuten neben der Tagesgrenze).
        # KN8 / N-929-03: Rand-Leerzeichen fuer Laengenpruefung UND Parser entfernen.
        text = anchor.strip()
        anchor = date.fromisoformat(text) if len(text) == 10 else datetime.fromisoformat(text)
    if isinstance(anchor, datetime):
        return anchor if anchor.tzinfo else anchor.replace(tzinfo=timezone.utc)
    if isinstance(anchor, date):
        return datetime.combine(anchor, time(12, 0), tzinfo=timezone.utc)
    raise TypeError(f"Import-Uhr: unbekannter Anker {anchor!r}")


def fixed_import_clock(anchor):
    """Autouse-Fixture: Wanduhr = Import-Anker, weiterlaufend.

    * ``date`` oder reiner Datums-String («2026-11-21») -> 12:00 UTC dieses Tages;
    * Datetime oder ISO-String mit Uhrzeit -> genau dieser Zeitpunkt (ohne
      Zeitzone als UTC gelesen)."""
    instant = _instant(anchor)

    @pytest.fixture(autouse=True)
    def _fixed_import_clock():
        import time_machine

        with time_machine.travel(instant, tick=True):
            yield instant

    return _fixed_import_clock
