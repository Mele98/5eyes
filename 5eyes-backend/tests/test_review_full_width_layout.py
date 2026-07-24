"""2026-07-24: Review & Abschluss nutzt die volle Seitenbreite.

User-Feedback: die Sektion war in einem schmalen, zentrierten 1080px-Block
gefangen ("alles in der Mitte") -- auf breiten Bildschirmen wirkte das leer
und wenig kundenfreundlich. Storytelling-Prinzip: Hero (Kopfaussage) volle
Breite, Kennzahlen-Uebersicht (Kennzahlen + Risikoprofil) daneben statt
darunter gestapelt, Details bleiben im Accordion/in Disclosures.
"""
from __future__ import annotations

from pathlib import Path


HTML_PATH = Path(__file__).resolve().parents[2] / "5eyes-electron" / "frontend" / "5eyes_v2.html"


def _html() -> str:
    return HTML_PATH.read_text(encoding="utf-8")


def test_page_rv_pad_no_longer_capped_narrow():
    html = _html()
    assert "#page-rv .pad{max-width:1080px;margin:0 auto" not in html
    assert "#page-rv .pad{width:100%;max-width:none;margin:0" in html


def test_review_overview_is_a_wide_two_column_grid():
    html = _html()
    idx = html.find(".rv-review-overview{")
    assert idx > 0
    block = html[idx: idx + 400]
    assert "display:grid" in block
    assert "grid-template-columns:minmax(0,1.7fr) minmax(280px,1fr)" in block


def test_hero_and_cockpit_span_full_width_kpis_sit_beside():
    html = _html()
    assert ".rv-review-overview>#rv-hero{grid-column:1/-1" in html
    assert ".rv-review-overview>#rv-cockpit{grid-column:1;grid-row:2" in html
    assert ".rv-review-overview>.rv-final-kpis{grid-column:2;grid-row:2" in html
    assert ".rv-review-overview>#sr-riskprofile-card{grid-column:2;grid-row:3" in html


def test_narrow_viewport_falls_back_to_single_column():
    html = _html()
    breakpoint_idx = html.find("@media(max-width:1100px){")
    assert breakpoint_idx > 0
    block = html[breakpoint_idx: breakpoint_idx + 600]
    assert ".rv-review-overview{grid-template-columns:1fr;}" in block
