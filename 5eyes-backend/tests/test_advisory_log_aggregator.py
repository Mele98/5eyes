"""Sprint U-FINMA-2.2 — Tests fuer Aggregator-Integration + Suitability-
Mismatch-Detection + Auto-Log-Endpoint.
"""
from __future__ import annotations

import sys
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import configure_mappers, sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base, get_db  # noqa: E402
from models import (  # noqa: E402,F401
    allocation, clients, mandates, profiling, review, snapshots, users, wealth,
)
configure_mappers()

from main import app  # noqa: E402
from models.allocation import (  # noqa: E402
    BuildingBlock, HouseMatrix, OptimizerPolicy, TargetAllocation,
)
from models.clients import Client  # noqa: E402
from models.mandates import Mandate  # noqa: E402
from models.profiling import RiskAssessment  # noqa: E402
from models.review import AdvisoryLog  # noqa: E402
from models.users import User  # noqa: E402
from services.advisory_log_service import (  # noqa: E402
    count_active_entries,
    detect_suitability_mismatches,
    get_latest_active_entry,
)
from services.advisory_report import compute_advisory_report  # noqa: E402
from services.auth import get_current_user, require_advisor  # noqa: E402


_NOW = "2026-05-29T10:00:00.000Z"


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'finma22.db'}",
        connect_args={"check_same_thread": False},
    )
    SF = sessionmaker(
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
        bind=engine,
    )
    Base.metadata.create_all(bind=engine)
    try:
        yield SF
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _seed(s) -> tuple[User, Mandate]:
    advisor = User(
        id=str(uuid.uuid4()),
        username=f"adv-{uuid.uuid4().hex[:6]}",
        password_hash="h",
        full_name="Anna Beispiel",
        role="advisor",
        is_active=1,
        created_at=_NOW, updated_at=_NOW,
    )
    client = Client(
        id=str(uuid.uuid4()),
        client_number=f"C-{uuid.uuid4().hex[:6]}",
        first_name="Daniel", last_name="Beispiel",
        advisor_id=advisor.id,
        country_of_residence="CH",
        created_at=_NOW, updated_at=_NOW,
    )
    mandate = Mandate(
        id=str(uuid.uuid4()),
        client_id=client.id,
        mandate_number=f"M-{uuid.uuid4().hex[:6]}",
        mandate_type="Anlageberatung",
        opened_at=_NOW,
        created_at=_NOW, updated_at=_NOW,
    )
    s.add_all([advisor, client, mandate])
    s.commit()
    return advisor, mandate


def _seed_ta_within_budget(s, mandate, advisor, *, risky_bps: int = 4000):
    """Erzeugt eine TargetAllocation deren Buckets innerhalb der Bands sind."""
    policy = OptimizerPolicy(
        id=str(uuid.uuid4()), policy_name="test-policy", version=1,
        is_current=1, valid_from=_NOW[:10],
        optimizer_engine="goal_based_v1",
        max_real_estate_bps=2000, max_alternatives_bps=1000,
        min_liquidity_bps=0, allow_other_assets_for_goals=1,
        created_by=advisor.id, created_at=_NOW, updated_at=_NOW,
    )
    s.add(policy)
    s.flush()
    ta = TargetAllocation(
        id=str(uuid.uuid4()), mandate_id=mandate.id, policy_id=policy.id,
        version=1, is_current=1,
        target_equities_bps=3500, target_bonds_bps=5000,
        target_real_estate_bps=1000, target_alternatives_bps=300,
        target_liquidity_bps=200,
        band_equities_min_bps=3000, band_equities_max_bps=4000,
        band_bonds_min_bps=4000, band_bonds_max_bps=6000,
        band_real_estate_min_bps=500, band_real_estate_max_bps=1500,
        band_alternatives_min_bps=0, band_alternatives_max_bps=800,
        band_liquidity_min_bps=0, band_liquidity_max_bps=500,
        risky_fraction_bps=risky_bps,
        risk_budget_bps_at_generation=4500,
        set_by=advisor.id, set_at=_NOW,
        created_at=_NOW, updated_at=_NOW,
    )
    s.add(ta)
    s.commit()
    return ta, policy


# ---------------------------------------------------------------------------
# detect_suitability_mismatches
# ---------------------------------------------------------------------------

