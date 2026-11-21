"""Sichtbarer Produktname in Monolith und Reporting-App (Spec §5, Minimalbranding).

Fenstertitel, Intro-Dialog, Login und Topbar zeigen den Produktnamen ``Ares``
als Text. Bis zur Freigabe eines Logos gibt es keine Bildmarke und kein
Ziffern-Monogramm im Logo-Block.
"""
from __future__ import annotations

import re
from pathlib import Path
from tests.monolith_source import read_monolith_bundle  # H3/I-04: inkl. ausgelagerter Teile

REPO_ROOT = Path(__file__).resolve().parents[2]
MONOLITH = REPO_ROOT / "ares-desktop" / "frontend" / "ares.html"
REPORTING = REPO_ROOT / "ares-desktop" / "frontend" / "reporting"

PRODUCT = "Ares"


def _html() -> str:
    return read_monolith_bundle()


def test_window_title_is_product_name():
    assert re.search(r"<title>\s*Ares\s*</title>", _html())


def test_intro_dialog_label_and_wordmark():
    html = _html()
    assert 'aria-label="Ares wird gestartet"' in html
    assert '<div class="intro-brand">Ares</div>' in html


def test_topbar_logo_is_text_without_monogram():
    html = _html()
    assert '<div class="logo-n">Ares</div>' in html
    # Das Logo-Quadrat (Monogramm) ist als Element entfernt; die CSS-Regel
    # darf bleiben.
    assert '<div class="logo-m">' not in html


def test_login_overlay_shows_product_name():
    html = _html()
    start = html.index('<div id="login-overlay"')
    block = html[start:start + 1500]
    assert '>Ares</div>' in block


_TITLE_ASSIGN = re.compile(r"document\.title\s*=\s*(['\"`])(.*?)\1")


def test_dynamic_window_titles_use_product_name():
    # N-875-07/-08: alle Frontendquellen, alle Quote-Stile.
    from tests.monolith_source import read_frontend_sources

    titles = [m.group(2) for m in _TITLE_ASSIGN.finditer(read_frontend_sources())]
    assert titles, "keine dynamischen Fenstertitel gefunden"
    assert all(t.startswith(PRODUCT) for t in titles), titles


def test_title_detector_handles_all_quote_styles():
    text = "document.title='Ares a';document.title=\"X b\";document.title=`Y ${c}`"
    assert [m.group(2) for m in _TITLE_ASSIGN.finditer(text)] == ["Ares a", "X b", "Y ${c}"]


def test_reporting_index_title_and_cover():
    index = (REPORTING / "index.html").read_text(encoding="utf-8")
    assert re.search(r"<title>\s*Ares\s*</title>", index)
    cover = (REPORTING / "src" / "pages" / "Cover.tsx").read_text(encoding="utf-8")
    assert re.search(r">\s*Ares\s*<", cover)
