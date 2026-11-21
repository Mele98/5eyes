"""Live-Test 2026-11 H2/H3 -- PDFs rechneten Haupt- und Subklassen auf zwei
Basen und die abgezogene Liquiditaetsreserve war unsichtbar.

Rechenbasis (im Code geklaert, unveraendert):
``services/portfolio_engine.py`` zieht die externe Reserve vor der SAA ab
(``_investable_advisory_wealth_rappen`` = Beratungsvermoegen - externe
Reserve) und weist ``strategy_base_rappen`` aus. Die Klassen- und Subklassen-
Gewichte der TargetAllocation beziehen sich auf DIESE Basis; Bucket-Betraege
im App-Payload sind ``strategy_base * target_bps`` (Aktien 47.8 % von 141'000
= 67'398), die Produktempfehlung ebenso ("Zielvolumen CHF 141'000").

Befund im Live-Test (150'000 Beratungsvermoegen, 9'000 externe Reserve):
- Hauptklassen in Anlagestrategie- und AA-PDF auf 150'000 (Aktien 71'700),
  Subklassen auf 141'000 (CH 33'699 + Global 26'959 + Europa 6'740 = 67'398),
  obwohl der Text sagt "Die Summe der Detailquoten entspricht der jeweiligen
  Hauptanlageklasse".
- Die 9'000 Reserve erschien nirgends.
- Das AA-PDF las die Subklassen aus der Produktempfehlung: EM (2.4 %) war in
  "Aktien Schweiz 23.9 %" enthalten statt als eigene SAA-Subklasse (21.5 %).

Soll: eine Basis (Strategiebasis), Reserve als eigene Zeile, Betraege
summieren auf das ausgewiesene Total; Subklassen aus der SAA-Sub-Allokation.
Die Allokationsberechnung selbst bleibt unberuehrt -- getestet wird nur die
Darstellung/Aggregation.
"""
from __future__ import annotations

import re
from datetime import date
from io import BytesIO

import pytest
from pypdf import PdfReader

from services.pdf.base import AnlagestrategieData, PDFContext
from services.pdf.reportlab_renderer import ReportLabRenderer


@pytest.fixture
def ctx() -> PDFContext:
    return PDFContext(
        mandate_name="Muster Person",
        advisor_name="Berater Muster",
        advisor_org="Muster AG",
        report_date=date(2026, 11, 2),
        audit_hash="abc123def456789012345678",
        locale="de-CH",
    )


TARGET_BPS = {"equities": 4780, "bonds": 3900, "real_estate": 500, "alternatives": 500, "liquidity": 320}

SAA_SUBS = [
    {"asset_class": "equities", "sub_asset_class": "Aktien Schweiz", "target_weight_bps": 2151},
    {"asset_class": "equities", "sub_asset_class": "Aktien Global", "target_weight_bps": 1912},
    {"asset_class": "equities", "sub_asset_class": "Aktien Europa", "target_weight_bps": 478},
    {"asset_class": "equities", "sub_asset_class": "Aktien Schwellenlaender", "target_weight_bps": 239},
    {"asset_class": "bonds", "sub_asset_class": "Obligationen CHF IG", "target_weight_bps": 2383},
    {"asset_class": "bonds", "sub_asset_class": "Obligationen Global Hedged", "target_weight_bps": 1517},
    {"asset_class": "real_estate", "sub_asset_class": "Immobilien Schweiz", "target_weight_bps": 400},
    {"asset_class": "real_estate", "sub_asset_class": "Immobilien Global", "target_weight_bps": 100},
    {"asset_class": "alternatives", "sub_asset_class": "Gold / Rohstoffe", "target_weight_bps": 500},
    {"asset_class": "liquidity", "sub_asset_class": "Geldmarktfonds", "target_weight_bps": 320},
]

# Produktempfehlung: EM nicht umsetzbar -> im CH-Produkt (23.9 %), Betraege auf 141'000.
PRODUCTS = [
    {"name": "CH-Aktien-ETF", "asset_class": "equities", "sub_asset_class": "Aktien Schweiz",
     "target_weight_bps": 2390, "target_amount_rappen": 33_699_00},
    {"name": "Welt-ETF", "asset_class": "equities", "sub_asset_class": "Aktien Global",
     "target_weight_bps": 1912, "target_amount_rappen": 26_959_00},
    {"name": "Europa-ETF", "asset_class": "equities", "sub_asset_class": "Aktien Europa",
     "target_weight_bps": 478, "target_amount_rappen": 6_740_00},
]


