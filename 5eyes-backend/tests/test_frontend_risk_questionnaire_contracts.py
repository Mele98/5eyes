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
    assert "Ort, Datum" not in html


def test_no_goal_horizon_hint_is_hidden_when_no_basis_is_available():
    html = HTML_PATH.read_text(encoding="utf-8")

    assert "Noch kein Zielhorizont ableitbar. Bitte Anlagehorizont manuell erfassen." not in html


def test_asset_allocation_expand_click_uses_data_attribute_binding():
    html = HTML_PATH.read_text(encoding="utf-8")

    assert 'data-allocation-group="' in html
    assert "bindAllocationTableInteractions" in html
    assert "toggleSubAllocationGroup(decodeURIComponent(" in html
