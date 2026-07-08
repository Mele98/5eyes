import pytest

from services.login_guard import LoginAttemptGuard, login_attempt_guard


@pytest.fixture(autouse=True)
def _reset_persistent_login_guard():
    """AUTH-03: der Guard ist jetzt DB-persistent + prozessweit geteilt.

    Frueher hielt jede ``LoginAttemptGuard()``-Instanz eigene In-Memory-Dicts,
    sodass Tests automatisch isoliert waren. Jetzt teilen alle Instanzen (ohne
    explizite Engine) dieselbe App-DB -> Fehlversuche wuerden zwischen Tests
    akkumulieren. Diese Fixture leert den geteilten Zustand vor+nach jedem Test
    (nutzt die Backwards-Compat-Reset-Shims ``_failures``/``_locked_until``).
    """
    login_attempt_guard._failures.clear()
    login_attempt_guard._locked_until.clear()
    yield
    login_attempt_guard._failures.clear()
    login_attempt_guard._locked_until.clear()


def test_login_guard_locks_after_repeated_failures(monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, 'login_rate_limit_enabled', True)
    monkeypatch.setattr(settings, 'login_max_attempts', 3)
    monkeypatch.setattr(settings, 'login_window_seconds', 300)
    monkeypatch.setattr(settings, 'login_lockout_seconds', 600)

    guard = LoginAttemptGuard()
    assert guard.check('admin').allowed is True
    assert guard.register_failure('admin').allowed is True
    assert guard.register_failure('admin').allowed is True
    decision = guard.register_failure('admin')
    assert decision.allowed is False
    assert decision.retry_after_seconds > 0

    blocked = guard.check('admin')
    assert blocked.allowed is False
    assert blocked.retry_after_seconds > 0


def test_login_guard_resets_after_success(monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, 'login_rate_limit_enabled', True)
    monkeypatch.setattr(settings, 'login_max_attempts', 3)
    monkeypatch.setattr(settings, 'login_window_seconds', 300)
    monkeypatch.setattr(settings, 'login_lockout_seconds', 600)

    guard = LoginAttemptGuard()
    guard.register_failure('advisor')
    guard.register_failure('advisor')
    guard.register_success('advisor')

    decision = guard.check('advisor')
    assert decision.allowed is True
    assert decision.retry_after_seconds == 0


# ============================================================================
# Sprint U-58 (Roadmap-Punkt 58, 2026-06-01): erweiterte Test-Coverage
# ============================================================================

import time
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
import pytest

from services.login_guard import LoginGuardDecision


@pytest.fixture()
def u58_guard():
    """Frische Guard-Instance pro U-58-Test — kein Shared-State-Leak."""
    return LoginAttemptGuard()


@pytest.fixture()
def u58_defaults(monkeypatch):
    """Stable defaults fuer alle U-58-Tests (Settings-Schutz)."""
    from config import settings
    monkeypatch.setattr(settings, 'login_rate_limit_enabled', True)
    monkeypatch.setattr(settings, 'login_max_attempts', 5)
    monkeypatch.setattr(settings, 'login_window_seconds', 60)
    monkeypatch.setattr(settings, 'login_lockout_seconds', 600)


def test_u58_check_allows_when_no_history(u58_guard, u58_defaults):
    assert u58_guard.check('192.168.1.1').allowed is True


def test_u58_remaining_counter_in_failure_reason(u58_guard, u58_defaults):
    """Failure-Decisions enthalten verbleibende Versuche im Reason."""
    for i in range(4):
        decision = u58_guard.register_failure('192.168.1.1')
        assert decision.allowed is True
        assert decision.reason is not None
        assert str(5 - i - 1) in decision.reason


def test_u58_check_returns_429_during_lockout(u58_guard, u58_defaults):
    """Nach Lock-out: check() liefert allowed=False mit Retry-After."""
    for _ in range(5):
        u58_guard.register_failure('192.168.1.1')
    decision = u58_guard.check('192.168.1.1')
    assert decision.allowed is False
    assert decision.retry_after_seconds >= 1


def test_u58_lockout_clears_after_seconds(u58_guard, monkeypatch):
    """Lock-out loest sich automatisch nach lockout_seconds."""
    from config import settings
    monkeypatch.setattr(settings, 'login_rate_limit_enabled', True)
    monkeypatch.setattr(settings, 'login_max_attempts', 5)
    monkeypatch.setattr(settings, 'login_window_seconds', 60)
    monkeypatch.setattr(settings, 'login_lockout_seconds', 1)
    for _ in range(5):
        u58_guard.register_failure('192.168.1.1')
    assert u58_guard.check('192.168.1.1').allowed is False
    time.sleep(1.2)
    assert u58_guard.check('192.168.1.1').allowed is True


def test_u58_window_cleanup_removes_old_failures(u58_guard, monkeypatch):
    """Failures aelter als window_seconds zaehlen nicht mehr fuer den Counter."""
    from config import settings
    monkeypatch.setattr(settings, 'login_rate_limit_enabled', True)
    monkeypatch.setattr(settings, 'login_max_attempts', 5)
    monkeypatch.setattr(settings, 'login_window_seconds', 60)

    base = datetime.now(timezone.utc)
    with patch.object(LoginAttemptGuard, '_now', return_value=base):
        for _ in range(4):
            u58_guard.register_failure('192.168.1.1')

    with patch.object(LoginAttemptGuard, '_now', return_value=base + timedelta(seconds=61)):
        decision = u58_guard.register_failure('192.168.1.1')
        # Alle 4 alten Failures sind ausgewindowed -> dieser hier ist 1. im neuen Window
        assert decision.allowed is True
        assert decision.reason is not None
        # 5 max - 1 current = 4 verbleibend
        assert '4' in decision.reason


def test_u58_different_keys_isolated(u58_guard, u58_defaults):
    """Lock auf Key A trifft NICHT Key B (kein Cross-Tenant-Leak)."""
    for _ in range(5):
        u58_guard.register_failure('192.168.1.1')
    assert u58_guard.check('192.168.1.1').allowed is False
    assert u58_guard.check('10.0.0.5').allowed is True


def test_u58_username_normalization_strips_and_lowercases(u58_guard, u58_defaults):
    """  ALICE   und alice zaehlen als selber Key (case-insensitive + strip)."""
    for _ in range(5):
        u58_guard.register_failure('  ALICE  ')
    assert u58_guard.check('alice').allowed is False
    assert u58_guard.check('ALICE').allowed is False
    assert u58_guard.check('  alice  ').allowed is False


def test_u58_disabled_setting_bypasses_all_checks(u58_guard, monkeypatch):
    """login_rate_limit_enabled=False -> kein Rate-Limit, 100 Failures kein Lock."""
    from config import settings
    monkeypatch.setattr(settings, 'login_rate_limit_enabled', False)
    monkeypatch.setattr(settings, 'login_max_attempts', 5)
    for _ in range(100):
        decision = u58_guard.register_failure('192.168.1.1')
        assert decision.allowed is True
    assert u58_guard.check('192.168.1.1').allowed is True


def test_u58_decision_dataclass_schema():
    """LoginGuardDecision-Schema-Drift-Schutz fuer Endpoint-Integration."""
    d = LoginGuardDecision(allowed=False, retry_after_seconds=60, reason='x')
    assert d.allowed is False
    assert d.retry_after_seconds == 60
    assert d.reason == 'x'
    d2 = LoginGuardDecision(allowed=True)
    assert d2.allowed is True
    assert d2.retry_after_seconds == 0
    assert d2.reason is None
