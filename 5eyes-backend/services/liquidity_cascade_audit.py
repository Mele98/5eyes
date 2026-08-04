"""Sprint U-21 (2026-06-03): Liquidity-Cascade-Stage-3 Warning Audit.

Hintergrund
-----------
portfolio_engine hat eine 2-Stage-Eskalation fuer SAA-Liquiditaet:
- Stage 1: normales Maximum aus HouseMatrix (typisch 2-5%)
- Stage 2: Hard-Cap 3% (_SAA_LIQUIDITY_HARD_CAP_BPS)
- Stage 3: Emergency-Cap 10% (_SAA_LIQUIDITY_EMERGENCY_CAP_BPS) + Warning

Die Stage-3-Eskalation hinterlaesst nur einen Reasoning-Trail-Eintrag
+ generische WARN_FALLBACK Warning. Es gibt keine strukturierte
Sichtbarkeit ob ein Mandate in Stage 3 ist.

Read-only Audit-Service:
- classify_liquidity_stage(liquidity_bps) -> 'normal' | 'hard_cap' | 'emergency'
- audit_mandate_liquidity_cascade(db, mandate) -> Befund pro Mandat
"""
from __future__ import annotations

from typing import Any, Optional

from sqlalchemy.orm import Session


# Mirror der portfolio_engine-Konstanten. Drift-Test sichert Konsistenz.
LIQUIDITY_HARD_CAP_BPS = 300         # 3 %
LIQUIDITY_EMERGENCY_CAP_BPS = 1000   # 10 %


STAGE_NORMAL = "normal"
STAGE_HARD_CAP = "hard_cap"
STAGE_EMERGENCY = "emergency"
STAGE_UNKNOWN = "unknown"


STAGE_LABELS = {
    STAGE_NORMAL:
        "Liquiditaetsanteil innerhalb der normalen Bandbreite.",
    STAGE_HARD_CAP:
        "Liquiditaet am Soll-Hard-Cap (3 %). Berater hat die "
        "Eskalation nicht in den Emergency-Bereich getrieben.",
    STAGE_EMERGENCY:
        "Liquiditaet ueber dem Soll-Hard-Cap im Emergency-Bereich "
        "(bis 10 %). Risikoprofil oder Goal-Struktur im Beratungs-"
        "gespraech pruefen — die SAA wurde aufgeweicht damit das "
        "Risikobudget eingehalten wird.",
    STAGE_UNKNOWN:
        "Liquiditaets-Cascade-Stage kann nicht bestimmt werden — "
        "keine aktuelle Allokation vorhanden.",
}


def classify_liquidity_stage(
    liquidity_bps: Optional[int],
    *,
    hard_cap_bps: int = LIQUIDITY_HARD_CAP_BPS,
    emergency_cap_bps: int = LIQUIDITY_EMERGENCY_CAP_BPS,
) -> str:
    """Liefert Stage-Code basierend auf Liquiditaets-Wert in bps."""
    if liquidity_bps is None:
        return STAGE_UNKNOWN
    try:
        bps = int(liquidity_bps)
    except (TypeError, ValueError):
        return STAGE_UNKNOWN
    if bps <= hard_cap_bps:
        return STAGE_NORMAL
    if bps <= emergency_cap_bps:
        return STAGE_EMERGENCY
    return STAGE_EMERGENCY


def _extract_liquidity_bps(allocation: Any) -> Optional[int]:
    """Liest Liquiditaets-bps aus TargetAllocation (schema-tolerant)."""
    for attr in (
        "liquidity_target_bps", "liquidity_bps",
        "target_liquidity_bps",
    ):
        if hasattr(allocation, attr):
            try:
                v = getattr(allocation, attr)
                if v is not None:
                    return int(v)
            except (TypeError, ValueError):
                pass
    raw = getattr(allocation, "targets_json", None)
    if raw:
        try:
            import json
            data = json.loads(raw) if isinstance(raw, str) else raw
            if isinstance(data, dict) and "liquidity" in data:
                return int(data["liquidity"])
        except (TypeError, ValueError, KeyError):
            pass
    return None


def audit_mandate_liquidity_cascade(
    db: Session, mandate: Any,
) -> dict[str, Any]:
    """Liquidity-Cascade-Audit pro Mandat.

    Output-Schema
    -------------
    {
      'stage': 'normal' | 'hard_cap' | 'emergency' | 'unknown',
      'stage_label': str,
      'liquidity_bps': int | None,
      'hard_cap_bps': 300,
      'emergency_cap_bps': 1000,
      'over_hard_cap_by_bps': int | None,
      'warning_required': bool,
      'beratungsgespraech_pruefen': bool,
      'fidleg_basis': 'Art. 11 / Art. 13 FIDLEG',
    }

    Robust gegen Schema-Mismatch -> degraded unknown.
    """
    empty = {
        "stage": STAGE_UNKNOWN,
        "stage_label": STAGE_LABELS[STAGE_UNKNOWN],
        "liquidity_bps": None,
        "hard_cap_bps": LIQUIDITY_HARD_CAP_BPS,
        "emergency_cap_bps": LIQUIDITY_EMERGENCY_CAP_BPS,
        "over_hard_cap_by_bps": None,
        "warning_required": False,
        "beratungsgespraech_pruefen": False,
        "fidleg_basis": "Art. 11 / Art. 13 FIDLEG",
    }

    try:
        from models.allocation import TargetAllocation
        active_ta = (
            db.query(TargetAllocation)
            .filter(TargetAllocation.mandate_id == mandate.id)
            .filter(TargetAllocation.is_current == 1)
            .filter(TargetAllocation.deleted_at.is_(None))
            .first()
        )
    except Exception:  # noqa: BLE001
        # Mega-Audit (2026-08-04): "unknown"/warning_required=False war schon
        # vor diesem Fix ehrlich (keine falsche "normal"-Behauptung) -- aber
        # eine DB-Exception ist NICHT dasselbe wie "noch keine Allokation
        # vorhanden". audit_degraded macht diesen Unterschied fuer
        # nachgelagerte Konsumenten sichtbar.
        return {**empty, "audit_degraded": True}

    if active_ta is None:
        return empty

    liquidity_bps = _extract_liquidity_bps(active_ta)
    stage = classify_liquidity_stage(liquidity_bps)
    over_hard_cap = None
    if liquidity_bps is not None and liquidity_bps > LIQUIDITY_HARD_CAP_BPS:
        over_hard_cap = liquidity_bps - LIQUIDITY_HARD_CAP_BPS

    return {
        "stage": stage,
        "stage_label": STAGE_LABELS[stage],
        "liquidity_bps": liquidity_bps,
        "hard_cap_bps": LIQUIDITY_HARD_CAP_BPS,
        "emergency_cap_bps": LIQUIDITY_EMERGENCY_CAP_BPS,
        "over_hard_cap_by_bps": over_hard_cap,
        "warning_required": stage == STAGE_EMERGENCY,
        "beratungsgespraech_pruefen": stage == STAGE_EMERGENCY,
        "fidleg_basis": "Art. 11 / Art. 13 FIDLEG",
    }
