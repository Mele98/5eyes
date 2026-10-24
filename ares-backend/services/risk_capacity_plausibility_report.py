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

# Bindung/Availability (Closure-Review PR #677, RISK-CAPACITY-PLAUSIBILITY-001):
# jeder publizierte Status nennt das bewertete Risikoprofil; fehlt das aktuelle
# Profil oder passt die Identitaet nicht, ist das ein sichtbarer Zustand.
AVAILABILITY_EVALUATED = "evaluated"
AVAILABILITY_MISSING_INPUT = "missing_input"
AVAILABILITY_UNAVAILABLE = "unavailable"
AVAILABILITY_INTEGRITY_MISMATCH = "integrity_mismatch"
KNOWN_AVAILABILITIES = (
    AVAILABILITY_EVALUATED, AVAILABILITY_MISSING_INPUT,
    AVAILABILITY_UNAVAILABLE, AVAILABILITY_INTEGRITY_MISMATCH,
)
REASON_NO_CURRENT_RISK_ASSESSMENT = "NO_CURRENT_RISK_ASSESSMENT"
REASON_ASSESSMENT_BINDING_MISMATCH = "RISK_ASSESSMENT_BINDING_MISMATCH"
# Der Block ist eine Live-Pruefung gegen das aktuelle Risikoprofil, nicht
# Teil des (ggf. aelteren) SuitabilityChecks, in dessen Summary er steht.
EVALUATION_BASIS = "live_current_assessment"

NO_ASSESSMENT_NOTE = (
    PDF_NOTE_PREFIX
    + "Kein aktuelles Risikoprofil vorhanden – Risikofähigkeit nicht prüfbar, "
    "Risikoprofil erfassen."
    + PDF_NOTE_SUFFIX
)
BINDING_MISMATCH_NOTE = (
    PDF_NOTE_PREFIX
    + "Prüfergebnis ist keinem aktuellen Risikoprofil eindeutig zuordenbar – "
    "nicht als geprüft werten, Prüfung erneut ausführen."
    + PDF_NOTE_SUFFIX
)

