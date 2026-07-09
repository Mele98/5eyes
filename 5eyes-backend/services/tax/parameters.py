"""Persistence helpers for global tax reference parameters."""
from __future__ import annotations

import datetime as _dt
import json
from typing import Any

from sqlalchemy.orm import Session

from models.tax import TaxParameterSet
from services.tax.reference_data import (
    CH_CANTON_PARAMETER_SETS,
    CH_PARAMETER_VERSION,
    CH_PARAMETER_YEAR,
    ch_default_parameter_sets,
)


def _utc_now() -> str:
    return _dt.datetime.now(_dt.UTC).isoformat().replace("+00:00", "Z")


def _parameter_id(country_code: str, region: str, year: int, version: str) -> str:
    return f"{country_code.upper()}-{region.upper()}-{year}-{version}"


def seed_default_tax_parameter_sets(db: Session) -> int:
    """Insert built-in reference parameter sets if they are missing.

    Existing rows are not overwritten. That preserves local corrections while
    keeping fresh installs usable.
    """
    inserted = 0
    now = _utc_now()
    for region, params in CH_CANTON_PARAMETER_SETS.items():
        row_id = _parameter_id("CH", region, CH_PARAMETER_YEAR, CH_PARAMETER_VERSION)
        exists = db.get(TaxParameterSet, row_id)
        if exists:
            continue
        db.add(
            TaxParameterSet(
                id=row_id,
                country_code="CH",
                region=region,
                year=CH_PARAMETER_YEAR,
                params_json=json.dumps(params, sort_keys=True),
                is_current=1,
                version=CH_PARAMETER_VERSION,
                source="built-in-reference",
                created_at=now,
                updated_at=now,
            )
        )
        inserted += 1
    if inserted:
        db.flush()
    return inserted


def get_country_parameter_sets(
    db: Session,
    country_code: str,
    year: int | None = None,
) -> dict[str, dict[str, Any]]:
    """Return current parameter sets for a country.

    Falls back to built-in CH defaults if the reference table has not been
    seeded yet. The fallback is deterministic and carries the same version data.
    """
    country = country_code.upper().strip()
    query = db.query(TaxParameterSet).filter(
        TaxParameterSet.country_code == country,
        TaxParameterSet.is_current == 1,
    )
    if year is not None:
        query = query.filter(TaxParameterSet.year == year)
    rows = query.order_by(TaxParameterSet.region.asc()).all()
    if rows:
        result: dict[str, dict[str, Any]] = {}
        for row in rows:
            if not row.region:
                continue
            try:
                result[row.region.upper()] = json.loads(row.params_json or "{}")
            except json.JSONDecodeError:
                continue
        if result:
            return result

    if country == "CH":
        return ch_default_parameter_sets()
    return {}


def list_current_regions(
    db: Session,
    country_code: str,
    year: int | None = None,
) -> list[str]:
    params = get_country_parameter_sets(db, country_code, year)
    return sorted(params.keys())

