from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from config import settings


@dataclass
class LoginGuardDecision:
    allowed: bool
    retry_after_seconds: int = 0
    reason: str | None = None


class LoginAttemptGuard:
    def __init__(self) -> None:
        self._failures: dict[str, deque[datetime]] = defaultdict(deque)
        self._locked_until: dict[str, datetime] = {}

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _normalize(username: str) -> str:
        return username.strip().lower()

    def _cleanup(self, username: str, now: datetime) -> None:
        window_start = now - timedelta(seconds=settings.login_window_seconds)
        queue = self._failures.get(username)
        if queue:
            while queue and queue[0] < window_start:
                queue.popleft()
            if not queue:
                self._failures.pop(username, None)

        locked_until = self._locked_until.get(username)
        if locked_until and locked_until <= now:
            self._locked_until.pop(username, None)

    def check(self, username: str) -> LoginGuardDecision:
        if not settings.login_rate_limit_enabled:
            return LoginGuardDecision(allowed=True)

        now = self._now()
        normalized = self._normalize(username)
        self._cleanup(normalized, now)
        locked_until = self._locked_until.get(normalized)
        if locked_until and locked_until > now:
            retry_after = int((locked_until - now).total_seconds()) + 1
            return LoginGuardDecision(
                allowed=False,
                retry_after_seconds=retry_after,
                reason='Zu viele Fehlversuche. Bitte später erneut versuchen.',
            )
        return LoginGuardDecision(allowed=True)

    def register_failure(self, username: str) -> LoginGuardDecision:
        if not settings.login_rate_limit_enabled:
            return LoginGuardDecision(allowed=True)

        now = self._now()
        normalized = self._normalize(username)
        self._cleanup(normalized, now)
        queue = self._failures[normalized]
        queue.append(now)

        if len(queue) >= settings.login_max_attempts:
            locked_until = now + timedelta(seconds=settings.login_lockout_seconds)
            self._locked_until[normalized] = locked_until
            retry_after = int((locked_until - now).total_seconds()) + 1
            return LoginGuardDecision(
                allowed=False,
                retry_after_seconds=retry_after,
                reason='Zu viele Fehlversuche. Bitte später erneut versuchen.',
            )

        remaining = max(settings.login_max_attempts - len(queue), 0)
        return LoginGuardDecision(
            allowed=True,
            retry_after_seconds=0,
            reason=f'Anmeldung fehlgeschlagen. Verbleibende Versuche: {remaining}.',
        )

    def register_success(self, username: str) -> None:
        normalized = self._normalize(username)
        self._failures.pop(normalized, None)
        self._locked_until.pop(normalized, None)


login_attempt_guard = LoginAttemptGuard()
