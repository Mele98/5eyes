"""P22 Tests: Webhook-Notifier fuer Validation-Alerts.

Mock-HTTP, kein Netzwerk. Verifiziert:
- build_alert_payload formatiert ValidationResult-Liste korrekt
- post_alert posted JSON mit Content-Type-Header
- post_alert swallowed HTTPError, URLError, Timeout
- notify_validation_alerts skippt bei 0 Alerts oder leerer URL
- weekly_validation_job ruft Webhook nur wenn URL gesetzt und Alerts > 0
"""
from __future__ import annotations

import json
import sys
from datetime import date as Date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.market_data import notifier
from services.market_data.notifier import (
    build_alert_payload,
    notify_validation_alerts,
    post_alert,
)


def _make_result(symbol: str, is_alert: bool, diff_bps: int = 0, median: str = "100.00",
                 n_providers: int = 2):
    return SimpleNamespace(
        symbol=symbol,
        is_alert=is_alert,
        diff_bps=diff_bps,
        median_close=median,
        n_providers=n_providers,
    )


# ============================================================================
# build_alert_payload
# ============================================================================


def test_payload_filters_only_alerts():
    results = [
        _make_result("OK1", False),
        _make_result("ALT1", True, diff_bps=400),
        _make_result("OK2", False),
        _make_result("ALT2", True, diff_bps=500, median="28.75", n_providers=3),
    ]
    p = build_alert_payload(results, "2026-05-10", threshold_bps=300)
    assert len(p["alerts"]) == 2
    assert {a["symbol"] for a in p["alerts"]} == {"ALT1", "ALT2"}
    assert p["checked"] == 4
    assert p["threshold_bps"] == 300
    assert p["on_date"] == "2026-05-10"
    assert "5eyes" in p["text"]
    assert "2 von 4" in p["text"]


def test_payload_includes_generated_at_iso():
    results = [_make_result("X", True, diff_bps=400)]
    p = build_alert_payload(results, "2026-05-10", 300)
    assert p["generated_at"].endswith("Z")


def test_payload_no_alerts_zero_in_text():
    results = [_make_result("X", False), _make_result("Y", False)]
    p = build_alert_payload(results, "2026-05-10", 300)
    assert p["alerts"] == []
    assert "0 von 2" in p["text"]


# ============================================================================
# post_alert (mit Mock-urlopen)
# ============================================================================


def _mock_response(status=200):
    resp = MagicMock()
    resp.__enter__ = MagicMock(return_value=resp)
    resp.__exit__ = MagicMock(return_value=False)
    resp.status = status
    return resp


def test_post_alert_returns_true_on_2xx():
    with patch.object(notifier, "urlopen", return_value=_mock_response(200)) as mock:
        ok = post_alert("https://hook.example/x", {"text": "hi"})
    assert ok is True
    args, kwargs = mock.call_args
    req = args[0]
    assert req.method == "POST"
    assert req.headers.get("Content-type") == "application/json"
    body_payload = json.loads(req.data.decode("utf-8"))
    assert body_payload == {"text": "hi"}


def test_post_alert_returns_false_on_5xx():
    with patch.object(notifier, "urlopen", return_value=_mock_response(503)):
        ok = post_alert("https://hook.example/x", {"text": "hi"})
    assert ok is False


def test_post_alert_swallows_url_error():
    from urllib.error import URLError
    with patch.object(notifier, "urlopen", side_effect=URLError("dns fail")):
        ok = post_alert("https://hook.example/x", {"text": "hi"})
    assert ok is False


def test_post_alert_swallows_http_error():
    from urllib.error import HTTPError
    err = HTTPError("http://x", 502, "bad gateway", {}, None)
    with patch.object(notifier, "urlopen", side_effect=err):
        ok = post_alert("https://hook.example/x", {"text": "hi"})
    assert ok is False


def test_post_alert_swallows_timeout():
    with patch.object(notifier, "urlopen", side_effect=TimeoutError("slow")):
        ok = post_alert("https://hook.example/x", {"text": "hi"})
    assert ok is False


def test_post_alert_empty_url_returns_false_without_call():
    with patch.object(notifier, "urlopen") as mock:
        ok = post_alert("", {"text": "x"})
    assert ok is False
    assert mock.call_count == 0


