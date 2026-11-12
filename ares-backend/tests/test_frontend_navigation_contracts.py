from pathlib import Path
import re
from tests.monolith_source import read_monolith_bundle  # H3/I-04: inkl. ausgelagerter Teile


HTML_PATH = Path(__file__).resolve().parents[2] / "ares-desktop" / "frontend" / "ares.html"
VALID_PAGE_KEYS = {"sd", "vg", "cf", "ub", "rp", "al", "po", "rv", "sr"}


def test_all_go_targets_reference_known_pages():
    html = read_monolith_bundle()
    targets = set(re.findall(r"go\('([a-z]{2})'", html))

    assert targets
    assert targets <= VALID_PAGE_KEYS


ADVISORY_LOG_MODULE = HTML_PATH.parent / "advisory-log-finma.js"


def test_event_logging_goals_action_returns_to_combined_cashflow_step():
    # ADVISORY-LOG-FINMA-FIELDS: die Ereignis-Erfassung oeffnet jetzt das
    # Protokollformular; die Navigation folgt nach dem Speichern im
    # ausgelagerten Modul (afterSave = gewaehlte Massnahme).
    module = ADVISORY_LOG_MODULE.read_text(encoding="utf-8")
    html = read_monolith_bundle()

    assert "if(afterSave==='goals')go('cf');" in module
    assert "go('uz')" not in module
    assert "if(action==='goals')go('uz');" not in html
    assert set(re.findall(r"go\('([a-z]{2})'", module)) <= VALID_PAGE_KEYS


def test_frontend_navigation_keeps_review_and_summary_combined_sequence():
    html = read_monolith_bundle()

    assert "const pages={sd:0,vg:1,cf:2,ub:3,rp:4,al:5,po:6,rv:7};" in html
    assert "if(p==='sr')p='rv';" in html
    assert 'data-page="sr"' not in html
    assert "Review &amp; Abschluss" in html


def test_summary_recipe_print_binding_uses_explicit_button_id():
    html = read_monolith_bundle()

    assert 'id="sr-recipe-print"' in html
    assert "var summaryRecipePrint=document.getElementById('sr-recipe-print');" in html
    assert 'id="rv-output-hub"' in html
    assert "rv-output-rail" in html
    assert "rv-output-item" in html
    assert "rv-decision-grid" in html
    assert "rv-final-grid" in html
    assert "function printPortfolioPlan()" in html
    assert "function printAdvisoryProtocol()" in html


def test_review_absschluss_keeps_internal_triggers_out_of_customer_surface():
    html = read_monolith_bundle()
    review_page = html.split('<div id="page-rv" class="page">', 1)[1].split("<!-- Legacy sr route", 1)[0]

    assert 'id="trigger-count"' not in html
    assert "om('m-nt')" not in review_page
    assert "rv-trigger-" not in review_page
    assert "+ Trigger" not in review_page
    assert "Trigger pruefen" not in review_page
    assert "Trigger prüfen" not in review_page


def test_portfolio_header_keeps_secondary_actions_in_more_menu():
    html = read_monolith_bundle()
    header = html.split('<div id="page-po" class="page">', 1)[1].split('<div class="pad">', 1)[0]
    page = html.split('<div id="page-po" class="page">', 1)[1].split('<div id="page-rv"', 1)[0]
    visible_actions = header.split('<details class="ph-more"', 1)[0]
    more_menu = header.split('<details class="ph-more"', 1)[1].split("</details>", 1)[0]

    assert 'id="btn-po-refresh"' in visible_actions
    assert "Portfolio generieren" in visible_actions
    assert 'id="btn-po-pdf"' in visible_actions
    assert 'id="btn-po-advisory-report"' in visible_actions
    assert "Weiter zum Review" not in visible_actions
    assert "Weiter zum Review" in page
    assert 'id="btn-po-live-prices"' not in visible_actions
    assert 'id="btn-po-depot-check"' not in visible_actions
    assert "openImplementationRecipe()" not in visible_actions
    assert 'id="btn-po-add-position"' not in visible_actions

    assert 'id="btn-po-add-position"' in more_menu
    assert 'id="btn-po-live-prices"' in more_menu
    assert 'id="btn-po-depot-check"' in more_menu
    assert "openImplementationRecipe()" in more_menu
    assert "var portfolioBtn=document.getElementById('btn-po-add-position');" in html


