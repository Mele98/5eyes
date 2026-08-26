"""Regression-Lock fuer REC-002/REC-004 (Codex-Audit 2026-08-25,
docs/audits/2026-08-25-auth-execution-operations-followup-audit.md).

REC-002: `_validate_recommendation_for_finalization()` (routers/review.py)
prueft nur die SUMME aller Positionsgewichte (9900-10100 bps) -- eine
einzelne negative oder absurd grosse Einzelposition blieb unbemerkt,
solange die Summe rechnerisch stimmte. Fix: harte Bounds (0-10000 bps,
target_amount_rappen >= 0) direkt am API-Rand in
schemas/review.py::RecommendationPositionCreate.

REC-004: POST .../positions (add_position) blockte nur `result_status ==
"Final"`, nicht `"Superseded"` -- ein durch finalize_recommendation()
bereits abgeloester Run blieb ueber diesen Endpoint trotzdem mutierbar.
Fix: Gate erweitert auf beide Endzustaende.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

BACKEND_ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = Path(__file__).resolve().parent
for path in (BACKEND_ROOT, TESTS_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from database import get_db, new_uuid  # noqa: E402
from main import app  # noqa: E402
from models.review import Product, RecommendationRun  # noqa: E402
from models.users import User  # noqa: E402
from services.auth import require_advisor  # noqa: E402
from test_optimizer_shadow_mode import _seed_realistic_mandate, session_factory  # noqa: E402,F401


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _add_product(session_factory, product_id: str = "prod-rec002") -> str:
    now_iso = _iso(datetime.now(timezone.utc))
    with session_factory() as s:
        if not s.query(Product).filter(Product.id == product_id).first():
            s.add(Product(
                id=product_id, isin=f"CH{product_id[:10].rjust(10, '0')}",
                symbol="X",
                product_name="Test", asset_class="Aktien", currency="CHF",
                product_type="ETF", is_active=1,
                created_at=now_iso, updated_at=now_iso,
            ))
            s.commit()
    return product_id


def _ensure_policy(session_factory, *, suffix: str, advisor_id: str) -> str:
    from models.allocation import OptimizerPolicy

    policy_id = f"policy-{suffix}"
    now_iso = _iso(datetime.now(timezone.utc))
    with session_factory() as s:
        if not s.query(OptimizerPolicy).filter(OptimizerPolicy.id == policy_id).first():
            s.add(OptimizerPolicy(
                id=policy_id, policy_name=f"REC002-{suffix}",
                version=1, is_current=0, valid_from=now_iso,
                optimizer_engine="goal_based_v1",
                max_real_estate_bps=2000, max_alternatives_bps=1000,
                min_liquidity_bps=0, created_by=advisor_id,
                created_at=now_iso, updated_at=now_iso,
            ))
            s.commit()
    return policy_id


def _add_run(
    session_factory, *, mandate_id: str, admin_id: str, policy_id: str, status: str = "Draft",
) -> str:
    from models.mandates import Mandate

    now_iso = _iso(datetime.now(timezone.utc))
    run_id = new_uuid()
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mandate_id).first()
        s.add(RecommendationRun(
            id=run_id, mandate_id=mandate_id, client_id=mandate.client_id,
            policy_id=policy_id,
            run_type="Optimizer", result_status=status,
            created_by=admin_id, created_at=now_iso, updated_at=now_iso,
        ))
        s.commit()
    return run_id


def _client(session_factory, advisor_id: str) -> TestClient:
    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    with session_factory() as s:
        advisor = s.query(User).filter(User.id == advisor_id).first()
        s.expunge(advisor)

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[require_advisor] = lambda: advisor
    return TestClient(app)


def _positions_url(mandate_id: str, run_id: str) -> str:
    return f"/mandates/{mandate_id}/recommendations/{run_id}/positions"


def test_add_position_rejects_negative_weight(session_factory):
    advisor_id, _cid, mandate_id, _aid, _gid = _seed_realistic_mandate(session_factory, suffix="rec002neg")
    product_id = _add_product(session_factory, "prod-rec002neg")
    policy_id = _ensure_policy(session_factory, suffix="prod-rec002neg", advisor_id=advisor_id)
    run_id = _add_run(session_factory, mandate_id=mandate_id, admin_id=advisor_id, policy_id=policy_id)

    try:
        with _client(session_factory, advisor_id) as client:
            response = client.post(
                _positions_url(mandate_id, run_id),
                json={"product_id": product_id, "target_weight_bps": -100},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422, response.text


def test_add_position_rejects_weight_above_10000_bps(session_factory):
    advisor_id, _cid, mandate_id, _aid, _gid = _seed_realistic_mandate(session_factory, suffix="rec002big")
    product_id = _add_product(session_factory, "prod-rec002big")
    policy_id = _ensure_policy(session_factory, suffix="prod-rec002big", advisor_id=advisor_id)
    run_id = _add_run(session_factory, mandate_id=mandate_id, admin_id=advisor_id, policy_id=policy_id)

    try:
        with _client(session_factory, advisor_id) as client:
            response = client.post(
                _positions_url(mandate_id, run_id),
                json={"product_id": product_id, "target_weight_bps": 15000},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422, response.text


def test_add_position_rejects_negative_target_amount(session_factory):
    advisor_id, _cid, mandate_id, _aid, _gid = _seed_realistic_mandate(session_factory, suffix="rec002amt")
    product_id = _add_product(session_factory, "prod-rec002amt")
    policy_id = _ensure_policy(session_factory, suffix="prod-rec002amt", advisor_id=advisor_id)
    run_id = _add_run(session_factory, mandate_id=mandate_id, admin_id=advisor_id, policy_id=policy_id)

    try:
        with _client(session_factory, advisor_id) as client:
            response = client.post(
                _positions_url(mandate_id, run_id),
                json={
                    "product_id": product_id,
                    "target_weight_bps": 500,
                    "target_amount_rappen": -1,
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422, response.text


def test_add_position_accepts_valid_position(session_factory):
    advisor_id, _cid, mandate_id, _aid, _gid = _seed_realistic_mandate(session_factory, suffix="rec002ok")
    product_id = _add_product(session_factory, "prod-rec002ok")
    policy_id = _ensure_policy(session_factory, suffix="prod-rec002ok", advisor_id=advisor_id)
    run_id = _add_run(session_factory, mandate_id=mandate_id, admin_id=advisor_id, policy_id=policy_id)

    try:
        with _client(session_factory, advisor_id) as client:
            response = client.post(
                _positions_url(mandate_id, run_id),
                json={
                    "product_id": product_id,
                    "target_weight_bps": 5000,
                    "target_amount_rappen": 250000,
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 201, response.text


def test_add_position_rejects_mutation_on_superseded_run(session_factory):
    """REC-004-Kernfix: bisher blockte der Gate nur 'Final', nicht
    'Superseded' -- ein bereits abgeloester Run blieb mutierbar."""
    advisor_id, _cid, mandate_id, _aid, _gid = _seed_realistic_mandate(session_factory, suffix="rec004sup")
    product_id = _add_product(session_factory, "prod-rec004sup")
    policy_id = _ensure_policy(session_factory, suffix="prod-rec004sup", advisor_id=advisor_id)
    run_id = _add_run(session_factory, mandate_id=mandate_id, admin_id=advisor_id, policy_id=policy_id, status="Superseded")

    try:
        with _client(session_factory, advisor_id) as client:
            response = client.post(
                _positions_url(mandate_id, run_id),
                json={"product_id": product_id, "target_weight_bps": 5000},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 400, response.text
    assert "können nicht mehr geändert werden" in response.text


def test_add_position_still_rejects_mutation_on_final_run(session_factory):
    """Gegenprobe: das bereits bestehende 'Final'-Gate darf nicht regressieren."""
    advisor_id, _cid, mandate_id, _aid, _gid = _seed_realistic_mandate(session_factory, suffix="rec004fin")
    product_id = _add_product(session_factory, "prod-rec004fin")
    policy_id = _ensure_policy(session_factory, suffix="prod-rec004fin", advisor_id=advisor_id)
    run_id = _add_run(session_factory, mandate_id=mandate_id, admin_id=advisor_id, policy_id=policy_id, status="Final")

    try:
        with _client(session_factory, advisor_id) as client:
            response = client.post(
                _positions_url(mandate_id, run_id),
                json={"product_id": product_id, "target_weight_bps": 5000},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 400, response.text
