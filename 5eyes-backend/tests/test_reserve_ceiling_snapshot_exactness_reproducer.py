"""RESERVE-CEILING-001 (Rest) -- Codex-Reproducer als regulaerer Test.

Quelle (read-only): ``docs/audits/reproducers/
test_2026_10_16_reserve_ceiling_snapshot_and_exactness_adversarial.py`` im
Codex-Branch. Beide Vertraege laufen hier ohne xfail; einzige Anpassung ist
der Import (regulaerer Test statt ``FIVEEYES_BACKEND``-Pfad).

Soll-Invariante:

* Exaktes Cap: interne Reserve = min(R, floor(A * c / 10000)); entschieden per
  Integervergleich ``R * 10000 > A * c`` -- nie mit vorgerundeten bps.
* Deckungsgleichung, jeder Rappen genau einmal:
  ``R = intern + absorbiert + extern + Deckungsluecke``, ``intern + extern <= A``.
* Historischer Reload publiziert den gespeicherten Split
  (``ReserveSplitSnapshotV1``, hash-gebunden im Reserve-Ledger-Snapshot und im
  Allocation-Context). Heutige HouseMatrix/Policy ergibt nur eine getrennte
  Neubewertung (``live_re_evaluation`` + Drift, Status ``stale``) und
  blockiert die Finalisierung.
"""
from __future__ import annotations

import json

import pytest

from models.allocation import HouseMatrix, TargetAllocation
from routers.allocation import get_current_allocation_payload
from services.portfolio_engine_reserve import (
    _compute_reserve_for_inputs,
    _saa_internal_reserve_rappen,
)
from services.reserve_funding_ledger_snapshot import (
    RESERVE_FUNDING_LEDGER_SNAPSHOT_VERSION,
    REASON_LEDGER_STALE,
    reserve_ledger_finalization_block,
    verify_persisted_reserve_snapshot,
)
from services.reserve_split_snapshot import split_from_dict, split_reserve
from test_reserve_ceiling_single_source import (  # noqa: F401
    _generate,
    advisor_user,
    session_factory,
)

CHF = 100


def _payload(session_factory, advisor_user, mandate_id):
    with session_factory() as session:
        payload = get_current_allocation_payload(mandate_id, db=session, current_user=advisor_user)
    return payload if isinstance(payload, dict) else payload.model_dump()


def _set_house_liq_max(session_factory, mandate_id, liq_max_bps):
    with session_factory() as session:
        allocation = (
            session.query(TargetAllocation)
            .filter(TargetAllocation.mandate_id == mandate_id, TargetAllocation.is_current == 1)
            .one()
        )
        rows = session.query(HouseMatrix).filter(HouseMatrix.policy_id == allocation.policy_id).all()
        assert rows
        for row in rows:
            row.liq_max_bps = liq_max_bps
        session.commit()


# ---------------------------------------------------------------------------
# Codex-Vertrag 1 (woertlich): Reload schreibt die Generationsreserve nicht um
# ---------------------------------------------------------------------------


def test_reload_does_not_rewrite_generation_reserve_from_mutated_house_matrix(
    session_factory,  # noqa: F811
    advisor_user,  # noqa: F811
) -> None:
    mandate_id, generated = _generate(session_factory, advisor_user, 4)
    generated_external = int(generated["external_reserve_rappen"])

    _set_house_liq_max(session_factory, mandate_id, 300)

    payload = _payload(session_factory, advisor_user, mandate_id)
    allocation_payload = payload["target_allocation"]
    stored_external = (
        allocation_payload["external_reserve_at_generation_rappen"]
        if isinstance(allocation_payload, dict)
        else allocation_payload.external_reserve_at_generation_rappen
    )
    assert int(stored_external) == generated_external
    assert int(payload["external_reserve_rappen"]) == generated_external


# ---------------------------------------------------------------------------
# Codex-Vertrag 2 (woertlich): exaktes Rappen-Cap vor jeder bps-Rundung
# ---------------------------------------------------------------------------


def test_internal_reserve_never_exceeds_exact_rappen_cap_before_bps_rounding() -> None:
    advisory_wealth_rappen = 60_000_000  # CHF 600'000
    ceiling_bps = 200
    exact_cap_rappen = advisory_wealth_rappen * ceiling_bps // 10_000
    reserve_needed_rappen = exact_cap_rappen + 1_000  # CHF 10 = 0.167 bp above cap

    internal = _saa_internal_reserve_rappen(
        reserve_needed_rappen,
        advisory_wealth_rappen,
        ceiling_bps,
    )

    assert internal == exact_cap_rappen


