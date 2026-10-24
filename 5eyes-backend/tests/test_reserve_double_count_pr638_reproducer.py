"""RESERVE-DOUBLE-COUNT-001 -- Codex-Reproducer zu PR #638 als regulaerer Test.

Quelle (read-only): ``docs/audits/reproducers/
test_2026_10_18_reserve_double_count_pr638_adversarial.py`` im Codex-Branch.
Alle drei Vertraege laufen hier ohne xfail.

Soll-Invariante (Liquiditaetsreserve, jeder Franken genau einmal):

    I + sum(Releases) + unspent_floor + unreleased_need == A

mit I = A - E (investierbarer Teil). Ein Release ist an genau eine Quelle
gebunden (Ziel oder nahes Cashflow-Defizit), faellt nie vor deren Abfluss an,
ist je Jahr hoechstens so gross wie dieser Abfluss und in Summe <= E. Ein
Betrag ohne Herkunft (Policy-/minReserve-Floor oder aggregiertes E) wird nie
freigegeben -- er bleibt als Reservekonto beim Kunden (konservativ).

Abweichungen vom Reproducer (fachlich begruendet):

* Vertrag 1 und 3: woertlich uebernommen.
* Vertrag 2: der Reproducer erzwang E = CHF 100'000 per Monkeypatch von
  ``_apply_goal_and_reserve_tilts`` und erwartete die greedy Aggregat-
  Freigabe dieses E in jede Liability. Der Bedarf des Szenarios ist aber nur
  die halbe Pensionsjahresrate; der erzwungene Rest haette keine Quelle und
  ist nach Vertrag 1 nicht freigebbar. Sensitivity bemisst E heute je Goal-Set
  selbst (``compile_goal_set_funding``), der Monkeypatch erreicht den
  Solverpfad nicht mehr. Isoliert wird deshalb ueber Ceiling 0 (E = R,
  vollstaendig extern, voll quellengebunden) plus ein reservewirksames
  Nahziel (die Pension des Seeds endet erst in 30 J und traegt nach der
  Stufenregel nichts bei, E waere 0); das Orakel bleibt die
  chronologische Freigabe in die summierten Liabilities (je Tranche:
  ``_tranche_release_series``). Codex' Closure-Review zu PR #648 (Abschnitt 8)
  fuehrt die Aggregat-Fassung als durch die quellengebundenen Vertraege
  abgeloest.
"""
from __future__ import annotations

import copy

import pytest

import services.portfolio_engine as pe
import services.portfolio_engine_mc_simulation as mc_simulation
import services.reserve_funding_ledger as ledger_module
from models.wealth import Goal
from services.portfolio_engine import PortfolioSummary
from services.portfolio_engine_reserve import (
    _external_reserve_release_series,
    _tranche_release_series,
)
from services.reserve_funding_ledger import compile_reserve_funding_ledger
from tests.test_audit_f23_mc_total_paths import _zero_return_cma
from tests.test_optimizer_phase6 import (  # noqa: F401
    _capture_sensitivity_solver_calls,
    _seed_mandate,
    session_factory,
)


# ---------------------------------------------------------------------------
# Vertrag 1 (woertlich): reiner Floor ohne Herkunft wird nie freigegeben
# ---------------------------------------------------------------------------


def test_pure_floor_reserve_is_not_released_into_an_unrelated_late_goal():
    pure_policy_floor = 50_000_00
    cashflows = [0] * 10
    unrelated_late_goal = [0] * 8 + [100_000_00, 0]

    release = _external_reserve_release_series(
        pure_policy_floor,
        cashflows,
        unrelated_late_goal,
    )

    assert release == [0] * 10


# ---------------------------------------------------------------------------
# Vertrag 2: beide Sensitivity-Laeufe geben das carve-out genau einmal zurueck
# ---------------------------------------------------------------------------


