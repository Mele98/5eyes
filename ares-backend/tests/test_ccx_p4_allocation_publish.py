"""CCX-P4 Allocation-Publish -- Pflichtregressionen (Vertrag 2026-11-13 §7).

* CCX-04: Pruefung UND Freigabe gaten die Publikation (``is_publishable``).
* Publish-Gate (``services/allocation_publication_gate.py``): Envelope
  SEALED+FRESH (P1/P2), Bewertung COMPLETE (P3), wirksame Bindungen, Summe
  genau 10'000 bps (9'999/10'001 blockiert), Baender, Allocation-Context,
  Release-Gates, Vier Augen; Publikation und Active-Pointer atomar.
* Regressionen: stale approval, Mutation nach Pruefung, zwei Publisher,
  Mandatswechsel A->B->A, PDF direkt vor Commit, manuelle Allokation nur ueber
  denselben Gate, Tenant-IDOR, append-only/no-replace, Konsumenten (Handoff,
  "Portfolio umsetzen", Kunden-PDFs, React-Bericht, aktuelle Endpunkte).
* Migration: genau ein Head (``CCX_P4_REV``), upgrade/downgrade/upgrade,
  ORM = Bootstrap-SQL = Laufzeitpatch = Alembic.
* Waechter: kein Pfad schreibt Publikationen am Gate vorbei; jeder Lesepfad
  der aktuellen Soll-Allokation ist inventarisiert und klassifiziert.

PostgreSQL (RLS, Trigger, zwei echte Publisher):
``tests/test_postgres_ccx_p4_publication_live.py``.
"""
from __future__ import annotations

import ast
import json
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from core.reason_codes import DomainError
from services.allocation_publication_gate import (
    APPROVAL_APPROVED,
    VALIDATION_PASS,
    is_publishable,
)
from tests.test_ccx_p1_snapshot_hash import (  # noqa: F401
    BACKEND,
    _alembic_cfg,
    _audit,
    _finalizable_run,
    _finalize,
    _seed_realistic_mandate,
    session_factory,
)

CCX_P4_REV = "24e7606245d3"
CCX_P3_REV = "6814c14575e9"
P4_TABLES = ("allocation_publication_decisions", "allocation_active_publications")


# ── CCX-04 ───────────────────────────────────────────────────────────────────


def test_ccx04_validation_and_approval_both_gate_publication():
    assert is_publishable(VALIDATION_PASS, APPROVAL_APPROVED) is True
    assert is_publishable("REJECTED", APPROVAL_APPROVED) is False
    assert is_publishable(VALIDATION_PASS, "DRAFT") is False
    for unknown in (None, "", "UNKNOWN", "pass", "approved"):
        assert is_publishable(unknown, APPROVAL_APPROVED) is False
        assert is_publishable(VALIDATION_PASS, unknown) is False


# ── Helfer ───────────────────────────────────────────────────────────────────


def _users(db):
    from models.users import User

    return {u.id: u for u in db.query(User).all()}


def _mandate(db, mid):
    from models.mandates import Mandate

    return db.query(Mandate).filter(Mandate.id == mid).one()


def _second_approver(session_factory, advisor_id):
    """Zweite freigabeberechtigte Person derselben Firma (Vier Augen)."""
    from models.users import User

    with session_factory() as db:
        advisor = db.query(User).filter(User.id == advisor_id).one()
        uid = f"approver-{uuid.uuid4().hex[:8]}"
        clone = {c.name: getattr(advisor, c.name) for c in User.__table__.columns}
        clone.update(id=uid, email=f"{uid}@example.invalid", full_name="Zweite Freigabe")
        if "username" in clone:
            clone["username"] = uid
        db.add(User(**clone))
        db.commit()
    return uid


def _finalized(session_factory, suffix):
    advisor_id, mid, aid, run_id = _finalizable_run(session_factory, suffix)
    _finalize(session_factory, advisor_id, mid, run_id)
    return advisor_id, mid, aid, run_id


def _overview(session_factory, mid):
    from services.allocation_publication_gate import publication_overview

    with session_factory() as db:
        return publication_overview(db, _mandate(db, mid))


def _publish(session_factory, mid, user_id, overview=None, **kw):
    from models.users import User
    from services.allocation_publication_gate import publish_allocation

    overview = overview or _overview(session_factory, mid)
    with session_factory() as db:
        user = db.query(User).filter(User.id == user_id).one()
        decision = publish_allocation(
            db, _mandate(db, mid), user=user,
            expected_validation_hash=kw.pop("validation_hash", overview["validation_hash"]),
            expected_target_allocation_id=kw.pop("target_allocation_id", overview["target_allocation_id"]),
            **kw,
        )
        return decision


def _state(session_factory, mid, deep=True):
    from services.allocation_publication_gate import active_publication_state

    with session_factory() as db:
        return active_publication_state(db, _mandate(db, mid), deep=deep)


def _published(session_factory, suffix):
    advisor_id, mid, aid, run_id = _finalized(session_factory, suffix)
    approver = _second_approver(session_factory, advisor_id)
    decision = _publish(session_factory, mid, approver)
    return advisor_id, approver, mid, aid, run_id, decision


def _blocked(session_factory, mid, user_id, code, **kw):
    with pytest.raises(DomainError) as exc:
        _publish(session_factory, mid, user_id, **kw)
    assert exc.value.reason_code == code, exc.value.as_detail()
    return exc.value


# ── Publish-Gate ─────────────────────────────────────────────────────────────


def test_unfinalized_allocation_is_a_draft_and_not_publishable(session_factory):
    advisor_id, mid, _aid, _run = _finalizable_run(session_factory, "draft")
    overview = _overview(session_factory, mid)
    assert overview["publication_status"] == "DRAFT"
    assert overview["can_publish"] is False
    assert "CCX_ENVELOPE_MISSING" in overview["blocker_codes"]
    err = _blocked(session_factory, mid, advisor_id, "CCX_ALLOCATION_NOT_PUBLISHABLE")
    assert "CCX_ENVELOPE_MISSING" in err.extra["blocker_codes"]
    with session_factory() as db:
        rows = db.execute(text(
            "SELECT publishable, blocker_codes_json, publication_sequence FROM allocation_publication_decisions"
        )).all()
        assert [(r[0], r[2]) for r in rows] == [(0, 1)]
        assert "CCX_ENVELOPE_MISSING" in json.loads(rows[0][1])
        assert db.execute(text("SELECT count(*) FROM allocation_active_publications")).scalar() == 0
        audit = _audit(db, "ccx.allocation.publication_rejected")
        assert len(audit) == 1 and audit[0].mandate_id == mid and audit[0].tenant_id
        assert "{" not in audit[0].new_value
    assert _state(session_factory, mid).status == "DRAFT"


