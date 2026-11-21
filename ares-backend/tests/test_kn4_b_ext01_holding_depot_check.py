"""KN4-B / EXT-01 (externe Abnahme, CTO-Entscheid): Depotcheck nutzt dieselbe
Bestandsquelle wie das Live-Rebalancing.

Befund: Ein Bestand ueber die oeffentliche Route ``PUT .../positions/{id}/
holding`` (Tabelle ``recommendation_holdings``) wurde vom Live-Rebalancing
gewertet («Aktien CHF 100'000 verletzt»), vom Depotcheck aber ignoriert («IST =
SOLL, nicht beurteilbar»): er las nur ``recommendation_positions.
current_amount_rappen``, das ausser im Snapshot-Pfad niemand schreibt.

Jetzt (services/depot_check._live_holding_amounts): Holding-Bestaende mit der
Bewertung des Live-Rebalancings. Teilweise erfasst -> ``ist_teilweise_
abgeleitet`` (core/holdings_rule.py), keine Bandaussage; vollstaendig erfasst ->
echte Bandaussage (core/band_rule.py). Konsistenz: gleiche Ist-bps je Bucket wie
das Live-Rebalancing.

Gegenprobe: ``_live_holding_amounts`` liefert {} -> rot.
"""
from __future__ import annotations

from types import SimpleNamespace

from tests.test_ccx_p1_snapshot_hash import session_factory  # noqa: F401
from tests.test_ccx_p4_allocation_publish import _finalizable_run

BUCKET_BY_CLASS = {"Aktien": "equities", "Obligationen": "bonds", "Immobilien": "real_estate",
                   "Alternative": "alternatives", "Liquiditaet": "liquidity"}


def _put_holding(session_factory, mid, run_id, position_id, value_rappen):
    from models.users import User
    from routers.review import upsert_position_holding
    from schemas.review import RecommendationHoldingUpsert

    with session_factory() as db:
        from models.review import RecommendationRun

        run = db.get(RecommendationRun, run_id)
        user = db.query(User).filter(User.id == run.created_by).first() or db.query(User).first()
        upsert_position_holding(
            mid, run_id, position_id,
            RecommendationHoldingUpsert(market_value_rappen=value_rappen, as_of_date="2026-11-19",
                                        source="manual", notes="Synthetischer Bestand"),
            db=db, current_user=user,
        )


def _positions(session_factory, run_id):
    from models.review import Product, RecommendationPosition

    with session_factory() as db:
        rows = db.query(RecommendationPosition).filter(RecommendationPosition.run_id == run_id).all()
        return [(row.id, int(row.target_amount_rappen or 0),
                 db.get(Product, row.product_id).asset_class) for row in rows]


def _depot(session_factory, mid):
    from models.mandates import Mandate
    from services.depot_check import compute_depot_check

    with session_factory() as db:
        return compute_depot_check(db, db.get(Mandate, mid))


def _live_buckets(session_factory, mid, run_id):
    from models.allocation import TargetAllocation
    from models.mandates import Mandate
    from models.review import RecommendationRun
    from services.fx_basis import load_fx_basis
    from services.portfolio_engine import build_live_rebalancing_payload

    with session_factory() as db:
        mandate = db.get(Mandate, mid)
        ta = db.query(TargetAllocation).filter(TargetAllocation.mandate_id == mid,
                                               TargetAllocation.is_current == 1).first()
        payload = build_live_rebalancing_payload(
            db=db, allocation=ta, run=db.get(RecommendationRun, run_id), advisory_wealth_rappen=0,
            fx_source=load_fx_basis(db, mandate.base_currency or "CHF", set()),
            target_currency=(mandate.base_currency or "CHF"),
        )
    return {BUCKET_BY_CLASS[d["asset_class"]]: d for d in payload["bucket_drifts"]}


def _add_bond_position(session_factory, run_id):
    """Zweite Position (Obligationen), damit "teilweise erfasst" moeglich ist."""
    from datetime import datetime, timezone

    from database import new_uuid
    from models.review import Product, RecommendationPosition

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    pid = new_uuid()
    with session_factory() as s:
        s.add(Product(id=pid, product_name="Test Obligationen", provider="X", product_type="ETF",
                      asset_class="Obligationen", sub_asset_class="Obligationen CHF", currency="CHF",
                      ter_bps=15, sfdr_class="6", is_active=1, created_at=now, updated_at=now))
        s.add(RecommendationPosition(id=new_uuid(), run_id=run_id, product_id=pid, target_weight_bps=0,
                                     target_amount_rappen=200_000_00, created_at=now, updated_at=now))
        s.commit()


def test_holding_route_reaches_depot_check_partial_then_full(session_factory):
    _advisor, mid, _aid, run_id = _finalizable_run(session_factory, "ext01")
    _add_bond_position(session_factory, run_id)
    positions = _positions(session_factory, run_id)
    assert len(positions) >= 2, positions
    before = _depot(session_factory, mid)
    assert before["ist_basiert_auf_soll"] is True  # ohne jeden Bestand: IST = SOLL

    # Teilweise erfasst: eine Position mit Holding, die uebrigen ohne.
    first_id, first_target, first_class = positions[0]
    _put_holding(session_factory, mid, run_id, first_id, first_target + 50_000_00)
    partial = _depot(session_factory, mid)
    bucket = BUCKET_BY_CLASS[first_class]
    assert partial["ist_basiert_auf_soll"] is False and partial["ist_teilweise_abgeleitet"] is True
    assert partial["buckets"][bucket]["ist_rappen"] >= first_target + 50_000_00
    assert all(b["in_band"] is None for b in partial["buckets"].values()), partial["buckets"]

    # Vollstaendig erfasst: echte Bandaussage, gleiche Ist-bps wie das Live-Rebalancing.
    for position_id, target, _cls in positions[1:]:
        _put_holding(session_factory, mid, run_id, position_id, target)
    full = _depot(session_factory, mid)
    assert full["ist_basiert_auf_soll"] is False and full["ist_teilweise_abgeleitet"] is False
    assert any(b["in_band"] is not None for b in full["buckets"].values()), full["buckets"]
    live = _live_buckets(session_factory, mid, run_id)
    for key, depot_bucket in full["buckets"].items():
        live_bps = int((live.get(key) or {}).get("current_weight_bps") or 0)
        assert abs(int(depot_bucket["ist_bps"]) - live_bps) <= 1, (key, depot_bucket["ist_bps"], live_bps)


def test_advisory_report_uses_the_same_flag():
    from services.advisory_report import _check_asset_allocation

    verdict = _check_asset_allocation({"buckets": {"equities": {"in_band": None, "label": "Aktien"}},
                                       "ist_basiert_auf_soll": False, "ist_teilweise_abgeleitet": True},
                                      SimpleNamespace(mandate_type="Anlageberatung"))
    assert verdict["bewertung"] == "nicht_beurteilbar", verdict
