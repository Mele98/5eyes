"""PDF-Service — Kundendokumente in WM-Qualitaet via ReportLab.

Spec: docs/planning/2026-05-17-sprint-5-pdf-engine.md

Architektur:
- base.py: PDFRenderer-Protocol + PDFContext
- reportlab_renderer.py: konkrete ReportLab-Implementierung
- styles.py: Designsystem (Farben, Fonts)
- components/: wiederverwendbare PDF-Bausteine
- documents/: vollstaendige Dokument-Typen
"""
from __future__ import annotations

from services.pdf.base import PDFContext, PDFRenderer
from services.pdf.reportlab_renderer import ReportLabRenderer

__all__ = [
    "PDFContext",
    "PDFRenderer",
    "ReportLabRenderer",
]
