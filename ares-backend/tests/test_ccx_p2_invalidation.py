"""CCX-P2 Invalidation und Staleness -- Pflichtregressionen (Vertrag 2026-11-13 §5).

Abgedeckt (SQLite, echter Finalisierungspfad):

* Versiegelung schreibt je Abhaengigkeit eine Kante und setzt FRESH; leere
  Pflicht-Inputgruppe -> UNKNOWN (unknown != fresh).
* Jede Abhaengigkeit einzeln mutiert -> Ereignis (Sequenz 1) + STALE im selben
  Commit + Audit ``ccx.envelope.invalidated`` (zentraler Mutation Hook).
* Wiederholungsmutation idempotent; Rueckkehr zu A erzeugt keinen FRESH-Status.
* Gate: STALE -> CCX_INPUT_STALE, UNKNOWN -> CCX_FRESHNESS_UNKNOWN (Audit,
  kein Fallback); Pull-Pruefung findet Mutationen am Hook vorbei.
* Wettlauf Mutation <-> Versiegelung (CCX_INVALIDATION_RACE), verspaetetes
  Ergebnis A nach Wechsel zu B (CCX_RESULT_SUPERSEDED), parallele Mutationen
  mit eindeutiger, lueckenloser invalidation_sequence.
* Trigger: Frische-Uebergaenge, append-only, kein REPLACE/UPSERT, Mandant.
* Consumer: allocation_inputs_stale, Dokumentarchiv, Cache-Scope, Statusroute.
* CCX-01/CCX-06-Adapter, Migration (genau ein Head, up/down/up, Paritaet).

PostgreSQL (RLS, Trigger, echte parallele Transaktionen):
``tests/test_postgres_ccx_p2_invalidation_live.py``.
"""
from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from core.reason_codes import DomainError
from tests.test_ccx_p1_snapshot_hash import _audit, _finalizable_run, _finalize
from tests.test_optimizer_shadow_mode import session_factory  # noqa: F401

CCX_P2_REV = "d868f4eaa028"
CCX_P1_REV = "2c62f9012c73"
BACKEND = Path(__file__).resolve().parents[1]
NOW = "2026-11-14T00:00:00.000000Z"


def _sealed(session_factory, suffix):
    advisor_id, mid, aid, run_id = _finalizable_run(session_factory, suffix)
    result = _finalize(session_factory, advisor_id, mid, run_id)
    return advisor_id, mid, aid, run_id, result.advisory_envelope_id


def _envelope(db, envelope_id):
    return db.execute(text(
        "SELECT status, freshness_status, stale_at, stale_reason_code, optimistic_version "
        "FROM advisory_decision_envelopes WHERE id = :e"), {"e": envelope_id}).one()


def _events(db, envelope_id):
    return db.execute(text(
        "SELECT invalidation_sequence, source_kind, source_object_id, old_hash, new_hash, reason_code, "
        "created_by, mandate_id, tenant_id FROM advisory_invalidation_events WHERE envelope_id = :e "
        "ORDER BY invalidation_sequence"), {"e": envelope_id}).all()


def _gate(db, mid, advisor_id):
    from models.mandates import Mandate
    from models.users import User
    from services.advisory_decision_envelope import current_verified_envelope

    return current_verified_envelope(db, mandate=db.get(Mandate, mid), user=db.get(User, advisor_id))


# ── Versiegelung: Kanten und FRESH ───────────────────────────────────────────


def test_seal_writes_one_edge_per_dependency_and_is_fresh(session_factory):
    from models.snapshots import DEPENDENCY_KINDS
    from services.effective_input_manifest import components_from_parts, DependencyPart

    advisor_id, mid, _aid, _run, envelope_id = _sealed(session_factory, "edges")
    with session_factory() as db:
        row = _envelope(db, envelope_id)
        assert (row.status, row.freshness_status, row.stale_at, row.stale_reason_code) == (
            "SEALED", "FRESH", None, None)
        edges = db.execute(text(
            "SELECT dependency_kind, dependency_object_id, dependency_version, dependency_hash, tenant_id "
            "FROM advisory_dependency_edges WHERE envelope_id = :e"), {"e": envelope_id}).all()
        assert sorted(e.dependency_kind for e in edges) == sorted(DEPENDENCY_KINDS)
        assert all(len(e.dependency_hash) == 64 for e in edges)
        manifest = db.execute(text(
            "SELECT * FROM advisory_effective_input_manifests m JOIN advisory_envelope_bindings b "
            "ON b.object_id = m.id WHERE b.envelope_id = :e AND b.binding_kind = 'effective_input_manifest'"),
            {"e": envelope_id}).mappings().one()
        parts = [DependencyPart(e.dependency_kind, e.dependency_object_id, e.dependency_version,
                                e.dependency_hash) for e in edges]
        # Kanten sind exakt die Kind-Hashes des versiegelten Manifests.
        for name, value in components_from_parts(parts).items():
            assert manifest[name] == value, name
        view = _gate(db, mid, advisor_id)
        assert view["freshness_status"] == "FRESH"


def test_empty_required_input_group_seals_unknown_never_fresh(session_factory, monkeypatch):
    """Leere Pflicht-Inputgruppe -> UNKNOWN. Ohne Ziele/Risikoprofil/Policy
    blockt bereits die Finalisierungsvalidierung (P0) bzw. das P1-Manifest
    (ManifestIncomplete); hier wird deshalb eine leere Benchmark-Gruppe in der
    Kantenlesung simuliert (alle anderen Teile echt)."""
    from dataclasses import replace

    import services.effective_input_manifest as manifest
    from services.effective_input_manifest import REQUIRED_DEPENDENCY_KINDS, empty_required_kinds

    assert REQUIRED_DEPENDENCY_KINDS >= {"risk", "cma", "optimizer_policy", "constraints", "benchmark"}
    advisor_id, mid, _aid, run_id = _finalizable_run(session_factory, "emptyreq")
    real = manifest.collect_dependency_parts

    def without_benchmark(db, **kw):  # Policy ohne Hausmatrix-Zeilen
        return [replace(p, row_count=0) if p.kind == "benchmark" else p for p in real(db, **kw)]

    monkeypatch.setattr(manifest, "collect_dependency_parts", without_benchmark)
    result = _finalize(session_factory, advisor_id, mid, run_id)
    with session_factory() as db:
        assert _envelope(db, result.advisory_envelope_id).freshness_status == "UNKNOWN"
        with pytest.raises(DomainError) as caught:
            _gate(db, mid, advisor_id)
    assert caught.value.reason_code == "CCX_FRESHNESS_UNKNOWN"


# ── Jede Abhaengigkeit einzeln mutieren ──────────────────────────────────────


def _mutate_goal(db, ids):
    from models.wealth import Goal
    goal = db.query(Goal).filter(Goal.mandate_id == ids["mid"], Goal.rank == 1).one()
    goal.target_amount_rappen += 100
    return "goals", goal.id


def _mutate_cashflow(db, ids):
    from models.wealth import Cashflow
    row = db.query(Cashflow).filter(Cashflow.client_id == ids["cid"]).first()
    row.amount_rappen += 100
    return "cashflows", row.id


def _insert_inflow(db, ids):
    from database import new_uuid
    from models.wealth import WealthInflow
    row = WealthInflow(id=new_uuid(), client_id=ids["cid"], label="Erbe", source_type="Erbschaft",
                       amount_rappen=10_000_00, expected_year=2030, created_at=NOW, updated_at=NOW)
    db.add(row)
    return "wealth_inflows", row.id


