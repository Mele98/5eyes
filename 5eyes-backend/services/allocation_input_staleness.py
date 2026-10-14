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

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

_UNSET: Any = object()


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
    if not str(getattr(ta, "input_snapshot_hash", None) or "").strip():
        return False

    from models.allocation import CapitalMarketAssumption, OptimizerPolicy
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
            cma = (
                db.query(CapitalMarketAssumption)
                .filter(
                    CapitalMarketAssumption.is_current == 1,
                    CapitalMarketAssumption.deleted_at.is_(None),
                )
                .first()
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