def test_no_mismatch_for_in_budget_allocation(session_factory):
    with session_factory() as s:
        advisor, mandate = _seed(s)
        _seed_ta_within_budget(s, mandate, advisor, risky_bps=4000)
        warnings = detect_suitability_mismatches(s, mandate)
    assert warnings == []


def test_mismatch_when_risky_exceeds_budget(session_factory):
    """risky_fraction > risk_budget_at_generation → Warning."""
    with session_factory() as s:
        advisor, mandate = _seed(s)
        _seed_ta_within_budget(s, mandate, advisor, risky_bps=5000)  # > 4500
        warnings = detect_suitability_mismatches(s, mandate)
    assert any("Risiko" in w and "ueberschreitet" in w.lower() or "Risiko" in w and "überschreitet" in w for w in warnings)


def test_mismatch_when_bucket_outside_band(session_factory):
    with session_factory() as s:
        advisor, mandate = _seed(s)
        ta, _ = _seed_ta_within_budget(s, mandate, advisor, risky_bps=4000)
        # Aktien: target 35%, Band 30-40 → ok. Jetzt Band auf 36-40 setzen → ausserhalb
        ta.band_equities_min_bps = 3600
        s.commit()
        warnings = detect_suitability_mismatches(s, mandate)
    assert any("Toleranzband" in w for w in warnings)


def test_no_mismatches_when_no_target_allocation(session_factory):
    """Mandat ohne TA → keine Mismatches (kein False-Positive)."""
    with session_factory() as s:
        advisor, mandate = _seed(s)
        warnings = detect_suitability_mismatches(s, mandate)
    assert warnings == []


# ---------------------------------------------------------------------------
# count_active_entries + get_latest_active_entry
# ---------------------------------------------------------------------------

def test_count_excludes_superseded(session_factory):
    with session_factory() as s:
        advisor, mandate = _seed(s)
        # 3 Einträge, einer davon superseded
        e1 = AdvisoryLog(
            id=str(uuid.uuid4()), mandate_id=mandate.id, advisor_id=advisor.id,
            entry_type="Sonstiges", title="A",
            entry_date=_NOW[:10], status="Empfohlen",
            version=1, created_at=_NOW, updated_at=_NOW,
        )
        e2_old = AdvisoryLog(
            id=str(uuid.uuid4()), mandate_id=mandate.id, advisor_id=advisor.id,
            entry_type="Sonstiges", title="B-v1",
            entry_date=_NOW[:10], status="Empfohlen",
            version=1, created_at=_NOW, updated_at=_NOW,
        )
        s.add_all([e1, e2_old])
        s.flush()
        e2_new = AdvisoryLog(
            id=str(uuid.uuid4()), mandate_id=mandate.id, advisor_id=advisor.id,
            entry_type="Sonstiges", title="B-v2",
            entry_date=_NOW[:10], status="Beschlossen",
            version=2, supersedes_id=e2_old.id,
            created_at=_NOW, updated_at=_NOW,
        )
        s.add(e2_new)
        s.flush()
        e2_old.superseded_by_id = e2_new.id
        s.commit()

        count = count_active_entries(s, mandate_id=mandate.id)
    assert count == 2  # e1 + e2_new (e2_old superseded)


def test_latest_active_entry_is_most_recent(session_factory):
    with session_factory() as s:
        advisor, mandate = _seed(s)
        old = AdvisoryLog(
            id=str(uuid.uuid4()), mandate_id=mandate.id, advisor_id=advisor.id,
            entry_type="Sonstiges", title="Alt",
            entry_date="2026-01-01",
            entry_datetime="2026-01-01T10:00:00.000Z",
            status="Empfohlen", version=1,
            created_at=_NOW, updated_at=_NOW,
        )
        new = AdvisoryLog(
            id=str(uuid.uuid4()), mandate_id=mandate.id, advisor_id=advisor.id,
            entry_type="Sonstiges", title="Neu",
            entry_date="2026-05-29",
            entry_datetime="2026-05-29T10:00:00.000Z",
            status="Empfohlen", version=1,
            created_at=_NOW, updated_at=_NOW,
        )
        s.add_all([old, new])
        s.commit()
        latest = get_latest_active_entry(s, mandate_id=mandate.id)
    assert latest.title == "Neu"


