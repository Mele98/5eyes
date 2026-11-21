"""KN7 / N-928-04: Grenztest um Mitternacht (lokales Datum Europe/Zuerich vs. UTC).

Die feste Import-Uhr (tests/import_day_clock.py, KN6) laesst 13 Testmodule am
Importtag um 12:00 UTC laufen. Dort sind lokales und UTC-Datum immer gleich;
ein Datumsgrenzen-Fehler der Produktlogik waere dort nie mehr sichtbar. Dieser
Test faehrt deshalb gezielt ueber die Tagesgrenze, fuer die Stichtag-Logik der
abgeschirmten Module (services/fx_basis.resolve_as_of und die Bewertung
«Bewertungsdatum nach dem Stichtag» in services/holdings_valuation):

* Zeitpunkte 22:30 / 23:30 / 00:30 UTC im Winter (Zuerich = UTC+1) und 22:30 UTC
  im Sommer (Zuerich = UTC+2) -- dort liegen UTC- und Zuercher Datum auseinander.
* Prozess-Zeitzone UTC (CI-Runner) und Europe/Zurich (Desktop beim Berater),
  wo ``time.tzset`` verfuegbar ist (Linux/CI); unter Windows die lokale Zone.
* Regel: Der Stichtag ist der Kalendertag der Prozess-Zeitzone; ein am Stichtag
  datierter Wert ist nie «in der Zukunft», ein Wert vom Folgetag immer.

Gegenprobe: ``resolve_as_of`` auf das UTC-Datum umgestellt -> unter
Europe/Zurich um 23:30 UTC rot (Wert von «heute» wird FUTURE_VALUATION_DATE).
"""
from __future__ import annotations

import os
import time
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from tests.test_ccx_p1_snapshot_hash import _seed_realistic_mandate
from tests.test_optimizer_shadow_mode import session_factory  # noqa: F401

BOUNDARY_INSTANTS = (
    datetime(2026, 11, 21, 22, 30, tzinfo=timezone.utc),  # Zuerich 23:30, gleicher Tag
    datetime(2026, 11, 21, 23, 30, tzinfo=timezone.utc),  # Zuerich 00:30 am 22.11.
    datetime(2026, 11, 22, 0, 30, tzinfo=timezone.utc),   # beide 22.11.
    datetime(2026, 6, 30, 22, 30, tzinfo=timezone.utc),   # Sommer: Zuerich 00:30 am 1.7.
)
_CAN_SET_TZ = hasattr(time, "tzset")
PROCESS_ZONES = ("UTC", "Europe/Zurich") if _CAN_SET_TZ else ("lokal",)


@pytest.fixture(params=PROCESS_ZONES)
def process_zone(request):
    if request.param == "lokal":
        yield None
        return
    old = os.environ.get("TZ")
    os.environ["TZ"] = request.param
    time.tzset()
    try:
        yield request.param
    finally:
        if old is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = old
        time.tzset()


def _travel(instant, zone=None):
    """Reist zum Zeitpunkt; mit ``zone`` als ZoneInfo-Ziel, damit time_machine
    auch die Prozess-Zeitzone setzt (nur Unix; CI 44861481744 zeigte, dass ein
    UTC-Ziel die Zone sonst auf UTC haelt)."""
    import time_machine

    destination = instant.astimezone(ZoneInfo(zone)) if zone else instant
    return time_machine.travel(destination, tick=False)


def test_import_clock_treats_a_date_string_like_a_date():
    """N-928-04 Nebenbefund: «2026-11-21» -> 12:00 UTC (vorher 00:00 UTC)."""
    from tests.import_day_clock import _instant

    noon = datetime(2026, 11, 21, 12, 0, tzinfo=timezone.utc)
    assert _instant("2026-11-21") == _instant(date(2026, 11, 21)) == noon
    assert _instant("2026-11-21T23:30:00+00:00") == datetime(2026, 11, 21, 23, 30, tzinfo=timezone.utc)


