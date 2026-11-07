"""I-02 (Integrationsprobe 2026-11-07, Dok. 103): Snapshot 0 ist ein Betrag.

Befund: ``_strategy_basis_from_allocation`` (N-858-2) las den
Generierungs-Snapshot ``advisory_wealth_at_generation_rappen`` per
``int(x or 0) or current``. Ein Snapshot von 0 (Strategie auf Beratungs-
vermoegen 0 gerechnet) fiel dadurch still auf das AKTUELLE Beratungs-
vermoegen zurueck -- und umging in Kombination mit #866 (N-858-11) dessen
Fix: das PDF haette Betraege auf ein Vermoegen gerechnet, auf das die
Strategie nie gerechnet wurde.

Soll: Snapshot 0 bleibt 0 (Basis 0, keine Bucket-Betraege, Hinweis auf das
abweichende aktuelle Vermoegen); nur ``None`` (Altbestand ohne Snapshot)
faellt auf das aktuelle Beratungsvermoegen zurueck. Nur synthetische Daten.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from routers.pdf_reports import _strategy_basis_from_allocation, _strategy_presentation_amounts

TARGET = {"equities": 4000, "bonds": 4000, "liquidity": 2000}


def _ta(snapshot, reserve=None):
    return SimpleNamespace(
        advisory_wealth_at_generation_rappen=snapshot,
        external_reserve_at_generation_rappen=reserve,
        created_at="2026-11-02T22:50:00",
    )


@pytest.mark.parametrize("reserve", [None, 0, 5_000_00])
def test_snapshot_zero_stays_zero_and_is_not_replaced_by_current_wealth(reserve):
    current = 50_000_00
    payload = {"strategy_base_rappen": current, "external_reserve_rappen": 0}
    basis = _strategy_basis_from_allocation(_ta(0, reserve), payload, current)
    assert basis["advisory_wealth_rappen"] == 0
    assert basis["strategy_base_rappen"] == 0
    assert basis["external_reserve_rappen"] == 0
    amounts = _strategy_presentation_amounts(
        basis["advisory_wealth_rappen"], basis["strategy_base_rappen"], TARGET, [])
    assert not any(int(v or 0) for v in amounts["bucket_amounts_rappen"].values())
    # Abweichung zum aktuellen Vermoegen wird ausgewiesen, nicht still ersetzt.
    assert basis["note"] and "CHF 0 per 02.11.2026" in basis["note"] and "50'000" in basis["note"]


def test_missing_snapshot_falls_back_to_current_wealth():
    current = 50_000_00
    basis = _strategy_basis_from_allocation(
        _ta(None), {"strategy_base_rappen": current, "external_reserve_rappen": 0}, current)
    assert basis["advisory_wealth_rappen"] == current
    assert basis["strategy_base_rappen"] == current
    assert basis["note"] is None


def test_no_snapshot_and_no_current_wealth_stays_unknown():
    basis = _strategy_basis_from_allocation(_ta(None), {}, None)
    assert basis["advisory_wealth_rappen"] is None
    assert basis["strategy_base_rappen"] is None


def test_positive_snapshot_unchanged():
    basis = _strategy_basis_from_allocation(_ta(150_000_00, 9_000_00), {}, 150_000_00)
    assert basis["advisory_wealth_rappen"] == 150_000_00
    assert basis["strategy_base_rappen"] == 141_000_00
    assert basis["note"] is None
