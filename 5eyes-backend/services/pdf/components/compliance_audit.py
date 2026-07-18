"""Compliance-audit block for the Advisory-Report PDF.

Renders the read-only FINMA audit sections 19-23 from the
`compute_advisory_report` payload. This module deliberately does not
compute or reclassify recommendations; it only makes existing audit
signals visible in the PDF.
"""
from __future__ import annotations

from typing import Any

from reportlab.lib.colors import HexColor
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import KeepTogether, Paragraph, Spacer, Table, TableStyle

from services.pdf.components.advisory_palette import (
    COLOR_ACCENT,
    COLOR_CANVAS_SUBTLE,
    COLOR_GOLD,
    COLOR_INK,
    COLOR_INK_MUTED,
    COLOR_INK_SUBTLE,
    COLOR_RULE,
    COLOR_STATUS_GRUEN,
    COLOR_STATUS_ROT,
    FONT_MONO,
    FONT_SANS_BOLD,
    MARGIN_LEFT,
    MARGIN_RIGHT,
    PAGE_SIZE,
)
from services.pdf.components.swiss_numbers import format_bps_as_pct, format_integer


PILL_OK = ("gruen", "#E5EEDF", "#4E6F58")
PILL_BAD = ("rot", "#F0D9D9", "#9E4747")
PILL_PENDING = ("Daten ausstehend", "#E9EBEE", "#7A8395")


def render_compliance_audit_section(payload: dict, story: list, styles) -> None:
    """Append the consolidated Compliance-Audit PDF section.

    The function is intentionally side-effect free except for appending
    ReportLab flowables to `story`.
    """
    story.append(Paragraph("Sektionen 19-23", styles["kicker"]))
    story.append(Paragraph("Compliance-Audit", styles["h1"]))
    story.append(Spacer(1, 4 * mm))
    story.append(_hr())
    story.append(Spacer(1, 5 * mm))
    story.append(Paragraph(
        "Kompakte FINMA-Audit-Sicht auf Geeignetheitspruefung, "
        "Methodik, Optimizer-Herleitung, Mandats-Sperren und "
        "Liquiditaets-Cascade. Die Sektion ist rein dokumentierend "
        "und loest keine automatische Portfolio-Anpassung aus.",
        _style(styles["caption"], color=COLOR_INK_MUTED),
    ))
    story.append(Spacer(1, 5 * mm))

    blocks = [
        _suitability_block(payload.get("suitability_compliance") or {}, styles),
        _methodology_block(payload.get("methodology_models") or {}, styles),
        _recommendation_block(payload.get("recommendation_methodology") or {}, styles),
        _mandate_lock_block(payload.get("mandate_lock_status") or {}, styles),
        _liquidity_block(payload.get("liquidity_cascade") or {}, styles),
    ]
    # Sprint C2 (2026-06-07): Engine-Configuration-Block sichtbar machen
    # (IS-Status, Tax-Mode, Sub-Allocation-Aware). Nur appended wenn payload
    # einen 'engine_configuration'-Key enthaelt (Backwards-Compat: optional).
    engine_cfg = payload.get("engine_configuration")
    if engine_cfg:
        blocks.append(_engine_configuration_block(engine_cfg, styles))
    for index, block in enumerate(blocks):
        if index:
            story.append(Spacer(1, 4 * mm))
        story.append(KeepTogether(block))


def _suitability_block(data: dict, styles) -> list:
    # Fail-closed (2026-07-18): NUR der explizite audit_degraded-Marker
    # (Audit-Exception) -> 'Pruefung nicht moeglich' (amber). Ein fehlendes
    # is_compliant (leeres Minimal-Payload) bleibt beim bisherigen Verhalten.
    is_degraded = bool(data.get("audit_degraded"))
    is_compliant = bool(data.get("is_compliant", True))
    violations = _collect_suitability_violations(data)
    rows = [[
        _metric("Total-Logs", data.get("total_advisory_logs"), styles),
        _metric("Required", data.get("logs_requiring_suitability"), styles),
        _metric("Mit Check", data.get("logs_with_suitability"), styles),
        _metric("Ohne Check", len(data.get("logs_without_suitability") or []), styles),
    ]]
    pill = _pill(*PILL_PENDING, styles=styles) if is_degraded else _compliance_pill(is_compliant, styles)
    out = [
        _block_header("Geeignetheitspruefung", pill, styles),
        _metrics_row(rows, styles),
    ]
    if is_degraded:
        out.append(_muted_note(
            "Pruefung nicht moeglich: Suitability-Audit fehlgeschlagen. "
            "Konformitaet konnte NICHT bestaetigt werden.", styles))
    elif violations:
        out.append(Spacer(1, 2 * mm))
        out.append(_issues_table(
            violations,
            styles,
            headers=("Typ", "Referenz", "Grund"),
            empty_text="Keine Verstoesse erfasst.",
        ))
    else:
        out.append(_muted_note("Keine Suitability-Verstoesse im Audit-Payload.", styles))
    accent = COLOR_ACCENT if is_degraded else (COLOR_STATUS_GRUEN if is_compliant else COLOR_STATUS_ROT)
    return [_panel(out, styles, accent=accent)]


