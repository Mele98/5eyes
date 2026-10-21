"""Plausibilitaetspruefung Risikofaehigkeit in Advisory-Report und Strategie-PDF.

RISK-CAPACITY-REPORT-001 (Folge zu RISK-CAPACITY-PLAUSIBILITY-001).

Die Pruefung selbst lebt in ``services/risk_capacity_plausibility.py`` und
wird hier NICHT veraendert. Dieses Modul liest nur die stabile Schnittstelle
des Pruefergebnisses -- ``status``, ``reason_code``, ``findings[].check`` und
``not_evaluable[].check`` -- und leitet daraus ab:

* einen kompakten, betragsfreien Auszug fuer den Advisory-Report-Payload
  (``suitability_summary.risk_capacity_plausibility``), und
* einen neutralen Beraterhinweis fuer die PDFs (Advisory-Report, Strategie).

Spaetere Felder werden nie vorausgesetzt: ``verification_code`` (Coverage-
Attestation, PR #664) wird optional durchgereicht; ``resolution_actions``
bewusst NICHT, weil deren Fallback freie Begruendungstexte enthalten kann
(Report-Payload bleibt betragsfrei; die Schritte zeigt die Berater-Ansicht
direkt aus dem Endpoint).

Bewusst ohne Betraege (keine Rappen-/CHF-Werte aus ``data_basis`` oder den
Befund-Texten) und ohne Aussage ueber den Kunden: der Hinweis dokumentiert
nur, dass die Fragebogen-Angaben gegen die erfassten Finanzdaten nicht
(vollstaendig) aufgehen und das Profil dadurch NICHT automatisch geaendert
wurde. Status ``consistent`` und ``not_evaluable`` erzeugen keinen PDF-Hinweis.
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
NOTE_STATUSES = (STATUS_PARTIAL, STATUS_INCONSISTENT)

PDF_NOTE_PREFIX = "Plausibilitätsprüfung Risikofähigkeit (Beraterhinweis): "
PDF_NOTE_SUFFIX = " Das Risikoprofil wurde dadurch nicht automatisch verändert."


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
    """Neutraler, betragsfreier Beraterhinweis fuer partial/inconsistent."""
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


def evaluate_for_assessment(db, mandate, assessment) -> dict | None:
    """Pruefung gegen ein bestimmtes Assessment; None ohne Assessment.

    Hinweis-Layer: ein Fehler darf weder Report noch PDF verhindern
    (``evaluate_mandate_safely`` faengt bereits; hier zusaetzlich der Import).
    """
    if assessment is None:
        return None
    try:
        from services import risk_capacity_plausibility as rcp

        return rcp.evaluate_mandate_safely(db, mandate, assessment)
    except Exception:  # noqa: BLE001 -- Hinweis-Layer
        logger.exception(
            "Risk-capacity plausibility (report) failed for mandate %s",
            getattr(mandate, "id", "?"),
        )
        return None


__all__ = [
    "KNOWN_STATUSES",
    "NOTE_STATUSES",
    "PDF_NOTE_PREFIX",
    "advisor_report_note",
    "compact_view",
    "evaluate_for_assessment",
]
