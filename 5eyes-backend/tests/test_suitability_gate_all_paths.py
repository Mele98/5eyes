"""Mega-Audit (2026-08-04), Compliance-Dimension: das FIDLEG-Suitability-
Opt-in-Gate (Welle 2.1, test_suitability_optin_gate.py) war nur in EINEM von
vier Endpoints verdrahtet, die eine TargetAllocation/RecommendationRun
erzeugen -- routers/allocation.py::generate_target_allocation_endpoint. Drei
weitere, produktive Umgehungspfade blieben ungegated, auch wenn
require_suitability_before_recommendation=True gesetzt war:

1. routers/allocation.py::create_target_allocation (direktes POST) --
   pruefte nur require_strategy_ready_assessment() (Vollstaendigkeit),
   NICHT die 365-Tage-Freshness aus audit_mandate_suitability().
2. routers/review.py::create_recommendation_run (manueller Draft) -- eigene,
   noch schwaechere Regel (nur "existiert ein aktuelles RiskAssessment mit
   vollstaendigem Score", keine Freshness-Pruefung).
3. routers/review.py::generate_recommendation_run_endpoint -- GAR KEIN
   Suitability-Bezug, weder Vollstaendigkeit noch Freshness.

Diese Suite verifiziert das identische Opt-in-Gate (Flag AUS -> kein
Aufruf/kein Block; Flag AN + nicht-konform -> 409; Flag AN + konform ->
Run laeuft durch) jetzt an allen drei nachgezogenen Stellen -- exakt nach
dem in test_suitability_optin_gate.py etablierten Muster.
"""
from __future__ import annotations

import sys
import uuid
from pathlib import Path

import pytest
from fastapi import HTTPException

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))
TESTS_ROOT = Path(__file__).resolve().parent
if str(TESTS_ROOT) not in sys.path:
    sys.path.insert(0, str(TESTS_ROOT))

import routers.allocation as alloc
import routers.review as review
from main import app  # noqa: F401 (erzwingt vollstaendige Modell-Registrierung, inkl. tenants)
from models.allocation import OptimizerPolicy
from models.mandates import Mandate
from models.users import User
from schemas.allocation import TargetAllocationCreate, TargetAllocationGenerateRequest
from schemas.review import RecommendationGenerateRequest, RecommendationRunCreate
from test_suitability_optin_gate import _seed_mandate, session_factory  # noqa: E402,F401


def _current_policy_id(session_factory, mid: str) -> str:
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        policy = s.query(OptimizerPolicy).filter(OptimizerPolicy.is_current == 1).first()
        assert policy, "ensure_runtime_reference_data sollte eine aktuelle Policy angelegt haben"
        return policy.id


# ===========================================================================
# 1. create_target_allocation (routers/allocation.py, direktes POST)
# ===========================================================================


class _FakeClient:
    def __init__(self, host="127.0.0.1"):
        self.host = host


class _FakeRequest:
    def __init__(self, host="127.0.0.1"):
        self.headers = {}
        self.client = _FakeClient(host)


def _target_allocation_body() -> TargetAllocationCreate:
    return TargetAllocationCreate(
        target_equities_bps=4000, target_bonds_bps=3000, target_real_estate_bps=1000,
        target_alternatives_bps=1000, target_liquidity_bps=1000,
        band_equities_min_bps=3000, band_equities_max_bps=5000,
        band_bonds_min_bps=2000, band_bonds_max_bps=4000,
        band_real_estate_min_bps=0, band_real_estate_max_bps=2000,
        band_alternatives_min_bps=0, band_alternatives_max_bps=2000,
        band_liquidity_min_bps=0, band_liquidity_max_bps=2000,
        policy_id="placeholder",
    )


