"""Sprint U-26 (2026-06-06): Tests fuer PDF-Single-Pass-Render via AdvisoryNumberedCanvas.

Pre-U-26 hatte der Advisory-Report-Renderer einen Two-Pass-Build.
AdvisoryNumberedCanvas implementiert den Single-Pass-Trick: sammelt
alle Seiten-States via showPage-Override, dann zeichnet das Chrome
beim save() mit bekannter Gesamtseitenzahl.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]
TESTS_ROOT = Path(__file__).resolve().parents[1]
for path in (BACKEND_ROOT, TESTS_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


def _minimal_payload() -> dict:
    """Minimaler Payload damit der Renderer nicht crashed."""
    return {
        "schema_version": 2,
        "mandate_id": "test-u26",
        "generated_at": "2026-06-06T10:00:00.000Z",
        "cover": {
            "title": "Test", "subtitle": "U-26", "client_name": "Test",
            "mandate_number": "TEST-26", "report_date": "2026-06-06",
            "advisor_name": "Tester",
        },
        "disclaimer": {"hinweise": ["Test-Hinweis 1"]},
        "inhaltsverzeichnis": {"kapitel": [{"nr": 1, "title": "Cover"}]},
        "ausgangslage": {
            "client_info": {},
            "wealth_summary": {"cashflows": [], "ziele": []},
            "key_metrics": {},
        },
        "positionen": {"groups": [], "has_recommendation_run": False, "hinweis": ""},
        "pruefpunkte": {"bloecke": []},
        "erkenntnisse": {"checks": []},
        "asset_allocation": {"items": [], "ist_bps": {}, "soll_bps": {}, "drift_bps": {}},
        "risikowaehrungen": {"items": [], "ist_bps": {}, "soll_bps": {}, "drift_bps": {}},
        "branchen": {"items": [], "ist_bps": {}, "soll_bps": {}, "drift_bps": {}, "anteil_aktien_bps": 0},
        "goal_based_investing": {"goals": [], "monte_carlo_paths": {"data_pending": True}},
        "risikoprofilierung": {},
        "building_blocks": {},
        "statement_pm": {"principles": []},
        "weiteres_vorgehen": {"items": []},
        "beratungsprotokoll": {"entries": []},
        "stress_replay": {"scenarios": []},
        "conflict_disclosures": {"items": []},
        "suitability_compliance": {},
        "methodology_models": {},
        "recommendation_methodology": {},
        "mandate_lock_status": {},
        "liquidity_cascade": {},
    }


# ---------------------------------------------------------------------------
# AdvisoryNumberedCanvas Architektur
# ---------------------------------------------------------------------------

def test_advisory_numbered_canvas_exists():
    """Single-Pass-Trick basiert auf AdvisoryNumberedCanvas."""
    from services.pdf.components.advisory_page_chrome import AdvisoryNumberedCanvas
    from reportlab.pdfgen.canvas import Canvas
    assert issubclass(AdvisoryNumberedCanvas, Canvas)


def test_advisory_numbered_canvas_overrides_show_page():
    """showPage muss ueberschrieben sein um Seiten-States zu sammeln."""
    from services.pdf.components.advisory_page_chrome import AdvisoryNumberedCanvas
    # showPage muss eine Override-Methode sein (nicht von Canvas geerbt)
    assert AdvisoryNumberedCanvas.showPage is not None
    assert AdvisoryNumberedCanvas.showPage.__qualname__.startswith("AdvisoryNumberedCanvas")


def test_advisory_numbered_canvas_overrides_save():
    """save muss ueberschrieben sein um Chrome bei bekannter Pages-Zahl zu zeichnen."""
    from services.pdf.components.advisory_page_chrome import AdvisoryNumberedCanvas
    assert AdvisoryNumberedCanvas.save.__qualname__.startswith("AdvisoryNumberedCanvas")


def test_single_pass_path_documented_in_source():
    """Source-Parse: 'Single-pass' im Docstring + Two-Pass nur als Fallback."""
    src = (BACKEND_ROOT / "services" / "pdf" / "documents" / "advisory_report.py").read_text(encoding="utf-8")
    assert "Single-pass" in src or "Single-Pass" in src
    # Two-pass nur als Fallback
    assert "falling back to two-pass" in src.lower() or "fallback" in src.lower()


# ---------------------------------------------------------------------------
# Render-Pipeline benutzt Single-Pass per Default
# ---------------------------------------------------------------------------

def test_render_pdf_uses_canvasmaker_with_advisory_numbered_canvas():
    """render_advisory_report_pdf_from_payload setzt canvasmaker=
    AdvisoryNumberedCanvas (Single-Pass-Pfad)."""
    src = (BACKEND_ROOT / "services" / "pdf" / "documents" / "advisory_report.py").read_text(encoding="utf-8")
    assert "canvasmaker=_canvasmaker" in src
    assert "AdvisoryNumberedCanvas(" in src


def test_render_pdf_returns_bytes():
    """End-to-End: PDF wird gerendert + liefert bytes (Single-Pass-Pfad).

    Wenn das schief geht, springt der Renderer auf Two-Pass-Fallback —
    aber das Ergebnis (bytes) muss in jedem Fall valide sein.
    """
    from services.pdf.documents.advisory_report import render_advisory_report_pdf_from_payload
    payload = _minimal_payload()
    pdf_bytes = render_advisory_report_pdf_from_payload(payload)
    assert isinstance(pdf_bytes, bytes)
    assert len(pdf_bytes) > 500  # echt was rausgekommen
    # PDF-Magic-Bytes
    assert pdf_bytes.startswith(b"%PDF-")


# ---------------------------------------------------------------------------
# Performance-Smoke-Test
# ---------------------------------------------------------------------------

def test_render_pdf_under_5_seconds_for_minimal_payload():
    """Minimaler Payload muss in < 5 Sek gerendert sein (Single-Pass-Pfad)."""
    from services.pdf.documents.advisory_report import render_advisory_report_pdf_from_payload
    payload = _minimal_payload()
    start = time.perf_counter()
    pdf_bytes = render_advisory_report_pdf_from_payload(payload)
    elapsed = time.perf_counter() - start
    assert pdf_bytes
    # Single-Pass sollte < 5 Sek liefern auch fuer minimal payload
    assert elapsed < 5.0, f"PDF-Render zu langsam: {elapsed:.2f}s (Schwelle 5s)"


def test_render_idempotent_two_calls_same_size():
    """Zwei sequenzielle Renders mit gleichem Payload liefern gleich
    grosse PDFs (deterministisch)."""
    from services.pdf.documents.advisory_report import render_advisory_report_pdf_from_payload
    payload = _minimal_payload()
    pdf1 = render_advisory_report_pdf_from_payload(payload)
    pdf2 = render_advisory_report_pdf_from_payload(payload)
    # PDFs koennen sich in Metadaten unterscheiden (Timestamps, IDs),
    # aber die Groesse sollte aehnlich sein
    size_diff = abs(len(pdf1) - len(pdf2))
    assert size_diff < 1000, f"Render nicht reproduzierbar: Δ={size_diff} bytes"
