from __future__ import annotations

from calendar import monthrange
from datetime import date


SUPPORTED_FREQUENCIES = {
    "monatlich",
    "quartalsweise",
    "halbjährlich",
    "jährlich",
    "einmalig",
}

_TOKEN_FIXUPS = {
    "ä": "ae",
    "ö": "oe",
    "ü": "ue",
    "Ã¤": "ae",
    "Ã¶": "oe",
    "Ã¼": "ue",
}


def _normalize_token(value: str | None) -> str:
    normalized = str(value or "").strip().lower()
    for source, target in _TOKEN_FIXUPS.items():
        normalized = normalized.replace(source, target)
    return normalized.replace("?", "").replace(" ", "").replace("-", "")


def _parse_date(value: str | None) -> date | None:
    raw = str(value or "").strip()[:10]
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def _add_months(anchor: date, months: int) -> date:
    year = anchor.year + (anchor.month - 1 + months) // 12
    month = (anchor.month - 1 + months) % 12 + 1
    day = min(anchor.day, monthrange(year, month)[1])
    return date(year, month, day)


def normalize_frequency(value: str | None) -> str:
    raw = str(value or "").strip()
    normalized = _normalize_token(raw)
    mapping = {
        "monatlich": "monatlich",
        "monthly": "monatlich",
        "quartalsweise": "quartalsweise",
        "vierteljaehrlich": "quartalsweise",
        "quarter": "quartalsweise",
        "quarterly": "quartalsweise",
        "quarteryearly": "quartalsweise",
        "halbjaehrlich": "halbjährlich",
        "semiannual": "halbjährlich",
        "semiannually": "halbjährlich",
        "jaehrlich": "jährlich",
        "annual": "jährlich",
        "yearly": "jährlich",
        "annually": "jährlich",
        "einmalig": "einmalig",
        "once": "einmalig",
        "oneoff": "einmalig",
        "onetime": "einmalig",
    }
    return mapping.get(normalized, raw or "jährlich")


def normalize_nature(value: str | None, frequency: str | None = None) -> str:
    normalized = _normalize_token(value)
    if normalize_frequency(frequency) == "einmalig":
        return "einmalig"
    if normalized in {"einmalig", "oneoff", "once"}:
        return "einmalig"
    return "wiederkehrend"


def event_date_for_cashflow(
    valid_from: str | None,
    valid_until: str | None,
    fallback_today: date | None = None,
) -> date:
    return _parse_date(valid_from) or _parse_date(valid_until) or fallback_today or date.today()


def contribution_for_year(
    *,
    amount_rappen: int,
    frequency: str | None,
    nature: str | None,
    valid_from: str | None,
    valid_until: str | None,
    year: int,
    inflation_factor: float = 1.0,
) -> int:
    """Annualisierter Beitrag eines Cashflows fuer ein Ziel-Jahr.

    B1: ``inflation_factor`` skaliert den Periodenbetrag (vom Aufrufer
    berechnet als ``Pi(1+inflation_t)`` fuer is_inflation_linked Cashflows,
    sonst 1.0). User gibt Beträge in heutigen Rappen (real) ein, Backend
    rechnet die nominalen Zukunfts-Rappen.
    """
    amount = int(round(int(amount_rappen or 0) * float(inflation_factor or 1.0)))
    if amount == 0:
        return 0

    frequency_value = normalize_frequency(frequency)
    nature_value = normalize_nature(nature, frequency_value)
    year_start = date(year, 1, 1)
    year_end = date(year, 12, 31)
    start = _parse_date(valid_from)
    end = _parse_date(valid_until)

    if end and start and end < start:
        return 0

    if frequency_value == "einmalig" or nature_value == "einmalig":
        event_date = event_date_for_cashflow(valid_from, valid_until)
        return amount if event_date.year == year else 0

    if end and end < year_start:
        return 0
    if start and start > year_end:
        return 0

    months_per_occurrence = {
        "monatlich": 1,
        "quartalsweise": 3,
        "halbjährlich": 6,
        "jährlich": 12,
    }.get(frequency_value, 12)

    anchor = start or year_start
    current = anchor
    while current < year_start:
        current = _add_months(current, months_per_occurrence)

    effective_end = min(end or year_end, year_end)
    occurrences = 0
    while current <= effective_end:
        occurrences += 1
        current = _add_months(current, months_per_occurrence)

    return amount * occurrences


def _is_one_off_flow(frequency: str | None, nature: str | None) -> bool:
    frequency_value = normalize_frequency(frequency)
    nature_value = normalize_nature(nature, frequency_value)
    return frequency_value == "einmalig" or nature_value == "einmalig"


