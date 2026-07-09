"""Switzerland reference tax estimate plugin.

This is a deterministic advisory estimate, not a municipal tax filing engine.
It combines a simplified direct-federal income tariff with canton-level
parameter sets. Missing or unknown regions fall back to conservative parameters
and are disclosed in assumptions.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Mapping

from schemas.tax import TaxEstimateResult, TaxJurisdictionMetadata, TaxProfileInput
from services.tax.reference_data import (
    CH_PARAMETER_VERSION,
    CH_PARAMETER_YEAR,
    ch_conservative_fallback_parameters,
    ch_default_parameter_sets,
)
from services.tax.registry import register_jurisdiction


_SINGLE_FEDERAL_BRACKETS: tuple[tuple[int, int], ...] = (
    (14800, 0),
    (32200, 77),
    (42200, 88),
    (56200, 264),
    (73800, 297),
    (79700, 594),
    (105500, 660),
    (137200, 880),
    (179400, 1100),
    (10**12, 1150),
)

_MARRIED_FEDERAL_BRACKETS: tuple[tuple[int, int], ...] = tuple(
    (upper * 2 if upper < 10**12 else upper, bps)
    for upper, bps in _SINGLE_FEDERAL_BRACKETS
)


def _round_rappen(value: float) -> int:
    return int(round(value))


def _bps_amount(basis_rappen: int, bps: int) -> int:
    return _round_rappen(basis_rappen * bps / 10000)


def _progressive_tax_rappen(
    taxable_income_rappen: int,
    brackets: tuple[tuple[int, int], ...],
) -> tuple[int, int]:
    income_chf = taxable_income_rappen / 100
    lower = 0.0
    tax_chf = 0.0
    marginal_bps = 0
    for upper_chf, rate_bps in brackets:
        if income_chf <= lower:
            break
        taxable_slice = min(income_chf, float(upper_chf)) - lower
        if taxable_slice > 0:
            tax_chf += taxable_slice * rate_bps / 10000
            marginal_bps = rate_bps
        lower = float(upper_chf)
    return _round_rappen(tax_chf * 100), marginal_bps


def _effective_bps(tax_rappen: int, basis_rappen: int) -> int:
    if basis_rappen <= 0:
        return 0
    return _round_rappen(tax_rappen * 10000 / basis_rappen)


def _merge_component_assumptions(*results: TaxEstimateResult) -> list[str]:
    seen: set[str] = set()
    assumptions: list[str] = []
    for result in results:
        for assumption in result.assumptions:
            if assumption not in seen:
                seen.add(assumption)
                assumptions.append(assumption)
    return assumptions


@register_jurisdiction
@dataclass(frozen=True)
class SwissTaxJurisdiction:
    """Country-level Switzerland tax estimate plugin."""

    parameter_sets: Mapping[str, Mapping[str, Any]] = field(
        default_factory=ch_default_parameter_sets
    )
    version: str = CH_PARAMETER_VERSION

    @property
    def metadata(self) -> TaxJurisdictionMetadata:
        return TaxJurisdictionMetadata(
            country_code="CH",
            display_name="Schweiz",
            currency="CHF",
            version=self.version,
            supported_regions=sorted(self.parameter_sets.keys()),
            supports_income_tax=True,
            supports_wealth_tax=True,
            supports_capital_gains_tax=True,
        )

    def with_parameter_sets(
        self,
        parameter_sets: Mapping[str, Mapping[str, Any]],
    ) -> "SwissTaxJurisdiction":
        return replace(self, parameter_sets=parameter_sets)

    def _params_for(self, profile: TaxProfileInput) -> tuple[str, Mapping[str, Any], list[str]]:
        assumptions = [
            "Schweizer Referenzschaetzung: direkte Bundessteuer vereinfacht, Kanton/Gemeinde ueber Parameter.",
            f"Parameterjahr {CH_PARAMETER_YEAR}, Version {self.version}.",
        ]
        region = (profile.region or "").upper().strip()
        if region and region in self.parameter_sets:
            return region, self.parameter_sets[region], assumptions

        fallback = ch_conservative_fallback_parameters()
        if region:
            assumptions.append(
                f"Region '{region}' nicht parametrisiert; konservativer CH-Fallback verwendet."
            )
        else:
            assumptions.append("Keine Region angegeben; konservativer CH-Fallback verwendet.")
        return "CH-CONSERVATIVE", fallback, assumptions

    def estimate_income_tax(self, profile: TaxProfileInput) -> TaxEstimateResult:
        region, params, assumptions = self._params_for(profile)
        brackets = (
            _MARRIED_FEDERAL_BRACKETS
            if profile.marital_status in {"married", "partnership"}
            else _SINGLE_FEDERAL_BRACKETS
        )
        federal_tax, federal_marginal_bps = _progressive_tax_rappen(
            profile.taxable_income_rappen,
            brackets,
        )
        cantonal_base_bps = int(params["income_tax_bps"])
        municipal_multiplier_bps = int(params.get("municipal_multiplier_bps", 10000))
        cantonal_bps = _round_rappen(cantonal_base_bps * municipal_multiplier_bps / 10000)
        cantonal_tax = _bps_amount(profile.taxable_income_rappen, cantonal_bps)
        income_tax = federal_tax + cantonal_tax
        return TaxEstimateResult(
            country_code="CH",
            region=region,
            year=profile.year,
            currency="CHF",
            income_tax_rappen=income_tax,
            total_tax_rappen=income_tax,
            effective_tax_bps=_effective_bps(income_tax, profile.taxable_income_rappen),
            marginal_tax_bps=federal_marginal_bps + cantonal_bps,
            breakdown={
                "direct_federal_tax_rappen": federal_tax,
                "cantonal_municipal_income_tax_rappen": cantonal_tax,
                "cantonal_income_bps": cantonal_bps,
            },
            assumptions=assumptions,
            tariff_version=self.version,
        )

    def estimate_wealth_tax(self, profile: TaxProfileInput) -> TaxEstimateResult:
        region, params, assumptions = self._params_for(profile)
        allowance_key = (
            "wealth_allowance_married_rappen"
            if profile.marital_status in {"married", "partnership"}
            else "wealth_allowance_single_rappen"
        )
        taxable_wealth = max(
            0,
            profile.taxable_wealth_rappen - int(params.get(allowance_key, 0)),
        )
        wealth_bps = int(params["wealth_tax_bps"])
        wealth_tax = _bps_amount(taxable_wealth, wealth_bps)
        return TaxEstimateResult(
            country_code="CH",
            region=region,
            year=profile.year,
            currency="CHF",
            wealth_tax_rappen=wealth_tax,
            total_tax_rappen=wealth_tax,
            effective_tax_bps=_effective_bps(wealth_tax, profile.taxable_wealth_rappen),
            marginal_tax_bps=wealth_bps,
            breakdown={
                "taxable_wealth_after_allowance_rappen": taxable_wealth,
                "wealth_tax_bps": wealth_bps,
            },
            assumptions=assumptions,
            tariff_version=self.version,
        )

    def estimate_capital_gains(self, profile: TaxProfileInput) -> TaxEstimateResult:
        region, _params, assumptions = self._params_for(profile)
        if profile.capital_gains_realization == "private":
            assumptions.append(
                "Private Kapitalgewinne werden in der Schweiz im Regelfall nicht besteuert; gewerbsmaessiger Handel bleibt vorbehalten."
            )
            return TaxEstimateResult(
                country_code="CH",
                region=region,
                year=profile.year,
                currency="CHF",
                capital_gains_tax_rappen=0,
                total_tax_rappen=0,
                effective_tax_bps=0,
                marginal_tax_bps=0,
                breakdown={"capital_gains_realization": "private"},
                assumptions=assumptions,
                tariff_version=self.version,
            )

        baseline = self.estimate_income_tax(profile)
        profile_with_gains = profile.model_copy(
            update={
                "taxable_income_rappen": (
                    profile.taxable_income_rappen + profile.capital_gains_rappen
                )
            }
        )
        with_gains = self.estimate_income_tax(profile_with_gains)
        capital_gains_tax = max(0, with_gains.income_tax_rappen - baseline.income_tax_rappen)
        assumptions.append(
            "Kapitalgewinne als gewerbsmaessig markiert; konservativ als Einkommen besteuert."
        )
        return TaxEstimateResult(
            country_code="CH",
            region=region,
            year=profile.year,
            currency="CHF",
            capital_gains_tax_rappen=capital_gains_tax,
            total_tax_rappen=capital_gains_tax,
            effective_tax_bps=_effective_bps(capital_gains_tax, profile.capital_gains_rappen),
            marginal_tax_bps=with_gains.marginal_tax_bps,
            breakdown={
                "capital_gains_realization": "business",
                "income_tax_without_gains_rappen": baseline.income_tax_rappen,
                "income_tax_with_gains_rappen": with_gains.income_tax_rappen,
            },
            assumptions=assumptions,
            tariff_version=self.version,
        )

    def estimate(self, profile: TaxProfileInput) -> TaxEstimateResult:
        income = self.estimate_income_tax(profile)
        wealth = self.estimate_wealth_tax(profile)
        gains = self.estimate_capital_gains(profile)
        total = (
            income.income_tax_rappen
            + wealth.wealth_tax_rappen
            + gains.capital_gains_tax_rappen
        )
        total_basis = (
            profile.taxable_income_rappen
            + profile.taxable_wealth_rappen
            + profile.capital_gains_rappen
        )
        return TaxEstimateResult(
            country_code="CH",
            region=income.region,
            year=profile.year,
            currency="CHF",
            income_tax_rappen=income.income_tax_rappen,
            wealth_tax_rappen=wealth.wealth_tax_rappen,
            capital_gains_tax_rappen=gains.capital_gains_tax_rappen,
            total_tax_rappen=total,
            effective_tax_bps=_effective_bps(total, total_basis),
            marginal_tax_bps=max(
                income.marginal_tax_bps,
                wealth.marginal_tax_bps,
                gains.marginal_tax_bps,
            ),
            breakdown={
                "income": income.breakdown,
                "wealth": wealth.breakdown,
                "capital_gains": gains.breakdown,
            },
            assumptions=_merge_component_assumptions(income, wealth, gains),
            tariff_version=self.version,
        )

