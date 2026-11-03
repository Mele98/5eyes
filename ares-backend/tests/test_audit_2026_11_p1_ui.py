"""Audit 2026-11, Paket P1: Monolith-UI fuer Stammdaten und Retrozessions-Block."""
from __future__ import annotations

from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]

# ---------------------------------------------------------------------------
# 7. Monolith-UI: Stammdaten erfassbar, Kennzeichnung sichtbar, Retro-Block
# ---------------------------------------------------------------------------

HTML_PATH = BACKEND_ROOT.parent / "ares-desktop" / "frontend" / "ares.html"


def test_monolith_exposes_master_data_and_retro_block():
    html = HTML_PATH.read_text(encoding="utf-8")
    for element_id in ("pf-domicile", "pf-is-hedged", "pf-hedge-currency", "pf-ter-source",
                       "pf-ter-as-of", "pf-retro", "pf-retro-source", "pf-house-product",
                       "pf-distribution", "pf-valor", "pf-min-investment", "cd-retro"):
        assert f'id="{element_id}"' in html, element_id
    assert "Retrozession unbekannt" in html
    assert "ISIN ungueltig" in html
    body = html[html.index("function renderCostDisclosure(data){"):]
    assert "renderCostRetrocessions(data);" in body[:400]
    collect = html[html.index("function adminCollectFundMasterData"):]
    # leer beim Bearbeiten = explizit null (zurueck auf "unbekannt"), nie 0
    assert "payload.retrocession_bps = null;" in collect[:2500]
