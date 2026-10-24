"""RESERVE-FUNDING-LEDGER-001 -- Folgefix zu PR #638 (RESERVE-DOUBLE-COUNT-001).

Uebernommen aus Codex' adversarialem Review
``docs/audits/reproducers/test_2026_10_18_reserve_double_count_pr638_adversarial.py``
(Branch codex/asset-allocation-stochastic-core). Die drei dort als strict-xfail
gefuehrten Vertraege sind hier ohne xfail aktiv:

1. Ein reiner Policy-/minReserve-Floor wird nie in ein sachfremdes spaetes
   Ziel freigegeben.
2. Die Ziel-Sensitivity konsumiert fuer Baseline UND Gegenlauf je einen
   eigenen, aus dem jeweiligen Goal-Set kompilierten Reserve-Ledger.
3. Reporting-MC vergleicht IST und SOLL auf derselben wirtschaftlichen Basis.

Anpassungen gegenueber dem Reproducer (fachlich begruendet, nicht
abgeschwaecht):

* Vertrag 1 rief ``_external_reserve_release_series`` mit dem aggregierten E
  auf. Ein aggregierter Betrag traegt keine Herkunft -- genau das war der
  Befund. Das Primitiv bleibt (je Tranche), der Vertrag wird daher am Ledger
  geprueft, der die Herkunft kennt.
* Vertrag 2 erwartete die greedy Aggregat-Release (jede Liability darf jeden
  CHF konsumieren) -- das ist die in Vertrag 1 widerlegte Regel. Geprueft
  wird hier die Geldidentitaet gegen den publizierten Ledger beider Laeufe.
  Der Reproducer isolierte E per Monkeypatch von ``_apply_goal_and_reserve_
  tilts``; da Sensitivity E jetzt je Goal-Set neu bemisst, wird stattdessen
  der SAA-Liquiditaets-Ceiling auf 0 gesetzt (E = R, vollstaendig extern).
"""
from __future__ import annotations

import copy
import itertools
from dataclasses import replace
from types import SimpleNamespace

import pytest

import services.optimizer.solver as optimizer_solver
import services.portfolio_engine as pe
import services.portfolio_engine_mc_simulation as mc_simulation
from models.wealth import Goal
from services.portfolio_engine import PortfolioSummary
from services.portfolio_engine_reserve import (
    _external_reserve_release_series,
    _tranche_release_series,
)
from services.reserve_funding_ledger import (
    RESERVE_ACCOUNTING_BASIS,
    compile_reserve_funding_ledger,
    ledger_contract_hash,
)
from test_audit_f23_mc_total_paths import _zero_return_cma
from test_optimizer_phase6 import _seed_mandate, session_factory  # noqa: F401


# ---------------------------------------------------------------------------
# Vertrag 1: Herkunftsbindung
# ---------------------------------------------------------------------------


def test_pure_floor_reserve_is_not_released_into_an_unrelated_late_goal():
    """A source-free floor must not be relabelled as goal funding."""
    pure_policy_floor = 50_000_00
    ledger = compile_reserve_funding_ledger(
        reserve_needed_rappen=pure_policy_floor,
        external_reserve_rappen=pure_policy_floor,
        goal_needs=[],  # kein Ziel hat zur Reserve beigetragen
        cashflow_deficit_need_rappen=0,
        cashflow_series_rappen=[0] * 10,
        goal_liability_paths={"unrelated-late-goal": [0] * 8 + [100_000_00, 0]},
        horizon_years=10,
    )

    assert list(ledger.release_series_rappen) == [0] * 10
    assert ledger.releases == ()
    assert ledger.unspent_floor_rappen == pure_policy_floor
    (floor,) = ledger.tranches
    assert floor.source_kind == "policy_floor" and floor.releasable is False


def test_aggregate_reserve_without_provenance_is_never_released():
    """Aggregate E carries no source: fail-closed, it stays a floor.

    The per-tranche primitive is greedy only for the outflows of its own
    source; the source-blind aggregate entry point no longer relabels.
    """
    assert _external_reserve_release_series(
        50_000_00, [0] * 10, [0] * 8 + [100_000_00, 0]
    ) == [0] * 10
    assert _tranche_release_series(
        50_000_00, [0] * 10, [0] * 8 + [100_000_00, 0]
    )[8] == 50_000_00


