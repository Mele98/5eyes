"""Thin after-tax return adapter for future optimizer integration.

No optimizer imports live here. The optimizer can call this pure function in a
later sprint (#90) once the objective needs after-tax return estimates.
"""
from __future__ import annotations

from dataclasses import dataclass

from schemas.tax import TaxProfileInput
from services.tax.registry import discover_builtin_jurisdictions, get_jurisdiction


@dataclass(frozen=True)
class AfterTaxReturnEstimate:
    country_code: str
    region: str | None
    gross_return_bps: int
    after_tax_return_bps: int
    estimated_tax_drag_bps: int
    gross_gain_rappen: int
    tax_rappen: int
    assumptions: tuple[str, ...]


def _round_bps(numerator_rappen: int, denominator_rappen: int) -> int:
    if denominator_rappen <= 0:
        return 0
    return int(round(numerator_rappen * 10000 / denominator_rappen))


def get_after_tax_return(
    profile: TaxProfileInput,
    *,
    gross_return_bps: int,
    return_base_rappen: int,
) -> AfterTaxReturnEstimate:
    """Estimate after-tax return for a single-period gross return.

    Current scope: realized capital-gains tax. Income/dividend tax hooks can be
    layered on top once the optimizer supplies return decomposition.
    """
    discover_builtin_jurisdictions()
    gross_gain_rappen = max(0, int(round(return_base_rappen * gross_return_bps / 10000)))
    if return_base_rappen <= 0 or gross_gain_rappen <= 0:
        return AfterTaxReturnEstimate(
            country_code=profile.country_code,
            region=profile.region,
            gross_return_bps=gross_return_bps,
            after_tax_return_bps=gross_return_bps,
            estimated_tax_drag_bps=0,
            gross_gain_rappen=gross_gain_rappen,
            tax_rappen=0,
            assumptions=(
                "Kein positiver Realisationsgewinn; keine Kapitalgewinnsteuer im Adapter.",
            ),
        )

    jurisdiction = get_jurisdiction(profile.country_code)
    estimate_profile = profile.model_copy(update={"capital_gains_rappen": gross_gain_rappen})
    tax_result = jurisdiction.estimate_capital_gains(estimate_profile)
    tax_drag_bps = _round_bps(tax_result.capital_gains_tax_rappen, return_base_rappen)
    return AfterTaxReturnEstimate(
        country_code=profile.country_code,
        region=tax_result.region or profile.region,
        gross_return_bps=gross_return_bps,
        after_tax_return_bps=gross_return_bps - tax_drag_bps,
        estimated_tax_drag_bps=tax_drag_bps,
        gross_gain_rappen=gross_gain_rappen,
        tax_rappen=tax_result.capital_gains_tax_rappen,
        assumptions=tuple(tax_result.assumptions)
        + (
            "After-tax Adapter beruecksichtigt aktuell realisierte Kapitalgewinne; Dividenden/Zinsen folgen mit Return-Decomposition.",
        ),
    )

