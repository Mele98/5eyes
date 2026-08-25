"""Regressions-Sperre #38: Hinweis auf mögliche Doppelerfassung — ein manueller
Cashflow, der einen bereits automatisch abgeleiteten Posten dupliziert (Hypothek-
zins, Miete, Zinsertrag). Nicht-blockierend (User-Entscheid "beide zeigen").
"""
from pathlib import Path


HTML_PATH = Path(__file__).resolve().parents[2] / "5eyes-electron" / "frontend" / "5eyes_v2.html"


def _html() -> str:
    return HTML_PATH.read_text(encoding="utf-8")


def test_dupe_hint_container_and_functions_exist():
    html = _html()
    assert 'id="cf-dupe-hint"' in html
    assert "function _cashflowDuplicateHints(" in html
    assert "function _renderCashflowDuplicateHint(" in html


def test_dupe_detector_uses_origin_tokens():
    html = _html()
    assert "origin_position_type" in html
    assert "'hypothek'" in html and "'miete'" in html and "'zinsertrag'" in html


def test_dupe_hint_is_wired_into_refresh():
    html = _html()
    assert "_renderCashflowDuplicateHint(inc.concat(exp), derInc.concat(derExp))" in html


def test_dupe_hint_is_non_blocking_wording():
    html = _html()
    # Hinweis, kein Hard-Block; nennt die Doppelzählungs-Wirkung.
    assert "Mögliche Doppelerfassung" in html
    assert "doppelt zählt" in html
