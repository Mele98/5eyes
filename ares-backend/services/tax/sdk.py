"""Ares Tax-Plugin-SDK — Public API fuer Dritt-Anbieter.

Dieses Modul ist die OEFFENTLICHE Schnittstelle fuer externe
Entwickler, die ein neues Land/eine neue Steuer-Jurisdiction zu
Ares hinzufuegen wollen, ohne den Core-Code zu modifizieren.

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
    # ares.tax_regime =
    #     vn = my_ares_vn_tax:VNTaxRegime
    # Ares ruft beim Boot (services.tax.plugin_inventory) die Discovery
    # auf und findet alle eingetragenen Entry-Points.
    # Ab SDK 2.0.0 Pflicht im geladenen Plugin-Objekt (Modul oder Klasse):
    #     TAX_SDK_TARGET_VERSION = "2.0.0"
"""
from __future__ import annotations

from services.tax.base import (
    TaxContext,
    TaxJurisdiction,
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
    TaxJurisdictionNotFound,
    discover_builtin_jurisdictions,
    get_jurisdiction,
    list_jurisdictions,
    list_registered_patterns,
    register_jurisdiction,
    register_regime,
    resolve_regime_class,
)

TAX_SDK_VERSION = "2.0.0"
"""Semver-Version der oeffentlichen Tax-SDK-Schnittstelle.

2.0.0 (W2-804-01): Breaking — Entry-Point-Gruppe ist `ares.tax_regime`,
die fruehere Gruppe wird ohne Alias nicht mehr gelesen. Plugins muessen
`TAX_SDK_TARGET_VERSION` mit Major 2 deklarieren, sonst lehnt
`services.tax.plugin_inventory` sie fail-closed ab.

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
    "TaxJurisdiction",
    "TaxContext",
    "TaxResult",
    # Registry
    "register_regime",
    "register_jurisdiction",
    "resolve_regime_class",
    "get_jurisdiction",
    "list_jurisdictions",
    "TaxJurisdictionNotFound",
    "list_registered_patterns",
    "discover_builtin_jurisdictions",
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