def test_finalized_allocation_publishes_with_approval_binding(session_factory):
    from services.allocation_publication_gate import approval_hash_for

    advisor_id, approver, mid, _aid, run_id, decision = _published(session_factory, "pub")
    assert decision.publishable == 1 and decision.publication_sequence == 1
    assert decision.approved_by == approver and decision.approval_mode == "four_eyes"
    assert decision.approval_hash == approval_hash_for(
        tenant_id=decision.tenant_id, mandate_id=mid, publication_sequence=1,
        validation_hash=decision.validation_hash, envelope_id=decision.envelope_id,
        envelope_hash=decision.published_envelope_hash, target_allocation_id=decision.target_allocation_id,
        approved_by=approver, approved_at=decision.approved_at, approval_mode="four_eyes",
    )
    state = _state(session_factory, mid)
    assert state.published and state.publication_id == decision.id
    assert state.target_allocation_id == decision.target_allocation_id
    with session_factory() as db:
        envelope = db.execute(text(
            "SELECT envelope_hash, status, freshness_status FROM advisory_decision_envelopes WHERE id = :i"
        ), {"i": decision.envelope_id}).one()
        assert envelope == (decision.published_envelope_hash, "SEALED", "FRESH")
        pointer = db.execute(text(
            "SELECT publication_id, optimistic_version FROM allocation_active_publications WHERE mandate_id = :m"
        ), {"m": mid}).one()
        assert pointer == (decision.id, 1)
        audit = _audit(db, "ccx.allocation.published")
        assert len(audit) == 1 and decision.approval_hash in audit[0].new_value
    overview = _overview(session_factory, mid)
    assert overview["publication_status"] == "PUBLISHED" and overview["already_published"] is True
    assert overview["can_publish"] is False


def test_four_eyes_self_approval_blocked_and_attestation_only_for_single_approver(session_factory):
    advisor_id, mid, _aid, _run = _finalized(session_factory, "eyes")
    err = _blocked(session_factory, mid, advisor_id, "CCX_APPROVAL_BINDING_MISSING")
    assert err.extra["blocker_codes"] == ["FOUR_EYES_REQUIRED"]
    # Begruendung zu kurz -> weiter gesperrt.
    _blocked(session_factory, mid, advisor_id, "CCX_APPROVAL_BINDING_MISSING",
             single_approver_attestation=True, attestation_reason="zu kurz")
    from services.allocation_publication_gate import PUBLICATION_APPROVER_ROLES
    from services.product_eligibility_governance import tenant_approver_ids

    with session_factory() as db:
        approvers = tenant_approver_ids(db, _mandate(db, mid).tenant_id, roles=PUBLICATION_APPROVER_ROLES)
    if approvers == [advisor_id]:
        decision = _publish(session_factory, mid, advisor_id, single_approver_attestation=True,
                            attestation_reason="Einzige freigabeberechtigte Person der Firma.")
        assert decision.approval_mode == "single_approver_attested"
    # Mit einer zweiten Person ist Einzelfreigabe nie zulaessig.
    _second_approver(session_factory, advisor_id)
    if approvers != [advisor_id]:
        _blocked(session_factory, mid, advisor_id, "CCX_APPROVAL_BINDING_MISSING",
                 single_approver_attestation=True, attestation_reason="Einzige freigabeberechtigte Person der Firma.")


def test_mutation_after_check_is_validation_hash_mismatch(session_factory):
    advisor_id, mid, _aid, _run = _finalized(session_factory, "mut")
    approver = _second_approver(session_factory, advisor_id)
    stale = dict(_overview(session_factory, mid))
    stale["validation_hash"] = "f" * 64
    _blocked(session_factory, mid, approver, "CCX_VALIDATION_HASH_MISMATCH", overview=stale)
    other = dict(_overview(session_factory, mid))
    other["target_allocation_id"] = "anderer-stand"
    _blocked(session_factory, mid, approver, "CCX_VALIDATION_HASH_MISMATCH", overview=other)
    assert _state(session_factory, mid).status == "DRAFT"


def test_stale_input_after_check_blocks_publish_and_invalidates_publication(session_factory):
    """stale approval: eine Inputmutation nach Pruefung/Freigabe macht den
    Envelope STALE -> Publish gesperrt bzw. Publikation ungueltig."""
    from models.wealth import Goal

    advisor_id, approver, mid, _aid, _run, _decision = _published(session_factory, "stale")
    assert _state(session_factory, mid).published
    with session_factory() as db:
        goal = db.query(Goal).filter(Goal.mandate_id == mid).first()
        goal.target_amount_rappen = int(goal.target_amount_rappen or 0) + 100
        db.commit()
    state = _state(session_factory, mid)
    assert state.status == "PUBLICATION_INVALID" and state.reason_code == "CCX_INPUT_STALE"
    overview = _overview(session_factory, mid)
    assert overview["can_publish"] is False and "CCX_INPUT_STALE" in overview["blocker_codes"]
    _blocked(session_factory, mid, approver, "CCX_ALLOCATION_NOT_PUBLISHABLE")


def test_approval_against_old_validation_after_mutation_is_rejected(session_factory):
    from models.wealth import Goal

    advisor_id, mid, _aid, _run = _finalized(session_factory, "oldval")
    approver = _second_approver(session_factory, advisor_id)
    checked = _overview(session_factory, mid)
    assert checked["can_publish"] is True
    with session_factory() as db:
        goal = db.query(Goal).filter(Goal.mandate_id == mid).first()
        goal.target_amount_rappen = int(goal.target_amount_rappen or 0) + 100
        db.commit()
    err = _blocked(session_factory, mid, approver, "CCX_ALLOCATION_NOT_PUBLISHABLE", overview=checked)
    assert "CCX_INPUT_STALE" in err.extra["blocker_codes"]


