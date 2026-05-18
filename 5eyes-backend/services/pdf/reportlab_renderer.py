"""ReportLab-basierter PDF-Renderer.

Implementiert das PDFRenderer-Protocol mit ReportLab's Platypus-Framework
(Flowables, Document-Templates). Pure-Python — keine externen Binaries.
"""
from __future__ import annotations

from io import BytesIO

from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate

from services.pdf.base import (
    AnlagestrategieData,
    PDFContext,
    RisikoprofilData,
)
from services.pdf.styles import (
    MARGIN_BOTTOM,
    MARGIN_LEFT,
    MARGIN_RIGHT,
    MARGIN_TOP,
    PAGE_SIZE,
)


class ReportLabRenderer:
    """Konkrete PDFRenderer-Implementierung mit ReportLab."""

    def render_anlagestrategie(
        self, ctx: PDFContext, data: AnlagestrategieData
    ) -> bytes:
        # Lazy-Import des Document-Builders fuer Test-Isolation
        from services.pdf.documents.anlagestrategie import build_anlagestrategie_flowables
        return self._render_to_bytes(
            ctx=ctx,
            title="Anlagestrategie",
            build_flowables=lambda: build_anlagestrategie_flowables(ctx, data),
        )

    def render_risikoprofil(
        self, ctx: PDFContext, data: RisikoprofilData
    ) -> bytes:
        from services.pdf.documents.risikoprofil import build_risikoprofil_flowables
        return self._render_to_bytes(
            ctx=ctx,
            title="Risikoprofil",
            build_flowables=lambda: build_risikoprofil_flowables(ctx, data),
        )

    def render_portfolio(self, ctx: PDFContext, data) -> bytes:
        """Sprint 11 Phase 6: Portfolio-PDF (Positionen + Drift)."""
        from services.pdf.documents.portfolio import build_portfolio_flowables
        return self._render_to_bytes(
            ctx=ctx,
            title="Portfolio",
            build_flowables=lambda: build_portfolio_flowables(ctx, data),
        )

    def render_vertrag(self, ctx: PDFContext, data) -> bytes:
        """Sprint 12: Vertrags-PDF (ContractDocument)."""
        from services.pdf.documents.vertrag import build_vertrag_flowables
        return self._render_to_bytes(
            ctx=ctx,
            title=str(getattr(data, "document_title", "Vertrag")),
            build_flowables=lambda: build_vertrag_flowables(ctx, data),
        )

    def _render_to_bytes(
        self,
        *,
        ctx: PDFContext,
        title: str,
        build_flowables,
    ) -> bytes:
        """Gemeinsamer Render-Loop fuer alle Dokument-Typen."""
        from services.pdf.components.footer import make_footer_callback

        buffer = BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=PAGE_SIZE,
            topMargin=MARGIN_TOP,
            bottomMargin=MARGIN_BOTTOM + 12 * mm,  # extra Platz fuer Footer
            leftMargin=MARGIN_LEFT,
            rightMargin=MARGIN_RIGHT,
            title=f"5eyes — {title} — {ctx.mandate_name}",
            author=ctx.advisor_name,
            subject=title,
        )
        footer_cb = make_footer_callback(ctx)
        doc.build(
            build_flowables(),
            onFirstPage=footer_cb,
            onLaterPages=footer_cb,
        )
        return buffer.getvalue()
