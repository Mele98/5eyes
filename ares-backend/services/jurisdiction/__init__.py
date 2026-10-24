"""WP-Resolver (Home-Bias/CMA-Parametrisierung pro Jurisdiktion, 2026-07-30):
Freistehende Resolver-Bausteine fuer Jurisdiktions-Aufloesung.

Dieses Package wird bewusst NIRGENDS aus services/portfolio_engine.py oder
services/cost_disclosure.py aufgerufen -- das Wiring in die bestehende
Engine ist ein spaeteres, noch nicht freigegebenes Arbeitspaket (WP2), das
exklusiven Schreibzugriff auf portfolio_engine.py braucht. Siehe
services/jurisdiction/resolve.py und services/jurisdiction/provisional_gate.py
fuer die einzelnen Bausteine.
"""
from services.jurisdiction.exceptions import (
    JurisdictionNotApprovedError,
    JurisdictionReferenceDataMissingError,
)
from services.jurisdiction.resolve import (
    resolve_building_blocks_for_jurisdiction,
    resolve_cma_for_jurisdiction,
    resolve_mandate_jurisdiction,
)
from services.jurisdiction.provisional_gate import assert_jurisdiction_ready

__all__ = [
    "JurisdictionNotApprovedError",
    "JurisdictionReferenceDataMissingError",
    "resolve_building_blocks_for_jurisdiction",
    "resolve_cma_for_jurisdiction",
    "resolve_mandate_jurisdiction",
    "assert_jurisdiction_ready",
]
