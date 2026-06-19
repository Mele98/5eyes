"""Tax-Plugin-System fuer 5eyes — WM-grade, weltweit.

Strategy + Registry Pattern:
- TaxRegime: abstrakte Basis-Klasse (Protocol)
- @register_regime: Plugin-Decorator
- resolve_regime: Lookup nach Jurisdiction-ID

Neue Laender werden in services/tax/regimes/ als eigene Module hinzugefuegt
und registrieren sich beim Import automatisch.

Engine-Integration: simulate_wealth_paths(tax_regime=...) bleibt
steuer-agnostisch — ruft nur regime.*_tax() auf.
"""
from __future__ import annotations

from services.tax.base import (
    TaxJurisdiction,
    TaxContext,
    TaxRegime,
    TaxResult,
)
from services.tax.registry import (
    JURISDICTION_REGISTRY,
    REGIME_REGISTRY,
    TaxJurisdictionNotFound,
    discover_builtin_jurisdictions,
    get_jurisdiction,
    list_jurisdictions,
    register_jurisdiction,
    register_regime,
    resolve_regime_class,
)

# Auto-Import aller Regimes loest @register_regime aus.
# Reihenfolge irrelevant — Registry sammelt einfach alle.
import services.tax.regimes  # noqa: F401, E402

__all__ = [
    "TaxContext",
    "TaxJurisdiction",
    "TaxRegime",
    "TaxResult",
    "JURISDICTION_REGISTRY",
    "REGIME_REGISTRY",
    "TaxJurisdictionNotFound",
    "discover_builtin_jurisdictions",
    "get_jurisdiction",
    "list_jurisdictions",
    "register_jurisdiction",
    "register_regime",
    "resolve_regime_class",
]
