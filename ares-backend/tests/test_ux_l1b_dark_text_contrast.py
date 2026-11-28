"""UX-L1b (UX-Vertrag 27.11.2026): Text-Tokens erfuellen WCAG AA (4.5:1) auf --surface.

Liest die tatsaechlichen Tokens aus ares.css (Light-:root und Dark-Block) und
loest var()-Verweise auf -- keine fest verdrahteten Farbwerte im Test.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

CSS = Path(__file__).resolve().parents[2] / "ares-desktop" / "frontend" / "ares.css"


def _block(css: str, selector: str) -> dict[str, str]:
    start = css.index(selector)
    body = css[css.index("{", start) + 1: css.index("}", start)]
    return {m.group(1): m.group(2).strip() for m in re.finditer(r"(--[\w-]+)\s*:\s*([^;]+);", body)}


def _resolve(tokens: dict[str, str], name: str) -> str:
    value = tokens[name]
    for _ in range(5):
        m = re.fullmatch(r"var\((--[\w-]+)\)", value)
        if not m:
            return value
        value = tokens[m.group(1)]
    raise AssertionError(f"var-Kette zu tief: {name}")


def _luminance(hex_value: str) -> float:
    v = hex_value.lstrip("#")
    if len(v) == 3:
        v = "".join(c * 2 for c in v)
    out = []
    for i in (0, 2, 4):
        c = int(v[i:i + 2], 16) / 255
        out.append(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4)
    return 0.2126 * out[0] + 0.7152 * out[1] + 0.0722 * out[2]


def _contrast(a: str, b: str) -> float:
    x, y = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (x + 0.05) / (y + 0.05)


def _themes() -> dict[str, dict[str, str]]:
    css = CSS.read_text(encoding="utf-8")
    light = _block(css, ":root {") if ":root {" in css else _block(css, ":root{")
    dark = {**light, **_block(css, ':root[data-theme="dark"]')}
    return {"light": light, "dark": dark}


@pytest.mark.parametrize("theme", ["light", "dark"])
@pytest.mark.parametrize("token", ["--text-body", "--text-muted"])
def test_text_tokens_meet_wcag_aa_on_surface(theme, token):
    tokens = _themes()[theme]
    fg, bg = _resolve(tokens, token), _resolve(tokens, "--surface")
    assert _contrast(fg, bg) >= 4.5, f"{theme} {token} {fg} auf {bg}: {_contrast(fg, bg):.2f}"


def test_checker_negative_control():
    assert _contrast("#5f80a8", "#101b2c") < 4.5  # alter Dark-Muted-Wert waere rot
