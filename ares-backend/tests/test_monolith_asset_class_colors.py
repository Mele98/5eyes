"""AA-UX-COLORS-001 -- Anlageklassen- und SOLL-Farben (UX-Audit Befund 11).

Vorher: Aktien #1e4b8f, Immobilien #2c5080, Alternative #4a6080 (drei fast
gleiche Blautoene), Liquiditaet #166534 -- identisch mit der SOLL-Farbe
rgb(22,101,52) und dem Positiv-Gruen. Gruen bedeutete gleichzeitig
"Liquiditaet", "SOLL" und "besser".

Vertrag:
* Sechs Klassen-Tokens --ac-* in :root und [data-theme=dark], gespiegelt in
  JS (AC_COLORS*) und im Report (tokens.ts assetClass/assetClassDark +
  tailwind.config.ts). Alle Werte identisch.
* Keine der alten Klassenfarben mehr im Monolithen; Klassen-Zuordnung nur
  noch ueber assetClassKey()/assetClass*().
* SOLL = Brand-Gold (--soll), nicht Gruen; Gruen (--pos) bleibt "besser".
* Barrierearmut: Klassen paarweise unterscheidbar auch bei Protanopie/
  Deuteranopie (Machado-Simulation, CIELAB-dE >= 8); Text auf Klassenflaechen
  (assetClassTextOn) und SOLL-Text erreichen WCAG AA 4.5:1.
"""
from __future__ import annotations

import itertools
import json
import math
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HTML_PATH = ROOT / "ares-desktop" / "frontend" / "ares.html"
REPORTING = ROOT / "ares-desktop" / "frontend" / "reporting"
TOKENS_TS = REPORTING / "src" / "design" / "tokens.ts"
TAILWIND = REPORTING / "tailwind.config.ts"

KEYS = ("eq", "bd", "re", "alt", "liq", "oth")


def _html() -> str:
    return HTML_PATH.read_text(encoding="utf-8")


def _css_block(html: str, selector: str) -> str:
    start = html.index(selector + " {")
    return html[start:html.index("\n}", start)]


def _css_tokens(block: str) -> dict[str, str]:
    return {k: v.upper() for k, v in re.findall(r"--ac-([a-z]+):(#[0-9A-Fa-f]{6})", block)}


def _js_map(html: str, name: str) -> dict[str, str]:
    m = re.search(r"var " + name + r"=\{([^}]*)\};", html)
    assert m, name
    return {k: v.upper() for k, v in re.findall(r"([a-z]+):'(#[0-9A-Fa-f]{6})'", m.group(1))}


def _ts_map(src: str, name: str) -> dict[str, str]:
    m = re.search(r"export const " + name + r" = \{(.*?)\} as const;", src, re.S)
    assert m, name
    return {k: v.upper() for k, v in re.findall(r"([a-z]+):\s*'(#[0-9A-Fa-f]{6})'", m.group(1))}


def _soll_hex(html: str) -> tuple[str, str]:
    m = re.search(r"var hex=\(!print&&_acIsDarkTheme\(\)\)\?'(#[0-9A-Fa-f]{6})':'(#[0-9A-Fa-f]{6})';", html)
    assert m, "sollColor() nicht gefunden"
    return m.group(2), m.group(1)


def _light_dark():
    html = _html()
    light = _css_tokens(_css_block(html, ":root"))
    dark = _css_tokens(_css_block(html, ':root[data-theme="dark"]'))
    return html, light, dark


def test_six_tokens_in_light_and_dark_and_js_mirror_identical():
    html, light, dark = _light_dark()
    assert tuple(light) == KEYS and tuple(dark) == KEYS
    assert light == _js_map(html, "AC_COLORS")
    assert dark == _js_map(html, "AC_COLORS_DARK")
    # Audit-Vorgaben (Terrakotta bewusst dunkler, siehe CVD-Test unten)
    assert light["eq"] == "#1F3A5F" and light["bd"] == "#B39455"
    assert light["alt"] == "#5E6B45" and light["liq"] == "#8E97A8"


