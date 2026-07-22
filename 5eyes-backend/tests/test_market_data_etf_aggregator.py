"""Tests: ETFAggregator (Fallback-Kette fuer justetf/swissfunddata) +
Provider-Health-Sichtbarkeit (collect_etf_provider_health).

Vorher gab es KEINE Fallback-Kette fuer ETF-Master-Daten: fiel der
primaere Scraper aus, gab es kein Ergebnis (stiller Ausfall). Diese Tests
verifizieren:
(a) faellt der Primaer-ETF-Provider aus, liefert der Fallback ein Ergebnis
    UND der Fehler landet im HealthState (in-memory + persistente
    provider_health_registry, sofern konfiguriert).
(b) die Health-Snapshot-Funktion (collect_etf_provider_health) liefert
    ein korrektes, serialisierbares Dict pro Provider.

Reine Unit-Tests mit Fake-Providern + einer echten SQLite-gestuetzten
ProviderHealthRegistry (kein Netzwerk). Ein Integrationstest am Ende
nutzt die echten Scraper-Klassen mit gemockten Sessions.
"""
from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.market_data.admin import collect_etf_provider_health  # noqa: E402
from services.market_data.etf.aggregator import ETFAggregator  # noqa: E402
from services.market_data.etf.base import ETFInfo, ETFProvider  # noqa: E402
from services.market_data.etf.factory import build_default_etf_aggregator  # noqa: E402
from services.market_data.etf.providers import (  # noqa: E402
    JustetfScraper,
    SwissfunddataScraper,
)
from services.market_data.exceptions import (  # noqa: E402
    MarketDataError,
    ProviderError,
    RateLimitError,
    SymbolNotFound,
)
from services.market_data.provider_health_registry import (  # noqa: E402
    ProviderHealthRegistry,
    ensure_provider_health_table,
    latest_provider_health_by_name,
)


# ============================================================================
# Fake-Provider Helper
# ============================================================================


class _FakeETFProvider(ETFProvider):
    """Konfigurierbarer Fake-ETFProvider fuer Aggregator-Tests."""

    def __init__(self, name: str, result: ETFInfo | None = None, exc: BaseException | None = None):
        self.name = name
        self._result = result
        self._exc = exc
        self.calls = 0

    def lookup_isin(self, isin: str) -> ETFInfo:
        self.calls += 1
        if self._exc is not None:
            raise self._exc
        if self._result is not None:
            return self._result
        raise SymbolNotFound(isin)


def _etf_info(source: str, isin: str = "IE00TEST0001") -> ETFInfo:
    return ETFInfo(isin=isin, ticker=None, name=f"{source}-fund", ter_bps=20, source=source)


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'etf_provider_health.db'}")
    factory = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    ensure_provider_health_table(engine)
    try:
        yield factory
    finally:
        engine.dispose()


# ============================================================================
# ETFAggregator: Fallback-Verhalten (in-memory HealthState)
# ============================================================================


def test_etf_aggregator_falls_back_to_next_provider_on_provider_error():
    primary = _FakeETFProvider("justetf", exc=ProviderError("justetf down"))
    fallback = _FakeETFProvider("swissfunddata", result=_etf_info("swissfunddata"))
    agg = ETFAggregator(providers=[primary, fallback])

    info = agg.lookup_isin("IE00TEST0001")

    assert info.source == "swissfunddata"
    assert primary.calls == 1
    assert fallback.calls == 1
    assert agg.health.is_healthy("justetf") is False
    assert agg.health.is_healthy("swissfunddata") is True


def test_etf_aggregator_falls_back_on_rate_limit():
    primary = _FakeETFProvider("justetf", exc=RateLimitError("429"))
    fallback = _FakeETFProvider("swissfunddata", result=_etf_info("swissfunddata"))
    agg = ETFAggregator(providers=[primary, fallback])

    info = agg.lookup_isin("IE00TEST0001")

    assert info.source == "swissfunddata"
    assert agg.health.is_healthy("justetf") is False


def test_etf_aggregator_symbol_not_found_falls_through_and_stays_healthy():
    primary = _FakeETFProvider("justetf", exc=SymbolNotFound("unknown isin"))
    fallback = _FakeETFProvider("swissfunddata", result=_etf_info("swissfunddata"))
    agg = ETFAggregator(providers=[primary, fallback])

    info = agg.lookup_isin("IE00TEST0001")

    assert info.source == "swissfunddata"
    # SymbolNotFound ist kein Backoff-Trigger -- Provider bleibt healthy.
    assert agg.health.is_healthy("justetf") is True


