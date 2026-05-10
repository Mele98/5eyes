"""Phase 9 Tests: FRED + ECB + SNB Macro-Provider.

Mock-Session, kein Netzwerk.
"""
from __future__ import annotations

import sys
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import requests

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.market_data import (
    ECBMacroProvider,
    FREDMacroProvider,
    MacroPoint,
    MacroProvider,
    ProviderError,
    RateLimitError,
    SNBMacroProvider,
)


def _mock_response(payload, status: int = 200):
    resp = MagicMock()
    resp.status_code = status
    resp.json = lambda: payload
    return resp


def _mock_session(payload, status: int = 200):
    session = MagicMock()
    session.get.return_value = _mock_response(payload, status)
    return session


# ============================================================================
# MacroPoint Dataclass
# ============================================================================


def test_macro_point_is_frozen():
    p = MacroPoint(date=date(2026, 1, 1), value=Decimal("100"), series_code="X")
    with pytest.raises(Exception):
        p.value = Decimal("200")  # type: ignore[misc]


# ============================================================================
# FREDMacroProvider
# ============================================================================


_FRED_OK = {
    "observations": [
        {"date": "2026-01-01", "value": "315.605"},
        {"date": "2026-02-01", "value": "316.124"},
        {"date": "2026-03-01", "value": "."},  # FRED-Missing
        {"date": "2026-04-01", "value": "317.500"},
    ]
}


def test_fred_requires_api_key():
    provider = FREDMacroProvider(api_key=None)
    with pytest.raises(ProviderError):
        provider.get_series("CPIAUCSL", date(2026, 1, 1), date(2026, 4, 30))


def test_fred_returns_series():
    session = _mock_session(_FRED_OK)
    provider = FREDMacroProvider(api_key="K", session=session)
    points = provider.get_series("CPIAUCSL", date(2026, 1, 1), date(2026, 4, 30))
    assert len(points) == 3  # "." skipped
    assert all(isinstance(p, MacroPoint) for p in points)
    assert [p.date for p in points] == [date(2026, 1, 1), date(2026, 2, 1), date(2026, 4, 1)]
    assert points[0].value == Decimal("315.605")
    assert points[0].source == "fred"


def test_fred_empty_when_end_before_start():
    provider = FREDMacroProvider(api_key="K", session=_mock_session(_FRED_OK))
    assert provider.get_series("X", date(2026, 4, 1), date(2026, 1, 1)) == []


def test_fred_429_raises_rate_limit():
    session = _mock_session({}, status=429)
    provider = FREDMacroProvider(api_key="K", session=session)
    with pytest.raises(RateLimitError):
        provider.get_series("X", date(2026, 1, 1), date(2026, 4, 30))


def test_fred_500_raises_provider_error():
    session = _mock_session({}, status=500)
    provider = FREDMacroProvider(api_key="K", session=session)
    with pytest.raises(ProviderError):
        provider.get_series("X", date(2026, 1, 1), date(2026, 4, 30))


def test_fred_is_healthy_false_without_key():
    assert FREDMacroProvider().is_healthy() is False
    assert FREDMacroProvider(api_key="K").is_healthy() is True


# ============================================================================
# ECBMacroProvider
# ============================================================================


_ECB_OK = {
    "dataSets": [
        {
            "series": {
                "0:0:0:0:0:0": {
                    "observations": {
                        "0": [1.0850],
                        "1": [1.0875],
                        "2": [1.0900],
                    }
                }
            }
        }
    ],
    "structure": {
        "dimensions": {
            "observation": [
                {
                    "values": [
                        {"id": "2026-01-01"},
                        {"id": "2026-01-02"},
                        {"id": "2026-01-03"},
                    ]
                }
            ]
        }
    },
}


def test_ecb_returns_series():
    session = _mock_session(_ECB_OK)
    provider = ECBMacroProvider(session=session)
    points = provider.get_series("EXR.D.USD.EUR.SP00.A", date(2026, 1, 1), date(2026, 1, 3))
    assert len(points) == 3
    assert points[0].date == date(2026, 1, 1)
    assert points[0].value == Decimal("1.085")
    assert points[0].source == "ecb"