def test_sensitivity_consumes_the_same_reserve_release_ledger_as_generate(
    session_factory,  # noqa: F811
    monkeypatch,
):
    monkeypatch.setattr(pe.settings, "optimizer_mode", "stochastic")
    monkeypatch.setattr(pe, "_saa_liquidity_ceiling_bps", lambda *_a, **_k: 0)
    advisor_id, client_id, mandate_id, _assessment_id, goal_id = _seed_mandate(
        session_factory,
        suffix="reserve-ledger-audit",
    )
    # Die Pension des Seeds (Ende in 30 J) traegt nach Stufenregel nichts zur
    # Reserve bei; ein reservewirksames Nahziel macht E > 0 (Quelle bekannt).
    with session_factory() as session:
        session.add(Goal(
            id="goal-near-reserve-ledger-audit", mandate_id=mandate_id, client_id=client_id,
            goal_family="Cashflow", goal_type="Einmalige_Ausgabe", label="Renovation",
            rank=1, weight_bps=2000, goal_scope="Beratungsvermögen", value_mode="nominal",
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

    fundings: list = []
    real_funding = ledger_module.compile_goal_set_funding

    def capture_funding(**kwargs):
        funding = real_funding(**kwargs)
        fundings.append(funding)
        return funding

    monkeypatch.setattr(pe, "_load_allocation_inputs", capture_inputs)
    monkeypatch.setattr(pe, "compile_goal_set_funding", capture_funding)
    solver_calls = _capture_sensitivity_solver_calls(monkeypatch)

    with session_factory() as session:
        mandate = session.query(pe.Mandate).filter(pe.Mandate.id == mandate_id).one()
        pe.evaluate_goal_sensitivity(
            db=session,
            mandate=mandate,
            user_id=advisor_id,
            goal_id=goal_id,
            target_delta_pct=0,
        )

    assert loaded_inputs
    assert len(solver_calls) == 2
    assert len(fundings) == 2
    inputs = loaded_inputs[-1]
    advisory = int(inputs["advisory_wealth_rappen"])
    raw_cashflows = list(inputs["optimizer_cashflow_projection_series_rappen"])

    for call, funding in zip(solver_calls, fundings):
        external_reserve = advisory - int(funding.start_wealth_rappen)
        assert external_reserve == funding.ledger.total_external_rappen > 0
        horizon = int(call["horizon_years"])
        liabilities = [0] * horizon
        for liability in call["liabilities"]:
            for index, amount in enumerate(liability["liability_path_rappen"][:horizon]):
                liabilities[index] += int(amount)
        raw = [int(value) for value in raw_cashflows[:horizon]]
        release = _tranche_release_series(external_reserve, raw, liabilities)
        assert sum(release) > 0
        assert call["cashflow_series_rappen"] == [
            value + released for value, released in zip(raw, release)
        ]
        # Geldidentitaet: carve-out + Releases + Reste == A, jeder Franken einmal.
        ledger = funding.ledger
        assert (
            funding.start_wealth_rappen + sum(ledger.release_series_rappen)
            + ledger.unspent_floor_rappen + ledger.unreleased_need_rappen
        ) == advisory


# ---------------------------------------------------------------------------
# Vertrag 3 (woertlich): Reporting-MC auf einer wirtschaftlichen Basis
# ---------------------------------------------------------------------------


def test_reporting_mc_compares_current_and_target_on_one_economic_wealth_base(
    monkeypatch,
):
    monkeypatch.setattr(mc_simulation, "_monte_carlo_simulations", lambda _prefs: 1)
    total_advisory = 1_000_000
    external_reserve = 200_000
    targets = {
        bucket: (10_000 if bucket == "liquidity" else 0)
        for bucket in pe.BUCKET_FIELDS
    }
    empty_bounds = {bucket: 0 for bucket in pe.BUCKET_FIELDS}
    advisory = PortfolioSummary(
        amounts_rappen={
            bucket: (total_advisory if bucket == "liquidity" else 0)
            for bucket in pe.BUCKET_FIELDS
        },
        total_rappen=total_advisory,
    )

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


# ---------------------------------------------------------------------------
# Randfaelle der Soll-Invariante (Ledger-Ebene)
# ---------------------------------------------------------------------------


def _identity(ledger, advisory: int) -> int:
    start = advisory - ledger.total_external_rappen
    return (
        start + sum(ledger.release_series_rappen)
        + ledger.unspent_floor_rappen + ledger.unreleased_need_rappen
    )


def test_zero_reserve_releases_nothing():
    ledger = compile_reserve_funding_ledger(
        reserve_needed_rappen=0, external_reserve_rappen=0,
        goal_needs=[{"goal_id": "g", "need_rappen": 0, "rank": 1, "hardness": None}],
        cashflow_deficit_need_rappen=0, cashflow_series_rappen=[-5_000_00, 0, 0],
        goal_liability_paths={"g": [0, 9_000_00, 0]}, horizon_years=3,
    )
    assert list(ledger.release_series_rappen) == [0, 0, 0]
    assert ledger.tranches == () and ledger.releases == ()
    assert _identity(ledger, 600_000_00) == 600_000_00


def test_reserve_above_advisory_wealth_releases_at_most_the_carve_out():
    # Bedarf CHF 350k, Beratungsvermoegen CHF 300k: E ist auf A gecappt.
    advisory = 300_000_00
    ledger = compile_reserve_funding_ledger(
        reserve_needed_rappen=350_000_00, external_reserve_rappen=advisory,
        goal_needs=[
            {"goal_id": "haus", "need_rappen": 200_000_00, "rank": 1, "hardness": "Hart"},
            {"goal_id": "ausbildung", "need_rappen": 150_000_00, "rank": 2, "hardness": None},
        ],
        cashflow_deficit_need_rappen=0, cashflow_series_rappen=[0, 0],
        goal_liability_paths={"haus": [0, 200_000_00], "ausbildung": [0, 150_000_00]},
        horizon_years=2,
    )
    # Pro rata 4:3 auf CHF 300k -> 171'428.57 / 128'571.43 (groesster Rest).
    shares = {t.source_id: t.amount_rappen for t in ledger.tranches}
    assert shares == {"haus": 171_428_57, "ausbildung": 128_571_43}
    assert list(ledger.release_series_rappen) == [0, advisory]
    assert ledger.unspent_floor_rappen == 0 and ledger.unreleased_need_rappen == 0
    assert _identity(ledger, advisory) == advisory


def test_rounding_boundary_pro_rata_splits_every_rappen_exactly_once():
    # 1 Rappen auf drei gleich grosse Quellen: genau einer bekommt ihn (ID-Tiebreak).
    ledger = compile_reserve_funding_ledger(
        reserve_needed_rappen=3, external_reserve_rappen=1,
        goal_needs=[
            {"goal_id": goal, "need_rappen": 1, "rank": 1, "hardness": None}
            for goal in ("c", "a", "b")
        ],
        cashflow_deficit_need_rappen=0, cashflow_series_rappen=[0],
        goal_liability_paths={"a": [1], "b": [1], "c": [1]}, horizon_years=1,
    )
    assert {t.source_id: t.amount_rappen for t in ledger.tranches} == {"a": 1, "b": 0, "c": 0}
    assert list(ledger.release_series_rappen) == [1]
    assert _identity(ledger, 10) == 10


def test_several_outflows_in_the_same_year_are_each_funded_once():
    # Zwei Ziele und ein Cashflow-Defizit faellig im selben Jahr 1; E deckt den
    # Bedarf voll. Je Quelle hoechstens ihr eigener Abfluss, kein Doppelmatching.
    kwargs = dict(
        reserve_needed_rappen=90_000_00, external_reserve_rappen=90_000_00,
        cashflow_deficit_need_rappen=20_000_00,
        cashflow_series_rappen=[0, -20_000_00, 0],
        goal_liability_paths={"a": [0, 40_000_00, 0], "b": [0, 30_000_00, 0]},
        horizon_years=3,
    )
    needs = [
        {"goal_id": "a", "need_rappen": 40_000_00, "rank": 1, "hardness": None},
        {"goal_id": "b", "need_rappen": 30_000_00, "rank": 2, "hardness": None},
    ]
    ledger = compile_reserve_funding_ledger(goal_needs=needs, **kwargs)
    reversed_ledger = compile_reserve_funding_ledger(goal_needs=list(reversed(needs)), **kwargs)
    assert list(ledger.release_series_rappen) == [0, 90_000_00, 0]
    assert {(r.destination_id, r.year_index, r.amount_rappen) for r in ledger.releases} == {
        ("a", 1, 40_000_00), ("b", 1, 30_000_00), ("near_term", 1, 20_000_00),
    }
    assert ledger.contract_hash == reversed_ledger.contract_hash
    assert _identity(ledger, 500_000_00) == 500_000_00


@pytest.mark.parametrize("amount", [0, 1, 50_000_00])
def test_aggregate_entry_point_never_releases(amount):
    assert _external_reserve_release_series(amount, [-10, -10], [10, 10]) == [0, 0]