def _mutate_position(db, ids):
    from models.wealth import WealthPosition
    row = db.query(WealthPosition).filter(WealthPosition.client_id == ids["cid"]).first()
    row.current_value_rappen += 100
    return "positions", row.id


def _mutate_risk(db, ids):
    from models.profiling import RiskAssessment
    row = db.get(RiskAssessment, ids["aid"])
    row.investment_horizon_years = 14
    return "risk", row.id


def _mutate_risk_answer(db, ids):
    from models.profiling import RiskAssessmentAnswer
    row = db.query(RiskAssessmentAnswer).filter(RiskAssessmentAnswer.assessment_id == ids["aid"]).first()
    row.answer_points = (row.answer_points or 0) + 1
    return "risk", row.id


def _mutate_mandate(db, ids):
    from models.mandates import Mandate
    row = db.get(Mandate, ids["mid"])
    row.mandate_number = row.mandate_number + "x"
    return "mandate", row.id


def _mutate_client(db, ids):
    from models.clients import Client
    row = db.get(Client, ids["cid"])
    row.notes = "geaendert"
    return "client", row.id


def _mutate_allocation(db, ids):
    from models.allocation import TargetAllocation
    row = db.get(TargetAllocation, ids["ta"])
    row.band_equities_max_bps = row.band_equities_max_bps - 1
    return "constraints", row.id


def _mutate_cma(db, ids):
    from models.allocation import CapitalMarketAssumption
    row = db.get(CapitalMarketAssumption, ids["cma"])
    row.notes = (row.notes or "") + " geaendert"
    return "cma", row.id


def _mutate_policy(db, ids):
    from models.allocation import OptimizerPolicy
    row = db.get(OptimizerPolicy, ids["policy"])
    row.notes = (row.notes or "") + " geaendert"
    return "optimizer_policy", row.id


def _mutate_house_matrix(db, ids):
    from models.allocation import HouseMatrix
    row = db.query(HouseMatrix).filter(HouseMatrix.policy_id == ids["policy"]).first()
    row.profile_name = row.profile_name + " v2"
    return "benchmark", row.id


def _insert_run_holding(db, ids):
    from database import new_uuid
    from models.review import RecommendationHolding, RecommendationPosition
    position = db.query(RecommendationPosition).filter(RecommendationPosition.run_id == ids["run"]).first()
    row = RecommendationHolding(id=new_uuid(), run_id=ids["run"], recommendation_position_id=position.id,
                                product_id=position.product_id, created_at=NOW, updated_at=NOW)
    db.add(row)
    return "run_holdings", row.id


MUTATIONS = [
    _mutate_goal, _mutate_cashflow, _insert_inflow, _mutate_position, _mutate_risk, _mutate_risk_answer,
    _mutate_mandate, _mutate_client, _mutate_allocation, _mutate_cma, _mutate_policy, _mutate_house_matrix,
    _insert_run_holding,
]


def _ids(session_factory, suffix):
    advisor_id, mid, aid, run_id, envelope_id = _sealed(session_factory, suffix)
    with session_factory() as db:
        row = db.execute(text(
            "SELECT m.client_id, r.target_allocation_id, r.capital_market_assumptions_id, t.policy_id "
            "FROM mandates m JOIN recommendation_runs r ON r.mandate_id = m.id "
            "JOIN target_allocations t ON t.id = r.target_allocation_id WHERE r.id = :r"), {"r": run_id}).one()
    return {"advisor": advisor_id, "mid": mid, "aid": aid, "run": run_id, "envelope": envelope_id,
            "cid": row[0], "ta": row[1], "cma": row[2], "policy": row[3]}


@pytest.mark.parametrize("mutate", MUTATIONS, ids=[m.__name__ for m in MUTATIONS])
def test_each_dependency_mutation_invalidates_in_same_commit(session_factory, mutate):
    ids = _ids(session_factory, "dep-" + mutate.__name__[-8:])
    with session_factory() as db:
        db.info["ares_actor_user_id"] = ids["advisor"]
        kind, object_id = mutate(db, ids)
        db.commit()
    with session_factory() as db:
        row = _envelope(db, ids["envelope"])
        assert (row.status, row.freshness_status, row.stale_reason_code) == ("SEALED", "STALE", "CCX_INPUT_STALE")
        assert row.stale_at and row.optimistic_version == 3
        events = _events(db, ids["envelope"])
        assert [(e.invalidation_sequence, e.source_kind, e.source_object_id) for e in events] == [
            (1, kind, object_id)]
        assert events[0].created_by == ids["advisor"] and events[0].mandate_id == ids["mid"]
        assert events[0].reason_code == "CCX_INPUT_STALE"
        audit = _audit(db, "ccx.envelope.invalidated")
        assert len(audit) == 1 and audit[0].record_id == ids["envelope"] and audit[0].mandate_id == ids["mid"]
        assert "invalidation_sequence=1" in audit[0].new_value and f"source_kind={kind}" in audit[0].new_value
        assert audit[0].tenant_id == events[0].tenant_id
        with pytest.raises(DomainError) as caught:
            _gate(db, ids["mid"], ids["advisor"])
        assert caught.value.reason_code == "CCX_INPUT_STALE"


def test_rolled_back_mutation_leaves_no_event_and_stays_fresh(session_factory):
    ids = _ids(session_factory, "rollback")
    with session_factory() as db:
        _mutate_goal(db, ids)
        db.flush()
        assert _envelope(db, ids["envelope"]).freshness_status == "STALE"  # gleiche Transaktion
        db.rollback()
    with session_factory() as db:
        assert _envelope(db, ids["envelope"]).freshness_status == "FRESH"
        assert _events(db, ids["envelope"]) == []
        assert _audit(db, "ccx.envelope.invalidated") == []


def test_unrelated_mandate_mutation_does_not_invalidate(session_factory):
    a = _ids(session_factory, "iso-a")
    b = _ids(session_factory, "iso-b")
    with session_factory() as db:
        _mutate_goal(db, b)
        db.commit()
    with session_factory() as db:
        assert _envelope(db, a["envelope"]).freshness_status == "FRESH"
        assert _envelope(db, b["envelope"]).freshness_status == "STALE"


def test_repeat_mutation_is_idempotent_and_return_to_a_stays_stale(session_factory):
    from models.wealth import Goal

    ids = _ids(session_factory, "repeat")
    with session_factory() as db:
        goal = db.query(Goal).filter(Goal.mandate_id == ids["mid"], Goal.rank == 1).one()
        original = goal.target_amount_rappen
        goal.target_amount_rappen = original + 500  # A -> B
        db.commit()
    with session_factory() as db:
        goal = db.query(Goal).filter(Goal.mandate_id == ids["mid"], Goal.rank == 1).one()
        goal.target_amount_rappen = original + 500  # B -> B: Leermutation
        goal.updated_at = "2099-01-01T00:00:00Z"  # updated_at ist fluechtig
        db.commit()
    with session_factory() as db:
        assert [e.invalidation_sequence for e in _events(db, ids["envelope"])] == [1]
        first = _envelope(db, ids["envelope"])
        goal = db.query(Goal).filter(Goal.mandate_id == ids["mid"], Goal.rank == 1).one()
        goal.target_amount_rappen = original  # B -> A
        db.commit()
    with session_factory() as db:
        row = _envelope(db, ids["envelope"])
        assert row.freshness_status == "STALE"  # keine Frische ohne neue Berechnung
        assert (row.stale_at, row.stale_reason_code) == (first.stale_at, first.stale_reason_code)
        assert [e.invalidation_sequence for e in _events(db, ids["envelope"])] == [1, 2]
        with pytest.raises(DomainError) as caught:
            _gate(db, ids["mid"], ids["advisor"])
        assert caught.value.reason_code == "CCX_INPUT_STALE"


