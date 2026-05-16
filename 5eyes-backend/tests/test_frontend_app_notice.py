"""Frontend-Contract-Tests fuer das App-Notice (Toast-Stack) System.

2026-05-16: Codex §11 hat mehrfach 'global sichtbar' behauptet, aber kein
echtes globales Notice-System war im Code. Mit diesem Modul jetzt da:
showAppNotice + showAppError/Warn/Success/Info convenience-wrapper +
CSS-Stack #app-notice-stack.
"""
from __future__ import annotations

from pathlib import Path

FRONTEND_HTML = (
    Path(__file__).resolve().parents[2]
    / "5eyes-electron" / "frontend" / "5eyes_v2.html"
)


def _html() -> str:
    return FRONTEND_HTML.read_text(encoding="utf-8")


def test_app_notice_stack_container_exists():
    html = _html()
    assert 'id="app-notice-stack"' in html
    assert 'role="region"' in html
    assert 'aria-live="polite"' in html


def test_app_notice_css_classes_defined():
    html = _html()
    for cls in ('.app-notice-stack', '.app-notice', '.an-error', '.an-warn', '.an-success', '.an-info', '.an-close', '.an-leaving'):
        assert cls in html, f"CSS-Klasse {cls} fehlt"
    assert '@keyframes appNoticeIn' in html
    assert '@keyframes appNoticeOut' in html


def test_show_app_notice_function_exists():
    html = _html()
    assert 'function showAppNotice(opts)' in html
    assert "opts.level" in html
    assert "an-leaving" in html


def test_convenience_wrappers_exist():
    html = _html()
    assert 'function showAppError(' in html
    assert 'function showAppWarn(' in html
    assert 'function showAppSuccess(' in html
    assert 'function showAppInfo(' in html


def test_supports_all_four_levels():
    html = _html()
    block = html.split("function showAppNotice(opts)", 1)[1].split("function showAppError", 1)[0]
    for level in ('error', 'warn', 'success', 'info'):
        assert f"'{level}'" in block, f"Level '{level}' nicht im showAppNotice block"


def test_supports_optional_action_button():
    html = _html()
    block = html.split("function showAppNotice(opts)", 1)[1].split("function showAppError", 1)[0]
    assert 'opts.action' in block
    assert 'an-action' in block


def test_auto_dismiss_durations_set():
    html = _html()
    block = html.split("function showAppNotice(opts)", 1)[1].split("function showAppError", 1)[0]
    assert 'error:8000' in block
    assert 'success:4000' in block


def test_aria_close_button_present():
    html = _html()
    block = html.split("function showAppNotice(opts)", 1)[1].split("function showAppError", 1)[0]
    assert 'aria-label' in block
    assert "an-close" in block
