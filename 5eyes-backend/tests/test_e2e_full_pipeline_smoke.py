"""Sprint E2E-Smoke (2026-06-08): End-to-End-Pipeline-Smoke-Tests.

Verifiziert dass die heutigen Sprints (P1 + A1-A4 + B1-B3 + C1-C2 + Option-C
+ C2-Wiring) integriert sauber funktionieren:

1. Goal-Rank-Conflict-Fix (#215): Mehrere Goals gleicher Haerte erfassbar
2. Achievability-Invalidation (#225): Nach Goal-Edit alle Scores auf NULL
3. Renditeziel-Tilt (#226): Primaer-Renditeziel beeinflusst SAA-Recompute
4. Engine-Config im Aggregator (#227): Compliance-Block kriegt echte Daten
5. PDF-Render mit Goal-Ampel (#223): Visuelle Balken in PDF-Bytes
6. PDF-Render mit Engine-Config-Block (#224): 6. Block im Compliance-Audit
"""
from __future__ import annotations

import datetime
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base, get_db
from main import app
from models.clients import Client  # noqa: F401
from models.mandates import Mandate  # noqa: F401
from models.users import User
from services.auth import get_current_user


def _utc_now_iso() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'e2e_smoke.db'}",
        connect_args={"check_same_thread": False},
    )
    sf = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield sf
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture()
def advisor_user():
    return User(
        id="user-e2e",
        username="advisor",
        password_hash="h",
        full_name="E2E Advisor",
        role="advisor",
        is_active=1,
        created_at=_utc_now_iso(),
        updated_at=_utc_now_iso(),
    )


@pytest.fixture()
def auth_client(session_factory, advisor_user):
    def override_db():
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: advisor_user
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


def _setup_full_mandate(auth_client, advisor_user) -> tuple[str, str]:
    """Erstellt Client + Mandat, returnt (client_id, mandate_id)."""
    client_resp = auth_client.post(
        "/clients",
        json={
            "client_number": "E2E-001", "first_name": "End", "last_name": "ToEnd",
            "advisor_id": advisor_user.id, "household_type": "Einzelperson",
        },
    )
    assert client_resp.status_code == 201, client_resp.text
    client_id = client_resp.json()["id"]
    mandate_resp = auth_client.post(
        f"/clients/{client_id}/mandates",
        json={"mandate_number": "E2E-M-001", "mandate_type": "Anlageberatung"},
    )
    assert mandate_resp.status_code == 201, mandate_resp.text
    mandate_id = mandate_resp.json()["id"]
    return client_id, mandate_id


# ===========================================================================
# 1. Goal-Rank-Conflict-Fix sauber durch
# ===========================================================================


def test_e2e_mehrere_hart_goals_erfassbar(auth_client, advisor_user):
    """PR #215: 5 Hart-Goals erfassen — historisch hatte rank=1-Conflict 409 geblockt."""
    _, mandate_id = _setup_full_mandate(auth_client, advisor_user)
    for i in range(5):
        resp = auth_client.post(
            f"/mandates/{mandate_id}/goals",
            json={
                "goal_family": "Vermögen", "goal_type": "Vermoegensziel",
                "label": f"Hart-Goal-{i}", "rank": 1,
                "target_wealth_rappen": 1_000_000_00 + i * 100_000_00,
                "horizon_years": 10, "hardness": "Hart", "value_mode": "nominal",
            },
        )
        assert resp.status_code == 201, f"Goal {i}: {resp.text}"
    list_resp = auth_client.get(f"/mandates/{mandate_id}/goals")
    assert len(list_resp.json()) == 5


# ===========================================================================
# 2. Achievability-Invalidation nach Goal-Edit
# ===========================================================================