def test_ecb_invalid_series_code_raises():
    provider = ECBMacroProvider(session=MagicMock())
    with pytest.raises(ProviderError):
        provider.get_series("NO_DOT_HERE", date(2026, 1, 1), date(2026, 1, 31))


def test_ecb_empty_response():
    session = _mock_session({})
    provider = ECBMacroProvider(session=session)
    assert provider.get_series("X.Y", date(2026, 1, 1), date(2026, 1, 31)) == []


def test_ecb_404_returns_empty():
    session = _mock_session({}, status=404)
    provider = ECBMacroProvider(session=session)
    assert provider.get_series("X.Y", date(2026, 1, 1), date(2026, 1, 31)) == []


def test_ecb_network_exception():
    session = MagicMock()
    session.get.side_effect = requests.RequestException("timeout")
    provider = ECBMacroProvider(session=session)
    with pytest.raises(ProviderError):
        provider.get_series("X.Y", date(2026, 1, 1), date(2026, 1, 31))


def test_ecb_handles_yearly_dates():
    """ECB liefert manchmal Format 'YYYY' fuer annual series."""
    payload = {
        "dataSets": [{"series": {"0:0": {"observations": {"0": [2.5], "1": [2.7]}}}}],
        "structure": {
            "dimensions": {
                "observation": [{"values": [{"id": "2024"}, {"id": "2025"}]}]
            }
        },
    }
    session = _mock_session(payload)
    provider = ECBMacroProvider(session=session)
    points = provider.get_series("FOO.BAR", date(2024, 1, 1), date(2025, 12, 31))
    assert len(points) == 2
    assert points[0].date == date(2024, 1, 1)
    assert points[1].date == date(2025, 1, 1)


# ============================================================================
# SNBMacroProvider
# ============================================================================


_SNB_OK = {
    "timeseries": [
        {
            "values": [
                {"date": "2026-01", "value": "1.5"},
                {"date": "2026-02", "value": "1.6"},
                {"date": "2026-03", "value": "1.7"},
            ]
        }
    ]
}


def test_snb_returns_series():
    session = _mock_session(_SNB_OK)
    provider = SNBMacroProvider(session=session)
    points = provider.get_series("plkopr", date(2026, 1, 1), date(2026, 3, 31))
    assert len(points) == 3
    assert points[0].date == date(2026, 1, 1)
    assert points[0].value == Decimal("1.5")
    assert points[0].source == "snb"


def test_snb_filters_by_range():
    """Punkte ausserhalb [start, end] werden weggefiltert."""
    session = _mock_session(_SNB_OK)
    provider = SNBMacroProvider(session=session)
    points = provider.get_series("plkopr", date(2026, 2, 1), date(2026, 2, 28))
    assert len(points) == 1
    assert points[0].date == date(2026, 2, 1)


def test_snb_empty_cube_id_raises():
    provider = SNBMacroProvider(session=MagicMock())
    with pytest.raises(ProviderError):
        provider.get_series("", date(2026, 1, 1), date(2026, 12, 31))


def test_snb_skips_dot_missing_value():
    payload = {
        "timeseries": [
            {
                "values": [
                    {"date": "2026-01", "value": "."},  # missing
                    {"date": "2026-02", "value": "1.6"},
                ]
            }
        ]
    }
    session = _mock_session(payload)
    provider = SNBMacroProvider(session=session)
    points = provider.get_series("X", date(2026, 1, 1), date(2026, 2, 28))
    assert len(points) == 1


def test_snb_404_returns_empty():
    session = _mock_session({}, status=404)
    provider = SNBMacroProvider(session=session)
    assert provider.get_series("X", date(2026, 1, 1), date(2026, 12, 31)) == []


def test_macro_providers_share_base_interface():
    """Alle 3 erben von MacroProvider und haben .name + .get_series + .is_healthy."""
    fred = FREDMacroProvider(api_key="K")
    ecb = ECBMacroProvider()
    snb = SNBMacroProvider()
    for p in (fred, ecb, snb):
        assert isinstance(p, MacroProvider)
        assert isinstance(p.name, str) and p.name
        assert callable(p.get_series)
        assert isinstance(p.is_healthy(), bool)
