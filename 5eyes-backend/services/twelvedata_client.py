from __future__ import annotations

import json
from decimal import Decimal, ROUND_HALF_UP
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from config import settings


TWELVEDATA_TIME_SERIES_URL = "https://api.twelvedata.com/time_series"


def _to_rappen(amount: Any) -> int:
    value = Decimal(str(amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return int(value * 100)


def _request_json(url: str) -> Any:
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "5Eyes-WealthArchitekten/1.0",
        },
    )
    try:
        with urlopen(request, timeout=15) as response:
            payload = response.read().decode("utf-8")
    except Exception as exc:
        raise RuntimeError(f"Twelve Data Request fehlgeschlagen: {exc}") from exc
    try:
        return json.loads(payload)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Twelve Data lieferte keine gueltige JSON-Antwort") from exc


def _extract_series_payload(decoded: Any, symbol: str) -> dict[str, Any] | None:
    if isinstance(decoded, dict) and symbol in decoded and isinstance(decoded[symbol], dict):
        return decoded[symbol]
    if isinstance(decoded, dict) and decoded.get("meta"):
        return decoded
    return None


def fetch_twelvedata_latest_prices(symbols: list[str]) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    api_key = str(settings.twelvedata_api_key or "").strip()
    if not api_key:
        raise RuntimeError("Twelve Data API Key ist nicht konfiguriert")
    cleaned_symbols = [str(symbol or "").strip() for symbol in symbols if str(symbol or "").strip()]
    if not cleaned_symbols:
        return {}, {}

    params = urlencode(
        {
            "symbol": ",".join(cleaned_symbols),
            "interval": "1day",
            "outputsize": 2,
            "apikey": api_key,
            "format": "JSON",
        }
    )
    decoded = _request_json(f"{TWELVEDATA_TIME_SERIES_URL}?{params}")

    if isinstance(decoded, dict) and str(decoded.get("status") or "").lower() == "error":
        message = decoded.get("message") or decoded.get("code") or "unbekannter Fehler"
        raise RuntimeError(f"Twelve Data Zeitreihe fehlgeschlagen: {message}")

    resolved: dict[str, dict[str, Any]] = {}
    failures: dict[str, str] = {}
    for symbol in cleaned_symbols:
        payload = _extract_series_payload(decoded, symbol)
        if not payload:
            failures[symbol] = "Kein Twelve-Data-Ergebnis fuer Symbol erhalten"
            continue
        if str(payload.get("status") or "").lower() == "error":
            failures[symbol] = str(payload.get("message") or payload.get("code") or "Symbolfehler")
            continue
        values = payload.get("values")
        if not isinstance(values, list) or not values:
            failures[symbol] = "Keine Werte in Twelve-Data-Zeitreihe vorhanden"
            continue
        latest = values[0] if isinstance(values[0], dict) else None
        if not latest:
            failures[symbol] = "Ungueltiges Twelve-Data-Format"
            continue
        close_value = latest.get("close") or latest.get("value") or payload.get("price")
        if close_value in {None, ""}:
            failures[symbol] = "Kein Schlusskurs in Twelve-Data-Antwort"
            continue
        timestamp = str(latest.get("datetime") or latest.get("date") or "").strip()
        if not timestamp:
            failures[symbol] = "Kein Kursdatum in Twelve-Data-Antwort"
            continue
        resolved[symbol] = {
            "price_date": timestamp[:10],
            "price_rappen": _to_rappen(close_value),
            "source": "twelvedata",
        }
    return resolved, failures