# ---------------------------------------------------------------------------
# Referenzfall Snapshot: Generate -> Reload bytegleich, Drift getrennt
# ---------------------------------------------------------------------------


def test_reference_case_snapshot_replay_and_separate_re_evaluation(
    session_factory,  # noqa: F811
    advisor_user,  # noqa: F811
):
    # A = CHF 600'000, R = CHF 150'000 (Einmalausgabe in 2 J), c = 200 bps.
    mandate_id, generated = _generate(session_factory, advisor_user, 4)
    split = generated["reserve_split"]
    assert (split["internal_rappen"], split["external_rappen"]) == (12_000 * CHF, 138_000 * CHF)
    assert split["ceiling_bps"] == 200 and split["ceiling_rappen"] == 12_000 * CHF
    assert split["coverage_gap_rappen"] == 0 and split["absorbed_rappen"] == 0

    unchanged = _payload(session_factory, advisor_user, mandate_id)
    assert unchanged["reserve_split"] == split  # bytegleich zum Generate
    assert unchanged["reserve_split_replay"]["status"] == "verified"
    assert unchanged["reserve_split_replay"]["live_re_evaluation"] is None
    assert reserve_ledger_finalization_block(unchanged) is None

    with session_factory() as session:
        allocation = session.query(TargetAllocation).filter(
            TargetAllocation.mandate_id == mandate_id, TargetAllocation.is_current == 1).one()
        constraints = json.loads(allocation.effective_constraints_json)
        reference = constraints["reserve_funding_ledger"]
        assert reference["reserve_split_hash"] == split["contract_hash"]
        _ledger, stored_split = verify_persisted_reserve_snapshot(allocation, constraints)
        assert stored_split.to_dict() == split

    _set_house_liq_max(session_factory, mandate_id, 300)
    drifted = _payload(session_factory, advisor_user, mandate_id)
    assert drifted["reserve_split"] == split  # historischer Entscheid unveraendert
    assert int(drifted["external_reserve_rappen"]) == 138_000 * CHF
    assert int(drifted["investable_advisory_wealth_rappen"]) == 462_000 * CHF
    replay = drifted["reserve_split_replay"]
    assert replay["status"] == "stale"
    live = replay["live_re_evaluation"]
    assert (live["internal_rappen"], live["external_rappen"]) == (18_000 * CHF, 132_000 * CHF)
    assert replay["external_reserve_drift_rappen"] == -6_000 * CHF
    assert reserve_ledger_finalization_block(drifted)[0] == REASON_LEDGER_STALE


def test_tampered_split_snapshot_fails_integrity(session_factory, advisor_user):  # noqa: F811
    mandate_id, _generated = _generate(session_factory, advisor_user, 4)
    with session_factory() as session:
        allocation = session.query(TargetAllocation).filter(
            TargetAllocation.mandate_id == mandate_id, TargetAllocation.is_current == 1).one()
        constraints = json.loads(allocation.effective_constraints_json)
        snapshot = json.loads(allocation.reserve_funding_ledger_json)
        snapshot["reserve_split"]["external_rappen"] -= 1
        allocation.reserve_funding_ledger_json = json.dumps(snapshot)
        with pytest.raises(ValueError):
            verify_persisted_reserve_snapshot(allocation, constraints)


def test_v1_ledger_snapshot_without_split_stays_readable(session_factory, advisor_user):  # noqa: F811
    mandate_id, generated = _generate(session_factory, advisor_user, 4)
    with session_factory() as session:
        allocation = session.query(TargetAllocation).filter(
            TargetAllocation.mandate_id == mandate_id, TargetAllocation.is_current == 1).one()
        constraints = json.loads(allocation.effective_constraints_json)
        snapshot = json.loads(allocation.reserve_funding_ledger_json)
        v1 = {"snapshot_version": RESERVE_FUNDING_LEDGER_SNAPSHOT_VERSION, "ledger": snapshot["ledger"]}
        allocation.reserve_funding_ledger_json = json.dumps(v1)
        reference = dict(constraints["reserve_funding_ledger"])
        for key in ("reserve_split_version", "reserve_split_hash"):
            reference.pop(key)
        reference["snapshot_version"] = RESERVE_FUNDING_LEDGER_SNAPSHOT_VERSION
        constraints["reserve_funding_ledger"] = reference
        ledger, split = verify_persisted_reserve_snapshot(allocation, constraints)
    assert split is None
    assert ledger.total_external_rappen == int(generated["external_reserve_rappen"])