def test_create_target_allocation_gate_off_proceeds(session_factory, monkeypatch):
    advisor_id, _cid, mid = _seed_mandate(session_factory)
    assert alloc.settings.require_suitability_before_recommendation is False
    # 2026-08 (asset-allocation-stochastic-core): manuelles Erzeugen ist im
    # stochastischen Modus (Produktions-Default) grundsaetzlich gesperrt
    # (409, "Bitte den Engine-Generate-Pfad verwenden"). Dieser Test prueft
    # das Suitability-Gate, nicht diese Sperre -- daher house_matrix-Modus.
    monkeypatch.setattr(alloc.settings, "optimizer_mode", "house_matrix")

    def _fail_audit(*_a, **_k):  # pragma: no cover
        raise AssertionError("Audit darf bei ausgeschaltetem Flag nicht laufen")
    monkeypatch.setattr(alloc, "audit_mandate_suitability", _fail_audit)

    with session_factory() as s:
        advisor = s.query(User).filter(User.id == advisor_id).first()
        policy_id = _current_policy_id(session_factory, mid)
        body = _target_allocation_body()
        body.policy_id = policy_id
        result = alloc.create_target_allocation(mandate_id=mid, body=body, request=_FakeRequest(), db=s, current_user=advisor)
        assert result.id


def test_create_target_allocation_gate_on_noncompliant_blocks_409(session_factory, monkeypatch):
    advisor_id, _cid, mid = _seed_mandate(session_factory)
    monkeypatch.setattr(alloc.settings, "require_suitability_before_recommendation", True)
    monkeypatch.setattr(
        alloc, "audit_mandate_suitability",
        lambda db, mandate: {"is_compliant": False, "fidleg_basis": "Art. 11/13 FIDLEG"},
    )

    with session_factory() as s:
        advisor = s.query(User).filter(User.id == advisor_id).first()
        policy_id = _current_policy_id(session_factory, mid)
        body = _target_allocation_body()
        body.policy_id = policy_id
        with pytest.raises(HTTPException) as exc_info:
            alloc.create_target_allocation(mandate_id=mid, body=body, request=_FakeRequest(), db=s, current_user=advisor)
        assert exc_info.value.status_code == 409
        assert "FIDLEG" in exc_info.value.detail


def test_create_target_allocation_gate_on_compliant_proceeds(session_factory, monkeypatch):
    advisor_id, _cid, mid = _seed_mandate(session_factory)
    monkeypatch.setattr(alloc.settings, "optimizer_mode", "house_matrix")
    monkeypatch.setattr(alloc.settings, "require_suitability_before_recommendation", True)
    monkeypatch.setattr(
        alloc, "audit_mandate_suitability",
        lambda db, mandate: {"is_compliant": True, "fidleg_basis": "Art. 11/13 FIDLEG"},
    )

    with session_factory() as s:
        advisor = s.query(User).filter(User.id == advisor_id).first()
        policy_id = _current_policy_id(session_factory, mid)
        body = _target_allocation_body()
        body.policy_id = policy_id
        result = alloc.create_target_allocation(mandate_id=mid, body=body, request=_FakeRequest(), db=s, current_user=advisor)
        assert result.id


# ===========================================================================
# 2. create_recommendation_run (routers/review.py, manueller Draft-POST)
# ===========================================================================


def test_create_recommendation_run_gate_off_proceeds(session_factory, monkeypatch):
    advisor_id, _cid, mid = _seed_mandate(session_factory)
    assert review.settings.require_suitability_before_recommendation is False

    def _fail_audit(*_a, **_k):  # pragma: no cover
        raise AssertionError("Audit darf bei ausgeschaltetem Flag nicht laufen")
    monkeypatch.setattr(review, "audit_mandate_suitability", _fail_audit)

    with session_factory() as s:
        advisor = s.query(User).filter(User.id == advisor_id).first()
        policy_id = _current_policy_id(session_factory, mid)
        body = RecommendationRunCreate(run_type="Optimizer", policy_id=policy_id)
        result = review.create_recommendation_run(mandate_id=mid, body=body, request=_FakeRequest(), db=s, current_user=advisor)
        assert result.id