def _data(*, reserve: bool = True) -> AnlagestrategieData:
    from routers.pdf_reports import _strategy_presentation_amounts

    advisory = 150_000_00
    strategy_base = 141_000_00 if reserve else advisory
    amounts = _strategy_presentation_amounts(advisory, strategy_base, TARGET_BPS, SAA_SUBS)
    return AnlagestrategieData(
        target_allocation_bps=TARGET_BPS,
        cma_expected_return_bps=423,
        cma_expected_vol_bps=754,
        horizon_years=15,
        mandate_number="M-1",
        advisory_wealth_rappen=advisory,
        products=PRODUCTS,
        **amounts,
    )


def _pdf_text(pdf: bytes) -> str:
    return "\n".join(p.extract_text() or "" for p in PdfReader(BytesIO(pdf)).pages)


def _chf_amounts(text: str) -> list[int]:
    return [int(m.replace("'", "")) for m in re.findall(r"CHF ([0-9][0-9']*)", text)]


def test_presentation_amounts_sum_exactly_on_one_basis():
    from routers.pdf_reports import _strategy_presentation_amounts

    out = _strategy_presentation_amounts(150_000_00, 141_000_00, TARGET_BPS, SAA_SUBS)
    assert out["strategy_base_rappen"] == 141_000_00
    assert out["external_reserve_rappen"] == 9_000_00
    assert sum(out["bucket_amounts_rappen"].values()) == 141_000_00
    assert out["bucket_amounts_rappen"]["equities"] == 67_398_00
    subs = out["sub_allocations"]
    eq_subs = [s for s in subs if s["asset_class"] == "equities"]
    assert sum(s["target_amount_rappen"] for s in eq_subs) == out["bucket_amounts_rappen"]["equities"]
    assert sum(s["target_weight_bps"] for s in eq_subs) == TARGET_BPS["equities"]
    assert any(s["sub_asset_class"] == "Aktien Schwellenlaender" for s in eq_subs)


def test_asset_allocation_pdf_uses_strategy_base_and_shows_reserve(ctx):
    text = _pdf_text(ReportLabRenderer().render_asset_allocation(ctx, _data()))
    # Hauptklasse auf der Strategiebasis (nicht 71'700 = 47.8 % von 150'000).
    assert "71'700" not in text
    assert "67'398" in text
    # Reserve als eigene Zeile, Total = Beratungsvermoegen.
    assert "Liquiditätsreserve" in text and "9'000" in text
    assert "150'000" in text


def test_asset_allocation_pdf_lists_saa_em_subclass_not_product_mix(ctx):
    text = _pdf_text(ReportLabRenderer().render_asset_allocation(ctx, _data()))
    assert "Schwellenl" in text, "EM-Subklasse fehlt im AA-PDF"
    assert "21.5 %" in text  # G7: gemeinsamer Formatter
    assert "23.9%" not in text and "23.9 %" not in text, "Produkt-Gewicht (EM im CH-Produkt) statt SAA-Subklasse"


def test_asset_allocation_pdf_subclass_amounts_sum_to_class(ctx):
    text = _pdf_text(ReportLabRenderer().render_asset_allocation(ctx, _data()))
    sub_page = text[text.index("SUBANLAGEKLASSEN"):] if "SUBANLAGEKLASSEN" in text else text[text.index("Subanlageklassen"):]
    lines = sub_page.splitlines()
    i = next(n for n, line in enumerate(lines) if line.startswith("Aktien Total"))
    block = "\n".join(lines[i:i + 16])
    amounts = _chf_amounts(block)
    total, children = amounts[0], amounts[1:5]
    assert total == 67_398
    assert sum(children) == total


def test_strategy_pdf_soll_table_sums_to_advisory_total_with_reserve_row(ctx):
    text = _pdf_text(ReportLabRenderer().render_anlagestrategie(ctx, _data()))
    start = text.index("SOLL-ALLOKATION")
    block = text[start:start + 900]
    assert "71'700" not in block
    assert "Liquiditätsreserve" in block
    assert "9'000" in block
    assert "141'000" in block and "150'000" in block


def test_without_reserve_table_is_unchanged(ctx):
    data = _data(reserve=False)
    assert data.external_reserve_rappen == 0
    text = _pdf_text(ReportLabRenderer().render_asset_allocation(ctx, data))
    assert "Liquiditätsreserve" not in text
    assert "71'700" in text  # 47.8 % von 150'000
