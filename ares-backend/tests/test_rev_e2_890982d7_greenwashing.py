"""Pruefer-Reproducer E2 @ 890982d7 (uebernommen in Nachtrag 2).

Erwartung nach Fix: alle drei Tests gruen. Am Head 890982d7: rot.
"""
from __future__ import annotations

from sqlalchemy import text

from tests.test_e2e_thierry_goessi_walkthrough import (  # noqa: F401
    _create_client_and_mandate, _seed_goals, _seed_products, _seed_risk_profile, _seed_wealth,
    advisor_user, api, session_factory,
)
from tests.test_sustainability_e2a_contract import _capture, _ok_capture
from tests.test_sustainability_e2b_n1_product_enforcement import (  # noqa: F401
    _evidence, _non_liquid_positions, _retire, _run, _run_id, world,
)

# Nachtrag 2 (N-901-04): Claim-Text nennt die Liquiditaetsausnahme.
CLAIM = "alle Produkte der Empfehlung ausser Liquidität mit belegtem Nachweis"


def _line(session_factory, mid):
    from models.mandates import Mandate
    from routers.pdf_reports import _build_protokoll_data
    with session_factory() as s:
        data = _build_protokoll_data(s.get(Mandate, mid), s)
    return dict(data.sustainability_lines).get("Umsetzung in der Anlagestrategie") or ""


def test_n901_01_02_manual_unevidenced_position(world, api, session_factory):
    """N-901-01: Finalisierung -> 500 (Product.name). N-901-02: Claim bleibt."""
    mid = world["mid"]
    _ok_capture(api, mid, exclusions=["tobacco"])
    run_id = _run_id(_run(api, mid))
    with session_factory() as s:
        ids = [r[0] for r in s.execute(text(
            "SELECT id FROM products WHERE is_active = 1 AND deleted_at IS NULL "
            "AND asset_class NOT IN ('Liquidität', 'Liquiditaet')"))]
    bad = [p for p in ids if p not in world["evidence"]][0]
    add = api.post(f"/mandates/{mid}/recommendations/{run_id}/positions",
                   json={"product_id": bad, "target_weight_bps": 100})
    assert add.status_code == 409 or CLAIM not in _line(session_factory, mid)  # am Head: 201 + Claim
    if add.status_code == 409:
        # Nachtrag 2 (Entscheid Koordinator): unbelegte Position ist nicht
        # hinzufuegbar. Den Finalisierungspfad aus N-901-01 erreicht der Test
        # deshalb ueber eine direkt eingefuegte Position (Altbestand/Import).
        from database import new_uuid
        now = "2026-11-13T00:00:00.000Z"
        with session_factory() as s:
            s.execute(text(
                "INSERT INTO recommendation_positions (id, run_id, product_id, target_weight_bps, "
                "created_at, updated_at) VALUES (:i, :r, :p, 100, :n, :n)"
            ), {"i": new_uuid(), "r": run_id, "p": bad, "n": now})
            s.commit()
        assert CLAIM not in _line(session_factory, mid)
    assert api.get(f"/mandates/{mid}/reports/portfolio.pdf").status_code == 409  # am Head: 200
    fin = api.put(f"/mandates/{mid}/recommendations/{run_id}/finalize")
    assert fin.status_code == 409, fin.text  # am Head: 500 AttributeError Product.name


def test_n901_02_withdrawn_evidence_after_finalize(world, api, session_factory):
    from models.mandates import Mandate
    from models.review import RecommendationRun
    from services.recommendation_release_gate import assert_recommendation_release_eligible
    mid = world["mid"]
    _ok_capture(api, mid, exclusions=["tobacco"])
    run_id = _run_id(_run(api, mid))
    assert api.put(f"/mandates/{mid}/recommendations/{run_id}/finalize").status_code == 200
    for pid in _non_liquid_positions(api, mid, session_factory, run_id):
        _retire(session_factory, world["advisor_id"], world["evidence"][pid])
    assert CLAIM not in _line(session_factory, mid)  # am Head: Claim bleibt
    assert api.get(f"/mandates/{mid}/reports/anlagestrategie.pdf").status_code == 409  # am Head: 200
    with session_factory() as s:
        blocked = False
        try:
            assert_recommendation_release_eligible(
                s, s.get(Mandate, mid), channel="handoff", run=s.get(RecommendationRun, run_id))
        except Exception:  # noqa: BLE001
            blocked = True
    assert blocked  # am Head: Handoff-Gate passiert


def test_n901_03_combination_offered_then_409(api, advisor_user, session_factory):
    from database import new_uuid
    from models.mandates import Mandate
    from models.product_eligibility import ProductEligibilityRule
    from models.profiling import RiskAssessment
    from models.review import Product
    from routers.review import _risk_score_bucket, build_run_context
    from services.product_eligibility import derive_service_mode, is_eligible_candidate, mandate_tenant_id
    cid, mid = _create_client_and_mandate(api, advisor_user)
    _seed_wealth(api, cid); _seed_goals(api, mid); _seed_risk_profile(api, mid); _seed_products(api, advisor_user)
    api.post(f"/mandates/{mid}/target-allocation/generate",
             json={"preferences": {"tilts": {"tobacco": "exclude", "alcohol": "exclude"}}})
    assert _run(api, mid).status_code == 200
    with session_factory() as s:
        m = s.get(Mandate, mid)
        a = s.query(RiskAssessment).filter(RiskAssessment.mandate_id == mid).first()
        el = lambda p: is_eligible_candidate(s, p, service_mode=derive_service_mode(m), score_bucket=_risk_score_bucket(a),  # noqa: E731
                                             jurisdiction=build_run_context(m).jurisdiction, tenant_id=mandate_tenant_id(m))
        src = [p for p in s.query(Product).filter(Product.sub_asset_class == "Immobilien Schweiz").all() if el(p)][0]
        clone = Product(**{c.name: getattr(src, c.name) for c in Product.__table__.columns})
        clone.id, clone.isin, clone.product_name = new_uuid(), "CH9999999990", "Probe Immo CH 2"
        s.add(clone)
        for r in s.query(ProductEligibilityRule).filter(ProductEligibilityRule.product_id == src.id).all():
            rc = ProductEligibilityRule(**{c.name: getattr(r, c.name) for c in ProductEligibilityRule.__table__.columns})
            rc.id, rc.product_id = new_uuid(), clone.id
            s.add(rc)
        s.commit()
        prods = [p for p in s.query(Product).filter(Product.is_active == 1).all()
                 if p.asset_class not in ("Liquidität", "Liquiditaet") and el(p)]
        immo = {}
        for p in sorted((p for p in prods if p.asset_class == "Immobilien"), key=lambda p: (p.sub_asset_class, p.id)):
            immo.setdefault(p.sub_asset_class, []).append(p.id)
        rest = [p.id for p in prods if p.asset_class != "Immobilien"]
    _evidence(session_factory, advisor_user.id, rest + [v[0] for v in immo.values()], theme="tobacco")
    _evidence(session_factory, advisor_user.id, rest + [v[1] for v in immo.values()], theme="alcohol")
    cur = api.get(f"/mandates/{mid}/sustainability-preferences").json()["current"]
    cap = _capture(api, mid, expected=cur["id"] if cur else None, exclusions=["tobacco", "alcohol"])
    run = _run(api, mid)
    # Owner-Regel: angeboten => erfuellbar. Am Head: Erfassung 201, Lauf 409.
    assert not (cap.status_code == 201 and run.status_code == 409), run.text
