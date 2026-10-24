"""Eignungspruefung als vollstaendige Frage-Antwort-Dokumentation.

Der PDF-Bericht bildet den aktuellen FINMA-Risikofragebogen vollstaendig ab:
alle Fragen 1-11 erscheinen immer, inklusive Antwortfeld. Punkte bleiben intern.
Fehlende Antworten werden sichtbar als "Nicht beantwortet" ausgewiesen.
"""
from __future__ import annotations

import json
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
    FONT_SIZE_TABLE,
    FONT_SIZE_TABLE_HEADER,
    PAGE_SIZE,
    make_paragraph_styles,
)


SECTION_ORDER = (
    "Kenntnisse & Erfahrungen",
    "Risikofähigkeit",
    "Risikobereitschaft",
)

QUESTION_CATALOG: dict[int, tuple[str, str]] = {
    1: (
        "Kenntnisse & Erfahrungen",
        "Mit welchen Finanzdienstleistungen haben Sie Kenntnisse und Erfahrungen?",
    ),
    2: (
        "Kenntnisse & Erfahrungen",
        "Mit welchen Finanzinstrumenten haben Sie Kenntnisse und Erfahrungen?",
    ),
    3: (
        "Risikofähigkeit",
        "Regelmässiges Einkommen – Wie hoch ist Ihr regelmässiges Bruttoeinkommen pro Monat aus selbstständiger und unselbstständiger Erwerbstätigkeit, Miete, Anlagen und Rente?",
    ),
    4: (
        "Risikofähigkeit",
        "Herkunft des Einkommens – Woher stammt Ihr regelmässiges Einkommen?",
    ),
    5: (
        "Risikofähigkeit",
        "Finanzielle Verpflichtungen – Wie hoch sind Ihre aktuellen und künftig absehbaren finanziellen Verpflichtungen pro Monat?",
    ),
    6: (
        "Risikofähigkeit",
        "Vermögen – Wie hoch ist Ihr frei verfügbares Vermögen (z.B. Kontoguthaben, Wertschriften), welches Sie nicht zur Deckung von aktuellen oder zukünftigen finanziellen Verpflichtungen benötigen?",
    ),
    7: (
        "Risikofähigkeit",
        "Sparen – Wie viel Prozent Ihres Einkommens können Sie unter Berücksichtigung des regelmässigen Einkommens, der finanziellen Verpflichtungen und der sonstigen Ausgaben zur Seite legen?",
    ),
    8: (
        "Risikofähigkeit",
        "Anlagehorizont – Wie lange können Sie das investierte Kapital mindestens anlegen?",
    ),
    9: (
        "Risikobereitschaft",
        "Anlageziel – Welcher Zweck wird mit der Vermögensanlage verfolgt?",
    ),
    10: (
        "Risikobereitschaft",
        "Risikoverhalten – Anlagen mit höherer erwarteter Rendite haben auch ein höheres erwartetes Risiko.",
    ),
    11: (
        "Risikobereitschaft",
        "Risikoverhalten – Sie stellen fest, dass Ihre Anlagen einen Verlust von 20 % erlitten haben. Wie reagieren Sie?",
    ),
}