def test_bulk_orm_update_invalidates_and_bulk_insert_is_refused(session_factory):
    from sqlalchemy import insert

    from models.wealth import Goal

    ids = _ids(session_factory, "bulk")
    with session_factory() as db:
        db.query(Goal).filter(Goal.mandate_id == ids["mid"]).update({"weight_bps": 4000})
        db.commit()
    with session_factory() as db:
        assert _envelope(db, ids["envelope"]).freshness_status == "STALE"
        assert {e.source_kind for e in _events(db, ids["envelope"])} == {"goals"}
        with pytest.raises(RuntimeError, match="CCX-P2"):
            db.execute(insert(Goal), [{"id": "g-bulk", "mandate_id": ids["mid"]}])
        db.rollback()


# ── Gate und Pull-Pruefung ───────────────────────────────────────────────────


def test_gate_rejects_stale_with_code_audit_and_no_fallback(session_factory):
    from fastapi import HTTPException  # noqa: F401  (Router wirft DomainError)

    ids = _ids(session_factory, "gate")
    # Zweiter, frischer Entscheid A2 waere ein Fallback-Kandidat -- es gibt keinen.
    with session_factory() as db:
        _mutate_goal(db, ids)
        db.commit()
    with session_factory() as db:
        with pytest.raises(DomainError) as caught:
            _gate(db, ids["mid"], ids["advisor"])
        assert caught.value.reason_code == "CCX_INPUT_STALE"
        assert caught.value.http_status == 409
        rejected = _audit(db, "ccx.envelope.rejected")
        assert rejected and "reason_code=CCX_INPUT_STALE" in rejected[-1].new_value
        assert rejected[-1].mandate_id == ids["mid"] and rejected[-1].tenant_id


def test_gate_unknown_freshness_is_never_fresh(session_factory):
    ids = _ids(session_factory, "unknown")
    with session_factory() as db:
        db.execute(text("DROP TRIGGER trg_advisory_decision_envelopes_update_guard"))
        db.execute(text("UPDATE advisory_decision_envelopes SET freshness_status = 'UNKNOWN' WHERE id = :e"),
                   {"e": ids["envelope"]})
        db.commit()
        with pytest.raises(DomainError) as caught:
            _gate(db, ids["mid"], ids["advisor"])
    assert caught.value.reason_code == "CCX_FRESHNESS_UNKNOWN"


def test_pull_check_catches_mutation_around_the_hook(session_factory):
    ids = _ids(session_factory, "pull")
    with session_factory() as db:  # rohes SQL umgeht den ORM-Hook
        db.execute(text("UPDATE goals SET target_amount_rappen = target_amount_rappen + 1 "
                        "WHERE mandate_id = :m AND rank = 1"), {"m": ids["mid"]})
        db.commit()
        assert _envelope(db, ids["envelope"]).freshness_status == "FRESH"
        with pytest.raises(DomainError) as caught:
            _gate(db, ids["mid"], ids["advisor"])
        assert caught.value.reason_code == "CCX_INPUT_STALE"
    with session_factory() as db:
        assert _envelope(db, ids["envelope"]).freshness_status == "STALE"
        events = _events(db, ids["envelope"])
        assert [(e.invalidation_sequence, e.source_kind) for e in events] == [(1, "goals")]
        assert events[0].old_hash and events[0].new_hash and events[0].old_hash != events[0].new_hash
        assert "operation=gate_drift" in _audit(db, "ccx.envelope.invalidated")[0].new_value


# ── Wettlauf und verspaetetes Ergebnis ───────────────────────────────────────


def test_mutation_during_sealing_is_invalidation_race(session_factory, monkeypatch):
    import services.advisory_decision_envelope as svc
    from models.wealth import Goal

    advisor_id, mid, _aid, run_id = _finalizable_run(session_factory, "race-seal")
    real = svc.collect_effective_input_components
    calls = {"n": 0}

    def mutate_between(db, **kw):
        calls["n"] += 1
        if calls["n"] == 2:  # nach dem DRAFT, vor dem Siegel
            goal = db.query(Goal).filter(Goal.mandate_id == mid, Goal.rank == 1).one()
            goal.target_amount_rappen += 1
            db.flush()
        return real(db, **kw)

    monkeypatch.setattr(svc, "collect_effective_input_components", mutate_between)
    with pytest.raises(DomainError) as caught:
        _finalize(session_factory, advisor_id, mid, run_id)
    assert caught.value.reason_code == "CCX_INVALIDATION_RACE"
    with session_factory() as db:
        assert db.execute(text("SELECT count(*) FROM advisory_decision_envelopes")).scalar() == 0
        assert db.execute(text("SELECT count(*) FROM advisory_invalidation_events")).scalar() == 0
        assert db.execute(text("SELECT result_status FROM recommendation_runs WHERE id = :r"),
                          {"r": run_id}).scalar() == "Draft"
        race = _audit(db, "ccx.envelope.race_rejected")
        assert len(race) == 1 and "reason_code=CCX_INVALIDATION_RACE" in race[0].new_value
        assert race[0].mandate_id == mid and race[0].tenant_id


def test_late_result_a_after_switch_to_b_is_superseded(session_factory):
    from models.mandates import Mandate
    from models.review import RecommendationRun
    from routers.review import finalize_recommendation
    from models.users import User
    from services.advisory_decision_envelope import current_input_manifest_hash
    from tests.test_finalize_mandate_lock import _FakeRequest
    from tests.sustainability_test_support import answer_question_one_for_all_mandates

    advisor_id, mid, _aid, run_id = _finalizable_run(session_factory, "late")
    with session_factory() as db:  # Start der Berechnung auf Stand A (ESG-Erfassung vorhanden)
        answer_question_one_for_all_mandates(db)
        db.commit()
        started_a = current_input_manifest_hash(
            db, mandate=db.get(Mandate, mid), run=db.get(RecommendationRun, run_id))
        # Mandatsdaten (nicht Teil des input_snapshot_hash der Allokation,
        # sonst blockte bereits die P0-Pruefung): A -> B
        mandate = db.get(Mandate, mid)
        original = mandate.mandate_number
        mandate.mandate_number = original + "-B"
        db.commit()
    with session_factory() as db:
        answer_question_one_for_all_mandates(db)
        with pytest.raises(DomainError) as caught:
            finalize_recommendation(mandate_id=mid, run_id=run_id, request=_FakeRequest(), db=db,
                                    current_user=db.get(User, advisor_id), expected_input_manifest_hash=started_a)
    assert caught.value.reason_code == "CCX_RESULT_SUPERSEDED"
    with session_factory() as db:
        assert db.execute(text("SELECT count(*) FROM advisory_decision_envelopes")).scalar() == 0
        assert "reason_code=CCX_RESULT_SUPERSEDED" in _audit(db, "ccx.envelope.race_rejected")[0].new_value
        db.get(Mandate, mid).mandate_number = original  # zurueck zu A
        db.commit()
    with session_factory() as db:  # identische Inputs A -> das Ergebnis A ist wieder zulaessig
        answer_question_one_for_all_mandates(db)
        result = finalize_recommendation(mandate_id=mid, run_id=run_id, request=_FakeRequest(), db=db,
                                         current_user=db.get(User, advisor_id),
                                         expected_input_manifest_hash=started_a)
    with session_factory() as db:
        assert _envelope(db, result.advisory_envelope_id).freshness_status == "FRESH"


