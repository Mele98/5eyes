"""Tests fuer den Stage-8-Aggregations-Helper.

Aggregiert Per-Mandate-Shadow-Verdicts zu einem Owner-Verifikations-Report
nach Methodology §4 Gesamt-Verdikt. Unit-Tests pruefen die reine Verdict-
Logik; Integration-Tests pruefen DB-Aggregation + Admin-Endpoint.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

BACKEND_ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = Path(__file__).resolve().parent
for path in (BACKEND_ROOT, TESTS_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from database import get_db
from main import app
from models.mandates import Mandate
from services.auth import require_admin
from services.shadow_comparison import (
    _gesamt_verdikt,
    _summarize_mandate_for_aggregate,
    aggregate_shadow_comparisons,
    classify_shadow_verdict,
)
from test_optimizer_shadow_mode import _seed_realistic_mandate, session_factory
from test_shadow_stochastic_persistence import _fake_optimizer_result

import services.portfolio_engine as pe


def _client_with_admin(session_factory, admin_id: str = "admin-stage8"):
    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    admin_user = SimpleNamespace(id=admin_id, full_name="Admin Stage8", email="admin@example.test")
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[require_admin] = lambda: admin_user
    return TestClient(app)


# --- Pure unit tests: _gesamt_verdikt ----------------------------------

def test_gesamt_verdikt_empty_counts_blocks_with_reason():
    ready, reason = _gesamt_verdikt({"green": 0, "yellow": 0, "red": 0})
    assert ready is False
    assert "Keine" in reason


def test_gesamt_verdikt_red_hard_blocks():
    ready, reason = _gesamt_verdikt({"green": 5, "yellow": 0, "red": 1})
    assert ready is False
    assert "RED" in reason


def test_gesamt_verdikt_below_minimum_sample_blocks():
    ready, reason = _gesamt_verdikt({"green": 2, "yellow": 0, "red": 0})
    assert ready is False
    assert "mindestens 3" in reason


def test_gesamt_verdikt_yellow_majority_blocks():
    # 1/3 GREEN, 2/3 YELLOW: unter 2/3-Schwelle.
    ready, reason = _gesamt_verdikt({"green": 1, "yellow": 2, "red": 0})
    assert ready is False
    assert "GREEN-Anteil" in reason


def test_gesamt_verdikt_green_majority_releases():
    # 2/3 GREEN, 1/3 YELLOW: genau auf der Schwelle.
    ready, reason = _gesamt_verdikt({"green": 2, "yellow": 1, "red": 0})
    assert ready is True
    assert "2/3 GREEN" in reason
    assert "Gesamt-Verdikt erfuellt" in reason or "Gesamt-Verdikt erfüllt" in reason


def test_gesamt_verdikt_all_green_releases():
    ready, reason = _gesamt_verdikt({"green": 4, "yellow": 0, "red": 0})
    assert ready is True


# --- Pure unit test: summary projection --------------------------------

def test_summarize_keeps_only_methodology_fields():
    payload = {
        "mandate_id": "m1",
        "target_allocation_id": "ta-1",
        "verdict": "green",
        "verdict_notes": ["ok"],
        "total_drift_bps": 800,
        "risky_drift_bps": 250,
        "limiting_factor": "bandbreite",
        "optimization_status": "converged",
        "elapsed_ms": {"stochastic": 1200, "budget_ms": 8000},
        "goal_counts": {"n_goals_achievable_st": 3, "n_hard_unreachable_st": 0},
        "budget_compliance": {"house_matrix": True, "stochastic": True},
        "raw_shadow_payload": {"giant": "blob"},  # NICHT in summary
        "shadow_allocation_bps": {"equities": 5000},  # NICHT in summary
    }
    summary = _summarize_mandate_for_aggregate(payload)
    assert summary["mandate_id"] == "m1"
    assert summary["elapsed_ms_stochastic"] == 1200
    assert summary["goal_counts"]["n_hard_unreachable_st"] == 0
    assert "raw_shadow_payload" not in summary
    assert "shadow_allocation_bps" not in summary


def test_converged_robustified_is_yellow_not_red():
    verdict = classify_shadow_verdict(
        total_drift_bps=185,
        risky_drift_bps=47,
        budget_compliance_st=True,
        n_hard_unreachable_st=0,
        elapsed_ms=2036,
        limiting_factor="bandbreite",
        optimization_status="converged_robustified",
    )
    assert verdict["status"] == "YELLOW"
    assert "optimization_status=converged_robustified" in verdict["reasons"]


# --- Integration: empty DB -------------------------------------------

def test_aggregate_empty_db_returns_not_ready(session_factory):
    with session_factory() as s:
        result = aggregate_shadow_comparisons(s)
    assert result["counts"] == {"green": 0, "yellow": 0, "red": 0, "total": 0}
    assert result["default_switch_ready"] is False
    assert result["examples"] == {"green": [], "yellow": [], "red": []}
    assert result["errors"] == []


# --- Integration: one mandate with shadow data ------------------------

def test_aggregate_includes_persisted_shadow_mandate(session_factory, monkeypatch):
    advisor_id, _cid, mid, _aid, _gid = _seed_realistic_mandate(
        session_factory, suffix="s8agg-one"
    )
    monkeypatch.setattr(pe.settings, "optimizer_mode", "shadow_stochastic")
    monkeypatch.setattr(pe, "_run_stochastic_optimizer_pass", _fake_optimizer_result)

    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        pe.generate_target_allocation(s, mandate, advisor_id, preferences=None)
        s.commit()

    with session_factory() as s:
        result = aggregate_shadow_comparisons(s)

    assert result["counts"]["total"] == 1
    # 1 Mandat ist zu wenig (Methodology §4 verlangt ≥ 3) — Default bleibt gesperrt.
    assert result["default_switch_ready"] is False
    assert "mindestens 3" in result["default_switch_reason"]
    # Aber das Mandat MUSS klassifiziert sein.
    total_verdicts = (
        result["counts"]["green"] + result["counts"]["yellow"] + result["counts"]["red"]
    )
    assert total_verdicts == 1
    # Das eine Mandat erscheint als Beispiel in seinem Verdict-Bucket.
    represented = []
    for verdict in ("green", "yellow", "red"):
        represented.extend(result["examples"][verdict])
    assert len(represented) == 1
    assert represented[0]["mandate_id"] == mid
    assert represented[0]["verdict"] in {"green", "yellow", "red"}


# --- Endpoint integration --------------------------------------------

def test_admin_shadow_comparison_aggregate_endpoint(session_factory, monkeypatch):
    advisor_id, _cid, mid, _aid, _gid = _seed_realistic_mandate(
        session_factory, suffix="s8agg-ep"
    )
    monkeypatch.setattr(pe.settings, "optimizer_mode", "shadow_stochastic")
    monkeypatch.setattr(pe, "_run_stochastic_optimizer_pass", _fake_optimizer_result)

    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        pe.generate_target_allocation(s, mandate, advisor_id, preferences=None)
        s.commit()

    with _client_with_admin(session_factory, admin_id=advisor_id) as client:
        response = client.get("/admin/system/shadow-comparison-aggregate")
    app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()
    assert set(data.keys()) >= {
        "counts",
        "percentages",
        "examples",
        "default_switch_ready",
        "default_switch_reason",
        "errors",
    }
    assert data["counts"]["total"] == 1
    assert data["percentages"]["total"] == 1
    # Mandat ist im Examples-Bucket gemäß Verdict.
    bucket = data["examples"][
        ["green", "yellow", "red"][["green", "yellow", "red"].index(
            next(v for v in ("green", "yellow", "red") if data["counts"][v] == 1)
        )]
    ]
    assert bucket
    assert bucket[0]["mandate_id"] == mid
