"""Bugfix 2026-08-07 (CEO/CFO/CIO-Audit, MD-01, Abschluss): der Backend-
Endpoint /products/market-data/status lieferte currency_mismatch_count +
samples.currency_mismatches bereits korrekt (services.product_market_data.
currency_mismatch_warning, siehe test_md01_currency_exchange_mismatch.py),
aber das Frontend hat den Wert nur ABGERUFEN, nie GERENDERT --
formatAdminMarketSummary() zeigte lediglich OpenFIGI-/Referenzdaten-Luecken
an, die Waehrungs-Konflikte waren fuer den Berater komplett unsichtbar.
Dieselbe Bugklasse wie das E-Signing-Sichtbarkeitsproblem (d48c8d5).
"""
from __future__ import annotations

from pathlib import Path

FRONTEND_HTML = (
    Path(__file__).resolve().parents[2]
    / "5eyes-electron" / "frontend" / "5eyes_v2.html"
)


def _html() -> str:
    return FRONTEND_HTML.read_text(encoding="utf-8")


def test_currency_mismatch_count_rendered_as_status_card():
    html = _html()
    start = html.find("function formatAdminMarketSummary")
    assert start != -1
    end = html.find("\nfunction setAdminMarketActionState", start)
    block = html[start:end]
    assert "currency_mismatch_count" in block, (
        "formatAdminMarketSummary() muss currency_mismatch_count anzeigen"
    )


def test_currency_mismatch_samples_rendered_as_section():
    html = _html()
    start = html.find("function formatAdminMarketSummary")
    end = html.find("\nfunction setAdminMarketActionState", start)
    block = html[start:end]
    assert "samples.currency_mismatches" in block
    assert "currencyMismatchSamples" in block
    # Jeder Sample-Eintrag muss die vom Backend gelieferte warning-Botschaft zeigen.
    assert "item.warning" in block
