"""H1 / N-853-8: JEDER Ares-PDF-Renderer bettet ausschliesslich eigene Fonts ein.

Rendert jeden Dokument-Renderer (alle ``ReportLabRenderer.render_*`` plus den
Beratungsbericht ``render_advisory_report_pdf_from_payload``) mit
realistischen Fixtures und wendet die Packaging-Smoke-Pruefung
``check_pdf_bytes`` an: jede vom Inhalt verwendete Font-Resource (Seite,
Form-XObjects, Annotationen, Patterns, Type3) muss einen eingebetteten
Font-Stream haben, Inter und Cormorant Garamond muessen verwendet sein.

Zusaetzlich (strenger als der Smoke): auch keine nur DEKLARIERTE, nicht
eingebettete Font-Resource -- ein Ares-PDF referenziert keinen Standard-14-
Font, auch nicht ungenutzt.

N-877-02: waehrend jedes Renders prueft ein Hook auf ``TTFont.splitString``,
dass jedes Zeichen im eingebetteten Font eine Glyphe hat (sonst .notdef-
Kasten). Gegenprobe vor N-877-01 rot fuer die Anlagestrategie (Emoji-Titel,
Baumstrich U+2517, Balken U+25B0/U+25B1).

Gegenprobe auf der Basis 2e5dfcc3 (vor H1): rot fuer Kostenausweis
(Seite 2 /F6 Courier), Anlagestrategie mit vollen Referenzdaten (Seite 11/12
/F1 Helvetica, Tabellenzellen ohne FONTNAME), Anlagestrategie mit
Zielerreichung (Seite 15 /F6 Times-Roman, Diagramm-String) und
Beratungsbericht (Courier fuer Hash/Kennziffern).
"""
from __future__ import annotations

import contextlib
import importlib.util
import inspect
import sys
from datetime import date
from pathlib import Path

import pytest

from services.pdf.base import (
    AnlagestrategieData,
    CostDisclosurePDFData,
    PDFContext,
    PortfolioData,
    ProtokollData,
    RisikoprofilData,
    VertragData,
)
from services.pdf.reportlab_renderer import ReportLabRenderer

REPO_ROOT = Path(__file__).resolve().parents[3]


def _load_smoke():
    name = "_ares_packaging_smoke_all_renderers"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / "scripts" / "packaging_smoke.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


smoke = _load_smoke()


def _ctx() -> PDFContext:
    return PDFContext(
        mandate_name="Hans Muster",
        advisor_name="Anna Berater",
        advisor_org="Muster & Partner AG",
        report_date=date(2026, 5, 17),
        audit_hash="abc123def456789012345678",
        locale="de-CH",
    )


def _strategy_reference() -> AnlagestrategieData:
    """Volle Referenzdaten (19 Seiten): Vermoegensuebersicht inkl. anderem
    Vermoegen, Produkte, Cashflows, Ziele, Zielerreichung mit Balken."""
    return AnlagestrategieData(
        target_allocation_bps={"equities": 7100, "real_estate": 2000, "alternatives": 700, "liquidity": 200},
        cma_expected_return_bps=431,
        cma_expected_vol_bps=1078,
        horizon_years=15,
        monte_carlo_stats={"p10": 400_000_00, "p50": 620_000_00, "p90": 910_000_00},
        optimizer_reasoning="Wachstumsorientierte Allokation, begrenzt durch das Risikoprofil.",
        risk_profile_label="Wachstum",
        mandate_number="M-42",
        advisory_wealth_rappen=535_100_00,
        risk_score_x10=80,
        investment_horizon_years=15,
        bucket_bands_bps={
            "equities": (6500, 7500), "real_estate": (1500, 2500),
            "alternatives": (0, 1000), "liquidity": (0, 500),
        },
        products=[{
            "name": "Aktien Welt Indexfonds", "isin": "IE000N6LBS91",
            "asset_class": "equities", "sub_asset_class": "Aktien Welt",
            "target_weight_bps": 3195, "target_amount_rappen": 170_964_00,
            "ter_bps": 12, "provider": "Fondsanbieter A",
        }],
        advisory_positions=[
            {"asset_class": "equities", "sub_asset_class": "Aktien", "current_amount_rappen": 103_500_00},
            {"asset_class": "bonds", "sub_asset_class": "Obligationen", "current_amount_rappen": 99_000_00},
        ],
        other_wealth_positions=[{"label": "Cash extern", "amount_rappen": 100_000_00, "kind": "Liquiditaet"}],
        cashflow_events=[{
            "name": "Freizuegigkeitsdepot", "recurrence": "Einmalig",
            "start_label": "03.2028", "amount_rappen": 169_000_00,
        }],
        goals_list=[{
            "name": "Vermoegensverzehr", "category": "Rente", "recurrence": "Monatlich",
            "period_label": "2026-2040", "amount_rappen": 5_025_00,
        }],
        goal_analysis=[{
            "rank": 1, "label": "Vermoegensverzehr", "achievement_score": 75,
            "target_text": "Rente sichern", "shortfall_rappen": 0,
        }],
        limiting_factor="risikoprofil",
        goal_achievability=[
            {"goal_id": "g-1", "label": "Pensionsentnahme 2035", "goal_type": "Pensionsausgabe",
             "probability": 0.92, "status": "erreichbar", "hardness": "hart"},
            {"goal_id": "g-2", "label": "Hauskauf 2032", "goal_type": "Vermoegensziel",
             "probability": 0.71, "status": "knapp", "hardness": "primaer"},
        ],
        current_allocation_bps={"equities": 3868, "bonds": 3700, "real_estate": 832, "liquidity": 1600},
        allocation_preferences={
            "policy": {"esg": "esg_integration", "universe": "standard", "homeBias": "ch_focus", "hedging": "hedged"},
            "assetClasses": {"equitiesGeo": "Schweiz Fokus", "bondsDuration": "Langfristig",
                             "realestateMarket": "Schweiz", "altsGold": True},
            "product": {"fundsOnly": True},
            "geo": {"chFocus": True},
            "bands": {},
        },
    )


