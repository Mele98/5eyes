"""Plausibilitaetspruefung Risikofaehigkeit im internen Advisory-Report.

RISK-CAPACITY-REPORT-001 (Folge zu RISK-CAPACITY-PLAUSIBILITY-001).

Die Pruefregeln leben in ``services/risk_capacity_plausibility.py``. Dieses
Modul liest nur die stabile Schnittstelle des Pruefergebnisses -- ``status``,
``reason_code``, ``findings[].check`` und ``not_evaluable[].check`` -- und
leitet daraus ab:

* einen kompakten, betragsfreien Auszug fuer den Advisory-Report-Payload
  (``suitability_summary.risk_capacity_plausibility``), und
* einen neutralen Beraterhinweis fuer das interne Advisory-Report-PDF.

CIO-Entscheid 2026-10-21:
* NUR interner Berater-Report (und React-Berateransicht). Das vom Kunden
  unterzeichnete Anlagestrategie-PDF erhaelt bewusst KEINEN Hinweis --
  interne Hinweise gehoeren nicht in ein kundensigniertes Dokument.
* Auch ``not_evaluable`` erhaelt einen Hinweis: fehlende Daten bleiben nie
  stumm. Nur ``consistent`` erzeugt keinen Hinweis.
* Die Pruefung laeuft im Advisory-Report ueber den Aggregator-Call-Cache
  (keine zusaetzlichen Cashflow-/Ziel-Queries, test_aggregator_n1_baseline).

Spaetere Felder werden nie vorausgesetzt: ``verification_code`` (Coverage-
Attestation, PR #664) wird optional durchgereicht; ``resolution_actions``
bewusst NICHT, weil deren Fallback freie Begruendungstexte enthalten kann
(Report-Payload bleibt betragsfrei; die Schritte zeigt die Berater-Ansicht
direkt aus dem Endpoint).

Bewusst ohne Betraege (keine Rappen-/CHF-Werte aus ``data_basis`` oder den
Befund-Texten) und ohne Aussage ueber den Kunden.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

STATUS_CONSISTENT = "consistent"
STATUS_PARTIAL = "partial"
STATUS_INCONSISTENT = "inconsistent"
STATUS_NOT_EVALUABLE = "not_evaluable"
KNOWN_STATUSES = (
    STATUS_CONSISTENT, STATUS_PARTIAL, STATUS_INCONSISTENT, STATUS_NOT_EVALUABLE,
)
NOTE_STATUSES = (STATUS_PARTIAL, STATUS_INCONSISTENT, STATUS_NOT_EVALUABLE)

PDF_NOTE_PREFIX = "Plausibilitätsprüfung Risikofähigkeit (Beraterhinweis): "
PDF_NOTE_SUFFIX = " Das Risikoprofil wurde dadurch nicht automatisch verändert."
NOT_EVALUABLE_NOTE = (
    PDF_NOTE_PREFIX
    + "Risikofähigkeit mangels Daten nicht prüfbar – Finanzdaten erfassen."
    + PDF_NOTE_SUFFIX
)


def _short_labels() -> dict[str, str]:
    from services.risk_capacity_plausibility import CHECK_SHORT_LABELS

    return dict(CHECK_SHORT_LABELS)


def _check_ids(rows: Any) -> list[str]:
    ids: list[str] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        check = str(row.get("check") or "").strip()
        if check and check not in ids:
            ids.append(check)
    return ids


def _topics(check_ids: list[str]) -> str:
    labels = _short_labels()
    # Nur bekannte Pruef-IDs: ein Sammel-Eintrag wie "ALL" oder eine kuenftige
    # ID ohne Label erscheint nicht als Rohcode im PDF.
    return "; ".join(labels[c] for c in check_ids if c in labels)


def advisor_report_note(result: dict | None) -> str:
    """Neutraler, betragsfreier Beraterhinweis (alles ausser consistent)."""
    if not isinstance(result, dict):
        return ""
    status = result.get("status")
    if status == STATUS_INCONSISTENT:
        topics = _topics(_check_ids(result.get("findings")))
        return (
            PDF_NOTE_PREFIX
            + "Einzelne Angaben zur Risikofähigkeit weichen von den in der "
            "Beratung erfassten Finanzdaten ab"
            + (f" (betroffen: {topics})." if topics else ".")
            + PDF_NOTE_SUFFIX
        )
    if status == STATUS_PARTIAL:
        topics = _topics(_check_ids(result.get("not_evaluable")))
        return (
            PDF_NOTE_PREFIX
            + "Die Angaben zur Risikofähigkeit konnten mangels erfasster "
            "Finanzdaten noch nicht vollständig geprüft werden"
            + (f" (offen: {topics})." if topics else ".")
            + PDF_NOTE_SUFFIX
        )
    if status == STATUS_NOT_EVALUABLE:
        return NOT_EVALUABLE_NOTE
    return ""


def compact_view(result: dict | None) -> dict | None:
    """Betragsfreier Auszug fuer den Report-Payload (stabile Felder)."""
    if not isinstance(result, dict):
        return None
    status = result.get("status")
    if status not in KNOWN_STATUSES:
        # Unbekannter Status: nie als "konsistent" ausgeben.
        status = STATUS_NOT_EVALUABLE
    return {
        "status": status,
        "reason_code": result.get("reason_code"),
        "finding_checks": _check_ids(result.get("findings")),
        "open_checks": _check_ids(result.get("not_evaluable")),
        "verification_code": result.get("verification_code"),
        "note": advisor_report_note({**result, "status": status}),
    }


def evaluate_for_assessment(
    db, mandate, assessment, *, preloaded_rows: dict | None = None,
) -> dict | None:
    """Pruefung gegen ein bestimmtes Assessment; None ohne Assessment.

    ``preloaded_rows`` = {"cashflows": [...], "goals": [...]} aus dem
    Aggregator-Cache; sie werden nur fuer die Dauer dieses Aufrufs und nur
    fuer dieses Mandat hinterlegt (siehe
    ``risk_capacity_plausibility.PRELOADED_ROWS_KEY``).

    Hinweis-Layer: ein Fehler verhindert den Report nie und wird als
    ``not_evaluable`` sichtbar -- nie still als "konsistent" oder leer.
    """
    if assessment is None:
        return None
    try:
        from services import risk_capacity_plausibility as rcp

        info = getattr(db, "info", None)
        use_preloaded = preloaded_rows is not None and isinstance(info, dict)
        if use_preloaded:
            info[rcp.PRELOADED_ROWS_KEY] = {
                "mandate_id": getattr(mandate, "id", None),
                "client_id": getattr(mandate, "client_id", None),
                "cashflows": list(preloaded_rows.get("cashflows") or []),
                "goals": list(preloaded_rows.get("goals") or []),
            }
        try:
            return rcp.evaluate_mandate_safely(db, mandate, assessment)
        finally:
            if use_preloaded:
                info.pop(rcp.PRELOADED_ROWS_KEY, None)
    except Exception:  # noqa: BLE001 -- Hinweis-Layer
        logger.exception(
            "Risk-capacity plausibility (report) failed for mandate %s",
            getattr(mandate, "id", "?"),
        )
        return {"status": STATUS_NOT_EVALUABLE, "reason_code": None,
                "findings": [], "not_evaluable": [{"check": "ALL"}]}


__all__ = [
    "KNOWN_STATUSES",
    "NOTE_STATUSES",
    "NOT_EVALUABLE_NOTE",
    "PDF_NOTE_PREFIX",
    "advisor_report_note",
    "compact_view",
    "evaluate_for_assessment",
]
