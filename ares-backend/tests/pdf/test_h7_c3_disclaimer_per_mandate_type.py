"""H7 C-3 (Compliance-Audit 2026-11-07, Luecke 3): Disclaimer je Mandatstyp.

Befund an der Basis 2e5dfcc3: Anlagestrategie- und Backtest-PDF druckten fuer
JEDES Mandat denselben Text -- "Bestandteil des Vermoegensverwaltungs-
auftrags", "keine Haftung fuer Verluste" (pauschale Freizeichnung, OR 100),
"nicht als Anlageberatung im rechtlichen Sinne zu verstehen" (auch bei
Anlageberatungsmandaten) und "ausschliesslich an Personen mit Wohnsitz in der
Schweiz" (auch bei DE-Mandaten).

Der Wortlaut ist vorlaeufig und muss von Compliance/Recht gegengelesen
werden; die Tests pinnen die Aussagen, nicht jedes Wort.
"""
from __future__ import annotations

import re
from dataclasses import replace
from datetime import date
from io import BytesIO
from types import SimpleNamespace

import pytest
from pypdf import PdfReader

from services.pdf.base import AnlagestrategieData, BacktestData, PDFContext
from services.pdf.components.static_texts import DISCLAIMER_TEXT, disclaimer_paragraphs
from services.pdf.reportlab_renderer import ReportLabRenderer

MANDATE_TYPES = ("Vermögensverwaltung", "Anlageberatung", "Finanzplanung", "Reporting only", None)
JURISDICTIONS = ("CH", "DE", None, "AT")

FORBIDDEN = (
    "keine Haftung",
    "nicht als Anlageberatung",
    "im rechtlichen Sinne",
    "ausschliesslich an Personen",
)


def _joined(paragraphs) -> str:
    return " ".join(paragraphs)


@pytest.mark.parametrize("mandate_type", MANDATE_TYPES)
@pytest.mark.parametrize("jurisdiction", JURISDICTIONS)
def test_no_blanket_liability_waiver_and_no_advice_denial(mandate_type, jurisdiction):
    text = _joined(disclaimer_paragraphs(mandate_type, jurisdiction))
    for phrase in FORBIDDEN:
        assert phrase not in text, (mandate_type, jurisdiction, phrase)
    assert "Haftung richtet sich nach dem mit Ihnen abgeschlossenen Vertrag" in text
    assert "keine Garantie" in text
    assert "US-Personen" in text


def test_advisory_mandate_names_advisory_not_discretionary_management():
    text = _joined(disclaimer_paragraphs("Anlageberatung", "CH"))
    assert "Anlageberatungsauftrags" in text
    assert "Die Anlageentscheide treffen Sie selbst" in text
    assert "Vermögensverwaltungsauftrags" not in text


def test_discretionary_mandate_names_management_contract():
    text = _joined(disclaimer_paragraphs("Vermögensverwaltung", "CH"))
    assert "Bestandteil des Vermögensverwaltungsauftrags" in text
    assert "Anlageberatungsauftrags" not in text
    # ASCII-Schreibweise aus Altdaten wird gleich behandelt.
    assert disclaimer_paragraphs("Vermoegensverwaltung", "CH") == disclaimer_paragraphs("Vermögensverwaltung", "CH")


def test_consulting_mandate_is_neither_management_nor_advice_denial():
    text = _joined(disclaimer_paragraphs("Finanzplanung", "CH"))
    assert "Finanzplanungsauftrags" in text
    assert "Ein Auftrag zur Vermögensverwaltung ist damit nicht verbunden" in text
    assert "gelten dafür die Pflichten der Anlageberatung" in text


def test_reporting_and_unknown_mandate_type_stay_neutral():
    reporting = _joined(disclaimer_paragraphs("Reporting only", "CH"))
    assert "Reporting-Auftrags" in reporting
    unknown = _joined(disclaimer_paragraphs("irgendwas", "CH"))
    assert "Art und Umfang unserer Dienstleistung ergeben sich aus dem" in unknown
    for text in (reporting, unknown):
        assert "Bestandteil des Vermögensverwaltungsauftrags" not in text


