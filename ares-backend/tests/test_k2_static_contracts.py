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
    from services.product_market_data import LEGACY_SEED_NAME_SHA256, canonical_seed_name

    names = {r[0] for r in DEFAULT_CATALOG_PRODUCTS}
    assert set(LEGACY_SEED_NAME_SHA256.values()) <= names
    assert len(LEGACY_SEED_NAME_SHA256) == len(set(LEGACY_SEED_NAME_SHA256.values()))
    for name in names:
        assert canonical_seed_name(name) == name and default_market_entry(name) is not None
    text = (REPO / "ares-backend" / "services" / "product_market_data.py").read_text(encoding="utf-8")
    table = text[text.index("LEGACY_SEED_NAME_SHA256"):text.index("def canonical_seed_name")]
    assert not ISSUERS.search(table)


def test_hedged_seed_products_keep_their_chf_hedge_marker():
    from services.portfolio_engine import DEFAULT_CATALOG_PRODUCTS
    from services.product_exposures import hedge_from_product_name

    hedged = [r for r in DEFAULT_CATALOG_PRODUCTS if "abgesichert" in r[0]]
    assert len(hedged) == 11
    assert all(hedge_from_product_name(r[0], r[2]) == (True, "CHF") for r in hedged), hedged


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


# ── KN-B (E2E2-13, N-917-04, N-917-05): Kundentexte im Backend ───────────────
# Emittenten-, Studien-, Vorsorge-/Fintech- und Bankennamen duerfen in keinem
# Kundentext stehen (Kunden-PDFs, Demo-Fall, Kundeninformation/Handoff). Geprueft
# werden nur String-Literale (Kommentare/Docstrings mit Fachbegriffen bleiben).
THIRD_PARTY = re.compile(
    r"\b(Vanguard|Dalbar|QAIB|VIAC|frankly|finpension|BlackRock|iShares|Swisscanto|Pictet|Vontobel|"
    r"Credit Suisse|Swiss Life|Julius B[äa]e?r|Lombard Odier|Morningstar|Amundi|Xtrackers|SPDR|UBS|Raiffeisen|"
    r"ZKB|PostFinance|Swissquote|Kantonalbank|True Wealth|Selma|Brinson|Ibbotson|Beebower|Advisor's Alpha)\b"
)
BACKEND = REPO / "ares-backend"


def _customer_text_sources():
    yield from sorted((BACKEND / "services" / "pdf").rglob("*.py"))
    for rel in ("routers/pdf_reports.py", "services/foundation_example.py", "services/recommendation_release_gate.py",
                "services/portfolio_handoff.py", "services/advisory_report.py"):
        yield BACKEND / rel


def _string_literals(path):
    """String-Literale ohne Docstrings bzw. alleinstehende Kommentar-Strings."""
    import ast
    import io
    import tokenize

    source = path.read_text(encoding="utf-8")
    doc_lines = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            doc_lines.update(range(node.lineno, (node.end_lineno or node.lineno) + 1))
    kinds = {tokenize.STRING} | ({tokenize.FSTRING_MIDDLE} if hasattr(tokenize, "FSTRING_MIDDLE") else set())
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type in kinds and token.start[0] not in doc_lines:
            yield token.start[0], token.string.encode().decode("unicode_escape", "ignore")


def test_no_issuer_study_or_provider_names_in_backend_customer_texts():
    hits = []
    for path in _customer_text_sources():
        for line, literal in _string_literals(path):
            for match in THIRD_PARTY.finditer(literal):
                hits.append(f"{path.relative_to(BACKEND).as_posix()}:{line}: {match.group(0)}")
    assert hits == [], hits


def test_gegenprobe_third_party_pattern_detects_old_texts():
    assert THIRD_PARTY.search("(vgl. Dalbar QAIB-Studien; Vanguard «Advisor's Alpha»)")
    assert THIRD_PARTY.search('pension_institution="VIAC"')
    assert THIRD_PARTY.search("Brinson, Hood & Beebower, 1986")
    assert not THIRD_PARTY.search("Vorsorgestiftung (Muster) erfolgt substanziell")


def test_foundation_demo_case_has_neutral_pension_provider():
    text = (BACKEND / "services" / "foundation_example.py").read_text(encoding="utf-8")
    assert 'pension_institution="Vorsorgestiftung (Muster)"' in text