def test_report_tokens_and_tailwind_mirror_app_tokens():
    _, light, dark = _light_dark()
    ts = TOKENS_TS.read_text(encoding="utf-8")
    assert _ts_map(ts, "assetClass") == light
    assert _ts_map(ts, "assetClassDark") == dark
    tw = TAILWIND.read_text(encoding="utf-8")
    for key in KEYS:
        assert re.search(r"\b" + key + r": '" + light[key] + "'", tw, re.I), key
        assert re.search(r"'" + key + r"-dark': '" + dark[key] + "'", tw, re.I), key
    html = _html()
    soll_l, soll_d = (c.upper() for c in _soll_hex(html))
    assert f"--soll:{soll_l}".lower() in _css_block(html, ":root").lower()
    assert f"--soll:{soll_d}".lower() in _css_block(html, ':root[data-theme="dark"]').lower()
    assert re.search(r"DEFAULT: '" + soll_l + "'", ts, re.I)
    assert re.search(r"dark:\s+'" + soll_d + "'", ts, re.I)


def test_old_class_colors_gone_and_mapping_centralised():
    html = _html()
    # #2c5080/#4a6080/#78601a waren ausschliesslich Klassenfarben. #1e4b8f lebt als
    # Cashflow-Abfluss-/Serienfarbe ausserhalb der Klassen weiter -> nur im
    # Klassen-Kontext verboten.
    for old in ("#2c5080", "#4a6080", "#78601a"):
        assert old not in html.lower(), f"alte Klassenfarbe {old} noch im Monolithen"
    low = html.lower()
    for ctx in ("aktien", "equities", "c:'#1e4b8f'", "soll (rebal)', color:'#1e4b8f'"):
        for m in re.finditer(re.escape(ctx), low):
            assert "#1e4b8f" not in low[m.start():m.start() + 60], low[m.start():m.start() + 80]
    # Keine lokalen Farbtabellen pro Ansicht mehr
    assert "var colors={Aktien:" not in html
    assert "if(k.indexOf('aktien')>=0)return '#" not in html


def test_soll_uses_brand_accent_not_green():
    html = _html()
    # SOLL-Spaltenkoepfe und SOLL-Serien
    assert 'color:rgb(22,101,52);font-weight:700">SOLL' not in html
    assert "color:rgb(22,101,52)\">SOLL</th>" not in html
    assert "label:'Optimierte Strategie',data:opt,borderColor:'rgb(22,101,52)'" not in html
    assert "label:'Optimierte Strategie',data:opt,borderColor:sollColor()" in html
    assert "SOLL — optimierte Strategie <span class=\"tag tsoll\">" in html
    # Liquiditaet ist nicht mehr gruen
    _, light, _ = _light_dark()
    assert light["liq"] not in ("#166534", "#0E6B41")


# ---------------------------------------------------------------------------
# Barrierearmut: Farbenblindheit + Kontrast
# ---------------------------------------------------------------------------


def _rgb(h):
    h = h.lstrip("#")
    return [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]


def _lin(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _lum(h):
    r, g, b = (_lin(c) for c in _rgb(h))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(a, b):
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


# Machado et al. (2009), Schweregrad 1.0, lineares RGB
_CVD = {
    "protan": [[0.152286, 1.052583, -0.204868], [0.114503, 0.786281, 0.099216], [-0.003882, -0.048116, 1.051998]],
    "deutan": [[0.367322, 0.860646, -0.227968], [0.280085, 0.672501, 0.047413], [-0.011820, 0.042940, 0.968881]],
    "tritan": [[1.255528, -0.076749, -0.178779], [-0.078411, 0.930809, 0.147602], [0.004733, 0.691367, 0.303900]],
}


def _lab(lin_rgb):
    r, g, b = (max(0.0, min(1.0, c)) for c in lin_rgb)
    x = 0.4124 * r + 0.3576 * g + 0.1805 * b
    y = 0.2126 * r + 0.7152 * g + 0.0722 * b
    z = 0.0193 * r + 0.1192 * g + 0.9505 * b

    def f(t):
        return t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116

    fx, fy, fz = f(x / 0.95047), f(y), f(z / 1.08883)
    return (116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz))


def _sim(h, kind):
    lin = [_lin(c) for c in _rgb(h)]
    if kind == "none":
        return _lab(lin)
    m = _CVD[kind]
    return _lab([sum(m[i][j] * lin[j] for j in range(3)) for i in range(3)])


