"""Reference data for tax estimate plugins.

The values in this module are deliberately versioned approximations. Exact
municipal tax calculators remain outside the core; this layer provides stable
and conservative advisory estimates until a specific country plugin is enriched
with official tables.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any


CH_PARAMETER_YEAR = 2026
CH_PARAMETER_VERSION = "CH-REF-2026-v1"


# Canton-level approximations used by the Switzerland reference plugin.
# Municipal tax is represented as multiplier_bps. When an exact municipality is
# unknown, the plugin uses the conservative region/fallback and records that
# assumption in the result.
CH_CANTON_PARAMETER_SETS: dict[str, dict[str, Any]] = {
    "ZH": {
        "display_name": "Schweiz - Zuerich",
        "income_tax_bps": 1180,
        "wealth_tax_bps": 35,
        "municipal_multiplier_bps": 10000,
        "wealth_allowance_single_rappen": 0,
        "wealth_allowance_married_rappen": 0,
    },
    "ZG": {
        "display_name": "Schweiz - Zug",
        "income_tax_bps": 720,
        "wealth_tax_bps": 15,
        "municipal_multiplier_bps": 10000,
        "wealth_allowance_single_rappen": 0,
        "wealth_allowance_married_rappen": 0,
    },
    "GE": {
        "display_name": "Schweiz - Genf",
        "income_tax_bps": 1750,
        "wealth_tax_bps": 85,
        "municipal_multiplier_bps": 10000,
        "wealth_allowance_single_rappen": 0,
        "wealth_allowance_married_rappen": 0,
    },
}


def ch_default_parameter_sets() -> dict[str, dict[str, Any]]:
    """Return a mutable copy of the built-in CH reference parameters."""
    return deepcopy(CH_CANTON_PARAMETER_SETS)


def ch_conservative_fallback_parameters() -> dict[str, Any]:
    """Return conservative CH fallback parameters for missing region data."""
    return {
        "display_name": "Schweiz - konservative Schaetzung",
        "income_tax_bps": max(
            int(params["income_tax_bps"]) for params in CH_CANTON_PARAMETER_SETS.values()
        ),
        "wealth_tax_bps": max(
            int(params["wealth_tax_bps"]) for params in CH_CANTON_PARAMETER_SETS.values()
        ),
        "municipal_multiplier_bps": 10000,
        "wealth_allowance_single_rappen": 0,
        "wealth_allowance_married_rappen": 0,
    }

