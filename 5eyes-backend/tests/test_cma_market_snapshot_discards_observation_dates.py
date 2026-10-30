"""Red test fuer CMA-MARKET-SNAPSHOT-001 (Kontrollrunde 48, P2), siehe
docs/audits/2026-10-04-jurisdiction-cma-equity-measurement-snapshot-and-approval-integrity-audit.md.

Befund: services/jurisdiction/data_pipeline.py::fetch_yield_curve_for_jurisdiction()
holt pro konfigurierter Serie (siehe _YIELD_CURVE_REGISTRY) den jeweils
LETZTEN MacroPoint innerhalb eines 30-Tage-Fensters (_LOOKBACK_DAYS) -- jede
Serie kann dabei ein eigenes, tatsaechlich unterschiedliches Beobachtungsdatum
haben (z.B. Wochenend-/Feiertagsluecken, Publikationsverzug je Serie). Die
Funktion gibt aber nur `list[tuple[float, int]]`
((maturity_years, yield_bps)) zurueck -- MacroPoint.date, .series_code und
.source (siehe services/market_data/macro/base.py::MacroPoint) werden
komplett verworfen, bevor compute_cma_candidate_for_jurisdiction() daraus
source_detail["yield_curve"]["fetched_points_bps"] baut (ebenfalls nur
{"maturity_years", "yield_bps"}, kein "date").

Damit kann fetched_at/valid_from auf der resultierenden
CapitalMarketAssumption-Zeile NICHT beweisen, dass die Zinskurve ein
koherenter, replaybarer Markt-Snapshot zu EINEM Stichtag ist -- die
einzelnen Kurvenpunkte koennten (und werden in der Praxis) von
verschiedenen echten Tagen stammen, ohne dass das je nachvollziehbar ist.

Dasselbe Muster gilt fuer fetch_equity_pe_proxy_for_jurisdiction(): der
yfinance-`trailingPE`-Abruf liefert keinerlei Markt-/Fundamentaldaten-
Stichtag (weder im Rueckgabewert noch in source_detail["equity_kgv_mean_reversion"]).

Dieser Test nutzt GENAU das in tests/test_cma_data_pipeline.py etablierte
Muster (monkeypatch der Provider-Factory-Funktionen mit einem Fake-Provider,
der echte MacroPoint-Objekte liefert) -- kein Netzwerkzugriff, keine DB-Seed-
Tabelle noetig: fetch_yield_curve_for_jurisdiction() ist providerbasiert,
nicht DB-gestuetzt.
"""
from __future__ import annotations

import json
import sys
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base
from main import app  # noqa: F401
from services.market_data import MacroPoint
import services.jurisdiction.data_pipeline as dp


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'cma_market_snapshot.db'}",
        connect_args={"check_same_thread": False},
    )
    SF = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield SF
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


class _FakeProvider:
    def __init__(self, points_by_series):
        self._points_by_series = points_by_series

    def get_series(self, series_code, start, end):
        return self._points_by_series.get(series_code, [])


# Zwei echte, UNTERSCHIEDLICHE Beobachtungsdaten, 10 Kalendertage
# auseinander, beide innerhalb des 30-Tage-Lookback-Fensters
# (dp._LOOKBACK_DAYS) -- die Minimal-Reproduktion fuer "eine Zinskurve
# kombiniert Punkte mit genuinely unterschiedlichen Stichtagen".
_NEWER_OBS_DATE = date.today() - timedelta(days=5)
_OLDER_OBS_DATE = date.today() - timedelta(days=15)
assert (_NEWER_OBS_DATE - _OLDER_OBS_DATE).days == 10
assert (date.today() - _OLDER_OBS_DATE).days <= dp._LOOKBACK_DAYS


