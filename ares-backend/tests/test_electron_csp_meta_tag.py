"""2026-07-24 (Generalaudit, Electron/IPC-Sweep): CSP-Meta-Tag fuer die
Electron-Renderer-Seite.

Befund: das Backend setzt bereits einen Content-Security-Policy-Header
(core/middleware.py::DEFAULT_CSP_POLICY), aber der greift NUR bei ueber
HTTP ausgelieferten Antworten. Electron laedt ares.html via
mainWindow.loadFile() als file://-URL -- die Backend-Middleware laeuft
dafuer nie. contextIsolation+sandbox+nodeIntegration:false mindern das
Risiko bereits stark, aber eine CSP ist zusaetzliche Tiefenverteidigung.
Dieser Test pinnt das Meta-Tag UND haelt es 1:1 synchron zur Backend-Policy.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from tests.monolith_source import read_monolith_bundle  # H3/I-04: inkl. ausgelagerter Teile

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

HTML_PATH = BACKEND_ROOT.parent / "ares-desktop" / "frontend" / "ares.html"

from core.middleware import DEFAULT_CSP_POLICY  # noqa: E402


def _html() -> str:
    return read_monolith_bundle()


def test_csp_meta_tag_present_in_head():
    html = _html()
    head = html[: html.find("</head>")]
    assert '<meta http-equiv="Content-Security-Policy"' in head


def meta_policy_from_header(policy: str) -> str:
    """EXE-04 (CTO-Entscheid H-180, umgesetzt H-187): Meta und HTTP-Header sind
    entkoppelt. Die Meta ist der Header OHNE ``app://.`` (in einer Meta eine
    ungueltige Quelle, Chromium meldet je Start einen Renderer-Fehler) und OHNE
    ``frame-ancestors`` (in einer Meta wirkungslos, ebenfalls ein Fehler)."""
    directives = []
    for directive in policy.split(";"):
        directive = directive.strip()
        if not directive or directive.split()[0] == "frame-ancestors":
            continue
        directives.append(" ".join(tok for tok in directive.split() if tok != "app://."))
    return "; ".join(directives)


def test_csp_meta_tag_matches_backend_default_policy():
    """Drift-Wache: wenn core/middleware.py::DEFAULT_CSP_POLICY sich
    aendert, muss das Meta-Tag mitgezogen werden -- sonst driften HTTP-
    Antworten und die Electron-file://-Seite auseinander. Abgeleitet, nicht
    gleich (EXE-04, ``meta_policy_from_header``)."""
    html = _html()
    match = re.search(
        r'<meta http-equiv="Content-Security-Policy" content="([^"]+)">',
        html,
    )
    assert match, "CSP-Meta-Tag nicht gefunden oder Format geaendert"
    assert match.group(1) == meta_policy_from_header(DEFAULT_CSP_POLICY)


def test_csp_meta_has_no_app_scheme_or_frame_ancestors_but_header_keeps_both():
    """EXE-04: die Meta enthaelt weder ``app://.`` noch ``frame-ancestors``;
    der HTTP-Header bleibt unveraendert (beides weiter drin)."""
    match = re.search(r'<meta http-equiv="Content-Security-Policy" content="([^"]+)">', _html())
    assert match
    assert "app://." not in match.group(1)
    assert "frame-ancestors" not in match.group(1)
    assert "app://." in DEFAULT_CSP_POLICY
    assert "frame-ancestors 'none'" in DEFAULT_CSP_POLICY


def test_csp_meta_tag_before_title():
    """Muss frueh im <head> stehen (vor <title>), damit die Policy ab dem
    allerersten geparsten Byte greift."""
    html = _html()
    csp_idx = html.find('<meta http-equiv="Content-Security-Policy"')
    title_idx = html.find("<title>")
    assert 0 < csp_idx < title_idx
