"""Vertrag der Renderer-Bridges (Electron-Preload und JS-Fassade).

- Die Preload-Bridge heisst ``window.desktop`` (contextBridge, read-only).
- Die Renderer-Fassade aus ``frontend/desktop-api.js`` heisst
  ``window.AresAPI`` und ist die einzige Fassade, die das Haupt-HTML nutzt.

Beide Namen muessen getrennt bleiben: contextBridge-Objekte sind im
Renderer nicht beschreibbar, eine gleichnamige Fassade wuerde im Electron-
Betrieb stillschweigend nicht gesetzt.
"""
from __future__ import annotations

import re
from pathlib import Path

DESKTOP_ROOT = Path(__file__).resolve().parents[2] / "ares-desktop"
FACADE_JS = DESKTOP_ROOT / "frontend" / "desktop-api.js"
MAIN_HTML = DESKTOP_ROOT / "frontend" / "ares.html"
PRELOAD_JS = DESKTOP_ROOT / "preload.js"


def test_facade_is_exposed_as_ares_api():
    src = FACADE_JS.read_text(encoding="utf-8")
    assigned = re.findall(r"window\.(\w+)\s*=\s*\{", src)
    assert assigned == ["AresAPI"]


def test_main_html_uses_only_ares_api_facade():
    html = MAIN_HTML.read_text(encoding="utf-8")
    facades = set(re.findall(r"window\.(\w+API)\b", html))
    assert facades == {"AresAPI"}
    assert "window.AresAPI.resolveBaseUrl" in html
    assert "window.AresAPI.updates" in html


def test_preload_bridge_name_is_distinct_from_facade():
    src = PRELOAD_JS.read_text(encoding="utf-8")
    exposed = re.findall(r"exposeInMainWorld\('([^']+)'", src)
    assert exposed == ["desktop"]
