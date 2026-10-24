"""Sprint U-104 (2026-06-05): Tests fuer RecommendationRun-Cleanup.

Verifiziert dass:
  - Cleanup-Service alte Runs identifiziert und (bei dry_run=False) loescht
  - Zugehoerige RecommendationPositions mit weggehen (kein Orphan)
  - dry_run nichts anfasst
  - retention_days < 30 verboten ist (Sicherheits-Schwelle)
  - Endpoint POST /admin/system/recommendation-runs/cleanup schreibt Audit
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

BACKEND_ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = Path(__file__).resolve().parent
for path in (BACKEND_ROOT, TESTS_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from database import get_db, new_uuid
from main import app
from models.review import (
    AuditLog,
    RecommendationPosition,
    RecommendationRun,
)
from services.auth import require_admin
from services.recommendation_run_cleanup import (
    DEFAULT_RETENTION_DAYS,
    MIN_RETENTION_DAYS,
    cleanup_recommendation_runs,
)
from test_optimizer_shadow_mode import _seed_realistic_mandate, session_factory  # noqa: F401


# ---------------------------------------------------------------------------
# Seeding helpers
# ---------------------------------------------------------------------------

def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _seed_admin_and_mandate(session_factory, suffix: str) -> tuple[str, str, str]:
    """Erzeugt Mandat via realistischen Seed + ergaenzt Policy-FK.

    is_current=0: dies ist nur eine synthetische FK-Zielzeile fuer
    RecommendationRun.policy_id in diesen Cleanup-Tests (unabhaengig von der
    global-einzigen "aktuellen" Policy aus dem _seed_realistic_mandate-
    Bootstrap). is_current=1 wuerde -- da dieser Helper pro Testfall/Tenant
    mehrfach mit unterschiedlichem suffix aufgerufen wird -- mehrere
    gleichzeitig "aktuelle" OptimizerPolicy-Zeilen anhaeufen und den neuen
    Eindeutigkeits-Guard in ensure_runtime_reference_data() verletzen.
    """
    from models.allocation import OptimizerPolicy

    advisor_id, _cid, mandate_id, _aid, _gid = _seed_realistic_mandate(session_factory, suffix=suffix)
    policy_id = f"policy-{suffix}"
    now_iso = _iso(datetime.now(timezone.utc))
    with session_factory() as s:
        if not s.query(OptimizerPolicy).filter(OptimizerPolicy.id == policy_id).first():
            s.add(OptimizerPolicy(
                id=policy_id, policy_name=f"U104-{suffix}",
                version=1, is_current=0, valid_from=now_iso,
                optimizer_engine="goal_based_v1",
                max_real_estate_bps=2000, max_alternatives_bps=1000,
                min_liquidity_bps=0, created_by=advisor_id,
                created_at=now_iso, updated_at=now_iso,
            ))
            s.commit()
    return advisor_id, mandate_id, policy_id


def _add_run(
    session_factory,
    *,
    mandate_id: str,
    policy_id: str,
    admin_id: str,
    days_old: int,
    n_positions: int = 0,
    product_id: str = "prod-u104",
    result_status: str = "Draft",
) -> str:
    """Schreibt einen RecommendationRun mit created_at vor N Tagen."""
    from datetime import timedelta
    from models.mandates import Mandate

    created_at = _iso(datetime.now(timezone.utc) - timedelta(days=days_old))
    run_id = new_uuid()
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mandate_id).first()
        client_id = mandate.client_id
        s.add(RecommendationRun(
            id=run_id, mandate_id=mandate_id, client_id=client_id,
            policy_id=policy_id, run_type="Optimizer",
            result_status=result_status, created_by=admin_id,
            created_at=created_at, updated_at=created_at,
        ))
        for _ in range(n_positions):
            s.add(RecommendationPosition(
                id=new_uuid(), run_id=run_id, product_id=product_id,
                target_weight_bps=1000, created_at=created_at, updated_at=created_at,
            ))
        s.commit()
    return run_id


def _add_advisory_log_referencing_run(
    session_factory,
    *,
    mandate_id: str,
    advisor_id: str,
    run_id: str,
) -> str:
    """Schreibt einen AdvisoryLog-Eintrag (FINMA-Beratungsprotokoll), der per
    recommendation_run_id auf `run_id` zeigt -- PRIV-003-Repro: dieser Verweis
    darf den Cleanup nicht ins Leere laufen lassen."""
    from models.review import AdvisoryLog

    now_iso = _iso(datetime.now(timezone.utc))
    log_id = new_uuid()
    with session_factory() as s:
        s.add(AdvisoryLog(
            id=log_id, mandate_id=mandate_id, entry_type="Beratung",
            title="U104 Beratungsgespraech", recommendation_run_id=run_id,
            status="Empfohlen", advisor_id=advisor_id,
            entry_date=now_iso, created_at=now_iso, updated_at=now_iso,
        ))
        s.commit()
    return log_id


def _add_product(session_factory, product_id: str = "prod-u104"):
    from models.review import Product
    now_iso = _iso(datetime.now(timezone.utc))
    with session_factory() as s:
        if not s.query(Product).filter(Product.id == product_id).first():
            s.add(Product(
                id=product_id, isin=f"CH{product_id[:10].rjust(10,'0')}",
                symbol="X",
                product_name="Test", asset_class="Aktien", currency="CHF",
                product_type="ETF", is_active=1,
                created_at=now_iso, updated_at=now_iso,
            ))
            s.commit()


# ---------------------------------------------------------------------------
# Service-Tests
# ---------------------------------------------------------------------------

def test_default_retention_is_90_days():
    assert DEFAULT_RETENTION_DAYS == 90


def test_retention_below_min_raises(session_factory):
    with pytest.raises(ValueError, match="MIN_RETENTION|Mindest-Schwelle|30"):
        with session_factory() as s:
            cleanup_recommendation_runs(s, retention_days=MIN_RETENTION_DAYS - 1)


def test_dry_run_does_not_delete(session_factory):
    admin_id, mid, pid = _seed_admin_and_mandate(session_factory, "dryrun")
    _add_product(session_factory)
    _add_run(session_factory, mandate_id=mid, policy_id=pid,
             admin_id=admin_id, days_old=120, n_positions=2)

    with session_factory() as s:
        result = cleanup_recommendation_runs(s, dry_run=True)
        assert result.dry_run is True
        assert result.deleted_runs == 1
        assert result.deleted_positions == 2

    # DB unveraendert
    with session_factory() as s:
        assert s.query(RecommendationRun).count() == 1
        assert s.query(RecommendationPosition).count() == 2


def test_cleanup_deletes_old_runs_and_positions(session_factory):
    admin_id, mid, pid = _seed_admin_and_mandate(session_factory, "deletes")
    _add_product(session_factory)
    _add_run(session_factory, mandate_id=mid, policy_id=pid,
             admin_id=admin_id, days_old=120, n_positions=3)
    _add_run(session_factory, mandate_id=mid, policy_id=pid,
             admin_id=admin_id, days_old=10, n_positions=1)

    with session_factory() as s:
        result = cleanup_recommendation_runs(s)
        s.commit()

    assert result.deleted_runs == 1
    assert result.deleted_positions == 3

    with session_factory() as s:
        assert s.query(RecommendationRun).count() == 1  # nur der junge
        assert s.query(RecommendationPosition).count() == 1


def test_cleanup_with_no_old_runs_returns_zero(session_factory):
    admin_id, mid, pid = _seed_admin_and_mandate(session_factory, "noold")
    _add_product(session_factory)
    _add_run(session_factory, mandate_id=mid, policy_id=pid,
             admin_id=admin_id, days_old=5, n_positions=1)

    with session_factory() as s:
        result = cleanup_recommendation_runs(s)
    assert result.deleted_runs == 0
    assert result.deleted_positions == 0


# ---------------------------------------------------------------------------
# PRIV-003: Final/referenced Laeufe duerfen NICHT rein nach Alter geloescht
# werden.
# ---------------------------------------------------------------------------

def test_final_run_survives_cleanup_despite_age(session_factory):
    """Red vor dem Fix: ein 'Final'-Lauf (dem Kunden vorgelegt / vertraglich
    relevant) wurde bisher wie jeder Draft-Lauf rein nach created_at
    geloescht. Green nach dem Fix: result_status == 'Final' schuetzt den
    Lauf unabhaengig vom Alter."""
    admin_id, mid, pid = _seed_admin_and_mandate(session_factory, "finalold")
    _add_product(session_factory)
    final_run_id = _add_run(
        session_factory, mandate_id=mid, policy_id=pid, admin_id=admin_id,
        days_old=400, n_positions=2, result_status="Final",
    )
    draft_run_id = _add_run(
        session_factory, mandate_id=mid, policy_id=pid, admin_id=admin_id,
        days_old=400, n_positions=1, result_status="Draft",
    )

    with session_factory() as s:
        result = cleanup_recommendation_runs(s)
        s.commit()

    # Nur der alte Draft-Lauf ist ein Loesch-Kandidat, der Final-Lauf nicht.
    assert result.deleted_runs == 1
    assert result.deleted_positions == 1

    with session_factory() as s:
        remaining_ids = {r.id for r in s.query(RecommendationRun).all()}
    assert final_run_id in remaining_ids
    assert draft_run_id not in remaining_ids


def test_run_referenced_by_advisory_log_survives_cleanup(session_factory):
    """Red vor dem Fix: ein per AdvisoryLog.recommendation_run_id noch aktiv
    referenzierter Lauf (FINMA-Beratungsprotokoll, hash-geschuetzt, 10 Jahre
    Aufbewahrung) wurde trotzdem rein nach Alter geloescht, obwohl der
    Verweis danach ins Leere zeigt. Green nach dem Fix: referenzierte Laeufe
    werden von der Loeschung ausgenommen."""
    admin_id, mid, pid = _seed_admin_and_mandate(session_factory, "advlogref")
    _add_product(session_factory)
    referenced_run_id = _add_run(
        session_factory, mandate_id=mid, policy_id=pid, admin_id=admin_id,
        days_old=400, n_positions=2, result_status="Draft",
    )
    unreferenced_run_id = _add_run(
        session_factory, mandate_id=mid, policy_id=pid, admin_id=admin_id,
        days_old=400, n_positions=1, result_status="Draft",
    )
    _add_advisory_log_referencing_run(
        session_factory, mandate_id=mid, advisor_id=admin_id, run_id=referenced_run_id,
    )

    with session_factory() as s:
        result = cleanup_recommendation_runs(s)
        s.commit()

    assert result.deleted_runs == 1
    assert result.deleted_positions == 1

    with session_factory() as s:
        remaining_ids = {r.id for r in s.query(RecommendationRun).all()}
    assert referenced_run_id in remaining_ids
    assert unreferenced_run_id not in remaining_ids


def test_superseded_and_unreferenced_old_run_still_deleted(session_factory):
    """Regression: der Normalfall (Draft/Superseded, kein Verweis, aelter
    als Retention) muss weiterhin exakt wie vorher geloescht werden --
    Tier-1 Alltagsverhalten bleibt unveraendert."""
    admin_id, mid, pid = _seed_admin_and_mandate(session_factory, "supersededold")
    _add_product(session_factory)
    superseded_run_id = _add_run(
        session_factory, mandate_id=mid, policy_id=pid, admin_id=admin_id,
        days_old=400, n_positions=3, result_status="Superseded",
    )

    with session_factory() as s:
        result = cleanup_recommendation_runs(s)
        s.commit()

    assert result.deleted_runs == 1
    assert result.deleted_positions == 3
    with session_factory() as s:
        assert s.query(RecommendationRun).filter(
            RecommendationRun.id == superseded_run_id
        ).count() == 0


def test_portfolio_handoff_reference_is_nulled_not_blocking(session_factory):
    """PortfolioHandoff.recommendation_run_id ist laut Modell-Docstring
    ABSICHTLICH nullable und darf die Bereinigung nicht blockieren -- der
    Cleanup muss die FK vorab auf NULL setzen statt den Lauf zu schuetzen
    (sonst IntegrityError unter PRAGMA foreign_keys=ON in der echten Tier-1
    DB) und darf den eigentlichen Handoff-Datensatz nicht anfassen."""
    from models.portfolio_handoff import PortfolioHandoff

    admin_id, mid, pid = _seed_admin_and_mandate(session_factory, "handoffref")
    _add_product(session_factory)
    old_run_id = _add_run(
        session_factory, mandate_id=mid, policy_id=pid, admin_id=admin_id,
        days_old=400, n_positions=1, result_status="Draft",
    )
    handoff_id = new_uuid()
    now_iso = _iso(datetime.now(timezone.utc))
    with session_factory() as s:
        s.add(PortfolioHandoff(
            id=handoff_id, mandate_id=mid, recommendation_run_id=old_run_id,
            trade_list_snapshot_json="[]", live_total_value_rappen=0,
            position_count=0, recipient_name="Depotbank X",
            status="Gesendet", created_by=admin_id,
            created_at=now_iso, updated_at=now_iso,
        ))
        s.commit()

    with session_factory() as s:
        result = cleanup_recommendation_runs(s)
        s.commit()

    assert result.deleted_runs == 1

    with session_factory() as s:
        assert s.query(RecommendationRun).filter(
            RecommendationRun.id == old_run_id
        ).count() == 0
        handoff = s.query(PortfolioHandoff).filter(
            PortfolioHandoff.id == handoff_id
        ).first()
        assert handoff is not None  # der Handoff selbst bleibt bestehen
        assert handoff.recommendation_run_id is None  # nur die Referenz wird genullt


# ---------------------------------------------------------------------------
# Endpoint-Tests
# ---------------------------------------------------------------------------

def _client(session_factory, admin_id: str) -> TestClient:
    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()
    admin_user = SimpleNamespace(id=admin_id, full_name="Admin U104", email="admin-u104@test.local")
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[require_admin] = lambda: admin_user
    return TestClient(app)


def test_endpoint_dry_run_does_not_delete(session_factory):
    admin_id, mid, pid = _seed_admin_and_mandate(session_factory, "epdry")
    _add_product(session_factory)
    _add_run(session_factory, mandate_id=mid, policy_id=pid,
             admin_id=admin_id, days_old=200, n_positions=2)

    try:
        with _client(session_factory, admin_id) as client:
            response = client.post(
                "/admin/system/recommendation-runs/cleanup",
                json={"dry_run": True},
            )
            assert response.status_code == 200, response.text
            data = response.json()
            assert data["dry_run"] is True
            assert data["deleted_runs"] == 1
            assert data["retention_days"] == 90
    finally:
        app.dependency_overrides.clear()

    with session_factory() as s:
        assert s.query(RecommendationRun).count() == 1  # nichts geloescht


def test_endpoint_real_cleanup_deletes_and_audits(session_factory):
    admin_id, mid, pid = _seed_admin_and_mandate(session_factory, "epreal")
    _add_product(session_factory)
    _add_run(session_factory, mandate_id=mid, policy_id=pid,
             admin_id=admin_id, days_old=200, n_positions=2)
    _add_run(session_factory, mandate_id=mid, policy_id=pid,
             admin_id=admin_id, days_old=10, n_positions=1)

    try:
        with _client(session_factory, admin_id) as client:
            response = client.post(
                "/admin/system/recommendation-runs/cleanup",
                json={"retention_days": 90},
            )
            assert response.status_code == 200, response.text
            data = response.json()
            assert data["dry_run"] is False
            assert data["deleted_runs"] == 1
            assert data["deleted_positions"] == 2
            assert data["runs_remaining"] == 1
    finally:
        app.dependency_overrides.clear()

    # Verbleibend: 1 Run + 1 Position
    with session_factory() as s:
        assert s.query(RecommendationRun).count() == 1
        assert s.query(RecommendationPosition).count() == 1

    # Audit-Eintrag muss existieren (action=DELETE, table=recommendation_runs)
    with session_factory() as s:
        rows = (
            s.query(AuditLog)
            .filter(AuditLog.table_name == "recommendation_runs")
            .filter(AuditLog.action == "DELETE")
            .order_by(AuditLog.created_at.desc())
            .all()
        )
    assert len(rows) >= 1
    assert "bulk_cleanup" == rows[0].field_name
    assert "runs=1" in (rows[0].new_value or "")
    assert "positions=2" in (rows[0].new_value or "")


def test_endpoint_rejects_too_low_retention(session_factory):
    admin_id, _mid, _pid = _seed_admin_and_mandate(session_factory, "eprej")
    try:
        with _client(session_factory, admin_id) as client:
            response = client.post(
                "/admin/system/recommendation-runs/cleanup",
                json={"retention_days": 10},
            )
            assert response.status_code == 422
            assert "Mindest" in response.text or "30" in response.text
    finally:
        app.dependency_overrides.clear()
