"""SCHEMA-03: CapitalMarketAssumptionCreate-Validierung (Audit 2026-06-24).

Negative Volatilitäten erzeugten in der Kovarianz-/Cholesky-Konstruktion der
Monte-Carlo NaN/komplexe Werte (stiller Fehler statt klarer 422). Diese Tests
sperren den Guard: Vola >= 0 und valid_until >= valid_from.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from schemas.allocation import CapitalMarketAssumptionCreate
from services.cma_validation import CMAValidationError, validate_runtime_cma_completeness


class _FakeCMA:
    """Duck-typed stand-in for the ORM CMA row -- CH jurisdiction, all 7
    return/volatility fields present (required by validate_runtime_cma_
    completeness's own completeness check)."""

    def __init__(self, **overrides):
        self.jurisdiction = "CH"
        self.equity_ch_return_bps = 500
        self.equity_intl_return_bps = 600
        self.bonds_chf_ig_return_bps = 100
        self.bonds_fx_hedged_return_bps = 150
        self.real_estate_ch_return_bps = 300
        self.alternatives_gold_return_bps = 200
        self.liquidity_return_bps = 50
        self.equity_ch_vol_bps = 1500
        self.equity_intl_vol_bps = 1800
        self.bonds_chf_ig_vol_bps = 400
        self.bonds_fx_hedged_vol_bps = 450
        self.real_estate_ch_vol_bps = 900
        self.alternatives_gold_vol_bps = 1200
        self.liquidity_vol_bps = 10
        for key, value in overrides.items():
            setattr(self, key, value)


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


@pytest.mark.parametrize("invalid_return", [-10_000, -20_000, True])
def test_total_loss_or_boolean_return_is_rejected(invalid_return):
    with pytest.raises(ValidationError):
        CapitalMarketAssumptionCreate(
            valid_from="2026-01-01",
            equity_ch_return_bps=invalid_return,
        )


@pytest.mark.parametrize("field", [
    "equity_em_vol_bps", "liquidity_vol_bps", "real_estate_ch_vol_bps", "bonds_hy_vol_bps",
])
def test_negative_vol_rejected(field):
    with pytest.raises(ValidationError, match="Volatilität"):
        CapitalMarketAssumptionCreate(**{"valid_from": "2026-01-01", field: -500})


def test_fat_finger_return_typo_is_rejected():
    """Kontrollrunde 2026-09-23: nur eine UNTERE Schranke war geprueft -- ein
    Tippfehler (z.B. "5000%" statt "50%" durch Prozent-vs-bps-Verwechslung)
    passierte bisher klaglos und floss unbegrenzt in jede nachfolgende
    Optimierung/Simulation ein."""
    with pytest.raises(ValidationError, match="unplausibel hoch"):
        CapitalMarketAssumptionCreate(
            valid_from="2026-01-01", equity_ch_return_bps=500_000,
        )


def test_fat_finger_vol_typo_is_rejected():
    with pytest.raises(ValidationError, match="unplausibel hoch"):
        CapitalMarketAssumptionCreate(
            valid_from="2026-01-01", equity_intl_vol_bps=500_000,
        )


def test_plausible_high_return_and_vol_still_allowed():
    cma = CapitalMarketAssumptionCreate(
        valid_from="2026-01-01", equity_em_return_bps=1200, equity_em_vol_bps=3500,
    )
    assert cma.equity_em_return_bps == 1200
    assert cma.equity_em_vol_bps == 3500


def test_runtime_completeness_rejects_fat_finger_return():
    """Kontrollrunde 2026-09-23: validate_runtime_cma_completeness (der
    tatsaechliche Live-Gate vor jedem stochastischen Lauf, siehe
    services/portfolio_engine_cma.py) hatte ebenfalls keine Obergrenze."""
    cma = _FakeCMA(equity_ch_return_bps=500_000)
    with pytest.raises(CMAValidationError, match="unplausibel hoch"):
        validate_runtime_cma_completeness(cma)


def test_runtime_completeness_rejects_fat_finger_vol():
    cma = _FakeCMA(equity_intl_vol_bps=500_000)
    with pytest.raises(CMAValidationError, match="unplausibel hoch"):
        validate_runtime_cma_completeness(cma)


def test_runtime_completeness_allows_plausible_values():
    validate_runtime_cma_completeness(_FakeCMA())


def test_valid_until_before_valid_from_rejected():
    with pytest.raises(ValidationError, match="valid_until"):
        CapitalMarketAssumptionCreate(valid_from="2030-01-01", valid_until="2026-01-01")


def test_valid_until_equal_or_after_ok():
    cma = CapitalMarketAssumptionCreate(valid_from="2026-01-01", valid_until="2030-01-01")
    assert cma.valid_until == "2030-01-01"