def test_etf_aggregator_raises_last_exception_when_all_providers_fail():
    primary = _FakeETFProvider("justetf", exc=ProviderError("justetf down"))
    fallback = _FakeETFProvider("swissfunddata", exc=ProviderError("swissfunddata down"))
    agg = ETFAggregator(providers=[primary, fallback])

    with pytest.raises(ProviderError, match="swissfunddata down"):
        agg.lookup_isin("IE00TEST0001")

    assert agg.health.is_healthy("justetf") is False
    assert agg.health.is_healthy("swissfunddata") is False


def test_etf_aggregator_no_healthy_candidates_raises_market_data_error():
    primary = _FakeETFProvider("justetf", result=_etf_info("justetf"))
    agg = ETFAggregator(providers=[primary], unhealthy_ttl_seconds=60)
    agg.health.mark_unhealthy("justetf")

    with pytest.raises(MarketDataError):
        agg.lookup_isin("IE00TEST0001")
    assert primary.calls == 0  # gar nicht erst aufgerufen


def test_etf_aggregator_empty_provider_list_raises_market_data_error():
    agg = ETFAggregator(providers=[])
    with pytest.raises(MarketDataError):
        agg.lookup_isin("IE00TEST0001")


# ============================================================================
# ETFAggregator: persistente provider_health_registry
# ============================================================================


def test_etf_aggregator_records_unhealthy_in_registry_and_uses_fallback(session_factory):
    registry = ProviderHealthRegistry(session_factory=session_factory, ttl_seconds=60)
    primary = _FakeETFProvider("justetf", exc=ProviderError("justetf HTTP 500"))
    fallback = _FakeETFProvider("swissfunddata", result=_etf_info("swissfunddata"))
    agg = ETFAggregator(
        providers=[primary, fallback], unhealthy_ttl_seconds=60, health_registry=registry,
    )

    info = agg.lookup_isin("IE00TEST0001")

    assert info.source == "swissfunddata"
    with session_factory() as db:
        latest = latest_provider_health_by_name(db)
    assert latest["justetf"]["status"] == "unhealthy"
    assert "HTTP 500" in latest["justetf"]["reason"]
    assert "swissfunddata" not in latest or latest.get("swissfunddata", {}).get("status") != "unhealthy"


def test_etf_aggregator_marks_provider_recovered_after_success(session_factory):
    registry = ProviderHealthRegistry(session_factory=session_factory, ttl_seconds=60)
    primary = _FakeETFProvider("justetf", exc=ProviderError("down"))
    agg = ETFAggregator(
        providers=[primary], unhealthy_ttl_seconds=60, health_registry=registry,
    )
    with pytest.raises(ProviderError):
        agg.lookup_isin("IE00TEST0001")

    primary._exc = None
    primary._result = _etf_info("justetf")
    agg.health.reset("justetf")
    agg.lookup_isin("IE00TEST0001")

    with session_factory() as db:
        latest = latest_provider_health_by_name(db)
    assert latest["justetf"]["status"] == "recovered"
    assert latest["justetf"]["recovered_at"]


def test_etf_aggregator_registry_write_failure_does_not_break_lookup():
    class BrokenRegistry:
        def mark_unhealthy(self, *args, **kwargs):
            raise RuntimeError("db down")

        def mark_healthy(self, *args, **kwargs):
            raise RuntimeError("db down")

    primary = _FakeETFProvider("justetf", exc=ProviderError("down"))
    fallback = _FakeETFProvider("swissfunddata", result=_etf_info("swissfunddata"))
    agg = ETFAggregator(providers=[primary, fallback], health_registry=BrokenRegistry())

    info = agg.lookup_isin("IE00TEST0001")

    assert info.source == "swissfunddata"


# ============================================================================
# Integration: echte Scraper-Klassen, gemockte HTTP-Sessions
# ============================================================================


def _mock_response(text: str, status: int = 200):
    resp = MagicMock()
    resp.status_code = status
    resp.text = text
    return resp


def _mock_session(text: str, status: int = 200):
    session = MagicMock()
    session.get.return_value = _mock_response(text, status)
    return session


_SFD_HTML = """
<html>
<body>
<h1>UBS ETF Switzerland</h1>
<dl>
  <dt>TER</dt><dd>0.20%</dd>
  <dt>Domizil</dt><dd>CH</dd>
</dl>
</body>
</html>
"""


