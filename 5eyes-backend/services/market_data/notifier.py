"""P22 — Webhook-Notifier fuer Validation-Alerts.

Wenn `weekly_validation_job` Alerts findet (Median-Diff > Threshold),
postet dieser Notifier ein JSON-Payload an eine User-konfigurierte
Webhook-URL (Slack-/Discord-/generisch).

Opt-in: nur aktiv wenn `settings.market_data_alert_webhook_url` gesetzt.
Default: leer -> Notifier ist no-op, kein Netzwerkverkehr.

Format des Payloads (Slack-kompatibel via 'text'-Feld; weitere Felder
sind generisch verwendbar):
    {
      "text": "5eyes Cross-Validation Alert: 2 von 12 Symbolen ueber Threshold (300 bps).",
      "alerts": [
        {"symbol":"UBSG.SW","diff_bps":418,"median_close":"28.75","n_providers":3},
        ...
      ],
      "checked": 12,
      "threshold_bps": 300,
      "on_date": "2026-05-10",
      "generated_at": "2026-05-10T04:00:00Z"
    }

Defensive: jeder HTTP-Fehler wird geswallowed + geloggt. Der Alert soll
nie den Scheduler killen.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS = 5.0


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_alert_payload(
    results: list[Any],
    on_date: str | None,
    threshold_bps: int,
) -> dict[str, Any]:
    """Baut JSON-Payload aus einer Liste von ValidationResult-Objekten."""
    alerts = []
    for r in results:
        if not getattr(r, "is_alert", False):
            continue
        alerts.append({
            "symbol": getattr(r, "symbol", "?"),
            "diff_bps": int(getattr(r, "diff_bps", 0) or 0),
            "median_close": str(getattr(r, "median_close", "") or ""),
            "n_providers": getattr(r, "n_providers", 0),
        })
    text = (
        f"5eyes Cross-Validation Alert: {len(alerts)} von {len(results)} "
        f"Symbolen ueber Threshold ({threshold_bps} bps)."
    )
    return {
        "text": text,
        "alerts": alerts,
        "checked": len(results),
        "threshold_bps": int(threshold_bps),
        "on_date": str(on_date or ""),
        "generated_at": _now_iso(),
    }


def post_alert(
    webhook_url: str,
    payload: dict[str, Any],
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> bool:
    """POST JSON an Webhook. True=Erfolg, False=Fehler (geswallowed)."""
    url = (webhook_url or "").strip()
    if not url:
        return False
    try:
        body = json.dumps(payload).encode("utf-8")
        req = Request(
            url,
            data=body,
            headers={"Content-Type": "application/json", "User-Agent": "5eyes-alerter/1"},
            method="POST",
        )
        with urlopen(req, timeout=timeout_seconds) as resp:
            status = getattr(resp, "status", 200)
        if 200 <= int(status) < 300:
            return True
        logger.warning("alert webhook returned HTTP %s", status)
        return False
    except HTTPError as exc:
        logger.warning("alert webhook HTTPError: %s %s", exc.code, exc.reason)
    except URLError as exc:
        logger.warning("alert webhook URLError: %s", exc.reason)
    except (TimeoutError, OSError) as exc:
        logger.warning("alert webhook network error: %s", exc)
    except Exception as exc:  # noqa: BLE001
        logger.warning("alert webhook unexpected error: %s", exc)
    return False


def notify_validation_alerts(
    results: list[Any],
    *,
    webhook_url: str,
    threshold_bps: int,
    on_date: str | None = None,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> tuple[int, bool]:
    """High-Level Convenience: nur wenn Alerts UND webhook_url -> POST.

    Returns (n_alerts, sent).
    """
    n_alerts = sum(1 for r in results if getattr(r, "is_alert", False))
    if n_alerts == 0 or not (webhook_url or "").strip():
        return n_alerts, False
    payload = build_alert_payload(results, on_date, threshold_bps)
    sent = post_alert(webhook_url, payload, timeout_seconds=timeout_seconds)
    return n_alerts, sent
