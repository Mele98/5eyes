"""K3 / N-915-06: EINE Regel fuer Bestand ausserhalb der Empfehlung (Fremdbestand).

Reines Blatt (nur Standardbibliothek). Ein Kunde haelt in seinem
Wertschriftendepot oft Titel, die nicht in der Empfehlung stehen. Bisher liess
sich Bestand nur je Empfehlungsposition erfassen; der Depotcheck rechnete dann
mit Zielbetraegen (IST = SOLL) und die Handelsliste blieb ohne Weg.

Quelle: ``wealth_positions.external_holdings_json`` an einer aktiven
Depot-Position im Beratungsvermoegen. Je Titel: Bezeichnung, optional ISIN,
Anlageklasse (eine der fuenf Klassen), Waehrung, Marktwert (kleinste Einheit)
und Stichtag.

Bewertung (``evaluate``, genutzt von Depotcheck, Depot-Snapshot und
Handelsliste): Marktwert in der erfassten Waehrung, zeilenweise mit der
FX-Basis der jeweiligen Berechnung (``convert``) in die Mandatswaehrung.
Fail-closed: fehlt Marktwert, Stichtag oder Kurs, liegt der Stichtag nach dem
Bewertungstag, steht dieselbe ISIN in der Empfehlung oder schon einmal im
selben Depot (Doppelzaehlung, N-937-03), ist der Titel "nicht bewertbar" -- kein Ersatzwert, kein angenommener Kurs, kein
Rueckfall auf das Soll.
"""
from __future__ import annotations

import json

ORIGIN_EXTERNAL = "external_holding"
VALUATION_BASIS_EXTERNAL = "external_market_value"
ADVISORY_ASSIGNMENTS = ("Beratungsvermögen", "Beratungsvermoegen")

# Anlageklasse -> Bucket-Schluessel (dieselben fuenf Klassen wie Depotcheck/Allokation).
ASSET_CLASS_BUCKETS = {
    "Aktien": "equities",
    "Obligationen": "bonds",
    "Immobilien": "real_estate",
    "Alternative Anlagen": "alternatives",
    "Liquidität": "liquidity",
}

STATUS_OK = "ok"
STATUS_MISSING_VALUE = "missing_value"
STATUS_MISSING_DATE = "missing_date"
STATUS_FUTURE_DATE = "future_date"
STATUS_MISSING_FX = "missing_fx"
STATUS_IN_RECOMMENDATION = "in_recommendation"
STATUS_INVALID = "invalid"
STATUS_DUPLICATE = "duplicate_isin"

STATUS_TEXT = {
    STATUS_OK: "bewertet",
    STATUS_MISSING_VALUE: "nicht bewertbar – Marktwert fehlt",
    STATUS_MISSING_DATE: "nicht bewertbar – Stichtag fehlt",
    STATUS_FUTURE_DATE: "nicht bewertbar – Stichtag liegt in der Zukunft",
    STATUS_MISSING_FX: "nicht bewertbar – Wechselkurs fehlt",
    STATUS_IN_RECOMMENDATION: "nicht bewertbar – Titel steht in der Empfehlung (Bestand dort erfassen)",
    STATUS_INVALID: "nicht bewertbar – Angaben unvollständig",
    STATUS_DUPLICATE: "nicht bewertbar – ISIN im selben Depot doppelt erfasst",
}

ACTION_REVIEW = "REVIEW"
ACTION_REVIEW_LABEL = "Verkauf prüfen (Vorschlag)"

_UPPER = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
_DIGITS = "0123456789"


def normalize_isin(value) -> str | None:
    text = "".join(str(value or "").split()).upper()
    return text or None


def isin_is_valid(isin) -> bool:
    """Format und Pruefziffer (ISO 6166: Buchstaben -> Zahlen, Luhn)."""
    if not isinstance(isin, str) or len(isin) != 12:
        return False
    if not (all(c in _UPPER for c in isin[:2]) and all(c in _UPPER + _DIGITS for c in isin[2:11])
            and isin[11] in _DIGITS):
        return False
    digits = "".join(str(int(ch, 36)) for ch in isin[:-1])
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch) * (2 if i % 2 == 0 else 1)
        total += n - 9 if n > 9 else n
    return (10 - total % 10) % 10 == int(isin[-1])


def is_advisory_depot(position) -> bool:
    """Aktive Depot-Position im Beratungsvermoegen (nicht geloescht)."""
    return (
        str(getattr(position, "position_type", "") or "") == "Depot"
        and getattr(position, "deleted_at", None) is None
        and int(getattr(position, "is_active", 1) or 0) == 1
        and str(getattr(position, "assignment", "") or "").strip() in ADVISORY_ASSIGNMENTS
    )


def parse_items(raw) -> list[dict]:
    """Gespeicherte Liste lesen. Unlesbarer Inhalt ist kein leerer Bestand:
    ein nicht bewertbarer Eintrag (fail-closed)."""
    if raw is None or str(raw).strip() == "":
        return []
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return [{"_corrupt": True}]
    if not isinstance(data, list):
        return [{"_corrupt": True}]
    return [item if isinstance(item, dict) else {"_corrupt": True} for item in data]


def duplicate_isins(items) -> list[str]:
    """N-937-03: ISINs, die in EINER Fremdliste (ein Depot) mehrfach stehen."""
    seen: set[str] = set()
    dups: set[str] = set()
    for item in items or []:
        isin = normalize_isin(item.get("isin")) if isinstance(item, dict) else None
        if isin:
            (dups if isin in seen else seen).add(isin)
    return sorted(dups)


def dump_items(items) -> str | None:
    rows = [dict(item) for item in items or []]
    return json.dumps(rows, ensure_ascii=False, sort_keys=True) if rows else None


