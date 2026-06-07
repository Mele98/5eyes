from pathlib import Path


HTML_PATH = Path(__file__).resolve().parents[2] / "5eyes-electron" / "frontend" / "5eyes_v2.html"


def test_risk_questionnaire_stays_customer_friendly_without_transparency_boxes():
    html = HTML_PATH.read_text(encoding="utf-8")

    assert "Scoring-Logik:" not in html
    assert 'id="risk-live-scoreboard"' not in html
    assert 'id="risk-breakdown"' not in html
    assert "Scoring-Transparenz:" not in html
    assert "Live-Scorebild:" not in html


def test_risk_answer_options_do_not_expose_points_to_clients():
    html = HTML_PATH.read_text(encoding="utf-8")

    assert "(Income · 1 Punkt)" not in html
    assert "(Balanced · 2 Punkte)" not in html
    assert "(Growth · 3 Punkte)" not in html
    assert "(Equity · 4 Punkte)" not in html
    assert "(−4 % bis +6 % · 1 Punkt)" not in html
    assert "(−6 % bis +10 % · 2 Punkte)" not in html
    assert "(−10 % bis +16 % · 3 Punkte)" not in html
    assert "(−16 % bis +24 % · 4 Punkte)" not in html
    assert "(0 Punkte)" not in html
    assert "(3 Punkte)" not in html
    assert "(6 Punkte)" not in html
    assert "(9 Punkte)" not in html
    assert "(12 Punkte)" not in html


def test_risk_summary_and_override_controls_remain_visible():
    html = HTML_PATH.read_text(encoding="utf-8")

    assert "Final zählt immer der tiefere Wert" in html
    assert 'id="overr-badge"' in html
    assert "Risikoprofil speichern" in html
    assert "Empfohlene Anlagestrategie" in html
    assert "Abschluss & Unterschrift" not in html
    assert "Unterschrift Kunde" not in html


def test_no_goal_horizon_hint_is_hidden_when_no_basis_is_available():
    html = HTML_PATH.read_text(encoding="utf-8")

    assert "Noch kein Zielhorizont ableitbar. Bitte Anlagehorizont manuell erfassen." not in html


def test_asset_allocation_expand_click_uses_data_attribute_binding():
    html = HTML_PATH.read_text(encoding="utf-8")

    assert 'data-allocation-group="' in html
    assert "bindAllocationTableInteractions" in html
    assert "toggleSubAllocationGroup(decodeURIComponent(" in html


def test_asset_allocation_header_keeps_only_core_actions_visible():
    html = HTML_PATH.read_text(encoding="utf-8")
    header = html.split('<div id="page-al" class="page">', 1)[1].split('<div id="al-dirty-banner"', 1)[0]
    visible_actions = header.split('<details class="aa-more"', 1)[0]
    more_menu = header.split('<details class="aa-more"', 1)[1].split("</details>", 1)[0]
    fallback = html.split("function ensureAssetAllocationQuickActions(){", 1)[1].split(
        "function ensureAllocationControlModalsMounted", 1
    )[0]

    assert 'id="btn-aa-pref-open"' in visible_actions
    assert 'id="btn-aa-calc"' in visible_actions
    assert 'id="btn-aa-pdf"' in visible_actions
    assert 'id="btn-portfolio-umsetzen"' in visible_actions
    assert 'id="btn-aa-backtest"' not in visible_actions
    assert 'id="btn-aa-params-open"' not in visible_actions
    assert "openMandateSettingsModal()" not in visible_actions
    assert "openAllocationEngineModal()" not in visible_actions

    assert 'id="btn-aa-backtest"' in more_menu
    assert "Strategie-Backtest" in more_menu
    assert 'id="btn-aa-params-open"' in more_menu
    assert "openMandateSettingsModal()" in more_menu
    assert "openAllocationEngineModal()" in more_menu
    assert "header.insertBefore(paramBtn" not in fallback


def test_risk_profile_header_uses_single_server_pdf_action():
    html = HTML_PATH.read_text(encoding="utf-8")
    header = html.split('<div id="page-rp" class="page">', 1)[1].split('<div class="pad">', 1)[0]
    visible_actions = header.split('<details class="ph-more"', 1)[0]
    more_menu = header.split('<details class="ph-more"', 1)[1].split("</details>", 1)[0]
    risk_modal = html.split('<div class="overlay" id="m-rp-print">', 1)[1].split("<script>", 1)[0]

    assert 'id="btn-rp-server-pdf"' in header
    assert "downloadServerPdf('risikoprofil')" in header
    assert 'id="btn-rp-server-pdf"' not in visible_actions
    assert 'id="btn-rp-server-pdf"' in more_menu
    assert ">PDF</button>" in more_menu
    assert "PDF (Browser)" not in header
    assert "PDF (Server)" not in header
    assert "om('m-rp-print')" not in header
    assert "Browser-Druck" not in risk_modal
    assert "printReport({pages:['rp']})" not in risk_modal


def test_frontend_willingness_profile_labels_stay_in_sync_with_backend():
    html = HTML_PATH.read_text(encoding="utf-8")

    assert "services/risk_scoring.py:_willingness_profile()" in html
    assert "if(scoreX10 <= 24) return 'Kapitalschutz';" in html
    assert "if(scoreX10 <= 44) return 'Defensiv';" in html
    assert "if(scoreX10 <= 64) return 'Ausgewogen';" in html
    assert "if(scoreX10 <= 84) return 'Wachstumsorientiert';" in html
    assert "if(scoreX10 <= 94) return 'Dynamisch';" in html
    assert "return 'Aktien';" in html


def test_frontend_uses_safe_dom_bindings_for_dynamic_review_and_document_actions():
    html = HTML_PATH.read_text(encoding="utf-8")

    assert 'data-doc-action="print"' in html
    assert 'data-doc-action="sign"' in html
    assert 'data-trigger-action="review"' in html
    assert 'data-trigger-action="template"' in html
    assert "renderRowsSafe(" in html


def test_frontend_no_longer_contains_accidental_refresh_goals_cashflow_binding_block():
    html = HTML_PATH.read_text(encoding="utf-8")
    refresh_goals_block = html.split("async function refreshGoalsUI(mid){", 1)[1].split("async function loadPlanningAssumptions()", 1)[0]

    assert "(af||document.createElement('div')).querySelectorAll('.cf-row[data-cfid] .btn-ico')" not in refresh_goals_block


def test_override_api_errors_are_shown_in_modal():
    html = HTML_PATH.read_text(encoding="utf-8")
    apply_override_block = html.split("async function applyOv(){", 1)[1].split("// Init: hide subclass section", 1)[0]

    assert "errEl.textContent=parseApiError(e,'Override konnte nicht gespeichert werden.');" in apply_override_block
    assert "errEl.style.display='block';" in apply_override_block


def test_allocation_warnings_are_rendered_when_recommendation_is_missing_or_loaded():
    html = HTML_PATH.read_text(encoding="utf-8")

    assert "renderRecommendationWarnings(allocation.warnings||[],{},null,[]);" in html
    assert "var allocationWarnings=strategyState.allocation&&Array.isArray(strategyState.allocation.warnings)?strategyState.allocation.warnings:[];" in html
    assert "renderRecommendationWarnings((result.warnings||[]).concat(allocationWarnings),result.market_data_quality||{},live,result.positions||[]);" in html
