"""PROPERTY-RISK-MODEL-001 (Audit 2026-09-14, User-Entscheid 2026-09-16):

Das API-Schema erlaubte fuer Direktimmobilien bis zu 100'000 bps (1000%)
erwartete Jahresrendite, und die Engine compoundierte den akzeptierten Wert
exponentiell -- ein API-/Importwert konnte die Vermoegens- und Goal-Basis
dadurch explosionsartig dominieren (Audit-Repro: 1.000% Rendite ergab
[100, 1100, 12100, 133100] fuer eine Startposition von 100).

Fachentscheid (User, 2026-09-16): Direktimmobilien bleiben in der Monte-
Carlo-Simulation bewusst DETERMINISTISCH ("einfach eine Indexierung oder
keine") -- eine selbstbewohnte/direkt gehaltene Liegenschaft wird NICHT wie
ein kotierter Immobilienindex (SXI Real Estate, in der bestehenden CMA-
Korrelationsmatrix) modelliert; sie schwankt nicht wie eine Aktie. Diese
Datei deckt daher NUR die tatsaechlich geschlossene Luecke ab: die
Eingabevalidierung von asset_expected_return_bps fuer position_type=
'Immobilien'. test_external_direct_property_total_paths_contract.py und
test_audit_f23_mc_total_paths.py bestaetigen unveraendert, dass der
deterministische MC-Vertrag (p10==p50==p90 fuer die externe Immobilien-
Komponente) bewusst erhalten bleibt.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from schemas.wealth import WealthPositionCreate, WealthPositionUpdate
from services.wealth_position_semantics import (
    WealthPositionSemanticsError,
    require_plausible_property_expected_return,
)


def _valid_property(**overrides):
    base = dict(
        label="Ferienhaus Tessin",
        position_type="Immobilien",
        assignment="Anderes Vermögen",
        current_value_rappen=1_000_000_00,
        property_usage="Ferienimmobilie",
        asset_expected_return_bps=100,
    )
    base.update(overrides)
    return base


def test_require_plausible_property_expected_return_rejects_audit_repro_value():
    """Audit-Repro: 1000% (100_000 bps) wurde bislang klaglos akzeptiert."""
    with pytest.raises(WealthPositionSemanticsError):
        require_plausible_property_expected_return("Immobilien", 100_000)


def test_require_plausible_property_expected_return_accepts_plausible_range():
    for bps in (-2000, -500, 0, 100, 1000, 2000):
        require_plausible_property_expected_return("Immobilien", bps)


def test_require_plausible_property_expected_return_ignores_none_and_other_types():
    require_plausible_property_expected_return("Immobilien", None)
    # Alternative-Positionen (Private Equity/VC) duerfen weiterhin extreme
    # Renditeerwartungen haben -- nur Immobilien sind eingeschraenkt.
    require_plausible_property_expected_return("Alternative", 100_000)
    require_plausible_property_expected_return("Depot", 100_000)


def test_create_rejects_extreme_property_return():
    with pytest.raises(ValidationError):
        WealthPositionCreate(**_valid_property(asset_expected_return_bps=100_000))


def test_create_accepts_plausible_property_return():
    WealthPositionCreate(**_valid_property(asset_expected_return_bps=150))


def test_create_alternative_position_still_allows_extreme_return():
    """Regressionsschutz: die Feld-Obergrenze (le=100_000) bleibt fuer
    Alternative-Positionen unveraendert -- nur Immobilien wird eingeschraenkt."""
    WealthPositionCreate(
        label="VC-Fonds",
        position_type="Alternative",
        assignment="Anderes Vermögen",
        current_value_rappen=500_000_00,
        asset_expected_return_bps=50_000,
    )


def test_update_rejects_extreme_property_return_given_existing_position_type():
    """WealthPositionUpdate kennt position_type nicht (unveraenderlich nach
    Anlage) -- die Pruefung erfolgt im Router mit dem bestehenden
    position_type aus der DB, hier isoliert auf Funktionsebene nachgestellt."""
    payload = WealthPositionUpdate(asset_expected_return_bps=100_000)
    with pytest.raises(WealthPositionSemanticsError):
        require_plausible_property_expected_return(
            "Immobilien", payload.asset_expected_return_bps,
        )