def test_real_scrapers_justetf_network_failure_falls_back_to_swissfunddata(session_factory):
    """(a) End-to-End: primaerer Scraper (justetf) faellt aus (Netzwerkfehler),
    swissfunddata liefert -- und der Fehler landet in der Registry."""
    import requests

    broken_session = MagicMock()
    broken_session.get.side_effect = requests.RequestException("connection reset")
    justetf = JustetfScraper(enabled=True, rate_delay_seconds=0, session=broken_session, sleeper=lambda _s: None)

    ok_session = _mock_session(_SFD_HTML)
    swissfunddata = SwissfunddataScraper(
        enabled=True, rate_delay_seconds=0, session=ok_session, sleeper=lambda _s: None,
    )

    registry = ProviderHealthRegistry(session_factory=session_factory, ttl_seconds=60)
    agg = ETFAggregator(providers=[justetf, swissfunddata], health_registry=registry)

    info = agg.lookup_isin("CH0123456789")

    assert info.source == "swissfunddata"
    assert agg.health.is_healthy("justetf") is False
    with session_factory() as db:
        latest = latest_provider_health_by_name(db)
    assert latest["justetf"]["status"] == "unhealthy"
    assert "connection reset" in latest["justetf"]["reason"]


# ============================================================================
# Factory: build_default_etf_aggregator
# ============================================================================


def test_factory_default_order_includes_both_scrapers():
    fake_settings = SimpleNamespace()
    agg = build_default_etf_aggregator(settings=fake_settings)
    names = [p.name for p in agg.providers]
    assert names == ["justetf", "swissfunddata"]


def test_factory_respects_explicit_provider_order():
    fake_settings = SimpleNamespace(market_data_etf_providers="swissfunddata,justetf")
    agg = build_default_etf_aggregator(settings=fake_settings)
    names = [p.name for p in agg.providers]
    assert names == ["swissfunddata", "justetf"]


def test_factory_skips_unknown_etf_provider_name():
    fake_settings = SimpleNamespace(market_data_etf_providers="justetf,doesnotexist,swissfunddata")
    agg = build_default_etf_aggregator(settings=fake_settings)
    names = [p.name for p in agg.providers]
    assert names == ["justetf", "swissfunddata"]


def test_factory_falls_back_when_no_etf_providers_configured():
    fake_settings = SimpleNamespace(market_data_etf_providers="")
    agg = build_default_etf_aggregator(settings=fake_settings)
    names = [p.name for p in agg.providers]
    assert names == ["justetf", "swissfunddata"]


def test_factory_propagates_scrape_etf_data_enabled_flag():
    fake_settings = SimpleNamespace(scrape_etf_data=True, etf_scraper_rate_delay_seconds=0)
    agg = build_default_etf_aggregator(settings=fake_settings)
    assert all(getattr(p, "enabled", False) is True for p in agg.providers)


def test_factory_defaults_scrape_etf_data_disabled():
    fake_settings = SimpleNamespace()
    agg = build_default_etf_aggregator(settings=fake_settings)
    assert all(getattr(p, "enabled", True) is False for p in agg.providers)


# ============================================================================
# Provider-Health-Sichtbarkeit: collect_etf_provider_health
# ============================================================================


def test_collect_etf_provider_health_without_db_returns_serializable_list():
    cards = collect_etf_provider_health(db=None)

    assert isinstance(cards, list)
    assert len(cards) >= 1
    for card in cards:
        assert isinstance(card, dict)
        assert set(card.keys()) >= {
            "name", "enabled", "healthy", "registry_status",
            "reason", "observed_at", "unhealthy_until",
            "recovered_at", "consecutive_errors",
        }
        # serialisierbar: nur primitve Typen (str/bool/int/None) im Snapshot
        for value in card.values():
            assert value is None or isinstance(value, (str, bool, int))


def test_collect_etf_provider_health_reflects_registry_events(session_factory):
    ProviderHealthRegistry(session_factory=session_factory).mark_unhealthy(
        "justetf",
        reason="justetf HTTP 500",
        operation="lookup_isin(IE00TEST0001)",
        error_type="ProviderError",
    )

    with session_factory() as db:
        cards = collect_etf_provider_health(db)

    justetf_card = next(card for card in cards if card["name"] == "justetf")
    assert justetf_card["registry_status"] == "unhealthy"
    assert justetf_card["healthy"] is False
    assert justetf_card["reason"] == "justetf HTTP 500"
    assert justetf_card["consecutive_errors"] == 0
