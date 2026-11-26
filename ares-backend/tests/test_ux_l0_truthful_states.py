"""UX-L0 (Codex-UX-Audit 25.11.2026, UX-CH-01..03): wahrheitsgetreue Zustaende.

* UX-CH-01  Das Intro zeigt keine ungebundenen positiven Systemzustaende mehr
            (keine Statusleiste, kein "LIVE"/"SECURE CHANNEL", keine Status-
            woerter wie ACTIVE/MAPPED/READY/AWARE/SYNC).
* UX-CH-02  Die Schrittanzeige leitet "OK" nicht mehr aus der Position ab:
            zurueckliegend = "besucht" (Nummer bleibt), "OK" nur ueber eine
            Vollstaendigkeitspruefung. Verhaltensbeleg im Browser:
            ``test_livetest_ux_l0_step_states.py``.
* UX-CH-03  Anmelde-/Ersteinrichtungs-Overlay: kein Gold als Schrift auf Weiss,
            kein weisser Text auf Gold; Normaltext mindestens 4.5:1.
"""
from __future__ import annotations

import math
import re
from pathlib import Path

from tests.monolith_source import read_monolith_bundle

FRONTEND = Path(__file__).resolve().parents[2] / "ares-desktop" / "frontend"
HTML = read_monolith_bundle()
CSS = (FRONTEND / "ares.css").read_text(encoding="utf-8")


def _intro() -> str:
    return HTML.split('<div id="intro-screen"', 1)[1].split("</div>\n<script", 1)[0]


def _login_overlay() -> str:
    start = HTML.index('<div id="login-overlay"')
    return HTML[start:HTML.index("<!-- ", HTML.index('<div id="bootstrap-panel"', start))]


def _token(name: str) -> str:
    match = re.search(rf"--{re.escape(name)}\s*:\s*(#[0-9a-fA-F]{{6}})", CSS)
    assert match, name
    return match.group(1)


def _contrast(first: str, second: str) -> float:
    def lum(color: str) -> float:
        out = []
        for i in (1, 3, 5):
            v = int(color[i:i + 2], 16) / 255
            out.append(v / 12.92 if v <= 0.03928 else math.pow((v + 0.055) / 1.055, 2.4))
        return 0.2126 * out[0] + 0.7152 * out[1] + 0.0722 * out[2]

    a, b = lum(first), lum(second)
    return (max(a, b) + 0.05) / (min(a, b) + 0.05)


def test_intro_has_no_unbound_positive_system_status():
    intro = _intro()
    assert 'aria-label="Systemstatus"' not in intro
    assert "intro-rail" not in intro and "intro-signal" not in intro
    for claim in ("ACTIVE", "MAPPED", "READY", "AWARE", "SYNC", "LIVE", "SECURE", "VALID"):
        assert not re.search(rf"\b{claim}\b", intro), claim
    # Laufzeittexte der Startanimation (intro-sequence.js)
    sequence = (FRONTEND / "intro-sequence.js").read_text(encoding="utf-8")
    steps = re.search(r"var steps=\[(.*?)\];", sequence).group(1)
    for claim in ("ready", "validated", "synchronized", "mapped", "verified"):
        assert claim not in steps.lower(), claim
        assert f"system {claim}" not in sequence.lower(), claim


def test_step_ok_is_not_derived_from_position():
    go = HTML[HTML.index("async function go(p,b){"):]
    go = go[:go.index("\n}\n")]
    assert "textContent='OK'" not in go, "go() darf 'OK' nicht mehr aus der Position setzen"
    assert "renderStepStates(p);" in go
    render = HTML[HTML.index("function renderStepStates(p){"):]
    render = render[:render.index("\n}\n")]
    # OK nur im complete-Zweig, der ausschliesslich aus stepIsComplete stammt
    assert render.count("textContent='OK'") == 1
    assert "else if(complete){s.classList.add('done');if(sn)sn.textContent='OK';}" in render
    assert "var complete=stepIdx!==idx&&stepIsComplete(stepKey);" in render
    assert "else if(stepIdx<idx){s.classList.add('visited');if(sn)sn.textContent=i+1;}" in render
    table = HTML[HTML.index("var STEP_COMPLETENESS={"):]
    table = table[:table.index("};")]
    # Nur Schritte mit belegter Vollstaendigkeitspruefung; die Stammdaten nutzen
    # dieselbe Funktion wie das sichtbare Label "Stammdaten (un)vollstaendig".
    assert re.findall(r"\n  (\w+):function", table) == ["sd"]
    assert "computeStammdatenCompleteness().complete===true" in table
    assert ".tstep.visited .sn{" in HTML


def test_login_overlay_meets_contrast_contract():
    overlay = _login_overlay()
    assert "color:var(--g3)" not in overlay and "color:var(--g4)" not in overlay
    assert "background:var(--g4);color:#fff" not in overlay
    assert overlay.count("background:var(--chrome-n8);color:#fff;") == 2
    white = "#ffffff"
    assert _contrast(_token("n6"), white) >= 4.5  # --text-body
    assert _contrast(_token("n5"), white) >= 4.5  # Links
    assert _contrast(white, re.search(r"--chrome-n8:(#[0-9a-fA-F]{6})", CSS).group(1)) >= 4.5
    assert "--text-body:var(--n6)" in CSS
    build_info = (FRONTEND / "build-info.js").read_text(encoding="utf-8")
    assert "color:var(--g3)" not in build_info
