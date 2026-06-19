"""Tax plugin API schemas.

The schemas in this module are intentionally independent from the optimizer.
They describe a read-only tax estimate request/response contract that country
plugins can implement without touching portfolio construction code.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


MaritalStatus = Literal["single", "married", "partnership"]
CapitalGainsRealization = Literal["private", "business"]


class TaxProfileInput(BaseModel):
    """Input for a deterministic tax estimate.

    Amounts are expressed in rappen/cents of the local currency. Percentages in
    responses are expressed in basis points.
    """

    country_code: str = Field(..., min_length=2, max_length=2)
    region: str | None = Field(default=None, description="Canton/state/region code")
    year: int = Field(default=2026, ge=1900, le=2200)
    currency: str = Field(default="CHF", min_length=3, max_length=3)
    taxable_income_rappen: int = Field(default=0, ge=0)
    taxable_wealth_rappen: int = Field(default=0, ge=0)
    capital_gains_rappen: int = Field(default=0, ge=0)
    capital_gains_realization: CapitalGainsRealization = "private"
    marital_status: MaritalStatus = "single"
    religion: str | None = None
    municipality: str | None = None

    @field_validator("country_code", "currency")
    @classmethod
    def uppercase_code(cls, value: str) -> str:
        return value.upper().strip()

    @field_validator("region")
    @classmethod
    def normalize_region(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.upper().strip()
        return normalized or None


class TaxJurisdictionMetadata(BaseModel):
    """Stable plugin metadata exposed to API clients and audit logs."""

    country_code: str = Field(..., min_length=2, max_length=2)
    display_name: str
    currency: str = Field(..., min_length=3, max_length=3)
    version: str
    supported_regions: list[str] = Field(default_factory=list)
    supports_income_tax: bool = True
    supports_wealth_tax: bool = True
    supports_capital_gains_tax: bool = True

    @field_validator("country_code", "currency")
    @classmethod
    def uppercase_code(cls, value: str) -> str:
        return value.upper().strip()

    @field_validator("supported_regions")
    @classmethod
    def uppercase_regions(cls, values: list[str]) -> list[str]:
        return [value.upper().strip() for value in values if value.strip()]


class TaxEstimateResult(BaseModel):
    """Deterministic tax estimate result.

    The result can represent a full estimate or one component estimate. The
    component fields always add up to total_tax_rappen.
    """

    country_code: str
    region: str | None = None
    year: int
    currency: str = "CHF"
    income_tax_rappen: int = 0
    wealth_tax_rappen: int = 0
    capital_gains_tax_rappen: int = 0
    total_tax_rappen: int = 0
    effective_tax_bps: int = 0
    marginal_tax_bps: int = 0
    breakdown: dict[str, Any] = Field(default_factory=dict)
    assumptions: list[str] = Field(default_factory=list)
    tariff_version: str

    @model_validator(mode="after")
    def validate_total(self) -> "TaxEstimateResult":
        expected = (
            self.income_tax_rappen
            + self.wealth_tax_rappen
            + self.capital_gains_tax_rappen
        )
        if self.total_tax_rappen != expected:
            raise ValueError(
                "total_tax_rappen muss der Summe aus income/wealth/capital_gains entsprechen"
            )
        return self


class TaxJurisdictionListItem(BaseModel):
    country_code: str
    display_name: str
    currency: str
    version: str
    supported_regions: list[str] = Field(default_factory=list)

