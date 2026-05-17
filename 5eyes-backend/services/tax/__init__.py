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
    TaxContext,
    TaxRegime,
    TaxResult,
)
from services.tax.registry import (
    REGIME_REGISTRY,
    register_regime,
    resolve_regime_class,
)

# Auto-Import aller Regimes loest @register_regime aus.
# Reihenfolge irrelevant — Registry sammelt einfach alle.
import services.tax.regimes  # noqa: F401, E402

__all__ = [
    "TaxContext",
    "TaxRegime",
    "TaxResult",
    "REGIME_REGISTRY",
    "register_regime",
    "resolve_regime_class",
]
