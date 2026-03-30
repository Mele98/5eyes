from __future__ import annotations

import json
from typing import Any
from urllib.request import Request, urlopen

from config import settings


OPENFIGI_MAPPING_URL = "https://api.openfigi.com/v3/mapping"


def _build_mapping_job(
    *,
    isin: str | None = None,
    symbol: str | None = None,
    exchange_code: str | None = None,
    mic_code: str | None = None,
    currency: str | None = None,
) -> dict[str, Any]:
    raw_isin = str(isin or "").strip() or None
    raw_symbol = str(symbol or "").strip() or None
    raw_exchange_code = str(exchange_code or "").strip() or None
    raw_mic_code = str(mic_code or "").strip() or None
    raw_currency = str(currency or "").strip().upper() or None

    if raw_exchange_code and raw_mic_code:
        raise ValueError("OpenFIGI Preview akzeptiert exchCode oder micCode, aber nicht beides gleichzeitig")

    if raw_isin:
        job: dict[str, Any] = {
            "idType": "ID_ISIN",
            "idValue": raw_isin,
        }
    elif raw_symbol:
        job = {
            "idType": "TICKER",
            "idValue": raw_symbol,
        }
    else:
        raise ValueError("OpenFIGI Preview benoetigt ISIN oder Symbol")

    if raw_exchange_code:
        job["exchCode"] = raw_exchange_code
    if raw_mic_code:
        job["micCode"] = raw_mic_code
    if raw_currency:
        job["currency"] = raw_currency
    return job


def _candidate_payload(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "figi": item.get("figi"),
        "ticker": item.get("ticker"),
        "name": item.get("name"),
        "exch_code": item.get("exchCode"),
        "composite_figi": item.get("compositeFIGI"),
        "share_class_figi": item.get("shareClassFIGI"),
        "security_type": item.get("securityType"),
        "security_type2": item.get("securityType2"),
        "market_sector": item.get("marketSector"),
        "security_description": item.get("securityDescription"),
    }


def preview_openfigi_mapping(
    *,
    isin: str | None = None,
    symbol: str | None = None,
    exchange_code: str | None = None,
    mic_code: str | None = None,
    currency: str | None = None,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    job = _build_mapping_job(
        isin=isin,
        symbol=symbol,
        exchange_code=exchange_code,
        mic_code=mic_code,
        currency=currency,
    )
    payload = json.dumps([job]).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "5Eyes-WealthArchitekten/1.0",
    }
    if settings.openfigi_api_key:
        headers["X-OPENFIGI-APIKEY"] = settings.openfigi_api_key
    request = Request(
        OPENFIGI_MAPPING_URL,
        data=payload,
        headers=headers,
        method="POST",
    )
    try:
        with urlopen(request, timeout=15) as response:
            raw = response.read().decode("utf-8")
    except Exception as exc:
        raise RuntimeError(f"OpenFIGI Mapping fehlgeschlagen: {exc}") from exc

    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("OpenFIGI Mapping lieferte keine gueltige JSON-Antwort") from exc

    if not isinstance(decoded, list) or not decoded:
        raise RuntimeError("OpenFIGI Mapping lieferte kein Ergebnisarray")

    first = decoded[0] if isinstance(decoded[0], dict) else {}
    candidates = [_candidate_payload(item) for item in list(first.get("data") or []) if isinstance(item, dict)]
    return {
        "source": "openfigi",
        "api_key_used": bool(settings.openfigi_api_key),
        "request_job": job,
        "resolved_from": context or {},
        "warning": first.get("warning"),
        "error": first.get("error"),
        "candidates": candidates,
    }
