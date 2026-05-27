"""Sprint U-P26 PR A — Tests fuer den Advisory-Report Server-PDF.

PR A deckt nur Cover + Disclaimer + TOC ab. Spaetere Sprints fuegen
weitere Sektion-Tests hinzu.

Test-Strategie:
- `render_advisory_report_pdf_from_payload` mit Inline-Payload —
  schnell, kein DB-Setup, deterministisch
- Bytes-Smoke + ein Mini-Text-Scan auf erwartete Inhalte
- KEIN Pixel-Perfect-Test (zu fragil), aber strukturelle Assertions

ReportLab schreibt Strings im PDF teils mit hex-encoding (FEFF…) — wir
testen über `pypdf.PdfReader` der das transparent dekodiert.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


from services.pdf.documents.advisory_report import (  # noqa: E402
    render_advisory_report_pdf_from_payload,
)


def _make_minimal_payload() -> dict:
    """Liefert ein gültiges Aggregator-ähnliches Payload mit Minimal-Daten
    für Cover/Disclaimer/TOC/Ausgangslage/Positionen."""
    return {
        "schema_version": 2,
        "mandate_id": "test-mandate-id",
        "generated_at": "2026-05-27T14:32:00.000Z",
        "cover": {
            "title": "Depotcheck",
            "subtitle": "Strategische Portfolioanalyse",
            "client_name": "Hans Muster",
            "mandate_number": "MX-FOUNDATION-01",
            "report_date": "2026-05-27",
            "advisor_name": "Anna Beispiel",
        },
        "disclaimer": {
            "hinweise": [
                "Dieser Bericht dient ausschliesslich Beratungszwecken.",
                "Vergangene Performance ist kein Indikator fuer kuenftige Renditen.",
                "Monte-Carlo-Simulationen sind Modellrechnungen mit Modell-Risiken.",
            ],
        },
        "inhaltsverzeichnis": {
            "kapitel": [
                {"nr": 1, "title": "Ausgangslage"},
                {"nr": 2, "title": "Übersicht Ihrer Positionen"},
                {"nr": 3, "title": "Was wir im Depotcheck prüfen"},
            ],
        },
        "ausgangslage": {
            "client_info": {
                "alter": 49,
                "anlagehorizont_jahre": 16,
                "risikoprofil": "Defensiv",
                "anlageziel": "Frühpension mit 60",
                "liquiditaetsbedarf_rappen": 6_600_000,
                "steuerdomizil": "CH",
                "referenzwaehrung": "CHF",
            },
            "wealth_summary": {
                "gesamtvermoegen_rappen": 250_000_000,
                "beratungsvermoegen_rappen": 180_000_000,
                "immobilien_rappen": 50_000_000,
                "vorsorge_rappen": 20_000_000,
                "kredite_rappen": 0,
                "cashflows": [],
                "ziele": [],
            },
            "key_metrics": {
                "risky_fraction_bps": 4250,
                "zielerreichung_bps": 8500,
                "exp_vol_bps": 1100,
                "exp_return_bps": 380,
                "max_drawdown_bps": 1620,
                "var_95_bps": 980,
            },
        },
        "pruefpunkte": {
            "bloecke": [
                {
                    "key": "diversifikation",
                    "title": "Diversifikation",
                    "beschreibung": "Streuung über Anlageklassen und Regionen.",
                },
                {
                    "key": "waehrungsrisiken",
                    "title": "Währungsrisiken",
                    "beschreibung": "Anteil Fremdwährungen zur Referenzwährung.",
                },
            ],
        },
        "erkenntnisse": {
            "checks": [
                {
                    "pruefpunkt": "Diversifikation",
                    "bewertung": "gruen",
                    "beurteilung": "Portfolio ist breit gestreut.",
                    "handlungsempfehlung": "Beibehalten.",
                },
                {
                    "pruefpunkt": "Währungsrisiken",
                    "bewertung": "gelb",
                    "beurteilung": "CHF-Anteil bei 55 %.",
                    "handlungsempfehlung": "Hedge prüfen.",
                },
                {
                    "pruefpunkt": "Risikobudget",
                    "bewertung": "rot",
                    "beurteilung": "Über dem Cap.",
                    "handlungsempfehlung": "Risiko reduzieren.",
                },
                {
                    "pruefpunkt": "Liquidität",
                    "bewertung": "nicht_beurteilbar",
                    "beurteilung": "Daten unvollständig.",
                    "handlungsempfehlung": "Cashflow-Erfassung nachpflegen.",
                },
            ],
        },
        "positionen": {
            "groups": [
                {
                    "key": "equities",
                    "label": "Aktien",
                    "share_bps": 2500,
                    "total_rappen": 45_000_000,
                    "positions": [
                        {
                            "isin": "CH0244767585",
                            "product_name": "Test-ETF SPI Schweiz",
                            "product_type": "ETF",
                            "sub_asset_class": "Aktien Schweiz",
                            "currency": "CHF",
                            "market_value_rappen": 30_000_000,
                            "ter_bps": 10,
                            "provider": "Anbieter A",
                            "share_bps": 1665,
                        },
                    ],
                },
            ],
            "total_rappen": 45_000_000,
            "has_recommendation_run": True,
            "hinweis": "Daten basieren auf der aktuellen Empfehlung.",
        },
    }


# ---------------------------------------------------------------------------
# 1) Bytes-Smoke: gibt PDF-Bytes zurück
# ---------------------------------------------------------------------------

def test_render_returns_pdf_bytes():
    payload = _make_minimal_payload()
    pdf = render_advisory_report_pdf_from_payload(payload)
    assert isinstance(pdf, (bytes, bytearray))
    assert len(pdf) > 1000, "PDF wirkt verdaechtig klein"
    assert pdf[:5] == b"%PDF-", "Magic Bytes fehlen — kein PDF"


# ---------------------------------------------------------------------------
# 2) Strukturelle Assertions via pypdf
# ---------------------------------------------------------------------------

def test_pdf_has_at_least_three_pages_cover_disclaimer_toc():
    pypdf = pytest.importorskip("pypdf")
    payload = _make_minimal_payload()
    pdf = render_advisory_report_pdf_from_payload(payload)
    reader = pypdf.PdfReader(__import__("io").BytesIO(pdf))
    # Cover + Disclaimer + TOC → mindestens 3 Seiten (kann mehr sein bei
    # langem Disclaimer-Text)
    assert len(reader.pages) >= 3, (
        f"Erwartet mindestens 3 Seiten (Cover/Disclaimer/TOC), "
        f"PDF hat {len(reader.pages)}"
    )


def test_cover_contains_mandate_and_client_and_advisor():
    pypdf = pytest.importorskip("pypdf")
    payload = _make_minimal_payload()
    pdf = render_advisory_report_pdf_from_payload(payload)
    reader = pypdf.PdfReader(__import__("io").BytesIO(pdf))
    cover_text = reader.pages[0].extract_text() or ""
    # Mandat-Nummer + Client + Advisor müssen auf dem Cover sein
    assert "MX-FOUNDATION-01" in cover_text, (
        f"Mandat-Nr. nicht im Cover gefunden. Cover-Text: {cover_text[:300]}"
    )
    assert "Hans Muster" in cover_text
    assert "Anna Beispiel" in cover_text


def test_cover_uses_swiss_date_format():
    """Swiss-Format DD.MM.YYYY (nicht ISO YYYY-MM-DD)."""
    pypdf = pytest.importorskip("pypdf")
    payload = _make_minimal_payload()
    pdf = render_advisory_report_pdf_from_payload(payload)
    reader = pypdf.PdfReader(__import__("io").BytesIO(pdf))
    cover_text = reader.pages[0].extract_text() or ""
    assert "27.05.2026" in cover_text, (
        f"Swiss-Datum fehlt. Cover-Text: {cover_text[:300]}"
    )
    # ISO-Variante darf nicht durchschlagen
    assert "2026-05-27" not in cover_text, (
        "ISO-Datum 2026-05-27 sollte nicht im Cover sein (Swiss-Format erwartet)"
    )


def test_disclaimer_lists_all_hinweise():
    pypdf = pytest.importorskip("pypdf")
    payload = _make_minimal_payload()
    pdf = render_advisory_report_pdf_from_payload(payload)
    reader = pypdf.PdfReader(__import__("io").BytesIO(pdf))
    disclaimer_text = reader.pages[1].extract_text() or ""
    assert "Rechtliche Hinweise" in disclaimer_text
    for hinweis in payload["disclaimer"]["hinweise"]:
        # Erstes Wort als Indicator (Substring-Match wegen Umbrueche)
        first_words = hinweis.split(".")[0][:30]
        assert first_words in disclaimer_text, (
            f"Hinweis '{first_words}…' fehlt im Disclaimer"
        )


def test_toc_lists_kapitel_in_order():
    pypdf = pytest.importorskip("pypdf")
    payload = _make_minimal_payload()
    pdf = render_advisory_report_pdf_from_payload(payload)
    reader = pypdf.PdfReader(__import__("io").BytesIO(pdf))
    toc_text = reader.pages[2].extract_text() or ""
    assert "Inhaltsverzeichnis" in toc_text
    # Reihenfolge der Kapitel muss erhalten sein
    titles = [k["title"] for k in payload["inhaltsverzeichnis"]["kapitel"]]
    positions = [toc_text.find(t) for t in titles]
    assert all(p >= 0 for p in positions), (
        f"Mindestens ein Kapitel fehlt im TOC. Positionen: {positions}"
    )
    assert positions == sorted(positions), (
        f"Kapitel-Reihenfolge nicht respektiert: {positions}"
    )


# ---------------------------------------------------------------------------
# 3) Branding-Disziplin: keine Dritt-Marken im PDF
# ---------------------------------------------------------------------------

def test_pdf_contains_no_third_party_brands_in_layout():
    """Memory-Regel: NIE Swiss Life, 3eyes etc. im EIGENEN PDF-Layout
    (Wordmark, Tagline, Disclaimer-Texte, Headers/Footers).

    Echte Produktnamen aus den Daten (z. B. 'UBS ETF', 'Pictet Global')
    sind im echten Mandat erlaubt — sie kommen aus dem Empfehlungs-Run,
    nicht aus dem 5eyes-Branding. Daher prüfen wir hier nur das Layout,
    indem wir das Test-Payload mit anonymisierten Produktnamen befüllen.
    """
    pypdf = pytest.importorskip("pypdf")
    payload = _make_minimal_payload()
    # Sicherheitscheck: Test-Daten dürfen keine Dritt-Marken enthalten,
    # damit wir das Layout ehrlich prüfen können.
    forbidden = ["swiss life", "3eyes"]
    pdf = render_advisory_report_pdf_from_payload(payload)
    reader = pypdf.PdfReader(__import__("io").BytesIO(pdf))
    all_text = "\n".join((p.extract_text() or "") for p in reader.pages).lower()
    for term in forbidden:
        assert term not in all_text, f"Verbotene Marke '{term}' im PDF-Layout"


# ---------------------------------------------------------------------------
# 4) Defensiv gegen leere/fehlende Felder
# ---------------------------------------------------------------------------

def test_render_handles_missing_optional_fields():
    payload = {
        "schema_version": 2,
        "mandate_id": "x",
        "generated_at": "",
        "cover": {},
        "disclaimer": {},
        "inhaltsverzeichnis": {},
    }
    pdf = render_advisory_report_pdf_from_payload(payload)
    assert pdf[:5] == b"%PDF-"
    assert len(pdf) > 500


def test_render_handles_special_characters_in_names():
    """XSS-style mini-HTML in Client-Name darf das Layout nicht brechen."""
    payload = _make_minimal_payload()
    payload["cover"]["client_name"] = "<script>alert('xss')</script> & Co."
    pdf = render_advisory_report_pdf_from_payload(payload)
    assert pdf[:5] == b"%PDF-"

    pypdf = pytest.importorskip("pypdf")
    reader = pypdf.PdfReader(__import__("io").BytesIO(pdf))
    cover_text = reader.pages[0].extract_text() or ""
    # Der escape-Mechanismus muss den literal Text rendern, nicht als HTML
    # interpretieren. Substring-Test reicht.
    assert "script" in cover_text  # der Text ist drin, aber als literal


# ---------------------------------------------------------------------------
# Sektion 4 — Ausgangslage (U-P26 PR B)
# ---------------------------------------------------------------------------

def test_ausgangslage_shows_client_info_with_swiss_formatting():
    pypdf = pytest.importorskip("pypdf")
    payload = _make_minimal_payload()
    pdf = render_advisory_report_pdf_from_payload(payload)
    reader = pypdf.PdfReader(__import__("io").BytesIO(pdf))
    # Cover (1) + Disclaimer (2) + TOC (3) + Ausgangslage (4)
    assert len(reader.pages) >= 4
    ausgangslage_text = reader.pages[3].extract_text() or ""
    assert "Ausgangslage" in ausgangslage_text
    assert "49 Jahre" in ausgangslage_text
    assert "16 Jahre" in ausgangslage_text  # Horizont
    assert "Defensiv" in ausgangslage_text
    assert "Frühpension mit 60" in ausgangslage_text
    # Swiss-Format: 6'600'000 Rappen → CHF 66'000
    assert "66'000" in ausgangslage_text


def test_ausgangslage_shows_wealth_summary_with_categories():
    pypdf = pytest.importorskip("pypdf")
    payload = _make_minimal_payload()
    pdf = render_advisory_report_pdf_from_payload(payload)
    reader = pypdf.PdfReader(__import__("io").BytesIO(pdf))
    page_text = reader.pages[3].extract_text() or ""
    assert "Gesamtvermögen" in page_text
    assert "Beratungsvermögen" in page_text
    assert "Immobilien" in page_text
    assert "Vorsorge" in page_text
    # CHF 2'500'000 (250 Mio Rappen)
    assert "2'500'000" in page_text


def test_ausgangslage_shows_six_key_metrics():
    pypdf = pytest.importorskip("pypdf")
    payload = _make_minimal_payload()
    pdf = render_advisory_report_pdf_from_payload(payload)
    reader = pypdf.PdfReader(__import__("io").BytesIO(pdf))
    page_text = reader.pages[3].extract_text() or ""
    # alle 6 KPI-Karten müssen ihre Labels haben
    for label in [
        "Risky-Fraction", "Zielerreichung", "Erw. Volatilität",
        "Erw. Rendite", "Max Drawdown", "VaR 95",
    ]:
        assert label in page_text, f"KPI-Karte '{label}' fehlt"
    # Werte: 4250 bps -> 42.5 %, 8500 -> 85.0 %, 1100 -> 11.0 %
    assert "42.5 %" in page_text
    assert "85.0 %" in page_text


def test_ausgangslage_renders_dash_for_missing_age():
    payload = _make_minimal_payload()
    payload["ausgangslage"]["client_info"]["alter"] = 0
    payload["ausgangslage"]["client_info"]["liquiditaetsbedarf_rappen"] = 0
    pdf = render_advisory_report_pdf_from_payload(payload)
    pypdf = pytest.importorskip("pypdf")
    reader = pypdf.PdfReader(__import__("io").BytesIO(pdf))
    page_text = reader.pages[3].extract_text() or ""
    # Alter 0 darf NICHT als "0 Jahre" auftauchen — sondern als Dash
    assert "0 Jahre" not in page_text


# ---------------------------------------------------------------------------
# Sektion 5 — Positionen (U-P26 PR B)
# ---------------------------------------------------------------------------

def test_positionen_groups_show_bucket_label_and_total():
    pypdf = pytest.importorskip("pypdf")
    payload = _make_minimal_payload()
    pdf = render_advisory_report_pdf_from_payload(payload)
    reader = pypdf.PdfReader(__import__("io").BytesIO(pdf))
    # Cover/Disclaimer/TOC/Ausgangslage/Positionen = mindestens 5 Seiten
    assert len(reader.pages) >= 5
    positionen_text = reader.pages[4].extract_text() or ""
    assert "Übersicht Ihrer Positionen" in positionen_text
    assert "Aktien" in positionen_text
    assert "Test-ETF SPI Schweiz" in positionen_text
    assert "CH0244767585" in positionen_text
    # 30 Mio Rappen → CHF 300'000
    assert "300'000" in positionen_text


def test_positionen_handles_empty_groups_gracefully():
    """Mandat ohne Empfehlungen → Hinweis statt Crash."""
    payload = _make_minimal_payload()
    payload["positionen"] = {
        "groups": [],
        "total_rappen": 0,
        "has_recommendation_run": False,
        "hinweis": "Noch keine Empfehlung erfasst.",
    }
    pdf = render_advisory_report_pdf_from_payload(payload)
    assert pdf[:5] == b"%PDF-"
    pypdf = pytest.importorskip("pypdf")
    reader = pypdf.PdfReader(__import__("io").BytesIO(pdf))
    page_text = reader.pages[4].extract_text() or ""
    assert "Noch keine Empfehlung" in page_text


def test_positionen_total_is_swiss_formatted():
    pypdf = pytest.importorskip("pypdf")
    payload = _make_minimal_payload()
    pdf = render_advisory_report_pdf_from_payload(payload)
    reader = pypdf.PdfReader(__import__("io").BytesIO(pdf))
    page_text = reader.pages[4].extract_text() or ""
    # 45 Mio Rappen → CHF 450'000
    assert "450'000" in page_text


# ---------------------------------------------------------------------------
# Sektion 6 — Prüfpunkte (U-P26 PR C)
# ---------------------------------------------------------------------------

def test_pruefpunkte_lists_all_titles_and_descriptions():
    pypdf = pytest.importorskip("pypdf")
    payload = _make_minimal_payload()
    pdf = render_advisory_report_pdf_from_payload(payload)
    reader = pypdf.PdfReader(__import__("io").BytesIO(pdf))
    # Cover/Disclaimer/TOC/Ausgangslage/Positionen/Pruefpunkte = mind. 6 Seiten
    assert len(reader.pages) >= 6
    page_text = reader.pages[5].extract_text() or ""
    assert "Was wir im Depotcheck prüfen" in page_text
    assert "Diversifikation" in page_text
    assert "Währungsrisiken" in page_text
    assert "Streuung über Anlageklassen" in page_text


def test_pruefpunkte_handles_empty_block_list():
    payload = _make_minimal_payload()
    payload["pruefpunkte"] = {"bloecke": []}
    pdf = render_advisory_report_pdf_from_payload(payload)
    assert pdf[:5] == b"%PDF-"
    pypdf = pytest.importorskip("pypdf")
    reader = pypdf.PdfReader(__import__("io").BytesIO(pdf))
    page_text = reader.pages[5].extract_text() or ""
    assert "Keine Prüfpunkte" in page_text


# ---------------------------------------------------------------------------
# Sektion 7 — Erkenntnisse mit Ampel-Pills (U-P26 PR C)
# ---------------------------------------------------------------------------

def test_erkenntnisse_shows_all_pruefpunkte_with_ampel():
    pypdf = pytest.importorskip("pypdf")
    payload = _make_minimal_payload()
    pdf = render_advisory_report_pdf_from_payload(payload)
    reader = pypdf.PdfReader(__import__("io").BytesIO(pdf))
    # Cover/Disclaimer/TOC/Ausgangslage/Positionen/Pruefpunkte/Erkenntnisse = mind. 7
    assert len(reader.pages) >= 7
    page_text = reader.pages[6].extract_text() or ""
    assert "Erkenntnisse aus dem Depotcheck" in page_text
    # alle 4 Prüfpunkte und ihre Beurteilung
    assert "Diversifikation" in page_text
    assert "Portfolio ist breit gestreut" in page_text
    assert "CHF-Anteil bei 55" in page_text
    assert "Über dem Cap" in page_text


def test_erkenntnisse_renders_all_four_ampel_labels():
    """gruen→OK / gelb→Achtung / rot→Handeln / nicht_beurteilbar→Pendant.

    pypdf bricht schmale Cell-Texte teils auf zwei Zeilen um — wir
    vergleichen daher gegen den Text ohne Zeilenwechsel/Whitespace,
    damit der Test stabil bleibt.
    """
    pypdf = pytest.importorskip("pypdf")
    payload = _make_minimal_payload()
    pdf = render_advisory_report_pdf_from_payload(payload)
    reader = pypdf.PdfReader(__import__("io").BytesIO(pdf))
    raw = reader.pages[6].extract_text() or ""
    normalized = "".join(raw.split())  # whitespace incl. \n weg
    for label in ["OK", "Achtung", "Handeln", "Pendant"]:
        assert label in normalized, (
            f"Ampel-Label '{label}' fehlt. Normalisiert: {normalized[:600]}"
        )


def test_erkenntnisse_unknown_bewertung_falls_back_to_pendant():
    """Unbekannte Ampel-Werte → 'Pendant' (kein Crash)."""
    pypdf = pytest.importorskip("pypdf")
    payload = _make_minimal_payload()
    payload["erkenntnisse"]["checks"] = [{
        "pruefpunkt": "Mystery",
        "bewertung": "abracadabra",
        "beurteilung": "Test",
        "handlungsempfehlung": "—",
    }]
    pdf = render_advisory_report_pdf_from_payload(payload)
    reader = pypdf.PdfReader(__import__("io").BytesIO(pdf))
    page_text = reader.pages[6].extract_text() or ""
    assert "Pendant" in page_text


def test_erkenntnisse_handles_empty_checks():
    payload = _make_minimal_payload()
    payload["erkenntnisse"] = {"checks": []}
    pdf = render_advisory_report_pdf_from_payload(payload)
    pypdf = pytest.importorskip("pypdf")
    reader = pypdf.PdfReader(__import__("io").BytesIO(pdf))
    page_text = reader.pages[6].extract_text() or ""
    assert "Keine Erkenntnisse" in page_text