def test_parallel_mutations_get_unique_gapless_sequences(session_factory):
    from models.wealth import Cashflow, Goal

    ids = _ids(session_factory, "seq")
    for step in range(3):
        with session_factory() as db:
            goal = db.query(Goal).filter(Goal.mandate_id == ids["mid"], Goal.rank == 1).one()
            goal.target_amount_rappen += 1
            cashflow = db.query(Cashflow).filter(Cashflow.client_id == ids["cid"]).first()
            cashflow.amount_rappen += 1
            db.commit()
    with session_factory() as db:
        assert [e.invalidation_sequence for e in _events(db, ids["envelope"])] == [1, 2, 3, 4, 5, 6]
        tenant = db.execute(text("SELECT tenant_id FROM mandates WHERE id = :m"), {"m": ids["mid"]}).scalar()
        insert = (
            "INSERT INTO advisory_invalidation_events (id, tenant_id, mandate_id, envelope_id, source_kind, "
            "source_object_id, reason_code, invalidation_sequence, created_at, created_by) VALUES "
            "(:id, :t, :m, :e, 'goals', 'g', 'CCX_INPUT_STALE', :seq, :now, 'system')"
        )
        for seq in (6, 8, 0):  # doppelt, Luecke, ungueltig
            with pytest.raises((IntegrityError, DBAPIError)):
                db.execute(text(insert), {"id": f"ev-{seq}", "t": tenant, "m": ids["mid"], "e": ids["envelope"],
                                          "seq": seq, "now": NOW})
            db.rollback()


# ── Trigger ──────────────────────────────────────────────────────────────────


REJECTED_STATEMENTS = [
    # zurueck auf FRESH / Frische ohne Versionssprung / stale_at umschreiben
    "UPDATE advisory_decision_envelopes SET freshness_status = 'FRESH', stale_at = NULL, "
    "stale_reason_code = NULL, optimistic_version = optimistic_version + 1",
    "UPDATE advisory_decision_envelopes SET freshness_status = 'UNKNOWN', stale_at = NULL, "
    "stale_reason_code = NULL, optimistic_version = optimistic_version + 1",
    "UPDATE advisory_decision_envelopes SET stale_at = '2000-01-01T00:00:00.000000Z', "
    "optimistic_version = optimistic_version + 1",
    "UPDATE advisory_decision_envelopes SET stale_reason_code = 'X', optimistic_version = optimistic_version + 1",
    "UPDATE advisory_decision_envelopes SET stale_at = NULL, optimistic_version = optimistic_version + 1",
    # Ereignisse und Kanten append-only
    "UPDATE advisory_invalidation_events SET new_hash = NULL",
    "DELETE FROM advisory_invalidation_events",
    "UPDATE advisory_dependency_edges SET dependency_hash = '" + "0" * 64 + "'",
    "DELETE FROM advisory_dependency_edges",
    "INSERT INTO advisory_dependency_edges (id, tenant_id, envelope_id, dependency_kind, dependency_object_id, "
    "dependency_hash, observed_at, created_by) SELECT 'd-x', tenant_id, id, 'extra', 'x', '" + "0" * 64
    + "', created_at, created_by FROM advisory_decision_envelopes",
    # kein REPLACE/UPSERT am Append-only-Schutz vorbei (N-906-01-Muster)
    "INSERT OR REPLACE INTO advisory_invalidation_events SELECT * FROM advisory_invalidation_events",
    "REPLACE INTO advisory_dependency_edges SELECT * FROM advisory_dependency_edges",
    "INSERT INTO advisory_invalidation_events SELECT * FROM advisory_invalidation_events WHERE true "
    "ON CONFLICT(id) DO UPDATE SET new_hash = NULL",
    "INSERT INTO advisory_dependency_edges SELECT * FROM advisory_dependency_edges WHERE true "
    "ON CONFLICT(id) DO UPDATE SET dependency_hash = '" + "1" * 64 + "'",
]


@pytest.mark.parametrize("statement", REJECTED_STATEMENTS)
def test_freshness_and_evidence_rows_are_guarded(session_factory, statement):
    ids = _ids(session_factory, "trig")
    with session_factory() as db:
        _mutate_goal(db, ids)
        db.commit()
    with session_factory() as db:
        before = (db.execute(text("SELECT freshness_status, stale_at, optimistic_version FROM "
                                  "advisory_decision_envelopes")).all(),
                  db.execute(text("SELECT * FROM advisory_invalidation_events")).all(),
                  db.execute(text("SELECT * FROM advisory_dependency_edges ORDER BY id")).all())
        with pytest.raises((IntegrityError, DBAPIError)):
            db.execute(text(statement))
        db.rollback()
        after = (db.execute(text("SELECT freshness_status, stale_at, optimistic_version FROM "
                                 "advisory_decision_envelopes")).all(),
                 db.execute(text("SELECT * FROM advisory_invalidation_events")).all(),
                 db.execute(text("SELECT * FROM advisory_dependency_edges ORDER BY id")).all())
        assert after == before


def test_fresh_requires_edges_and_insert_only_unknown(session_factory):
    advisor_id, mid, _aid, _run = _finalizable_run(session_factory, "fresh-edges")
    with session_factory() as db:
        tenant = db.execute(text("SELECT tenant_id FROM mandates WHERE id = :m"), {"m": mid}).scalar()
        insert = (
            "INSERT INTO advisory_decision_envelopes (id, tenant_id, mandate_id, schema_version, status, locale, "
            "base_currency, created_at, created_by, optimistic_version, freshness_status) VALUES "
            "(:id, :t, :m, 'ares/advisory-envelope/1', 'DRAFT', 'DE', 'CHF', :now, :u, 1, :f)"
        )
        with pytest.raises((IntegrityError, DBAPIError)):
            db.execute(text(insert), {"id": "e-f", "t": tenant, "m": mid, "now": NOW, "u": advisor_id, "f": "FRESH"})
        db.rollback()
        db.execute(text(insert), {"id": "e-u", "t": tenant, "m": mid, "now": NOW, "u": advisor_id, "f": "UNKNOWN"})
        db.execute(text(
            "INSERT INTO advisory_envelope_bindings (id, tenant_id, envelope_id, binding_kind, object_type, "
            "object_id, child_hash, ordinal, created_at, created_by) VALUES ('b-u', :t, 'e-u', "
            "'effective_input_manifest', 'm', 'm', '" + "0" * 64 + "', 0, :now, :u)"),
            {"t": tenant, "now": NOW, "u": advisor_id})
        with pytest.raises((IntegrityError, DBAPIError), match="CCX_FRESHNESS_UNKNOWN"):
            db.execute(text(
                "UPDATE advisory_decision_envelopes SET status = 'SEALED', freshness_status = 'FRESH', "
                "canonical_payload_json = '{}', envelope_hash = '" + "1" * 64 + "', sealed_at = :now, "
                "sealed_by = :u, optimistic_version = 2 WHERE id = 'e-u'"), {"now": NOW, "u": advisor_id})
        db.rollback()