def make_eignungspruefung_section(
    *,
    answers: Iterable[Mapping] | None = None,
    services_knowledge: Mapping[str, bool] | None = None,
    instruments_knowledge: Mapping[str, bool] | None = None,
) -> list:
    """FINMA-Fragebogen: jede Frage immer mit Frage und Antwort."""
    flowables: list = []
    answers_list = [a for a in (answers or []) if isinstance(a, Mapping)]

    answers_by_question: dict[int, Mapping] = {}
    extra_entries: list[tuple[int, str, str, str]] = []
    for answer in answers_list:
        try:
            qn = int(answer.get("question_number", 0))
        except (TypeError, ValueError):
            continue
        if qn <= 0:
            continue
        if qn in QUESTION_CATALOG:
            answers_by_question[qn] = answer
            continue
        extra_entries.append((
            qn,
            str(answer.get("question_section", "") or "Weitere Angaben"),
            str(answer.get("question_text", "") or f"Frage {qn}"),
            str(answer.get("answer_label", "") or "Nicht beantwortet"),
        ))

    grouped: dict[str, list[tuple[int, str, str]]] = {section: [] for section in SECTION_ORDER}
    for qn in sorted(QUESTION_CATALOG):
        section, question_text = QUESTION_CATALOG[qn]
        answer = answers_by_question.get(qn)
        grouped[section].append((
            qn,
            question_text,
            _answer_text(qn, answer, services_knowledge or {}, instruments_knowledge or {}),
        ))

    for qn, section, question_text, answer_text in extra_entries:
        grouped.setdefault(section, []).append((qn, question_text, answer_text))

    flowables.append(_section_title("Eignungsprüfung - Risikofragebogen"))

    rows = [["Frage", "Antwort"]]
    section_rows: list[int] = []
    for section in list(SECTION_ORDER) + [s for s in grouped if s not in SECTION_ORDER]:
        entries = grouped.get(section, [])
        if not entries:
            continue

        section_rows.append(len(rows))
        rows.append([
            Paragraph(
                f'<font name="{FONT_BOLD}" size="7.5" color="#0f172a">{_esc(section)}</font>',
                _para_q(),
            ),
            "",
        ])
        for qn, question_text, answer_text in sorted(entries, key=lambda x: x[0]):
            rows.append([
                Paragraph(
                    f'<font name="{FONT_BOLD}">Frage {qn}</font><br/>{_esc(question_text)}',
                    _para_q(),
                ),
                Paragraph(
                    f'<font name="{FONT_BOLD}">{_esc(answer_text)}</font>',
                    _para_a(),
                ),
            ])

    page_width, _ = PAGE_SIZE
    table_width = page_width - 24 * mm
    table = Table(
        rows,
        colWidths=[table_width * 0.55, table_width * 0.45],
        repeatRows=1,
    )
    style_cmds = [
        ("FONTNAME", (0, 0), (-1, 0), FONT_BOLD),
        ("FONTSIZE", (0, 0), (-1, 0), FONT_SIZE_TABLE_HEADER),
        ("FONTSIZE", (0, 1), (-1, -1), 6.6),
        ("BACKGROUND", (0, 0), (-1, 0), COLOR_TABLE_HEADER_BG),
        ("TEXTCOLOR", (0, 0), (-1, 0), COLOR_TEXT_LIGHT),
        ("TEXTCOLOR", (0, 1), (-1, -1), COLOR_TEXT),
        ("LINEBELOW", (0, 0), (-1, 0), 0.8, COLOR_BORDER),
        ("LINEBELOW", (0, 1), (-1, -2), 0.25, COLOR_BORDER),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 2.2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.2),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]
    for row_idx in section_rows:
        style_cmds.extend([
            ("SPAN", (0, row_idx), (-1, row_idx)),
            ("BACKGROUND", (0, row_idx), (-1, row_idx), COLOR_TABLE_HEADER_BG),
            ("LINEABOVE", (0, row_idx), (-1, row_idx), 0.4, COLOR_BORDER),
            ("TOPPADDING", (0, row_idx), (-1, row_idx), 2),
            ("BOTTOMPADDING", (0, row_idx), (-1, row_idx), 2),
        ])
    table.setStyle(TableStyle(style_cmds))
    flowables.append(table)

    return flowables


def _answer_text(
    question_number: int,
    answer: Mapping | None,
    services_knowledge: Mapping,
    instruments_knowledge: Mapping,
) -> str:
    if answer:
        label = str(answer.get("answer_label", "") or "").strip()
        if label:
            return _clean_answer_label(question_number, label)
    if question_number == 1:
        return _knowledge_summary(services_knowledge)
    if question_number == 2:
        return _knowledge_summary(instruments_knowledge)
    return "Nicht beantwortet"


def _clean_answer_label(question_number: int, label: str) -> str:
    if question_number not in (1, 2):
        return label
    if ":" not in label:
        return label
    _, payload = label.split(":", 1)
    payload = payload.strip()
    if not payload.startswith("{"):
        return label
    try:
        parsed = json.loads(payload)
    except (TypeError, ValueError, json.JSONDecodeError):
        return label
    return _knowledge_summary(parsed)


def _knowledge_summary(items: Mapping) -> str:
    if not items:
        return "Nicht beantwortet"
    parts: list[str] = []
    for key, value in items.items():
        label = str(key)
        if isinstance(value, Mapping):
            known = bool(value.get("known") or value.get("kenntnis") or value.get("kenntnisse"))
            informed = bool(value.get("informed") or value.get("aufklaerung") or value.get("aufklärung"))
            states = []
            if known:
                states.append("Kenntnisse vorhanden")
            if informed:
                states.append("Aufklärung erhalten")
            parts.append(f"{label}: {', '.join(states) if states else 'keine Angabe'}")
        else:
            parts.append(f"{label}: {'Kenntnisse vorhanden' if value else 'keine Angabe'}")
    return "; ".join(parts) if parts else "Nicht beantwortet"


def _legacy_bool_section(services_knowledge: Mapping, instruments_knowledge: Mapping) -> list:
    """Kompatibilitaetshelfer fuer alte Direktaufrufe."""
    if not services_knowledge and not instruments_knowledge:
        return []
    styles = make_paragraph_styles()
    flowables = [_section_title("Eignungsprüfung - Kenntnisse")]
    flowables.append(Paragraph(
        f'<font name="{FONT_DEFAULT}" size="9" color="#94a3b8"><i>'
        f'Keine detaillierten Antworten aus dem Risikoprofil-Fragebogen verfügbar. '
        f'Nachfolgend nur die Bool-Übersicht aus dem Mandate-Stammprofil.</i></font>',
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
            rows.append([_esc(str(key)), "Ja" if value else "—"])
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
        fontSize=6.6,
        textColor=COLOR_TEXT,
        leading=7.4,
        spaceAfter=0,
    )


def _para_a():
    from reportlab.lib.styles import ParagraphStyle
    return ParagraphStyle(
        "EignAntwort",
        fontName=FONT_DEFAULT,
        fontSize=6.6,
        textColor=COLOR_TEXT,
        leading=7.4,
        spaceAfter=0,
    )
