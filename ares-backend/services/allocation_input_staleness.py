"""ALLOCATION-INPUT-STALENESS-001: geteilte "Inputs veraltet"-Pruefung.

Payload (409), Finalisierung und Strategie-PDF lehnen eine Soll-Allokation
bereits ab, sobald ihr gespeicherter ``input_snapshot_hash`` nicht mehr zu
den Live-Inputs (Vermoegen, Cashflows, Ziele, Zufluesse, Projektions-
kontext) passt -- ``StaleAllocationInputError`` aus
``services.portfolio_engine.build_target_payload_from_allocation``.
Depot-Check und Beratungsreport prueften dagegen nur die Risikoprofil-
Identitaet (``target_allocation_predates_current_assessment``) und zeigten
die veraltete Allokation kommentarlos weiter.

Dieser Helper erfindet KEINE eigene Hash-Herleitung: er ruft exakt den
Payload-Pfad auf (``input_snapshot_check_only=True`` steigt direkt nach der
Hash-Pruefung aus, ohne Analyse/Simulation). Damit koennen die Oberflaechen
nie unterschiedlich urteilen.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import inspect as sa_inspect
from sqlalchemy import text
from sqlalchemy.orm import Session

from core.reason_codes import ReasonCode

logger = logging.getLogger(__name__)

_UNSET: Any = object()
# Gleicher Verbindungs-Merker wie models/snapshots.py::freshness_tables_present.
_FRESHNESS_TABLES_KEY = "ares_ccx_p2_tables_present"


def advisory_envelope_stale_reason(db: Session, mandate: Any, ta: Any) -> ReasonCode | None:
    """CCX-P2 (Vertrag 2026-11-13 §5): Frische des versiegelten
    Beratungsentscheids, der genau diese Soll-Allokation bindet.

    ``CCX_INPUT_STALE`` -- der Entscheid ist durch eine Mutation einer
    Abhaengigkeit (Ziele, Cashflows, Vermoegen, Risikoprofil, ESG-Praeferenz,
    CMA/Policy, Benchmark, Restriktionen, Mandatsdaten) invalidiert
    (``AdvisoryInvalidationEvent`` mit ``invalidation_sequence``,
    ``optimistic_version`` des Envelopes erhoeht; Kanten
    ``AdvisoryDependencyEdge`` mit ``dependency_hash``).
    ``CCX_FRESHNESS_UNKNOWN`` -- Bestand ohne Kanten (unknown != fresh).
    ``None`` -- kein versiegelter Entscheid bindet diese Allokation oder er ist
    FRESH. Reine Lesung (keine Fachwirkung); die Oberflaechen zeigen den
    Serverstatus ueber den bestehenden Veraltet-Hinweis an."""
    if ta is None or mandate is None or not getattr(ta, "id", None):
        return None
    connection = db.connection()
    if not connection.info.get(_FRESHNESS_TABLES_KEY):
        if not sa_inspect(connection).has_table("advisory_invalidation_events"):
            return None  # ohne Envelope-Schema gibt es keinen Entscheid
    row = db.execute(text(
        "SELECT e.freshness_status FROM advisory_decision_envelopes e "
        "JOIN advisory_envelope_bindings b ON b.envelope_id = e.id AND b.tenant_id = e.tenant_id "
        "WHERE e.mandate_id = :mandate_id AND e.status = 'SEALED' "
        "AND b.binding_kind = 'target_allocation' AND b.object_id = :ta_id"
    ), {"mandate_id": str(mandate.id), "ta_id": str(ta.id)}).first()
    if row is None or row[0] == "FRESH":
        return None
    if row[0] == "STALE":
        return ReasonCode.CCX_INPUT_STALE
    return ReasonCode.CCX_FRESHNESS_UNKNOWN


def allocation_inputs_stale(
    db: Session,
    mandate: Any,
    ta: Any,
    *,
    assessment: Any = _UNSET,
) -> bool:
    """True genau dann, wenn der Payload-Pfad fuer ``ta`` mit
    ``StaleAllocationInputError`` ablehnen wuerde.

    - Alt-Allokationen ohne ``input_snapshot_hash`` bleiben unmarkiert
      (identisch zur Rueckwaertskompat-Regel des Payload-Pfads und von
      ``target_allocation_predates_current_assessment``) -- ohne jede Query.
    - Andere Integritaetsfehler (fehlende Policy/CMA, ungueltiges
      Risikoprofil, korrupte Inputs) sind NICHT "Inputs geaendert"; sie
      werden von den blockierenden Pfaden (Payload/Finalisierung/PDF)
      gemeldet und hier nur geloggt (return False).
    - ``assessment`` kann vom Aufrufer vorab aufgeloest uebergeben werden,
      um eine doppelte Query zu sparen.
    """
    if ta is None or mandate is None:
        return False
    # CCX-P2: ein invalidierter versiegelter Entscheid, der genau diese
    # Allokation bindet, ist "Inputs veraltet" -- auch fuer Alt-Allokationen
    # ohne input_snapshot_hash (Serverstatus, keine neue Herleitung).
    if advisory_envelope_stale_reason(db, mandate, ta) == ReasonCode.CCX_INPUT_STALE:
        return True
    if not str(getattr(ta, "input_snapshot_hash", None) or "").strip():
        return False

    from models.allocation import OptimizerPolicy
    from services.portfolio_engine import (
        StaleAllocationInputError,
        _current_risk_assessment_or_none,
        build_target_payload_from_allocation,
    )

    try:
        if assessment is _UNSET:
            assessment = _current_risk_assessment_or_none(db, mandate.id)
        if assessment is None:
            return False
        policy_id = str(getattr(ta, "policy_id", "") or "").strip()
        policy = (
            db.query(OptimizerPolicy).filter(OptimizerPolicy.id == policy_id).first()
            if policy_id
            else None
        )
        if policy is None:
            return False
        # Wie im Payload-Pfad: ein CMA-Snapshot-Anker der Allokation hat
        # Vorrang (build_target_payload_from_allocation laedt ihn selbst);
        # nur Alt-Allokationen ohne Anker rechnen mit der aktuellen CMA.
        cma = None
        if not str(getattr(ta, "capital_market_assumptions_id", "") or "").strip():
            # CMA-EFFECTIVE-DATE-001: dieselbe CMA wie die Engine.
            from services.jurisdiction.resolve import (
                resolve_effective_cma_or_none,
                resolve_mandate_jurisdiction,
            )
            cma = resolve_effective_cma_or_none(
                db, resolve_mandate_jurisdiction(mandate), getattr(mandate, "tenant_id", None),
            )
            if cma is None:
                return False
        build_target_payload_from_allocation(
            db=db,
            mandate=mandate,
            allocation=ta,
            policy=policy,
            cma=cma,
            assessment=assessment,
            preferences=None,
            input_snapshot_check_only=True,
        )
    except StaleAllocationInputError:
        return True
    except ValueError as exc:
        logger.warning(
            "allocation_inputs_stale: Anker-Pruefung fuer Allokation %s nicht "
            "moeglich (%s); keine Input-Staleness-Aussage.",
            getattr(ta, "id", None),
            exc,
        )
        return False
    return False
