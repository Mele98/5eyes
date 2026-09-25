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


_TA_NOT_PASSED = object()


def audit_recommendation_methodology(
    db: Session, mandate: Any, current_ta: Any = _TA_NOT_PASSED,
) -> dict[str, Any]:
    """Audit der Recommendation-Methodology pro Mandat.

    Liefert die letzten OptimizerRun-Daten + den Run, der TATSAECHLICH die
    aktuelle TargetAllocation produziert hat (via deren optimization_run_id
    -- siehe STALE-OPTIMIZER-RUN-MISATTRIBUTION-001-Kommentar unten), damit
    Berater sieht ob die produktive Allokation aus Stochastic oder Fallback
    kommt.

    `current_ta`: optional bereits geladene aktuelle TargetAllocation
    (N1-BASELINE-001, Kontrollrunde 2026-09-25). Der einzige reale Aufrufer
    (services/advisory_report.py::_build_recommendation_methodology, Teil
    des 25-Sektionen-Aggregators) haelt bereits eine per-Request gecachte
    Kopie ueber _cached_current_ta() vor -- eine zweite, identische Query
    hier haette die TARGET_ALLOCATIONS-Query-Obergrenze des N+1-Regressions-
    Guards (tests/test_aggregator_n1_baseline.py) gerissen. Ohne Argument
    (Default-Sentinel) wird weiterhin selbst frisch abgefragt, fuer jeden
    Aufrufer ausserhalb eines aktiven Aggregator-Request-Caches (z.B. Tests,
    ein kuenftiger eigenstaendiger Endpoint).

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
        from models.allocation import OptimizerRun, TargetAllocation
        runs = (
            db.query(OptimizerRun)
            .filter(OptimizerRun.mandate_id == mandate.id)
            .order_by(OptimizerRun.run_at.desc())
            .all()
        )
        if current_ta is _TA_NOT_PASSED:
            current_ta = (
                db.query(TargetAllocation)
                .filter(
                    TargetAllocation.mandate_id == mandate.id,
                    TargetAllocation.is_current == 1,
                    TargetAllocation.deleted_at.is_(None),
                )
                .first()
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

    # STALE-OPTIMIZER-RUN-MISATTRIBUTION-001 (Kontrollrunde 2026-09-24):
    # vorher wurde hier ungeprueft der JUENGSTE OptimizerRun mit role=
    # 'active' als Beleg fuer die AKTUELLE Allokation ausgewiesen -- auch
    # dann, wenn diese Allokation laengst durch eine neuere (z.B. per
    # house_matrix generierte, da OPTIMIZER_MODE zwischenzeitlich
    # umgestellt wurde) TargetAllocation ersetzt wurde. _persist_optimizer_
    # run() schreibt fuer house_matrix/iterative-Modi bewusst KEINEN neuen
    # OptimizerRun (services/portfolio_engine_optimizer_integration.py) --
    # der alte, laengst nicht mehr massgebliche stochastic-Run blieb dadurch
    # der "juengste aktive" und wurde faelschlich als Herleitung der
    # aktuellen (in Wahrheit house_matrix-basierten) Empfehlung ausgewiesen.
    # Live reproduziert. Fix: nur der Run, auf den die AKTUELLE
    # TargetAllocation via optimization_run_id tatsaechlich zeigt, gilt als
    # 'latest_active_run' -- zeigt die aktuelle Allokation auf keinen Run
    # (house_matrix/noch keine Allokation), ist latest_active_run=None,
    # unabhaengig davon, ob es fuer eine laengst superseded Allokation mal
    # einen aktiven Run gab.
    current_run_id = getattr(current_ta, "optimization_run_id", None) if current_ta else None
    if current_run_id:
        matching_run = next(
            (r for r in active_runs if getattr(r, "id", None) == current_run_id), None
        )
        latest_active = summarize_optimizer_run(matching_run) if matching_run else None
    else:
        latest_active = None

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