@pytest.mark.parametrize("delta", [-1, 1])
def test_allocation_sum_9999_or_10001_is_not_publishable(session_factory, delta):
    from models.allocation import TargetAllocation
    from services.allocation_publication_gate import _allocation_findings

    advisor_id, mid, _aid, _run = _finalized(session_factory, f"sum{delta}")
    with session_factory() as db:
        ta = db.query(TargetAllocation).filter(
            TargetAllocation.mandate_id == mid, TargetAllocation.is_current == 1).one()
        assert sum(getattr(ta, f"target_{b}_bps") for b in
                   ("equities", "bonds", "real_estate", "alternatives", "liquidity")) == 10_000
        db.expunge(ta)
    ta.target_liquidity_bps = int(ta.target_liquidity_bps) + delta
    ta.band_liquidity_max_bps = max(int(ta.band_liquidity_max_bps), int(ta.target_liquidity_bps))
    ta.band_liquidity_min_bps = min(int(ta.band_liquidity_min_bps), int(ta.target_liquidity_bps))
    assert _allocation_findings(ta) == ["CCX_ALLOCATION_SUM_INVALID"]


def test_band_violation_is_not_publishable(session_factory):
    from models.allocation import TargetAllocation
    from services.allocation_publication_gate import _allocation_findings

    advisor_id, mid, _aid, _run = _finalized(session_factory, "band")
    with session_factory() as db:
        ta = db.query(TargetAllocation).filter(
            TargetAllocation.mandate_id == mid, TargetAllocation.is_current == 1).one()
        db.expunge(ta)
    assert _allocation_findings(ta) == []
    ta.band_equities_max_bps = int(ta.target_equities_bps) - 1
    assert "CCX_ALLOCATION_BAND_VIOLATED" in _allocation_findings(ta)


def test_two_publishers_have_exactly_one_winner(session_factory):
    advisor_id, mid, _aid, _run = _finalized(session_factory, "race")
    first = _second_approver(session_factory, advisor_id)
    second = _second_approver(session_factory, advisor_id)
    checked = _overview(session_factory, mid)
    _publish(session_factory, mid, first, overview=checked)
    err = _blocked(session_factory, mid, second, "CCX_PUBLICATION_RACE", overview=checked)
    assert err.extra["blocker_codes"] == ["CCX_PUBLICATION_RACE"]
    with session_factory() as db:
        assert db.execute(text(
            "SELECT count(*) FROM allocation_publication_decisions WHERE publishable = 1")).scalar() == 1
        assert db.execute(text("SELECT optimistic_version FROM allocation_active_publications")).scalar() == 1


def test_parallel_publisher_losing_the_sequence_is_publication_race(session_factory, monkeypatch):
    """Zwei Publisher mit derselben gelesenen Sequenz: die DB laesst genau
    einen gewinnen (Sequenz-Trigger/Unique), der zweite endet als RACE."""
    import services.allocation_publication_gate as gate

    advisor_id, mid, _aid, _run = _finalized(session_factory, "seq")
    approver = _second_approver(session_factory, advisor_id)
    with session_factory() as db:
        db.execute(text(
            "INSERT INTO allocation_publication_decisions (id, tenant_id, mandate_id, schema_version, "
            "publication_sequence, validation_hash, publishable, blocker_codes_json, created_at, created_by) "
            "VALUES ('foreign-attempt', :t, :m, 'ares/allocation-publication/1', 1, :h, 0, "
            "'[\"CCX_ENVELOPE_MISSING\"]', '2026-11-14T00:00:00.000000Z', :u)"
        ), {"t": _mandate(db, mid).tenant_id, "m": mid, "h": "0" * 64, "u": advisor_id})
        db.commit()
    real = gate._next_sequence
    monkeypatch.setattr(gate, "_next_sequence", lambda db, mandate_id: 1)
    err = _blocked(session_factory, mid, approver, "CCX_PUBLICATION_RACE")
    monkeypatch.setattr(gate, "_next_sequence", real)
    assert err.extra["blocker_codes"] == ["CCX_PUBLICATION_RACE"]
    assert _state(session_factory, mid).status == "DRAFT"
    with session_factory() as db:
        assert _audit(db, "ccx.allocation.publication_rejected")


def test_republish_after_refinalize_moves_pointer_forward(session_factory):
    from tests.test_ccx_p1_snapshot_hash import _finalizable_run as again

    advisor_id, approver, mid, aid, run_id, first = _published(session_factory, "move")
    # neue Finalisierung desselben Mandats (neuer Lauf, neue Allokation)
    advisor_id2, mid2, aid2, run2 = again(session_factory, "move", mandate=(advisor_id, mid, aid))
    _finalize(session_factory, advisor_id, mid, run2)
    state = _state(session_factory, mid)
    assert state.status == "PUBLICATION_INVALID"  # alter Envelope ersetzt bzw. neue Allokation
    second = _publish(session_factory, mid, approver)
    assert second.publication_sequence > first.publication_sequence
    with session_factory() as db:
        assert db.execute(text("SELECT publication_id, optimistic_version FROM allocation_active_publications")
                          ).one() == (second.id, 2)
    assert _state(session_factory, mid).publication_id == second.id


def test_mandate_switch_a_b_a_never_leaks_publication(session_factory):
    adv_a, appr_a, mid_a, *_rest, dec_a = _published(session_factory, "a")
    adv_b, mid_b, _aid_b, _run_b = _finalized(session_factory, "b")
    assert _state(session_factory, mid_b).status == "DRAFT"
    assert _state(session_factory, mid_a).publication_id == dec_a.id
    assert _overview(session_factory, mid_b)["active_publication"]["publication_id"] is None
    appr_b = _second_approver(session_factory, adv_b)
    dec_b = _publish(session_factory, mid_b, appr_b)
    assert _state(session_factory, mid_a).publication_id == dec_a.id
    assert _state(session_factory, mid_b).publication_id == dec_b.id
    assert dec_a.envelope_id != dec_b.envelope_id


