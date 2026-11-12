"""Test-Hilfe Nachtrag 1 (Pflichtfrage vor der Finalisierung).

Seit E2 Nachtrag 1 muss Frage 1 der Nachhaltigkeitspraeferenz vor der
Finalisierung beantwortet sein. Tests, die etwas anderes als die Erhebung
pruefen, erfassen dafuer ausdruecklich "Keine Angabe" (zaehlt als
beantwortet) -- ueber dasselbe Modell und denselben Hash wie die API. In der
Produktion gibt es kein Backfill.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import text

from core import sustainability_preference as sp
from core.evidence import evidence_hash


def answer_question_one_for_all_mandates(db) -> int:
    """Erfasst "Keine Angabe" fuer jedes Mandat ohne Erfassung; gibt die
    Anzahl zurueck. Commit durch den Aufrufer-Kontext (hier: flush+commit)."""
    from database import new_uuid
    from models.mandates import Mandate
    from models.profiling import InvestmentPreferenceDecision

    user_id = db.execute(text("SELECT id FROM users ORDER BY id LIMIT 1")).scalar()
    done = {r[0] for r in db.execute(text("SELECT DISTINCT mandate_id FROM investment_preference_decisions"))}
    count = 0
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    for mandate in db.query(Mandate).all():
        if mandate.id in done:
            continue
        months = sp.resolve_review_months(db.execute(
            text(sp.TENANT_REVIEW_MONTHS_SQL), {"tid": mandate.tenant_id},
        ).scalar() if mandate.tenant_id else None)
        row = InvestmentPreferenceDecision(
            id=new_uuid(), schema_version=sp.SCHEMA_VERSION, tenant_id=mandate.tenant_id,
            mandate_id=mandate.id, client_id=mandate.client_id, sequence_no=1, supersedes_id=None,
            questionnaire_version=sp.QUESTIONNAIRE_VERSION, definition_hash=sp.definition_hash(),
            derivation_version=sp.DERIVATION_VERSION, response_status="declined", esg_relevance=None,
            esg_characteristic=None, exclusions_json=json.dumps([]), preference_waived=0,
            waiver_reason_sealed=None, profile_code="declined", information_acknowledged=0,
            client_confirmed=1, capture_channel="in_person", mandate_type_at_capture=mandate.mandate_type,
            review_policy_version=sp.REVIEW_POLICY_VERSION, review_policy_months=months,
            review_due_on=sp.add_months_iso(now[:10], months), captured_by=user_id,
            captured_at=now, created_at=now,
        )
        row.decision_hash = evidence_hash(sp.decision_snapshot(
            {c.name: getattr(row, c.name) for c in row.__table__.columns}
        ))
        db.add(row)
        count += 1
    db.flush()
    db.commit()
    return count
