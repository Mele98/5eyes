"""Drift-Tests fuer das oeffentliche Tax-SDK.

Wenn ein Symbol aus SDK_PUBLIC_API entfernt wird, brechen externe
Dritt-Anbieter-Pakete. Diese Tests pinnen den Vertrag — bei Aenderung
MUSS der Test-Update Teil des PRs sein + Semver-Bump in
TAX_SDK_VERSION + Migration-Doc.

Spec: U-32 Tax-Plugin-SDK (2026-06-06).
"""
from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def test_sdk_module_importable():
    """services.tax.sdk muss importierbar sein — sonst keine externe Nutzung."""
    import services.tax.sdk  # noqa: F401


def test_sdk_exposes_all_public_symbols():
    """Drift-Test: alle SDK_PUBLIC_API-Eintraege sind im Modul vorhanden."""
    from services.tax import sdk
    for symbol in sdk.SDK_PUBLIC_API:
        assert hasattr(sdk, symbol), (
            f"SDK_PUBLIC_API listet '{symbol}' aber Symbol nicht im sdk-Modul. "
            "Beim Entfernen MUSS Major-Version-Bump erfolgen."
        )


def test_sdk_version_is_semver():
    """TAX_SDK_VERSION muss valider Semver-String sein."""
    import re
    from services.tax import sdk
    assert re.match(r"^\d+\.\d+\.\d+$", sdk.TAX_SDK_VERSION), (
        f"TAX_SDK_VERSION '{sdk.TAX_SDK_VERSION}' ist kein Semver"
    )


def test_sdk_conformance_version_is_semver():
    """TAX_SDK_CONFORMANCE_CONTRACT_VERSION muss Semver sein."""
    import re
    from services.tax import sdk
    assert re.match(r"^\d+\.\d+\.\d+$", sdk.TAX_SDK_CONFORMANCE_CONTRACT_VERSION)


def test_sdk_protocol_and_types_re_exported():
    """Drittanbieter sollen `from services.tax.sdk import ...` machen koennen."""
    from services.tax.sdk import TaxContext, TaxRegime, TaxResult
    assert TaxContext is not None
    assert TaxRegime is not None
    assert TaxResult is not None


def test_sdk_register_regime_re_exported():
    """Decorator ueber den Plugins sich registrieren — muss exportiert sein."""
    from services.tax.sdk import register_regime
    assert callable(register_regime)


def test_sdk_conformance_contract_re_exported():
    """Drittanbieter brauchen den ConformanceContract fuer ihr CI."""
    from services.tax.sdk import ConformanceContract, ConformanceReport, ConformanceRequirement
    assert ConformanceContract is not None
    assert ConformanceReport is not None
    assert ConformanceRequirement is not None


def test_sdk_discovery_helpers_re_exported():
    """Entry-Point-Discovery + Group-Konstante muessen exportiert sein."""
    from services.tax.sdk import (
        EXTERNAL_REGIME_ENTRY_POINT_GROUP,
        DiscoveryResult,
        discover_external_regimes,
    )
    assert EXTERNAL_REGIME_ENTRY_POINT_GROUP == "5eyes.tax_regime"
    assert callable(discover_external_regimes)
    assert DiscoveryResult is not None


def test_sdk_all_matches_public_api_tuple():
    """__all__ muss SDK_PUBLIC_API entsprechen — sonst inkonsistente Doku."""
    from services.tax import sdk
    assert tuple(sdk.__all__) == tuple(sdk.SDK_PUBLIC_API)
