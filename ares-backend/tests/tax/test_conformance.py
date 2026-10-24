"""Conformance-Tests fuer Built-in Tax-Regimes.

Jede Regime-Implementierung (Generic, CH, DE) muss den
ConformanceContract bestehen. Wenn ein neuer Regime registriert wird
und diesen Test failed -> NICHT mergen.

Auch ein Drittanbieter kann das gleiche Pattern verwenden:
    from services.tax.sdk import ConformanceContract
    def test_my_regime():
        report = ConformanceContract().run(MyRegime())
        assert report.passed, report.format_failures()
"""
from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def test_generic_regime_passes_conformance():
    from services.tax.regimes.generic import GenericFlatRateRegime
    from services.tax.sdk import ConformanceContract

    regime = GenericFlatRateRegime(
        id="TEST-XX",
        country_code="XX",
        local_currency="EUR",
        wealth_tax_bps_pa=50.0,
        dividend_tax_bps=2500.0,
        capital_gains_tax_bps=2500.0,
    )
    report = ConformanceContract().run(regime)
    assert report.passed, report.format_failures()


def test_ch_regime_passes_conformance():
    from services.tax.registry import resolve_regime_class
    from services.tax.sdk import ConformanceContract

    # CH-ZH ist der Default-CH-Kanton im Sprint-3-Setup
    cls = resolve_regime_class("CH-ZH")
    regime = cls() if not hasattr(cls, "for_canton") else cls.for_canton("ZH")
    report = ConformanceContract().run(regime)
    assert report.passed, report.format_failures()


def test_de_regime_passes_conformance():
    from services.tax.registry import resolve_regime_class
    from services.tax.sdk import ConformanceContract

    cls = resolve_regime_class("DE")
    regime = cls()
    report = ConformanceContract().run(regime)
    assert report.passed, report.format_failures()


def test_failing_regime_fails_conformance():
    """Negativ-Test: ein bewusst kaputtes Regime MUSS scheitern."""
    from services.tax.base import TaxContext, TaxResult
    from services.tax.sdk import ConformanceContract

    class BrokenRegime:
        id = "BROKEN"
        country_code = "xx"  # lowercase — verletzt R002
        region_code = None
        display_name = "Broken Test"
        local_currency = "CHF"
        supports_wealth_tax = True
        supports_capital_gains_tax = False
        supports_inheritance_tax = False

        def annual_wealth_tax(self, ctx):
            return TaxResult(
                amount_rappen=-100.0,  # negativ — verletzt R005
                effective_bps=0,
                regime_id=self.id,
                tariff_version="BROKEN-v1",
            )

        def dividend_tax(self, ctx, dividend_income_rappen):
            return TaxResult(
                amount_rappen=0, effective_bps=0,
                regime_id=self.id, tariff_version="BROKEN-v1",
            )

        def interest_tax(self, ctx, interest_income_rappen):
            return self.dividend_tax(ctx, interest_income_rappen)

        def capital_gains_tax(self, ctx, gains_rappen, holding_years):
            return TaxResult(
                amount_rappen=0, effective_bps=0,
                regime_id=self.id, tariff_version="BROKEN-v1",
            )

        def pension_lumpsum_tax(self, ctx, amount_rappen):
            return TaxResult(
                amount_rappen=0, effective_bps=0,
                regime_id=self.id, tariff_version="BROKEN-v1",
            )

        def inheritance_tax(self, ctx, amount_rappen, relation):
            return TaxResult(
                amount_rappen=0, effective_bps=0,
                regime_id=self.id, tariff_version="BROKEN-v1",
            )

        def validate_parameters(self, params):
            return ()

        def with_overrides(self, overrides):
            return self

    report = ConformanceContract().run(BrokenRegime())
    assert not report.passed
    failed_ids = {rid for rid, _ in report.failed_requirements}
    assert "R002-country" in failed_ids
    assert "R005-wealth-nonneg" in failed_ids


def test_conformance_report_has_contract_version():
    """Externe CI muessen die Vertrags-Version aufzeichnen koennen."""
    from services.tax.regimes.generic import GenericFlatRateRegime
    from services.tax.sdk import ConformanceContract

    contract = ConformanceContract()
    report = contract.run(GenericFlatRateRegime())
    assert report.contract_version == contract.VERSION


def test_conformance_format_failures_human_readable():
    """format_failures() muss menschen-lesbaren Output liefern."""
    from services.tax.sdk import ConformanceReport

    report = ConformanceReport(
        regime_id="X",
        contract_version="1.0.0",
        failed_requirements=[("R001-id", "id leer")],
        warnings=[("R010-tariff-version", "tariff_version leer")],
    )
    text = report.format_failures()
    assert "X" in text
    assert "R001-id" in text
    assert "R010-tariff-version" in text
    assert "FAIL" in text
    assert "WARN" in text
