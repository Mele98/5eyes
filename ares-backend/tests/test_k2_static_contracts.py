"""K2 (Dok. 115) -- statische Vertraege der Berater-Oberflaeche.

* E2E-10: keine Drittbank-Namen als Vorgabe, Option oder Platzhalter in den
  Frontendquellen und im Demo-Fall; ohne Wahl geht keine Depotbank an die
  Empfehlung (die Positionsbegruendung nennt dann keinen Banknamen).
* E2E-17: keine statischen Demo-Mandate/Platzhalterdaten im Monolithen.
* E2E-02: ``single_person_firm`` ist in der Oberflaeche setzbar (nicht nur per API).
* Der neue Teil ``advisor-guidance.js`` ist genau einmal eingebunden und gehoert
  zum Monolith-Bundle (Budget, Verbots-Guards).
"""
from __future__ import annotations

import re
from pathlib import Path

from tests.monolith_source import read_frontend_sources, read_monolith_bundle

REPO = Path(__file__).resolve().parents[2]
FRONTEND = REPO / "ares-desktop" / "frontend"
# Drittbanken, die frueher als Vorgabe/Platzhalter im Produkt standen (Fremdmarken-Verbot).
BANKS = re.compile(r"\b(UBS AG|UBS,|ZKB|Raiffeisen|Swissquote|PostFinance|BEKB|Sichtguthaben UBS|Depot UBS)\b")


def test_no_third_party_bank_names_in_frontend_sources():
    src = read_frontend_sources()
    hits = sorted(set(m.group(0) for m in BANKS.finditer(src)))
    assert hits == [], hits


def test_gegenprobe_bank_pattern_detects_old_default():
    assert BANKS.search("var b=getInputValue('recipe-depot-bank')||'UBS AG Zürich';")
    assert BANKS.search('<select><option>ZKB</option></select>')


def test_recommendation_depot_bank_defaults_to_none():
    bundle = read_monolith_bundle()
    calls = re.findall(r"getInputValue\('recipe-depot-bank'\)\|\|([^;]+);", bundle)
    assert calls and set(calls) <= {"null", "'')"}, calls  # nie ein vorbelegter Bankname


def test_foundation_demo_case_uses_neutral_bank_labels():
    text = (REPO / "ares-backend" / "services" / "foundation_example.py").read_text(encoding="utf-8")
    assert not BANKS.search(text.replace("\\u00fc", "ü"))
    assert "Depotbank (Muster)" in text


def test_no_static_demo_mandates_or_placeholder_people():
    html = read_monolith_bundle()
    for needle in ("Familie Mueller-Weber", 'data-pid="HH-001"', 'id="alert-count"', "CHF 3.9 Mio",
                   'id="m-edit-depot"', 'id="m-edit-hypo"', 'id="m-edit-custom"', 'id="m-edit-immo"'):
        assert needle not in html, needle


def test_single_person_firm_is_settable_in_the_ui_and_module_is_bundled():
    from tests.monolith_source import EXTRACTED_PARTS

    # read_monolith_bundle() prueft selbst, dass jede Einbindung genau einmal vorkommt.
    assert ("advisor-guidance.js", "js") in EXTRACTED_PARTS
    module = (FRONTEND / "advisor-guidance.js").read_text(encoding="utf-8")
    assert "single_person_firm" in module
    assert "API.put('/tenants/me', {single_person_firm: want})" in module
    bundle = read_monolith_bundle()
    assert "function publishFourEyesFlow" in bundle and "askSinglePersonFirmAfterBootstrap" in bundle


# K2-Nachtrag 1 (N-915-03/04): Wächter auch im Backend -- Seed-Katalog, Marktprofile,
# Demo-Fall und Portfolio-PDF tragen keine Emittenten- oder Banknamen.
ISSUERS = re.compile(
    r"(BlackRock|iShares|Vanguard|VanEck|State Street|SPDR|WisdomTree|Roundhill|JPMorgan|\bJPM\b|Amundi|"
    r"Swisscanto|PIMCO|Man AHL|Man Group|Partners Group|21Shares|\bUBS\b|\bZKB\b|Raiffeisen|Swissquote|"
    r"PostFinance|Pictet|Vontobel|Julius)")