def test_create_recommendation_run_gate_on_noncompliant_blocks_409(session_factory, monkeypatch):
    advisor_id, _cid, mid = _seed_mandate(session_factory)
    monkeypatch.setattr(review.settings, "require_suitability_before_recommendation", True)
    monkeypatch.setattr(
        review, "audit_mandate_suitability",
        lambda db, mandate: {"is_compliant": False, "fidleg_basis": "Art. 11/13 FIDLEG"},
    )

    with session_factory() as s:
        advisor = s.query(User).filter(User.id == advisor_id).first()
        policy_id = _current_policy_id(session_factory, mid)
        body = RecommendationRunCreate(run_type="Optimizer", policy_id=policy_id)
        with pytest.raises(HTTPException) as exc_info:
            review.create_recommendation_run(mandate_id=mid, body=body, request=_FakeRequest(), db=s, current_user=advisor)
        assert exc_info.value.status_code == 409
        assert "FIDLEG" in exc_info.value.detail


def test_create_recommendation_run_gate_on_compliant_proceeds(session_factory, monkeypatch):
    advisor_id, _cid, mid = _seed_mandate(session_factory)
    monkeypatch.setattr(review.settings, "require_suitability_before_recommendation", True)
    monkeypatch.setattr(
        review, "audit_mandate_suitability",
        lambda db, mandate: {"is_compliant": True, "fidleg_basis": "Art. 11/13 FIDLEG"},
    )

    with session_factory() as s:
        advisor = s.query(User).filter(User.id == advisor_id).first()
        policy_id = _current_policy_id(session_factory, mid)
        body = RecommendationRunCreate(run_type="Optimizer", policy_id=policy_id)
        result = review.create_recommendation_run(mandate_id=mid, body=body, request=_FakeRequest(), db=s, current_user=advisor)
        assert result.id


# ===========================================================================
# 3. generate_recommendation_run_endpoint (routers/review.py) -- vorher GAR
#    KEIN Suitability-Bezug, der breiteste der drei Umgehungspfade.
# ===========================================================================


def test_generate_recommendation_run_gate_off_proceeds(session_factory, monkeypatch):
    advisor_id, _cid, mid = _seed_mandate(session_factory)
    assert review.settings.require_suitability_before_recommendation is False

    def _fail_audit(*_a, **_k):  # pragma: no cover
        raise AssertionError("Audit darf bei ausgeschaltetem Flag nicht laufen")
    monkeypatch.setattr(review, "audit_mandate_suitability", _fail_audit)

    with session_factory() as s:
        advisor = s.query(User).filter(User.id == advisor_id).first()
        body = RecommendationGenerateRequest()
        result = review.generate_recommendation_run_endpoint(
            mandate_id=mid, body=body, request=_FakeRequest(), db=s, current_user=advisor,
        )
        assert result["run"].id


def test_generate_recommendation_run_gate_on_noncompliant_blocks_409(session_factory, monkeypatch):
    advisor_id, _cid, mid = _seed_mandate(session_factory)
    monkeypatch.setattr(review.settings, "require_suitability_before_recommendation", True)
    monkeypatch.setattr(
        review, "audit_mandate_suitability",
        lambda db, mandate: {"is_compliant": False, "fidleg_basis": "Art. 11/13 FIDLEG"},
    )

    with session_factory() as s:
        advisor = s.query(User).filter(User.id == advisor_id).first()
        body = RecommendationGenerateRequest()
        with pytest.raises(HTTPException) as exc_info:
            review.generate_recommendation_run_endpoint(
                mandate_id=mid, body=body, request=_FakeRequest(), db=s, current_user=advisor,
            )
        assert exc_info.value.status_code == 409
        assert "FIDLEG" in exc_info.value.detail


def test_generate_recommendation_run_gate_on_compliant_proceeds(session_factory, monkeypatch):
    advisor_id, _cid, mid = _seed_mandate(session_factory)
    monkeypatch.setattr(review.settings, "require_suitability_before_recommendation", True)
    monkeypatch.setattr(
        review, "audit_mandate_suitability",
        lambda db, mandate: {"is_compliant": True, "fidleg_basis": "Art. 11/13 FIDLEG"},
    )

    with session_factory() as s:
        advisor = s.query(User).filter(User.id == advisor_id).first()
        body = RecommendationGenerateRequest()
        result = review.generate_recommendation_run_endpoint(
            mandate_id=mid, body=body, request=_FakeRequest(), db=s, current_user=advisor,
        )
        assert result["run"].id
