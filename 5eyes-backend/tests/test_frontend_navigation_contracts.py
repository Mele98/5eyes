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
    assert 'id="cf-risk-context-summary"' in html
    assert 'id="cf-combined-template"' in html
    assert 'id="page-ub"' not in html
    assert 'id="ub-review-strip"' not in html
    assert "#cf-goals-projection .projection-grid" in html
    assert "if(templateGrid)templateGrid.classList.add('projection-grid');" in html


def test_cashflow_projection_renders_compact_hud_not_component_wall():
    html = HTML_PATH.read_text(encoding="utf-8")
    block = html.split("function renderCashflowProjection(data) {", 1)[1].split("function buildWealthPositionPayload", 1)[0]

    assert "Cashflow-HUD" in block
    assert "Einnahmen" in block
    assert "Ausgaben" in block
    assert "Sparquote" in block
    assert "Verm\\u00f6gensverzehr" in block
    assert "Cashflow-Projektion nach Komponenten" not in html


def test_allocation_donut_legend_uses_bucket_target_amounts():
    html = HTML_PATH.read_text(encoding="utf-8")
    apply_block = html.split("function applyAllocationEngineResult(result){", 1)[1].split("function renderAllocationWarnings", 1)[0]
    legend_block = html.split("function buildDLegend(){", 1)[1].split("function syncAllocationDonutFromStrategyState", 1)[0]

    assert "chfTarget:Math.round((Number(bucket.target_amount_rappen||0))/100)" in apply_block
    assert "var targetChf=Number(r.chfTarget||0);" in legend_block
    assert "if(!(targetChf>0))targetChf=Math.round(TOTAL*Number(r.soll||0)/100)" in legend_block


def test_active_combined_step_logic_no_longer_uses_old_ub_runtime_hooks():
    html = HTML_PATH.read_text(encoding="utf-8")

    assert "updateCfRiskContextSummary" in html
    assert "updateUbRiskContextSummary" not in html
    assert "function applyAllocationEngineResultLegacy(" not in html
    assert "normalizeVisibleMojibake(document.getElementById('page-cf')||document.body);" in html
    assert "getElementById('page-ub')" not in html
    assert "querySelector('#page-ub" not in html
    assert "#page-ub .g2,#page-al .g2" not in html
    assert "#page-ub .chart,#page-al .chart" not in html
