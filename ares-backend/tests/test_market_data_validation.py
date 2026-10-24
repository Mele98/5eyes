"""Phase 7 Tests: Cross-Validation + Log-Persistenz.

Fake-Provider mit konfigurierbaren Closes. Persistenz testen via SQLite
(tmp_path).
"""
from __future__ import annotations

import json
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import configure_mappers, sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base
from models.market_data_validation_log import MarketDataValidationLog  # noqa: F401
from models import (  # noqa: F401
    allocation, clients, mandates, profiling, review, users, wealth,
)
configure_mappers()

from services.market_data import (
    Bar,
    DEFAULT_THRESHOLD_BPS,
    MarketDataProvider,
    ProviderError,
    SymbolNotFound,
    ValidationResult,
    validate_batch,
    validate_symbol,
)
from services.market_data.validation import _median


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'val.db'}",
        connect_args={"check_same_thread": False},
    )
    SF = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield SF
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


class _FixedProvider(MarketDataProvider):
    """Provider mit fixem close oder fixer Exception pro Symbol."""

    def __init__(self, name: str, close: Decimal | None = None, exc: Exception | None = None):
        self.name = name
        self._close = close
        self._exc = exc

    def get_eod(self, symbol, on_date):
        if self._exc:
            raise self._exc
        if self._close is None:
            raise SymbolNotFound(symbol)
        return Bar(
            symbol=symbol, date=on_date,
            open=self._close, high=self._close,
            low=self._close, close=self._close,
            currency="USD", source=self.name,
        )

    def get_history(self, symbol, start, end):
        return []

    def lookup_isin(self, isin):
        raise SymbolNotFound(isin)


# ============================================================================
# _median Helper
# ============================================================================


def test_median_odd_count():
    assert _median([Decimal("1"), Decimal("2"), Decimal("3")]) == Decimal("2")


def test_median_even_count():
    assert _median([Decimal("1"), Decimal("2"), Decimal("3"), Decimal("4")]) == Decimal("2.5")


def test_median_unsorted():
    assert _median([Decimal("3"), Decimal("1"), Decimal("2")]) == Decimal("2")


# ============================================================================
# validate_symbol — happy path
# ============================================================================


def test_two_providers_equal_no_alert():
    p1 = _FixedProvider("p1", close=Decimal("100.00"))
    p2 = _FixedProvider("p2", close=Decimal("100.00"))
    result = validate_symbol("X", date(2026, 5, 8), [p1, p2])
    assert isinstance(result, ValidationResult)
    assert result.status == "ok"
    assert result.is_alert is False
    assert result.diff_bps == 0
    assert result.median_close == Decimal("100.00")
    assert result.n_providers == 2


def test_two_providers_small_diff_under_threshold():
    """100.00 vs 100.50 = 0.5% = 50bps, default Threshold 300bps -> ok."""
    p1 = _FixedProvider("p1", close=Decimal("100.00"))
    p2 = _FixedProvider("p2", close=Decimal("100.50"))
    result = validate_symbol("X", date(2026, 5, 8), [p1, p2])
    assert result.status == "ok"
    assert result.is_alert is False
    assert 49 <= result.diff_bps <= 51  # gerundet


def test_two_providers_large_diff_alert():
    """100 vs 110 = 10% = 1000bps -> Alert."""
    p1 = _FixedProvider("p1", close=Decimal("100.00"))
    p2 = _FixedProvider("p2", close=Decimal("110.00"))
    result = validate_symbol("X", date(2026, 5, 8), [p1, p2])
    assert result.status == "alert"
    assert result.is_alert is True
    assert result.diff_bps > DEFAULT_THRESHOLD_BPS


def test_three_providers_median_used():
    """Outlier: 100/100/200 -> Median 100, Min 100, Max 200, Diff 1.0 -> 10000bps."""
    p1 = _FixedProvider("p1", close=Decimal("100.00"))
    p2 = _FixedProvider("p2", close=Decimal("100.00"))
    p3 = _FixedProvider("p3", close=Decimal("200.00"))
    result = validate_symbol("X", date(2026, 5, 8), [p1, p2, p3])
    assert result.median_close == Decimal("100.00")
    assert result.min_close == Decimal("100.00")
    assert result.max_close == Decimal("200.00")
    assert result.is_alert is True
    assert result.n_providers == 3