def _compound_inflation_factor(
    inflation_series_bps: list[int] | None,
    start_year: int | None,
    target_year: int,
) -> float:
    """B1: kumulierter Inflations-Faktor von ``start_year`` bis ``target_year``.

    inflation_series_bps[i] = Inflation in bps fuer das Jahr ``start_year + i``.
    Faktor fuer Jahr t (= start_year + t) = Pi_{i=0..t-1}(1 + inflation_i / 10000).
    Im Start-Jahr selber: Faktor 1.0 (User-Input ist heute-Wert).
    """
    if not inflation_series_bps:
        return 1.0
    base = int(start_year or target_year)
    offset = int(target_year) - base
    if offset <= 0:
        return 1.0
    factor = 1.0
    for i in range(offset):
        if i >= len(inflation_series_bps):
            # Falls Series zu kurz: letzter Wert wird konstant fortgeschrieben
            inflation = inflation_series_bps[-1]
        else:
            inflation = inflation_series_bps[i]
        factor *= 1.0 + (int(inflation or 0) / 10000.0)
    return factor


def totals_for_year(
    cashflows: list,
    year: int | None = None,
    *,
    inflation_series_bps: list[int] | None = None,
    start_year: int | None = None,
) -> dict[str, int]:
    target_year = int(year or date.today().year)
    inflation_factor_universal = _compound_inflation_factor(
        inflation_series_bps, start_year, target_year
    )
    recurring_income = 0
    capital_inflow = 0
    recurring_expense = 0
    capital_outflow = 0
    for cf in cashflows:
        # B1: nur is_inflation_linked Cashflows werden inflationiert.
        # Aufrufer kann inflation_series_bps weglassen -> Faktor 1.0 (nominal).
        is_linked = bool(getattr(cf, "is_inflation_linked", 0))
        cf_factor = inflation_factor_universal if is_linked else 1.0
        amount = contribution_for_year(
            amount_rappen=int(getattr(cf, "amount_rappen", 0) or 0),
            frequency=getattr(cf, "frequency", None),
            nature=getattr(cf, "nature", None),
            valid_from=getattr(cf, "valid_from", None),
            valid_until=getattr(cf, "valid_until", None),
            year=target_year,
            inflation_factor=cf_factor,
        )
        if amount == 0:
            continue
        one_off = _is_one_off_flow(
            frequency=getattr(cf, "frequency", None),
            nature=getattr(cf, "nature", None),
        )
        if str(getattr(cf, "cashflow_type", "")) == "Income":
            if one_off:
                capital_inflow += amount
            else:
                recurring_income += amount
        elif str(getattr(cf, "cashflow_type", "")) == "Expense":
            if one_off:
                capital_outflow += amount
            else:
                recurring_expense += amount
    income = recurring_income + capital_inflow
    expense = recurring_expense + capital_outflow
    return {
        "year": target_year,
        "recurring_income_rappen": recurring_income,
        "capital_inflow_rappen": capital_inflow,
        "income_rappen": income,
        "recurring_expense_rappen": recurring_expense,
        "capital_outflow_rappen": capital_outflow,
        "expense_rappen": expense,
        "net_rappen": income - expense,
    }


def net_cashflow_series(
    cashflows: list,
    years: int,
    start_year: int | None = None,
    *,
    inflation_series_bps: list[int] | None = None,
) -> list[int]:
    base_year = int(start_year or date.today().year)
    return [
        totals_for_year(
            cashflows,
            base_year + offset,
            inflation_series_bps=inflation_series_bps,
            start_year=base_year,
        )["net_rappen"]
        for offset in range(max(0, years))
    ]


def recurring_net_cashflow_series(
    cashflows: list,
    years: int,
    start_year: int | None = None,
    *,
    inflation_series_bps: list[int] | None = None,
) -> list[int]:
    base_year = int(start_year or date.today().year)
    return [
        totals_for_year(
            cashflows,
            base_year + offset,
            inflation_series_bps=inflation_series_bps,
            start_year=base_year,
        )["recurring_income_rappen"]
        - totals_for_year(
            cashflows,
            base_year + offset,
            inflation_series_bps=inflation_series_bps,
            start_year=base_year,
        )["recurring_expense_rappen"]
        for offset in range(max(0, years))
    ]


def future_value_with_cashflow_series(
    current_rappen: int,
    contribution_series_rappen: list[int],
    expected_return_bps: int,
) -> int:
    rate = expected_return_bps / 10000
    future = float(current_rappen)
    for contribution in contribution_series_rappen:
        future = future * (1 + rate) + float(contribution or 0)
    return int(round(future))