# ============================================================================
# notify_validation_alerts (Convenience)
# ============================================================================


def test_notify_skips_when_no_alerts():
    with patch.object(notifier, "urlopen") as mock:
        n_alerts, sent = notify_validation_alerts(
            [_make_result("X", False)],
            webhook_url="https://hook/x",
            threshold_bps=300,
        )
    assert n_alerts == 0
    assert sent is False
    assert mock.call_count == 0


def test_notify_skips_when_empty_url():
    with patch.object(notifier, "urlopen") as mock:
        n_alerts, sent = notify_validation_alerts(
            [_make_result("X", True, diff_bps=400)],
            webhook_url="",
            threshold_bps=300,
        )
    assert n_alerts == 1
    assert sent is False
    assert mock.call_count == 0


def test_notify_posts_when_alerts_and_url():
    with patch.object(notifier, "urlopen", return_value=_mock_response(200)) as mock:
        n_alerts, sent = notify_validation_alerts(
            [_make_result("X", True, diff_bps=400, median="28.75")],
            webhook_url="https://hook/x",
            threshold_bps=300,
            on_date="2026-05-10",
        )
    assert n_alerts == 1
    assert sent is True
    assert mock.call_count == 1
    # Verify payload structure
    req = mock.call_args.args[0]
    payload = json.loads(req.data.decode("utf-8"))
    assert payload["alerts"][0]["symbol"] == "X"
    assert payload["alerts"][0]["diff_bps"] == 400


# ============================================================================
# weekly_validation_job-Integration (Mock-Provider)
# ============================================================================


def test_weekly_job_does_not_post_when_no_webhook(tmp_path):
    """webhook_url=None -> kein Webhook-Aufruf, auch bei Alerts."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import configure_mappers, sessionmaker
    from database import Base
    from models.market_data_validation_log import MarketDataValidationLog  # noqa: F401
    from models import (  # noqa: F401
        allocation, clients, mandates, profiling, review, users, wealth,
    )
    from models.market_data_cache import MarketDataCacheEntry  # noqa: F401
    configure_mappers()

    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}",
                           connect_args={"check_same_thread": False})
    SF = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        from services.market_data.scheduled import weekly_validation_job
        with patch.object(notifier, "urlopen") as mock:
            checked, alerts = weekly_validation_job(
                symbols=["UBSG.SW"],
                session_factory=SF,
                on_date=Date(2026, 5, 10),
                webhook_url=None,
            )
        assert checked >= 0
        assert mock.call_count == 0
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_weekly_job_passes_webhook_through_when_set(tmp_path, monkeypatch):
    """webhook_url + Alerts -> Webhook wird gerufen.

    Wir mocken validate_batch direkt, damit wir kontrollierbare
    ValidationResults bekommen ohne echte Provider.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import configure_mappers, sessionmaker
    from database import Base
    from models.market_data_validation_log import MarketDataValidationLog  # noqa: F401
    from models import (  # noqa: F401
        allocation, clients, mandates, profiling, review, users, wealth,
    )
    from models.market_data_cache import MarketDataCacheEntry  # noqa: F401
    configure_mappers()

    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}",
                           connect_args={"check_same_thread": False})
    SF = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        from services.market_data import validation, scheduled
        fake_result = SimpleNamespace(
            symbol="X", is_alert=True, diff_bps=500, median_close="100.00",
            n_providers=2,
        )
        monkeypatch.setattr(validation, "validate_batch",
                            lambda **kwargs: [fake_result])
        monkeypatch.setattr(scheduled, "validate_batch",
                            lambda **kwargs: [fake_result], raising=False)

        # Patch import inside scheduled.py
        with patch("services.market_data.validation.validate_batch",
                   return_value=[fake_result]):
            with patch.object(notifier, "urlopen",
                              return_value=_mock_response(200)) as mock:
                checked, alerts = scheduled.weekly_validation_job(
                    symbols=["X"],
                    session_factory=SF,
                    on_date=Date(2026, 5, 10),
                    webhook_url="https://hook.example/x",
                )
        assert alerts == 1
        assert mock.call_count == 1
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()
