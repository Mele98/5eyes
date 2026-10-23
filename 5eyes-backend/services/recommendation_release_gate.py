"""Zentrales Risk-Budget-Freigabe-Gate (RISK-BUDGET-FINALIZATION-001, Rest).

Vorher pruefte NUR die Finalisierung (routers/review.py::
_validate_recommendation_for_finalization) die Risikobudget-Treue der
verankerten Soll-Allokation -- und selbst dort war ein fehlender
Ist-Risikoanteil nur eine Warnung. Die staerkeren Freigabekanaele
(Advisory-Report-PDF, Signatur eines Empfehlungsdokuments, Weiterleitung
an das Asset Management) riefen die Pruefung gar nicht auf: eine
Allokation, die das Risikobudget des Kunden verletzt oder deren
Budget-Treue nicht belegbar ist, konnte damit als Kunden-PDF exportiert,
unterzeichnet oder zur Ausfuehrung weitergeleitet werden.

Diese Datei ist die EINE Quelle der Pruefung:

- ``risk_budget_release_findings(allocation)`` -- reine Pruefung der
  typisierten Spalten ``risk_budget_bps_at_generation`` und
  ``risky_fraction_bps_at_generation`` der verankerten Allokation. Die
  Finalisierung nutzt sie fuer ihre Fehlerliste (422 wie bisher).
- ``assert_recommendation_release_eligible(...)`` -- das Gate fuer die
  Freigabekanaele. Wirft ``HTTPException(409)`` mit stabilem Reason-Code,
  BEVOR der Kanal irgendeine Wirkung hat (kein PDF, keine Signatur, kein
  Handoff).

Fail-closed: fehlt der Nachweis (Budget oder Ist-Risikoanteil fehlt bzw.
ist nicht lesbar), wird blockiert -- "nicht belegbar" ist nicht
"eingehalten". Heilmittel ist immer dasselbe: Allokation neu generieren
(liefert den Nachweis) bzw. Risikoprofil/Bausteine anpassen (bei
Verletzung).
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

RISK_BUDGET_EVIDENCE_MISSING = "RISK_BUDGET_EVIDENCE_MISSING"
RISK_BUDGET_VIOLATED = "RISK_BUDGET_VIOLATED"
RELEASE_ALLOCATION_MISSING = "RELEASE_ALLOCATION_MISSING"

CHANNEL_ADVISORY_PDF = "advisory_pdf"
CHANNEL_SIGNATURE = "signature"
CHANNEL_HANDOFF = "handoff"

_CHANNEL_LABELS = {
    CHANNEL_ADVISORY_PDF: "Der Advisory-Report kann nicht exportiert werden",
    CHANNEL_SIGNATURE: "Das Dokument kann nicht unterzeichnet werden",
    CHANNEL_HANDOFF: "Die Handelsliste kann nicht weitergeleitet werden",
}

# Dokumenttypen, die die Anlageempfehlung/Soll-Allokation verkoerpern. Ein
# Beratungsvertrag, eine Risikoprofilierung oder "Sonstiges" haengen nicht
# an der Allokation und bleiben unabhaengig vom Risikobudget signierbar.
RECOMMENDATION_DOCUMENT_TYPES = frozenset({
    "Anlagestrategie",
    "Anlagerezept",
    "Beratungsprotokoll",
    "Eignungsprüfung",
    "Override-Zustimmung",
    "Kostenausweis",
})

_EVIDENCE_MISSING_MESSAGE = (
    "Die Einhaltung des Risikobudgets ist für die aktuelle Soll-Allokation "
    "nicht nachgewiesen (Risikobudget oder Ist-Risikoanteil fehlt bzw. ist "
    "nicht lesbar). Bitte die Allokation neu generieren, damit der Nachweis "
    "vorliegt."
)


def risk_budget_release_findings(allocation: Any) -> list[tuple[str, str]]:
    """``[(reason_code, message)]`` fuer die Risikobudget-Treue der Allokation.

    Leere Liste = Nachweis vorhanden und Budget eingehalten.
    """
    budget = getattr(allocation, "risk_budget_bps_at_generation", None)
    realized = getattr(allocation, "risky_fraction_bps_at_generation", None)
    if budget is None or realized is None:
        return [(RISK_BUDGET_EVIDENCE_MISSING, _EVIDENCE_MISSING_MESSAGE)]
    try:
        budget_int = int(budget)
        realized_int = int(realized)
    except (TypeError, ValueError):
        return [(RISK_BUDGET_EVIDENCE_MISSING, _EVIDENCE_MISSING_MESSAGE)]
    if realized_int > budget_int:
        # Zahlen in die Meldung: der Berater muss sehen, WIE weit er
        # darueber liegt, um Risikoprofil oder Bausteine als Stellschraube
        # zu waehlen.
        return [(
            RISK_BUDGET_VIOLATED,
            "Die Soll-Allokation verletzt das Risikobudget des "
            f"Risikoprofils: Ist-Risikoanteil {realized_int / 100:.2f} % "
            f"gegen Budget {budget_int / 100:.2f} %. Risikoprofil oder "
            "Bausteine anpassen und die Allokation neu generieren.",
        )]
    return []


def risk_budget_release_errors(allocation: Any) -> list[str]:
    """Nur die Meldungen -- fuer die Fehlerliste der Finalisierung."""
    return [message for _code, message in risk_budget_release_findings(allocation)]


def _current_allocation(db: Session, mandate: Any) -> Any:
    from models.allocation import TargetAllocation

    return (
        db.query(TargetAllocation)
        .filter(
            TargetAllocation.mandate_id == mandate.id,
            TargetAllocation.is_current == 1,
            TargetAllocation.deleted_at.is_(None),
        )
        .first()
    )


def _run_allocation(db: Session, mandate: Any, run: Any) -> Any:
    from models.allocation import TargetAllocation

    if not getattr(run, "target_allocation_id", None):
        return None
    return (
        db.query(TargetAllocation)
        .filter(
            TargetAllocation.id == run.target_allocation_id,
            TargetAllocation.mandate_id == mandate.id,
            TargetAllocation.deleted_at.is_(None),
        )
        .first()
    )


def assert_recommendation_release_eligible(
    db: Session,
    mandate: Any,
    *,
    channel: str,
    run: Optional[Any] = None,
) -> None:
    """Zentrales Freigabe-Gate fuer PDF, Signatur und Handoff.

    Bezug:
    - mit ``run`` (Handoff): die im Run verankerte Allokation. Ein Run ohne
      gueltige Allokation ist nicht freigebbar (409).
    - ohne ``run`` (Advisory-PDF, Signatur): die aktuelle Soll-Allokation
      des Mandats -- genau die, die der Advisory-Report publiziert
      (services/advisory_report.py::_cached_current_ta). Existiert keine,
      wird keine Strategie publiziert und es gibt kein Risikobudget zu
      belegen.

    Wirft ``HTTPException(409, detail={reason_code, message, channel})``.
    """
    if run is not None:
        allocation = _run_allocation(db, mandate, run)
        if allocation is None:
            raise HTTPException(
                status_code=409,
                detail={
                    "reason_code": RELEASE_ALLOCATION_MISSING,
                    "message": (
                        f"{_CHANNEL_LABELS.get(channel, 'Freigabe nicht möglich')}: "
                        "die Empfehlung ist keiner gültigen Soll-Allokation "
                        "zugeordnet. Bitte die Allokation neu generieren."
                    ),
                    "channel": channel,
                },
            )
    else:
        allocation = _current_allocation(db, mandate)
        if allocation is None:
            return
    findings = risk_budget_release_findings(allocation)
    if not findings:
        return
    reason_code, message = findings[0]
    raise HTTPException(
        status_code=409,
        detail={
            "reason_code": reason_code,
            "message": (
                f"{_CHANNEL_LABELS.get(channel, 'Freigabe nicht möglich')}. "
                f"{message}"
            ),
            "channel": channel,
            "target_allocation_id": getattr(allocation, "id", None),
        },
    )