def test_domicile_notice_follows_jurisdiction():
    ch = _joined(disclaimer_paragraphs("Anlageberatung", "CH"))
    de = _joined(disclaimer_paragraphs("Anlageberatung", "DE"))
    other = _joined(disclaimer_paragraphs("Anlageberatung", "AT"))
    assert "mit Wohnsitz in der Schweiz bestimmt" in ch
    assert "Schweizer Fondsleitungen" in ch
    assert "mit Wohnsitz in Deutschland bestimmt" in de
    assert "Wohnsitz in der Schweiz" not in de
    assert "Schweizer Fondsleitungen" not in de
    assert "Verwaltungsgesellschaft" in de
    assert "Wohnsitz in der Schweiz" not in other
    assert "Wohnsitz in Deutschland" not in other
    assert "Wohnsitzstaat" in other
    # Ohne aufgeloesten Code neutral (kein eigener CH-Rueckgriff, N-884-02);
    # NULL -> CH loest allein der zentrale Resolver beim PDF-Kontext auf.
    assert disclaimer_paragraphs("Anlageberatung", None) == disclaimer_paragraphs("Anlageberatung", "AT")


def test_neutral_default_constant_is_ch_without_mandate_type():
    assert DISCLAIMER_TEXT == disclaimer_paragraphs(None, "CH")
    for phrase in FORBIDDEN:
        assert phrase not in _joined(DISCLAIMER_TEXT)


# ---------------------------------------------------------------------------
# Gerenderte PDFs: Anlagestrategie und Backtest drucken die Mandatsvariante.
# ---------------------------------------------------------------------------

def _ctx(**overrides) -> PDFContext:
    return replace(PDFContext(
        mandate_name="Hans Muster",
        advisor_name="Anna Berater",
        advisor_org="Muster Partner AG",
        report_date=date(2026, 11, 7),
        audit_hash="abc123def456789012345678",
        locale="de-CH",
    ), **overrides)


def _pdf_text(pdf_bytes: bytes) -> str:
    reader = PdfReader(BytesIO(pdf_bytes))
    raw = "\n".join(page.extract_text() or "" for page in reader.pages)
    return re.sub(r"\s+", " ", raw)


def _anlagestrategie_data(**overrides) -> AnlagestrategieData:
    defaults = dict(
        target_allocation_bps={
            "equities": 6000, "bonds": 3000, "real_estate": 500,
            "alternatives": 0, "liquidity": 500,
        },
        cma_expected_return_bps=485,
        cma_expected_vol_bps=1120,
        horizon_years=10,
        risk_profile_label="Wachstumsorientiert",
        risk_score_x10=75,
        mandate_number="M-100001",
        advisory_wealth_rappen=1_000_000_00,
    )
    defaults.update(overrides)
    return AnlagestrategieData(**defaults)


def test_anlagestrategie_pdf_advisory_de_prints_matching_disclaimer():
    ctx = _ctx(mandate_type="Anlageberatung", jurisdiction="DE")
    text = _pdf_text(ReportLabRenderer().render_anlagestrategie(ctx, _anlagestrategie_data()))
    assert "Anlageberatungsauftrags" in text
    assert "Wohnsitz in Deutschland" in text
    assert "Anlageberatung im rechtlichen Sinne" not in text
    assert "keine Haftung" not in text
    assert "Wohnsitz in der Schweiz" not in text


def test_anlagestrategie_pdf_falls_back_to_data_mandate_type():
    ctx = _ctx(jurisdiction="CH")
    data = _anlagestrategie_data(mandate_type="Vermögensverwaltung")
    text = _pdf_text(ReportLabRenderer().render_anlagestrategie(ctx, data))
    assert "Vermögensverwaltungsauftrags" in text
    assert "Wohnsitz in der Schweiz bestimmt" in text