def _methodology_block(data: dict, styles) -> list:
    models = list(data.get("models") or [])
    is_pending = not models
    active_count = int(data.get("active_count") or 0)
    if is_pending:
        pill = _pill(*PILL_PENDING, styles=styles)
    elif active_count > 0:
        pill = _pill("aktiv", "#E5EEDF", "#4E6F58", styles)
    else:
        pill = _pill("keine aktiv", "#F4EBD5", "#B59243", styles)

    out = [
        _block_header("Methodology-Modelle", pill, styles),
    ]
    if is_pending:
        out.append(_muted_note("Daten ausstehend: keine Modell-Statuszeilen im Payload.", styles))
    else:
        rows = [[_th("Modell", styles), _th("Status", styles), _th("Basis", styles)]]
        for model in models:
            rows.append([
                _p(_safe(model.get("label")), styles, bold=True),
                _pill("aktiv" if model.get("active") else "inaktiv",
                      "#E5EEDF" if model.get("active") else "#E9EBEE",
                      "#4E6F58" if model.get("active") else "#7A8395",
                      styles),
                _p(_safe(model.get("basis")), styles, muted=True),
            ])
        out.append(_table(rows, [0.30, 0.16, 0.54], styles))

    notes = list(data.get("methodology_notes") or [])
    if notes:
        out.append(Spacer(1, 2 * mm))
        out.append(_bullet_list("Berater-Hinweise", notes[:4], styles))
    return [_panel(out, styles, accent=COLOR_ACCENT)]


def _recommendation_block(data: dict, styles) -> list:
    # Fail-closed (2026-07-18): nur expliziter audit_degraded-Marker -> pending
    # (amber), nie gruen. Fehlendes Payload faellt weiter auf has_run/pending.
    is_degraded = bool(data.get("audit_degraded"))
    is_compliant = bool(data.get("is_compliant", True))
    active_run = data.get("latest_active_run") or data.get("latest_run") or {}
    has_run = isinstance(active_run, dict) and bool(active_run)
    pill = (
        _pill(*PILL_PENDING, styles=styles)
        if is_degraded or not has_run
        else _compliance_pill(is_compliant, styles)
    )

    out = [
        _block_header("Recommendation-Methodology", pill, styles),
        _metrics_row([[
            _metric("Runs", data.get("total_runs"), styles),
            _metric("Active", data.get("active_count"), styles),
            _metric("Shadow", data.get("shadow_count"), styles),
            _metric("Fallback", data.get("fallback_count"), styles),
        ]], styles),
    ]
    if has_run:
        details = [
            ("Methode", _safe(active_run.get("method") or active_run.get("optimizer_mode"))),
            ("Status", _safe(active_run.get("status_label") or active_run.get("status"))),
            ("Konvergenz", "akzeptiert" if active_run.get("is_acceptable") else "pruefen"),
            ("Seed / Pfade", _seed_paths(active_run)),
        ]
        out.append(Spacer(1, 2 * mm))
        out.append(_kv_table(details, styles))
    elif is_degraded:
        out.append(_muted_note(
            "Pruefung nicht moeglich: Recommendation-Audit fehlgeschlagen. "
            "Konformitaet konnte NICHT bestaetigt werden.", styles))
    else:
        out.append(_muted_note("Daten ausstehend: kein Optimizer-Run im Payload.", styles))
    accent = COLOR_ACCENT if (is_degraded or not has_run) else (
        COLOR_STATUS_GRUEN if is_compliant else COLOR_STATUS_ROT)
    return [_panel(out, styles, accent=accent)]