def _risikoprofil() -> RisikoprofilData:
    return RisikoprofilData(
        risk_profile_label="Wachstumsorientiert",
        risk_capacity_score=65,
        risk_tolerance_score=58,
        risk_score_x10=58,
        mandate_number="M-RP",
        mandate_type="Anlageberatung",
        knowledge_services={"Anlageberatung": {"known": True, "informed": True}},
        knowledge_instruments={"Anlagefonds": {"known": True, "informed": True}},
        risk_answers=[
            {"question_number": 3, "question_section": "Risikofaehigkeit",
             "answer_label": "CHF 10'000 bis CHF 20'000", "answer_points": 3},
            {"question_number": 11, "question_section": "Risikobereitschaft",
             "answer_label": "Ich bleibe investiert und prüfe die Strategie im Gespräch.", "answer_points": 3},
        ],
        experience_years=8,
        suitability_note="Risikofähigkeit und Toleranz sind kompatibel.",
        is_overridden=True,
        override_reason="Kundenwunsch dokumentiert",
        override_client_confirmed=True,
        override_warning_delivered=True,
    )


def _portfolio() -> PortfolioData:
    return PortfolioData(
        mandate_number="M-42",
        advisory_wealth_rappen=100_000_00,
        positions=[
            {"name": "Aktien Welt Indexfonds", "isin": "CH0000000001", "asset_class": "equities",
             "sub_asset_class": "Aktien Welt", "target_weight_bps": 6000, "current_weight_bps": 5400,
             "drift_bps": -600, "target_amount_rappen": 60_000_00, "current_amount_rappen": 54_000_00,
             "currency": "CHF", "ter_bps": 20, "provider": "Fondsanbieter A"},
            {"name": "Obligationen CHF Fonds", "isin": "CH0000000002", "asset_class": "bonds",
             "sub_asset_class": "Obligationen CHF", "target_weight_bps": 4000, "current_weight_bps": 4600,
             "drift_bps": 600, "target_amount_rappen": 40_000_00, "current_amount_rappen": 46_000_00,
             "currency": "CHF", "ter_bps": 15, "provider": "Fondsanbieter B"},
        ],
    )


def _protokoll() -> ProtokollData:
    return ProtokollData(
        mandate_number="M-42",
        advisory_wealth_rappen=1_250_000_00,
        latest_recommendation_summary="Strategie wurde besprochen.",
        entries=[{
            "entry_date": "2026-05-19", "entry_type": "Review", "title": "Entscheid dokumentiert",
            "description": "Kunde stimmt der Umsetzung zu.", "decision": "Umsetzung", "status": "Empfohlen",
        }],
        conflict_messages=[{"severity": "conflict", "text": "Renditeziel und Risikoprofil widersprechen sich."}],
        selected_bausteine=[{"title": "Hinweis Kosten", "content_md": "Kosten wurden offengelegt.",
                             "category": "Kosten", "sort_order": 1, "custom_override_md": None}],
        risk_signoff_state="signed",
        risk_signoff_id="rps-1",
        risk_signoff_hash="f" * 64,
        risk_signoff_lines=(("Risikoprofil", "Wachstumsorientiert"),),
    )


def _cost_disclosure() -> CostDisclosurePDFData:
    from tests.test_cost_disclosure_pdf import _full_payload

    return CostDisclosurePDFData(mandate_number="M-1", advisory_wealth_rappen=1_000_000_00,
                                 payload=_full_payload())


