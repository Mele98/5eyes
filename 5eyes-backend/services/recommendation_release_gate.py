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

    Wirft ``HTTPException(409, detail={reason_code, message, channel})``;
    neben dem Risikobudget auch ``CMA_ADR12A_HOLD`` (KGV-aktive CMA).
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
    # CMA-001 / ADR-12a-Release-Hold: keine Freigabe, solange die CMA der
    # Allokation eine ungeklaerte KGV-Bewertungsanpassung traegt
    # (services/cma_valuation_hold.py).
    from services.cma_valuation_hold import assert_allocation_cma_without_adr12a_hold

    assert_allocation_cma_without_adr12a_hold(
        db,
        allocation,
        channel=channel,
        channel_label=_CHANNEL_LABELS.get(channel, "Freigabe nicht möglich"),
    )
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


# ---------------------------------------------------------------------------
# Risikoprofil-Signoff (CIO-Entscheid 2026-10-24)
# ---------------------------------------------------------------------------
#
# Ein Signoff im Zustand ``integrity_mismatch`` (Zeile oder fachliche Bindung
# passt nicht mehr zum Assessment, services/risk_profile_signoff.py::
# verify_signoff_binding) wurde in Kundendokumenten bisher nur als "nicht
# gueltig" ausgewiesen. Jetzt sperren dieselben Freigabekanaele fail-closed.
# Legacy-Zustaende (unsigniert, Altsignatur ohne Signoff, "neue Signatur
# erforderlich") bleiben wie bisher -- sie behaupten keine gueltige Signatur.
# Der interne Advisory-Report zeigt den Zustand weiter an; die
# Kundenportal-Sicht desselben Reports ist gesperrt (neutrale Meldung).

RISK_PROFILE_SIGNOFF_MISMATCH = "RISK_PROFILE_SIGNOFF_MISMATCH"

CHANNEL_CLIENT_PDF = "client_pdf"
_CHANNEL_LABELS[CHANNEL_CLIENT_PDF] = "Das Kundendokument kann nicht erstellt werden"
CHANNEL_CLIENT_PORTAL = "client_portal"
_CHANNEL_LABELS[CHANNEL_CLIENT_PORTAL] = "Der Kundenportal-Bericht kann nicht angezeigt werden"

# Neutrale Kundenmeldung (Kundenportal): keine internen Details, der
# Reason-Code steht nur in Log und Audit.
CLIENT_PORTAL_UNAVAILABLE_MESSAGE = (
    "Ihr Bericht wird derzeit aktualisiert – bitte wenden Sie sich an Ihre "
    "Beraterin oder Ihren Berater."
)

# Kundenrelevante bzw. kundensignierbare Dokumenttypen, die das Risikoprofil
# des Kunden tragen und deshalb eine gueltige Signoff-Bindung voraussetzen.
SIGNOFF_BOUND_DOCUMENT_TYPES = frozenset({
    "Anlagestrategie",
    "Risikoprofilierung",
    "Beratungsprotokoll",
    "Eignungsprüfung",
    "Override-Zustimmung",
    "Kostenausweis",
    "Anlagerezept",
})

_SIGNOFF_MISMATCH_MESSAGE = (
    "Die Risikoprofil-Signatur passt nicht mehr zum gespeicherten Profil – "
    "Profil prüfen und neu signieren."
)


def assert_risk_signoff_release_eligible(
    db: Session,
    mandate: Any,
    *,
    channel: str,
) -> None:
    """409, wenn der Signoff des aktuellen Risikoprofils ``integrity_mismatch``
    ist -- dieselbe Pruefung wie API/PDF-Anzeige (``signoff_state`` +
    ``resolve_signoff_binding``), VOR jeder Wirkung des Kanals.

    Ohne aktuelles Risikoprofil oder ohne gebundene Signatur passiert nichts
    (unveraendertes Verhalten; andere Gates sind dafuer zustaendig)."""
    from services.portfolio_engine import _current_risk_assessment_or_none
    from services.risk_profile_signoff import (
        STATUS_SIGNED,
        resolve_signoff_binding,
        signoff_state,
    )

    try:
        assessment = _current_risk_assessment_or_none(db, mandate.id)
    except ValueError:
        # Mehrdeutiger Anker: eigener Fehlerpfad der Kanaele, hier nichts
        # zusaetzlich zu belegen.
        return
    if assessment is None or signoff_state(assessment) != STATUS_SIGNED:
        return
    binding = resolve_signoff_binding(db, assessment)
    if binding is not None and binding.verified:
        return
    mismatches = list(binding.mismatches) if binding is not None else ["signoff_missing"]
    if binding is not None and not binding.row_verified and "signoff_row" not in mismatches:
        mismatches.append("signoff_row")
    raise HTTPException(
        status_code=409,
        detail={
            "reason_code": RISK_PROFILE_SIGNOFF_MISMATCH,
            "message": (
                f"{_CHANNEL_LABELS.get(channel, 'Freigabe nicht möglich')}. "
                f"{_SIGNOFF_MISMATCH_MESSAGE}"
            ),
            "channel": channel,
            "risk_assessment_id": getattr(assessment, "id", None),
            "signoff_id": getattr(assessment, "signoff_id", None),
            "integrity_mismatches": mismatches,
        },
    )


def assert_current_allocation_without_adr12a_hold(
    db: Session,
    mandate: Any,
    *,
    channel: str,
) -> None:
    """CMA-001 / ADR-12a-Release-Hold fuer Kundenkanaele ohne Risikobudget-
    Gate (Kunden-PDFs mit Strategie/Positionen, Kundenportal): 409
    ``CMA_ADR12A_HOLD``, wenn die CMA der aktuellen Soll-Allokation eine
    ungeklaerte KGV-Bewertungsanpassung traegt. Ohne aktuelle Allokation
    wird keine Strategie publiziert -- nichts zu sperren."""
    from services.cma_valuation_hold import assert_allocation_cma_without_adr12a_hold

    allocation = _current_allocation(db, mandate)
    if allocation is None:
        return
    assert_allocation_cma_without_adr12a_hold(
        db,
        allocation,
        channel=channel,
        channel_label=_CHANNEL_LABELS.get(channel, "Freigabe nicht möglich"),
    )
