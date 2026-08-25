"""Phase 11 Tests: Justetf + Swissfunddata Scraper.

Mock-Sessions, kein Netzwerk. Sleep ist gemockt damit Tests schnell sind.
"""
from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import requests

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.market_data import (
    ETFInfo,
    ETFProvider,
    JustetfScraper,
    ProviderError,
    RateLimitError,
    SwissfunddataScraper,
    SymbolNotFound,
)


def _mock_response(text: str, status: int = 200):
    resp = MagicMock()
    resp.status_code = status
    resp.text = text
    return resp


def _mock_session(text: str, status: int = 200):
    session = MagicMock()
    session.get.return_value = _mock_response(text, status)
    return session


_JUSTETF_HTML = """
<html>
<head><title>iShares Core MSCI World UCITS ETF</title></head>
<body>
<h1>iShares Core MSCI World UCITS ETF</h1>
<div>
  <div class="vallabel">Total expense ratio</div>
  <span class="val">0.20% p.a.</span>
</div>
<div>
  <div class="vallabel">Fund size</div>
  <span class="val">75300000000 EUR</span>
</div>
<div>
  <div class="vallabel">Replication method</div>
  <span class="val">Physical (Sampling)</span>
</div>
<div>
  <div class="vallabel">Distribution policy</div>
  <span class="val">Accumulating</span>
</div>
<div>
  <div class="vallabel">Fund domicile</div>
  <span class="val">IE</span>
</div>
<div>
  <div class="vallabel">Fund currency</div>
  <span class="val">USD</span>
</div>
</body>
</html>
"""

_SFD_HTML = """
<html>
<body>
<h1>UBS ETF Switzerland</h1>
<dl>
  <dt>TER</dt><dd>0.20%</dd>
  <dt>Domizil</dt><dd>CH</dd>
  <dt>Fondswaehrung</dt><dd>CHF</dd>
  <dt>Anlageklasse</dt><dd>Aktien</dd>
  <dt>Replikation</dt><dd>Physical</dd>
</dl>
</body>
</html>
"""


# ============================================================================
# ETFInfo / ETFProvider Interface
# ============================================================================


def test_etf_info_is_frozen():
    info = ETFInfo(isin="IE00B4L5Y983", ticker=None, name="iShares")
    with pytest.raises(Exception):
        info.name = "Other"  # type: ignore[misc]


def test_justetf_and_sfd_implement_etf_provider():
    assert isinstance(JustetfScraper(), ETFProvider)
    assert isinstance(SwissfunddataScraper(), ETFProvider)


# ============================================================================
# Opt-In Verhalten
# ============================================================================


def test_justetf_disabled_by_default():
    provider = JustetfScraper()
    assert provider.enabled is False
    assert provider.is_healthy() is False


def test_swissfunddata_disabled_by_default():
    provider = SwissfunddataScraper()
    assert provider.enabled is False
    assert provider.is_healthy() is False


def test_justetf_disabled_raises_provider_error_on_lookup():
    provider = JustetfScraper(enabled=False)
    with pytest.raises(ProviderError):
        provider.lookup_isin("IE00B4L5Y983")


def test_swissfunddata_disabled_raises_provider_error_on_lookup():
    provider = SwissfunddataScraper(enabled=False)
    with pytest.raises(ProviderError):
        provider.lookup_isin("CH0123456789")


# ============================================================================
# JustetfScraper
# ============================================================================


def test_justetf_parses_profile():
    session = _mock_session(_JUSTETF_HTML)
    provider = JustetfScraper(
        enabled=True, rate_delay_seconds=0,
        session=session, sleeper=lambda _s: None,
    )
    info = provider.lookup_isin("IE00B4L5Y983")
    assert isinstance(info, ETFInfo)
    assert info.isin == "IE00B4L5Y983"
    assert info.name and "iShares" in info.name
    assert info.ter_bps == 20  # 0.20% = 20 bps
    assert info.aum_chf == Decimal("75300000000")
    assert info.replication == "physical"
    assert info.distribution == "accumulating"
    assert info.domicile == "IE"
    assert info.fund_currency == "USD"
    assert info.source == "justetf"


def test_justetf_empty_isin_raises_symbol_not_found():
    provider = JustetfScraper(enabled=True)
    with pytest.raises(SymbolNotFound):
        provider.lookup_isin("")


def test_justetf_404_raises_symbol_not_found():
    session = _mock_session("Not Found", status=404)
    provider = JustetfScraper(
        enabled=True, rate_delay_seconds=0,
        session=session, sleeper=lambda _s: None,
    )
    with pytest.raises(SymbolNotFound):
        provider.lookup_isin("XX0000000000")


def test_justetf_429_raises_rate_limit():
    session = _mock_session("", status=429)
    provider = JustetfScraper(
        enabled=True, rate_delay_seconds=0,
        session=session, sleeper=lambda _s: None,
    )
    with pytest.raises(RateLimitError):
        provider.lookup_isin("IE00B4L5Y983")


def test_justetf_500_raises_provider_error():
    session = _mock_session("", status=500)
    provider = JustetfScraper(
        enabled=True, rate_delay_seconds=0,
        session=session, sleeper=lambda _s: None,
    )
    with pytest.raises(ProviderError):
        provider.lookup_isin("IE00B4L5Y983")


def test_justetf_network_exception_raises_provider_error():
    session = MagicMock()
    session.get.side_effect = requests.RequestException("timeout")
    provider = JustetfScraper(
        enabled=True, rate_delay_seconds=0,
        session=session, sleeper=lambda _s: None,
    )
    with pytest.raises(ProviderError):
        provider.lookup_isin("IE00B4L5Y983")


def test_justetf_html_without_title_raises_symbol_not_found():
    session = _mock_session("<html><body></body></html>")
    provider = JustetfScraper(
        enabled=True, rate_delay_seconds=0,
        session=session, sleeper=lambda _s: None,
    )
    with pytest.raises(SymbolNotFound):
        provider.lookup_isin("XX0000000000")


def test_justetf_rate_limit_sleep_called():
    """Zweiter Request triggert Sleep wegen rate_delay > 0."""
    sleeps: list[float] = []

    def _sleeper(s: float) -> None:
        sleeps.append(s)

    session = _mock_session(_JUSTETF_HTML)
    provider = JustetfScraper(
        enabled=True, rate_delay_seconds=5,
        session=session, sleeper=_sleeper,
    )
    provider.lookup_isin("A")
    provider.lookup_isin("B")
    # Zweiter Call sollte (knapp) gesleepd haben — Wert nahe 5s
    assert len(sleeps) >= 1
    assert all(0 <= s <= 5 for s in sleeps)


# ============================================================================
# SwissfunddataScraper
# ============================================================================


def test_swissfunddata_parses_profile():
    session = _mock_session(_SFD_HTML)
    provider = SwissfunddataScraper(
        enabled=True, rate_delay_seconds=0,
        session=session, sleeper=lambda _s: None,
    )
    info = provider.lookup_isin("CH0123456789")
    assert info.isin == "CH0123456789"
    assert info.name and "UBS" in info.name
    assert info.ter_bps == 20
    assert info.domicile == "CH"
    assert info.fund_currency == "CHF"
    assert info.asset_class == "Aktien"
    assert info.source == "swissfunddata"


def test_swissfunddata_404_raises_symbol_not_found():
    session = _mock_session("Not Found", status=404)
    provider = SwissfunddataScraper(
        enabled=True, rate_delay_seconds=0,
        session=session, sleeper=lambda _s: None,
    )
    with pytest.raises(SymbolNotFound):
        provider.lookup_isin("XX0000000000")