def _mandate_lock_block(data: dict, styles) -> list:
    is_editable = bool(data.get("is_editable", True))
    pill = (
        _pill("editierbar", "#E5EEDF", "#4E6F58", styles)
        if is_editable
        else _pill("Read-only", "#F0D9D9", "#9E4747", styles)
    )
    out = [
        _block_header("Mandate-Lock-Status", pill, styles),
        _kv_table([
            ("Mandat-Status", _safe(data.get("mandate_status"))),
            ("Letzter Optimizer-Status", _safe(data.get("latest_optimizer_status"))),
        ], styles),
    ]
    reasons = list(data.get("lock_reasons") or [])
    labels = data.get("lock_reason_labels") or {}
    if reasons:
        out.append(Spacer(1, 2 * mm))
        out.append(_bullet_list(
            "Lock-Reasons",
            [str(labels.get(reason) or reason) for reason in reasons],
            styles,
        ))
    else:
        out.append(_muted_note("Keine Read-only-Reasons im Audit-Payload.", styles))
    return [_panel(out, styles, accent=COLOR_STATUS_GRUEN if is_editable else COLOR_STATUS_ROT)]


def _liquidity_block(data: dict, styles) -> list:
    stage = str(data.get("stage") or "unknown")
    warning_required = bool(data.get("warning_required"))
    pill = _stage_pill(stage, warning_required, styles)
    over = data.get("over_hard_cap_by_bps")
    out = [
        _block_header("Liquidity-Cascade", pill, styles),
        _kv_table([
            ("Stage", _safe(data.get("stage_label") or stage)),
            ("Liquiditaet", _bps_or_dash(data.get("liquidity_bps"))),
            ("Hard-Cap", _bps_or_dash(data.get("hard_cap_bps"))),
            ("Ueber Hard-Cap", _bps_or_dash(over)),
        ], styles),
    ]
    if warning_required or stage == "emergency":
        out.append(Spacer(1, 2 * mm))
        out.append(_warning_box(
            "Liquidity-Cascade-Warnung",
            "Emergency-Stage: Berater soll Risikoprofil, Zielstruktur und "
            "Liquiditaetsbedarf im Beratungsgespraech dokumentiert pruefen.",
            styles,
        ))
    return [_panel(out, styles, accent=COLOR_STATUS_ROT if warning_required else COLOR_GOLD)]


def _engine_configuration_block(data: dict, styles) -> list:
    """Sprint C2 (2026-06-07): Engine-Configuration im Compliance-Audit-Block.

    Macht den Risiko-Engine-Konfigurations-Status fuer Berater/Auditoren
    sichtbar:
    - Importance Sampling aktiv? (mit Trigger-Grund)
    - Tax-Mode (median/binned/per_path)
    - Sub-Allocation-Aware?
    - Stochastic-Engine aktiv (vs House-Matrix-Fallback)?

    Damit kann ein FINMA-Pruefer auf einen Blick sehen, mit welchen
    Engine-Einstellungen das Mandat berechnet wurde.
    """
    is_active = bool(data.get("importance_sampling_active"))
    is_reason = str(data.get("importance_sampling_reason") or "")
    tax_mode = str(data.get("tax_mode") or "median")
    sub_alloc_aware = bool(data.get("sub_allocation_aware"))
    stochastic_mode = str(data.get("optimizer_mode") or "stochastic")

    if is_active:
        pill = _pill("IS aktiv", "#E5EEDF", "#4E6F58", styles)
    else:
        pill = _pill("IS inaktiv", "#F3F4F6", "#475569", styles)

    out = [
        _block_header("Risiko-Engine-Konfiguration", pill, styles),
        _kv_table([
            ("Optimizer-Modus", _safe(stochastic_mode)),
            ("Importance Sampling", "aktiv" if is_active else "inaktiv"),
            ("IS-Trigger", _safe(is_reason) if is_reason else "—"),
            ("Tax-Modus", _safe(tax_mode)),
            ("Sub-Allocation-Aware", "ja" if sub_alloc_aware else "nein"),
        ], styles),
    ]
    if is_active:
        out.append(Spacer(1, 2 * mm))
        out.append(_muted_note(
            "Achievability-Wahrscheinlichkeiten sind likelihood-ratio-gewichtet "
            "(Mean-Shift Importance Sampling, Glasserman 2004 Sec 4.6). "
            "Tail-Statistik (P5/P95) reduziert Varianz 5-50x gegenueber Standard-MC.",
            styles,
        ))
    return [_panel(out, styles, accent=COLOR_STATUS_GRUEN if is_active else COLOR_GOLD)]


