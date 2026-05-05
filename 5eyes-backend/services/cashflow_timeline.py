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
) -> int:
    amount = int(amount_rappen or 0)
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


def totals_for_year(cashflows: list, year: int | None = None) -> dict[str, int]:
    target_year = int(year or date.today().year)
    recurring_income = 0
    capital_inflow = 0
    recurring_expense = 0
    capital_outflow = 0
    for cf in cashflows:
        amount = contribution_for_year(
            amount_rappen=int(getattr(cf, "amount_rappen", 0) or 0),
            frequency=getattr(cf, "frequency", None),
            nature=getattr(cf, "nature", None),
            valid_from=getattr(cf, "valid_from", None),
            valid_until=getattr(cf, "valid_until", None),
            year=target_year,
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


def net_cashflow_series(cashflows: list, years: int, start_year: int | None = None) -> list[int]:
    base_year = int(start_year or date.today().year)
    return [totals_for_year(cashflows, base_year + offset)["net_rappen"] for offset in range(max(0, years))]


def recurring_net_cashflow_series(cashflows: list, years: int, start_year: int | None = None) -> list[int]:
    base_year = int(start_year or date.today().year)
    series: list[int] = []
    for offset in range(max(0, years)):
        totals = totals_for_year(cashflows, base_year + offset)
        series.append(totals["recurring_income_rappen"] - totals["recurring_expense_rappen"])
    return series


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
