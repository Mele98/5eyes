"""Sprint 14 Phase 2: Eignungspruefung als Frage-Antwort-Dokumentation.

FINMA-W305-konform: explizite Frage-Antwort-Liste statt nur Bool-Tabelle.
Gruppiert in drei Bereiche:
- Kenntnisse und Erfahrungen (Q1-Q5)
- Risikobereitschaft (Q9-Q11)
- Risikotragfaehigkeit (Q6-Q8)

Datenquelle: RiskAssessmentAnswer (question_number, answer_label,
answer_points). Frage-Texte sind statisch (Frontend-konsistent).
"""
from __future__ import annotations

from typing import Iterable, Mapping

from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, Spacer, Table, TableStyle

from services.pdf.components.header import _esc
from services.pdf.styles import (
    COLOR_BORDER,
    COLOR_TABLE_HEADER_BG,
    COLOR_TEXT,
    COLOR_TEXT_LIGHT,
    FONT_BOLD,
    FONT_DEFAULT,
    FONT_SIZE_SMALL,
    FONT_SIZE_TABLE,
    FONT_SIZE_TABLE_HEADER,
    PAGE_SIZE,
    make_paragraph_styles,
)


# Frage-Texte und Bereich-Zuordnung (konsistent zum Frontend-Fragebogen).
# Plus Reihenfolge der Bereiche fuer die Anzeige.
SECTION_ORDER = (
    "Kenntnisse und Erfahrungen",
    "Risikobereitschaft",
    "Risikotragfähigkeit",
)

QUESTION_CATALOG: dict[int, tuple[str, str]] = {
    1: ("Kenntnisse und Erfahrungen",
        "Von welchen Bewirtschaftungsformen / Finanzdienstleistungen haben Sie Kenntnisse?"),
    2: ("Kenntnisse und Erfahrungen",
        "Welche Erfahrungen haben Sie mit Wertschriftenanlagen / Finanzinstrumenten?"),
    3: ("Kenntnisse und Erfahrungen",
        "Wie hoch ist Ihr jährliches Bruttoeinkommen?"),
    4: ("Kenntnisse und Erfahrungen",
        "Woher stammt Ihr Einkommen?"),
    5: ("Kenntnisse und Erfahrungen",
        "Wie hoch sind Ihre aktuellen und künftig absehbaren jährlichen Verpflichtungen?"),
    6: ("Risikotragfähigkeit",
        "Wie hoch ist Ihr investierbares Vermögen?"),
    7: ("Risikotragfähigkeit",
        "Welcher Anteil Ihres Vermögens soll angelegt werden bzw. wie hoch sind Ihre sofort verfügbaren Reserven?"),
    8: ("Risikotragfähigkeit",
        "Wie lange können Sie Ihr Geld voraussichtlich anlegen (Anlagehorizont)?"),
    9: ("Risikobereitschaft",
        "Welcher Zweck wird mit der Vermögensanlage verfolgt?"),
    10: ("Risikobereitschaft",
        "Welches Risiko-/Rendite-Profil bevorzugen Sie?"),
    11: ("Risikobereitschaft",
        "Wie reagieren Sie, wenn Ihre Anlagen vorübergehend Verluste erleiden (z.B. -20%)?"),
}


