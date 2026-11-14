"""H9 -- Risikofaehigkeit ohne Widerspruchswarnung (Owner-Vorgabe 2026-11-08).

Kundenangaben zur Risikofaehigkeit werden respektiert; der Berater sorgt
selbst fuer die Plausibilitaet. Darum gegenueber dem Kunden keine
Widerspruchs-Badges/Warnboxen mehr:

- Maske Risikoprofil: keine Warnbox "Angaben widersprechen den erfassten
  Finanzdaten", kein "neu zu pruefen"-Badge, kein Laden der Pruefung.
- Strategie (AA-Maske): kein Plausibilitaetshinweis im Reasoning.
- PDFs: kein Hinweis im Risikoprofil-PDF und im Beratungsbericht.

Unveraendert (bewusst): Fragen, Punkte, Formel und Ergebnis des
Risikoprofils; die Pruefung selbst laeuft intern weiter (Datenfeld,
unveraenderliche Evidenz-Snapshots, Audit-Eintrag) und blockiert nichts.
"""
from __future__ import annotations

import inspect
from io import BytesIO

from tests.monolith_source import read_frontend_sources

from services import risk_capacity_plausibility as rcp
from services.risk_capacity_plausibility_report import compact_view


def test_risk_mask_has_no_contradiction_warning_or_badge():
    src = read_frontend_sources()
    for needle in (
        "widersprechen den erfassten Finanzdaten",
        'id="rp-capacity-plausibility"',
        'id="rp-capacity-recheck"',
        "renderRiskCapacityPlausibility",
        "refreshRiskCapacityPlausibility",
        "/risk-capacity-plausibility",
        "Risikofähigkeit: noch nicht verifiziert",
    ):
        assert needle not in src, needle


def _inconsistent():
    from tests.test_risk_capacity_plausibility import _inconsistent_result

    return _inconsistent_result()


def test_strategy_reasoning_carries_no_plausibility_hint():
    result = _inconsistent()
    assert result["status"] == "inconsistent"
    payload = rcp.attach_to_strategy_payload({"reasoning": ["House Matrix"]}, result)
    assert payload["reasoning"] == ["House Matrix"]
    assert payload["risk_capacity_plausibility"] is result  # intern weiter verfuegbar


def test_risk_profile_pdf_route_feeds_no_plausibility_note():
    from routers import pdf_reports

    src = inspect.getsource(pdf_reports)
    assert "pdf_advisor_note" not in src
    assert 'capacity_plausibility_note = ""' in src


def test_advisory_report_pdf_has_no_plausibility_note():
    from pypdf import PdfReader
    from services.pdf.documents.advisory_report import render_advisory_report_pdf_from_payload
    from test_advisory_report_pdf import _make_minimal_payload

    payload = _make_minimal_payload()
    ss = dict(payload.get("suitability_summary") or {})
    ss["has_check"] = True
    ss["risk_capacity_plausibility"] = compact_view(_inconsistent())
    payload["suitability_summary"] = ss
    reader = PdfReader(BytesIO(render_advisory_report_pdf_from_payload(payload)))
    text = " ".join(" ".join((p.extract_text() or "").split()) for p in reader.pages)
    assert "Plausibilitätsprüfung" not in text
    assert "Widerspruch" not in text
