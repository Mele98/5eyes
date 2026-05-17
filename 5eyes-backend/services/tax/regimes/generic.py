"""GenericFlatRateRegime — Universal-Fallback fuer alle Laender ohne
spezifische Implementierung.

Verwendung:
- Berater fuegt im UI ein neues Land hinzu (z.B. 'VN' fuer Vietnam)
- Gibt Pauschal-Werte ein: 0 bps Wealth, 2000 bps Dividend, 1500 bps Capital-Gains
- 5eyes nutzt dieses Regime mit den eingegebenen Werten
- Spaeter, wenn 5eyes-Team eine VNTaxRegime-Klasse implementiert,
  uebernimmt die fuer 'VN'-IDs automatisch.

Spec: docs/planning/2026-05-17-sprint-3-tax-plugin-system.md §3
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Mapping

from services.tax.base import TaxContext, TaxResult
from services.tax.registry import register_regime


@register_regime("*")  # Catchall — letzte Resort wenn kein anderes Pattern matcht
@dataclass(frozen=True)
class GenericFlatRateRegime:
    """Pauschal-Implementierung mit 3 Flat-Werten.

    Parameter (alle in bps, default = 0):
    - wealth_tax_bps_pa: jaehrliche Vermoegenssteuer
    - dividend_tax_bps: Steuersatz auf Dividenden-Income
    - interest_tax_bps: Steuersatz auf Zins-Income (default = dividend)
    - capital_gains_tax_bps: Steuersatz auf Kursgewinne
    - pension_lumpsum_tax_bps: pauschaler Kapitalbezugssteuer-Satz

    Keine Progression, keine Sonderregeln. Maximal einfach.
    """

    id: str = "GENERIC"
    country_code: str = "XX"
    region_code: str | None = None
    display_name: str = "Generic Flat-Rate Jurisdiction"
    local_currency: str = "CHF"
    tariff_version: str = "GENERIC-v1"

    wealth_tax_bps_pa: float = 0.0
    dividend_tax_bps: float = 0.0
    interest_tax_bps: float | None = None  # None → faellt auf dividend_tax_bps zurueck
    capital_gains_tax_bps: float = 0.0
    pension_lumpsum_tax_bps: float = 0.0
    inheritance_tax_bps_default: float = 0.0

    overrides: Mapping[str, float] | None = field(default=None, compare=False)

    # ---- Capability-Flags (von Werten abgeleitet) ----

    @property
    def supports_wealth_tax(self) -> bool:
        return self.wealth_tax_bps_pa > 0

    @property
    def supports_capital_gains_tax(self) -> bool:
        return self.capital_gains_tax_bps > 0

    @property
    def supports_inheritance_tax(self) -> bool:
        return self.inheritance_tax_bps_default > 0

    # ---- Tax-Berechnungen ----

    def annual_wealth_tax(self, ctx: TaxContext) -> TaxResult:
        wealth = max(ctx.wealth_rappen, 0.0)  # keine Steuer auf negatives Vermoegen
        amount = wealth * self.wealth_tax_bps_pa / 10000.0
        return self._make_result(amount, self.wealth_tax_bps_pa, "wealth")

    def dividend_tax(
        self, ctx: TaxContext, dividend_income_rappen: float
    ) -> TaxResult:
        income = max(dividend_income_rappen, 0.0)
        amount = income * self.dividend_tax_bps / 10000.0
        return self._make_result(amount, self.dividend_tax_bps, "dividend")

    def interest_tax(
        self, ctx: TaxContext, interest_income_rappen: float
    ) -> TaxResult:
        bps = (
            self.interest_tax_bps
            if self.interest_tax_bps is not None
            else self.dividend_tax_bps
        )
        income = max(interest_income_rappen, 0.0)
        amount = income * bps / 10000.0
        return self._make_result(amount, bps, "interest")

    def capital_gains_tax(
        self,
        ctx: TaxContext,
        gains_rappen: float,
        holding_years: int,
    ) -> TaxResult:
        gains = max(gains_rappen, 0.0)
        amount = gains * self.capital_gains_tax_bps / 10000.0
        return self._make_result(amount, self.capital_gains_tax_bps, "capital_gains")

    def pension_lumpsum_tax(
        self, ctx: TaxContext, amount_rappen: float
    ) -> TaxResult:
        amount_pos = max(amount_rappen, 0.0)
        tax = amount_pos * self.pension_lumpsum_tax_bps / 10000.0
        return self._make_result(tax, self.pension_lumpsum_tax_bps, "pension_lumpsum")

    def inheritance_tax(
        self,
        ctx: TaxContext,
        amount_rappen: float,
        relation: str,
    ) -> TaxResult:
        amount_pos = max(amount_rappen, 0.0)
        tax = amount_pos * self.inheritance_tax_bps_default / 10000.0
        return self._make_result(
            tax, self.inheritance_tax_bps_default, "inheritance",
            breakdown={"relation": 0.0, "rate_bps": self.inheritance_tax_bps_default},
        )

    # ---- Validation ----

    def validate_parameters(self, params: Mapping[str, float]) -> tuple[str, ...]:
        warnings: list[str] = []
        for key, value in params.items():
            if not isinstance(value, (int, float)):
                warnings.append(f"{key}: non-numeric value '{value}' ignored")
                continue
            if value < 0:
                warnings.append(f"{key}={value}: negative tax rate is unusual")
            if "bps" in key and value > 5000:  # 50%
                warnings.append(
                    f"{key}={value} bps ({value/100:.1f}%): unusually high, "
                    "please verify"
                )
        return tuple(warnings)

    # ---- Overrides ----

    def with_overrides(self, overrides: Mapping[str, float]) -> "GenericFlatRateRegime":
        """Returns neue Instanz mit ueberschriebenen Werten.

        Nur Felder die im Regime existieren werden uebernommen — unbekannte
        Keys werden ignoriert (Berater-Tippfehler-tolerant).
        """
        valid_keys = {
            "wealth_tax_bps_pa", "dividend_tax_bps", "interest_tax_bps",
            "capital_gains_tax_bps", "pension_lumpsum_tax_bps",
            "inheritance_tax_bps_default",
        }
        applied = {k: float(v) for k, v in overrides.items() if k in valid_keys}
        if not applied:
            return self
        return replace(self, **applied, overrides=dict(overrides))

    # ---- Internal ----

    def _make_result(
        self,
        amount: float,
        bps: float,
        tax_type: str,
        breakdown: Mapping[str, float] | None = None,
    ) -> TaxResult:
        return TaxResult(
            amount_rappen=amount,
            effective_bps=float(bps),
            regime_id=self.id,
            tariff_version=self.tariff_version,
            breakdown=breakdown or {tax_type: float(bps)},
            used_overrides=dict(self.overrides) if self.overrides else None,
        )
