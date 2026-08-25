"""2026-07-24 (Generalaudit, Electron/IPC-Sweep): CSP-Meta-Tag fuer die
Electron-Renderer-Seite.

Befund: das Backend setzt bereits einen Content-Security-Policy-Header
(core/middleware.py::DEFAULT_CSP_POLICY), aber der greift NUR bei ueber
HTTP ausgelieferten Antworten. Electron laedt 5eyes_v2.html via
mainWindow.loadFile() als file://-URL -- die Backend-Middleware laeuft
dafuer nie. contextIsolation+sandbox+nodeIntegration:false mindern das
Risiko bereits stark, aber eine CSP ist zusaetzliche Tiefenverteidigung.
Dieser Test pinnt das Meta-Tag UND haelt es 1:1 synchron zur Backend-Policy.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

HTML_PATH = BACKEND_ROOT.parent / "5eyes-electron" / "frontend" / "5eyes_v2.html"

from core.middleware import DEFAULT_CSP_POLICY  # noqa: E402


def _html() -> str:
    return HTML_PATH.read_text(encoding="utf-8")


def test_csp_meta_tag_present_in_head():
    html = _html()
    head = html[: html.find("</head>")]
    assert '<meta http-equiv="Content-Security-Policy"' in head


def test_csp_meta_tag_matches_backend_default_policy():
    """Drift-Wache: wenn core/middleware.py::DEFAULT_CSP_POLICY sich
    aendert, muss das Meta-Tag mitgezogen werden -- sonst driften HTTP-
    Antworten und die Electron-file://-Seite auseinander."""
    html = _html()
    match = re.search(
        r'<meta http-equiv="Content-Security-Policy" content="([^"]+)">',
        html,
    )
    assert match, "CSP-Meta-Tag nicht gefunden oder Format geaendert"
    assert match.group(1) == DEFAULT_CSP_POLICY


def test_csp_meta_tag_before_title():
    """Muss frueh im <head> stehen (vor <title>), damit die Policy ab dem
    allerersten geparsten Byte greift."""
    html = _html()
    csp_idx = html.find('<meta http-equiv="Content-Security-Policy"')
    title_idx = html.find("<title>")
    assert 0 < csp_idx < title_idx