def test_gegenprobe_issuer_pattern_detects_old_seed_names():
    assert ISSUERS.search("ZKB Gold ETF") and ISSUERS.search("iShares Core SPI ETF")
    assert ISSUERS.search('("UBS Geldmarktfonds CHF", "UBS", "Fonds")')


def test_seed_catalog_and_market_profiles_are_neutral():
    from services.portfolio_engine import DEFAULT_CATALOG_PRODUCTS, HEDGED_PRODUCT_VARIANTS
    from services.product_market_data import DEFAULT_PRODUCT_MARKET_CATALOG

    rows = list(DEFAULT_CATALOG_PRODUCTS) + list(HEDGED_PRODUCT_VARIANTS)
    hits = sorted({f"{r[0]} / {r[1]}" for r in rows if ISSUERS.search(f"{r[0]} {r[1]}")})
    assert hits == [], hits
    profile_hits = sorted(k for k, v in DEFAULT_PRODUCT_MARKET_CATALOG.items()
                          if ISSUERS.search(k) or ISSUERS.search(str(v.get("pricing_note") or "")))
    assert profile_hits == [], profile_hits
    # Anbieter bleiben unterscheidbar (Einzelemittentenlimite wirkt unveraendert).
    providers = {r[1] for r in rows if r[1] != "Hausbank"}
    assert len(providers) >= 10 and all(p.startswith("Musteranbieter ") for p in providers)


def test_legacy_seed_names_still_resolve_without_plaintext():
    from services.portfolio_engine import DEFAULT_CATALOG_PRODUCTS
    from services.product_market_data import default_market_entry
    from services.seed_catalog_names import LEGACY_SEED_NAME_SHA256, canonical_seed_name

    names = {r[0] for r in DEFAULT_CATALOG_PRODUCTS}
    assert set(LEGACY_SEED_NAME_SHA256.values()) <= names
    assert len(LEGACY_SEED_NAME_SHA256) == len(set(LEGACY_SEED_NAME_SHA256.values()))
    for name in names:
        assert canonical_seed_name(name) == name and default_market_entry(name) is not None
    text = (REPO / "ares-backend" / "services" / "seed_catalog_names.py").read_text(encoding="utf-8")
    assert not ISSUERS.search(text)


def test_foundation_demo_and_portfolio_pdf_are_neutral():
    from datetime import date
    from io import BytesIO

    from pypdf import PdfReader

    from services.pdf.base import PDFContext, PortfolioData
    from services.pdf.reportlab_renderer import ReportLabRenderer
    from services.portfolio_engine import DEFAULT_CATALOG_PRODUCTS

    demo = (REPO / "ares-backend" / "services" / "foundation_example.py").read_text(encoding="utf-8")
    assert not ISSUERS.search(demo) and "CH93 0024" not in demo
    positions = [{"name": r[0], "provider": r[1], "isin": None, "asset_class": r[3], "sub_asset_class": r[4],
                  "target_weight_bps": 400, "target_amount_rappen": 4_000_00, "ter_bps": r[6] or 0}
                 for r in DEFAULT_CATALOG_PRODUCTS[:25]]
    ctx = PDFContext(mandate_name="Testkunde Fiktiv", advisor_name="Beraterin Fiktiv", advisor_org="Testfirma Fiktiv AG",
                     report_date=date(2026, 11, 19), audit_hash="k2n91503k2n91503k2n91503", locale="de-CH")
    pdf = ReportLabRenderer().render_portfolio(ctx, PortfolioData(mandate_number="M-K2", advisory_wealth_rappen=100_000_00,
                                                                  positions=positions))
    text = "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(pdf)).pages)
    assert not ISSUERS.search(text), ISSUERS.findall(text)
    assert "Musterprodukt" in text
