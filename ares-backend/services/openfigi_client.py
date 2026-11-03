from __future__ import annotations

import json
from typing import Any
from urllib.request import Request, urlopen

from config import settings, user_agent
from services.product_market_data import map_openfigi_exchange_code


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


def _split_ticker(raw_ticker: Any) -> tuple[str | None, str | None]:
    """OpenFIGI liefert Ticker teils in Bloomberg-Space-Notation ("UBSG SW").

    OF-1 / Audit O5: Der Boersenteil wird abgetrennt und NICHT als Suffix
    angehaengt ("VWRL LN" -> "VWRL.LN" loeste kein Provider auf). Das Produkt
    bekommt das blanke Symbol plus internen Boersencode; die Provider-
    Symbolik entsteht erst in services/product_market_data.provider_lookup_symbol.
    """
    ticker = str(raw_ticker or "").strip() or None
    if ticker and " " in ticker:
        base, _sep, suffix = ticker.rpartition(" ")
        if base.strip() and suffix:
            return base.strip(), suffix.strip().upper()
    return ticker, None


def _normalize_ticker(raw_ticker: Any) -> str | None:
    """Blankes Symbol ohne Bloomberg-Boersenteil (siehe _split_ticker)."""
    return _split_ticker(raw_ticker)[0]


def _candidate_payload(item: dict[str, Any]) -> dict[str, Any]:
    ticker, ticker_exchange = _split_ticker(item.get("ticker"))
    raw_exch_code = str(item.get("exchCode") or "").strip().upper() or ticker_exchange
    mapped = map_openfigi_exchange_code(raw_exch_code)
    if not raw_exch_code:
        status = "missing"
    elif mapped:
        status = "mapped"
    else:
        status = "unknown"
    return {
        "figi": item.get("figi"),
        "ticker": ticker,
        "name": item.get("name"),
        "exch_code": item.get("exchCode") or ticker_exchange,
        # OF-1: interner Boersencode (Basis der Provider-Symbolik) bzw. None,
        # wenn der Bloomberg-Code nicht in der expliziten Tabelle steht.
        "exchange_code": mapped,
        "exchange_code_status": status,
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
        "User-Agent": user_agent(),
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
