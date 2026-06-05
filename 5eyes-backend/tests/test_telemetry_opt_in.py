"""Sprint U-64 (Roadmap-Punkt 64, 2026-06-04): Telemetrie opt-in Tests."""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services import telemetry  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_telemetry_state():
    telemetry._reset_for_testing()
    yield
    telemetry._reset_for_testing()


def test_default_settings_disable_telemetry():
    from config import settings
    assert settings.telemetry_enabled is False
    assert settings.telemetry_dsn == ''
    assert settings.telemetry_sample_rate == 1.0


def test_configure_returns_false_when_disabled(monkeypatch):
    monkeypatch.setattr('config.settings.telemetry_enabled', False)
    monkeypatch.setattr('config.settings.telemetry_dsn', 'https://x@sentry.io/1')
    assert telemetry.configure_telemetry() is False
    assert telemetry.is_telemetry_active() is False


def test_configure_returns_false_when_no_dsn(monkeypatch):
    monkeypatch.setattr('config.settings.telemetry_enabled', True)
    monkeypatch.setattr('config.settings.telemetry_dsn', '')
    assert telemetry.configure_telemetry() is False


def test_configure_returns_false_when_dsn_whitespace_only(monkeypatch):
    monkeypatch.setattr('config.settings.telemetry_enabled', True)
    monkeypatch.setattr('config.settings.telemetry_dsn', '   ')
    assert telemetry.configure_telemetry() is False


def test_configure_returns_false_when_sentry_sdk_not_installed(monkeypatch):
    monkeypatch.setattr('config.settings.telemetry_enabled', True)
    monkeypatch.setattr('config.settings.telemetry_dsn', 'https://x@sentry.io/1')

    real_import = __builtins__['__import__'] if isinstance(__builtins__, dict) else __builtins__.__import__

    def fake_import(name, *args, **kwargs):
        if name == 'sentry_sdk':
            raise ImportError("simulated")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr('builtins.__import__', fake_import)
    assert telemetry.configure_telemetry() is False


def test_configure_succeeds_with_dsn_and_mock_sentry(monkeypatch):
    monkeypatch.setattr('config.settings.telemetry_enabled', True)
    monkeypatch.setattr('config.settings.telemetry_dsn', 'https://x@sentry.io/1')
    monkeypatch.setattr('config.settings.telemetry_environment', 'production')

    mock_sentry = MagicMock()
    monkeypatch.setitem(sys.modules, 'sentry_sdk', mock_sentry)

    assert telemetry.configure_telemetry() is True
    assert telemetry.is_telemetry_active() is True
    mock_sentry.init.assert_called_once()
    call_kwargs = mock_sentry.init.call_args.kwargs
    assert call_kwargs['dsn'] == 'https://x@sentry.io/1'
    assert call_kwargs['environment'] == 'production'
    assert call_kwargs['send_default_pii'] is False
    assert call_kwargs['traces_sample_rate'] == 0.0


def test_configure_clamps_sample_rate(monkeypatch):
    monkeypatch.setattr('config.settings.telemetry_enabled', True)
    monkeypatch.setattr('config.settings.telemetry_dsn', 'https://x@sentry.io/1')
    monkeypatch.setattr('config.settings.telemetry_sample_rate', 5.0)

    mock_sentry = MagicMock()
    monkeypatch.setitem(sys.modules, 'sentry_sdk', mock_sentry)

    telemetry.configure_telemetry()
    assert mock_sentry.init.call_args.kwargs['sample_rate'] == 1.0


def test_configure_uses_app_env_when_environment_empty(monkeypatch):
    monkeypatch.setattr('config.settings.telemetry_enabled', True)
    monkeypatch.setattr('config.settings.telemetry_dsn', 'https://x@sentry.io/1')
    monkeypatch.setattr('config.settings.telemetry_environment', '')
    monkeypatch.setattr('config.settings.app_env', 'staging')

    mock_sentry = MagicMock()
    monkeypatch.setitem(sys.modules, 'sentry_sdk', mock_sentry)

    telemetry.configure_telemetry()
    assert mock_sentry.init.call_args.kwargs['environment'] == 'staging'


