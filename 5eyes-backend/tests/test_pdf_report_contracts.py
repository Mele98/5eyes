from pathlib import Path


PDF_REPORTS_PATH = Path(__file__).resolve().parents[1] / "routers" / "pdf_reports.py"


def test_pdf_reports_query_recommendation_positions_by_run_id():
    source = PDF_REPORTS_PATH.read_text(encoding="utf-8")

    assert "RecommendationPosition.recommendation_run_id" not in source
    assert "RecommendationPosition.run_id == last_run.id" in source

