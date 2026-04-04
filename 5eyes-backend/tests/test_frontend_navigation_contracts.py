from pathlib import Path
import re


HTML_PATH = Path(__file__).resolve().parents[2] / "5eyes-electron" / "frontend" / "5eyes_v2.html"
VALID_PAGE_KEYS = {"sd", "vg", "cf", "ub", "rp", "al", "po", "rv", "sr"}


def test_all_go_targets_reference_known_pages():
    html = HTML_PATH.read_text(encoding="utf-8")
    targets = set(re.findall(r"go\('([a-z]{2})'", html))

    assert targets
    assert targets <= VALID_PAGE_KEYS


def test_event_logging_goals_action_returns_to_combined_cashflow_step():
    html = HTML_PATH.read_text(encoding="utf-8")

    assert "if(action==='goals')go('cf');" in html
    assert "if(action==='goals')go('uz');" not in html


def test_frontend_navigation_keeps_nine_step_page_sequence():
    html = HTML_PATH.read_text(encoding="utf-8")

    assert "const pages={sd:0,vg:1,cf:2,ub:3,rp:4,al:5,po:6,rv:7,sr:8};" in html


def test_summary_recipe_print_binding_uses_explicit_button_id():
    html = HTML_PATH.read_text(encoding="utf-8")

    assert 'id="sr-recipe-print"' in html
    assert "var summaryRecipePrint=document.getElementById('sr-recipe-print');" in html


def test_combined_cashflow_projection_has_own_root_and_responsive_grid():
    html = HTML_PATH.read_text(encoding="utf-8")

    assert 'id="cf-goals-projection"' in html
    assert "#cf-goals-projection .projection-grid" in html
    assert "if(ubGrid)ubGrid.classList.add('projection-grid');" in html


def test_active_combined_step_logic_no_longer_uses_old_ub_runtime_hooks():
    html = HTML_PATH.read_text(encoding="utf-8")

    assert "updateCfRiskContextSummary" in html
    assert "updateUbRiskContextSummary" not in html
    assert "function applyAllocationEngineResultLegacy(" not in html
    assert "normalizeVisibleMojibake(document.getElementById('page-cf')||document.body);" in html
    assert "#page-ub .g2,#page-al .g2" not in html
    assert "#page-ub .chart,#page-al .chart" not in html