@pytest.mark.parametrize("theme", ["light", "dark"])
@pytest.mark.parametrize("kind", ["none", "protan", "deutan", "tritan"])
def test_classes_distinguishable_under_colour_vision_deficiency(theme, kind):
    _, light, dark = _light_dark()
    pal = light if theme == "light" else dark
    worst = min(
        (math.dist(_sim(pal[a], kind), _sim(pal[b], kind)), a, b)
        for a, b in itertools.combinations(KEYS, 2)
    )
    # Vorher (Audit-Vorschlag #8A5A3C) lag Terrakotta/Oliv bei Protanopie bei dE 3.3.
    assert worst[0] >= 8.0, worst


def test_dark_tokens_reach_graphic_contrast_on_dark_surface():
    _, _, dark = _light_dark()
    for key in KEYS:
        assert _contrast(dark[key], "#101B2C") >= 3.0, key


def test_soll_text_contrast_wcag_aa():
    soll_l, soll_d = _soll_hex(_html())
    assert _contrast(soll_l, "#FFFFFF") >= 4.5
    assert _contrast(soll_l, "#F3F5F8") >= 4.5  # --bg
    assert _contrast(soll_l, "#FAF3E0") >= 4.5  # .tsoll Hintergrund
    assert _contrast(soll_d, "#101B2C") >= 4.5
    assert _contrast(soll_d, "#261D0E") >= 4.5


def _extract_function(src: str, name: str) -> str:
    match = re.search(r"\nfunction " + re.escape(name) + r"\(", src)
    assert match, name
    start = match.start() + 1
    i = src.index("{", start)
    depth, j = 1, i + 1
    while depth:
        depth += {"{": 1, "}": -1}.get(src[j], 0)
        j += 1
    return src[start:j]


def _run_js(body: str, theme: str = "light"):
    if shutil.which("node") is None:
        pytest.skip("node not available")
    html = _html()
    prelude = (
        "var document={documentElement:{dataset:{theme:%s}}};\n" % json.dumps(theme)
        + re.search(r"var AC_COLORS=\{[^}]*\};", html).group(0) + "\n"
        + re.search(r"var AC_COLORS_DARK=\{[^}]*\};", html).group(0) + "\n"
    )
    fns = "\n".join(
        _extract_function(html, n)
        for n in ("assetClassKey", "_acIsDarkTheme", "assetClassCssVar", "assetClassColor",
                  "assetClassPrintColor", "assetClassTextOn", "sollColor", "hexWithAlpha")
    )
    script = prelude + fns + "\nprocess.stdout.write(JSON.stringify((function(){" + body + "})()));"
    proc = subprocess.run(["node", "-e", script], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def test_asset_class_key_covers_engine_depotcheck_and_display_names():
    out = _run_js(
        "return ['Aktien','Obligationen','Immobilien','Alternative','Liquiditaet',"
        "'equities','bonds','real_estate','alternatives','liquidity',"
        "'Aktien (global+CH)','Anleihen / Defensiv','Alternative / Gold','Liquiditätsreserve',"
        "'Private Equity','Externe Mandate','Nicht klassifiziert'].map(assetClassKey);"
    )
    assert out == ["eq", "bd", "re", "alt", "liq", "eq", "bd", "re", "alt", "liq",
                   "eq", "bd", "alt", "liq", "alt", "oth", "oth"]


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_text_on_class_fill_meets_wcag_aa(theme):
    out = _run_js(
        "return ['eq','bd','re','alt','liq','oth'].map(function(k){return [assetClassColor(k),assetClassTextOn(k)];});",
        theme,
    )
    for fill, text in out:
        assert _contrast(fill, text) >= 4.5, (theme, fill, text)


def test_canvas_colours_follow_theme_and_print_stays_light():
    light = _run_js("return [assetClassColor('Aktien'),assetClassPrintColor('Aktien'),sollColor(),sollColor(0.1),assetClassCssVar('bonds')];")
    dark = _run_js("return [assetClassColor('Aktien'),assetClassPrintColor('Aktien'),sollColor(),sollColor(null,true)];", "dark")
    assert light[0] == "#1F3A5F" and light[1] == "#1F3A5F"
    assert light[2] == "#8A6A1F" and light[3] == "rgba(138,106,31,0.1)"
    assert light[4] == "var(--ac-bd)"
    assert dark[0] == "#3D6DB0" and dark[1] == "#1F3A5F"  # Druck immer hell
    assert dark[2] == "#D9B869" and dark[3] == "#8A6A1F"