def test_goal_tranche_funds_only_its_own_goal_and_floor_rest_stays_outside():
    # R = max(floor 80k, need 60k) = 80k; E = 70k (10k intern).
    # Need-first: 60k extern fuer die Ziele, 10k Floor-Rest (nie freigegeben).
    ledger = compile_reserve_funding_ledger(
        reserve_needed_rappen=80_000,
        external_reserve_rappen=70_000,
        goal_needs=[
            {"goal_id": "near", "need_rappen": 40_000, "rank": 1, "hardness": "Hart"},
            {"goal_id": "mid", "need_rappen": 20_000, "rank": 2, "hardness": "Primaer"},
        ],
        cashflow_deficit_need_rappen=0,
        cashflow_series_rappen=[0] * 6,
        goal_liability_paths={
            "near": [0, 50_000, 0, 0, 0, 0],
            "mid": [0, 0, 0, 0, 30_000, 0],
            "unrelated": [0, 0, 0, 0, 0, 999_000],
        },
        horizon_years=6,
    )
    assert list(ledger.release_series_rappen) == [0, 40_000, 0, 0, 20_000, 0]
    assert ledger.unspent_floor_rappen == 10_000
    assert ledger.unreleased_need_rappen == 0
    assert {(r.destination_id, r.year_index, r.amount_rappen) for r in ledger.releases} == {
        ("near", 1, 40_000),
        ("mid", 4, 20_000),
    }
    assert sum(ledger.release_series_rappen) <= ledger.total_external_rappen


def test_partial_external_share_is_split_pro_rata_and_order_independent():
    needs = [
        {"goal_id": "a", "need_rappen": 30_000, "rank": 1, "hardness": None},
        {"goal_id": "b", "need_rappen": 10_000, "rank": 1, "hardness": None},
    ]
    kwargs = dict(
        reserve_needed_rappen=60_000,
        external_reserve_rappen=20_001,
        cashflow_deficit_need_rappen=20_000,
        cashflow_series_rappen=[-5_000, -5_000, -5_000, -50_000],
        goal_liability_paths={"a": [0, 0, 40_000, 0], "b": [10_000, 0, 0, 0]},
        horizon_years=4,
    )
    hashes = set()
    for permutation in itertools.permutations(needs):
        ledger = compile_reserve_funding_ledger(goal_needs=list(permutation), **kwargs)
        hashes.add(ledger.contract_hash)
    assert len(hashes) == 1
    amounts = {t.tranche_id: t.amount_rappen for t in ledger.tranches}
    # 20'001 anteilig auf 30k/10k/20k Bedarf (groesster Rest, Tiebreak ID).
    assert amounts == {
        "cashflow_deficit:near_term": 6_667,
        "goal:a": 10_001,
        "goal:b": 3_333,
    }
    # Cashflow-Tranche nur in negative Cashflows im 3-Jahres-Fenster, nie in
    # den spaeten -50k-Abfluss in Jahr 3 und nie in ein Ziel.
    cash = [r for r in ledger.releases if r.destination_kind == "cashflow_deficit"]
    assert all(r.year_index <= 2 for r in cash)
    assert sum(r.amount_rappen for r in cash) == amounts["cashflow_deficit:near_term"]
    assert all(value >= 0 for value in ledger.release_series_rappen)


def test_ledger_hash_detects_manipulation():
    ledger = compile_reserve_funding_ledger(
        reserve_needed_rappen=10_000, external_reserve_rappen=10_000,
        goal_needs=[{"goal_id": "g", "need_rappen": 10_000}],
        cashflow_deficit_need_rappen=0, cashflow_series_rappen=[0, 0],
        goal_liability_paths={"g": [0, 10_000]}, horizon_years=2,
    )
    assert ledger_contract_hash(ledger) == ledger.contract_hash
    tampered = replace(ledger, release_series_rappen=(0, 9_000))
    assert ledger_contract_hash(tampered) != tampered.contract_hash
    other_policy = replace(ledger, policy_version="greedy_aggregate_v0")
    assert ledger_contract_hash(other_policy) != ledger.contract_hash


# ---------------------------------------------------------------------------
# Vertrag 2: Sensitivity kompiliert je Goal-Set einen eigenen Ledger
# ---------------------------------------------------------------------------


def _capture_solver(monkeypatch) -> list[dict]:
    calls: list[dict] = []

    def fake_run_solver(**kwargs):
        calls.append({
            "horizon_years": int(kwargs["horizon_years"]),
            "advisory_wealth_rappen": int(kwargs["advisory_wealth_rappen"]),
            "cashflow_series_rappen": [int(v) for v in kwargs["cashflow_series_rappen"]],
        })
        return SimpleNamespace(
            objective_value=1.0 + len(calls),
            weights_bps={"liquidity": 2000, "bonds": 3000, "equities": 4000,
                         "real_estate": 500, "alternatives": 500},
            status="converged",
        )

    monkeypatch.setattr(optimizer_solver, "run_solver", fake_run_solver)
    return calls


