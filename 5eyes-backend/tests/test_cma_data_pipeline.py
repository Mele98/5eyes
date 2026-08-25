"""WP-DataPipeline (Home-Bias/CMA-Parametrisierung pro Jurisdiktion, 2026-07-30):
Tests fuer services/jurisdiction/data_pipeline.py.

Mockt FRED/ECB-Provider und den yfinance-Abruf (kein Netzwerk-Call, siehe
tests/test_market_data_macro.py fuer das etablierte Mock-Session-Muster --
hier per monkeypatch der Provider-Factory-Funktionen, da data_pipeline.py
explizit dafuer ausgelegt ist ("in Tests via monkeypatch ersetzbar").
"""
from __future__ import annotations

import json
import sys
from datetime import date
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
from models.allocation import CapitalMarketAssumption
from services.market_data import MacroPoint
import services.jurisdiction.data_pipeline as dp


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'cma_data_pipeline.db'}",
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


def _points(*values_pct):
    """Baut MacroPoint-Listen (ein Punkt pro Serie) aus Prozentwerten (z.B. 4.25 = 4.25%)."""
    return [MacroPoint(date=date(2026, 7, 1), value=Decimal(str(v)), series_code="X") for v in values_pct]


_DE_SERIES = dict(dp._YIELD_CURVE_REGISTRY["DE"][1])
_US_SERIES = dict(dp._YIELD_CURVE_REGISTRY["US"][1])


def _full_curve_provider(series_codes, values_pct):
    return _FakeProvider({code: _points(v)[:1] for code, v in zip(series_codes, values_pct)})


# ---------------------------------------------------------------------------
# fetch_yield_curve_for_jurisdiction
# ---------------------------------------------------------------------------


def test_fetch_yield_curve_unknown_jurisdiction_raises_no_source():
    with pytest.raises(dp.NoYieldCurveSourceConfiguredError):
        dp.fetch_yield_curve_for_jurisdiction("XX")


def test_fetch_yield_curve_de_uses_ecb_provider_with_full_data(monkeypatch):
    series_codes = [c for _, c in dp._YIELD_CURVE_REGISTRY["DE"][1]]
    provider = _full_curve_provider(series_codes, [2.5, 2.7, 3.0, 3.2, 3.4])
    monkeypatch.setattr(dp, "_build_ecb_provider", lambda: provider)
    points = dp.fetch_yield_curve_for_jurisdiction("DE")
    assert len(points) == 5
    # 2.5% -> 250 bps
    assert points[0] == (1.0, 250)


def test_fetch_yield_curve_us_uses_fred_provider(monkeypatch):
    series_codes = [c for _, c in dp._YIELD_CURVE_REGISTRY["US"][1]]
    provider = _full_curve_provider(series_codes, [4.0, 4.1, 4.2, 4.3, 4.4, 4.5])
    monkeypatch.setattr(dp, "_build_fred_provider", lambda: provider)
    points = dp.fetch_yield_curve_for_jurisdiction("us")  # case-insensitive
    assert len(points) == 6
    assert points[-1] == (30.0, 450)


def test_fetch_yield_curve_insufficient_points_raises(monkeypatch):
    series_codes = [c for _, c in dp._YIELD_CURVE_REGISTRY["DE"][1]]
    # Nur 2 von 5 Serien liefern einen Punkt -> unter dem Minimum von 3.
    provider = _FakeProvider({series_codes[0]: _points(2.5), series_codes[1]: _points(2.7)})
    monkeypatch.setattr(dp, "_build_ecb_provider", lambda: provider)
    with pytest.raises(dp.InsufficientYieldCurveDataError):
        dp.fetch_yield_curve_for_jurisdiction("DE")


def test_fetch_yield_curve_missing_series_are_skipped_not_fatal(monkeypatch):
    series_codes = [c for _, c in dp._YIELD_CURVE_REGISTRY["DE"][1]]
    # 3 von 5 Serien liefern einen Punkt -> genau am Minimum, kein Fehler.
    provider = _FakeProvider({
        series_codes[0]: _points(2.5),
        series_codes[2]: _points(3.0),
        series_codes[4]: _points(3.4),
    })
    monkeypatch.setattr(dp, "_build_ecb_provider", lambda: provider)
    points = dp.fetch_yield_curve_for_jurisdiction("DE")
    assert len(points) == 3


# ---------------------------------------------------------------------------
# fetch_equity_pe_proxy_for_jurisdiction
# ---------------------------------------------------------------------------


def test_fetch_pe_proxy_unknown_jurisdiction_returns_none():
    assert dp.fetch_equity_pe_proxy_for_jurisdiction("XX") is None


def test_fetch_pe_proxy_returns_trailing_pe(monkeypatch):
    monkeypatch.setattr(dp, "_fetch_pe_ticker_info", lambda ticker: {"trailingPE": 24.7})
    assert dp.fetch_equity_pe_proxy_for_jurisdiction("DE") == 25


def test_fetch_pe_proxy_missing_field_returns_none(monkeypatch):
    monkeypatch.setattr(dp, "_fetch_pe_ticker_info", lambda ticker: {"someOtherField": 1})
    assert dp.fetch_equity_pe_proxy_for_jurisdiction("DE") is None


def test_fetch_pe_proxy_fetch_error_returns_none_no_crash(monkeypatch):
    def _boom(ticker):
        raise RuntimeError("network down")
    monkeypatch.setattr(dp, "_fetch_pe_ticker_info", _boom)
    assert dp.fetch_equity_pe_proxy_for_jurisdiction("DE") is None


