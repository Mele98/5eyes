"""Sprint U-69 (2026-06-03): Recommendation-Run-Methodology Audit.

Hintergrund
-----------
OptimizerRun-Tabelle existiert seit Sprint U-P9+ und persistiert
methode/mode/status/seed/n_paths/iterations/reasoning. Im Berater-
und Mandate-UI fehlt aber ein Hinweis welcher Algorithmus den
aktuellen Run produziert hat (stochastic vs fallback_house_matrix,
konvergiert/divergiert, n_starts_attempted etc.).

Read-only Audit-Service der die letzten/aktiven OptimizerRun-Daten
zusammenfasst, damit Aggregator + Sub-App + PDF eine Methodology-
Box rendern koennen.

FINMA-Bezug
-----------
- Methode + Status sind Bestandteil der Berater-Empfehlungs-
  Dokumentation (FIDLEG Art. 16, "wie wurde die Empfehlung
  hergeleitet"). Pre-U-69 musste man die Tabelle direkt abfragen
  um diese Audit-Spur zu sehen.
"""
from __future__ import annotations

import json
from typing import Any, Optional

from sqlalchemy.orm import Session


# Status-Klassifikation fuer UI/Aggregator (Berater-tauglich).
STATUS_LABELS = {
    "converged":              "konvergiert",
    "converged_robustified":  "konvergiert (robustifiziert)",
    "diverged":               "divergiert",
    "diverged_infeasible":    "divergiert (Constraints unerfuellbar)",
    "fallback_house_matrix":  "Fallback HouseMatrix-Mid",
}

# Status-Codes die als "produktiv akzeptabel" gelten (FINMA-Hinweis: ok).
ACCEPTABLE_STATUSES = {"converged", "converged_robustified", "fallback_house_matrix"}


def _safe_json(value: Any) -> Any:
    if value in (None, "", b""):
        return None
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return None


def _label_for_status(status: Optional[str]) -> str:
    if not status:
        return "(kein Status)"
    return STATUS_LABELS.get(status, status)


def _is_acceptable(status: Optional[str]) -> bool:
    return bool(status) and status in ACCEPTABLE_STATUSES


def summarize_optimizer_run(run: Any) -> dict[str, Any]:
    """Wandelt eine OptimizerRun-Row in das Methodology-Schema."""
    status = getattr(run, "status", None)
    mode = getattr(run, "optimizer_mode", None)
    method = getattr(run, "method", None)
    constraint_violations = _safe_json(getattr(run, "constraint_violations_json", None))
    reasoning = _safe_json(getattr(run, "reasoning_json", None))

    return {
        "run_id": getattr(run, "id", None),
        "run_at": getattr(run, "run_at", None),
        "optimizer_mode": mode,
        "role": getattr(run, "role", None),
        "method": method,
        "status": status,
        "status_label": _label_for_status(status),
        "is_acceptable": _is_acceptable(status),
        "seed": getattr(run, "seed", None),
        "n_paths": getattr(run, "n_paths", None),
        "n_iterations": getattr(run, "n_iterations", None),
        "n_starts_attempted": getattr(run, "n_starts_attempted", None),
        "objective_value_milli": getattr(run, "objective_value_milli", None),
        "constraint_violations": constraint_violations or [],
        "reasoning": reasoning or [],
    }


def audit_recommendation_methodology(
    db: Session, mandate: Any,
) -> dict[str, Any]:
    """Audit der Recommendation-Methodology pro Mandat.

    Liefert die letzten OptimizerRun-Daten + die letzte aktive Rolle
    (`role='active'`) separat, damit Berater sieht ob die produktive
    Allokation aus Stochastic oder Fallback kommt.

    Output-Schema
    -------------
    {
      'latest_run': {...},     # juengster Run (egal welche role)
      'latest_active_run': {...},  # juengster mit role='active'
      'total_runs': int,
      'shadow_count': int,
      'active_count': int,
      'fallback_count': int,
      'is_compliant': bool,    # latest_active_run.status in ACCEPTABLE
      'fidleg_basis': 'Art. 16 FIDLEG',
    }

    Robust gegen Schema-Mismatch -> degraded leeres Schema.
    """
    empty = {
        "latest_run": None,
        "latest_active_run": None,
        "total_runs": 0,
        "shadow_count": 0,
        "active_count": 0,
        "fallback_count": 0,
        "is_compliant": True,
        "fidleg_basis": "Art. 16 FIDLEG",
    }
    try:
        from models.allocation import OptimizerRun
        runs = (
            db.query(OptimizerRun)
            .filter(OptimizerRun.mandate_id == mandate.id)
            .order_by(OptimizerRun.run_at.desc())
            .all()
        )
    except Exception:  # noqa: BLE001
        # Fail-closed (Mega-Audit 2026-08-04, analog Commit 23585cf): eine
        # DB-/Schema-Exception ist NICHT dasselbe wie "noch kein Run
        # vorhanden" -- hier wissen wir schlicht nichts, also KEINE
        # Konformitaet behaupten. is_compliant=None + audit_degraded=True,
        # der PDF-Renderer (_recommendation_block) zeigt darauf bereits
        # "Pruefung nicht moeglich" (amber) statt Gruen.
        return {**empty, "is_compliant": None, "audit_degraded": True}

    if not runs:
        return empty

    latest = summarize_optimizer_run(runs[0])
    active_runs = [r for r in runs if getattr(r, "role", None) == "active"]
    latest_active = summarize_optimizer_run(active_runs[0]) if active_runs else None

    shadow_count = sum(1 for r in runs if getattr(r, "role", None) == "shadow")
    active_count = len(active_runs)
    fallback_count = sum(
        1 for r in runs if getattr(r, "method", None) == "fallback_house_matrix"
    )

    if latest_active is not None:
        is_compliant = bool(latest_active.get("is_acceptable"))
    else:
        # Kein aktiver Run -> noch im Shadow-Mode (Stage 8 Pattern), OK
        is_compliant = True

    return {
        "latest_run": latest,
        "latest_active_run": latest_active,
        "total_runs": len(runs),
        "shadow_count": shadow_count,
        "active_count": active_count,
        "fallback_count": fallback_count,
        "is_compliant": is_compliant,
        "fidleg_basis": "Art. 16 FIDLEG",
    }
