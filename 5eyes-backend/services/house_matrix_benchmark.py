"""SUITABILITY-DETECTOR-AVAILABILITY-001 (Depotcheck): HouseMatrix-
Referenz ("zum Risikoprofil passende strategische Referenz") mit explizitem
Status statt stiller Auslassung.

Vorher lieferte ``routers/pdf_reports._depotcheck_house_matrix_benchmark``
bei fehlender Policy/Profil/Matrix-Zeile still ``{}``: der Depotcheck-PDF-
Performancevergleich lief dann ohne Referenzlinie, ohne Hinweis. Ueber-
lappende Zeilen wurden per ``order_by(score_from desc).first()`` still
aufgeloest.

Jetzt: Status ``available`` / ``unavailable`` mit Reason-Code (dieselben
Codes und dieselbe eindeutige Bucket-Aufloesung wie der Suitability-
Detektor, ``services.suitability_cap_check``) und ein kundentauglicher
Hinweistext.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from services.suitability_cap_check import resolve_house_matrix_for_assessment

STATUS_AVAILABLE = "available"
STATUS_UNAVAILABLE = "unavailable"

REASON_TARGET_ALLOCATION_MISSING = "TARGET_ALLOCATION_MISSING"

UNAVAILABLE_NOTE_PREFIX = (
    "Vergleich mit der Hausmatrix nicht möglich – Policy/Profil fehlt"
)


@dataclass(frozen=True)
class HouseMatrixBenchmark:
    status: str
    reason_code: str | None = None
    note: str | None = None
    score_bucket: int | None = None
    profile_name: str | None = None
    weights_bps: dict[str, int] = field(default_factory=dict)

    @property
    def available(self) -> bool:
        return self.status == STATUS_AVAILABLE

    def public(self) -> dict:
        """Status-Block fuer API/PDF (ohne Gewichte)."""
        return {
            "status": self.status,
            "reason_code": self.reason_code,
            "note": self.note,
            "score_bucket": self.score_bucket,
            "profile_name": self.profile_name,
        }


def _unavailable(reason_code: str, detail: str | None, score_bucket=None) -> HouseMatrixBenchmark:
    detail_text = f" {detail}" if detail else ""
    return HouseMatrixBenchmark(
        status=STATUS_UNAVAILABLE,
        reason_code=reason_code,
        note=f"{UNAVAILABLE_NOTE_PREFIX} ({reason_code}).{detail_text}",
        score_bucket=score_bucket,
    )


def _current_assessment(db: Session, mandate):
    from models.profiling import RiskAssessment

    return (
        db.query(RiskAssessment)
        .filter(
            RiskAssessment.mandate_id == mandate.id,
            RiskAssessment.is_current == 1,
            RiskAssessment.deleted_at.is_(None),
        )
        .order_by(RiskAssessment.created_at.desc())
        .first()
    )


def _current_target_allocation(db: Session, mandate):
    from models.allocation import TargetAllocation

    return (
        db.query(TargetAllocation)
        .filter(
            TargetAllocation.mandate_id == mandate.id,
            TargetAllocation.is_current == 1,
            TargetAllocation.deleted_at.is_(None),
        )
        .order_by(TargetAllocation.version.desc(), TargetAllocation.created_at.desc())
        .first()
    )


def resolve_depotcheck_benchmark(
    db: Session,
    mandate,
    *,
    target_allocation=None,
    use_current_target_allocation: bool = True,
) -> HouseMatrixBenchmark:
    """HouseMatrix-Referenz fuer den Depotcheck.

    Die Policy ist die der Soll-Allokation (``TargetAllocation.policy_id``),
    damit die Referenz zur Matrix passt, mit der die Strategie erzeugt wurde.
    """
    ta = target_allocation
    if ta is None and use_current_target_allocation:
        ta = _current_target_allocation(db, mandate)
    if ta is None:
        return _unavailable(
            REASON_TARGET_ALLOCATION_MISSING,
            "Keine aktive Soll-Allokation.",
        )
    resolution = resolve_house_matrix_for_assessment(
        db,
        assessment=_current_assessment(db, mandate),
        policy_id=getattr(ta, "policy_id", None),
    )
    if resolution.row is None:
        return _unavailable(
            str(resolution.reason_code),
            resolution.detail,
            score_bucket=resolution.score_bucket,
        )
    row = resolution.row
    return HouseMatrixBenchmark(
        status=STATUS_AVAILABLE,
        score_bucket=resolution.score_bucket,
        profile_name=str(getattr(row, "profile_name", "") or "") or None,
        weights_bps={
            "equities": int(getattr(row, "equity_target_bps", 0) or 0),
            "bonds": int(getattr(row, "bonds_target_bps", 0) or 0),
            "real_estate": int(getattr(row, "real_estate_target_bps", 0) or 0),
            "alternatives": int(getattr(row, "alt_target_bps", 0) or 0),
            "liquidity": int(getattr(row, "liq_target_bps", 0) or 0),
        },
    )