def make_eignungspruefung_section(
    *,
    answers: Iterable[Mapping] | None = None,
    services_knowledge: Mapping[str, bool] | None = None,
    instruments_knowledge: Mapping[str, bool] | None = None,
) -> list:
    """FINMA-konforme Eignungspruefung als 3 Bereiche mit Frage-Antwort-Tabellen.

    answers: Liste von dicts {question_number, answer_label, answer_points}
             aus RiskAssessmentAnswer-Tabelle (bevorzugte Quelle).
    services_knowledge / instruments_knowledge: Legacy-Fallback (Bool-Dict)
             wenn keine Answers vorhanden, dann Fallback-Hinweis ausgeben.
    """
    flowables: list = []
    styles = make_paragraph_styles()
    answers_list = [a for a in (answers or []) if isinstance(a, Mapping)]

    if not answers_list:
        # Legacy-Fallback: alte Bool-Sektion wenn Answers nicht verfuegbar
        return _legacy_bool_section(
            services_knowledge or {}, instruments_knowledge or {}
        )

    # Sprint 14 Phase 3: Bereich-Zuordnung primaer aus den Answer-Daten
    # (question_section). Fallback: Catalog. So sind Antworten immer dort
    # gruppiert wo sie im Frontend-Fragebogen wirklich stehen.
    def _normalize_section(s: str) -> str:
        v = (s or "").strip()
        # Normalisierung: Umlaute + Capitalize → matchen mit SECTION_ORDER
        norm = (v.replace("ae", "ä").replace("oe", "ö").replace("ue", "ü"))
        for canonical in SECTION_ORDER:
            if norm.lower() == canonical.lower():
                return canonical
            if v.lower() == canonical.lower():
                return canonical
        return v or "Sonstiges"

    grouped: dict[str, list] = {sec: [] for sec in SECTION_ORDER}
    for a in answers_list:
        try:
            qn = int(a.get("question_number", 0))
        except (TypeError, ValueError):
            continue
        if qn <= 0:
            continue
        # Section: bevorzugt aus answer-data, sonst aus catalog
        raw_section = str(a.get("question_section", "") or "")
        if raw_section:
            section = _normalize_section(raw_section)
        elif qn in QUESTION_CATALOG:
            section = QUESTION_CATALOG[qn][0]
        else:
            section = "Sonstiges"
        # Frage-Text: bevorzugt aus answer-data, sonst Catalog
        question_text = str(a.get("question_text", "") or "")
        if not question_text and qn in QUESTION_CATALOG:
            question_text = QUESTION_CATALOG[qn][1]
        if not question_text:
            question_text = f"Frage {qn}"
        answer_label = str(a.get("answer_label", "") or "—")
        try:
            points = int(a.get("answer_points", 0) or 0)
        except (TypeError, ValueError):
            points = 0
        grouped.setdefault(section, []).append((qn, question_text, answer_label, points))

    # Leere Sections entfernen
    grouped = {k: v for k, v in grouped.items() if v}

    flowables.append(_section_title("Eignungsprüfung — Kenntnisse, Risikobereitschaft und Risikotragfähigkeit"))

    # Pro Bereich eine Sub-Sektion mit Frage-Antwort-Tabelle
    for section in list(SECTION_ORDER) + [s for s in grouped if s not in SECTION_ORDER]:
        entries = grouped.get(section)
        if not entries:
            continue

        flowables.append(Spacer(1, 2.5 * mm))
        flowables.append(Paragraph(
            f'<font name="{FONT_BOLD}" size="10" color="#0f172a">{_esc(section)}</font>',
            styles["body"],
        ))

        rows = [["Frage", "Antwort", "Punkte"]]
        for qn, question_text, answer_label, points in sorted(entries, key=lambda x: x[0]):
            rows.append([
                Paragraph(_esc(question_text), _para_q()),
                Paragraph(
                    f'<font name="{FONT_BOLD}">{_esc(answer_label)}</font>',
                    _para_a(),
                ),
                Paragraph(
                    f'<para align="center"><font name="{FONT_BOLD}" color="#475569">'
                    f'{points if points else "—"}</font></para>',
                    _para_a(),
                ),
            ])

        page_width, _ = PAGE_SIZE
        table_width = page_width - 24 * mm
        table = Table(
            rows,
            colWidths=[table_width * 0.55, table_width * 0.35, table_width * 0.10],
            repeatRows=1,
        )
        table.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, 0), FONT_BOLD),
            ("FONTSIZE", (0, 0), (-1, 0), FONT_SIZE_TABLE_HEADER),
            ("FONTSIZE", (0, 1), (-1, -1), FONT_SIZE_TABLE),
            ("BACKGROUND", (0, 0), (-1, 0), COLOR_TABLE_HEADER_BG),
            ("TEXTCOLOR", (0, 0), (-1, 0), COLOR_TEXT_LIGHT),
            ("TEXTCOLOR", (0, 1), (-1, -1), COLOR_TEXT),
            ("LINEBELOW", (0, 0), (-1, 0), 0.8, COLOR_BORDER),
            ("LINEBELOW", (0, 1), (-1, -2), 0.3, COLOR_BORDER),
            ("ALIGN", (2, 0), (2, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ]))
        flowables.append(table)

    return flowables