def test_event_tenant_and_mandate_are_bound_to_the_envelope(session_factory):
    from models.tenant import Tenant

    ids = _ids(session_factory, "ev-tenant")
    with session_factory() as db:
        _mutate_goal(db, ids)
        db.commit()
    with session_factory() as db:
        db.add(Tenant(id="t-p2-foreign", display_name="Fremd", slug="fremd-p2",
                      created_at="2026-11-14T00:00:00Z", updated_at="2026-11-14T00:00:00Z"))
        db.commit()
        tenant = db.execute(text("SELECT tenant_id FROM mandates WHERE id = :m"), {"m": ids["mid"]}).scalar()
        insert = (
            "INSERT INTO advisory_invalidation_events (id, tenant_id, mandate_id, envelope_id, source_kind, "
            "source_object_id, reason_code, invalidation_sequence, created_at, created_by) VALUES "
            "('ev-x', :t, :m, :e, 'goals', 'g', 'CCX_INPUT_STALE', 2, :now, 'system')"
        )
        for args in ({"t": "t-p2-foreign", "m": ids["mid"]}, {"t": tenant, "m": "other-mandate"}):
            with pytest.raises((IntegrityError, DBAPIError)):
                db.execute(text(insert), {**args, "e": ids["envelope"], "now": NOW})
            db.rollback()


# ── Consumer ─────────────────────────────────────────────────────────────────


def test_allocation_inputs_stale_reports_server_status(session_factory):
    from models.allocation import TargetAllocation
    from models.mandates import Mandate
    from services.allocation_input_staleness import advisory_envelope_stale_reason, allocation_inputs_stale

    ids = _ids(session_factory, "consumer")
    with session_factory() as db:
        mandate, ta = db.get(Mandate, ids["mid"]), db.get(TargetAllocation, ids["ta"])
        assert advisory_envelope_stale_reason(db, mandate, ta) is None
        assert allocation_inputs_stale(db, mandate, ta) is False
        _mutate_cma(db, ids)  # nicht Teil des input_snapshot_hash -> nur die Envelope-Frische
        db.commit()
    with session_factory() as db:
        mandate, ta = db.get(Mandate, ids["mid"]), db.get(TargetAllocation, ids["ta"])
        assert advisory_envelope_stale_reason(db, mandate, ta) == "CCX_INPUT_STALE"
        assert allocation_inputs_stale(db, mandate, ta) is True


def test_document_archive_refuses_stale_decision_with_audit(session_factory):
    from models.users import User
    from routers.pdf_reports import _archive_final

    ids = _ids(session_factory, "archive")
    ctx = type("Ctx", (), {"watermark_mode": "none"})()
    kwargs = {"mandate_id": ids["mid"], "document_type": "Beratungsprotokoll", "title": "Beratungsprotokoll",
              "pdf_bytes": b"%PDF-1.4 test", "content_hash": "c" * 64, "ip_address": None,
              "binding": {"target_allocation_id": ids["ta"], "preferences_sha256": None}}
    count = text("SELECT count(*) FROM contract_documents WHERE mandate_id = :m")
    with session_factory() as db:
        _mutate_goal(db, ids)
        db.commit()
    with session_factory() as db:
        before = db.execute(count, {"m": ids["mid"]}).scalar()
        with pytest.raises(DomainError) as caught:
            _archive_final(ctx, db, current_user=db.get(User, ids["advisor"]), **kwargs)
        assert caught.value.reason_code == "CCX_INPUT_STALE"
        assert db.execute(count, {"m": ids["mid"]}).scalar() == before
        blocked = db.execute(text("SELECT new_value, mandate_id FROM audit_log WHERE field_name = "
                                  "'ccx.envelope.rejected'")).all()
        assert blocked and '"channel": "archive"' in blocked[-1].new_value and blocked[-1].mandate_id == ids["mid"]
        # eine andere (neue) Strategie ist nicht der Entscheid -> keine P2-Sperre
        assert _archive_final(ctx, db, current_user=db.get(User, ids["advisor"]),
                              **{**kwargs, "binding": {"target_allocation_id": "other-ta"}}) is not None


def test_cache_scope_changes_with_every_invalidation(session_factory):
    from models.mandates import Mandate
    from services.advisory_decision_envelope import advisory_report_cache_scope

    ids = _ids(session_factory, "cache-scope")
    with session_factory() as db:
        fresh = advisory_report_cache_scope(db, db.get(Mandate, ids["mid"]))
        _mutate_goal(db, ids)
        db.commit()
    with session_factory() as db:
        stale1 = advisory_report_cache_scope(db, db.get(Mandate, ids["mid"]))
        _mutate_cashflow(db, ids)
        db.commit()
    with session_factory() as db:
        stale2 = advisory_report_cache_scope(db, db.get(Mandate, ids["mid"]))
    assert len({fresh, stale1, stale2}) == 3


def test_freshness_status_route_shows_server_status(session_factory):
    from models.users import User
    from routers.review import get_current_advisory_envelope_freshness

    ids = _ids(session_factory, "status")
    with session_factory() as db:
        user = db.get(User, ids["advisor"])
        status = get_current_advisory_envelope_freshness(mandate_id=ids["mid"], db=db, current_user=user)
        assert (status["freshness_status"], status["invalidation_count"]) == ("FRESH", 0)
        _mutate_goal(db, ids)
        db.commit()
        status = get_current_advisory_envelope_freshness(mandate_id=ids["mid"], db=db, current_user=user)
        assert (status["freshness_status"], status["stale_reason_code"], status["invalidation_count"],
                status["last_invalidation_sequence"]) == ("STALE", "CCX_INPUT_STALE", 1, 1)


# ── CCX-01 / CCX-06 Adapter ──────────────────────────────────────────────────


def test_ccx01_goal_binding_and_ccx06_benchmark_lineage():
    from services.advisory_decision_envelope import goal_binding_is_current
    from services.benchmark_evidence import benchmark_identity, is_benchmark_current

    assert goal_binding_is_current({"goal_schedule_hash": "old"}, "old") is True
    assert goal_binding_is_current({"goal_schedule_hash": "old"}, "new") is False
    assert goal_binding_is_current({}, "x") is False and goal_binding_is_current({"goals_hash": "x"}, None) is False
    assert is_benchmark_current("bench@1", "bench@1") is True
    assert is_benchmark_current("bench@1", "bench@2") is False
    assert is_benchmark_current(None, None) is False
    assert benchmark_identity("p", 1, "h") != benchmark_identity("p", 2, "h")
    assert benchmark_identity("p", None, "h") is None


def test_hook_kinds_cover_contract_dependency_groups():
    from models.snapshots import DEPENDENCY_KINDS, DEPENDENCY_SOURCES

    kinds = {source.kind for source in DEPENDENCY_SOURCES.values()}
    assert kinds <= set(DEPENDENCY_KINDS)
    # Ziele, Cashflows, Vermoegen, Risikoprofil, ESG, CMA/Policy, Benchmark,
    # Restriktionen, Mandats-/Kundendaten (Vertrag §5, Auftrag P2).
    for table in ("goals", "cashflows", "wealth_inflows", "wealth_positions", "risk_assessments",
                  "investment_preference_decisions", "capital_market_assumptions", "optimizer_policies",
                  "cma_policies", "house_matrix", "target_allocations", "mandates", "clients"):
        assert table in DEPENDENCY_SOURCES, table


# ── Migration und Paritaet ───────────────────────────────────────────────────


def _alembic_cfg(db_url):
    from alembic.config import Config

    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", db_url)
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    return cfg


P2_TABLES = ("advisory_dependency_edges", "advisory_invalidation_events")
ALL_TABLES = ("advisory_decision_envelopes", "advisory_envelope_bindings",
              "advisory_effective_input_manifests") + P2_TABLES
FRESHNESS_COLUMNS = ("freshness_status", "stale_at", "stale_reason_code")


def _schema(conn):
    columns = {t: [r[1] for r in conn.execute(f"PRAGMA table_info({t})")] for t in ALL_TABLES}
    names = ", ".join(f"'{t}'" for t in ALL_TABLES)
    triggers = {r[0]: r[1] for r in conn.execute(
        f"SELECT name, sql FROM sqlite_master WHERE type = 'trigger' AND tbl_name IN ({names})")}
    indexes = {r[0] for r in conn.execute(
        f"SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name IN ({names}) "
        "AND name NOT LIKE 'sqlite_%'")}
    return columns, triggers, indexes