def test_portfolio_refresh_regenerates_missing_current_recommendation():
    html = read_monolith_bundle()
    refresh_block = html.split("async function refreshPortfolioFromStoredState(){", 1)[1].split(
        "// Sprint U-P11b", 1
    )[0]

    assert "function allocationPreferencesFromStoredAllocation(result)" in html
    # Live-Test 2026-11 H4: nicht nur bei fehlender Empfehlung, sondern bei
    # jedem nicht freigegebenen Vorschlag wird echt neu generiert
    # (Verhalten: tests/test_livetest_h4_portfolio_generate_really_regenerates.py).
    assert "if(!keptReleased){" in refresh_block
    assert "/recommendations/generate" in refresh_block
    assert "target_allocation_id:allocationId" in refresh_block
    assert "applyRecommendationEngineResult(recommendation)" in refresh_block


def test_allocation_preference_defaults_keep_gold_enabled():
    html = read_monolith_bundle()
    defaults_block = html.split("function buildDefaultAllocationPreferences(){", 1)[1].split(
        "function loadAllocationPreferences()", 1
    )[0]
    apply_block = html.split("function applyAllocationPreferencesToUI(prefs){", 1)[1].split(
        "function persistAllocationPreferences", 1
    )[0]

    assert 'id="aa-alts-gold" checked' in html
    assert "altsGold:true" in defaults_block
    assert "setCheckboxValue('aa-alts-gold',prefs.assetClasses&&prefs.assetClasses.altsGold)" in apply_block


def test_review_header_focuses_on_closing_actions():
    html = read_monolith_bundle()
    header = html.split('<div id="page-rv" class="page">', 1)[1].split('<div class="strip"', 1)[0]
    visible_actions = header.split('<details class="ph-more"', 1)[0]
    more_menu = header.split('<details class="ph-more"', 1)[1].split("</details>", 1)[0]

    assert "Entscheid protokollieren" in visible_actions
    assert "printAnlagestrategie()" in visible_actions
    assert "printAdvisoryProtocol()" not in visible_actions
    assert "printAdvisoryProtocol()" in more_menu
    assert "Protokoll drucken" in more_menu


def test_combined_cashflow_projection_has_own_root_and_responsive_grid():
    html = read_monolith_bundle()

    assert 'id="cf-goals-projection"' in html
    assert 'id="cf-risk-context-summary"' in html
    assert 'id="cf-combined-template"' in html
    assert 'id="page-ub"' not in html
    assert 'id="ub-review-strip"' not in html
    assert "#cf-goals-projection .projection-grid" in html
    # initDomLayout fügt templateGrid die projection-grid-Klasse hinzu — sowohl
    # one-liner als auch block-statement-Variante akzeptiert.
    assert "templateGrid.classList.add('projection-grid')" in html


def test_cashflow_projection_renders_compact_hud_not_component_wall():
    html = read_monolith_bundle()
    block = html.split("function renderCashflowProjection(data) {", 1)[1].split("function buildWealthPositionPayload", 1)[0]

    assert "Cashflow-HUD" in block
    assert "Einnahmen" in block
    assert "Ausgaben" in block
    assert "Sparquote" in block
    assert "Verm\\u00f6gensverzehr" in block
    assert "Cashflow-Projektion nach Komponenten" not in html


def test_allocation_donut_legend_uses_bucket_target_amounts():
    html = read_monolith_bundle()
    apply_block = html.split("function applyAllocationEngineResult(result){", 1)[1].split("function renderAllocationWarnings", 1)[0]
    legend_block = html.split("function buildDLegend(){", 1)[1].split("function syncAllocationDonutFromStrategyState", 1)[0]

    assert "chfTarget:Math.round((Number(bucket.target_amount_rappen||0))/100)" in apply_block
    # G7 (H-153 Nachtrag 1): die Legende nutzt aaChartAllocItems -- Betraege wie im
    # PDF ueber presentationAmounts auf der Strategiebasis (Live-Test 2026-11 H2:
    # Basis, nicht volles Beratungsvermoegen inkl. Reserve); Rueckfall ebenfalls Basis.
    assert "aaChartLegendHtml(aaChartAllocItems(),allocationReserveBreakdown(strategyState.allocation))" in legend_block
    items_fn = html.split("function aaChartAllocItems(){", 1)[1].split("\nfunction ", 1)[0]
    assert "AresRounding.presentationAmounts(rb.advisoryRappen,rb.strategyBaseRappen," in items_fn
    assert "Math.round((rb.strategyBaseRappen/100)*Number(r.soll||0)/100)" in items_fn


def test_active_combined_step_logic_no_longer_uses_old_ub_runtime_hooks():
    html = read_monolith_bundle()

    assert "updateCfRiskContextSummary" in html
    assert "updateUbRiskContextSummary" not in html
    assert "function applyAllocationEngineResultLegacy(" not in html
    assert "normalizeVisibleMojibake(document.getElementById('page-cf')||document.body);" in html
    assert "getElementById('page-ub')" not in html
    assert "querySelector('#page-ub" not in html
    assert "#page-ub .g2,#page-al .g2" not in html
    assert "#page-ub .chart,#page-al .chart" not in html
