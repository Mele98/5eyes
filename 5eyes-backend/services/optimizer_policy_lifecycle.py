"""Lebenszyklus einer OptimizerPolicy als versioniertes Aggregat.

POLICY-VERSION-IDENTITY-001: Eine Policy-Zeile, die aktiv ist oder von einer
TargetAllocation bzw. einem RecommendationRun referenziert wird, ist unter
ihrer ID unveraenderlich. Eine fachliche Aenderung erzeugt eine neue
Entwurfsversion mit neuer ID; House Matrix und Building Blocks werden
mitkopiert, damit jede Version ein vollstaendiges Aggregat ist.

POLICY-ACTIVATION-COMPLETENESS-001: Aktiv werden darf eine Policy nur mit
lueckenloser, ueberlappungsfreier House-Matrix-Abdeckung der Scores 1..10.
"""
from __future__ import annotations

from typing import Iterable

from sqlalchemy.orm import Session

from database import new_uuid
from models.allocation import BuildingBlock, HouseMatrix, OptimizerPolicy, TargetAllocation
from models.review import RecommendationRun

REASON_CODE_HOUSE_MATRIX_INCOMPLETE = "POLICY_HOUSE_MATRIX_INCOMPLETE"
SCORE_MIN = 1
SCORE_MAX = 10

# Spalten der Kindzeilen, die beim Kopieren neu vergeben werden.
_CHILD_IDENTITY_COLUMNS = frozenset({"id", "policy_id", "created_at", "updated_at"})


def policy_is_referenced(db: Session, policy_id: str) -> bool:
    """True, wenn eine TargetAllocation oder ein RecommendationRun auf die ID zeigt."""
    if db.query(TargetAllocation.id).filter(TargetAllocation.policy_id == policy_id).first():
        return True
    return bool(
        db.query(RecommendationRun.id).filter(RecommendationRun.policy_id == policy_id).first()
    )


def policy_is_frozen(db: Session, policy: OptimizerPolicy) -> bool:
    """Aktive oder referenzierte Versionen duerfen nicht in-place geaendert werden."""
    return int(policy.is_current or 0) == 1 or policy_is_referenced(db, policy.id)


def next_policy_version(db: Session, policy_name: str) -> int:
    latest = db.query(OptimizerPolicy).filter(
        OptimizerPolicy.policy_name == policy_name,
    ).order_by(OptimizerPolicy.version.desc()).first()
    return (int(latest.version) if latest else 0) + 1


def copy_policy_children(db: Session, *, source_id: str, target_id: str, now: str) -> None:
    """Kopiert alle aktiven House-Matrix- und Building-Block-Zeilen spaltengetreu."""
    for model, order_col in ((HouseMatrix, HouseMatrix.score_from), (BuildingBlock, BuildingBlock.id)):
        rows = db.query(model).filter(
            model.policy_id == source_id,
            model.is_active == 1,
        ).order_by(order_col.asc()).all()
        for src in rows:
            values = {
                col.name: getattr(src, col.name)
                for col in model.__table__.columns
                if col.name not in _CHILD_IDENTITY_COLUMNS
            }
            db.add(model(
                id=new_uuid(), policy_id=target_id,
                created_at=now, updated_at=now, **values,
            ))
    db.flush()


def new_draft_version(
    db: Session, source: OptimizerPolicy, *, now: str, created_by: str,
    overrides: dict | None = None,
) -> OptimizerPolicy:
    """Neue Entwurfsversion (neue ID, is_current=0) als vollstaendige Kopie."""
    values = {
        col.name: getattr(source, col.name)
        for col in OptimizerPolicy.__table__.columns
        if col.name not in {
            "id", "version", "is_current", "valid_from", "valid_to",
            "created_by", "created_at", "updated_at",
        }
    }
    values.update(overrides or {})
    draft = OptimizerPolicy(
        id=new_uuid(),
        version=next_policy_version(db, values["policy_name"]),
        is_current=0,
        valid_from=now,
        valid_to=None,
        created_by=created_by,
        created_at=now,
        updated_at=now,
        **values,
    )
    db.add(draft)
    db.flush()
    copy_policy_children(db, source_id=source.id, target_id=draft.id, now=now)
    return draft


def house_matrix_coverage_problems(rows: Iterable) -> list[str]:
    """Luecken, Ueberlappungen oder fehlende Abdeckung der Scores 1..10."""
    bands = sorted(
        ((int(r.score_from), int(r.score_to)) for r in rows),
        key=lambda b: (b[0], b[1]),
    )
    if not bands:
        return ["keine aktive House-Matrix-Zeile"]
    problems: list[str] = []
    expected = SCORE_MIN
    for start, end in bands:
        if end < start:
            problems.append(f"Band {start}-{end}: score_to < score_from")
            continue
        if start > expected:
            problems.append(f"Score {expected}-{start - 1} nicht abgedeckt")
        elif start < expected:
            problems.append(f"Band {start}-{end} ueberlappt bis Score {expected - 1}")
        expected = max(expected, end + 1)
    if expected <= SCORE_MAX:
        problems.append(f"Score {expected}-{SCORE_MAX} nicht abgedeckt")
    if bands[0][0] < SCORE_MIN or max(b[1] for b in bands) > SCORE_MAX:
        problems.append(f"Band ausserhalb {SCORE_MIN}-{SCORE_MAX}")
    return problems