def test_new_draft_after_publication_is_not_active(session_factory):
    """Eine neue (generierte oder manuelle) Allokation nach der Publikation
    ist ein Entwurf; die alte Publikation gilt nicht mehr (kein Fallback)."""
    from models.allocation import TargetAllocation

    advisor_id, approver, mid, *_rest = _published(session_factory, "redraft")
    with session_factory() as db:
        ta = db.query(TargetAllocation).filter(
            TargetAllocation.mandate_id == mid, TargetAllocation.is_current == 1).one()
        ta.is_current = 0
        db.flush()
        clone = {c.name: getattr(ta, c.name) for c in TargetAllocation.__table__.columns}
        clone.update(id=str(uuid.uuid4()), version=int(ta.version) + 1, is_current=1)
        db.add(TargetAllocation(**clone))
        db.commit()
        new_id = clone["id"]
    state = _state(session_factory, mid)
    assert not state.published
    from services.allocation_publication_gate import allocation_publication_status

    assert allocation_publication_status(state, new_id) == "DRAFT"


# ── Datenbank ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("statement", [
    "UPDATE allocation_publication_decisions SET validation_hash = '{h}'",
    "DELETE FROM allocation_publication_decisions",
    "INSERT OR REPLACE INTO allocation_publication_decisions SELECT * FROM allocation_publication_decisions",
    "REPLACE INTO allocation_publication_decisions SELECT * FROM allocation_publication_decisions",
    "DELETE FROM allocation_active_publications",
    "UPDATE allocation_active_publications SET optimistic_version = optimistic_version + 5",
    "UPDATE allocation_active_publications SET mandate_id = 'fremd', optimistic_version = optimistic_version + 1",
    "INSERT OR REPLACE INTO allocation_active_publications SELECT * FROM allocation_active_publications",
])
def test_publication_evidence_is_append_only_and_no_replace(session_factory, statement):
    _published(session_factory, "ao")
    with session_factory() as db:
        with pytest.raises((IntegrityError, DBAPIError)):
            db.execute(text(statement.format(h="e" * 64)))
            db.commit()


def test_publishable_row_requires_sealed_fresh_envelope_and_contiguous_sequence(session_factory):
    advisor_id, mid, _aid, _run = _finalizable_run(session_factory, "ddl")
    with session_factory() as db:
        tenant = _mandate(db, mid).tenant_id
        base = ("INSERT INTO allocation_publication_decisions (id, tenant_id, mandate_id, schema_version, "
                "envelope_id, target_allocation_id, publication_sequence, validation_hash, approval_hash, "
                "approval_mode, approved_at, approved_by, publishable, blocker_codes_json, "
                "published_envelope_hash, created_at, created_by) VALUES (:id, :t, :m, "
                "'ares/allocation-publication/1', :e, 'ta', :s, :h, :h, 'four_eyes', 'x', :u, 1, '[]', :h, 'x', :u)")
        with pytest.raises((IntegrityError, DBAPIError), match="CCX_ALLOCATION_NOT_PUBLISHABLE|FOREIGN"):
            db.execute(text(base), {"id": "p1", "t": tenant, "m": mid, "e": None, "s": 1, "h": "a" * 64,
                                    "u": advisor_id})
        db.rollback()
        with pytest.raises((IntegrityError, DBAPIError), match="CCX_PUBLICATION_RACE"):
            db.execute(text(
                "INSERT INTO allocation_publication_decisions (id, tenant_id, mandate_id, schema_version, "
                "publication_sequence, validation_hash, publishable, blocker_codes_json, created_at, created_by) "
                "VALUES ('gap', :t, :m, 'ares/allocation-publication/1', 2, :h, 0, '[\"X\"]', 'x', :u)"
            ), {"t": tenant, "m": mid, "h": "a" * 64, "u": advisor_id})
        db.rollback()
        # Blockierter Versuch ohne Blocker ist eine CHECK-Verletzung (nie leer).
        with pytest.raises((IntegrityError, DBAPIError)):
            db.execute(text(
                "INSERT INTO allocation_publication_decisions (id, tenant_id, mandate_id, schema_version, "
                "publication_sequence, validation_hash, publishable, blocker_codes_json, created_at, created_by) "
                "VALUES ('empty', :t, :m, 'ares/allocation-publication/1', 1, :h, 0, '[]', 'x', :u)"
            ), {"t": tenant, "m": mid, "h": "a" * 64, "u": advisor_id})
        db.rollback()
        # Pointer nur auf publizierbaren Entscheid.
        db.execute(text(
            "INSERT INTO allocation_publication_decisions (id, tenant_id, mandate_id, schema_version, "
            "publication_sequence, validation_hash, publishable, blocker_codes_json, created_at, created_by) "
            "VALUES ('blocked', :t, :m, 'ares/allocation-publication/1', 1, :h, 0, '[\"X\"]', 'x', :u)"
        ), {"t": tenant, "m": mid, "h": "a" * 64, "u": advisor_id})
        with pytest.raises((IntegrityError, DBAPIError), match="CCX_PUBLICATION_RACE"):
            db.execute(text(
                "INSERT INTO allocation_active_publications (id, tenant_id, mandate_id, publication_id, "
                "optimistic_version, updated_at, updated_by) VALUES ('ptr', :t, :m, 'blocked', 1, 'x', :u)"
            ), {"t": tenant, "m": mid, "u": advisor_id})
        db.rollback()


def test_tenant_guard_rejects_foreign_tenant(session_factory):
    from models.tenant import Tenant

    advisor_id, mid, _aid, _run = _finalizable_run(session_factory, "ten")
    with session_factory() as db:
        if db.query(Tenant).filter(Tenant.id == "fremd-p4").first() is None:
            cols = {c.name for c in Tenant.__table__.columns}
            values = {"id": "fremd-p4", "name": "Fremd"}
            for c in Tenant.__table__.columns:
                if c.name not in values and not c.nullable and c.default is None and c.server_default is None:
                    values[c.name] = "x" if str(c.type).startswith(("VARCHAR", "TEXT", "String")) else 0
            db.add(Tenant(**{k: v for k, v in values.items() if k in cols}))
            db.commit()
        with pytest.raises((IntegrityError, DBAPIError), match="MANDATE_EVIDENCE_TENANT_MISMATCH"):
            db.execute(text(
                "INSERT INTO allocation_publication_decisions (id, tenant_id, mandate_id, schema_version, "
                "publication_sequence, validation_hash, publishable, blocker_codes_json, created_at, created_by) "
                "VALUES ('x', 'fremd-p4', :m, 'ares/allocation-publication/1', 1, :h, 0, '[\"X\"]', 'x', :u)"
            ), {"m": mid, "h": "a" * 64, "u": advisor_id})
        db.rollback()