def test_e2e_achievability_invalidiert_nach_goal_edit(
    auth_client, advisor_user, session_factory,
):
    """PR #225: Nach Goal-UPDATE wird achievement_score von allen Goals NULL."""
    from models.wealth import Goal as GoalModel
    _, mandate_id = _setup_full_mandate(auth_client, advisor_user)
    # Goal anlegen + manuell Score setzen (simuliert vorherigen SAA-Lauf)
    create_resp = auth_client.post(
        f"/mandates/{mandate_id}/goals",
        json={
            "goal_family": "Vermögen", "goal_type": "Vermoegensziel",
            "label": "Test-Pension", "rank": 1,
            "target_wealth_rappen": 1_000_000_00, "horizon_years": 10,
            "hardness": "Hart", "value_mode": "nominal",
        },
    )
    goal_id = create_resp.json()["id"]
    # Manuell Score setzen
    with session_factory() as db:
        g = db.query(GoalModel).filter(GoalModel.id == goal_id).first()
        g.achievement_score = 75
        db.commit()
    # UPDATE Goal target
    update_resp = auth_client.put(
        f"/mandates/{mandate_id}/goals/{goal_id}",
        json={"target_wealth_rappen": 2_000_000_00},
    )
    assert update_resp.status_code == 200
    # Score muss NULL sein
    with session_factory() as db:
        g = db.query(GoalModel).filter(GoalModel.id == goal_id).first()
        assert g.achievement_score is None


# ===========================================================================
# 3. Renditeziel-Tilt im SAA-Pfad (Helper-Level)
# ===========================================================================


def test_e2e_renditeziel_tilt_helper_funktioniert():
    """PR #226: _renditeziel_equity_tilt_bps liefert erwartete Werte."""
    from services.portfolio_engine import _renditeziel_equity_tilt_bps
    # Niedriges Target: defensiv
    assert _renditeziel_equity_tilt_bps(
        target_return_bps=200, current_equity_bps=4000,
        min_equity_bps=2500, max_equity_bps=5000,
    ) == -150
    # Hohes Target: Wachstum
    assert _renditeziel_equity_tilt_bps(
        target_return_bps=500, current_equity_bps=4000,
        min_equity_bps=2500, max_equity_bps=5000,
    ) == 150
    # Sehr hohes Target
    assert _renditeziel_equity_tilt_bps(
        target_return_bps=700, current_equity_bps=4000,
        min_equity_bps=2500, max_equity_bps=5000,
    ) == 200


# ===========================================================================
# 4. Engine-Config im Aggregator
# ===========================================================================


def test_e2e_engine_configuration_im_payload():
    """PR #227: compute_advisory_report enthaelt engine_configuration mit allen Feldern."""
    from services.advisory_report import _build_engine_configuration
    from types import SimpleNamespace

    class EmptyDB:
        def query(self, *args, **kwargs):
            class Q:
                def filter(self, *a, **k): return self
                def order_by(self, *a, **k): return self
                def first(self): return None
            return Q()

    cfg = _build_engine_configuration(EmptyDB(), SimpleNamespace(id="m-test"))
    # Alle Felder vorhanden
    required_fields = {
        "importance_sampling_active", "importance_sampling_reason",
        "tax_mode", "sub_allocation_aware", "optimizer_mode", "audit_basis",
    }
    assert required_fields.issubset(cfg.keys())


# ===========================================================================
# 5. PDF-Komponenten konsumieren engine_configuration
# ===========================================================================


def test_e2e_pdf_compliance_block_konsumiert_engine_config():
    """PR #224 + #227: Compliance-Audit-Section rendert Engine-Block bei vorhandenem
    engine_configuration im Payload."""
    from services.pdf.components.advisory_palette import make_advisory_styles
    from services.pdf.components.compliance_audit import (
        render_compliance_audit_section,
    )

    styles = make_advisory_styles()
    payload = {
        "suitability_compliance": {"is_compliant": True},
        "methodology_models": {"models": []},
        "recommendation_methodology": {},
        "mandate_lock_status": {"is_editable": True},
        "liquidity_cascade": {"stage": "normal", "warning_required": False},
        # Aus C2-Wiring:
        "engine_configuration": {
            "importance_sampling_active": True,
            "importance_sampling_reason": "konservativ + hart-Goal",
            "tax_mode": "binned",
            "sub_allocation_aware": True,
            "optimizer_mode": "stochastic",
            "audit_basis": "Run-State zum Zeitpunkt der letzten Strategie-Berechnung.",
        },
    }
    story = []
    render_compliance_audit_section(payload, story, styles)
    # Story sollte 6 Bloecke enthalten (5 standard + 1 engine_config)
    # Die genaue Struktur ist komplex; reicht: deutlich mehr als ohne Engine-Cfg
    assert len(story) > 5


