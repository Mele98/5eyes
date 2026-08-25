"""WP-B (2026-08-01): gemeinsame Provisorik-Gate-Logik fuer PDF-Dokumente.

Verallgemeinert die Logik, die WP4 (2026-07-31) urspruenglich nur fuer den
Advisory-Report gebaut hat
(`services.pdf.documents.advisory_report._resolve_advisory_report_
provisional_notice` / `_build_provisional_notice_banner`), damit sie von
weiteren CMA-/Allokations-abhaengigen PDF-Dokumenttypen wiederverwendet
werden kann, ohne 6x denselben Code zu duplizieren.

Fuer jurisdiction in (None, "CH") liefert `resolve_pdf_provisional_notice`
GARANTIERT `None`, OHNE jeden zusaetzlichen DB-Zugriff (Kurzschluss vor der
ersten Query) -- identisches Verhalten + Performance-Garantie fuer den
CH-Bestand, siehe Auftrag Constraint 1.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from reportlab.lib.colors import HexColor
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, Spacer, Table, TableStyle
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


# Identische Palette wie das Advisory-Report-Banner
# (services.pdf.components.advisory_palette.COLOR_STATUS_ROT /
# COLOR_INK_MUTED), hier als eigenstaendige Konstanten hinterlegt, damit
# dieses Modul unabhaengig vom jeweiligen Dokument-Stylesheet
# (services.pdf.styles vs. services.pdf.components.advisory_palette)
# funktioniert -- Anlagestrategie/AssetAllocation/Portfolio/
# CostDisclosure/Backtest nutzen ein anderes Stylesheet als der
# Advisory-Report.
_BANNER_BACKGROUND = HexColor("#F0D9D9")
_BANNER_BORDER = HexColor("#9E4747")
_BANNER_HEADING_COLOR = HexColor("#9E4747")
_BANNER_BODY_COLOR = HexColor("#3B475A")

BANNER_HEADING_TEXT = "PROVISORISCH — NICHT IC-FREIGEGEBEN"


def resolve_pdf_provisional_notice(db: Session | None, mandate: Any) -> dict[str, Any] | None:
    """Liefert None fuer CH ODER eine bereits IC-freigegebene Nicht-CH-CMA.

    Andernfalls ein dict {jurisdiction, cma_status, message}, das als
    sichtbares "PROVISORISCH -- NICHT IC-FREIGEGEBEN"-Banner im PDF
    erscheinen soll.

    Primaere Quelle ist `RecommendationRun.provisional_data_warning` (von
    WP2 beim Generieren der Empfehlung persistiert) -- das spiegelt exakt
    die CMA-Zeile, die fuer die im Dokument gezeigten Zahlen tatsaechlich
    verwendet wurde, unabhaengig von spaeteren CMA-Aenderungen. Existiert
    (noch) kein Empfehlungslauf, wird die aktuelle Referenzzeile live
    geprueft (`resolve_cma_for_jurisdiction`); fehlen sogar Referenzdaten
    komplett, ist das ebenfalls ein sichtbarer Provisorik-Fall (NIE
    stillschweigend als "ok" behandeln).
    """
    from services.jurisdiction.exceptions import JurisdictionReferenceDataMissingError
    from services.jurisdiction.resolve import (
        resolve_cma_for_jurisdiction,
        resolve_mandate_jurisdiction,
    )

    jurisdiction = resolve_mandate_jurisdiction(mandate)
    if jurisdiction in (None, "CH"):
        return None

    from models.review import RecommendationRun

    latest_run = (
        db.query(RecommendationRun)
        .filter(RecommendationRun.mandate_id == mandate.id)
        .order_by(RecommendationRun.created_at.desc())
        .first()
    )
    if latest_run is not None:
        raw_warning = getattr(latest_run, "provisional_data_warning", None)
        if not raw_warning:
            # Empfehlung wurde mit einer committee_approved-CMA generiert.
            return None
        try:
            parsed = json.loads(raw_warning)
        except (TypeError, ValueError):
            parsed = {}
        message = str(parsed.get("message") or "").strip() or (
            f"Kapitalmarktannahmen fuer Jurisdiktion '{jurisdiction}' sind noch "
            "nicht vom Investment Committee freigegeben."
        )
        return {
            "jurisdiction": jurisdiction,
            "cma_status": parsed.get("cma_status"),
            "message": message,
        }

    # Kein Empfehlungslauf vorhanden (z.B. Dokument vor der ersten
    # Empfehlung angefragt) -- direkte Live-Pruefung der aktuellen
    # CMA-Referenzzeile.
    tenant_id = getattr(mandate, "tenant_id", None)
    try:
        cma = resolve_cma_for_jurisdiction(db, jurisdiction, tenant_id=tenant_id)
    except JurisdictionReferenceDataMissingError:
        return {
            "jurisdiction": jurisdiction,
            "cma_status": None,
            "message": (
                f"Fuer Jurisdiktion '{jurisdiction}' liegen keine "
                "Kapitalmarkt-Referenzdaten vor. Dieses Dokument ist "
                "PROVISORISCH und darf nicht als finales Kundendokument "
                "verwendet werden."
            ),
        }
    cma_status = getattr(cma, "status", None)
    if cma_status == "committee_approved":
        return None
    return {
        "jurisdiction": jurisdiction,
        "cma_status": cma_status,
        "message": (
            f"Kapitalmarktannahmen fuer Jurisdiktion '{jurisdiction}' sind "
            f"noch nicht vom Investment Committee freigegeben (status="
            f"{cma_status!r}). Dieses Dokument ist PROVISORISCH und darf "
            "ohne IC-Freigabe nicht als finales Kundendokument verwendet werden."
        ),
    }


def _escape(text: str) -> str:
    return (
        str(text or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def make_provisional_notice_banner(
    notice: dict[str, Any],
    *,
    table_width: float,
    font_bold: str | None = None,
    font_default: str | None = None,
) -> Table:
    """Rendert dasselbe visuelle Warnbanner wie im Advisory-Report-Cover
    (rote Box, "PROVISORISCH -- NICHT IC-FREIGEGEBEN" + Begruendung),
    generalisiert fuer beliebige Dokumenttypen/Stylesheets.

    `font_bold`/`font_default` sind optional -- ohne Angabe faellt der
    Banner auf die editorial Font-Registrierung
    (`services.pdf.fonts.editorial_font_names`) zurueck, die von allen
    PDF-Dokumenttypen dieser Codebase geteilt wird.
    """
    if font_bold is None or font_default is None:
        from services.pdf.fonts import editorial_font_names
        names = editorial_font_names()
        font_bold = font_bold or names.sans_bold
        font_default = font_default or names.sans

    heading_style = ParagraphStyle(
        "ProvisionalNoticeHeading",
        fontName=font_bold,
        fontSize=9.5,
        leading=12,
        textColor=_BANNER_HEADING_COLOR,
        spaceAfter=0,
    )
    body_style = ParagraphStyle(
        "ProvisionalNoticeBody",
        fontName=font_default,
        fontSize=8,
        leading=10.5,
        textColor=_BANNER_BODY_COLOR,
        spaceAfter=0,
    )

    heading = Paragraph(_escape(BANNER_HEADING_TEXT), heading_style)
    message = str((notice or {}).get("message") or "").strip() or (
        "Diese Kapitalmarktannahmen sind noch nicht vom Investment Committee "
        "freigegeben."
    )
    body = Paragraph(_escape(message), body_style)

    banner = Table([[heading], [body]], colWidths=[table_width])
    banner.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), _BANNER_BACKGROUND),
        ("BOX", (0, 0), (-1, -1), 0.6, _BANNER_BORDER),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (0, 0), 8),
        ("BOTTOMPADDING", (0, 0), (0, 0), 2),
        ("TOPPADDING", (0, 1), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 8),
    ]))
    return banner


def make_provisional_notice_flowables(
    provisional_notice: dict[str, Any] | None,
    *,
    table_width: float,
    font_bold: str | None = None,
    font_default: str | None = None,
    spacer_after_mm: float = 6.0,
) -> list:
    """Bequemlichkeits-Wrapper: Banner + Spacer als fertige Flowable-Liste,
    leer wenn `provisional_notice` None/leer ist (der haeufigste Fall --
    IMMER fuer CH, siehe `resolve_pdf_provisional_notice`).

    Einheitlicher Einzeiler fuer alle 5 Dokumenttypen (Anlagestrategie,
    Asset Allocation, Portfolio, Kostenausweis, Backtest), damit dort kein
    eigener Banner-Rendering-Code entsteht.
    """
    if not provisional_notice:
        return []
    banner = make_provisional_notice_banner(
        provisional_notice,
        table_width=table_width,
        font_bold=font_bold,
        font_default=font_default,
    )
    return [banner, Spacer(1, spacer_after_mm * mm)]
