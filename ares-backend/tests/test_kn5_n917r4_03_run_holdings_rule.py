"""KN5 / N-917R4-03: Depotcheck und Live-Rebalancing waehlen Lauf und Holdings
nach DERSELBEN Regel (``core.holdings_rule.select_valuation_runs``).

Befund (H-176-Pruefung): ``depot_check._select_latest_run_with_holdings`` pruefte
Holdings nur am gewaehlten Lauf; ``build_live_rebalancing_payload`` nahm auch die
Produkt-Holdings des juengsten Draft/Final-Laufs. Fall: Final ohne Holdings +
neuerer Draft mit Holdings -> Live-Rebalancing bewertet den Bestand, der
Depotcheck ignoriert ihn («IST = SOLL»). Vorher zudem drei Auswahlregeln
(Depotcheck «Final vor Draft», Live «Final vor juengstem», Holdings «juengster
Draft/Final»).

Gegenprobe: alte Holdings-Pruefung (nur am gewaehlten Lauf) -> rot.
"""
from __future__ import annotations

from types import SimpleNamespace

from tests.test_ccx_p1_snapshot_hash import session_factory  # noqa: F401
from tests.test_ccx_p4_allocation_publish import _finalizable_run
from tests.test_kn4_b_ext01_holding_depot_check import BUCKET_BY_CLASS, _depot, _live_buckets, _positions, _put_holding


def _runs(*specs):
    return [SimpleNamespace(id=i, result_status=s) for i, s in specs]


def test_rule_valuation_and_holdings_run():
    from core.holdings_rule import select_valuation_runs

    # juengster zuerst
    assert [r.id if r else None for r in select_valuation_runs(_runs(("d2", "Draft"), ("f1", "Final")))] == ["f1", "d2"]
    assert [r.id if r else None for r in select_valuation_runs(_runs(("x", "Rejected"), ("d1", "Draft")))] == ["d1", "d1"]
    assert [r.id if r else None for r in select_valuation_runs(_runs(("x", "Rejected")))] == ["x", None]
    assert select_valuation_runs([]) == (None, None)


def _newer_draft_with_same_positions(session_factory, final_run_id):
    """Final-Lauf (aelter, ohne Holdings) + neuerer Draft mit denselben Produkten."""
    from database import new_uuid
    from models.review import RecommendationPosition, RecommendationRun

    with session_factory() as s:
        final = s.get(RecommendationRun, final_run_id)
        final.result_status = "Final"
        final.created_at = "2026-11-01T08:00:00.000Z"
        draft_id = new_uuid()
        s.add(RecommendationRun(
            id=draft_id, mandate_id=final.mandate_id, client_id=final.client_id,
            assessment_id=final.assessment_id, target_allocation_id=final.target_allocation_id,
            policy_id=final.policy_id, capital_market_assumptions_id=final.capital_market_assumptions_id,
            run_type="Optimizer", result_status="Draft", created_by=final.created_by,
            created_at="2026-11-02T08:00:00.000Z", updated_at="2026-11-02T08:00:00.000Z"))
        for pos in s.query(RecommendationPosition).filter(RecommendationPosition.run_id == final_run_id).all():
            s.add(RecommendationPosition(
                id=new_uuid(), run_id=draft_id, product_id=pos.product_id, target_weight_bps=pos.target_weight_bps,
                target_amount_rappen=pos.target_amount_rappen, created_at=pos.created_at, updated_at=pos.updated_at))
        s.commit()
    return draft_id


def test_final_without_holdings_and_newer_draft_with_holdings_same_answer(session_factory):
    from models.mandates import Mandate
    from services.depot_check import _select_latest_run, _select_latest_run_with_holdings
    from services.portfolio_engine import _current_recommendation_run
    from services.portfolio_engine_live_rebalancing import current_run_holdings
    from services.print_fx_gate import current_run_id

    _advisor, mid, _aid, final_id = _finalizable_run(session_factory, "kn5r403")
    draft_id = _newer_draft_with_same_positions(session_factory, final_id)
    draft_positions = _positions(session_factory, draft_id)
    position_id, target, asset_class = draft_positions[0]
    _put_holding(session_factory, mid, draft_id, position_id, target + 40_000_00)

    with session_factory() as db:
        mandate = db.get(Mandate, mid)
        # Eine Regel: bewerteter Lauf ueberall der Final, Holdings-Lauf der Draft.
        assert _select_latest_run(db, mandate).id == final_id
        assert _current_recommendation_run(db, mid).id == final_id
        assert current_run_id(db, mid) == final_id
        assert current_run_holdings(db, mid)[0].id == draft_id
        run, has_holdings = _select_latest_run_with_holdings(db, mandate)
        assert (run.id, has_holdings) == (final_id, True)

    # Live-Rebalancing (Final + Produkt-Holding des Drafts) und Depotcheck: derselbe Bestand.
    live = _live_buckets(session_factory, mid, final_id)
    depot = _depot(session_factory, mid)
    bucket = BUCKET_BY_CLASS[asset_class]
    assert depot["ist_basiert_auf_soll"] is False, depot  # vorher: IST = SOLL (Bestand ignoriert)
    assert depot["buckets"][bucket]["ist_rappen"] >= target + 40_000_00, depot["buckets"][bucket]
    for key, depot_bucket in depot["buckets"].items():
        live_bps = int((live.get(key) or {}).get("current_weight_bps") or 0)
        assert abs(int(depot_bucket["ist_bps"]) - live_bps) <= 1, (key, depot_bucket["ist_bps"], live_bps)


def test_no_holdings_anywhere_stays_ist_equals_soll(session_factory):
    """Gegenprobe der Richtung: ohne jeden Bestand bleibt IST = SOLL."""
    from models.mandates import Mandate
    from services.depot_check import _select_latest_run_with_holdings

    _advisor, mid, _aid, final_id = _finalizable_run(session_factory, "kn5r403b")
    _newer_draft_with_same_positions(session_factory, final_id)
    with session_factory() as db:
        run, has_holdings = _select_latest_run_with_holdings(db, db.get(Mandate, mid))
        assert (run.id, has_holdings) == (final_id, False)
    assert _depot(session_factory, mid)["ist_basiert_auf_soll"] is True