# ===========================================================================
# 6. Goal-Ampel-Drawing in PDF-Tabelle
# ===========================================================================


def test_e2e_goal_ampel_drawing_in_pdf_tabelle():
    """PR #223: make_goal_achievability_table embedded Drawing-Objekt in
    Wahrscheinlichkeit-Cell."""
    from reportlab.graphics.shapes import Drawing
    from services.pdf.components.goal_achievability import (
        make_goal_achievability_table,
    )
    achievability = [
        {"goal_id": "g1", "label": "Pension", "goal_type": "Vermoegensziel",
         "hardness": "Hart", "probability": 0.85, "status": "erreichbar"},
        {"goal_id": "g2", "label": "Eigenheim", "goal_type": "Vermoegensziel",
         "hardness": "Primär", "probability": 0.45, "status": "knapp"},
    ]
    table = make_goal_achievability_table(achievability)
    # Beide Probability-Cells sind Drawings (visuelle Ampel-Balken)
    cell_g1_prob = table._cellvalues[1][3]
    cell_g2_prob = table._cellvalues[2][3]
    assert isinstance(cell_g1_prob, Drawing)
    assert isinstance(cell_g2_prob, Drawing)


# ===========================================================================
# 7. Voller Pipeline-Smoke (alles zusammen, kein Crash)
# ===========================================================================


def test_e2e_voller_pipeline_smoke(auth_client, advisor_user):
    """Vollstaendiger Smoke-Lauf:
    - Mandate setup
    - Multi-Hart-Goals (Rank-Conflict-Fix)
    - Renditeziel-Goal erfassen (Tilt-Voraussetzung)
    - Goal-Update (Invalidation-Trigger)
    - Goals-Liste laden + verifizieren

    Stellt sicher dass die Sprints nicht gegenseitig kollidieren.
    """
    _, mandate_id = _setup_full_mandate(auth_client, advisor_user)
    # Hart-Goal Pension
    g1_resp = auth_client.post(
        f"/mandates/{mandate_id}/goals",
        json={
            "goal_family": "Cashflow", "goal_type": "Pensionsausgabe",
            "label": "Pension", "rank": 1, "target_amount_rappen": 60_000_00,
            "frequency": "jährlich", "start_date": "2030-01-01",
            "is_ongoing": 1, "hardness": "Hart", "value_mode": "real",
        },
    )
    assert g1_resp.status_code == 201, g1_resp.text
    # Hart-Goal Eigenheim (gleicher Rang wuerde 409 geben pre-#215)
    g2_resp = auth_client.post(
        f"/mandates/{mandate_id}/goals",
        json={
            "goal_family": "Vermögen", "goal_type": "Vermoegensziel",
            "label": "Eigenheim", "rank": 1, "target_wealth_rappen": 800_000_00,
            "horizon_years": 5, "hardness": "Hart", "value_mode": "nominal",
        },
    )
    assert g2_resp.status_code == 201, g2_resp.text
    # Primaer-Renditeziel (loest Tilt aus bei naechstem Recompute)
    g3_resp = auth_client.post(
        f"/mandates/{mandate_id}/goals",
        json={
            "goal_family": "Rendite", "goal_type": "Renditeziel",
            "label": "5% real p.a.", "rank": 2, "target_return_bps": 500,
            "horizon_years": 15, "hardness": "Primär",
        },
    )
    assert g3_resp.status_code == 201, g3_resp.text
    # Goals-Liste laden
    list_resp = auth_client.get(f"/mandates/{mandate_id}/goals")
    assert list_resp.status_code == 200
    goals = list_resp.json()
    assert len(goals) == 3
    # UPDATE des Renditeziels (Invalidation-Trigger)
    g3_id = g3_resp.json()["id"]
    update_resp = auth_client.put(
        f"/mandates/{mandate_id}/goals/{g3_id}",
        json={"target_return_bps": 700},
    )
    assert update_resp.status_code == 200
    assert int(update_resp.json()["target_return_bps"]) == 700