def _run_sensitivity(session_factory, monkeypatch, *, suffix: str, target_delta_pct: int):
    monkeypatch.setattr(pe.settings, "optimizer_mode", "stochastic")
    # Ceiling 0: die gesamte Reserve liegt extern (E = R) -- isoliert die
    # Geldidentitaet von der Intern/Extern-Aufteilung.
    monkeypatch.setattr(pe, "_saa_liquidity_ceiling_bps", lambda *_a, **_k: 0)
    advisor_id, client_id, mandate_id, _aid, _pension_goal_id = _seed_mandate(
        session_factory, suffix=suffix
    )
    # Reservewirksames Nahziel (<= 3 J -> voll in der Reserve); die Pension
    # (Ende in 30 J) traegt nach Stufenregel nichts bei.
    goal_id = f"goal-near-{suffix}"
    with session_factory() as session:
        session.add(Goal(
            id=goal_id, mandate_id=mandate_id, client_id=client_id, goal_family="Cashflow",
            goal_type="Einmalige_Ausgabe", label="Renovation", rank=1, weight_bps=2000,
            goal_scope="Beratungsvermögen", value_mode="nominal",
            target_amount_rappen=60_000_00, horizon_years=2, hardness="Hart", is_active=1,
            created_at="2026-03-27T00:00:00.000Z", updated_at="2026-03-27T00:00:00.000Z",
        ))
        session.commit()
    loaded_inputs: list[dict] = []
    real_loader = pe._load_allocation_inputs

    def capture_inputs(*args, **kwargs):
        result = real_loader(*args, **kwargs)
        loaded_inputs.append(copy.deepcopy(result))
        return result

    monkeypatch.setattr(pe, "_load_allocation_inputs", capture_inputs)
    calls = _capture_solver(monkeypatch)
    with session_factory() as session:
        mandate = session.query(pe.Mandate).filter(pe.Mandate.id == mandate_id).one()
        response = pe.evaluate_goal_sensitivity(
            db=session, mandate=mandate, user_id=advisor_id, goal_id=goal_id,
            target_delta_pct=target_delta_pct,
        )
    return response, calls, loaded_inputs[-1]


def _assert_call_consumes_ledger(call: dict, ledger: dict, raw: list[int], advisory: int):
    horizon = call["horizon_years"]
    release = list(ledger["release_series_rappen"])
    assert ledger["horizon_years"] == horizon
    # Startvermoegen = A - E dieses Goal-Sets.
    assert call["advisory_wealth_rappen"] == advisory - ledger["total_external_rappen"]
    # Solver-Cashflows = rohe Cashflows + Release dieses Ledgers.
    assert call["cashflow_series_rappen"] == [
        value + released for value, released in zip(raw[:horizon], release)
    ]
    # Geldidentitaet: jede CHF genau einmal (Rest bleibt Reservekonto).
    assert (
        call["advisory_wealth_rappen"] + sum(release)
        + ledger["unspent_floor_rappen"] + ledger["unreleased_need_rappen"]
        == advisory
    )


def test_sensitivity_consumes_the_same_reserve_release_ledger_as_generate(
    session_factory,  # noqa: F811
    monkeypatch,
):
    """Both sensitivity solver calls must restore carved-out customer cash."""
    response, calls, inputs = _run_sensitivity(
        session_factory, monkeypatch, suffix="reserve-ledger-audit", target_delta_pct=0,
    )
    assert not any(inputs.get("optimizer_replaced_tax_projection_series_rappen") or [])
    raw = [int(v) for v in inputs["optimizer_cashflow_projection_series_rappen"]]
    advisory = int(inputs["advisory_wealth_rappen"])
    assert len(calls) == 2
    baseline = response["baseline_reserve_funding_ledger"]
    modified = response["modified_reserve_funding_ledger"]
    assert baseline["total_external_rappen"] > 0
    assert sum(baseline["release_series_rappen"]) > 0
    for call, ledger in zip(calls, (baseline, modified)):
        _assert_call_consumes_ledger(call, ledger, raw, advisory)
    # Delta 0: identischer Ledger (der Kontext-Hash bindet ihn ein).
    assert baseline["contract_hash"] == modified["contract_hash"]