# ---------------------------------------------------------------------------
# Randfaelle: Cap-Grenzen, Reserve 0, Reserve > Vermoegen, Absorption
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "needed,expected_internal",
    [
        (1_200_000, 1_200_000),  # exakt auf dem Cap -> intern
        (1_200_001, 1_200_000),  # 1 Rappen darueber -> Cap
        (1_202_999, 1_200_000),  # < 0.5 bp darueber (frueher voll intern)
        (1_199_999, 1_199_999),  # 1 Rappen darunter
    ],
)
def test_cap_boundaries_in_rappen(needed, expected_internal):
    assert _saa_internal_reserve_rappen(needed, 60_000_000, 200) == expected_internal


def test_cap_is_rounded_down_for_fractional_rappen():
    # A = 12'345.67 CHF, c = 300 bps -> 370.3701 CHF -> 37'037 Rappen (abgerundet).
    assert _saa_internal_reserve_rappen(10_000_000, 1_234_567, 300) == 37_037


@pytest.mark.parametrize("needed,wealth,ceiling", [(0, 60_000_000, 200), (5_000, 0, 200), (5_000, -10, 200), (5_000, 60_000_000, 0)])
def test_zero_and_negative_inputs_are_well_defined(needed, wealth, ceiling):
    split = split_reserve(reserve_needed_rappen=needed, advisory_wealth_rappen=wealth, ceiling_bps=ceiling)
    assert split.internal_rappen + split.absorbed_rappen + split.external_rappen + split.coverage_gap_rappen == max(0, needed)
    assert min(split.internal_rappen, split.external_rappen, split.coverage_gap_rappen) >= 0
    assert split_from_dict(split.to_dict()) == split


def test_reserve_above_advisory_wealth_counts_internal_reserve_once():
    # Zwei Nahziele im selben Jahr: CHF 200k + 150k = 350k > A = 300k, c = 300 bps.
    goals = [
        type("G", (), dict(id=f"g-{label}", label=label, goal_type="Einmalige_Ausgabe", pension_pillar=None,
                           probability_pct=None, rank=1, hardness="Primaer", weight_bps=0,
                           target_amount_rappen=amount, target_date=None, start_date=None,
                           horizon_years=1, frequency=None))()
        for label, amount in (("Hauskauf", 200_000 * CHF), ("Ausbildung", 150_000 * CHF))
    ]
    breakdown: dict = {}
    needed, external = _compute_reserve_for_inputs(
        goals=goals, limits_prefs={}, asset_class_prefs={}, recurring_net_cashflow_rappen=0,
        recurring_cashflow_projection_series_rappen=[], advisory_wealth_rappen=300_000 * CHF,
        saa_liquidity_ceiling_bps=300, need_breakdown=breakdown,
    )
    split = breakdown["reserve_split"]
    assert needed == 350_000 * CHF
    # Vorher: extern = A = CHF 300k UND intern CHF 9k (Floor auf I = 0 nie
    # gehalten, aber ausgewiesen) -> CHF 309k "gedeckt" aus CHF 300k. Jetzt:
    # ganz A extern, kein investierbarer Teil, keine interne Reserve, Luecke
    # ehrlich ausgewiesen. E bleibt unveraendert CHF 300k.
    assert external == split.external_rappen == 300_000 * CHF
    assert split.internal_rappen == 0
    assert split.internal_rappen + split.external_rappen == 300_000 * CHF
    assert split.coverage_gap_rappen == 50_000 * CHF
    assert split.investable_wealth_rappen == 0


def test_reserve_above_wealth_with_other_assets_absorbs_only_the_excess():
    split = split_reserve(
        reserve_needed_rappen=350_000 * CHF, advisory_wealth_rappen=300_000 * CHF,
        ceiling_bps=300, unlocked_other_assets_rappen=20_000 * CHF,
    )
    assert (split.internal_rappen, split.absorbed_rappen, split.external_rappen, split.coverage_gap_rappen) == (
        0, 20_000 * CHF, 300_000 * CHF, 30_000 * CHF,
    )


def test_absorption_by_other_assets_closes_the_identity():
    split = split_reserve(
        reserve_needed_rappen=150_000 * CHF, advisory_wealth_rappen=600_000 * CHF,
        ceiling_bps=200, unlocked_other_assets_rappen=40_000 * CHF,
    )
    assert (split.internal_rappen, split.absorbed_rappen, split.external_rappen, split.coverage_gap_rappen) == (
        12_000 * CHF, 40_000 * CHF, 98_000 * CHF, 0,
    )
