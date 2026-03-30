from __future__ import annotations

import json
from typing import Any
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from config import settings


EODHD_SEARCH_URL = "https://eodhd.com/api/search/{query}"


def _clean(value: Any) -> str | None:
    raw = str(value or "").strip()
    return raw or None


def _clean_upper(value: Any) -> str | None:
    raw = _clean(value)
    return raw.upper() if raw else None


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
        raise RuntimeError(f"EODHD Request fehlgeschlagen: {exc}") from exc
    try:
        return json.loads(payload)
    except json.JSONDecodeError as exc:
        raise RuntimeError("EODHD lieferte keine gueltige JSON-Antwort") from exc


def _pick(obj: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in obj and obj.get(key) not in {None, ""}:
            return obj.get(key)
    return None


def _candidate_payload(item: dict[str, Any], *, score: int) -> dict[str, Any]:
    return {
        "symbol": _clean(_pick(item, "Code", "code", "Symbol", "symbol")),
        "exchange_code": _clean(_pick(item, "Exchange", "exchange")),
        "name": _clean(_pick(item, "Name", "name")),
        "instrument_type": _clean(_pick(item, "Type", "type")),
        "country": _clean(_pick(item, "Country", "country")),
        "currency": _clean_upper(_pick(item, "Currency", "currency")),
        "isin": _clean_upper(_pick(item, "ISIN", "Isin", "isin")),
        "match_score": score,
    }


def _score_candidate(
    item: dict[str, Any],
    *,
    isin: str | None,
    symbol: str | None,
    exchange_code: str | None,
    currency: str | None,
    product_name: str | None,
) -> int:
    score = 0
    candidate_isin = _clean_upper(_pick(item, "ISIN", "Isin", "isin"))
    candidate_symbol = _clean(_pick(item, "Code", "code", "Symbol", "symbol"))
    candidate_exchange = _clean(_pick(item, "Exchange", "exchange"))
    candidate_currency = _clean_upper(_pick(item, "Currency", "currency"))
    candidate_name = _clean(_pick(item, "Name", "name"))
    if isin and candidate_isin and candidate_isin == isin:
        score += 80
    if symbol and candidate_symbol and candidate_symbol.upper() == symbol.upper():
        score += 50
    if exchange_code and candidate_exchange and candidate_exchange.upper() == exchange_code.upper():
        score += 25
    if currency and candidate_currency and candidate_currency == currency:
        score += 15
    if product_name and candidate_name and candidate_name.strip().lower() == product_name.strip().lower():
        score += 10
    return score


def _search_eodhd(query: str, *, limit: int = 10) -> list[dict[str, Any]]:
    token = _clean(settings.eodhd_api_key)
    if not token:
        raise RuntimeError("EODHD API Key ist nicht konfiguriert")
    path = EODHD_SEARCH_URL.format(query=quote(query))
    params = urlencode({"api_token": token, "fmt": "json", "limit": limit})
    decoded = _request_json(f"{path}?{params}")
    if isinstance(decoded, list):
        return [item for item in decoded if isinstance(item, dict)]
    if isinstance(decoded, dict) and isinstance(decoded.get("data"), list):
        return [item for item in decoded["data"] if isinstance(item, dict)]
    if isinstance(decoded, dict) and decoded.get("error"):
        raise RuntimeError(f"EODHD Search fehlgeschlagen: {decoded.get('error')}")
    return []


def preview_eodhd_reference(
    *,
    isin: str | None = None,
    symbol: str | None = None,
    product_name: str | None = None,
    exchange_code: str | None = None,
    currency: str | None = None,
    limit: int = 10,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    raw_isin = _clean_upper(isin)
    raw_symbol = _clean(symbol)
    raw_name = _clean(product_name)
    raw_exchange = _clean(exchange_code)
    raw_currency = _clean_upper(currency)

    queries: list[tuple[str, str]] = []
    if raw_isin:
        queries.append(("isin", raw_isin))
    if raw_symbol:
        queries.append(("symbol", raw_symbol))
    if raw_name:
        queries.append(("product_name", raw_name))
    if not queries:
        raise ValueError("EODHD Preview benoetigt ISIN, Symbol oder Produktname")

    selected_query_type = None
    selected_query_value = None
    candidates: list[dict[str, Any]] = []
    for query_type, query_value in queries:
        rows = _search_eodhd(query_value, limit=limit)
        scored = []
        for item in rows:
            score = _score_candidate(
                item,
                isin=raw_isin,
                symbol=raw_symbol,
                exchange_code=raw_exchange,
                currency=raw_currency,
                product_name=raw_name,
            )
            scored.append((score, item))
        scored.sort(key=lambda item: (-item[0], str(_pick(item[1], "Name", "name") or "")))
        candidates = [_candidate_payload(item, score=score) for score, item in scored]
        selected_query_type = query_type
        selected_query_value = query_value
        if candidates:
            break

    return {
        "source": "eodhd",
        "api_key_used": bool(settings.eodhd_api_key),
        "query_used": {
            "type": selected_query_type,
            "value": selected_query_value,
            "exchange_code": raw_exchange,
            "currency": raw_currency,
            "limit": limit,
        },
        "resolved_from": context or {},
        "warning": None if candidates else "Keine EODHD-Referenzdaten gefunden",
        "candidates": candidates,
    }