def _collect_suitability_violations(data: dict) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    for item in data.get("logs_without_suitability") or []:
        issues.append({
            "type": "fehlender Check",
            "ref": _safe(item.get("id") or item.get("log_id")),
            "reason": _safe(item.get("reason")),
        })
    for item in data.get("freshness_issues") or []:
        issues.append({
            "type": "Freshness",
            "ref": _safe(item.get("log_id") or item.get("check_id")),
            "reason": _safe(item.get("reason")),
        })
    for item in data.get("result_issues") or []:
        issues.append({
            "type": "Resultat",
            "ref": _safe(item.get("log_id") or item.get("check_id")),
            "reason": _safe(item.get("reason") or item.get("result")),
        })
    return issues


def _block_header(title: str, pill: Table, styles) -> Table:
    page_width, _ = PAGE_SIZE
    inner_width = page_width - MARGIN_LEFT - MARGIN_RIGHT
    title_p = Paragraph(_escape(title), _style(styles["h3"], color=COLOR_INK))
    table = Table([[title_p, pill]], colWidths=[inner_width * 0.72, inner_width * 0.18])
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("ALIGN", (1, 0), (1, 0), "RIGHT"),
    ]))
    return table


def _metrics_row(rows: list, styles) -> Table:
    page_width, _ = PAGE_SIZE
    inner_width = page_width - MARGIN_LEFT - MARGIN_RIGHT
    table = Table(rows, colWidths=[inner_width * 0.225] * 4)
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    return table


def _metric(label: str, value: Any, styles) -> Table:
    label_p = Paragraph(_escape(label.upper()), _style(
        styles["micro"], color=COLOR_INK_SUBTLE, font=FONT_SANS_BOLD,
    ))
    value_p = Paragraph(_escape(_format_count(value)), _style(
        styles["body"], color=COLOR_INK, font=FONT_SANS_BOLD, size=13,
    ))
    table = Table([[label_p], [value_p]])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), COLOR_CANVAS_SUBTLE),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return table


def _issues_table(issues: list[dict[str, str]], styles, *, headers, empty_text: str) -> Table:
    if not issues:
        rows = [[Paragraph(_escape(empty_text), styles["caption"])]]
        return _table(rows, [1.0], styles)
    shown = issues[:5]
    rows = [[_th(headers[0], styles), _th(headers[1], styles), _th(headers[2], styles)]]
    for issue in shown:
        rows.append([
            _p(issue["type"], styles, bold=True),
            _p(issue["ref"], styles, mono=True),
            _p(issue["reason"], styles, muted=True),
        ])
    if len(issues) > len(shown):
        rows.append([
            _p(f"+{len(issues) - len(shown)} weitere", styles, bold=True),
            _p("", styles),
            _p("Weitere Befunde im Backend-Audit-Payload.", styles, muted=True),
        ])
    return _table(rows, [0.22, 0.24, 0.54], styles)


def _kv_table(items: list[tuple[str, str]], styles) -> Table:
    rows = []
    for label, value in items:
        rows.append([
            Paragraph(_escape(label), _style(
                styles["micro"], color=COLOR_INK_SUBTLE, font=FONT_SANS_BOLD,
            )),
            Paragraph(_escape(value), _style(styles["caption"], color=COLOR_INK)),
        ])
    return _table(rows, [0.26, 0.74], styles, header=False)


def _bullet_list(title: str, items: list[str], styles) -> Table:
    rows = [[Paragraph(_escape(title.upper()), _style(
        styles["micro"], color=COLOR_INK_SUBTLE, font=FONT_SANS_BOLD,
    ))]]
    if not items:
        rows.append([Paragraph("<i>Keine Eintraege.</i>", styles["caption"])])
    for item in items:
        rows.append([Paragraph(f"- {_escape(_safe(item))}", _style(
            styles["caption"], color=COLOR_INK_MUTED,
        ))])
    table = Table(rows)
    table.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 1),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
    ]))
    return table