def test_custom_threshold_overrides_alert_decision():
    """Diff=1000bps; Threshold=2000bps -> ok."""
    p1 = _FixedProvider("p1", close=Decimal("100"))
    p2 = _FixedProvider("p2", close=Decimal("110"))
    result = validate_symbol("X", date(2026, 5, 8), [p1, p2], threshold_bps=2000)
    assert result.status == "ok"
    assert result.is_alert is False


# ============================================================================
# Provider-Failure-Handling
# ============================================================================


def test_failed_provider_is_skipped():
    """Wenn p1 wirft, wird p2 trotzdem gewertet — und n_providers=1 -> insufficient."""
    p1 = _FixedProvider("p1", exc=ProviderError("down"))
    p2 = _FixedProvider("p2", close=Decimal("100"))
    result = validate_symbol("X", date(2026, 5, 8), [p1, p2])
    assert result.status == "insufficient_data"
    assert result.n_providers == 1


def test_two_failures_yield_insufficient():
    p1 = _FixedProvider("p1", exc=ProviderError("a"))
    p2 = _FixedProvider("p2", exc=SymbolNotFound("b"))
    result = validate_symbol("X", date(2026, 5, 8), [p1, p2])
    assert result.status == "insufficient_data"
    assert result.n_providers == 0


def test_no_providers_returns_insufficient():
    result = validate_symbol("X", date(2026, 5, 8), [])
    assert result.status == "insufficient_data"
    assert result.diff_bps == 0


def test_three_providers_one_fails_two_ok():
    p1 = _FixedProvider("p1", close=Decimal("100"))
    p2 = _FixedProvider("p2", exc=ProviderError("down"))
    p3 = _FixedProvider("p3", close=Decimal("100"))
    result = validate_symbol("X", date(2026, 5, 8), [p1, p2, p3])
    assert result.status == "ok"
    assert result.n_providers == 2


# ============================================================================
# Persistenz
# ============================================================================


def test_log_persisted_for_alert(session_factory):
    p1 = _FixedProvider("p1", close=Decimal("100"))
    p2 = _FixedProvider("p2", close=Decimal("110"))
    with session_factory() as s:
        result = validate_symbol("X", date(2026, 5, 8), [p1, p2], db=s)
        assert result.is_alert is True
        s.commit()
        rows = s.query(MarketDataValidationLog).all()
        assert len(rows) == 1
        row = rows[0]
        assert row.symbol == "X"
        assert row.is_alert == 1
        assert row.n_providers == 2
        assert row.diff_bps > DEFAULT_THRESHOLD_BPS
        providers = json.loads(row.providers_json)
        assert {p["name"] for p in providers} == {"p1", "p2"}


def test_log_persisted_for_ok_too(session_factory):
    """Auch bei status='ok' wird ein Log-Eintrag geschrieben (Audit-Trail)."""
    p1 = _FixedProvider("p1", close=Decimal("100"))
    p2 = _FixedProvider("p2", close=Decimal("100"))
    with session_factory() as s:
        validate_symbol("X", date(2026, 5, 8), [p1, p2], db=s)
        s.commit()
        rows = s.query(MarketDataValidationLog).all()
        assert len(rows) == 1
        assert rows[0].is_alert == 0


def test_log_not_persisted_for_insufficient(session_factory):
    """Bei insufficient_data wird KEIN Log-Eintrag geschrieben."""
    p1 = _FixedProvider("p1", close=Decimal("100"))
    with session_factory() as s:
        validate_symbol("X", date(2026, 5, 8), [p1], db=s)
        s.commit()
        rows = s.query(MarketDataValidationLog).all()
        assert rows == []


# ============================================================================
# validate_batch
# ============================================================================


def test_validate_batch_runs_all_symbols(session_factory):
    p1 = _FixedProvider("p1", close=Decimal("100"))
    p2 = _FixedProvider("p2", close=Decimal("100"))
    with session_factory() as s:
        results = validate_batch(["A", "B", "C"], date(2026, 5, 8), [p1, p2], db=s)
        s.commit()
    assert len(results) == 3
    assert all(r.status == "ok" for r in results)
