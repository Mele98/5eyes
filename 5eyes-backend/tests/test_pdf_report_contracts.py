from pathlib import Path


PDF_REPORTS_PATH = Path(__file__).resolve().parents[1] / "routers" / "pdf_reports.py"
FRONTEND_PATH = Path(__file__).resolve().parents[2] / "5eyes-electron" / "frontend" / "5eyes_v2.html"


def test_pdf_reports_query_recommendation_positions_by_run_id():
    source = PDF_REPORTS_PATH.read_text(encoding="utf-8")

    assert "RecommendationPosition.recommendation_run_id" not in source
    assert "RecommendationPosition.run_id == last_run.id" in source


def test_pdf_reports_use_current_allocation_field_names():
    source = PDF_REPORTS_PATH.read_text(encoding="utf-8")

    assert 'getattr(ta_obj, f"{bucket}_bps"' not in source
    assert 'getattr(ta, "advisory_wealth_rappen"' not in source
    assert "advisory_wealth_at_generation_rappen" in source
    assert "target_equities_bps" in source
    assert "band_equities_min_bps" in source


def test_pdf_reports_have_server_protokoll_endpoint():
    source = PDF_REPORTS_PATH.read_text(encoding="utf-8")
    frontend = FRONTEND_PATH.read_text(encoding="utf-8")

    assert '"/mandates/{mandate_id}/reports/protokoll.pdf"' in source
    assert "render_protokoll" in source
    assert "downloadServerPdf('protokoll')" in frontend
    assert "reportType!=='protokoll'" in frontend


def test_risk_pdf_uses_actual_risk_assessment_fields():
    source = PDF_REPORTS_PATH.read_text(encoding="utf-8")

    assert '"risk_profile_label"' not in source
    assert '"risk_capacity_score"' not in source
    assert '"risk_tolerance_score"' not in source
    assert '"experience_years"' not in source
    assert "final_profile" in source
    assert "risk_capacity_score_x10" in source
    assert "risk_willingness_score_x10" in source