def _table(rows: list, widths: list[float], styles, *, header: bool = True) -> Table:
    page_width, _ = PAGE_SIZE
    inner_width = page_width - MARGIN_LEFT - MARGIN_RIGHT
    table = Table(rows, colWidths=[inner_width * w * 0.92 for w in widths])
    commands = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LINEBELOW", (0, 0), (-1, -1), 0.2, COLOR_RULE),
    ]
    if header:
        commands.append(("LINEBELOW", (0, 0), (-1, 0), 0.4, COLOR_RULE))
    table.setStyle(TableStyle(commands))
    return table


def _panel(flowables: list, styles, *, accent) -> Table:
    inner = Table([[f] for f in flowables])
    inner.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), COLOR_CANVAS_SUBTLE),
        ("LINEBEFORE", (0, 0), (0, -1), 2.5, accent),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    return inner


def _warning_box(title: str, body: str, styles) -> Table:
    rows = [[
        Paragraph(_escape(title), _style(
            styles["caption"], color=COLOR_STATUS_ROT, font=FONT_SANS_BOLD,
        )),
    ], [
        Paragraph(_escape(body), _style(styles["caption"], color=COLOR_INK_MUTED)),
    ]]
    table = Table(rows)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), HexColor("#F0D9D9")),
        ("LINEBEFORE", (0, 0), (0, -1), 2.5, COLOR_STATUS_ROT),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return table


def _muted_note(text: str, styles) -> Table:
    table = Table([[Paragraph(_escape(text), _style(styles["caption"], color=COLOR_INK_SUBTLE))]])
    table.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    return table


def _compliance_pill(is_compliant: bool, styles) -> Table:
    return _pill(*(PILL_OK if is_compliant else PILL_BAD), styles=styles)


def _stage_pill(stage: str, warning_required: bool, styles) -> Table:
    if warning_required or stage == "emergency":
        return _pill("emergency", "#F0D9D9", "#9E4747", styles)
    if stage == "normal":
        return _pill("normal", "#E5EEDF", "#4E6F58", styles)
    if stage == "hard_cap":
        return _pill("hard-cap", "#F4EBD5", "#B59243", styles)
    return _pill(*PILL_PENDING, styles=styles)


def _pill(label: str, fill_hex: str, text_hex: str, styles) -> Table:
    table = Table([[Paragraph(
        _escape(label),
        _style(styles["micro"], color=HexColor(text_hex), font=FONT_SANS_BOLD),
    )]])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), HexColor(fill_hex)),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    return table


def _th(text: str, styles) -> Paragraph:
    return Paragraph(_escape(text), _style(
        styles["micro"], color=COLOR_INK_SUBTLE, font=FONT_SANS_BOLD,
    ))


def _p(text: str, styles, *, bold: bool = False, muted: bool = False, mono: bool = False) -> Paragraph:
    font = FONT_MONO if mono else (FONT_SANS_BOLD if bold else None)
    color = COLOR_INK_MUTED if muted else COLOR_INK
    return Paragraph(_escape(text), _style(styles["caption"], color=color, font=font))


def _hr() -> Table:
    page_width, _ = PAGE_SIZE
    inner_width = page_width - MARGIN_LEFT - MARGIN_RIGHT
    rule = Table([[""]], colWidths=[inner_width], rowHeights=[0.3])
    rule.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), COLOR_RULE),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
    ]))
    return rule


def _style(base, *, font: str | None = None, color=None, size: float | None = None) -> ParagraphStyle:
    return ParagraphStyle(
        f"{base.name}ComplianceVariant",
        parent=base,
        fontName=font or base.fontName,
        textColor=color or base.textColor,
        fontSize=size or base.fontSize,
        leading=base.leading,
    )


def _format_count(value: Any) -> str:
    try:
        return format_integer(int(value or 0))
    except (TypeError, ValueError):
        return "0"


def _bps_or_dash(value: Any) -> str:
    if value is None:
        return "-"
    try:
        return format_bps_as_pct(int(value), decimals=1)
    except (TypeError, ValueError):
        return "-"


def _seed_paths(run: dict) -> str:
    seed = run.get("seed")
    n_paths = run.get("n_paths")
    parts = []
    if seed is not None:
        parts.append(f"Seed {seed}")
    if n_paths is not None:
        parts.append(f"{format_integer(int(n_paths))} Pfade")
    return " / ".join(parts) if parts else "-"


def _safe(value: Any) -> str:
    if value is None:
        return "-"
    text = str(value).strip()
    return text or "-"


def _escape(text: Any) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
