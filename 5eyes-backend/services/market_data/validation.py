"""Cross-Validation: vergleicht 2-3 Provider, schreibt Log + Alert.

Ueberlegen: einzelner Provider kann Daten-Drift haben (split missed,
falsche Adjustments, korrupte Quote). Mit 2-3 Providern + Median-
Vergleich erkennt der Berater systematische Drift.

Ablauf:
  validate_symbol(symbol, on_date, providers, threshold_bps=300, db=None)
  - rufe pro Provider.get_eod(symbol, on_date)
  - sammle (name, close)-Paare; Provider-Fehler skip
  - bei < 2 Quotes: status='insufficient_data'
  - berechne median/min/max der Closes (Decimal)
  - diff_bps = (max-min)/median * 10000
  - is_alert = diff_bps > threshold_bps
  - wenn db gegeben: schreibe MarketDataValidationLog
  - return ValidationResult

Kein eigener Cron — APScheduler-Hook kommt in P13 (Integration).
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date as Date
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Iterable

from .base import MarketDataProvider
from .exceptions import MarketDataError

logger = logging.getLogger(__name__)


DEFAULT_THRESHOLD_BPS = 300  # 3% Abweichung -> Alert


@dataclass(frozen=True)
class ProviderQuote:
    name: str
    close: Decimal


@dataclass(frozen=True)
class ValidationResult:
    """Ergebnis einer Cross-Validation fuer ein Symbol an einem Datum.

    status:
      - 'ok'                : Diff <= Threshold, kein Alert
      - 'alert'             : Diff > Threshold
      - 'insufficient_data' : weniger als 2 Provider lieferten Daten
    """
    symbol: str
    on_date: Date
    status: str
    quotes: list[ProviderQuote]
    median_close: Decimal | None
    min_close: Decimal | None
    max_close: Decimal | None
    diff_bps: int
    threshold_bps: int
    is_alert: bool

    @property
    def n_providers(self) -> int:
        return len(self.quotes)


# --------------------------------------------------------------------------- #
def _median(values: list[Decimal]) -> Decimal:
    """Median ueber Decimal-Liste. Geht von len(values) >= 1 aus."""
    sorted_v = sorted(values)
    n = len(sorted_v)
    mid = n // 2
    if n % 2 == 1:
        return sorted_v[mid]
    return (sorted_v[mid - 1] + sorted_v[mid]) / Decimal(2)


def validate_symbol(
    symbol: str,
    on_date: Date,
    providers: Iterable[MarketDataProvider],
    threshold_bps: int = DEFAULT_THRESHOLD_BPS,
    db: Any | None = None,
) -> ValidationResult:
    """Cross-Validation fuer ein Symbol an einem Tag.

    db: optional SQLAlchemy-Session — wenn gegeben, wird ein
    MarketDataValidationLog-Eintrag geschrieben (db.commit()).
    """
    threshold = max(0, int(threshold_bps))
    quotes: list[ProviderQuote] = []
    for provider in providers:
        try:
            bar = provider.get_eod(symbol, on_date)
        except Exception as exc:  # noqa: BLE001 - skip bad provider
            logger.warning(
                "validate_symbol: %s skipped for %s (%s)",
                provider.name, symbol, exc,
            )
            continue
        try:
            quotes.append(ProviderQuote(name=provider.name, close=Decimal(bar.close)))
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "validate_symbol: cannot decode close from %s (%s)",
                provider.name, exc,
            )
            continue

    if len(quotes) < 2:
        result = ValidationResult(
            symbol=symbol, on_date=on_date,
            status="insufficient_data",
            quotes=quotes,
            median_close=None, min_close=None, max_close=None,
            diff_bps=0, threshold_bps=threshold, is_alert=False,
        )
        # Kein Log-Eintrag bei insufficient_data — nicht aussagekraeftig.
        return result

    closes = [q.close for q in quotes]
    median_close = _median(closes)
    min_close = min(closes)
    max_close = max(closes)
    if median_close > 0:
        diff_bps = int(round(float((max_close - min_close) / median_close) * 10000))
    else:
        diff_bps = 0
    is_alert = diff_bps > threshold
    status = "alert" if is_alert else "ok"

    result = ValidationResult(
        symbol=symbol, on_date=on_date,
        status=status,
        quotes=quotes,
        median_close=median_close,
        min_close=min_close,
        max_close=max_close,
        diff_bps=diff_bps,
        threshold_bps=threshold,
        is_alert=is_alert,
    )

    if is_alert:
        logger.warning(
            "validate_symbol: ALERT %s on %s diff=%dbps median=%s providers=%s",
            symbol, on_date, diff_bps, median_close,
            [q.name for q in quotes],
        )

    if db is not None:
        _persist_log(db, result)

    return result


def validate_batch(
    symbols: Iterable[str],
    on_date: Date,
    providers: Iterable[MarketDataProvider],
    threshold_bps: int = DEFAULT_THRESHOLD_BPS,
    db: Any | None = None,
) -> list[ValidationResult]:
    """validate_symbol fuer eine Liste von Symbolen."""
    provider_list = list(providers)
    results: list[ValidationResult] = []
    for sym in symbols:
        results.append(
            validate_symbol(sym, on_date, provider_list, threshold_bps=threshold_bps, db=db)
        )
    return results


def _persist_log(db: Any, result: ValidationResult) -> None:
    """Schreibt einen MarketDataValidationLog-Eintrag. Defensive: schluckt
    DB-Fehler (Logging soll nie den Validation-Flow brechen)."""
    from models.market_data_validation_log import MarketDataValidationLog  # lazy
    try:
        providers_payload = [
            {"name": q.name, "close": str(q.close)} for q in result.quotes
        ]
        entry = MarketDataValidationLog(
            symbol=result.symbol,
            on_date=result.on_date.isoformat(),
            checked_at=datetime.now(timezone.utc).isoformat(),
            providers_json=json.dumps(providers_payload, separators=(",", ":")),
            median_close=str(result.median_close),
            min_close=str(result.min_close),
            max_close=str(result.max_close),
            diff_bps=int(result.diff_bps),
            threshold_bps=int(result.threshold_bps),
            is_alert=1 if result.is_alert else 0,
            n_providers=int(result.n_providers),
        )
        db.add(entry)
        db.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning("validate_symbol: persist_log failed (%s)", exc)
        try:
            db.rollback()
        except Exception:  # noqa: BLE001
            pass
