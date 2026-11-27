"""L2d (CTO-Zusatz, K3-Pruefer): Depot-Snapshot-Stichtag um Mitternacht.

Befund (schon auf 56ec62fa): ``tests/test_depot_snapshot_ist_stress.py`` war
kurz nach Mitternacht (Schweiz) in 4 Tests rot, USD-Kurs «MISMATCH».
Ursache war ein Produktfehler, kein reiner Testfehler: Der Depot-Snapshot
nahm als Stichtag das UTC-Datum (``routers/allocation.py`` create_depot_snapshot
und ``routers/pdf_reports.py`` Depotcheck-PDF: ``datetime.now(timezone.utc).date()``;
``services/portfolio_data_release_gate.py``: ``advice_at.date()`` mit UTC-advice_at).
Preise, Bestandsstichtage und manuell erfasste Kurse tragen aber den
Kalendertag des Beraters (Prozess-Zeitzone, Stichtag-Regel KN7). Zwischen
00:00 und 01:00 (Sommer 02:00) Schweizer Zeit lag ein heute erfasster Kurs
deshalb «nach dem Stichtag» -> MISMATCH, der Snapshot und damit Depotcheck-
PDF und Freigabe-Gate waren gesperrt.

Fix: Stichtag = Kalendertag der Prozess-Zeitzone (``database.validity_day``,
gleiche Regel wie ``services.fx_basis.resolve_as_of``). Kursbeobachtungen mit
Zeitpunkt (die FX-API schreibt UTC ``...Z``) werden fuer den Vergleich in
dieselbe Zeitbasis umgerechnet (``services.currency.fx_rates.observed_day``).

Gegenprobe: Stichtag in create_depot_snapshot wieder ``datetime.now(timezone.utc).date()``
-> unter Europe/Zurich um 23:30 UTC (Winter) und 22:30 UTC (Sommer) rot
(FxBasisError MISMATCH).
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from tests.test_depot_snapshot_ist_stress import _create, _seed, session_factory  # noqa: F401
from tests.test_kn7_midnight_boundary import _travel, process_zone  # noqa: F401

# Wie KN7, aber nach den festen Datumswerten der Depot-Fixture (NOW 2026-10-26).
BOUNDARY_INSTANTS = (
    datetime(2026, 11, 21, 22, 30, tzinfo=timezone.utc),  # Zuerich 23:30, gleicher Tag
    datetime(2026, 11, 21, 23, 30, tzinfo=timezone.utc),  # Zuerich 00:30 am 22.11.
    datetime(2026, 11, 22, 0, 30, tzinfo=timezone.utc),   # beide 22.11.
    datetime(2027, 6, 30, 22, 30, tzinfo=timezone.utc),   # Sommer: Zuerich 00:30 am 1.7.
)


@pytest.mark.parametrize("instant", BOUNDARY_INSTANTS, ids=lambda i: i.strftime("%Y%m%d-%H%MZ"))
def test_depot_snapshot_stichtag_is_the_process_calendar_day(session_factory, process_zone, instant):
    with _travel(instant, process_zone):
        local = date.today()
        if process_zone is not None:
            assert local == instant.astimezone(ZoneInfo(process_zone)).date()
        with session_factory() as s:
            advisor, mandate = _seed(s)  # Preise und Bestand mit dem Kalendertag des Beraters
            s.commit()
            created = _create(s, mandate, advisor)  # Kurs heute erfasst (Testvektor)
        assert created["snapshot"]["as_of"] == local.isoformat()


@pytest.mark.parametrize("instant", BOUNDARY_INSTANTS, ids=lambda i: i.strftime("%Y%m%d-%H%MZ"))
def test_utc_timestamp_observation_is_compared_in_the_process_zone(process_zone, instant):
    """Die FX-API schreibt valid_from als UTC-Zeitpunkt. Ein eben erfasster Kurs
    ist am Stichtag (Prozess-Kalendertag) nie «nach dem Stichtag»."""
    from services.currency.fx_rates import FX_STATUS_OK, observed_day, quote_status

    stamp = instant.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    with _travel(instant, process_zone):
        local = date.today()
        assert observed_day(stamp) == local
        assert quote_status("Manual", stamp, as_of=local, max_age_days=5) == FX_STATUS_OK
    # Reines Datum bleibt unveraendert, Unlesbares ist None.
    assert observed_day("2026-11-22") == date(2026, 11, 22)
    assert observed_day("kaputt") is None and observed_day(None) is None