def test_no_float_in_any_p4_column():
    from sqlalchemy import Float, Numeric

    from models.snapshots import AllocationActivePublication, AllocationPublicationDecision

    for model in (AllocationPublicationDecision, AllocationActivePublication):
        for column in model.__table__.columns:
            assert not isinstance(column.type, (Float, Numeric)), (model.__tablename__, column.name)


def test_validation_hash_is_domain_separated_and_integer_only():
    from core.evidence import SCHEME_V1, canonical_json
    import hashlib

    from services.allocation_publication_gate import validation_hash_for

    record = {"a": 1, "b": "x"}
    naked = hashlib.sha256(canonical_json(record, scheme=SCHEME_V1).encode()).hexdigest()
    assert validation_hash_for(record) != naked
    assert validation_hash_for(record) == validation_hash_for(dict(reversed(list(record.items()))))
    assert validation_hash_for(record) != validation_hash_for({"a": 2, "b": "x"})
    with pytest.raises(ValueError):
        validation_hash_for({"a": 1.0})


# ── Migration / Paritaet ─────────────────────────────────────────────────────


def test_alembic_single_head_p4_and_upgrade_downgrade_upgrade(tmp_path):
    import sqlite3

    from alembic import command
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(_alembic_cfg("sqlite://"))
    assert script.get_heads() == [CCX_P4_REV]
    assert script.get_revision(CCX_P4_REV).down_revision == CCX_P3_REV
    chain = [rev.revision for rev in script.walk_revisions("base", CCX_P4_REV)][:4]
    assert chain == [CCX_P4_REV, CCX_P3_REV, "d868f4eaa028", "2c62f9012c73"]
    url = f"sqlite:///{tmp_path / 'p4.db'}"
    cfg = _alembic_cfg(url)

    def tables():
        with sqlite3.connect(tmp_path / "p4.db") as conn:
            return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}

    command.upgrade(cfg, "head")
    assert set(P4_TABLES) <= tables()
    command.downgrade(cfg, CCX_P3_REV)
    assert not set(P4_TABLES) & tables()
    with sqlite3.connect(tmp_path / "p4.db") as conn:
        assert not [r for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'trigger' AND name LIKE 'trg_allocation_%'")]
    command.upgrade(cfg, "head")
    assert set(P4_TABLES) <= tables()


def test_orm_bootstrap_runtime_patch_and_alembic_are_identical_for_p4(tmp_path, monkeypatch):
    import importlib.util
    import sqlite3

    from alembic import command
    from sqlalchemy import create_engine

    import database as db_module
    from database import (
        ALLOCATION_PUBLICATION_SQLITE_TABLE_DDL,
        ALLOCATION_PUBLICATION_SQLITE_TENANT_GUARDS,
        ALLOCATION_PUBLICATION_SQLITE_TRIGGERS,
        Base,
    )

    def schema(conn):
        columns = {t: [r[1] for r in conn.execute(f"PRAGMA table_info({t})")] for t in P4_TABLES}
        names = ", ".join(f"'{t}'" for t in P4_TABLES)
        triggers = {r[0]: " ".join(r[1].split()) for r in conn.execute(
            f"SELECT name, sql FROM sqlite_master WHERE type = 'trigger' AND tbl_name IN ({names})")}
        indexes = {r[0] for r in conn.execute(
            f"SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name IN ({names}) "
            "AND name NOT LIKE 'sqlite_%'")}
        return columns, triggers, indexes

    orm_db = tmp_path / "orm.db"
    engine = create_engine(f"sqlite:///{orm_db}")
    Base.metadata.create_all(engine)
    engine.dispose()
    with sqlite3.connect(orm_db) as conn:
        orm = schema(conn)

    boot_db = tmp_path / "boot.db"
    db_module.bootstrap_sqlite_schema(db_path=boot_db, schema_path=BACKEND / "ares_schema.sql")
    with sqlite3.connect(boot_db) as conn:
        boot_columns = schema(conn)[0]
        for table in reversed(P4_TABLES):
            conn.execute(f"DROP TABLE {table}")
        conn.commit()
    engine = create_engine(f"sqlite:///{boot_db}")
    monkeypatch.setattr(db_module, "engine", engine)
    db_module.ensure_runtime_columns()
    engine.dispose()
    with sqlite3.connect(boot_db) as conn:
        patched = schema(conn)

    alembic_db = tmp_path / "alembic.db"
    command.upgrade(_alembic_cfg(f"sqlite:///{alembic_db}"), "head")
    with sqlite3.connect(alembic_db) as conn:
        migrated = schema(conn)

    assert orm[0] == boot_columns == patched[0] == migrated[0]
    assert orm[1] == patched[1] == migrated[1]
    assert len(orm[1]) == len(ALLOCATION_PUBLICATION_SQLITE_TRIGGERS) + len(ALLOCATION_PUBLICATION_SQLITE_TENANT_GUARDS)
    assert orm[2] == patched[2] == migrated[2]
    assert "ux_allocation_publication_decisions_one_per_envelope" in orm[2]

    schema_sql = (BACKEND / "ares_schema.sql").read_text(encoding="utf-8")
    for ddl in ALLOCATION_PUBLICATION_SQLITE_TABLE_DDL + ALLOCATION_PUBLICATION_SQLITE_TRIGGERS:
        assert ddl + ";" in schema_sql
    path = BACKEND / "alembic" / "versions" / f"{CCX_P4_REV}_ccx_p4_allocation_publish.py"
    spec = importlib.util.spec_from_file_location("ccx_p4_migration_under_test", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert migration._SQLITE_TRIGGERS == ALLOCATION_PUBLICATION_SQLITE_TRIGGERS + ALLOCATION_PUBLICATION_SQLITE_TENANT_GUARDS


# ── Waechter: kein Pfad am Publish-Gate vorbei ───────────────────────────────

GATE_MODULE = "services/allocation_publication_gate.py"
PUBLICATION_SYMBOLS = ("AllocationPublicationDecision", "AllocationActivePublication")
PUBLICATION_TABLES_SQL = ("allocation_publication_decisions", "allocation_active_publications")
# Erlaubte DDL-/Schema-Stellen (keine Daten): Laufzeitpatch, ORM, Migration.
DDL_ALLOWLIST = {"database.py", "models/snapshots.py", "ares_schema.sql"}


def _py_files():
    for path in sorted(BACKEND.rglob("*.py")):
        rel = path.relative_to(BACKEND).as_posix()
        if rel.startswith(("tests/", "alembic/", ".venv", "venv/")) or "/site-packages/" in rel:
            continue
        yield rel, path


def test_only_the_gate_writes_publications():
    """AST-Waechter: Publikationsentscheid und Active-Pointer werden nur im
    Gate-Modul erzeugt/geaendert -- kein Direktweg (auch nicht fuer manuelle
    Allokationen); rohes Schreib-SQL auf die Tabellen nur in den DDL-Stellen."""
    offenders = []
    for rel, path in _py_files():
        source = path.read_text(encoding="utf-8-sig")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                name = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else ""
                if name in PUBLICATION_SYMBOLS and rel != GATE_MODULE:
                    offenders.append(f"{rel}:{node.lineno} {name}(...)")
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and rel not in DDL_ALLOWLIST:
                lowered = node.value.lower()
                for table in PUBLICATION_TABLES_SQL:
                    if table in lowered and any(k in lowered for k in ("insert", "update ", "delete", "replace")):
                        offenders.append(f"{rel}:{node.lineno} SQL auf {table}")
    assert offenders == [], offenders


def test_gate_module_has_no_lazy_imports_and_uses_publish_only_from_router():
    tree = ast.parse((BACKEND / GATE_MODULE).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            assert not any(isinstance(n, (ast.Import, ast.ImportFrom)) for n in ast.walk(node)), node.name
    callers = []
    for rel, path in _py_files():
        if rel == GATE_MODULE:
            continue
        if "publish_allocation(" in path.read_text(encoding="utf-8-sig"):
            callers.append(rel)
    assert callers == ["routers/allocation.py"], callers


# Inventar aller Lesepfade der aktuellen Soll-Allokation (is_current) in den
# Kanaelen, die eine Allocation als aktiv/kundenwirksam liefern koennten.
# Klassifikation:
#   PUBLISHED_GATE -- liest nur den publizierten Stand (require_published_allocation)
#   DRAFT_MARKED   -- Arbeitsstand, Antwort/Dokument traegt den Publikationsstatus
#                     bzw. Entwurfs-Wasserzeichen (allocation_publication_status /
#                     customer_document_watermark / active_publication_state)
CHANNEL_INVENTORY = {
    "routers/allocation.py::get_current_allocation": "DRAFT_MARKED",
    "routers/allocation.py::get_current_allocation_payload": "DRAFT_MARKED",
    "routers/allocation.py::create_target_allocation": "DRAFT_MARKED",
    "routers/allocation.py::generate_target_allocation_endpoint": "DRAFT_MARKED",
    "routers/allocation.py::get_advisory_report": "DRAFT_MARKED",
    "routers/allocation.py::get_published_allocation": "PUBLISHED_GATE",
    "routers/portfolio_handoff.py::_assert_run_is_published": "PUBLISHED_GATE",
    "routers/snapshots.py::create_snapshot": "PUBLISHED_GATE",
    "routers/pdf_reports.py::_mark_unpublished": "DRAFT_MARKED",
    "routers/pdf_reports.py::get_advisory_report_pdf": "DRAFT_MARKED",
    "routers/client_portal.py::_assert_portal_report_releasable": "DRAFT_MARKED",
}
MARKERS = {
    "PUBLISHED_GATE": ("require_published_allocation",),
    "DRAFT_MARKED": ("allocation_publication_status", "customer_document_watermark", "active_publication_state",
                     "PUBLICATION_STATUS_DRAFT"),
}
# Kundenwirksame Endpunkte, die eine Soll-Allokation tragen, und ihr Gate.
CUSTOMER_ENDPOINTS = {
    "routers/pdf_reports.py": ("get_anlagestrategie_pdf", "get_assetallocation_pdf", "get_portfolio_pdf",
                               "get_protokoll_pdf", "get_depotcheck_pdf", "get_backtest_pdf",
                               "get_cost_disclosure_pdf", "get_advisory_report_pdf"),
    "routers/portfolio_handoff.py": ("preview_portfolio_handoff", "create_portfolio_handoff"),
    "routers/snapshots.py": ("create_snapshot",),
}
CUSTOMER_GATES = ("_mark_unpublished", "customer_document_watermark", "_assert_run_is_published",
                  "require_published_allocation")


def _functions(rel):
    tree = ast.parse((BACKEND / rel).read_text(encoding="utf-8"))
    return {n.name: n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}


def _calls(node):
    names = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Call):
            f = n.func
            names.add(f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else "")
        if isinstance(n, ast.Name):
            names.add(n.id)
    return names


def test_channel_inventory_is_classified_and_marked():
    for key, klass in CHANNEL_INVENTORY.items():
        rel, func = key.split("::")
        functions = _functions(rel)
        assert func in functions, key
        assert _calls(functions[func]) & set(MARKERS[klass]), f"{key}: Markierung {klass} fehlt"


def test_every_customer_endpoint_with_allocation_passes_a_publication_gate():
    for rel, names in CUSTOMER_ENDPOINTS.items():
        functions = _functions(rel)
        for name in names:
            assert name in functions, (rel, name)
            assert _calls(functions[name]) & set(CUSTOMER_GATES), f"{rel}::{name} ohne Publish-Gate"


def test_customer_pdf_routes_are_all_classified():
    """Jeder kundenwirksame PDF-Endpunkt (REPORT_ROUTE_CLASSIFICATION) traegt
    entweder einen Publish-Gate oder ist begruendet allokationsfrei."""
    from services.recommendation_release_gate import REPORT_CLIENT_FACING, REPORT_ROUTE_CLASSIFICATION

    allocation_free = {
        "GET /mandates/{mandate_id}/reports/risikoprofil.pdf": "Risikoprofil, keine Allokation",
        "GET /mandates/{mandate_id}/reports/vertrag.pdf": "Vertragsdokument, keine Allokation",
        "GET /mandates/{mandate_id}/reports/contract-signoff.pdf": "Sign-off, keine Allokation",
        "GET /client-portal/mandates/{mandate_id}/report": "Kundenportal: Publish-Gate in routers/client_portal.py",
        "GET /mandates/{mandate_id}/advisory-report": "React-Bericht: DRAFT_MARKED (routers/allocation.py)",
    }
    pdf_functions = _functions("routers/pdf_reports.py")
    route_to_function = {}
    for node in pdf_functions.values():
        for deco in node.decorator_list:
            if isinstance(deco, ast.Call) and deco.args and isinstance(deco.args[0], ast.Constant):
                route_to_function[f"GET {deco.args[0].value}"] = node.name
    for route, (klass, _why) in REPORT_ROUTE_CLASSIFICATION.items():
        if klass != REPORT_CLIENT_FACING or route in allocation_free:
            continue
        name = route_to_function.get(route)
        assert name in CUSTOMER_ENDPOINTS["routers/pdf_reports.py"], f"{route} nicht klassifiziert"


def test_publication_bypass_is_limited_to_the_documented_legacy_files():
    from tests.ccx_p4_publication_support import LEGACY_CHANNEL_TEST_FILES

    users = sorted(
        p.name for p in (BACKEND / "tests").glob("test_*.py")
        if "assume_published_allocation" in p.read_text(encoding="utf-8") and p.name != Path(__file__).name
    )
    assert users == sorted(LEGACY_CHANNEL_TEST_FILES)


def test_publish_never_on_default_fx_rate_or_unbelegted_basis():
    """N-909-01: COMPLETE allein genuegt nicht -- die gebundene FX-Basis muss
    strikt sein (kein Ersatzkurs ``Default``, alle Kurse OK, Hash konsistent)."""
    from types import SimpleNamespace

    from services.allocation_publication_gate import _fx_basis_findings

    def snap(quotes, statuses, h="a" * 64, basis_hash=None):
        basis = {"schema": "x", "target_currency": "CHF", "as_of": "2026-11-14",
                 "fx_basis_hash": basis_hash or h, "quotes": quotes, "statuses": statuses}
        return SimpleNamespace(fx_basis_json=json.dumps(basis), fx_basis_hash=h)

    ok_quote = {"currency": "USD", "rate_x10000": 8000, "source": "Manual", "observed_at": "2026-11-14",
                "rate_id": "r"}
    assert _fx_basis_findings(snap([], {})) == []
    assert _fx_basis_findings(snap([ok_quote], {"USD": "OK"})) == []
    blocked = ["CCX_FX_BASIS_MISSING"]
    assert _fx_basis_findings(snap([{**ok_quote, "source": "Default"}], {"USD": "OK"})) == blocked
    assert _fx_basis_findings(snap([ok_quote], {"USD": "STALE"})) == blocked
    assert _fx_basis_findings(snap([{**ok_quote, "rate_x10000": 0}], {"USD": "OK"})) == blocked
    assert _fx_basis_findings(snap([ok_quote], {"USD": "OK"}, basis_hash="b" * 64)) == blocked
    assert _fx_basis_findings(SimpleNamespace(fx_basis_json="kein json", fx_basis_hash="a" * 64)) == blocked


def test_single_approver_attestation_is_visibly_marked_in_evidence_and_audit(session_factory, monkeypatch):
    """Ein-Personen-Firma: Einzelfreigabe nur mit Begruendung >= 20 Zeichen;
    im Nachweis (Modus im approval_hash, Status) und im Audit sichtbar als
    "Einzelfreigabe (eine berechtigte Person)"."""
    import services.allocation_publication_gate as gate

    advisor_id, mid, _aid, _run = _finalized(session_factory, "single")
    monkeypatch.setattr(gate, "tenant_approver_ids", lambda db, tenant_id, roles=(): [advisor_id])
    _blocked(session_factory, mid, advisor_id, "CCX_APPROVAL_BINDING_MISSING",
             single_approver_attestation=True, attestation_reason="zu kurz")
    decision = _publish(session_factory, mid, advisor_id, single_approver_attestation=True,
                        attestation_reason="Einzige freigabeberechtigte Person der Firma.")
    assert decision.approval_mode == "single_approver_attested"
    state = _state(session_factory, mid)
    assert state.published and state.as_dict()["approval_mode_label"] == "Einzelfreigabe (eine berechtigte Person)"
    with session_factory() as db:
        audit = _audit(db, "ccx.allocation.published")
        assert "approval_label=Einzelfreigabe (eine berechtigte Person)" in audit[-1].new_value
        assert "attestation_reason=Einzige freigabeberechtigte Person der Firma." in audit[-1].new_value
    overview = _overview(session_factory, mid)
    assert overview["active_publication"]["approval_mode_label"] == "Einzelfreigabe (eine berechtigte Person)"
    # Gegenprobe: mit zwei berechtigten Personen ist Einzelfreigabe nie zulaessig.
    from services.allocation_publication_gate import approval_mode_for

    monkeypatch.setattr(gate, "tenant_approver_ids", lambda db, tenant_id, roles=(): [advisor_id, "zweite"])
    with session_factory() as db:
        assert approval_mode_for(db, tenant_id="t", approver_id=advisor_id, preparer_id=advisor_id,
                                 single_approver_attestation=True,
                                 attestation_reason="Einzige freigabeberechtigte Person der Firma.") is None


# ── Konsumenten ──────────────────────────────────────────────────────────────


def test_customer_documents_are_drafts_until_published_and_pdf_right_before_commit(session_factory):
    """Kunden-PDF: Entwurf (Wasserzeichen, nie archiviert), solange nicht
    publiziert -- auch direkt vor dem Commit der Publikation (andere Session
    sieht nur den committeten Stand); danach final."""
    from models.users import User
    import services.allocation_publication_gate as gate

    advisor_id, mid, _aid, _run = _finalized(session_factory, "pdf")
    approver = _second_approver(session_factory, advisor_id)
    with session_factory() as db:
        assert gate.customer_document_watermark(db, _mandate(db, mid)) == "unpublished"
    overview = _overview(session_factory, mid)
    with session_factory() as publisher:
        user = publisher.query(User).filter(User.id == approver).one()
        original_commit = publisher.commit
        seen = {}

        def commit_after_probe():
            with session_factory() as reader:  # PDF direkt vor dem Commit
                seen["before"] = gate.customer_document_watermark(reader, _mandate(reader, mid))
            original_commit()

        publisher.commit = commit_after_probe
        gate.publish_allocation(publisher, _mandate(publisher, mid), user=user,
                                expected_validation_hash=overview["validation_hash"],
                                expected_target_allocation_id=overview["target_allocation_id"])
    assert seen["before"] == "unpublished"
    with session_factory() as db:
        assert gate.customer_document_watermark(db, _mandate(db, mid)) is None


def test_channel_gate_blocks_unpublished_with_code_and_audit_then_allows(session_factory):
    from models.users import User
    from services.allocation_publication_gate import require_published_allocation

    advisor_id, mid, _aid, _run = _finalized(session_factory, "chan")
    with session_factory() as db:
        user = db.query(User).filter(User.id == advisor_id).one()
        with pytest.raises(DomainError) as exc:
            require_published_allocation(db, _mandate(db, mid), channel="handoff", user=user)
        assert exc.value.reason_code == "CCX_ALLOCATION_NOT_PUBLISHABLE"
        assert exc.value.extra["publication_status"] == "DRAFT"
        audit = _audit(db, "ccx.allocation.channel_blocked")
        assert audit and audit[-1].mandate_id == mid and audit[-1].tenant_id
    _publish(session_factory, mid, _second_approver(session_factory, advisor_id))
    with session_factory() as db:
        user = db.query(User).filter(User.id == advisor_id).one()
        state = require_published_allocation(db, _mandate(db, mid), channel="handoff", user=user)
        assert state.published


def test_tenant_idor_foreign_mandate_publication_is_invisible(session_factory):
    from fastapi import HTTPException

    from models.tenant import Tenant
    from models.users import User
    from routers.allocation import get_allocation_publication

    advisor_id, approver, mid, *_rest = _published(session_factory, "idor")
    with session_factory() as db:
        db.add(Tenant(id="t-idor-p4", display_name="Andere Firma", slug="andere-p4",
                      created_at="2026-11-14T00:00:00Z", updated_at="2026-11-14T00:00:00Z"))
        db.add(User(id="adv-idor-p4", username="adv-idor-p4", password_hash="h", full_name="Fremd",
                    role="advisor", is_active=1, tenant_id="t-idor-p4",
                    created_at="2026-11-14T00:00:00Z", updated_at="2026-11-14T00:00:00Z"))
        db.commit()
        with pytest.raises(HTTPException) as caught:
            get_allocation_publication(mandate_id=mid, db=db, current_user=db.get(User, "adv-idor-p4"))
        assert caught.value.status_code == 404
        assert db.execute(text(
            "SELECT count(*) FROM allocation_active_publications WHERE tenant_id = 't-idor-p4'")).scalar() == 0
        own = get_allocation_publication(mandate_id=mid, db=db, current_user=db.get(User, advisor_id))
        assert own["publication_status"] == "PUBLISHED"


def test_pointer_requires_current_allocation_even_if_hooks_were_bypassed(session_factory):
    """Zweite Linie: wird die aktuelle Soll-Allokation am Mutation Hook vorbei
    ausgetauscht (rohe Verbindung, Envelope bleibt FRESH), gilt die alte
    Publikation trotzdem nicht -- der Pointer verlangt genau die aktuelle TA."""
    import sqlite3

    advisor_id, approver, mid, *_rest, decision = _published(session_factory, "bypass")
    with session_factory() as db:
        path = db.get_bind().url.database
    conn = sqlite3.connect(path)
    try:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(target_allocations)")]
        conn.execute("UPDATE target_allocations SET is_current = 0 WHERE id = ?", (decision.target_allocation_id,))
        select = ", ".join("? AS id" if c == "id" else ("1 AS is_current" if c == "is_current" else c) for c in cols)
        conn.execute(f"INSERT INTO target_allocations ({', '.join(cols)}) SELECT {select} FROM target_allocations "
                     "WHERE id = ?", ("ta-roh-" + uuid.uuid4().hex[:6], decision.target_allocation_id))
        conn.commit()
        assert conn.execute("SELECT freshness_status FROM advisory_decision_envelopes WHERE id = ?",
                            (decision.envelope_id,)).fetchone()[0] == "FRESH"
    finally:
        conn.close()
    state = _state(session_factory, mid)
    assert state.status == "PUBLICATION_INVALID" and state.reason_code == "CCX_ALLOCATION_NOT_PUBLISHABLE"
    assert _state(session_factory, mid, deep=False).status == "PUBLICATION_INVALID"


def test_tampered_approval_binding_invalidates_publication(session_factory):
    """Approval-Binding: ein (am Append-only-Trigger vorbei) veraenderter
    Freigeber bzw. Zeitpunkt passt nicht mehr zum approval_hash -> die
    Publikation gilt nicht (CCX_APPROVAL_BINDING_MISSING), kein Fallback."""
    advisor_id, approver, mid, *_rest, decision = _published(session_factory, "tamper")
    assert _state(session_factory, mid).published
    with session_factory() as db:
        db.execute(text("DROP TRIGGER trg_allocation_publication_decisions_no_update"))
        db.execute(text("UPDATE allocation_publication_decisions SET approved_at = '2020-01-01T00:00:00.000000Z' "
                        "WHERE id = :i"), {"i": decision.id})
        db.commit()
    state = _state(session_factory, mid)
    assert state.status == "PUBLICATION_INVALID" and state.reason_code == "CCX_APPROVAL_BINDING_MISSING"
