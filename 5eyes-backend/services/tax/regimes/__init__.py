"""Tax-Regimes — pro Land/Region eine Datei.

Imports loesen @register_regime aus. Reihenfolge:
1. GenericFlatRateRegime zuerst (als '*' Catchall-Fallback)
2. Spezifischere Patterns (CH-*, DE, US-*, ...) ueberschreiben fuer
   passende IDs.

Neues Land hinzufuegen:
    1. services/tax/regimes/xx.py erstellen
    2. @register_regime('XX') Decorator
    3. Import-Zeile hier hinzufuegen
"""
from __future__ import annotations

# Generic zuerst — als Catchall-Fallback fuer alles
from services.tax.regimes import generic  # noqa: F401

# Spezifische Regimes folgen in Phase 2:
# from services.tax.regimes import ch  # noqa: F401
# from services.tax.regimes import de  # noqa: F401
# ...
