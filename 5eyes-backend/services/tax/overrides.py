"""Helper: apply Mandate.tax_overrides_json auf ein Regime.

Trennt die Verantwortung: Mandate liefert overrides_json (String),
overrides.py parst + delegiert an regime.with_overrides().

Spec: docs/planning/2026-05-17-sprint-3-tax-plugin-system.md §3
"""
from __future__ import annotations

import json
from typing import Mapping, TYPE_CHECKING

if TYPE_CHECKING:
    from services.tax.base import TaxRegime


def parse_overrides_json(overrides_json: str | None) -> dict[str, float]:
    """Parsed JSON-String zu Dict. None oder leerer String → leeres Dict.

    Sicher gegen Malformed-JSON: gibt {} zurueck und loggt Warnung.
    """
    if not overrides_json:
        return {}
    try:
        data = json.loads(overrides_json)
    except (json.JSONDecodeError, TypeError):
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict[str, float] = {}
    for k, v in data.items():
        if isinstance(k, str) and isinstance(v, (int, float)):
            out[k] = float(v)
    return out


def apply_overrides(regime: "TaxRegime", overrides_json: str | None) -> "TaxRegime":
    """Wendet Mandate.tax_overrides_json auf das Regime an.

    Wenn overrides_json None/leer/invalid → Original-Regime unveraendert zurueck.
    Sonst: regime.with_overrides(parsed_dict).
    """
    overrides = parse_overrides_json(overrides_json)
    if not overrides:
        return regime
    return regime.with_overrides(overrides)


def validate_all(
    regime: "TaxRegime", overrides: Mapping[str, float]
) -> tuple[str, ...]:
    """Sammelt alle Plausi-Warnungen vom Regime fuer die Overrides.

    Wird vom API-Endpoint genutzt bevor er Overrides persistiert:
    'Berater, dein Override 'wealth_tax_bps_pa=5000' ist ungewoehnlich hoch.'
    """
    return regime.validate_parameters(overrides)
