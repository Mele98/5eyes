"""Sprint U-22 (2026-06-03): Mandate-Lock-Status Audit.

Hintergrund
-----------
Roadmap-Befund: "Alte Mandate Read-Only silent bei Risikobudget-
Verletzung". Es gab keinen klaren Read-Only-Indikator pro Mandat —
ein Berater konnte versuchen zu editieren ohne dass das System
proaktiv das Lock-Status zurueckmeldet.

Audit-Service der pro Mandat zusammenfasst:
- Soft-Delete (deleted_at gesetzt)
- Geschlossen (closed_at gesetzt)
- Status != 'Aktiv'
- Letzter Optimizer-Run divergiert (Risikobudget-Verletzung)

Read-only Audit-Layer, kein Breaking-Change im Edit-Pfad. Aggregator
+ Sub-App + PDF koennen den Lock-Hinweis als UI-Banner rendern.
"""
from __future__ import annotations

from typing import Any, Optional

from sqlalchemy.orm import Session


# Reason-Codes (stabile API fuer Frontend).
REASON_DELETED = "soft_deleted"
REASON_CLOSED = "mandate_closed"
REASON_INACTIVE_STATUS = "status_not_aktiv"
REASON_OPTIMIZER_DIVERGED = "optimizer_diverged"
REASON_RISK_BUDGET_VIOLATED = "risk_budget_violated"

# Status-Werte die als 'aktiv' gelten (editierbar).
ACTIVE_STATUSES = {"Aktiv", "Entwurf"}

# Berater-tauglich Texte pro Reason-Code.
REASON_LABELS = {
    REASON_DELETED:
        "Mandat ist soft-deleted (deleted_at gesetzt) — nicht editierbar.",
    REASON_CLOSED:
        "Mandat ist geschlossen (closed_at gesetzt). Editierungen "
        "muessen ueber Reaktivierung erfolgen.",
    REASON_INACTIVE_STATUS:
        "Mandat-Status ist nicht 'Aktiv'. Pruefen ob Wiederaktivierung "
        "erforderlich.",
    REASON_OPTIMIZER_DIVERGED:
        "Letzter Optimizer-Run divergierte (keine konvergente "
        "Allokation). Risikobudget oder Constraints pruefen.",
    REASON_RISK_BUDGET_VIOLATED:
        "Risky-Allokation verletzt das konfigurierte Risk-Budget. "
        "Kunde sollte hingewiesen werden bevor weitere Empfehlungen "
        "kommen.",
}


def _bool_or_none(value: Any) -> bool:
    if value in (None, "", 0, "0", False):
        return False
    return True


def audit_mandate_editability(
    db: Session, mandate: Any,
) -> dict[str, Any]:
    """Audit-Befund pro Mandat — non-breaking read-only.

    Output-Schema
    -------------
    {
      'is_editable': bool,                  # True wenn keine Lock-Reasons
      'lock_reasons': [str, ...],           # Code-Liste
      'lock_reason_labels': {code: str},    # Berater-Texte
      'mandate_status': str | None,         # Status-Snapshot
      'latest_optimizer_status': str | None,
      'fidleg_basis': 'Art. 16 / Art. 11 FIDLEG',
    }

    Robust gegen Schema-Mismatch -> degraded (is_editable=True).
    """
    lock_reasons: list[str] = []
    status = getattr(mandate, "status", None)
    deleted_at = getattr(mandate, "deleted_at", None)
    closed_at = getattr(mandate, "closed_at", None)

    if _bool_or_none(deleted_at):
        lock_reasons.append(REASON_DELETED)
    if _bool_or_none(closed_at):
        lock_reasons.append(REASON_CLOSED)
    if status and status not in ACTIVE_STATUSES:
        lock_reasons.append(REASON_INACTIVE_STATUS)

    latest_optimizer_status: Optional[str] = None
    try:
        from models.allocation import OptimizerRun
        latest = (
            db.query(OptimizerRun)
            .filter(OptimizerRun.mandate_id == mandate.id)
            .filter(OptimizerRun.role == "active")
            .order_by(OptimizerRun.run_at.desc())
            .first()
        )
        if latest is not None:
            latest_optimizer_status = getattr(latest, "status", None)
            if latest_optimizer_status in {"diverged", "diverged_infeasible"}:
                lock_reasons.append(REASON_OPTIMIZER_DIVERGED)
    except Exception:  # noqa: BLE001
        latest_optimizer_status = None

    try:
        from models.allocation import TargetAllocation
        active_ta = (
            db.query(TargetAllocation)
            .filter(TargetAllocation.mandate_id == mandate.id)
            .filter(TargetAllocation.is_current == 1)
            .filter(TargetAllocation.deleted_at.is_(None))
            .first()
        )
        if active_ta is not None:
            risky = getattr(active_ta, "risky_fraction_bps_at_generation", None)
            budget = getattr(active_ta, "risk_budget_bps_at_generation", None)
            if risky is not None and budget is not None:
                try:
                    if int(risky) > int(budget):
                        lock_reasons.append(REASON_RISK_BUDGET_VIOLATED)
                except (TypeError, ValueError):
                    pass
    except Exception:  # noqa: BLE001
        pass

    # Dedupe (defensiv falls Quellen sich ueberlappen).
    seen = set()
    deduped = []
    for r in lock_reasons:
        if r not in seen:
            deduped.append(r)
            seen.add(r)

    return {
        "is_editable": len(deduped) == 0,
        "lock_reasons": deduped,
        "lock_reason_labels": {r: REASON_LABELS[r] for r in deduped},
        "mandate_status": status,
        "latest_optimizer_status": latest_optimizer_status,
        "fidleg_basis": "Art. 16 / Art. 11 FIDLEG",
    }
