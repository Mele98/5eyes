"""Sprint U-66 (2026-06-03): FIDLEG-Geeignetheitserklaerung Audit-Service.

Hintergrund
-----------
FIDLEG Art. 11-13 verlangt fuer Anlageberatung mit Einzelempfehlung
(Vollberatung) eine Geeignetheitspruefung VOR der Empfehlung. Pre-U-66
existierten die Modelle (SuitabilityCheck + AdvisoryLog.
suitability_check_id), aber kein Code-Pfad pruefte ob die Pflicht
eingehalten wurde -> ein Audit-Befund konnte erst bei manueller
Inspektion entstehen.

Diese Modul liefert einen read-only Audit-Service:
- audit_mandate_suitability(db, mandate) -> strukturierter Befund pro
  Mandat: alle relevanten AdvisoryLog-Eintraege + Verstoesse.

Designed als NON-BREAKING Audit-Layer (kein Pflicht-Check in
advisory_log_service.create_entry — das waere Breaking-Change und
sollte separat per Spec entschieden werden). Hier nur: Sichtbarkeit
schaffen, damit der Berater den Bestand abklopfen kann.

FIDLEG-Bezug
------------
- Art. 11: Pflicht Geeignetheitspruefung bei Vermoegensverwaltung +
  Anlageberatung mit Beruecksichtigung des Portfolios
- Art. 13: Pflicht ueber Empfehlung zu unterlassen, wenn ungeeignet
  (oder warnen + Auftrag dokumentieren)
- Art. 16: Dokumentationspflicht
- BVI/SBVg-Praxis: 12-Monats-Freshness als Industry-Standard
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy.orm import Session

# Suitability-Check-Freshness in Tagen (12 Monate per Industry-Praxis).
SUITABILITY_FRESHNESS_MAX_DAYS = 365

# duty_type-Werte die eine Geeignetheitspruefung VERLANGEN.
# 'execution_only' und 'no_advice' brauchen sie nicht (FIDLEG Art. 13 Abs. 3).
DUTY_TYPES_REQUIRING_SUITABILITY = {
    "advisory_individual",  # Vollberatung mit Einzelempfehlung
    "advisory_portfolio",   # Vermoegensverwaltung
    "portfolio_management",
}


def _parse_iso(value: Any) -> Optional[datetime]:
    """Best-Effort ISO-Parsing mit aware-UTC-Default."""
    if not value:
        return None
    s = str(value).strip()
    if not s:
        return None
    try:
        # Normalize Z -> +00:00 fuer fromisoformat
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (TypeError, ValueError):
        return None


def evaluate_suitability_freshness(
    check_dt: Optional[datetime],
    reference_dt: datetime,
    *,
    max_age_days: int = SUITABILITY_FRESHNESS_MAX_DAYS,
) -> dict[str, Any]:
    """Bewertet ob ein SuitabilityCheck zum Referenz-Zeitpunkt noch
    'frisch' ist (=binnen max_age_days vor reference_dt)."""
    if check_dt is None:
        return {"fresh": False, "reason": "missing_checked_at",
                "age_days": None}
    if check_dt > reference_dt:
        return {"fresh": False, "reason": "check_after_advisory",
                "age_days": None}
    age = (reference_dt - check_dt).days
    if age > max_age_days:
        return {"fresh": False, "reason": "stale",
                "age_days": age}
    return {"fresh": True, "reason": "ok", "age_days": age}


def audit_mandate_suitability(
    db: Session, mandate: Any,
) -> dict[str, Any]:
    """Liefert FIDLEG-Geeignetheits-Audit-Report fuer ein Mandat.

    Schema-Output
    -------------
    {
      'total_advisory_logs': N,
      'logs_requiring_suitability': N,
      'logs_with_suitability': N,
      'logs_without_suitability': [{ id, entry_datetime, duty_type, ... }, ...],
      'freshness_issues': [{ log_id, check_id, reason, age_days }, ...],
      'result_issues': [{ log_id, check_id, result, ... }, ...],
      'is_compliant': bool,
      'fidleg_basis': 'Art. 11/13/16 FIDLEG',
    }

    Non-breaking: liest Daten, fasst Audit-Befund zusammen.
    """
    base = {
        "total_advisory_logs": 0,
        "logs_requiring_suitability": 0,
        "logs_with_suitability": 0,
        "logs_without_suitability": [],
        "freshness_issues": [],
        "result_issues": [],
        "is_compliant": True,
        "fidleg_basis": "Art. 11/13/16 FIDLEG",
    }

    try:
        from models.review import AdvisoryLog
        from models.profiling import SuitabilityCheck
        logs = (
            db.query(AdvisoryLog)
            .filter(AdvisoryLog.mandate_id == mandate.id)
            .all()
        )
    except Exception:  # noqa: BLE001 — robust gegen Schema-Mismatch
        return base

    base["total_advisory_logs"] = len(logs)
    if not logs:
        return base

    # Cache: SuitabilityCheck-Lookups pro Mandat (1 Query, dann in-memory)
    try:
        from models.profiling import SuitabilityCheck
        check_rows = (
            db.query(SuitabilityCheck)
            .filter(SuitabilityCheck.mandate_id == mandate.id)
            .all()
        )
        checks_by_id = {getattr(c, "id"): c for c in check_rows}
    except Exception:  # noqa: BLE001
        checks_by_id = {}

    for log in logs:
        duty = str(getattr(log, "duty_type", "") or "").strip().lower()
        log_id = getattr(log, "id", None)
        entry_dt = _parse_iso(getattr(log, "entry_datetime", None)) or \
                   _parse_iso(getattr(log, "entry_date", None)) or \
                   datetime.now(timezone.utc)

        if duty not in DUTY_TYPES_REQUIRING_SUITABILITY:
            continue
        base["logs_requiring_suitability"] += 1

        check_id = getattr(log, "suitability_check_id", None)
        if not check_id:
            base["logs_without_suitability"].append({
                "id": log_id,
                "entry_datetime": getattr(log, "entry_datetime", None),
                "duty_type": duty,
                "reason": "no_suitability_check_linked",
            })
            base["is_compliant"] = False
            continue

        check = checks_by_id.get(check_id)
        if check is None:
            base["logs_without_suitability"].append({
                "id": log_id,
                "entry_datetime": getattr(log, "entry_datetime", None),
                "duty_type": duty,
                "reason": "suitability_check_id_dangling",
                "check_id": check_id,
            })
            base["is_compliant"] = False
            continue

        base["logs_with_suitability"] += 1
        check_dt = _parse_iso(getattr(check, "checked_at", None))
        freshness = evaluate_suitability_freshness(check_dt, entry_dt)
        if not freshness["fresh"]:
            base["freshness_issues"].append({
                "log_id": log_id,
                "check_id": check_id,
                "reason": freshness["reason"],
                "age_days": freshness["age_days"],
            })
            base["is_compliant"] = False

        # Result-Konsistenz: wenn Check NEGATIV und client_proceeding_despite=0
        # aber Berater hat trotzdem advisory_log angelegt -> Verstoss.
        result = str(getattr(check, "result", "") or "").strip().lower()
        proceeding = bool(int(getattr(check, "client_proceeding_despite", 0) or 0))
        if result in {"nicht_geeignet", "unsuitable", "ungeeignet"} \
                and not proceeding:
            base["result_issues"].append({
                "log_id": log_id,
                "check_id": check_id,
                "result": result,
                "client_proceeding_despite": proceeding,
                "reason": "advisory_despite_unsuitable_without_consent",
            })
            base["is_compliant"] = False

    return base