def test_configure_is_idempotent(monkeypatch):
    monkeypatch.setattr('config.settings.telemetry_enabled', True)
    monkeypatch.setattr('config.settings.telemetry_dsn', 'https://x@sentry.io/1')

    mock_sentry = MagicMock()
    monkeypatch.setitem(sys.modules, 'sentry_sdk', mock_sentry)

    telemetry.configure_telemetry()
    telemetry.configure_telemetry()
    mock_sentry.init.assert_called_once()


def test_configure_handles_init_exception(monkeypatch):
    monkeypatch.setattr('config.settings.telemetry_enabled', True)
    monkeypatch.setattr('config.settings.telemetry_dsn', 'https://x@sentry.io/1')

    mock_sentry = MagicMock()
    mock_sentry.init.side_effect = RuntimeError("DSN invalid")
    monkeypatch.setitem(sys.modules, 'sentry_sdk', mock_sentry)

    assert telemetry.configure_telemetry() is False


def test_capture_exception_no_op_when_inactive(caplog):
    with caplog.at_level(logging.ERROR):
        try:
            raise ValueError("simulated")
        except ValueError as exc:
            telemetry.capture_exception(exc)
    assert any('simulated' in r.getMessage() for r in caplog.records)


def test_capture_exception_active_calls_sentry(monkeypatch):
    monkeypatch.setattr('config.settings.telemetry_enabled', True)
    monkeypatch.setattr('config.settings.telemetry_dsn', 'https://x@sentry.io/1')

    mock_sentry = MagicMock()
    monkeypatch.setitem(sys.modules, 'sentry_sdk', mock_sentry)
    telemetry.configure_telemetry()

    try:
        raise ValueError("active capture")
    except ValueError as exc:
        telemetry.capture_exception(exc)

    mock_sentry.capture_exception.assert_called_once()


def test_capture_exception_with_context_uses_scope(monkeypatch):
    monkeypatch.setattr('config.settings.telemetry_enabled', True)
    monkeypatch.setattr('config.settings.telemetry_dsn', 'https://x@sentry.io/1')

    mock_sentry = MagicMock()
    mock_scope = MagicMock()
    mock_sentry.push_scope.return_value.__enter__.return_value = mock_scope
    monkeypatch.setitem(sys.modules, 'sentry_sdk', mock_sentry)
    telemetry.configure_telemetry()

    try:
        raise ValueError("with context")
    except ValueError as exc:
        telemetry.capture_exception(exc, context={"mandate_id": "MX-1"})

    mock_scope.set_extra.assert_called_with("mandate_id", "MX-1")


def test_capture_message_no_op_when_inactive(caplog):
    with caplog.at_level(logging.INFO):
        telemetry.capture_message("test note")
    assert any('test note' in r.getMessage() for r in caplog.records)


def test_capture_message_active_calls_sentry(monkeypatch):
    monkeypatch.setattr('config.settings.telemetry_enabled', True)
    monkeypatch.setattr('config.settings.telemetry_dsn', 'https://x@sentry.io/1')

    mock_sentry = MagicMock()
    monkeypatch.setitem(sys.modules, 'sentry_sdk', mock_sentry)
    telemetry.configure_telemetry()

    telemetry.capture_message("operational note", level="warning")
    mock_sentry.capture_message.assert_called_once_with(
        "operational note", level="warning",
    )


def test_capture_exception_swallows_sentry_failure(monkeypatch):
    monkeypatch.setattr('config.settings.telemetry_enabled', True)
    monkeypatch.setattr('config.settings.telemetry_dsn', 'https://x@sentry.io/1')

    mock_sentry = MagicMock()
    mock_sentry.capture_exception.side_effect = RuntimeError("transport down")
    monkeypatch.setitem(sys.modules, 'sentry_sdk', mock_sentry)
    telemetry.configure_telemetry()

    try:
        raise ValueError("x")
    except ValueError as exc:
        telemetry.capture_exception(exc)
