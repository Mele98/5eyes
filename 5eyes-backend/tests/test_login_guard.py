from services.login_guard import LoginAttemptGuard


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
