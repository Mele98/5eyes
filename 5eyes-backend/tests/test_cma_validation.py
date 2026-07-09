"""SCHEMA-03: CapitalMarketAssumptionCreate-Validierung (Audit 2026-06-24).

Negative Volatilitäten erzeugten in der Kovarianz-/Cholesky-Konstruktion der
Monte-Carlo NaN/komplexe Werte (stiller Fehler statt klarer 422). Diese Tests
sperren den Guard: Vola >= 0 und valid_until >= valid_from.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from schemas.allocation import CapitalMarketAssumptionCreate


def test_minimal_valid_cma_ok():
    cma = CapitalMarketAssumptionCreate(valid_from="2026-01-01")
    assert cma.valid_from == "2026-01-01"


def test_positive_vol_ok():
    cma = CapitalMarketAssumptionCreate(
        valid_from="2026-01-01", equity_intl_vol_bps=1800, bonds_chf_ig_vol_bps=400,
    )
    assert cma.equity_intl_vol_bps == 1800


def test_negative_return_is_allowed():
    # Returns DÜRFEN negativ sein (z.B. negativer erwarteter Realertrag).
    cma = CapitalMarketAssumptionCreate(valid_from="2026-01-01", bonds_chf_ig_return_bps=-50)
    assert cma.bonds_chf_ig_return_bps == -50


@pytest.mark.parametrize("field", [
    "equity_em_vol_bps", "liquidity_vol_bps", "real_estate_ch_vol_bps", "bonds_hy_vol_bps",
])
def test_negative_vol_rejected(field):
    with pytest.raises(ValidationError, match="Volatilität"):
        CapitalMarketAssumptionCreate(**{"valid_from": "2026-01-01", field: -500})


def test_valid_until_before_valid_from_rejected():
    with pytest.raises(ValidationError, match="valid_until"):
        CapitalMarketAssumptionCreate(valid_from="2030-01-01", valid_until="2026-01-01")


def test_valid_until_equal_or_after_ok():
    cma = CapitalMarketAssumptionCreate(valid_from="2026-01-01", valid_until="2030-01-01")
    assert cma.valid_until == "2030-01-01"
