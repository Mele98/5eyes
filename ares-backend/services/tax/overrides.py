"""Helper: apply Mandate.tax_overrides_json auf ein Regime.

Trennt die Verantwortung: Mandate liefert overrides_json (String),
overrides.py parst + delegiert an regime.with_overrides().

Spec: docs/planning/2026-05-17-sprint-3-tax-plugin-system.md §3
"""
from __future__ import annotations

import json
import math
from typing import Mapping, TYPE_CHECKING

if TYPE_CHECKING:
    from services.tax.base import TaxRegime


SUPPORTED_TAX_OVERRIDE_KEYS = frozenset(
    {
        "wealth_tax_bps_pa",
        "dividend_tax_bps",
        "interest_tax_bps",
        "capital_gains_tax_bps",
        "pension_lumpsum_tax_bps",
        "inheritance_tax_bps_default",
    }
)
"""Kanonische, optimizer-wirksame Override-Felder (alle in Basispunkten)."""

MIN_TAX_RATE_BPS = 0.0
MAX_TAX_RATE_BPS = 10_000.0


def validate_tax_overrides(overrides: Mapping[object, object]) -> dict[str, float]:
    """Validiert Overrides atomar und liefert normalisierte ``float``-Werte.

    Alle unterstuetzten Felder sind SteuerSAETZE in Basispunkten. Damit ist
    der fachlich vollstaendige Wertebereich 0..10_000 (0..100 Prozent),
    jeweils inklusive. Ein fehlerhaftes Feld verwirft den gesamten Satz von
    Overrides; partielle Anwendung wuerde eine andere Steuerbasis modellieren
    als die konfigurierte.
    """
    if not isinstance(overrides, Mapping):
        raise ValueError("tax overrides must be a JSON object")

    normalized: dict[str, float] = {}
    for key, value in overrides.items():
        if not isinstance(key, str) or key not in SUPPORTED_TAX_OVERRIDE_KEYS:
            raise ValueError(
                "tax overrides must contain only supported rate fields"
            )
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
        ):
            raise ValueError(
                "tax overrides must contain finite numeric basis-point values"
            )
        rate_bps = float(value)
        if not MIN_TAX_RATE_BPS <= rate_bps <= MAX_TAX_RATE_BPS:
            raise ValueError(
                f"tax override '{key}' must be between 0 and 10000 bps inclusive"
            )
        normalized[key] = rate_bps
    return normalized


def parse_overrides_json(overrides_json: str | None) -> dict[str, float]:
    """Parst und validiert einen konfigurierten JSON-Override atomar.

    ``None`` bzw. leerer/blanker String bedeutet explizit "keine Overrides".
    Jeder nicht-leere ungueltige Payload wirft ``ValueError`` (fail-closed),
    damit Solver und Simulation nicht still mit Default-Steuern weiterlaufen.
    """
    if overrides_json is None or (
        isinstance(overrides_json, str) and not overrides_json.strip()
    ):
        return {}
    if not isinstance(overrides_json, str):
        raise ValueError("tax overrides must be encoded as a JSON string")
    try:
        data = json.loads(overrides_json)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValueError("malformed tax overrides JSON") from exc
    return validate_tax_overrides(data)


def apply_overrides(regime: "TaxRegime", overrides_json: str | None) -> "TaxRegime":
    """Wendet Mandate.tax_overrides_json auf das Regime an.

    Wenn overrides_json None/leer → Original-Regime unveraendert zurueck.
    Ungueltige konfigurierte Overrides schlagen fail-closed fehl.
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
    return regime.validate_parameters(validate_tax_overrides(overrides))