def strict_converter(fx, target_currency):
    """Umrechnung ueber die FX-Basis der Berechnung (``FxBasis`` oder strikte
    ``FXRateSource``: beide bieten ``convert_storage_amount``). Ohne Basis ist
    nur die Mandatswaehrung umrechenbar."""
    target = str(target_currency or "CHF").upper().strip() or "CHF"

    def convert(amount: int, currency: str) -> int:
        if currency == target:
            return int(amount)
        if fx is None:
            raise ValueError("Keine FX-Basis fuer " + str(currency))
        return int(fx.convert_storage_amount(int(amount), currency, target))

    return convert


def iso_date(value) -> str | None:
    """``YYYY-MM-DD`` (gueltiges Kalenderdatum) oder ``None``."""
    text = str(value or "").strip()[:10]
    if len(text) != 10 or text[4] != "-" or text[7] != "-" or not (text[:4] + text[5:7] + text[8:]).isdigit():
        return None
    year, month, day = int(text[:4]), int(text[5:7]), int(text[8:])
    leap = year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
    days = (31, 29 if leap else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)
    return text if year >= 1900 and 1 <= month <= 12 and 1 <= day <= days[month - 1] else None


def _status(item: dict, today: str, excluded: set) -> str:
    if item.get("_corrupt"):
        return STATUS_INVALID
    if str(item.get("asset_class") or "") not in ASSET_CLASS_BUCKETS or not str(item.get("currency") or "").strip():
        return STATUS_INVALID
    isin = normalize_isin(item.get("isin"))
    if isin and isin in excluded:
        return STATUS_IN_RECOMMENDATION
    value = item.get("market_value_rappen")
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return STATUS_MISSING_VALUE
    as_of = iso_date(item.get("valuation_date"))
    if as_of is None:
        return STATUS_MISSING_DATE
    return STATUS_FUTURE_DATE if as_of > today else STATUS_OK


def evaluate(depots, *, convert, exclude_isins=(), today: str) -> dict:
    """``depots``: Folge von ``(wealth_position_id, external_holdings_json)``;
    ``today``: Bewertungstag ``YYYY-MM-DD``.

    Returns ``{"items", "count", "valued_count", "unvalued_count",
    "total_rappen"}``; ``total_rappen`` summiert nur bewertete Titel. Ist ein
    Titel nicht bewertbar, unterbleibt jede Aussage ueber das ganze Depot
    (Aufrufer pruefen ``unvalued_count``). ``convert`` wirft ``Exception``
    bei fehlendem Kurs -- dann "nicht bewertbar", nie ein Ersatzwert."""
    excluded = {normalize_isin(i) for i in exclude_isins or () if normalize_isin(i)}
    items: list[dict] = []
    total = 0
    for wealth_position_id, raw in depots or ():
        seen: set[str] = set()  # N-937-03: dieselbe ISIN zweimal im selben Depot zaehlt nie doppelt
        for index, item in enumerate(parse_items(raw)):
            status = _status(item, str(today)[:10], excluded)
            isin = normalize_isin(item.get("isin")) if not item.get("_corrupt") else None
            if isin and status != STATUS_IN_RECOMMENDATION:
                if isin in seen:
                    status = STATUS_DUPLICATE
                seen.add(isin)
            currency = str(item.get("currency") or "").upper().strip() or None
            amount = None
            if status == STATUS_OK:
                try:
                    amount = int(convert(int(item["market_value_rappen"]), currency))
                except Exception:  # noqa: BLE001 -- jeder Kursfehler: nicht bewertbar (fail-closed)
                    status = STATUS_MISSING_FX
            value = item.get("market_value_rappen")
            asset_class = str(item.get("asset_class") or "") or None
            items.append({
                "id": f"ext-{wealth_position_id}-{index + 1}",
                "wealth_position_id": str(wealth_position_id),
                "label": " ".join(str(item.get("label") or "").split()) or "Titel ohne Bezeichnung",
                "isin": normalize_isin(item.get("isin")),
                "asset_class": asset_class,
                "bucket": ASSET_CLASS_BUCKETS.get(asset_class or ""),
                "currency": currency,
                "market_value_rappen": value if isinstance(value, int) and not isinstance(value, bool) else None,
                "valuation_date": str(item.get("valuation_date") or "").strip() or None,
                "amount_base_rappen": amount,
                "status": status,
                "status_text": STATUS_TEXT[status],
            })
            if amount is not None:
                total += amount
    valued = sum(1 for e in items if e["status"] == STATUS_OK)
    return {"items": items, "count": len(items), "valued_count": valued,
            "unvalued_count": len(items) - valued, "total_rappen": total}


def unvalued_message(items) -> str:
    bad = [e for e in items or [] if e.get("status") != STATUS_OK]
    names = "; ".join(f"{e.get('label')} ({e.get('status_text')})" for e in bad)
    return (
        f"{len(bad)} Titel ausserhalb der Empfehlung nicht bewertbar: {names}. "
        "Ohne belegten Wert gibt es keine Aussage über das ganze Depot; bitte "
        "Marktwert, Stichtag und Wechselkurs erfassen."
    )


def recommendation_zero_message(names) -> str:
    """N-937-02: Kundensprache (Depotcheck, Classic, PDF). Ist Fremdbestand
    erfasst, zaehlt ein Titel der Empfehlung ohne erfassten Bestand 0 -- diese
    Annahme bleibt sichtbar."""
    names = list(names or [])
    verb = "zählt" if len(names) == 1 else "zählen"
    return f"{len(names)} Titel der Empfehlung ohne erfassten Bestand {verb} 0: {'; '.join(names)}."
