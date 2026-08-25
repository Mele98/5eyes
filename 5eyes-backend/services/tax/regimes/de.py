"""DETaxRegime-Light — Deutsche Pauschal-Werte (Allocation-Fokus).

BEWUSST MINIMAL gehalten (User-Direktive 2026-05-17). Wichtige DE-Spezifika:
- Keine Vermoegenssteuer (seit 1997 ausgesetzt)
- Kapitalertragsteuer 25% + Soli 5.5% = effektiv 26.375% auf Dividenden
  UND Kursgewinne (kein CH-mae Unterschied!)
- ETF-Teilfreistellung (Aktien-ETF: 30% steuerfrei) im default-Pauschal
  weggelassen — Berater override wenn relevant.

Spec: docs/planning/2026-05-17-sprint-3-tax-plugin-system.md (downscaled)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from services.tax.regimes.generic import GenericFlatRateRegime
from services.tax.registry import register_regime


@register_regime("DE")
@dataclass(frozen=True)
class DETaxRegime(GenericFlatRateRegime):
    """Deutschland Pauschal-Steuer-Mittelwerte (ohne Kirchensteuer)."""

    id: str = "DE"
    country_code: str = "DE"
    region_code: str | None = None
    display_name: str = "Deutschland"
    local_currency: str = "EUR"
    tariff_version: str = "DE-LIGHT-v1-2026"

    wealth_tax_bps_pa: float = 0.0  # keine Vermoegenssteuer in DE
    dividend_tax_bps: float = 2637.5  # 25% KESt + 5.5% Soli auf KESt = 26.375%
    interest_tax_bps: float | None = None  # = dividend
    capital_gains_tax_bps: float = 2637.5  # GLEICH wie Dividenden (Abgeltungsteuer)
    pension_lumpsum_tax_bps: float = 0.0  # Fuenftelregelung — pauschal 0 als Default
    inheritance_tax_bps_default: float = 0.0  # Freibetraege gross

    overrides: Mapping[str, float] | None = None