def test_fetch_pe_proxy_never_returns_zero_for_missing_data(monkeypatch):
    monkeypatch.setattr(dp, "_fetch_pe_ticker_info", lambda ticker: {})
    result = dp.fetch_equity_pe_proxy_for_jurisdiction("US")
    assert result is None
    assert result != 0


# ---------------------------------------------------------------------------
# compute_cma_candidate_for_jurisdiction
# ---------------------------------------------------------------------------


def _patch_full_de_curve(monkeypatch):
    series_codes = [c for _, c in dp._YIELD_CURVE_REGISTRY["DE"][1]]
    provider = _full_curve_provider(series_codes, [2.0, 2.3, 2.6, 2.9, 3.1])
    monkeypatch.setattr(dp, "_build_ecb_provider", lambda: provider)


def test_compute_candidate_with_pe_proxy_is_data_derived(session_factory, monkeypatch):
    _patch_full_de_curve(monkeypatch)
    monkeypatch.setattr(dp, "_fetch_pe_ticker_info", lambda ticker: {"trailingPE": 22.0})

    with session_factory() as db:
        cma = dp.compute_cma_candidate_for_jurisdiction(db, "DE", "2026-07-30")
        db.commit()

        assert cma.jurisdiction == "DE"
        assert cma.status == "data_derived"
        assert cma.is_current == 0
        assert cma.bonds_home_ig_return_bps is not None
        assert cma.equity_home_return_bps is not None
        assert cma.computed_by == "system:cma_data_pipeline"
        assert cma.computed_at is not None
        # Real-Estate/Alternatives duerfen NIE automatisch befuellt werden.
        assert getattr(cma, "real_estate_home_return_bps", None) is None
        assert getattr(cma, "real_estate_home_vol_bps", None) is None

        detail = json.loads(cma.source_detail)
        assert detail["jurisdiction"] == "DE"
        assert detail["yield_curve"]["provider"] == "ecb"
        assert "pe_proxy_ticker" in detail["equity_kgv_mean_reversion"]
        assert detail["equity_kgv_mean_reversion"]["pe_proxy_value_kgv_current"] == 22.0

        # Persistiert (db.flush innerhalb der Funktion, hier zusaetzlich committed).
        reloaded = db.query(CapitalMarketAssumption).filter(
            CapitalMarketAssumption.id == cma.id
        ).first()
        assert reloaded is not None
        assert reloaded.jurisdiction == "DE"


def test_compute_candidate_without_pe_proxy_leaves_equity_null(session_factory, monkeypatch):
    _patch_full_de_curve(monkeypatch)
    monkeypatch.setattr(dp, "_fetch_pe_ticker_info", lambda ticker: {})  # kein trailingPE

    with session_factory() as db:
        cma = dp.compute_cma_candidate_for_jurisdiction(db, "DE", "2026-07-30")
        db.commit()

        assert cma.equity_home_return_bps is None
        # Bonds-Seite ist Pflicht und daher weiterhin gesetzt -> status bleibt data_derived.
        assert cma.bonds_home_ig_return_bps is not None
        assert cma.status == "data_derived"

        detail = json.loads(cma.source_detail)
        assert "skipped_reason" in detail["equity_kgv_mean_reversion"]


def test_compute_candidate_propagates_insufficient_yield_curve_error(session_factory, monkeypatch):
    series_codes = [c for _, c in dp._YIELD_CURVE_REGISTRY["DE"][1]]
    provider = _FakeProvider({series_codes[0]: _points(2.0)})  # nur 1 Punkt, unter dem Minimum
    monkeypatch.setattr(dp, "_build_ecb_provider", lambda: provider)

    with session_factory() as db:
        with pytest.raises(dp.InsufficientYieldCurveDataError):
            dp.compute_cma_candidate_for_jurisdiction(db, "DE", "2026-07-30")
        # Keine Zeile darf bei einem Fehler vor der Zinskurven-Pflicht persistiert werden.
        assert db.query(CapitalMarketAssumption).filter(
            CapitalMarketAssumption.jurisdiction == "DE"
        ).count() == 0


def test_compute_candidate_propagates_unknown_jurisdiction_error(session_factory):
    with session_factory() as db:
        with pytest.raises(dp.NoYieldCurveSourceConfiguredError):
            dp.compute_cma_candidate_for_jurisdiction(db, "XX", "2026-07-30")


def test_compute_candidate_never_touches_ch_rows(session_factory, monkeypatch):
    """Harter Constraint: dieses Modul erzeugt ausschliesslich Nicht-CH-Kandidaten
    und darf niemals eine bestehende CH-Zeile lesen/veraendern."""
    _patch_full_de_curve(monkeypatch)
    monkeypatch.setattr(dp, "_fetch_pe_ticker_info", lambda ticker: {"trailingPE": 20.0})

    now = "2026-07-30T00:00:00.000Z"
    with session_factory() as db:
        ch_row = CapitalMarketAssumption(
            id="cma-ch-existing", assumption_set_name="CH-Standard", version=1,
            valid_from="2026-01-01", is_current=1, status="committee_approved",
            created_by="ic", created_at=now, updated_at=now,
        )
        db.add(ch_row)
        db.commit()

        dp.compute_cma_candidate_for_jurisdiction(db, "DE", "2026-07-30")
        db.commit()

        reloaded_ch = db.query(CapitalMarketAssumption).filter(
            CapitalMarketAssumption.id == "cma-ch-existing"
        ).first()
        assert reloaded_ch.is_current == 1
        assert reloaded_ch.status == "committee_approved"
        assert reloaded_ch.jurisdiction is None