def _legacy_bool_section(services_knowledge: Mapping, instruments_knowledge: Mapping) -> list:
    """Fallback wenn keine RiskAssessmentAnswer-Daten verfuegbar:
    nutze die alte Bool-Tabelle (Knowledge-JSONs aus RiskAssessment)."""
    if not services_knowledge and not instruments_knowledge:
        return []
    styles = make_paragraph_styles()
    flowables = [_section_title("🔍  Eignungsprüfung — Kenntnisse")]
    flowables.append(Paragraph(
        f'<font name="{FONT_DEFAULT}" size="9" color="#94a3b8"><i>'
        f'Keine detaillierten Antworten aus dem Risikoprofil-Fragebogen '
        f'verfügbar. Nachfolgend nur die Bool-Übersicht aus dem Mandate-'
        f'Stammprofil. Vollständige Eignungsprüfung benötigt ausgefüllten '
        f'Fragebogen.</i></font>',
        styles["small_muted"],
    ))
    flowables.append(Spacer(1, 2 * mm))

    page_width, _ = PAGE_SIZE
    table_width = page_width - 24 * mm
    services_table = _make_knowledge_subtable(services_knowledge, "Finanzdienstleistungen")
    instruments_table = _make_knowledge_subtable(instruments_knowledge, "Finanzinstrumente")
    composite = Table(
        [[services_table, instruments_table]],
        colWidths=[table_width / 2, table_width / 2],
    )
    composite.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
    ]))
    flowables.append(composite)
    return flowables


def _make_knowledge_subtable(items: Mapping, header_label: str) -> Table:
    rows = [[header_label, "Kenntnis"]]
    if not items:
        rows.append(["Keine Angaben", "—"])
    else:
        for key, value in items.items():
            rows.append([_esc(str(key)), "☑" if value else "☐"])
    table = Table(rows, colWidths=[None, 22 * mm])
    table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, 0), FONT_BOLD),
        ("FONTSIZE", (0, 0), (-1, 0), FONT_SIZE_TABLE_HEADER),
        ("FONTSIZE", (0, 1), (-1, -1), FONT_SIZE_TABLE),
        ("BACKGROUND", (0, 0), (-1, 0), COLOR_TABLE_HEADER_BG),
        ("TEXTCOLOR", (0, 0), (-1, 0), COLOR_TEXT_LIGHT),
        ("LINEBELOW", (0, 0), (-1, 0), 0.8, COLOR_BORDER),
        ("LINEBELOW", (0, 1), (-1, -2), 0.3, COLOR_BORDER),
        ("ALIGN", (1, 0), (1, -1), "CENTER"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]))
    return table


def _section_title(text: str):
    style = make_paragraph_styles()["section_title"]
    return Paragraph(
        f'<font name="{FONT_BOLD}" size="12" color="#0f172a">{_esc(text)}</font>',
        style,
    )


def _para_q():
    from reportlab.lib.styles import ParagraphStyle
    return ParagraphStyle(
        "EignFrage",
        fontName=FONT_DEFAULT,
        fontSize=FONT_SIZE_TABLE,
        textColor=COLOR_TEXT,
        leading=11,
        spaceAfter=0,
    )


def _para_a():
    from reportlab.lib.styles import ParagraphStyle
    return ParagraphStyle(
        "EignAntwort",
        fontName=FONT_DEFAULT,
        fontSize=FONT_SIZE_TABLE,
        textColor=COLOR_TEXT,
        leading=11,
        spaceAfter=0,
    )