@pytest.mark.parametrize("instant", BOUNDARY_INSTANTS, ids=lambda i: i.strftime("%m%d-%H%MZ"))
def test_as_of_is_the_process_calendar_day_at_the_boundary(process_zone, instant):
    from services.fx_basis import resolve_as_of

    with _travel(instant, process_zone):
        local = date.today()
        assert resolve_as_of(None) == local
        if process_zone is not None:
            assert local == instant.astimezone(ZoneInfo(process_zone)).date()


def _project(session_factory, mid):
    from models.mandates import Mandate
    from services.holdings_valuation import project_holdings_valuation

    with session_factory() as db:
        mandate = db.query(Mandate).filter(Mandate.id == mid).one()
        return project_holdings_valuation(db, mandate, attest_manual_valuations=True)


def _add_chf_position(db, mid, label, valuation_date: date) -> str:
    import uuid

    from models.mandates import Mandate
    from models.wealth import WealthPosition

    client_id = db.query(Mandate).filter(Mandate.id == mid).one().client_id
    pid = f"pos-{label}-{uuid.uuid4().hex[:6]}"
    now = datetime.now(timezone.utc).isoformat()
    db.add(WealthPosition(
        id=pid, client_id=client_id, label=label, position_type="Depot", assignment="Beratungsvermögen",
        current_value_rappen=1_000_00, currency="CHF", valuation_date=valuation_date.isoformat(),
        alloc_equities_bps=10000, alloc_liquidity_bps=0, is_active=1, created_at=now, updated_at=now,
    ))
    return pid


def test_future_valuation_rule_holds_across_midnight(session_factory, process_zone):
    """Ueber alle Grenzzeitpunkte: Bewertung am Stichtag nie FUTURE, Folgetag
    immer FUTURE; ein Wert mit dem UTC-Datum ist FUTURE genau dann, wenn das
    UTC-Datum nach dem Stichtag liegt (Prozess-Kalendertag)."""
    _advisor, _cid, mid, _aid, _gid = _seed_realistic_mandate(session_factory, suffix="kn7-midnight")
    for instant in BOUNDARY_INSTANTS:
        with _travel(instant, process_zone):
            local = date.today()
            if process_zone is not None:
                assert local == instant.astimezone(ZoneInfo(process_zone)).date()
            utc_day = instant.date()
            with session_factory() as db:
                from models.wealth import WealthPosition

                db.query(WealthPosition).update({"is_active": 0})
                today_pid = _add_chf_position(db, mid, "heute", local)
                tomorrow_pid = _add_chf_position(db, mid, "morgen", local + timedelta(days=1))
                utc_pid = _add_chf_position(db, mid, "utc", utc_day)
                db.commit()
            rows = {r.position_id: r for r in _project(session_factory, mid).rows}
            label = f"{process_zone or 'lokal'} {instant.isoformat()}"
            assert rows[today_pid].data_quality != "FUTURE_VALUATION_DATE", label
            assert rows[tomorrow_pid].data_quality == "FUTURE_VALUATION_DATE", label
            assert (rows[utc_pid].data_quality == "FUTURE_VALUATION_DATE") == (utc_day > local), label


def test_a_day_captured_before_midnight_goes_stale_after_it():
    """Warum die Import-Uhr noetig ist (CI 44840465176): ein vor Mitternacht
    gelesener Tag ist nach Mitternacht «gestern» -- der Grenztest oben liest den
    Tag deshalb erst innerhalb des jeweiligen Zeitpunkts."""
    with _travel(datetime(2026, 11, 21, 23, 59, 50, tzinfo=timezone.utc)):
        captured = datetime.now(timezone.utc).date()
    with _travel(datetime(2026, 11, 22, 0, 0, 30, tzinfo=timezone.utc)):
        assert datetime.now(timezone.utc).date() == captured + timedelta(days=1)