REFERENCE_MISMATCH_NOTE = (
    PDF_NOTE_PREFIX
    + "Die Prüfung bezieht sich auf das aktuelle Risikoprofil, nicht auf das in "
    "der Eignungsprüfung referenzierte Profil."
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
        reason = result.get("reason_code")
        if reason == REASON_NO_CURRENT_RISK_ASSESSMENT:
            return NO_ASSESSMENT_NOTE
        if reason == REASON_ASSESSMENT_BINDING_MISMATCH:
            return BINDING_MISMATCH_NOTE
        return NOT_EVALUABLE_NOTE
    return ""


def _assessment_id(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _binding_mismatch(assessment_id: str | None) -> dict:
    return {
        "status": STATUS_NOT_EVALUABLE,
        "reason_code": REASON_ASSESSMENT_BINDING_MISMATCH,
        "availability": AVAILABILITY_INTEGRITY_MISMATCH,
        "risk_assessment_id": assessment_id,
        "findings": [],
        "not_evaluable": [{"check": "ALL"}],
    }


def _availability(result: dict, status: str) -> str:
    declared = result.get("availability")
    if declared in KNOWN_AVAILABILITIES:
        return declared
    if status == STATUS_NOT_EVALUABLE:
        return AVAILABILITY_UNAVAILABLE
    return AVAILABILITY_EVALUATED


def compact_view(result: dict | None) -> dict | None:
    """Betragsfreier Auszug fuer den Report-Payload (stabile Felder)."""
    if not isinstance(result, dict):
        return None
    status = result.get("status")
    if status not in KNOWN_STATUSES:
        # Unbekannter Status: nie als "konsistent" ausgeben.
        status = STATUS_NOT_EVALUABLE
    assessment_id = _assessment_id(result.get("risk_assessment_id"))
    if status != STATUS_NOT_EVALUABLE and assessment_id is None:
        # Ein bewerteter Status ohne Profil-Identitaet ist nicht zuordenbar:
        # fail-closed statt eines Live-Status ohne Bindung.
        result = _binding_mismatch(None)
        status = STATUS_NOT_EVALUABLE
    return {
        "status": status,
        "reason_code": result.get("reason_code"),
        "availability": _availability(result, status),
        "risk_assessment_id": assessment_id,
        "evaluation_basis": EVALUATION_BASIS,
        "rules_version": result.get("version"),
        "evaluation_hash": result.get("evaluation_hash"),
        "finding_checks": _check_ids(result.get("findings")),
        "open_checks": _check_ids(result.get("not_evaluable")),
        "verification_code": result.get("verification_code"),
        "note": advisor_report_note({**result, "status": status}),
    }


def evaluate_for_assessment(
    db, mandate, assessment, *, preloaded_rows: dict | None = None,
) -> dict | None:
    """Pruefung gegen ein bestimmtes Assessment.

    Ohne Assessment: typisiertes ``not_evaluable`` mit
    ``availability=missing_input`` und ``NO_CURRENT_RISK_ASSESSMENT`` -- der
    fehlende Kerninput wird sichtbar, nicht zu einem leeren Feld. Traegt das
    Ergebnis eine andere (oder keine) Profil-Identitaet als das uebergebene
    Assessment, wird es als ``integrity_mismatch`` verworfen.

    ``preloaded_rows`` = {"cashflows": [...], "goals": [...]} aus dem
    Aggregator-Cache; sie werden nur fuer die Dauer dieses Aufrufs und nur
    fuer dieses Mandat hinterlegt (siehe
    ``risk_capacity_plausibility.PRELOADED_ROWS_KEY``).

    Hinweis-Layer: ein Fehler verhindert den Report nie und wird als
    ``not_evaluable`` sichtbar -- nie still als "konsistent" oder leer.
    """
    if assessment is None:
        return {
            "status": STATUS_NOT_EVALUABLE,
            "reason_code": REASON_NO_CURRENT_RISK_ASSESSMENT,
            "availability": AVAILABILITY_MISSING_INPUT,
            "risk_assessment_id": None,
            "findings": [],
            "not_evaluable": [{"check": "ALL"}],
        }
    expected_id = _assessment_id(getattr(assessment, "id", None))
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
            result = rcp.evaluate_mandate_safely(db, mandate, assessment)
        finally:
            if use_preloaded:
                info.pop(rcp.PRELOADED_ROWS_KEY, None)
    except Exception:  # noqa: BLE001 -- Hinweis-Layer
        logger.exception(
            "Risk-capacity plausibility (report) failed for mandate %s",
            getattr(mandate, "id", "?"),
        )
        return {"status": STATUS_NOT_EVALUABLE, "reason_code": None,
                "availability": AVAILABILITY_UNAVAILABLE,
                "risk_assessment_id": expected_id,
                "findings": [], "not_evaluable": [{"check": "ALL"}]}
    if not isinstance(result, dict):
        return _binding_mismatch(expected_id)
    evaluated_id = _assessment_id(result.get("risk_assessment_id"))
    if result.get("status") == STATUS_NOT_EVALUABLE and evaluated_id is None:
        # Evaluator-Fehlerpfad ohne eigene Bindung: sichtbar nicht pruefbar,
        # dem angefragten Profil zugeordnet, nie als Live-Status.
        return {**result, "risk_assessment_id": expected_id,
                "availability": AVAILABILITY_UNAVAILABLE}
    if evaluated_id != expected_id:
        return _binding_mismatch(expected_id)
    return result


def bind_to_suitability_reference(block: dict | None, reference_id: Any) -> dict | None:
    """Kennzeichnet, ob der Live-Block dasselbe Profil bewertet wie die
    Suitability-Referenz (True), ein anderes (False) oder ob eine Seite fehlt
    (None). Liefert eine Kopie; der Cache-Eintrag bleibt unveraendert."""
    if not isinstance(block, dict):
        return block
    reference = _assessment_id(reference_id)
    evaluated = _assessment_id(block.get("risk_assessment_id"))
    match = None if reference is None or evaluated is None else reference == evaluated
    return {**block, "suitability_reference_match": match}


__all__ = [
    "AVAILABILITY_EVALUATED",
    "AVAILABILITY_INTEGRITY_MISMATCH",
    "AVAILABILITY_MISSING_INPUT",
    "AVAILABILITY_UNAVAILABLE",
    "BINDING_MISMATCH_NOTE",
    "EVALUATION_BASIS",
    "KNOWN_AVAILABILITIES",
    "KNOWN_STATUSES",
    "NOTE_STATUSES",
    "NOT_EVALUABLE_NOTE",
    "NO_ASSESSMENT_NOTE",
    "PDF_NOTE_PREFIX",
    "REASON_ASSESSMENT_BINDING_MISMATCH",
    "REASON_NO_CURRENT_RISK_ASSESSMENT",
    "REFERENCE_MISMATCH_NOTE",
    "advisor_report_note",
    "bind_to_suitability_reference",
    "compact_view",
    "evaluate_for_assessment",
]
