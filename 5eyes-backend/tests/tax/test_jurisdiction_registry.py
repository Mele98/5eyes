from __future__ import annotations

import pytest

from schemas.tax import TaxEstimateResult, TaxJurisdictionMetadata, TaxProfileInput
from services.tax.registry import (
    JURISDICTION_REGISTRY,
    TaxJurisdictionNotFound,
    clear_jurisdiction_registry,
    get_jurisdiction,
    list_jurisdictions,
    register_jurisdiction,
)


class _DummyJurisdiction:
    @property
    def metadata(self) -> TaxJurisdictionMetadata:
        return TaxJurisdictionMetadata(
            country_code="ZZ",
            display_name="Testland",
            currency="CHF",
            version="test-v1",
        )

    def _result(self, profile: TaxProfileInput) -> TaxEstimateResult:
        return TaxEstimateResult(
            country_code=profile.country_code,
            region=profile.region,
            year=profile.year,
            currency=profile.currency,
            total_tax_rappen=0,
            tariff_version="test-v1",
        )

    def estimate_income_tax(self, profile: TaxProfileInput) -> TaxEstimateResult:
        return self._result(profile)

    def estimate_wealth_tax(self, profile: TaxProfileInput) -> TaxEstimateResult:
        return self._result(profile)

    def estimate_capital_gains(self, profile: TaxProfileInput) -> TaxEstimateResult:
        return self._result(profile)

    def estimate(self, profile: TaxProfileInput) -> TaxEstimateResult:
        return self._result(profile)


def test_register_jurisdiction_roundtrip():
    original = dict(JURISDICTION_REGISTRY)
    clear_jurisdiction_registry()
    try:
        register_jurisdiction(_DummyJurisdiction())
        assert get_jurisdiction("zz").metadata.country_code == "ZZ"
        assert [j.metadata.country_code for j in list_jurisdictions()] == ["ZZ"]
    finally:
        clear_jurisdiction_registry()
        JURISDICTION_REGISTRY.update(original)


def test_register_jurisdiction_accepts_class():
    original = dict(JURISDICTION_REGISTRY)
    clear_jurisdiction_registry()
    try:
        returned = register_jurisdiction(_DummyJurisdiction)
        assert returned is _DummyJurisdiction
        assert get_jurisdiction("ZZ").metadata.display_name == "Testland"
    finally:
        clear_jurisdiction_registry()
        JURISDICTION_REGISTRY.update(original)


def test_unknown_country_raises_clear_error():
    original = dict(JURISDICTION_REGISTRY)
    clear_jurisdiction_registry()
    try:
        with pytest.raises(TaxJurisdictionNotFound) as exc:
            get_jurisdiction("NO")
        assert "NO" in str(exc.value)
    finally:
        clear_jurisdiction_registry()
        JURISDICTION_REGISTRY.update(original)