def test_fetch_yield_curve_discards_per_point_observation_dates(monkeypatch):
    """fetch_yield_curve_for_jurisdiction() MUSS -- fuer einen beweisbar
    koherenten Markt-Snapshot -- irgendeine Moeglichkeit bieten, pro
    zurueckgegebenem Punkt dessen echtes MacroPoint.date wiederzufinden.

    Seed: DE-Zinskurve (ECB), 5 konfigurierte Serien. Serie[0] bekommt einen
    MacroPoint mit date=_NEWER_OBS_DATE (vor 5 Tagen), Serien[1] und [2]
    bekommen MacroPoints mit date=_OLDER_OBS_DATE (vor 15 Tagen) -- also
    GENUINELY unterschiedliche Beobachtungstage innerhalb desselben
    30-Tage-Fensters, wie im Audit-Finding beschrieben.

    Vor dem Fix gab die Funktion nur `list[tuple[float, int]]` zurueck, ohne
    jede Datums-Information; seit CMA-MARKET-SNAPSHOT-001 traegt jeder Punkt
    sein observation_date.
    """
    series_codes = [c for _, c in dp._YIELD_CURVE_REGISTRY["DE"][1]]

    provider = _FakeProvider({
        series_codes[0]: [
            MacroPoint(
                date=_NEWER_OBS_DATE,
                value=Decimal("2.50"),
                series_code=series_codes[0],
                source="ecb",
            )
        ],
        series_codes[1]: [
            MacroPoint(
                date=_OLDER_OBS_DATE,
                value=Decimal("2.70"),
                series_code=series_codes[1],
                source="ecb",
            )
        ],
        series_codes[2]: [
            MacroPoint(
                date=_OLDER_OBS_DATE,
                value=Decimal("3.00"),
                series_code=series_codes[2],
                source="ecb",
            )
        ],
    })
    monkeypatch.setattr(dp, "_build_ecb_provider", lambda: provider)

    points = dp.fetch_yield_curve_for_jurisdiction("DE")

    assert len(points) == 3

    # Die zugrundeliegenden MacroPoints stammen nachweislich von ZWEI
    # verschiedenen echten Tagen (_NEWER_OBS_DATE vs _OLDER_OBS_DATE). Ein
    # Snapshot, der fetched_at/valid_from als EINEN koherenten Stichtag
    # ausgibt, muss diese Divergenz mindestens nachvollziehbar machen --
    # z.B. indem jeder zurueckgegebene Punkt sein eigenes
    # Beobachtungsdatum trägt.
    recovered_dates = {getattr(point, "observation_date", None) for point in points}
    assert recovered_dates == {_NEWER_OBS_DATE, _OLDER_OBS_DATE}, (
        "fetch_yield_curve_for_jurisdiction() muss das reale "
        "Beobachtungsdatum jedes einzelnen Punkts wiedergeben, damit ein "
        "Markt-Snapshot mit nur EINEM fetched_at/valid_from ueberhaupt als "
        "koherent/replaybar nachgewiesen werden kann (CMA-MARKET-SNAPSHOT-001). "
        f"Statt dessen liefert die Funktion nur rohe (maturity, yield_bps)-"
        f"Tupel ohne jede Datums-Information: {points!r}"
    )


