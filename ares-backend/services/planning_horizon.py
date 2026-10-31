"""Shared life-expectancy defaults for projection horizons."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any


def _year(value: Any, *, minimum: int = 1900) -> int | None:
    if isinstance(value, (date, datetime)):
        parsed = value.year
    elif isinstance(value, int):
        parsed = value
    else:
        text = str(value or "").strip()
        if len(text) < 4:
            return None
        try:
            parsed = int(text[:4])
        except (TypeError, ValueError):
            return None
    return parsed if parsed >= minimum else None


def _is_male(value: Any) -> bool:
    normalized = str(value or "").strip().casefold()
    return normalized == "m" or normalized == "herr" or normalized.startswith("herr ")


def _person_life_expectancy_year(
    date_of_birth: Any,
    salutation: Any,
    *,
    fallback_birth_year: Any = None,
) -> int | None:
    birth_year = _year(date_of_birth) or _year(fallback_birth_year)
    if birth_year is None:
        return None
    return birth_year + (83 if _is_male(salutation) else 85)


def life_expectancy_year_for(client: Any = None, mandate: Any = None) -> int | None:
    """Return the authoritative projection end year.

    A manually configured mandate year wins. Otherwise the year is derived
    from the client and, when present, the partner. The household projection
    ends at the later calendar year. Unknown/non-male salutations use +85.
    """

    manual_year = _year(getattr(mandate, "life_expectancy_year", None), minimum=1)
    if manual_year is not None:
        return manual_year

    if client is None and mandate is not None:
        client = getattr(mandate, "client", None)

    # Kontrollrunde 2026-09-21: die client_sex-Fallback-Verzweigung war toter
    # Code -- sie feuerte nur wenn primary_year None blieb, was ausschliesslich
    # von der Geburtsjahr-Aufloesung abhaengt (nicht von salutation), und
    # beide Aufrufe teilten sich denselben fallback_birth_year. Blieb die
    # erste Aufloesung ohne Geburtsjahr, blieb auch die zweite ohne -- die
    # Verzweigung konnte das Ergebnis nie aendern. Fix: mandate.client_sex
    # greift jetzt korrekt genau dann, wenn client.salutation fehlt (nicht
    # wenn das Geburtsjahr fehlt).
    salutation = getattr(client, "salutation", None)
    if not salutation and mandate is not None:
        salutation = getattr(mandate, "client_sex", None)

    primary_year = _person_life_expectancy_year(
        getattr(client, "date_of_birth", None),
        salutation,
        fallback_birth_year=getattr(mandate, "client_birth_year", None),
    )

    partner_year = _person_life_expectancy_year(
        getattr(client, "partner_date_of_birth", None),
        getattr(client, "partner_salutation", None),
    )
    years = [year for year in (primary_year, partner_year) if year is not None]
    return max(years) if years else None