def _migration():
    path = BACKEND / "alembic" / "versions" / f"{CCX_P2_REV}_ccx_p2_invalidation_staleness.py"
    spec = importlib.util.spec_from_file_location("ccx_p2_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_alembic_single_head_and_upgrade_downgrade_upgrade(tmp_path):
    from alembic import command
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(_alembic_cfg("sqlite://"))
    assert script.get_heads() == [CCX_P2_REV]
    assert script.get_revision(CCX_P2_REV).down_revision == CCX_P1_REV
    url = f"sqlite:///{tmp_path / 'p2.db'}"
    cfg = _alembic_cfg(url)

    def state():
        with sqlite3.connect(tmp_path / "p2.db") as conn:
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
            cols = [r[1] for r in conn.execute("PRAGMA table_info(advisory_decision_envelopes)")]
            guard = conn.execute("SELECT sql FROM sqlite_master WHERE name = "
                                 "'trg_advisory_decision_envelopes_update_guard'").fetchone()[0]
        return tables, cols, guard

    command.upgrade(cfg, "head")
    tables, cols, guard = state()
    assert set(P2_TABLES) <= tables and set(FRESHNESS_COLUMNS) <= set(cols) and "freshness_status" in guard
    command.downgrade(cfg, CCX_P1_REV)
    tables, cols, guard = state()
    assert not set(P2_TABLES) & tables and not set(FRESHNESS_COLUMNS) & set(cols)
    p1_url = f"sqlite:///{tmp_path / 'p1-only.db'}"
    command.upgrade(_alembic_cfg(p1_url), CCX_P1_REV)
    with sqlite3.connect(tmp_path / "p1-only.db") as conn:
        p1_guard = conn.execute("SELECT sql FROM sqlite_master WHERE name = "
                                "'trg_advisory_decision_envelopes_update_guard'").fetchone()[0]
    assert " ".join(guard.split()) == " ".join(p1_guard.split())  # P1-Stand exakt wiederhergestellt
    command.upgrade(cfg, "head")
    tables, cols, guard = state()
    assert set(P2_TABLES) <= tables and set(FRESHNESS_COLUMNS) <= set(cols) and "freshness_status" in guard


def test_orm_bootstrap_runtime_patch_and_alembic_are_identical(tmp_path, monkeypatch):
    from alembic import command
    from sqlalchemy import create_engine

    import database as db_module
    from database import ADVISORY_ENVELOPE_SQLITE_TRIGGERS, ADVISORY_FRESHNESS_SQLITE_TRIGGERS, Base

    orm_db = tmp_path / "orm.db"
    engine = create_engine(f"sqlite:///{orm_db}")
    Base.metadata.create_all(engine)
    engine.dispose()
    with sqlite3.connect(orm_db) as conn:
        orm = _schema(conn)

    boot_db = tmp_path / "boot.db"
    db_module.bootstrap_sqlite_schema(db_path=boot_db, schema_path=BACKEND / "ares_schema.sql")
    with sqlite3.connect(boot_db) as conn:
        boot = _schema(conn)
    engine = create_engine(f"sqlite:///{boot_db}")
    monkeypatch.setattr(db_module, "engine", engine)
    db_module.ensure_runtime_columns()
    engine.dispose()
    with sqlite3.connect(boot_db) as conn:
        patched = _schema(conn)

    # Bestands-DB auf P1-Stand (Alembic 2c62f9012c73): der Laufzeitpatch ergaenzt
    # Spalten, ersetzt den Update-Guard und legt Kanten/Ereignisse an.
    p1_db = tmp_path / "p1.db"
    command.upgrade(_alembic_cfg(f"sqlite:///{p1_db}"), CCX_P1_REV)
    engine = create_engine(f"sqlite:///{p1_db}")
    monkeypatch.setattr(db_module, "engine", engine)
    db_module.ensure_runtime_columns()
    engine.dispose()
    with sqlite3.connect(p1_db) as conn:
        upgraded = _schema(conn)

    alembic_db = tmp_path / "alembic.db"
    command.upgrade(_alembic_cfg(f"sqlite:///{alembic_db}"), "head")
    with sqlite3.connect(alembic_db) as conn:
        migrated = _schema(conn)

    assert orm[0] == boot[0] == patched[0] == upgraded[0] == migrated[0]
    for table in ("advisory_decision_envelopes",):
        assert orm[0][table][-3:] == list(FRESHNESS_COLUMNS)
    assert set(orm[1]) == set(patched[1]) == set(upgraded[1]) == set(migrated[1])
    assert orm[2] == patched[2] == upgraded[2] == migrated[2]
    # gleiche Trigger-Texte (normalisiert) ueber alle Wege
    norm = {name: " ".join(sql.split()) for name, sql in migrated[1].items()}
    for other in (orm[1], patched[1], upgraded[1]):
        assert {name: " ".join(sql.split()) for name, sql in other.items()} == norm
    migration = _migration()
    assert migration.SQLITE_UPDATE_GUARD in ADVISORY_ENVELOPE_SQLITE_TRIGGERS
    assert migration.SQLITE_TRIGGERS == ADVISORY_FRESHNESS_SQLITE_TRIGGERS
    assert migration.revision == CCX_P2_REV and migration.down_revision == CCX_P1_REV


def test_bootstrap_sql_is_textually_identical_to_constants():
    from database import ADVISORY_FRESHNESS_SQLITE_TABLE_DDL, ADVISORY_FRESHNESS_SQLITE_TRIGGERS

    schema = (BACKEND / "ares_schema.sql").read_text(encoding="utf-8")
    for ddl in ADVISORY_FRESHNESS_SQLITE_TABLE_DDL + ADVISORY_FRESHNESS_SQLITE_TRIGGERS:
        assert ddl + ";" in schema


def test_no_float_in_new_columns():
    from models.snapshots import AdvisoryDependencyEdge, AdvisoryInvalidationEvent

    for model in (AdvisoryDependencyEdge, AdvisoryInvalidationEvent):
        for column in model.__table__.columns:
            assert column.type.python_type in (str, int), (model.__tablename__, column.name)


# ── Nachtrag 1: N-908-01/02, Entscheid unterzeichnete Entscheide, N-908-04 ───


def test_core_table_dml_via_session_triggers_the_hook(session_factory):
    """N-908-02 Umgehung 1: ``session.execute(update(Goal.__table__))`` lief
    am Massen-Hook vorbei (bind_mapper None) -- jetzt invalidiert sie."""
    from sqlalchemy import update

    from models.wealth import Goal

    ids = _ids(session_factory, "core-table")
    with session_factory() as db:
        db.execute(update(Goal.__table__).where(Goal.__table__.c.mandate_id == ids["mid"]).values(weight_bps=4100))
        db.commit()
    with session_factory() as db:
        assert _envelope(db, ids["envelope"]).freshness_status == "STALE"
        assert {e.source_kind for e in _events(db, ids["envelope"])} == {"goals"}
        assert db.execute(text("SELECT count(*) FROM goals WHERE weight_bps = 4100")).scalar() >= 1


def test_connection_level_core_dml_triggers_the_hook(session_factory):
    """N-908-02 Umgehung 2: ``db.connection().execute(update(Goal))`` und
    ``engine.begin()`` umgingen jeden Session-Hook -- jetzt loest der
    Laufzeitschutz (Engine ``before_execute``) den Hook auf Verbindungsebene
    aus: Ereignis + STALE im selben Commit (Actor ``system``)."""
    from sqlalchemy import update

    from models.wealth import Goal

    ids = _ids(session_factory, "core-conn")
    with session_factory() as db:
        db.connection().execute(update(Goal).where(Goal.mandate_id == ids["mid"]).values(weight_bps=4200))
        db.rollback()  # zurueckgerollt -> keine Spur
        assert _envelope(db, ids["envelope"]).freshness_status == "FRESH"
        db.connection().execute(update(Goal).where(Goal.mandate_id == ids["mid"]).values(weight_bps=4200))
        db.commit()
    with session_factory() as db:
        assert _envelope(db, ids["envelope"]).freshness_status == "STALE"
        events = _events(db, ids["envelope"])
        assert {e.source_kind for e in events} == {"goals"} and {e.created_by for e in events} == {"system"}
        engine = db.get_bind()
    other = _ids(session_factory, "core-engine")
    with engine.begin() as conn:
        conn.execute(Goal.__table__.delete().where(Goal.__table__.c.mandate_id == other["mid"]))
    with session_factory() as db:
        assert _envelope(db, other["envelope"]).freshness_status == "STALE"
        assert {e.source_kind for e in _events(db, other["envelope"])} == {"goals"}


def _bypass_cma(db, ids):
    """Rohes SQL am Hook vorbei (simuliert z. B. eine globale CMA-Aenderung
    ausserhalb des Mandantenkontexts, N-908-01 (a)); der Status bleibt FRESH."""
    db.execute(text("UPDATE capital_market_assumptions SET notes = 'ausserhalb' WHERE id = :c"), {"c": ids["cma"]})
    db.commit()


def test_status_only_consumers_now_pull_the_edges(session_factory):
    """N-908-01: Veraltet-Hinweis, Cache-Scope und Dokumentarchiv lesen nicht
    nur den gespeicherten Status, sondern pruefen die Kanten."""
    from models.allocation import TargetAllocation
    from models.mandates import Mandate
    from models.users import User
    from routers.pdf_reports import _archive_final
    from services.advisory_decision_envelope import advisory_report_cache_scope
    from services.allocation_input_staleness import advisory_envelope_stale_reason, allocation_inputs_stale

    ids = _ids(session_factory, "pull-consumers")
    with session_factory() as db:
        fresh_scope = advisory_report_cache_scope(db, db.get(Mandate, ids["mid"]))
        _bypass_cma(db, ids)
    with session_factory() as db:
        mandate, ta = db.get(Mandate, ids["mid"]), db.get(TargetAllocation, ids["ta"])
        assert _envelope(db, ids["envelope"]).freshness_status == "FRESH"  # Status allein: "frisch"
        assert advisory_envelope_stale_reason(db, mandate, ta) == "CCX_INPUT_STALE"
        assert allocation_inputs_stale(db, mandate, ta) is True
        assert advisory_report_cache_scope(db, mandate) != fresh_scope
        assert _events(db, ids["envelope"]) == []  # lesende Konsumenten schreiben nichts
        ctx = type("Ctx", (), {"watermark_mode": "none"})()
        with pytest.raises(DomainError) as caught:
            _archive_final(ctx, db, current_user=db.get(User, ids["advisor"]), mandate_id=ids["mid"],
                           document_type="Beratungsprotokoll", title="Beratungsprotokoll",
                           pdf_bytes=b"%PDF-1.4 test", content_hash="d" * 64, ip_address=None,
                           binding={"target_allocation_id": ids["ta"], "preferences_sha256": None})
        assert caught.value.reason_code == "CCX_INPUT_STALE"
    with session_factory() as db:  # das Archiv haelt die Abweichung fest
        assert _envelope(db, ids["envelope"]).freshness_status == "STALE"
        assert [(e.invalidation_sequence, e.source_kind) for e in _events(db, ids["envelope"])] == [(1, "cma")]


def _sign_decision(db, ids):
    """Kunde unterzeichnet GENAU diesen Entscheid (Dokument nach dem Siegel
    erzeugt und signiert, N-908-05)."""
    _document(db, ids, at=_ms_now())


def _new_current_cma(db, ids):
    from sqlalchemy import inspect as sa_inspect

    from database import new_uuid
    from models.allocation import CapitalMarketAssumption

    bound = db.get(CapitalMarketAssumption, ids["cma"])
    values = {attr.key: getattr(bound, attr.key) for attr in sa_inspect(CapitalMarketAssumption).column_attrs}
    values.update(id=new_uuid(), is_current=1, version=(bound.version or 1) + 1, notes="neue Hausmeinung")
    db.add(CapitalMarketAssumption(**values))


@pytest.mark.parametrize("signed", [False, True], ids=["unterzeichnet-nein", "unterzeichnet-ja"])
def test_new_house_view_stales_only_unsigned_decisions(session_factory, signed):
    """Entscheid (Owner-Vertretung, N-908): neue aktuelle CMA/Policy setzt nur
    NICHT unterzeichnete Entscheide STALE. Ein unterzeichneter Entscheid bleibt
    unveraendert -- weder Hook noch Pull-Pruefung markieren ihn wegen der
    Hausmeinung (Strategietreue: kein Rebalancing, keine Ueberwachung).
    Kundendaten-Aenderungen invalidieren ihn weiterhin."""
    ids = _ids(session_factory, f"house-view-{signed}")
    if signed:
        with session_factory() as db:
            _sign_decision(db, ids)
    with session_factory() as db:
        _new_current_cma(db, ids)  # neue aktuelle Version (Insert)
        db.commit()
    with session_factory() as db:
        _mutate_cma(db, ids)  # gebundene Version geaendert (Update)
        db.commit()
    with session_factory() as db:
        row = _envelope(db, ids["envelope"])
        if signed:
            assert (row.freshness_status, row.optimistic_version) == ("FRESH", 2)
            assert _events(db, ids["envelope"]) == []
            assert _gate(db, ids["mid"], ids["advisor"])["freshness_status"] == "FRESH"  # Pull ebenso
        else:
            assert row.freshness_status == "STALE"
            assert {e.source_kind for e in _events(db, ids["envelope"])} == {"cma"}
    if signed:
        with session_factory() as db:
            _mutate_goal(db, ids)  # Kundendaten wirken weiterhin
            db.commit()
        with session_factory() as db:
            assert _envelope(db, ids["envelope"]).freshness_status == "STALE"


def test_former_scope_only_tables_now_have_edges_for_the_pull(session_factory):
    """N-908-04: auch die zehn Tabellen, die der Hook bisher nur ueber die
    Reichweite traf, haben eine Kante; eine Aenderung am Hook vorbei faellt
    der Pull-Pruefung auf (hier: Planungsannahmen per rohem SQL)."""
    from models.snapshots import DEPENDENCY_SOURCES

    ids = _ids(session_factory, "edge-planning")
    with session_factory() as db:
        kinds = {r[0] for r in db.execute(text(
            "SELECT dependency_kind FROM advisory_dependency_edges WHERE envelope_id = :e"), {"e": ids["envelope"]})}
        for table in ("goal_revision_decisions", "goal_lifecycle_transitions", "planning_assumptions",
                      "risk_override_decisions", "risk_profile_signoffs", "risk_capacity_plausibility_evaluations",
                      "financial_coverage_attestations", "building_blocks", "cma_policy_components",
                      "cma_policy_approvals"):
            assert DEPENDENCY_SOURCES[table].kind in kinds, table
        db.execute(text(
            "INSERT INTO planning_assumptions (id, mandate_id, client_id, valid_from, version, is_current, created_at, "
            "updated_at) VALUES ('pa-bypass', :m, :c, '2026-01-01', 99, 0, :now, :now)"),
            {"m": ids["mid"], "c": ids["cid"], "now": NOW})
        db.commit()
        with pytest.raises(DomainError) as caught:
            _gate(db, ids["mid"], ids["advisor"])
        assert caught.value.reason_code == "CCX_INPUT_STALE"
    with session_factory() as db:
        assert "planning" in {e.source_kind for e in _events(db, ids["envelope"])}


# ── Nachtrag 2: N-908-05 (Unterschrift am Entscheid), Flush-Zaehler ──────────


def _ms_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _document(db, ids, *, at: str, signed_by_client: int = 1) -> str:
    from database import new_uuid
    from models.review import ContractDocument

    doc_id = new_uuid()
    db.add(ContractDocument(
        id=doc_id, mandate_id=ids["mid"], document_type="Anlagestrategie", title="Vertrag",
        status="Unterzeichnet" if signed_by_client else "Entwurf", signed_by_advisor=signed_by_client,
        signed_by_client=signed_by_client, signed_at=at if signed_by_client else None,
        signature_client_signed_at=at if signed_by_client else None,
        bound_target_allocation_id=ids["ta"], created_by=ids["advisor"], created_at=at, updated_at=at,
    ))
    db.commit()
    return doc_id


def _onsite_evidence(db, ids, doc_id: str, *, at: str) -> None:
    from database import Base, new_uuid

    table = Base.metadata.tables["onsite_signature_evidence"]
    values = {}
    for column in table.columns:
        if column.nullable or column.default is not None or column.server_default is not None:
            continue
        python_type = column.type.python_type
        length = getattr(column.type, "length", None)
        values[column.name] = 1 if python_type is int else ("e" * length if length else "x")
    values.update(id=new_uuid(), mandate_id=ids["mid"], client_id=ids["cid"], document_id=doc_id,
                  signer_role="client", signed_at=at, advisor_id=ids["advisor"], created_at=at,
                  schema_version="OnsiteSignatureEvidenceV1",
                  tenant_id=db.execute(text("SELECT tenant_id FROM mandates WHERE id = :m"),
                                       {"m": ids["mid"]}).scalar())
    db.execute(table.insert(), values)
    db.commit()


def _house_view_change(session_factory, ids):
    with session_factory() as db:
        _new_current_cma(db, ids)
        db.commit()
    with session_factory() as db:
        _mutate_cma(db, ids)
        db.commit()


def test_signature_of_e1_does_not_exempt_e2_on_the_same_allocation(session_factory):
    """N-908-05: E1 unterzeichnet, E2 auf derselben Soll-Allokation neu
    finalisiert, neue Hausmeinung -> E2 STALE; E1 (abgeloest) unveraendert."""
    ids = _ids(session_factory, "sig-e1-e2")
    with session_factory() as db:
        _document(db, ids, at=_ms_now())  # E1 unterzeichnet (nach dessen Siegel)
    _a, _m, _x, run2 = _finalizable_run(session_factory, "sig-e1-e2", mandate=(ids["advisor"], ids["mid"], ids["aid"]))
    e2 = _finalize(session_factory, ids["advisor"], ids["mid"], run2).advisory_envelope_id
    with session_factory() as db:
        assert db.execute(text("SELECT target_allocation_id FROM recommendation_runs WHERE id = :r"),
                          {"r": run2}).scalar() == ids["ta"]  # wirklich dieselbe Allokation
    _house_view_change(session_factory, ids)
    with session_factory() as db:
        e1_row, e2_row = _envelope(db, ids["envelope"]), _envelope(db, e2)
        assert (e1_row.status, e1_row.freshness_status) == ("SUPERSEDED", "FRESH")
        assert e2_row.freshness_status == "STALE"
        assert {e.source_kind for e in _events(db, e2)} == {"cma"}


def test_signature_before_seal_does_not_count(session_factory):
    """Ein vor dem Siegel erzeugtes/signiertes Dokument gehoert nicht zu diesem
    Entscheid -> die neue Hausmeinung setzt ihn STALE."""
    ids = _ids(session_factory, "sig-before")
    with session_factory() as db:
        _document(db, ids, at="2026-01-01T00:00:00.000Z")
    _house_view_change(session_factory, ids)
    with session_factory() as db:
        assert _envelope(db, ids["envelope"]).freshness_status == "STALE"


def test_onsite_signature_counts_like_e_signing(session_factory):
    """Vor-Ort-Signatur (Evidenz signer_role = client) zaehlt gleichwertig,
    obwohl sie signed_by_client nicht setzt."""
    ids = _ids(session_factory, "sig-onsite")
    with session_factory() as db:
        now = _ms_now()
        doc_id = _document(db, ids, at=now, signed_by_client=0)
        _onsite_evidence(db, ids, doc_id, at=now)
    _house_view_change(session_factory, ids)
    with session_factory() as db:
        assert _envelope(db, ids["envelope"]).freshness_status == "FRESH"
        assert _events(db, ids["envelope"]) == []
        assert _gate(db, ids["mid"], ids["advisor"])["freshness_status"] == "FRESH"


def test_flush_counter_is_reset_at_transaction_end(session_factory):
    """Ein Flush ohne Arbeit (``flush(objects=...)`` auf ein unveraendertes
    Objekt bei sonstigen offenen Aenderungen) kehrt ohne after_flush_postexec
    zurueck; spaetestens am Transaktionsende ist der Laufzeitschutz wieder
    scharf (naechste Core-DML am Hook vorbei loest den Hook aus)."""
    from sqlalchemy import update

    import models.snapshots as snapshots
    from models.clients import Client
    from models.users import User
    from models.wealth import Goal

    ids = _ids(session_factory, "flush-reset")
    # Rollback-Pfad.
    with session_factory() as db:
        goal = db.query(Goal).filter(Goal.mandate_id == ids["mid"], Goal.rank == 1).one()
        db.get(Client, ids["cid"]).notes = "offen"  # sonstige offene Aenderung
        db.flush(objects=[goal])                    # keine Arbeit fuer goal
        db.rollback()
        assert snapshots._FLUSH_DEPTH.get() == 0
    # Commit-Pfad (Nachtrag 2, Gegenprobe): Flush ohne Arbeit, danach Commit
    # mit sonstiger Arbeit an einer Nicht-Abhaengigkeit (users). Ohne Reset am
    # Transaktionsende bliebe der Zaehler auf 1 und die folgende Core-DML am Hook
    # vorbei wuerde nicht erkannt (Entscheid bliebe FRESH).
    with session_factory() as db:
        goal = db.query(Goal).filter(Goal.mandate_id == ids["mid"], Goal.rank == 1).one()
        db.get(User, ids["advisor"]).email = "flush-reset@example.invalid"
        db.flush(objects=[goal])
        assert snapshots._FLUSH_DEPTH.get() == 1  # Vorbedingung: das Leck tritt wirklich auf
        db.commit()
        assert snapshots._FLUSH_DEPTH.get() == 0
    with session_factory() as db:
        assert _envelope(db, ids["envelope"]).freshness_status == "FRESH"  # users ist keine Kante
        db.connection().execute(update(Goal).where(Goal.mandate_id == ids["mid"]).values(weight_bps=4300))
        db.commit()
    with session_factory() as db:
        assert _envelope(db, ids["envelope"]).freshness_status == "STALE"
        assert {e.source_kind for e in _events(db, ids["envelope"])} == {"goals"}