def test_backtest_pdf_consulting_prints_matching_disclaimer():
    ctx = _ctx(mandate_type="Finanzplanung", jurisdiction="CH")
    data = BacktestData(mandate_number="M-100001", initial_value_rappen=500_000_00)
    text = _pdf_text(ReportLabRenderer().render_backtest(ctx, data))
    assert "Finanzplanungsauftrags" in text
    assert "keine Haftung" not in text
    assert "Anlageberatung im rechtlichen Sinne" not in text


def test_pdf_context_builder_carries_mandate_type_and_jurisdiction(monkeypatch):
    import routers.pdf_reports as pdf_reports

    class _Query:
        def filter(self, *args, **kwargs):
            return self

        def first(self):
            return None

    class _Db:
        def query(self, *args, **kwargs):
            return _Query()

    monkeypatch.setattr(pdf_reports, "_audit_hash_for_mandate", lambda mandate: "h")
    mandate = SimpleNamespace(
        id="m1", client_id="c1", mandate_number="M-1", base_currency="EUR",
        mandate_type="Anlageberatung", jurisdiction="DE",
    )
    null_mandate = SimpleNamespace(
        id="m2", client_id="c1", mandate_number="M-2", base_currency="CHF",
        mandate_type="Anlageberatung", jurisdiction=None,
    )
    user = SimpleNamespace(full_name="Anna Berater", email=None)
    # C-890-01 N-897-12: der Entwurfs-Check liest KYC aus der DB; der _Db-Stub hat
    # keine Tabellen -- hier geht es nur um Mandatstyp/Jurisdiktion.
    ctx = pdf_reports._build_pdf_context(mandate, user, _Db(), draft_check=False)
    assert ctx.mandate_type == "Anlageberatung"
    assert ctx.jurisdiction == "DE"
    assert pdf_reports._build_pdf_context(null_mandate, user, _Db(), draft_check=False).jurisdiction == "CH"


# ---------------------------------------------------------------------------
# N-884-03: Fusszeile je Mandatstyp, jurisdiktionsneutral, konsistent mit dem
# Disclaimer (keine "Anlageberatung nach FIDLEG" bei anderen Mandaten).
# ---------------------------------------------------------------------------

FOOTER_EXPECT = {
    "Vermögensverwaltung": "im Rahmen des Vermögensverwaltungsauftrags",
    "Anlageberatung": "im Rahmen des Anlageberatungsauftrags",
    "Finanzplanung": "im Rahmen des Finanzplanungsauftrags",
    "Reporting only": "im Rahmen des Reporting-Auftrags",
    None: "der mit Ihnen vereinbarten Dienstleistung",
}


@pytest.mark.parametrize("mandate_type", list(FOOTER_EXPECT))
@pytest.mark.parametrize("jurisdiction", ["CH", "DE"])
def test_footer_matches_mandate_type_on_rendered_pdf(mandate_type, jurisdiction):
    ctx = _ctx(mandate_type=mandate_type, jurisdiction=jurisdiction)
    data = BacktestData(mandate_number="M-100001", initial_value_rappen=500_000_00)
    text = _pdf_text(ReportLabRenderer().render_backtest(ctx, data))
    assert FOOTER_EXPECT[mandate_type] in text
    assert "FIDLEG" not in text
    assert "Dokumentation der Anlageberatung" not in text
    if mandate_type != "Anlageberatung":
        assert "Anlageberatungsauftrags" not in text


def test_pdf_context_resolves_null_jurisdiction_via_central_resolver(monkeypatch):
    import services.pdf.base as base

    seen = []
    real = base.resolve_pack

    def _spy(mandate=None, **kwargs):
        seen.append(getattr(mandate, "jurisdiction", "?"))
        return real(mandate, **kwargs)

    monkeypatch.setattr(base, "resolve_pack", _spy)
    assert base.resolve_pdf_jurisdiction(SimpleNamespace(jurisdiction=None)) == "CH"
    assert base.resolve_pdf_jurisdiction(SimpleNamespace(jurisdiction="DE")) == "DE"
    assert seen == [None, "DE"]
