"""Sprint U-73 + U-74 (Roadmap-Punkte 73+74, 2026-06-03): Engine-Modell-Audit.

Hintergrund
-----------
Sprint 6+7+8 (2026-05-17) haben Nelson-Siegel + KGV-Mean-Reversion +
Risikopraemien als CMA-Felder eingefuehrt. Im Admin-CMA-Editor sind
sie pflegbar. ABER: im Berater-/Mandate-Workflow ist NICHT sichtbar,
ob diese Modelle fuer den aktuellen Run aktiv waren.

Diese Suite verifiziert services/methodology_audit.py und seine
Aggregator-Integration (Sektion 20).
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.methodology_audit import (  # noqa: E402
    KGV_BASIS,
    NS_BASIS,
    RISK_PREMIA_BASIS,
    _build_kgv_status,
    _build_ns_status,
    _build_risk_premia_status,
    audit_engine_models,
)


def _cma(**overrides):
    """Builds a CMA-Stub mit allen Modell-Feldern als None per Default."""
    base = {
        "id": "cma-001",
        "version": 7,
        "is_current": 1,
        "deleted_at": None,
        "bonds_ns_beta0_bps": None,
        "bonds_ns_beta1_bps": None,
        "bonds_ns_beta2_bps": None,
        "bonds_ns_lambda_x100": None,
        "equity_kgv_current_x10": None,
        "equity_kgv_fair_x10": None,
        "equity_kgv_alpha_x100": None,
        "real_estate_risk_premium_bps": None,
        "alternatives_risk_premium_bps": None,
    }
    base.update(overrides)
    return MagicMock(**base)


def _stub_db(cma_row):
    db = MagicMock()
    query_chain = MagicMock()
    query_chain.filter.return_value = query_chain
    query_chain.order_by.return_value = query_chain
    query_chain.first.return_value = cma_row
    db.query.return_value = query_chain
    return db


# ---------------------------------------------------------------------------
# Nelson-Siegel Status (U-73 Teil 1)
# ---------------------------------------------------------------------------

def test_ns_inactive_when_no_fields_set():
    status = _build_ns_status(_cma())
    assert status["model_key"] == "nelson_siegel"
    assert status["active"] is False
    assert status["applies_to"] == "bonds"


def test_ns_active_when_all_4_fields_set():
    cma = _cma(
        bonds_ns_beta0_bps=400,
        bonds_ns_beta1_bps=-200,
        bonds_ns_beta2_bps=80,
        bonds_ns_lambda_x100=60,
    )
    status = _build_ns_status(cma)
    assert status["active"] is True
    assert status["parameters"]["beta0_bps"] == 400
    assert status["parameters"]["lambda_x100"] == 60
    assert NS_BASIS in status["basis"] or status["basis"] == NS_BASIS


def test_ns_inactive_when_one_field_missing():
    """Partial-Set ist NICHT aktiv — alle 4 muessen gesetzt sein."""
    cma = _cma(
        bonds_ns_beta0_bps=400,
        bonds_ns_beta1_bps=-200,
        bonds_ns_beta2_bps=80,
        # lambda fehlt
    )
    status = _build_ns_status(cma)
    assert status["active"] is False


# ---------------------------------------------------------------------------
# KGV-Mean-Reversion Status (U-73 Teil 2)
# ---------------------------------------------------------------------------

def test_kgv_inactive_when_no_fields_set():
    status = _build_kgv_status(_cma())
    assert status["model_key"] == "kgv_mean_reversion"
    assert status["active"] is False
    assert status["applies_to"] == "equity"


def test_kgv_active_when_all_3_fields_set():
    cma = _cma(
        equity_kgv_current_x10=220,
        equity_kgv_fair_x10=170,
        equity_kgv_alpha_x100=15,
    )
    status = _build_kgv_status(cma)
    assert status["active"] is True
    assert status["parameters"]["kgv_current_x10"] == 220
    assert status["basis"] == KGV_BASIS


def test_kgv_inactive_when_alpha_missing():
    cma = _cma(equity_kgv_current_x10=220, equity_kgv_fair_x10=170)
    status = _build_kgv_status(cma)
    assert status["active"] is False


# ---------------------------------------------------------------------------
# Risikopraemien Status (U-74)
# ---------------------------------------------------------------------------

def test_risk_premia_inactive_when_no_fields_set():
    status = _build_risk_premia_status(_cma(), ns_active=True)
    assert status["model_key"] == "risk_premia"
    assert status["active"] is False
    assert status["blocker_reason"] == "no_premium_configured"


def test_risk_premia_inactive_without_ns_base():
    """U-74-Spezifik: Praemien aktivieren NUR mit NS als Base."""
    cma = _cma(real_estate_risk_premium_bps=200, alternatives_risk_premium_bps=300)
    status = _build_risk_premia_status(cma, ns_active=False)
    assert status["active"] is False
    assert status["blocker_reason"] == "nelson_siegel_required_as_base"


def test_risk_premia_active_with_ns_and_any_premium():
    cma = _cma(real_estate_risk_premium_bps=200)
    status = _build_risk_premia_status(cma, ns_active=True)
    assert status["active"] is True
    assert status["blocker_reason"] is None
    assert status["parameters"]["real_estate_premium_bps"] == 200


def test_risk_premia_active_with_only_alternatives_premium():
    """Eine von beiden Praemien reicht."""
    cma = _cma(alternatives_risk_premium_bps=300)
    status = _build_risk_premia_status(cma, ns_active=True)
    assert status["active"] is True


def test_risk_premia_basis_text_constant():
    cma = _cma(real_estate_risk_premium_bps=200)
    status = _build_risk_premia_status(cma, ns_active=True)
    assert status["basis"] == RISK_PREMIA_BASIS


# ---------------------------------------------------------------------------
# audit_engine_models — orchestration
# ---------------------------------------------------------------------------

def test_audit_no_cma_returns_empty():
    db = _stub_db(None)
    result = audit_engine_models(db)
    assert result["cma_id"] is None
    assert result["models"] == []
    assert result["active_count"] == 0


def test_audit_all_models_inactive():
    db = _stub_db(_cma())
    result = audit_engine_models(db)
    assert result["cma_id"] == "cma-001"
    assert len(result["models"]) == 3
    assert result["active_count"] == 0
    # Bei 0 aktiv: explizite Note
    assert any(
        "Keine erweiterten Engine-Modelle aktiv" in n
        for n in result["methodology_notes"]
    )


def test_audit_only_ns_active():
    db = _stub_db(_cma(
        bonds_ns_beta0_bps=400,
        bonds_ns_beta1_bps=-200,
        bonds_ns_beta2_bps=80,
        bonds_ns_lambda_x100=60,
    ))
    result = audit_engine_models(db)
    assert result["active_count"] == 1
    ns = next(m for m in result["models"] if m["model_key"] == "nelson_siegel")
    assert ns["active"] is True
    assert any("Bond-Renditen aus Yield-Curve" in n for n in result["methodology_notes"])


def test_audit_all_three_active():
    db = _stub_db(_cma(
        bonds_ns_beta0_bps=400,
        bonds_ns_beta1_bps=-200,
        bonds_ns_beta2_bps=80,
        bonds_ns_lambda_x100=60,
        equity_kgv_current_x10=220,
        equity_kgv_fair_x10=170,
        equity_kgv_alpha_x100=15,
        real_estate_risk_premium_bps=200,
        alternatives_risk_premium_bps=300,
    ))
    result = audit_engine_models(db)
    assert result["active_count"] == 3
    assert len(result["methodology_notes"]) == 3
    # Alle 3 Modelle aktiv
    assert all(m["active"] for m in result["models"])


def test_audit_risk_premia_blocker_when_ns_missing():
    """Praemien gesetzt aber NS nicht -> Praemien NICHT aktiv + Blocker."""
    db = _stub_db(_cma(
        real_estate_risk_premium_bps=200,
        # NS-Felder bleiben None
    ))
    result = audit_engine_models(db)
    rp = next(m for m in result["models"] if m["model_key"] == "risk_premia")
    assert rp["active"] is False
    assert rp["blocker_reason"] == "nelson_siegel_required_as_base"
    assert result["active_count"] == 0


def test_audit_db_error_returns_degraded():
    db = MagicMock()
    db.query.side_effect = RuntimeError("table missing")
    result = audit_engine_models(db)
    assert result["cma_id"] is None
    assert result["models"] == []
    assert result["active_count"] == 0


# ---------------------------------------------------------------------------
# Aggregator-Integration (Sektion 20)
# ---------------------------------------------------------------------------

def test_compute_advisory_report_includes_section_20():
    # Seit PR #110 liegt die Sektions-Verdrahtung in _compute_advisory_report_inner.
    from services.advisory_report import _compute_advisory_report_inner
    import inspect
    source = inspect.getsource(_compute_advisory_report_inner)
    assert "methodology_models" in source
    assert "Sektion 20" in source


def test_build_methodology_models_degraded_on_error():
    from services.advisory_report import _build_methodology_models
    db = MagicMock()
    db.query.side_effect = RuntimeError("simulated")
    result = _build_methodology_models(db)
    assert result["active_count"] == 0
    assert result["models"] == []