def test_sensitivity_counterfactual_compiles_its_own_ledger(session_factory, monkeypatch):  # noqa: F811
    response, calls, inputs = _run_sensitivity(
        session_factory, monkeypatch, suffix="reserve-ledger-delta", target_delta_pct=20,
    )
    raw = [int(v) for v in inputs["optimizer_cashflow_projection_series_rappen"]]
    advisory = int(inputs["advisory_wealth_rappen"])
    baseline = response["baseline_reserve_funding_ledger"]
    modified = response["modified_reserve_funding_ledger"]
    # +20 % Nahziel -> mehr Reservebedarf -> anderes E und Release.
    assert modified["total_external_rappen"] > baseline["total_external_rappen"]
    assert modified["contract_hash"] != baseline["contract_hash"]
    for call, ledger in zip(calls, (baseline, modified)):
        _assert_call_consumes_ledger(call, ledger, raw, advisory)


# ---------------------------------------------------------------------------
# Vertrag 3: Reporting-MC auf einer wirtschaftlichen Basis
# ---------------------------------------------------------------------------


def _liquidity_only_inputs(total_advisory: int):
    targets = {bucket: (10_000 if bucket == "liquidity" else 0) for bucket in pe.BUCKET_FIELDS}
    empty_bounds = {bucket: 0 for bucket in pe.BUCKET_FIELDS}
    advisory = PortfolioSummary(
        amounts_rappen={
            bucket: (total_advisory if bucket == "liquidity" else 0)
            for bucket in pe.BUCKET_FIELDS
        },
        total_rappen=total_advisory,
    )
    return targets, empty_bounds, advisory


def test_reporting_mc_compares_current_and_target_on_one_economic_wealth_base(
    monkeypatch,
):
    """Carving out E must not manufacture a current-vs-target wealth gap."""
    monkeypatch.setattr(mc_simulation, "_monte_carlo_simulations", lambda _prefs: 1)
    total_advisory = 1_000_000
    external_reserve = 200_000
    targets, empty_bounds, advisory = _liquidity_only_inputs(total_advisory)

    result = pe._run_allocation_monte_carlo(
        advisory_summary=advisory,
        cashflow_projection_series_rappen=[0],
        goal_inflation_series_bps=[0],
        targets=targets,
        minimums=empty_bounds,
        maximums=empty_bounds,
        cma=_zero_return_cma(),
        goals=[],
        advisory_wealth_rappen=total_advisory,
        total_wealth_rappen=total_advisory,
        policy=None,
        mandate_id="reserve-ledger-reporting-audit",
        simulation_prefs={"transactionCostBps": 0, "rebalanceMode": "bands"},
        start_year=2026,
        target_total_rappen=total_advisory - external_reserve,
    )

    assert result["current_p50_series_rappen"] == [total_advisory, total_advisory]
    assert result["target_p50_series_rappen"] == [total_advisory, total_advisory]
    assert result["reserve_accounting_basis"] == RESERVE_ACCOUNTING_BASIS


def test_reporting_paths_consume_the_release_series_exactly_once(monkeypatch):
    """Release moves money from the reserve account into the strategy -- once."""
    monkeypatch.setattr(mc_simulation, "_monte_carlo_simulations", lambda _prefs: 1)
    total_advisory = 1_000_000
    targets, empty_bounds, advisory = _liquidity_only_inputs(total_advisory)
    cashflows = [-150_000, 0, -100_000]
    release = [150_000, 0, 50_000]  # E = 200k, voll freigegeben
    common = dict(
        advisory_summary=advisory,
        cashflow_projection_series_rappen=cashflows,
        targets=targets, minimums=empty_bounds, maximums=empty_bounds,
        cma=_zero_return_cma(),
        simulation_prefs={"transactionCostBps": 0, "rebalanceMode": "bands"},
        start_year=2026,
        target_total_rappen=total_advisory - 200_000,
        reserve_release_series_rappen=release,
    )
    expected = [1_000_000, 850_000, 850_000, 750_000]
    mc = pe._run_allocation_monte_carlo(
        goal_inflation_series_bps=[0, 0, 0], goals=[],
        advisory_wealth_rappen=total_advisory, total_wealth_rappen=total_advisory,
        policy=None, mandate_id="reserve-ledger-release", **common,
    )
    assert mc["current_p50_series_rappen"] == expected
    assert mc["target_p50_series_rappen"] == expected
    assert mc["external_reserve_balance_series_rappen"] == [200_000, 50_000, 50_000, 0]
    simulation = pe._build_simulation_payload(**common)
    assert simulation["current_mix_series_rappen"] == expected
    assert simulation["target_mix_series_rappen"] == expected
