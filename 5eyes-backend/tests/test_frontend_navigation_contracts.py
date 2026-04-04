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
