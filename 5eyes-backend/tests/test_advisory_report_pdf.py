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


import services.pdf.documents.advisory_report as advisory_pdf  # noqa: E402
from services.pdf.documents.advisory_report import (  # noqa: E402
    render_advisory_report_pdf_from_payload,
)
from services.pdf.components.goal_classification import classify_goals  # noqa: E402
from services.pdf.components.mc_paths_chart import build_mc_paths_drawing  # noqa: E402


def _make_minimal_payload() -> dict:
    """Liefert ein gültiges Aggregator-ähnliches Payload mit Minimal-Daten
    für Cover/Disclaimer/TOC/Ausgangslage/Positionen."""
    return {
        "schema_version": 2,
        "mandate_id": "test-mandate-id",
        "generated_at": "2026-05-27T14:32:00.000Z",
        "cover": {
            "title": "Strategische Portfolioanalyse",
            "subtitle": "Persoenlicher Advisory-Report",
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
        "asset_allocation": {
            "items": [
                {
                    "key": "equities", "label": "Aktien",
                    "ist_bps": 2500, "soll_bps": 3500, "drift_bps": -1000,
                    "band_min_bps": 3000, "band_max_bps": 4000, "in_band": False,
                },
                {
                    "key": "bonds", "label": "Obligationen",
                    "ist_bps": 6000, "soll_bps": 5000, "drift_bps": 1000,
                    "band_min_bps": 4000, "band_max_bps": 6000, "in_band": True,
                },
                {
                    "key": "liquidity", "label": "Liquidität",
                    "ist_bps": 250, "soll_bps": 250, "drift_bps": 0,
                    "band_min_bps": 0, "band_max_bps": 500, "in_band": True,
                },
            ],
            "ist_bps": {}, "soll_bps": {}, "drift_bps": {},
            "ist_basiert_auf_soll": True,
            "anmerkungen": "Aktien-Anteil unter dem Toleranzband — Rebalancing prüfen.",
        },
        "risikowaehrungen": {
            "items": [
                {"label": "CHF", "ist_bps": 5500, "soll_bps": 6000, "drift_bps": -500},
                {"label": "USD", "ist_bps": 3000, "soll_bps": 2500, "drift_bps": 500},
                {"label": "EUR", "ist_bps": 1500, "soll_bps": 1500, "drift_bps": 0},
            ],
            "ist_bps": {}, "soll_bps": {}, "drift_bps": {},
            "ist_basiert_auf_soll": False,
            "erklaerung": "CHF-Anteil leicht unter SOLL — kein Handlungsbedarf.",
        },
        "branchen": {
            "items": [
                {"label": "Tech", "ist_bps": 2500, "soll_bps": 2000, "drift_bps": 500},
                {"label": "Health", "ist_bps": 1500, "soll_bps": 1800, "drift_bps": -300},
                {"label": "Übrige", "ist_bps": 1000, "soll_bps": 1200, "drift_bps": -200},
            ],
            "ist_bps": {}, "soll_bps": {}, "drift_bps": {},
            "anteil_aktien_bps": 2500,
            "hinweis": "Basis für die Sektor-Drift sind die Aktien-Positionen.",
            "ist_basiert_auf_soll": False,
            "analyse": "Tech-Übergewicht — Konzentrationsrisiko prüfen.",
        },
        "goal_based_investing": {
            "goals": [
                {
                    "goal_id": "g1", "label": "Frühpension mit 60",
                    "goal_type": "Pension",
                    "target_amount_rappen": 1_500_000_00,
                    "target_date": "2042-09-18",
                    "hardness": "Primaer",
                    "probability_bps": 7800,
                    "status": "erreichbar",
                },
                {
                    "goal_id": "g2", "label": "Haus-Umbau",
                    "goal_type": "Liquidität",
                    "target_amount_rappen": 250_000_00,
                    "target_date": "2030-01-01",
                    "hardness": "Opportunistisch",
                    "probability_bps": 5500,
                    "status": "knapp",
                },
            ],
            "goal_achievement_score_bps": 7250,
            "monte_carlo_paths": {
                "data_pending": True,
                "note": "Pfade werden live berechnet.",
            },
        },
        "risikoprofilierung": {
            "risky_fraction_bps": 4250,
            "risk_capacity_score_x10": 68,
            "risk_willingness_score_x10": 55,
            "final_score_x10": 62,
            "final_profile": "Defensiv",
            "is_overridden": True,
            "override_reason": "Kunde wünscht defensiveres Profil als Score impliziert.",
            "questions": [
                {"key": "anlagehorizont", "frage": "Anlagehorizont", "points": 8},
                {"key": "sparquote", "frage": "Sparquote", "points": 6},
                {"key": "risikopraeferenz", "frage": "Risikopräferenz", "points": 5},
            ],
        },
        "building_blocks": {
            "blocks": [
                {
                    "key": "equities", "label": "Aktien",
                    "target_bps": 3500, "band_min_bps": 3000, "band_max_bps": 4000,
                },
                {
                    "key": "bonds", "label": "Obligationen",
                    "target_bps": 5000, "band_min_bps": 4000, "band_max_bps": 6000,
                },
                {
                    "key": "liquidity", "label": "Liquidität",
                    "target_bps": 250, "band_min_bps": 0, "band_max_bps": 500,
                },
            ],
            "constraints": [
                {
                    "key": "max_risky_fraction",
                    "label": "Maximale Risikoquote",
                    "value_bps": 4500,
                    "beschreibung": "FINMA-Eignungsprüfung Obergrenze.",
                },
            ],
            "methodologie": (
                "Institutionelle SAA-Logik mit Monte-Carlo-Überprüfung."
            ),
        },
        "statement_pm": {
            "principles": [
                {
                    "key": "langfristigkeit",
                    "title": "Langfristigkeit",
                    "body": "Strategische Allokation auf den Anlagehorizont.",
                },
                {
                    "key": "diversifikation",
                    "title": "Diversifikation",
                    "body": "Streuung reduziert idiosynkratisches Risiko.",
                },
                {
                    "key": "kosten",
                    "title": "Kosten-Disziplin",
                    "body": "Niedrige TER schlägt über Zeit hohe Performance.",
                },
            ],
        },
        "weiteres_vorgehen": {
            "block_optimierungen": "Quartals-Review im September.",
            "block_zielstrategie": "Vorsorge-Aufbau bis 65 mit Tilgung Hypothek.",
            "offene_fragen": ["Pillar 3a-Limit erreicht?", "BVG-Einkauf möglich?"],
            "naechster_termin": "2026-08-15",
            "todos": ["Vorsorgeauftrag aufsetzen", "Risikoabsicherung prüfen"],
            "dokumente": ["Identifikationspapier", "Ausweis Wohnsitz"],
        },
        # Sektion 17 — Suitability-Summary (Sprint U-FINMA-3)
        "suitability_summary": {
            "has_check": True,
            "check_id": "check-001",
            "performed_at": "2026-05-22T14:30:00.000Z",
            "duty_type": "suitability",
            "result": "passed",
            "result_notes": "Anlagestrategie ist mit Risikoprofil und Horizont vereinbar.",
            "missing_information": [],
            "client_proceeded_despite": False,
            "warning_delivered": False,
            "warning_delivered_at": None,
            "client_acknowledged": False,
            "client_acknowledged_at": None,
            "references": {
                "risk_assessment_id": "ra-001",
                "knowledge_assessment_id": None,
                "advisory_log_id": "log-1",
                "recommendation_run_id": None,
                "document_id": None,
            },
            "checked_by_id": "advisor-001",
            "checked_by_name": "Anna Beispiel",
            "linked_log_present": True,
        },
        # Sektion 16 — Beratungsprotokoll (Sprint U-FINMA-2.3)
        "beratungsprotokoll": {
            "total_active": 3,
            "last_review_date": "2026-05-15",
            "days_since_last_review": 13,
            "suitability_mismatches": [],
            "has_active_mismatches": False,
            "retention_audit_ok": True,
            "latest_entry": {
                "id": "log-1",
                "entry_type": "Jahresreview",
                "title": "Jahresreview Mai 2026",
                "description": "SAA überprüft, Risikoprofil aktualisiert, nächste Schritte vereinbart.",
                "decision": "Strategie angepasst",
                "status": "Beschlossen",
                "entry_datetime": "2026-05-15T14:00:00.000Z",
                "duration_minutes": 75,
                "communication_channel": "persoenlich",
                "language": "de",
                "location": "Büro Zürich",
                "participants": [{"role": "client", "name": "Daniel Beispiel"}],
                "topics": ["SAA", "Risikoprofil", "Pensionsplanung"],
                "risk_warnings_given": ["Marktrisiko", "Fremdwährungsrisiko"],
                "cost_disclosure_given": 1,
                "conflict_disclosure_ids": [],
                "suitability_check_id": None,
                "integrity_hash": "a" * 64,
                "retain_until": "2036-05-15",
                "version": 1,
                "supersedes_id": None,
                "superseded_by_id": None,
                "last_read_at": None,
                "last_read_by": None,
                "created_at": "2026-05-15T14:00:00.000Z",
                "updated_at": "2026-05-15T14:00:00.000Z",
            },
        },
        "stress_replay": {
            "data_pending": True,
            "note": "Stress-Replay aktuell nicht verfügbar.",
            "weights_bps": {},
            "scenarios": [],
        },
        "ab_backtest": {
            "data_pending": True,
            "note": "Keine zweite OptimizerPolicy für einen A/B-Vergleich vorhanden.",
            "policy_a": None,
            "policy_b": None,
            "buckets_diff": [],
            "risk_metrics_diff": {},
            "stress_diff": [],
            "warnings": [],
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


def _make_payload_with_stress_replay() -> dict:
    payload = _make_minimal_payload()
    payload["stress_replay"] = {
        "data_pending": False,
        "note": "Replay mit historischen jährlichen Returns pro Asset-Klasse.",
        "weights_bps": {
            "equities": 5500,
            "bonds": 2500,
            "real_estate": 1000,
            "alternatives": 500,
            "liquidity": 500,
        },
        "scenarios": [
            {
                "id": "dotcom_2000_2002",
                "label": "Dotcom 2000-2002",
                "period": "2000-2002",
                "cumulative_return_bps": -1830,
                "max_drawdown_bps": 2450,
                "recovery_months": 56,
                "annual_breakdown": [],
            },
            {
                "id": "gfc_2008",
                "label": "GFC 2008",
                "period": "2008",
                "cumulative_return_bps": -1380,
                "max_drawdown_bps": 3180,
                "recovery_months": 36,
                "annual_breakdown": [],
            },
            {
                "id": "covid_2020",
                "label": "Covid 2020",
                "period": "2020",
                "cumulative_return_bps": 890,
                "max_drawdown_bps": 940,
                "recovery_months": 5,
                "annual_breakdown": [],
            },
        ],
    }
    return payload


def _make_payload_with_mc_paths() -> dict:
    """Payload with aligned p5/p50/p75 paths for Section 11 tests."""
    payload = _make_minimal_payload()
    payload["goal_based_investing"]["goals"] = [
        {
            "goal_id": "g-reach",
            "label": "Retirement Goal",
            "goal_type": "Vermoegen",
            "target_amount_rappen": 210_000_000,
            "target_date": "2030-01-01",
            "hardness": "primaer",
            "probability_bps": None,
            "status": "data_pending",
        },
        {
            "goal_id": "g-tight",
            "label": "Renovation Goal",
            "goal_type": "Ausgabe",
            "target_amount_rappen": 180_000_000,
            "target_date": "2028-01-01",
            "hardness": "opportunistisch",
            "probability_bps": None,
            "status": "data_pending",
        },
        {
            "goal_id": "g-hard",
            "label": "Safety Goal",
            "goal_type": "Vermoegen",
            "target_amount_rappen": 200_000_000,
            "target_date": "2027-01-01",
            "hardness": "hart",
            "probability_bps": None,
            "status": "data_pending",
        },
        {
            "goal_id": "g-later",
            "label": "Later Goal",
            "goal_type": "Vermoegen",
            "target_amount_rappen": 220_000_000,
            "target_date": "2035-01-01",
            "hardness": "primaer",
            "probability_bps": None,
            "status": "data_pending",
        },
    ]
    payload["goal_based_investing"]["monte_carlo_paths"] = {
        "data_pending": False,
        "p5": [100_000_000, 105_000_000, 110_000_000, 115_000_000, 120_000_000],
        "p50": [100_000_000, 130_000_000, 160_000_000, 190_000_000, 220_000_000],
        "p75": [100_000_000, 150_000_000, 200_000_000, 250_000_000, 300_000_000],
        "time_axis": ["2026", "2027", "2028", "2029", "2030"],
        "n_paths": 1000,
        "seed": 282668599573,
        "horizon_years": 4,
        "initial_wealth_rappen": 100_000_000,
        "note": "",
    }
    return payload


def _make_payload_with_ab_backtest() -> dict:
    payload = _make_minimal_payload()
    payload["ab_backtest"] = {
        "data_pending": False,
        "note": "Reiner House-Matrix-Pfad ohne Tilts, Goals und Reserve-Logik.",
        "score_bucket": 7,
        "cma_id": "cma-2026-q1",
        "cma_version": 3,
        "policy_a": {
            "policy_id": "policy-a",
            "policy_name": "Policy 2025",
            "version": 1,
            "is_current": False,
            "profile_name": "Wachstumsorientiert",
            "max_risky_fraction_bps": 7000,
            "weights_bps": {"equities": 6500, "bonds": 2500, "liquidity": 1000},
            "expected_return_bps": 420,
            "expected_volatility_bps": 1180,
            "expected_ter_bps": 42,
            "sharpe_ratio_x100": 31,
        },
        "policy_b": {
            "policy_id": "policy-b",
            "policy_name": "Policy 2026",
            "version": 2,
            "is_current": True,
            "profile_name": "Wachstumsorientiert",
            "max_risky_fraction_bps": 6800,
            "weights_bps": {"equities": 6000, "bonds": 3000, "liquidity": 1000},
            "expected_return_bps": 395,
            "expected_volatility_bps": 1090,
            "expected_ter_bps": 38,
            "sharpe_ratio_x100": 33,
        },
        "buckets_diff": [
            {"key": "liquidity", "label": "Liquidität", "a_bps": 1000, "b_bps": 1000, "delta_bps": 0},
            {"key": "bonds", "label": "Obligationen", "a_bps": 2500, "b_bps": 3000, "delta_bps": 500},
            {"key": "equities", "label": "Aktien", "a_bps": 6500, "b_bps": 6000, "delta_bps": -500},
            {"key": "real_estate", "label": "Immobilien", "a_bps": 0, "b_bps": 0, "delta_bps": 0},
            {"key": "alternatives", "label": "Alternative Anlagen", "a_bps": 0, "b_bps": 0, "delta_bps": 0},
        ],
        "risk_metrics_diff": {
            "delta_expected_return_bps": -25,
            "delta_expected_volatility_bps": -90,
            "delta_expected_ter_bps": -4,
            "delta_sharpe_ratio_x100": 2,
        },
        "stress_diff": [
            {
                "id": "dotcom_2000_2002",
                "label": "Dotcom 2000-2002",
                "period": "2000-2002",
                "a_cumulative_return_bps": -2100,
                "b_cumulative_return_bps": -1900,
                "delta_cumulative_return_bps": 200,
                "a_max_drawdown_bps": 3200,
                "b_max_drawdown_bps": 2800,
                "delta_max_drawdown_bps": -400,
                "a_recovery_months": 60,
                "b_recovery_months": 54,
            },
            {
                "id": "gfc_2008",
                "label": "GFC 2008",
                "period": "2008",
                "a_cumulative_return_bps": -1800,
                "b_cumulative_return_bps": -1600,
                "delta_cumulative_return_bps": 200,
                "a_max_drawdown_bps": 2900,
                "b_max_drawdown_bps": 2600,
                "delta_max_drawdown_bps": -300,
                "a_recovery_months": 42,
                "b_recovery_months": 38,
            },
        ],
        "warnings": [],
    }
    return payload


def _drawing_texts(drawing) -> list[str]:
    return [
        str(getattr(node, "text"))
        for node in getattr(drawing, "contents", [])
        if getattr(node, "text", None)
    ]


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


# ---------------------------------------------------------------------------
# Sektion 8 — Asset Allocation Bar-Chart (U-P26 PR D)
# ---------------------------------------------------------------------------

def test_asset_allocation_shows_section_header_and_labels():
    pypdf = pytest.importorskip("pypdf")
    payload = _make_minimal_payload()
    pdf = render_advisory_report_pdf_from_payload(payload)
    reader = pypdf.PdfReader(__import__("io").BytesIO(pdf))
    # Sektion 8 = Seite 8 (0-indexed: 7)
    assert len(reader.pages) >= 8
    page_text = reader.pages[7].extract_text() or ""
    assert "Asset Allocation" in page_text
    assert "Aktien" in page_text
    assert "Obligationen" in page_text
    assert "Liquidität" in page_text


def test_asset_allocation_shows_ist_and_soll_percentages():
    pypdf = pytest.importorskip("pypdf")
    payload = _make_minimal_payload()
    pdf = render_advisory_report_pdf_from_payload(payload)
    reader = pypdf.PdfReader(__import__("io").BytesIO(pdf))
    page_text = reader.pages[7].extract_text() or ""
    normalized = "".join(page_text.split())
    # Aktien IST 25.0 % / SOLL 35.0 %
    assert "25.0%" in normalized
    assert "35.0%" in normalized
    # Drift −10.0 %
    assert "-10.0%" in normalized or "−10.0%" in normalized


def test_asset_allocation_shows_data_basis_banner_when_ist_basiert_auf_soll():
    pypdf = pytest.importorskip("pypdf")
    payload = _make_minimal_payload()
    pdf = render_advisory_report_pdf_from_payload(payload)
    reader = pypdf.PdfReader(__import__("io").BytesIO(pdf))
    page_text = reader.pages[7].extract_text() or ""
    assert "Datenstand" in page_text


def test_asset_allocation_shows_editorial_anmerkungen():
    pypdf = pytest.importorskip("pypdf")
    payload = _make_minimal_payload()
    pdf = render_advisory_report_pdf_from_payload(payload)
    reader = pypdf.PdfReader(__import__("io").BytesIO(pdf))
    page_text = reader.pages[7].extract_text() or ""
    assert "Aktien-Anteil unter dem Toleranzband" in page_text


def test_asset_allocation_handles_empty_items():
    payload = _make_minimal_payload()
    payload["asset_allocation"] = {
        "items": [], "ist_bps": {}, "soll_bps": {}, "drift_bps": {},
        "ist_basiert_auf_soll": False, "anmerkungen": "",
    }
    pdf = render_advisory_report_pdf_from_payload(payload)
    assert pdf[:5] == b"%PDF-"


# ---------------------------------------------------------------------------
# Sektion 9 — Risikowährungen (U-P26 PR D)
# ---------------------------------------------------------------------------

def test_risikowaehrungen_shows_currency_labels():
    pypdf = pytest.importorskip("pypdf")
    payload = _make_minimal_payload()
    pdf = render_advisory_report_pdf_from_payload(payload)
    reader = pypdf.PdfReader(__import__("io").BytesIO(pdf))
    # Sektion 9 = Seite 9 (0-indexed: 8)
    assert len(reader.pages) >= 9
    page_text = reader.pages[8].extract_text() or ""
    assert "Risikowährungen" in page_text
    assert "CHF" in page_text
    assert "USD" in page_text
    assert "EUR" in page_text
    assert "CHF-Anteil leicht unter SOLL" in page_text


def test_risikowaehrungen_no_data_basis_banner_when_ist_is_real():
    """ist_basiert_auf_soll=False → kein Datenstand-Banner."""
    pypdf = pytest.importorskip("pypdf")
    payload = _make_minimal_payload()
    pdf = render_advisory_report_pdf_from_payload(payload)
    reader = pypdf.PdfReader(__import__("io").BytesIO(pdf))
    page_text = reader.pages[8].extract_text() or ""
    # Banner-Text darf hier nicht auftauchen
    assert "IST basiert aktuell auf SOLL" not in page_text


# ---------------------------------------------------------------------------
# Sektion 10 — Branchen (U-P26 PR D)
# ---------------------------------------------------------------------------

def test_branchen_shows_sector_items_and_analyse():
    pypdf = pytest.importorskip("pypdf")
    payload = _make_minimal_payload()
    pdf = render_advisory_report_pdf_from_payload(payload)
    reader = pypdf.PdfReader(__import__("io").BytesIO(pdf))
    assert len(reader.pages) >= 10
    page_text = reader.pages[9].extract_text() or ""
    assert "Diversifikation Branchen" in page_text
    assert "Tech" in page_text
    assert "Health" in page_text
    assert "Übrige" in page_text
    assert "Tech-Übergewicht" in page_text


def test_branchen_shows_hinweis_about_data_basis():
    pypdf = pytest.importorskip("pypdf")
    payload = _make_minimal_payload()
    pdf = render_advisory_report_pdf_from_payload(payload)
    reader = pypdf.PdfReader(__import__("io").BytesIO(pdf))
    page_text = reader.pages[9].extract_text() or ""
    assert "Sektor-Drift" in page_text


# ---------------------------------------------------------------------------
# Branding-Disziplin: KEINE Dritt-Marken im erweiterten PDF
# ---------------------------------------------------------------------------

def test_pr_d_layout_contains_no_third_party_brands():
    pypdf = pytest.importorskip("pypdf")
    payload = _make_minimal_payload()
    pdf = render_advisory_report_pdf_from_payload(payload)
    reader = pypdf.PdfReader(__import__("io").BytesIO(pdf))
    all_text = "\n".join((p.extract_text() or "") for p in reader.pages).lower()
    for term in ["swiss life", "3eyes"]:
        assert term not in all_text, f"Verbotene Marke '{term}' im PR-D PDF"


# ---------------------------------------------------------------------------
# Sektion 11 — Goal-Based Investing (U-P26 PR E)
# ---------------------------------------------------------------------------

def test_goals_section_shows_achievement_score_and_goals():
    pypdf = pytest.importorskip("pypdf")
    payload = _make_minimal_payload()
    pdf = render_advisory_report_pdf_from_payload(payload)
    reader = pypdf.PdfReader(__import__("io").BytesIO(pdf))
    # Sektion 11 = Seite 11 (0-indexed: 10)
    assert len(reader.pages) >= 11
    page_text = reader.pages[10].extract_text() or ""
    assert "Zielbasierte Optimierung" in page_text
    assert "Frühpension mit 60" in page_text
    assert "Haus-Umbau" in page_text
    # Achievement-Score 7250 bps → 72 % oder 73 % (banker's-rounding)
    normalized = "".join(page_text.split())
    assert "72%" in normalized or "73%" in normalized, (
        f"Achievement-Score-KPI fehlt. Normalized: {normalized[:400]}"
    )


def test_goals_section_shows_status_pills():
    pypdf = pytest.importorskip("pypdf")
    payload = _make_minimal_payload()
    pdf = render_advisory_report_pdf_from_payload(payload)
    reader = pypdf.PdfReader(__import__("io").BytesIO(pdf))
    normalized = "".join((reader.pages[10].extract_text() or "").split())
    # Pills für die Stati
    assert "Erreichbar" in normalized
    assert "Knapp" in normalized


def test_goals_section_renders_mc_pending_hint():
    pypdf = pytest.importorskip("pypdf")
    payload = _make_minimal_payload()
    pdf = render_advisory_report_pdf_from_payload(payload)
    reader = pypdf.PdfReader(__import__("io").BytesIO(pdf))
    page_text = reader.pages[10].extract_text() or ""
    assert "Monte-Carlo" in page_text


def test_goals_pdf_builds_mc_paths_chart_when_paths_are_aligned():
    payload = _make_payload_with_mc_paths()
    drawing = build_mc_paths_drawing(
        payload["goal_based_investing"]["monte_carlo_paths"],
        payload["goal_based_investing"]["goals"],
    )
    assert drawing is not None
    assert drawing.width > 0
    assert drawing.height > 0
    assert "Retirement Goal" in _drawing_texts(drawing)

    pdf_with_chart = render_advisory_report_pdf_from_payload(payload)
    without_paths = _make_payload_with_mc_paths()
    without_paths["goal_based_investing"]["monte_carlo_paths"] = {
        "data_pending": True,
        "note": "Pfade werden live berechnet.",
    }
    pdf_without_chart = render_advisory_report_pdf_from_payload(without_paths)
    assert pdf_with_chart != pdf_without_chart


def test_goals_pdf_data_pending_keeps_hint_and_omits_chart():
    payload = _make_minimal_payload()
    drawing = build_mc_paths_drawing(
        payload["goal_based_investing"]["monte_carlo_paths"],
        payload["goal_based_investing"]["goals"],
    )
    assert drawing is None

    pdf = render_advisory_report_pdf_from_payload(payload)
    pypdf = pytest.importorskip("pypdf")
    reader = pypdf.PdfReader(__import__("io").BytesIO(pdf))
    page_text = reader.pages[10].extract_text() or ""
    assert "Monte-Carlo" in page_text
    assert "Pfade werden live berechnet" in page_text


def test_goals_pdf_mc_status_pills_follow_frontend_boundaries():
    payload = _make_payload_with_mc_paths()
    classifications = classify_goals(
        payload["goal_based_investing"]["goals"],
        payload["goal_based_investing"]["monte_carlo_paths"],
    )
    by_id = {c["goal_id"]: c["status"] for c in classifications}
    assert by_id["g-reach"] == "erreichbar"
    assert by_id["g-tight"] == "knapp"
    assert by_id["g-hard"] == "nicht_erreichbar"

    pdf = render_advisory_report_pdf_from_payload(payload)
    pypdf = pytest.importorskip("pypdf")
    reader = pypdf.PdfReader(__import__("io").BytesIO(pdf))
    normalized = "".join((reader.pages[10].extract_text() or "").split())
    assert "MC-Status" in normalized
    assert "Erreichbar" in normalized
    assert "Knapp" in normalized
    assert "Schwierig" in normalized


def test_goals_pdf_beyond_horizon_status_is_visible_in_mc_status_column():
    payload = _make_payload_with_mc_paths()
    classifications = classify_goals(
        payload["goal_based_investing"]["goals"],
        payload["goal_based_investing"]["monte_carlo_paths"],
    )
    by_id = {c["goal_id"]: c["status"] for c in classifications}
    assert by_id["g-later"] == "beyond_horizon"

    pdf = render_advisory_report_pdf_from_payload(payload)
    pypdf = pytest.importorskip("pypdf")
    reader = pypdf.PdfReader(__import__("io").BytesIO(pdf))
    normalized = "".join((reader.pages[10].extract_text() or "").split())
    assert "JenseitsHorizont" in normalized


def test_goals_pdf_misaligned_mc_paths_do_not_crash_or_render_chart():
    payload = _make_payload_with_mc_paths()
    payload["goal_based_investing"]["monte_carlo_paths"]["p75"] = [100_000_000]
    drawing = build_mc_paths_drawing(
        payload["goal_based_investing"]["monte_carlo_paths"],
        payload["goal_based_investing"]["goals"],
    )
    assert drawing is None

    pdf = render_advisory_report_pdf_from_payload(payload)
    assert pdf[:5] == b"%PDF-"


def test_goals_pdf_score_kpi_stays_unchanged_with_mc_chart():
    pypdf = pytest.importorskip("pypdf")
    payload = _make_payload_with_mc_paths()
    pdf = render_advisory_report_pdf_from_payload(payload)
    reader = pypdf.PdfReader(__import__("io").BytesIO(pdf))
    normalized = "".join((reader.pages[10].extract_text() or "").split())
    assert "72%" in normalized or "73%" in normalized, (
        f"Achievement-Score-KPI fehlt. Normalized: {normalized[:400]}"
    )


# ---------------------------------------------------------------------------
# Sektion 12 — Risikoprofilierung (U-P26 PR E)
# ---------------------------------------------------------------------------

def test_risikoprofil_section_shows_profile_score_and_questions():
    pypdf = pytest.importorskip("pypdf")
    payload = _make_minimal_payload()
    pdf = render_advisory_report_pdf_from_payload(payload)
    reader = pypdf.PdfReader(__import__("io").BytesIO(pdf))
    assert len(reader.pages) >= 12
    page_text = reader.pages[11].extract_text() or ""
    assert "Risikoprofilierung" in page_text
    assert "Defensiv" in page_text
    assert "62" in page_text  # final_score
    assert "42.5 %" in page_text  # risky_fraction
    # Fragen erscheinen
    assert "Anlagehorizont" in page_text
    assert "Risikopräferenz" in page_text


def test_risikoprofil_section_shows_override_when_active():
    pypdf = pytest.importorskip("pypdf")
    payload = _make_minimal_payload()
    pdf = render_advisory_report_pdf_from_payload(payload)
    reader = pypdf.PdfReader(__import__("io").BytesIO(pdf))
    page_text = reader.pages[11].extract_text() or ""
    assert "Manuelle Übersteuerung" in page_text
    assert "defensiveres Profil" in page_text


def test_risikoprofil_section_omits_override_when_inactive():
    payload = _make_minimal_payload()
    payload["risikoprofilierung"]["is_overridden"] = False
    payload["risikoprofilierung"]["override_reason"] = None
    pdf = render_advisory_report_pdf_from_payload(payload)
    pypdf = pytest.importorskip("pypdf")
    reader = pypdf.PdfReader(__import__("io").BytesIO(pdf))
    page_text = reader.pages[11].extract_text() or ""
    assert "Manuelle Übersteuerung" not in page_text


# ---------------------------------------------------------------------------
# Sektion 13 — Building Blocks (U-P26 PR E)
# ---------------------------------------------------------------------------

def test_building_blocks_section_shows_blocks_and_bands():
    pypdf = pytest.importorskip("pypdf")
    payload = _make_minimal_payload()
    pdf = render_advisory_report_pdf_from_payload(payload)
    reader = pypdf.PdfReader(__import__("io").BytesIO(pdf))
    assert len(reader.pages) >= 13
    page_text = reader.pages[12].extract_text() or ""
    assert "Building Blocks" in page_text
    assert "Aktien" in page_text
    assert "Obligationen" in page_text
    # Target 3500 bps → 35.0 %
    assert "35.0 %" in page_text
    # Band: 30.0 – 40.0 %
    assert "30.0" in page_text


def test_building_blocks_section_shows_constraints_and_methodologie():
    pypdf = pytest.importorskip("pypdf")
    payload = _make_minimal_payload()
    pdf = render_advisory_report_pdf_from_payload(payload)
    reader = pypdf.PdfReader(__import__("io").BytesIO(pdf))
    page_text = reader.pages[12].extract_text() or ""
    assert "Maximale Risikoquote" in page_text
    assert "FINMA" in page_text
    assert "Institutionelle SAA-Logik" in page_text


# ---------------------------------------------------------------------------
# Sektion 14 — Statement aus dem Portfoliomanagement (U-P26 PR F)
# ---------------------------------------------------------------------------

def test_statement_pm_section_shows_principles():
    pypdf = pytest.importorskip("pypdf")
    payload = _make_minimal_payload()
    pdf = render_advisory_report_pdf_from_payload(payload)
    reader = pypdf.PdfReader(__import__("io").BytesIO(pdf))
    # Sektion 14 = Seite 14 (0-indexed: 13)
    assert len(reader.pages) >= 14
    page_text = reader.pages[13].extract_text() or ""
    assert "Statement aus dem Portfoliomanagement" in page_text
    assert "Langfristigkeit" in page_text
    assert "Diversifikation" in page_text
    assert "Kosten-Disziplin" in page_text


def test_statement_pm_section_handles_empty_principles():
    payload = _make_minimal_payload()
    payload["statement_pm"] = {"principles": []}
    pdf = render_advisory_report_pdf_from_payload(payload)
    assert pdf[:5] == b"%PDF-"
    pypdf = pytest.importorskip("pypdf")
    reader = pypdf.PdfReader(__import__("io").BytesIO(pdf))
    page_text = reader.pages[13].extract_text() or ""
    assert "Keine Investmentgrundsätze" in page_text


# ---------------------------------------------------------------------------
# Sektion 15 — Weiteres Vorgehen (U-P26 PR F)
# ---------------------------------------------------------------------------

def test_weiteres_vorgehen_section_shows_blocks_lists_termin():
    pypdf = pytest.importorskip("pypdf")
    payload = _make_minimal_payload()
    pdf = render_advisory_report_pdf_from_payload(payload)
    reader = pypdf.PdfReader(__import__("io").BytesIO(pdf))
    assert len(reader.pages) >= 15
    page_text = reader.pages[14].extract_text() or ""
    assert "Weiteres Vorgehen" in page_text
    assert "Quartals-Review im September" in page_text
    assert "Vorsorge-Aufbau bis 65" in page_text
    assert "Pillar 3a-Limit" in page_text
    assert "Vorsorgeauftrag" in page_text
    assert "Identifikationspapier" in page_text
    assert "2026-08-15" in page_text


def test_weiteres_vorgehen_section_renders_placeholders_when_unedited():
    """Auto-Default-Text (von Aggregator wenn keine Notes gepflegt sind)
    soll gedimmt-kursiv erscheinen, nicht regulär."""
    payload = _make_minimal_payload()
    payload["weiteres_vorgehen"] = {
        "block_optimierungen": "(Vom Berater zu ergänzen — wird beim Druck konkretisiert.)",
        "block_zielstrategie": "(Vom Berater zu ergänzen — wird beim Druck konkretisiert.)",
        "offene_fragen": [],
        "naechster_termin": None,
        "todos": [],
        "dokumente": [],
    }
    pdf = render_advisory_report_pdf_from_payload(payload)
    pypdf = pytest.importorskip("pypdf")
    reader = pypdf.PdfReader(__import__("io").BytesIO(pdf))
    page_text = reader.pages[14].extract_text() or ""
    assert "Vom Berater zu ergänzen" in page_text
    assert "Noch nicht vereinbart" in page_text
    assert "Keine Einträge" in page_text


# ---------------------------------------------------------------------------
# Polish — Single-Pass-Build für echte Seitenzahlen im Page-Chrome
# ---------------------------------------------------------------------------

def test_page_chrome_shows_total_pages_after_single_pass_build():
    """Page-Header soll „Seite x / N" enthalten — nicht nur „Seite x"."""
    pypdf = pytest.importorskip("pypdf")
    payload = _make_minimal_payload()
    pdf = render_advisory_report_pdf_from_payload(payload)
    reader = pypdf.PdfReader(__import__("io").BytesIO(pdf))
    # Seite 2 (Disclaimer) hat schon Chrome — sollte „Seite 2 / 15" o.ä. zeigen
    page2 = reader.pages[1].extract_text() or ""
    assert "Seite 2" in page2
    assert "/" in page2, f"Total-Pages-Indicator fehlt. Page2 text: {page2[:300]}"


def test_two_pass_render_builds_story_twice():
    """U-13 (2026-06-02): Two-Pass-Render fuer echte Seitenzahlen.
    Pass 1 zaehlt + sammelt TOC-Anker, Pass 2 zeichnet mit echten Seiten.
    Beide Passes rufen _build_all_flowables auf."""
    import services.pdf.documents.advisory_report as advisory_pdf
    payload = _make_minimal_payload()
    original = advisory_pdf._build_all_flowables
    calls = 0

    def wrapped(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    import unittest.mock as mock
    with mock.patch.object(advisory_pdf, "_build_all_flowables", wrapped):
        pdf = advisory_pdf.render_advisory_report_pdf_from_payload(payload)

    assert pdf[:5] == b"%PDF-"
    assert calls == 2


def test_full_pdf_has_at_least_15_sections():
    pypdf = pytest.importorskip("pypdf")
    payload = _make_minimal_payload()
    pdf = render_advisory_report_pdf_from_payload(payload)
    reader = pypdf.PdfReader(__import__("io").BytesIO(pdf))
    # A/B-Backtest + Suitability + Compliance + Signatur -> >= 20 Seiten
    assert len(reader.pages) >= 20, (
        f"Erwartet mindestens 20 Seiten (alle Sektionen inkl. AB-Backtest + Eignung + Compliance + Signatur), "
        f"PDF hat {len(reader.pages)}"
    )


# ---------------------------------------------------------------------------
# Sektion 16 — Beratungsprotokoll (Sprint U-FINMA-2.3)
# ---------------------------------------------------------------------------

def test_beratungsprotokoll_section_shows_header_and_summary():
    pypdf = pytest.importorskip("pypdf")
    payload = _make_minimal_payload()
    pdf = render_advisory_report_pdf_from_payload(payload)
    reader = pypdf.PdfReader(__import__("io").BytesIO(pdf))
    # Sektion 16 = Seite 16 (0-indexed: 15)
    assert len(reader.pages) >= 16
    text = reader.pages[15].extract_text() or ""
    assert "Beratungsprotokoll" in text
    # pypdf-extract korrumpiert Umlaute -> wir matchen den Substring vor dem Umlaut
    assert "AKTIVE EINTR" in text.upper()
    assert "3" in text  # total_active
    assert "2026-05-15" in text  # last_review_date


def test_beratungsprotokoll_shows_latest_entry_details():
    pypdf = pytest.importorskip("pypdf")
    payload = _make_minimal_payload()
    pdf = render_advisory_report_pdf_from_payload(payload)
    reader = pypdf.PdfReader(__import__("io").BytesIO(pdf))
    text = reader.pages[15].extract_text() or ""
    assert "Jahresreview Mai 2026" in text
    assert "Beschlossen" in text  # Status-Pill
    assert "75 min" in text  # Dauer
    # Topics
    assert "SAA" in text
    assert "Risikoprofil" in text


def test_beratungsprotokoll_shows_integrity_marker():
    pypdf = pytest.importorskip("pypdf")
    payload = _make_minimal_payload()
    pdf = render_advisory_report_pdf_from_payload(payload)
    reader = pypdf.PdfReader(__import__("io").BytesIO(pdf))
    text = reader.pages[15].extract_text() or ""
    assert "verifiziert" in text.lower()


def test_beratungsprotokoll_shows_mismatch_banner_when_active():
    pypdf = pytest.importorskip("pypdf")
    payload = _make_minimal_payload()
    payload["beratungsprotokoll"] = {
        **payload["beratungsprotokoll"],
        "has_active_mismatches": True,
        "suitability_mismatches": [
            "Risiko-Anteil 47.0 % überschreitet Cap 45.0 % (Defensiv).",
        ],
    }
    pdf = render_advisory_report_pdf_from_payload(payload)
    reader = pypdf.PdfReader(__import__("io").BytesIO(pdf))
    text = reader.pages[15].extract_text() or ""
    assert "Suitability-Hinweise" in text
    assert "47.0" in text


def test_beratungsprotokoll_shows_retention_warning():
    pypdf = pytest.importorskip("pypdf")
    payload = _make_minimal_payload()
    payload["beratungsprotokoll"] = {
        **payload["beratungsprotokoll"],
        "retention_audit_ok": False,
    }
    pdf = render_advisory_report_pdf_from_payload(payload)
    reader = pypdf.PdfReader(__import__("io").BytesIO(pdf))
    text = reader.pages[15].extract_text() or ""
    assert "Aufbewahrungs" in text


def test_beratungsprotokoll_shows_no_entry_hint_when_empty():
    pypdf = pytest.importorskip("pypdf")
    payload = _make_minimal_payload()
    payload["beratungsprotokoll"] = {
        "total_active": 0,
        "latest_entry": None,
        "last_review_date": None,
        "days_since_last_review": None,
        "suitability_mismatches": [],
        "has_active_mismatches": False,
        "retention_audit_ok": True,
    }
    pdf = render_advisory_report_pdf_from_payload(payload)
    reader = pypdf.PdfReader(__import__("io").BytesIO(pdf))
    text = reader.pages[15].extract_text() or ""
    assert "Noch kein Beratungsprotokoll" in text


# ---------------------------------------------------------------------------
# Sektion 17 — Historische Stress-Szenarien (Sprint U-70)
# ---------------------------------------------------------------------------

def test_stress_replay_section_renders_pending_hint():
    pypdf = pytest.importorskip("pypdf")
    payload = _make_minimal_payload()
    pdf = render_advisory_report_pdf_from_payload(payload)
    reader = pypdf.PdfReader(__import__("io").BytesIO(pdf))
    text = "\n".join((page.extract_text() or "") for page in reader.pages)
    assert "Historische Stress-Szenarien" in text
    assert "Stress-Replay aktuell nicht" in text


def test_stress_replay_section_renders_scenario_table():
    pypdf = pytest.importorskip("pypdf")
    payload = _make_payload_with_stress_replay()
    pdf = render_advisory_report_pdf_from_payload(payload)
    reader = pypdf.PdfReader(__import__("io").BytesIO(pdf))
    text = "\n".join((page.extract_text() or "") for page in reader.pages)
    assert "Historische Stress-Szenarien" in text
    assert "Dotcom 2000-2002" in text
    assert "GFC 2008" in text
    assert "Covid 2020" in text


def test_stress_replay_section_shows_return_drawdown_and_recovery_values():
    pypdf = pytest.importorskip("pypdf")
    payload = _make_payload_with_stress_replay()
    pdf = render_advisory_report_pdf_from_payload(payload)
    reader = pypdf.PdfReader(__import__("io").BytesIO(pdf))
    text = "\n".join((page.extract_text() or "") for page in reader.pages).replace(" ", "")
    assert "-18.3%" in text
    assert "-31.8%" in text
    assert "+8.9%" in text
    assert "56Mt." in text


def test_stress_replay_empty_scenarios_do_not_crash():
    pypdf = pytest.importorskip("pypdf")
    payload = _make_minimal_payload()
    payload["stress_replay"] = {
        "data_pending": False,
        "note": "Noch keine Stress-Szenarien verfügbar.",
        "weights_bps": {},
        "scenarios": [],
    }
    pdf = render_advisory_report_pdf_from_payload(payload)
    reader = pypdf.PdfReader(__import__("io").BytesIO(pdf))
    text = "\n".join((page.extract_text() or "") for page in reader.pages)
    assert "Historische Stress-Szenarien" in text
    assert "Noch keine Stress-Szenarien" in text


# ---------------------------------------------------------------------------
# Sektion 18 — Policy-A/B-Vergleich (Sprint U-71)
# ---------------------------------------------------------------------------

def test_ab_backtest_section_renders_pending_hint():
    pypdf = pytest.importorskip("pypdf")
    payload = _make_minimal_payload()
    pdf = render_advisory_report_pdf_from_payload(payload)
    reader = pypdf.PdfReader(__import__("io").BytesIO(pdf))
    text = "\n".join((page.extract_text() or "") for page in reader.pages)
    assert "Policy-A/B-Vergleich" in text
    assert "Keine zweite OptimizerPolicy" in text


def test_ab_backtest_section_renders_policy_metric_table():
    pypdf = pytest.importorskip("pypdf")
    payload = _make_payload_with_ab_backtest()
    pdf = render_advisory_report_pdf_from_payload(payload)
    reader = pypdf.PdfReader(__import__("io").BytesIO(pdf))
    text = "\n".join((page.extract_text() or "") for page in reader.pages)
    assert "Policy-A/B-Vergleich" in text
    assert "Policy 2025" in text
    assert "Policy 2026" in text
    assert "Erwartete Rendite" in text
    assert "Sharpe" in text


def test_ab_backtest_section_shows_bucket_deltas():
    pypdf = pytest.importorskip("pypdf")
    payload = _make_payload_with_ab_backtest()
    pdf = render_advisory_report_pdf_from_payload(payload)
    reader = pypdf.PdfReader(__import__("io").BytesIO(pdf))
    text = "\n".join((page.extract_text() or "") for page in reader.pages).replace(" ", "")
    assert "Aktien" in text
    assert "-5.0%" in text
    assert "+5.0%" in text


def test_ab_backtest_section_shows_stress_diff():
    pypdf = pytest.importorskip("pypdf")
    payload = _make_payload_with_ab_backtest()
    pdf = render_advisory_report_pdf_from_payload(payload)
    reader = pypdf.PdfReader(__import__("io").BytesIO(pdf))
    text = "\n".join((page.extract_text() or "") for page in reader.pages)
    assert "Stress-Replay-Differenz" in text
    assert "Dotcom 2000-2002" in text
    assert "GFC 2008" in text


# ---------------------------------------------------------------------------
# Sektion 27 — Suitability-Summary (Sprint U-FINMA-3, re-architektiert 2026-06-09)
# ---------------------------------------------------------------------------

def test_suitability_section_renders_header_and_status_pill():
    """Sektion 27 hat Header + Pill 'Eignung gegeben' bei result=passed."""
    pypdf = pytest.importorskip("pypdf")
    payload = _make_minimal_payload()
    pdf = render_advisory_report_pdf_from_payload(payload)
    reader = pypdf.PdfReader(__import__("io").BytesIO(pdf))
    text = "\n".join((page.extract_text() or "") for page in reader.pages)
    assert "Eignungspruefung" in text
    assert "Eignung gegeben" in text
    assert "Anna Beispiel" in text
    assert "Suitability" in text


def test_suitability_section_shows_result_notes_and_references():
    """Result-Notes + Referenzen-Tabelle sichtbar bei passed-Check."""
    pypdf = pytest.importorskip("pypdf")
    payload = _make_minimal_payload()
    pdf = render_advisory_report_pdf_from_payload(payload)
    reader = pypdf.PdfReader(__import__("io").BytesIO(pdf))
    text = "\n".join((page.extract_text() or "") for page in reader.pages)
    assert "Anlagestrategie ist mit Risikoprofil" in text
    assert "Verkn" in text
    assert "ra-001" in text
    assert "log-1" in text


def test_suitability_section_shows_override_workflow_on_mismatch_proceeded():
    """Bei Mismatch + Override: rote FIDLEG-Art-12-Box mit Warnungsspur."""
    pypdf = pytest.importorskip("pypdf")
    payload = _make_minimal_payload()
    payload["suitability_summary"] = {
        **payload["suitability_summary"],
        "result": "mismatch",
        "result_notes": "Kunde wuenscht offensivere Strategie als Profil zulaesst.",
        "client_proceeded_despite": True,
        "warning_delivered": True,
        "warning_delivered_at": "2026-05-20T10:00:00.000Z",
        "client_acknowledged": True,
        "client_acknowledged_at": "2026-05-20T10:05:00.000Z",
    }
    pdf = render_advisory_report_pdf_from_payload(payload)
    reader = pypdf.PdfReader(__import__("io").BytesIO(pdf))
    text = "\n".join((page.extract_text() or "") for page in reader.pages)
    assert "Mismatch dokumentiert" in text
    assert "FIDLEG Art. 12" in text
    assert "Warnung ausgeh" in text
    assert "20.05.2026" in text


def test_suitability_section_shows_missing_info_block_when_incomplete():
    """Liste fehlender Infos erscheint als gelber Banner."""
    pypdf = pytest.importorskip("pypdf")
    payload = _make_minimal_payload()
    payload["suitability_summary"] = {
        **payload["suitability_summary"],
        "result": "incomplete",
        "missing_information": [
            "Aktualisierter Anlagehorizont fehlt",
            "Liquiditaetsbedarf nicht dokumentiert",
        ],
    }
    pdf = render_advisory_report_pdf_from_payload(payload)
    reader = pypdf.PdfReader(__import__("io").BytesIO(pdf))
    text = "\n".join((page.extract_text() or "") for page in reader.pages)
    assert "Fehlende Informationen" in text
    assert "Aktualisierter Anlagehorizont" in text
    assert "Liquidi" in text


def test_suitability_section_empty_state_when_no_check():
    """Empty-State wenn has_check=False — Hinweis dass Check fehlt."""
    pypdf = pytest.importorskip("pypdf")
    payload = _make_minimal_payload()
    payload["suitability_summary"] = {
        "has_check": False,
        "check_id": None,
        "performed_at": None,
        "duty_type": None,
        "result": None,
        "result_notes": None,
        "missing_information": [],
        "client_proceeded_despite": False,
        "warning_delivered": False,
        "warning_delivered_at": None,
        "client_acknowledged": False,
        "client_acknowledged_at": None,
        "references": {
            "risk_assessment_id": None,
            "knowledge_assessment_id": None,
            "advisory_log_id": None,
            "recommendation_run_id": None,
            "document_id": None,
        },
        "checked_by_id": None,
        "checked_by_name": "—",
        "linked_log_present": False,
    }
    pdf = render_advisory_report_pdf_from_payload(payload)
    reader = pypdf.PdfReader(__import__("io").BytesIO(pdf))
    text = "\n".join((page.extract_text() or "") for page in reader.pages)
    assert "Noch keine Eignungspruefung" in text
