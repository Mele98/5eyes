"""Sprint U-64 (2026-06-04): Telemetrie-Adapter (opt-in, Lazy-Import).

Pattern
-------
- Sentry-SDK ist NICHT als harte Dependency in requirements.txt.
- Wer Sentry nutzen will: `pip install sentry-sdk` + telemetry_enabled
  + telemetry_dsn setzen.
- Ohne diese Konfiguration: alle Funktionen sind no-ops, kein Crash,
  kein Logging-Spam.

API
---
- configure_telemetry(): wird beim Startup aufgerufen (main.py)
- capture_exception(exc, context=None): meldet eine Exception
- capture_message(msg, level='info'): meldet eine textuelle Notiz
- is_telemetry_active(): True wenn aktiv

Compliance
----------
Sentry sendet bei Default-Setup nicht-IP, kein User-PII. Telemetrie
sollte nur aktiv sein wenn:
- DSN gesetzt
- Berater/Compliance hat opt-in erteilt
- Production (in dev/test bewusst aus halten, sonst verzerrt Metriken)
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from config import settings

logger = logging.getLogger(__name__)

# Modul-State
_TELEMETRY_ACTIVE: bool = False
_SENTRY_SDK: Optional[Any] = None


def is_telemetry_active() -> bool:
    return _TELEMETRY_ACTIVE


def configure_telemetry() -> bool:
    """Initialisiert Sentry wenn opt-in + dsn gesetzt + sentry-sdk
    installiert. Idempotent: zweiter Aufruf ist no-op.

    Returns True wenn aktiv nach Aufruf.
    """
    global _TELEMETRY_ACTIVE, _SENTRY_SDK

    if _TELEMETRY_ACTIVE:
        return True

    enabled = bool(getattr(settings, "telemetry_enabled", False))
    dsn = str(getattr(settings, "telemetry_dsn", "") or "").strip()

    if not enabled:
        logger.debug("Telemetrie: disabled (telemetry_enabled=False).")
        return False
    if not dsn:
        logger.warning(
            "Telemetrie: enabled aber kein telemetry_dsn — bleibt inaktiv.",
        )
        return False

    try:
        import sentry_sdk  # noqa: F401
    except ImportError:
        logger.warning(
            "Telemetrie: sentry_sdk nicht installiert. "
            "`pip install sentry-sdk` falls aktiv gewuenscht.",
        )
        return False

    _SENTRY_SDK = sentry_sdk
    environment = str(getattr(settings, "telemetry_environment", "") or
                      getattr(settings, "app_env", "development"))
    sample_rate = float(getattr(settings, "telemetry_sample_rate", 1.0) or 1.0)

    try:
        _SENTRY_SDK.init(
            dsn=dsn,
            environment=environment,
            sample_rate=max(0.0, min(1.0, sample_rate)),
            traces_sample_rate=0.0,
            send_default_pii=False,
        )
    except Exception:  # noqa: BLE001
        logger.exception("Telemetrie: sentry_sdk.init failed — bleibt inaktiv.")
        return False

    _TELEMETRY_ACTIVE = True
    logger.info(
        "Telemetrie aktiv (environment=%s, sample_rate=%.2f).",
        environment, sample_rate,
    )
    return True


def capture_exception(
    exc: BaseException,
    *,
    context: Optional[dict[str, Any]] = None,
) -> None:
    """No-op wenn Telemetrie inaktiv. Logged exc IMMER lokal."""
    logger.exception("Captured exception: %s", exc, extra={"context": context})
    if not _TELEMETRY_ACTIVE or _SENTRY_SDK is None:
        return
    try:
        if context:
            with _SENTRY_SDK.push_scope() as scope:
                for k, v in context.items():
                    scope.set_extra(str(k), v)
                _SENTRY_SDK.capture_exception(exc)
        else:
            _SENTRY_SDK.capture_exception(exc)
    except Exception:  # noqa: BLE001
        logger.exception("Telemetrie: capture_exception failed.")


def capture_message(
    message: str,
    *,
    level: str = "info",
) -> None:
    """No-op wenn Telemetrie inaktiv. Logged lokal mit passendem Level."""
    log_method = getattr(logger, level.lower(), logger.info)
    log_method("Captured message: %s", message)
    if not _TELEMETRY_ACTIVE or _SENTRY_SDK is None:
        return
    try:
        _SENTRY_SDK.capture_message(message, level=level)
    except Exception:  # noqa: BLE001
        logger.exception("Telemetrie: capture_message failed.")


def _reset_for_testing() -> None:
    """Test-only Reset."""
    global _TELEMETRY_ACTIVE, _SENTRY_SDK
    _TELEMETRY_ACTIVE = False
    _SENTRY_SDK = None