def test_compute_candidate_source_detail_has_no_per_point_dates_or_pe_proxy_asof(
    session_factory, monkeypatch
):
    """compute_cma_candidate_for_jurisdiction() persistiert source_detail
    aus genau den verworfenen Werten oben -- dieser Test zeigt, dass auch
    die PERSISTIERTE Zeile (nicht nur die Zwischen-Rueckgabe) weder je
    Zinskurvenpunkt ein Beobachtungsdatum noch fuer den PE-Proxy
    (trailingPE) irgendein Markt-/Fundamentaldaten-Stichtag enthaelt --
    obwohl beide Angaben in der Praxis zu unterschiedlichen echten Tagen
    gehoeren koennen.
    """
    series_codes = [c for _, c in dp._YIELD_CURVE_REGISTRY["DE"][1]]
    provider = _FakeProvider({
        series_codes[0]: [
            MacroPoint(
                date=_NEWER_OBS_DATE,
                value=Decimal("2.0"),
                series_code=series_codes[0],
                source="ecb",
            )
        ],
        series_codes[1]: [
            MacroPoint(
                date=_OLDER_OBS_DATE,
                value=Decimal("2.3"),
                series_code=series_codes[1],
                source="ecb",
            )
        ],
        series_codes[2]: [
            MacroPoint(
                date=_OLDER_OBS_DATE,
                value=Decimal("2.6"),
                series_code=series_codes[2],
                source="ecb",
            )
        ],
    })
    monkeypatch.setattr(dp, "_build_ecb_provider", lambda: provider)
    monkeypatch.setattr(dp, "_fetch_pe_ticker_info", lambda ticker: {"trailingPE": 22.0})

    with session_factory() as db:
        cma = dp.compute_cma_candidate_for_jurisdiction(db, "DE", "2026-07-30")
        db.commit()

        detail = json.loads(cma.source_detail)
        fetched_points = detail["yield_curve"]["fetched_points_bps"]
        kgv_detail = detail["equity_kgv_mean_reversion"]

        # Jeder persistierte Zinskurvenpunkt muss sein eigenes echtes
        # Beobachtungsdatum tragen (hier: _NEWER_OBS_DATE fuer Serie[0],
        # _OLDER_OBS_DATE fuer Serien[1]/[2]) UND der PE-Proxy-Eintrag
        # braucht einen Markt-/Fundamentaldaten-Stichtag.
        assert all("date" in point for point in fetched_points), (
            "source_detail['yield_curve']['fetched_points_bps'] enthaelt nur "
            f"{fetched_points!r} -- kein 'date'-Feld je Punkt, obwohl die "
            "zugrundeliegenden MacroPoints aus zwei verschiedenen echten "
            "Tagen stammen (CMA-MARKET-SNAPSHOT-001)."
        )
        assert "pe_proxy_as_of" in kgv_detail or "market_as_of" in kgv_detail, (
            "source_detail['equity_kgv_mean_reversion'] enthaelt keinen "
            f"Markt-/Fundamentaldaten-Stichtag: {kgv_detail!r} "
            "(CMA-MARKET-SNAPSHOT-001)."
        )
        # Nicht nur Schluessel-Praesenz: die persistierten Daten muessen die
        # ECHTEN Beobachtungstage der jeweiligen Serie sein ...
        dates_by_series = {p["series_code"]: p["date"] for p in fetched_points}
        assert dates_by_series == {
            series_codes[0]: _NEWER_OBS_DATE.isoformat(),
            series_codes[1]: _OLDER_OBS_DATE.isoformat(),
            series_codes[2]: _OLDER_OBS_DATE.isoformat(),
        }
        assert detail["yield_curve"]["observation_date_min"] == _OLDER_OBS_DATE.isoformat()
        assert detail["yield_curve"]["observation_date_max"] == _NEWER_OBS_DATE.isoformat()
        # ... und der Fake-Provider liefert keinen Markt-Stichtag: der
        # Nachweis darf keinen erfinden, sondern nennt offen den Abruftag.
        assert kgv_detail["market_as_of"] is None
        assert kgv_detail["pe_proxy_as_of_basis"].startswith("retrieval_date")
        assert kgv_detail["pe_proxy_as_of"] == kgv_detail["pe_proxy_retrieved_at_utc"][:10]


def test_pe_proxy_as_of_uses_provider_market_time_when_available(monkeypatch):
    """Liefert der Provider regularMarketTime/mostRecentQuarter, werden genau
    diese Stichtage persistiert (nicht der Abruftag)."""
    market_time = 1_785_000_000  # 2026-07-25 (UTC)
    quarter_end = 1_782_777_600  # 2026-06-30 (UTC)
    monkeypatch.setattr(
        dp,
        "_fetch_pe_ticker_info",
        lambda ticker: {
            "trailingPE": 21.4,
            "regularMarketTime": market_time,
            "mostRecentQuarter": quarter_end,
        },
    )
    value, provenance = dp.fetch_equity_pe_proxy_with_provenance("DE")
    assert value == 21
    assert provenance["market_as_of"] == "2026-07-25"
    assert provenance["pe_proxy_as_of"] == "2026-07-25"
    assert provenance["pe_proxy_as_of_basis"] == "provider_market_time"
    assert provenance["pe_earnings_period_end"] == "2026-06-30"
