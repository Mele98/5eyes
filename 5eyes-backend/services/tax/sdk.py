"""5eyes Tax-Plugin-SDK — Public API fuer Dritt-Anbieter.

Dieses Modul ist die OEFFENTLICHE Schnittstelle fuer externe
Entwickler, die ein neues Land/eine neue Steuer-Jurisdiction zu
5eyes hinzufuegen wollen, ohne den Core-Code zu modifizieren.

# Wer dieses Modul nutzt
- Inhouse-Entwickler die ein neues Land hinzufuegen
- Externe Berater/Steuerexperten die ein Land als pip-Paket liefern
- Compliance-Auditoren die die Vollstaendigkeit pruefen

# Stabilitaets-Garantie
Symbole die hier exportiert sind, bilden den `SDK_PUBLIC_API`. Sie
sind versionsgebunden via `TAX_SDK_VERSION` (semver). Breaking-Changes
erhoehen die Major-Version + Migration-Notes in `docs/architecture/
tax-plugin-sdk.md`.

# Quick-Start fuer Drittanbieter
    from services.tax.sdk import (
        TaxRegime, TaxContext, TaxResult,
        register_regime, ConformanceContract,
    )

    @register_regime("VN")  # Vietnam-Pattern
    class VNTaxRegime:
        id = "VN"
        country_code = "VN"
        # ... siehe TaxRegime-Protocol fuer alle Methoden

    # Lokales Smoke-Test
    report = ConformanceContract().run(VNTaxRegime())
    assert report.passed

# Distribution als pip-Paket
    # setup.cfg / pyproject.toml:
    # [options.entry_points]
    # 5eyes.tax_regime =
    #     vn = my_5eyes_vn_tax:VNTaxRegime
    # 5eyes ruft beim Boot discover_external_regimes() auf und
    # findet alle eingetragenen Entry-Points.
"""
from __future__ import annotations

from services.tax.base import (
    TaxContext,
    TaxRegime,
    TaxResult,
)
from services.tax.conformance import (
    ConformanceContract,
    ConformanceReport,
    ConformanceRequirement,
)
from services.tax.discovery import (
    EXTERNAL_REGIME_ENTRY_POINT_GROUP,
    DiscoveryResult,
    discover_external_regimes,
)
from services.tax.registry import (
    list_registered_patterns,
    register_regime,
    resolve_regime_class,
)

TAX_SDK_VERSION = "1.0.0"
"""Semver-Version der oeffentlichen Tax-SDK-Schnittstelle.

Breaking-Changes (Protocol-Methods, Entry-Point-Group):
  -> Major-Version-Bump + Migration-Doc in docs/architecture/.
Neue optionale Methoden:
  -> Minor-Version-Bump, backwards-compatible per Default-Impl.
Bugfixes/Doku:
  -> Patch-Version-Bump.
"""

TAX_SDK_CONFORMANCE_CONTRACT_VERSION = "1.0.0"
"""Version des Conformance-Vertrags. Wenn neue Pflicht-Tests ergaenzt
werden, steigt diese Version. Dritt-Anbieter koennen
TAX_SDK_CONFORMANCE_CONTRACT_VERSION pinnen um Test-Regression-Schutz
zu haben."""


SDK_PUBLIC_API = (
    # Protocol / Datentypen
    "TaxRegime",
    "TaxContext",
    "TaxResult",
    # Registry
    "register_regime",
    "resolve_regime_class",
    "list_registered_patterns",
    # Discovery
    "discover_external_regimes",
    "DiscoveryResult",
    "EXTERNAL_REGIME_ENTRY_POINT_GROUP",
    # Conformance
    "ConformanceContract",
    "ConformanceReport",
    "ConformanceRequirement",
    # Versions
    "TAX_SDK_VERSION",
    "TAX_SDK_CONFORMANCE_CONTRACT_VERSION",
)
"""Die oeffentliche SDK-Oberflaeche. Drift-Test (test_sdk_public_api.py)
schuetzt vor versehentlichen Removals."""


__all__ = list(SDK_PUBLIC_API)