def test_latest_returns_none_for_empty_mandate(session_factory):
    with session_factory() as s:
        advisor, mandate = _seed(s)
        latest = get_latest_active_entry(s, mandate_id=mandate.id)
    assert latest is None


# ---------------------------------------------------------------------------
# Aggregator: neue Sektion `beratungsprotokoll`
# ---------------------------------------------------------------------------

def test_aggregator_includes_beratungsprotokoll_key(session_factory):
    with session_factory() as s:
        advisor, mandate = _seed(s)
        payload = compute_advisory_report(s, mandate, advisor=advisor)
    assert "beratungsprotokoll" in payload
    bp = payload["beratungsprotokoll"]
    assert bp["total_active"] == 0
    assert bp["latest_entry"] is None
    assert bp["last_review_date"] is None
    assert bp["days_since_last_review"] is None
    assert bp["suitability_mismatches"] == []
    assert bp["has_active_mismatches"] is False
    assert bp["retention_audit_ok"] is True


def test_aggregator_beratungsprotokoll_with_active_entry(session_factory):
    with session_factory() as s:
        advisor, mandate = _seed(s)
        s.add(AdvisoryLog(
            id=str(uuid.uuid4()), mandate_id=mandate.id, advisor_id=advisor.id,
            entry_type="Jahresreview", title="Review",
            entry_date="2026-05-29",
            entry_datetime="2026-05-29T14:00:00.000Z",
            description="Jahresgespraech mit detaillierter SAA-Diskussion.",
            status="Empfohlen", version=1,
            retain_until="2036-05-29",
            integrity_hash="a" * 64,
            created_at=_NOW, updated_at=_NOW,
        ))
        s.commit()
        payload = compute_advisory_report(s, mandate, advisor=advisor)
    bp = payload["beratungsprotokoll"]
    assert bp["total_active"] == 1
    assert bp["latest_entry"] is not None
    assert bp["latest_entry"]["title"] == "Review"
    assert bp["last_review_date"] == "2026-05-29"


def test_aggregator_signals_suitability_mismatches(session_factory):
    with session_factory() as s:
        advisor, mandate = _seed(s)
        _seed_ta_within_budget(s, mandate, advisor, risky_bps=5500)  # > 4500
        payload = compute_advisory_report(s, mandate, advisor=advisor)
    bp = payload["beratungsprotokoll"]
    assert bp["has_active_mismatches"] is True
    assert len(bp["suitability_mismatches"]) >= 1


# ---------------------------------------------------------------------------
# Auto-Log-Endpoint
# ---------------------------------------------------------------------------

@pytest.fixture()
def http_client(session_factory):
    SF = session_factory
    session = SF()
    advisor, mandate = _seed(session)

    def _db_dep():
        try:
            yield session
        finally:
            pass

    def _user_dep():
        return advisor

    app.dependency_overrides[get_db] = _db_dep
    app.dependency_overrides[get_current_user] = _user_dep
    app.dependency_overrides[require_advisor] = _user_dep
    try:
        yield TestClient(app), advisor, mandate, session
    finally:
        app.dependency_overrides.clear()
        session.close()


def test_auto_log_endpoint_creates_prefilled_entry(http_client):
    client, advisor, mandate, session = http_client
    resp = client.post(
        f"/mandates/{mandate.id}/advisory-log/from-report-generation",
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == "Empfohlen"
    assert body["communication_channel"] == "schriftlich"
    assert body["language"] == "de"
    assert len(body["topics"]) >= 1
    # Generischer Risiko-Hinweis muss da sein
    assert len(body["risk_warnings_given"]) >= 1
    assert body["integrity_hash"] is not None
    assert body["retain_until"].endswith("-29") or len(body["retain_until"]) == 10


def test_auto_log_includes_suitability_warnings(http_client):
    client, advisor, mandate, session = http_client
    _seed_ta_within_budget(session, mandate, advisor, risky_bps=5500)

    resp = client.post(
        f"/mandates/{mandate.id}/advisory-log/from-report-generation",
    )
    assert resp.status_code == 201
    body = resp.json()
    # Mismatches müssen als risk_warnings übernommen sein
    assert any("Risiko" in w or "Toleranz" in w for w in body["risk_warnings_given"])