def _contract_signoff():
    from tests.pdf.test_contract_signoff import _data

    return _data(overridden=True)


def _depotcheck():
    from tests.pdf.test_depotcheck_soll_analysis import _data

    return _data()


def _backtest():
    from tests.test_backtest_pdf import _sample_data

    return _sample_data(with_benchmark=True)


RENDERER_CASES = {
    "render_anlagestrategie": _strategy_reference,
    "render_asset_allocation": _strategy_reference,
    "render_risikoprofil": _risikoprofil,
    "render_portfolio": _portfolio,
    "render_vertrag": lambda: VertragData(praeambel="Präambel des Vertrags.", haftungsklausel="Haftung."),
    "render_contract_signoff": _contract_signoff,
    "render_protokoll": _protokoll,
    "render_depotcheck": _depotcheck,
    "render_cost_disclosure": _cost_disclosure,
    "render_backtest": _backtest,
}


def _advisory_payloads():
    from tests import test_advisory_report_pdf as advisory_tests

    return {
        "mc_paths": advisory_tests._make_payload_with_mc_paths,
        "stress_replay": advisory_tests._make_payload_with_stress_replay,
        "ab_backtest": advisory_tests._make_payload_with_ab_backtest,
    }


def _assert_only_own_fonts(pdf: bytes, label: str) -> None:
    import io

    import pypdf

    summary = smoke.check_pdf_bytes(pdf, label, ())
    assert "verwendete Font-Resource(n) eingebettet" in summary
    pages = list(pypdf.PdfReader(io.BytesIO(pdf)).pages)
    _, declared = smoke._font_resource_usage(pages)
    stray = sorted({d.describe() for d in declared if not d.embedded})
    assert not stray, f"{label}: nicht eingebettete Font-Resource deklariert: {stray[:5]}"


@contextlib.contextmanager
def _glyph_guard(label: str):
    """N-877-02: jede Glyphe, die ein eingebetteter TTF-Font darstellen soll,
    muss in dessen cmap stehen. ReportLab setzt fehlende Zeichen still auf
    .notdef (leerer Kasten); hier ist das fail-closed rot -- mit Renderer,
    Font, Zeichen und Codepoint. NBSP mappt ReportLab selbst auf Space."""
    from reportlab.pdfbase.ttfonts import TTFont

    missing: set[tuple[str, str, str]] = set()
    original = TTFont.splitString

    def split(self, text, doc, encoding="utf-8"):
        chars = text.decode("utf-8") if isinstance(text, bytes) else text
        cmap = self.face.charToGlyph
        for ch in chars:
            if ord(ch) != 0xA0 and ord(ch) not in cmap:
                missing.add((self.fontName, ch, f"U+{ord(ch):04X}"))
        return original(self, text, doc, encoding)

    TTFont.splitString = split
    try:
        yield
    finally:
        TTFont.splitString = original
    assert not missing, f"{label}: Zeichen ohne Glyphe im eingebetteten Font: {sorted(missing)}"


def test_every_document_renderer_is_covered():
    """Neue Renderer muessen hier mit Fixture aufgenommen werden."""
    renderers = {name for name, _ in inspect.getmembers(ReportLabRenderer, inspect.isfunction)
                 if name.startswith("render_")}
    assert renderers == set(RENDERER_CASES)


@pytest.mark.parametrize("method", sorted(RENDERER_CASES))
def test_renderer_embeds_only_own_fonts(method):
    with _glyph_guard(f"{method}.pdf"):
        pdf = getattr(ReportLabRenderer(), method)(_ctx(), RENDERER_CASES[method]())
    _assert_only_own_fonts(pdf, f"{method}.pdf")


@pytest.mark.parametrize("variant", ["mc_paths", "stress_replay", "ab_backtest"])
def test_advisory_report_embeds_only_own_fonts(variant):
    from services.pdf.documents.advisory_report import render_advisory_report_pdf_from_payload

    with _glyph_guard(f"beratungsbericht_{variant}.pdf"):
        pdf = render_advisory_report_pdf_from_payload(_advisory_payloads()[variant]())
    _assert_only_own_fonts(pdf, f"beratungsbericht_{variant}.pdf")


def test_glyph_guard_detects_missing_glyph():
    """Positivkontrolle: ein Zeichen ausserhalb der Inter-cmap ist rot."""
    import io

    from reportlab.pdfgen.canvas import Canvas

    from services.pdf.fonts import register_editorial_fonts

    assert register_editorial_fonts()
    with pytest.raises(AssertionError, match=r"x\.pdf: .*'Inter', '┗', 'U\+2517'"):
        with _glyph_guard("x.pdf"):
            canvas = Canvas(io.BytesIO())
            canvas.setFont("Inter", 9)
            canvas.drawString(10, 10, "Unterklasse ┗ Aktien")
            canvas.save()
