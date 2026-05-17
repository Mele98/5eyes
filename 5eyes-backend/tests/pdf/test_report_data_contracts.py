from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace


BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from routers import pdf_reports


def test_anlagestrategie_report_uses_target_allocation_model_fields():
    assessment = SimpleNamespace(
        final_profile="Ausgewogen",
        investment_horizon_years=12,
    )
    allocation = SimpleNamespace(
        target_equities_bps=5000,
        target_bonds_bps=2500,
        target_real_estate_bps=1500,
        target_alternatives_bps=500,
        target_liquidity_bps=500,
    )
    cma = SimpleNamespace(
        equity_ch_return_bps=600,
        bonds_chf_ig_return_bps=200,
        real_estate_ch_return_bps=350,
        alternatives_gold_return_bps=150,
        liquidity_return_bps=50,
        equity_ch_vol_bps=1400,
        bonds_chf_ig_vol_bps=450,
        real_estate_ch_vol_bps=800,
        alternatives_gold_vol_bps=1200,
        liquidity_vol_bps=50,
    )

    data = pdf_reports._build_anlagestrategie_data(assessment, allocation, cma)

    assert data.target_allocation_bps == {
        "equities": 5000,
        "bonds": 2500,
        "real_estate": 1500,
        "alternatives": 500,
        "liquidity": 500,
    }
    assert data.cma_expected_return_bps == 412
    assert data.cma_expected_vol_bps == 995
    assert data.horizon_years == 12
    assert data.risk_profile_label == "Ausgewogen"


def test_risikoprofil_report_uses_risk_assessment_model_fields():
    assessment = SimpleNamespace(
        final_profile="Wachstumsorientiert",
        risk_capacity_score_x10=80,
        risk_willingness_score_x10=70,
        investment_horizon_years=15,
        investment_horizon_label="Mehr als 12 Jahre",
        assessed_at="2026-05-17T10:00:00.000Z",
        knowledge_services_json='{"Beratung":{"known":true},"Execution only":{"known":false}}',
        knowledge_instruments_json='{"Anlagefonds":{"known":true},"Optionen":false}',
    )

    data = pdf_reports._build_risikoprofil_data(assessment)

    assert data.risk_profile_label == "Wachstumsorientiert"
    assert data.risk_capacity_score == 80
    assert data.risk_tolerance_score == 70
    assert data.experience_years == 15
    assert data.knowledge_services == {"Beratung": True, "Execution only": False}
    assert data.knowledge_instruments == {"Anlagefonds": True, "Optionen": False}


def test_pdf_reports_do_not_use_legacy_strategy_field_names():
    source = Path(pdf_reports.__file__).read_text(encoding="utf-8")

    assert "target_equities_bps" in source
    assert 'getattr(ta, "equities_bps"' not in source
    assert 'getattr(ra, "risk_profile_label"' not in source
    assert 'getattr(ra, "risk_capacity_score"' not in source
    assert 'getattr(ra, "risk_tolerance_score"' not in source
