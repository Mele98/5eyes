"""Backend-Validierungs-Haertung (Frontend-Audit 2026-07-10).

Drei Lücken, die klar-invalide Daten bis in den Plan liessen (FE hatte keinen Guard,
Backend auch nicht) -> jetzt schema-seitig abgewiesen (schuetzt UI UND API):
  #1 Cashflow amount_rappen < 0 (Vorzeichen-Kippen in der Projektion)
  #2 Ziel-Zielbetrag/-rendite <= 0 (verzerrt Zielerreichung/MC)
  #3 Band-Override negativ / >100% / min>max (korrumpiert den Optimizer)
"""
from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import pytest
from pydantic import ValidationError

from schemas.allocation import AllocationBandOverridePayload
from schemas.wealth import CashflowCreate, GoalCreate


# --- #1 Cashflow-Betrag ---------------------------------------------------

def test_cashflow_negative_amount_rejected():
    with pytest.raises(ValidationError):
        CashflowCreate(cashflow_type="Income", label="Lohn", amount_rappen=-5000)


def test_cashflow_positive_amount_ok():
    cf = CashflowCreate(cashflow_type="Income", label="Lohn", amount_rappen=12_000_00)
    assert cf.amount_rappen == 12_000_00


# --- #2 Ziel-Zielbetrag/-rendite ------------------------------------------

def _wealth_goal(**over):
    base = dict(goal_family="Vermögen", goal_type="Vermögensziel", label="Haus",
                rank=1, target_wealth_rappen=500_000_00, horizon_years=10)
    base.update(over)
    return GoalCreate(**base)


def test_goal_negative_wealth_target_rejected():
    with pytest.raises(ValidationError):
        _wealth_goal(target_wealth_rappen=-100_00)


def test_goal_zero_wealth_target_rejected():
    with pytest.raises(ValidationError):
        _wealth_goal(target_wealth_rappen=0)


def test_goal_positive_wealth_target_ok():
    assert _wealth_goal().target_wealth_rappen == 500_000_00


# Hinweis: die Positivitaet von target_return_bps (Renditeziel) wird auf ROUTER-Ebene
# erzwungen ("positive Zielrendite", test_mandate_api_contracts), nicht im Schema —
# der Schema-Guard hier deckt bewusst nur die Ziel-BETRAEGE (amount/wealth).


# --- #3 Band-Override -----------------------------------------------------

def test_band_override_inverted_rejected():
    with pytest.raises(ValidationError):
        AllocationBandOverridePayload(min_bps=8000, max_bps=2000)


def test_band_override_target_outside_band_rejected():
    with pytest.raises(ValidationError):
        AllocationBandOverridePayload(min_bps=2000, target_bps=9000, max_bps=6000)


def test_band_override_negative_and_over_100_rejected():
    with pytest.raises(ValidationError):
        AllocationBandOverridePayload(min_bps=-100)
    with pytest.raises(ValidationError):
        AllocationBandOverridePayload(max_bps=15000)


def test_band_override_valid_ok():
    b = AllocationBandOverridePayload(min_bps=2000, target_bps=4000, max_bps=6000)
    assert (b.min_bps, b.target_bps, b.max_bps) == (2000, 4000, 6000)
    # Alle None (kein Override gesetzt) bleibt gueltig.
    assert AllocationBandOverridePayload().min_bps is None
