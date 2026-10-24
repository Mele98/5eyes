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
    """Budget und Baender eingehalten -> keine Budget-/Band-Warnung.

    SUITABILITY-DETECTOR-AVAILABILITY-001: vorher erwartete dieser Test
    ``warnings == []``, obwohl das Fixture weder ein Risikoprofil noch
    HouseMatrix-Zeilen hat -- der Cap-Check wurde still uebersprungen und das
    leere Ergebnis als "geeignet" festgeschrieben (fail-open). Jetzt bleibt
    genau der Hinweis "HouseMatrix-Cap nicht pruefbar (RISK_PROFILE_MISSING)".
    Die echte Positivkontrolle (Cap geprueft und eingehalten -> leere Liste)
    liegt in test_suitability_detector_score_scale.py::
    test_positive_control_within_cap_no_warning.
    """
    with session_factory() as s:
        advisor, mandate = _seed(s)
        _seed_ta_within_budget(s, mandate, advisor, risky_bps=4000)
        warnings = detect_suitability_mismatches(s, mandate)
    assert len(warnings) == 1, warnings
    assert "HouseMatrix-Cap nicht pruefbar (RISK_PROFILE_MISSING)" in warnings[0]
    assert not any("Toleranzband" in w or "Risikobudget" in w for w in warnings)


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


def _seed_house_matrix_bands(s, policy):
    """Produktions-HouseMatrix (1..10-Bucket-Skala) ueber den echten
    Seeding-Pfad _seed_house_matrix_rows().

    SUITABILITY-DETECTOR-SCALE-001 (2026-10-14): frueher wurden hier zwei
    handgebaute Zeilen auf der 0..100-Skala geseedet (score 20-40 / 70-90).
    Solche Zeilen erzeugt die Produktion nie (score_from/score_to sind 1..10)
    -- das Test-Orakel kodierte damit genau den Defekt, dass
    detect_suitability_mismatches() den rohen score_x10 gegen die Matrix
    verglich. Relevante Caps hier: Defensiv (Bucket 3-4) 45 %,
    Wachstumsorientiert (Bucket 7-8) 80 %.
    """
    from services.house_matrix_loader import _HARDCODED_FALLBACK
    from services.portfolio_engine_house_matrix import (
        _normalize_house_matrix_defaults,
        _seed_house_matrix_rows,
    )

    _seed_house_matrix_rows(
        s, policy.id,
        _normalize_house_matrix_defaults(list(_HARDCODED_FALLBACK)), _NOW,
    )
    s.commit()


# Fragebogen-Punkte, aus denen risk_scoring.compute_scores() exakt diesen
# final_score_x10 herleitet (der Detektor validiert die Herleitung ueber
# services.risk_matrix.score_bucket_from_assessment()).
_RA_ANSWERS_BY_SCORE = {
    30: dict(q_income_points=0, q_obligations_points=0, q_savings_points=0, q_wealth_points=0,
             investment_horizon_label="Mehr als 12 Jahre",
             q_investment_goal_points=1, q_risk_preference_points=1, q_risk_behavior_points=3),
    75: dict(q_income_points=0, q_obligations_points=0, q_savings_points=0, q_wealth_points=12,
             investment_horizon_label="Mehr als 12 Jahre",
             q_investment_goal_points=2, q_risk_preference_points=4, q_risk_behavior_points=4),
}


def _seed_risk_assessment(s, mandate, advisor, *, final_score_x10, is_overridden=0,
                           override_score_x10=None):
    from risk_fixture_helpers import derive_current_risk_fields
    from services.risk_scoring import profile_for_score_x10

    fields = derive_current_risk_fields(**_RA_ANSWERS_BY_SCORE[final_score_x10])
    assert fields["final_score_x10"] == final_score_x10
    s.add(RiskAssessment(
        id=str(uuid.uuid4()), mandate_id=mandate.id, version=1, is_current=1,
        valid_from=_NOW[:10],
        **fields,
        is_overridden=is_overridden, override_score_x10=override_score_x10,
        override_profile=profile_for_score_x10(override_score_x10) if override_score_x10 else None,
        override_reason=(
            "Kunde hat nach ausfuehrlichem Gespraech seine Risikoneigung "
            "begruendet anders eingeschaetzt" if is_overridden else None
        ),
        # Override um >= 2 Profilbaender nach oben verlangt beides.
        override_client_confirmed=1 if is_overridden else 0,
        override_warning_delivered=1 if is_overridden else 0,
        assessed_at=_NOW, assessed_by=advisor.id,
        created_at=_NOW, updated_at=_NOW,
    ))
    s.commit()


def test_override_upward_no_longer_produces_false_positive_cap_warning(session_factory):
    """Kontrollrunde 2026-09-20: berechnetes Profil Defensiv (Score 30, Cap
    45%) wurde auf Wachstumsorientiert (Override-Score 75, Cap 80%)
    uebersteuert. Allokation nutzt 60% Risiko-Anteil -- innerhalb des
    (hoeheren) Override-Caps, aber ausserhalb des berechneten Caps. Vorher
    (Vergleich gegen final_score_x10) erzeugte das eine spurious Warnung."""
    with session_factory() as s:
        advisor, mandate = _seed(s)
        ta, policy = _seed_ta_within_budget(s, mandate, advisor, risky_bps=6000)
        _seed_house_matrix_bands(s, policy)
        _seed_risk_assessment(
            s, mandate, advisor,
            final_score_x10=30, is_overridden=1, override_score_x10=75,
        )
        warnings = detect_suitability_mismatches(s, mandate)
    assert not any("HouseMatrix-Cap" in w for w in warnings), warnings


def test_override_downward_now_detects_real_cap_violation(session_factory):
    """Kontrollrunde 2026-09-20: berechnetes Profil Wachstumsorientiert
    (Score 75, Cap 80%) wurde auf Defensiv (Override-Score 35, Cap 45%)
    uebersteuert. Allokation nutzt weiterhin 60% Risiko-Anteil -- innerhalb
    des berechneten (nicht mehr gueltigen) Caps, aber ausserhalb des
    tatsaechlichen Override-Caps. Vorher (Vergleich gegen final_score_x10)
    wurde diese echte Ueberschreitung NIE erkannt (Fail-Open)."""
    with session_factory() as s:
        advisor, mandate = _seed(s)
        ta, policy = _seed_ta_within_budget(s, mandate, advisor, risky_bps=6000)
        _seed_house_matrix_bands(s, policy)
        _seed_risk_assessment(
            s, mandate, advisor,
            final_score_x10=75, is_overridden=1, override_score_x10=35,
        )
        warnings = detect_suitability_mismatches(s, mandate)
    assert any("HouseMatrix-Cap 45.0 % (Defensiv)" in w for w in warnings), warnings


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
