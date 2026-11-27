"""CCX P5 Kanal-Envelope -- Pflichtregressionen (Vertrag 2026-11-13 §8).

* Siegel bindet Parametersatz (M-2) und Zielkennzahl (M-3) als Kind-Bindungen;
  beide Hashes sind aus der Soll-Allokation reproduzierbar.
* Kanal-Gate: P4 (SEALED+FRESH) + FX JETZT + P5-Bindungen; Kunden-PDF-Fuss
  traegt Envelope-Hash/Fassung, Archiv schreibt die Kanalzeile ``PDF``.
* Signatur nur fuer das archivierte Artefakt genau dieses Envelopes
  (``CCX_SIGNATURE_ENVELOPE_OUTDATED`` sonst); Handoff schreibt ``HANDOFF``.
* Querschnitt Freshness: irrelevante Aenderung (fremder FX-Kurs) bleibt
  auslieferbar, relevante (Kurs veraltet, IC-Risikoanteil geaendert) sperrt.
* Migration: ein Head, upgrade/downgrade/upgrade, ORM = Bootstrap-SQL =
  Laufzeitpatch = Alembic; Kanalzeilen append-only.
"""
from __future__ import annotations

import importlib.util
import sqlite3

import pytest
from sqlalchemy import create_engine, text

from core.reason_codes import DomainError
from tests.test_ccx_p1_snapshot_hash import BACKEND, _alembic_cfg, session_factory  # noqa: F401
from tests.test_ccx_p3_market_depot_truth import _add_fx, _add_position, _prepared_run
from tests.test_ccx_p4_allocation_publish import (
    _finalize,
    _mandate,
    _publish,
    _published,
    _second_approver,
)
from tests.test_finalize_mandate_lock import _FakeRequest
from tests.test_h12_ccx_hygiene import _text, _user

CCX_P5_REV = "c2546c196134"
CCX_P5B_REV = "74e3e973ea09"
K1_REV = "63332bb56098"
P5_TABLE = "advisory_channel_publications"


def _decision(session_factory, mid):
    from services.allocation_publication_gate import evaluate_channel_envelope

    with session_factory() as db:
        return evaluate_channel_envelope(db, _mandate(db, mid))


def _bindings(db, envelope_id):
    from models.snapshots import AdvisoryEnvelopeBinding

    return {row.binding_kind: row for row in db.query(AdvisoryEnvelopeBinding).filter(
        AdvisoryEnvelopeBinding.envelope_id == envelope_id).all()}


def _anlagestrategie(db, mid, user):
    import routers.pdf_reports as pdf

    return pdf.get_anlagestrategie_pdf(mandate_id=mid, request=_FakeRequest(), db=db, current_user=user,
                                       expected_allocation_id=None)


def _published_usd(session_factory, suffix):
    def setup(db, mandate_id):
        _add_fx(db, "USD", 8_800)
        _add_position(db, mandate_id, label="usd", currency="USD", value=10_000_00)

    advisor_id, mid, _aid, run_id = _prepared_run(session_factory, suffix, setup)
    _finalize(session_factory, advisor_id, mid, run_id)
    _publish(session_factory, mid, _second_approver(session_factory, advisor_id))
    return advisor_id, mid, run_id


# ── Siegel: M-2/M-3-Bindung ──────────────────────────────────────────────────


def test_seal_binds_parameter_set_and_goal_metric_reproducibly(session_factory):
    from services.advisory_decision_envelope import (
        GOAL_METRIC_BINDING_KIND,
        PARAMETER_SET_BINDING_KIND,
        p5_decision_hashes,
    )
    from services.allocation_publication_gate import current_target_allocation
    from core.risk_parameter_set import stored_risk_parameter_set

    _advisor, _approver, mid, *_rest = _published(session_factory, "p5-seal")
    decision = _decision(session_factory, mid)
    assert decision.ok, decision.reason_code
    with session_factory() as db:
        bindings = _bindings(db, decision.envelope_id)
        ta = current_target_allocation(db, mid)
        record = stored_risk_parameter_set(ta)
        assert bindings[PARAMETER_SET_BINDING_KIND].child_hash == record["parameter_set_hash"]
        assert (bindings[PARAMETER_SET_BINDING_KIND].child_hash,
                bindings[GOAL_METRIC_BINDING_KIND].child_hash) == p5_decision_hashes(
                    db, mandate=_mandate(db, mid), ta=ta)
        # Derselbe Vektor wie Persistenz/Budgetpruefung (Abnahme 1/5).
        import json

        constraints = json.loads(ta.effective_constraints_json)
        assert record["bucket_coefficients_bps"] == constraints["risky_fraction_per_bucket_bps"]
        assert record["ic_release_status"] == "UNRELEASED"


def test_seal_without_parameter_set_fails_closed(session_factory, monkeypatch):
    """Allokation ohne gespeicherten Satz (Bestand vor P5): kein Siegel."""
    import services.advisory_decision_envelope as rps  # Name dort gebunden
    from tests.test_ccx_p1_snapshot_hash import _finalizable_run

    advisor_id, mid, _aid, run_id = _finalizable_run(session_factory, "p5-noset")
    monkeypatch.setattr(rps, "stored_risk_parameter_set", lambda _ta: None)
    with pytest.raises(DomainError) as exc:
        _finalize(session_factory, advisor_id, mid, run_id)
    assert exc.value.reason_code == "CCX_PARAMETER_SET_MISSING"


def test_seal_without_certified_goal_metric_fails_closed(session_factory, monkeypatch):
    import core.goal_metric_contract as gmc
    from tests.test_ccx_p1_snapshot_hash import _finalizable_run

    advisor_id, mid, _aid, run_id = _finalizable_run(session_factory, "p5-nogoal")
    monkeypatch.setattr(gmc, "_individual_rows", lambda _a: {})
    with pytest.raises(DomainError) as exc:
        _finalize(session_factory, advisor_id, mid, run_id)
    assert exc.value.reason_code == "CCX_GOAL_METRIC_UNCERTIFIED"


def test_goal_status_comes_from_lower_bound_not_point_estimate(monkeypatch):
    """M-3 Abnahme 3/5: Punktschaetzer gut (80 %), Untergrenze unzureichend ->
    kein gruener Status; ein Sekundaerwert (Punktschaetzer) ersetzt den Status
    nicht. Der Payload uebernimmt den zertifizierten Status, nie eine Ampel des
    Punktschaetzers."""
    import json
    from types import SimpleNamespace

    import core.goal_metric_contract as gmc
    from services.optimizer.certification import wilson_lower_bound

    lower = wilson_lower_bound(0.80, 20)
    assert lower < 0.70
    row = {"goal_id": "g1", "probability": 0.80, "lower_confidence_bound": lower, "tau": 0.70,
           "effective_sample_size": 20.0, "status": "knapp", "validation_seed": 7}
    monkeypatch.setattr(gmc, "_individual_rows", lambda _a: {"g1": row})
    goal = SimpleNamespace(id="g1", updated_at="2026-11-21", rank=1, hardness="Primär", target_amount_rappen=1,
                           target_wealth_rappen=None, target_date="2030-01-01", is_active=1, is_included=1,
                           label="Ziel")

    # P5b / N-925-03: Validierungsanker (Seed, Wuerfel, Pfadzahl) Pflicht.
    run = SimpleNamespace(validation_seed=7, validation_cube_hash="c" * 64, validation_n_paths=20)
    ta = SimpleNamespace(id="ta", goal_achievability_json=json.dumps([row]), optimization_run=run)
    payload = gmc.build_goal_metric_payload([goal], mandate=SimpleNamespace(id="m", base_currency="CHF"),
                                            target_allocation=ta)
    entry = payload["goals"][0]
    # P5b / N-925-03: Status neu berechnet (ESS 20 < 30 -> "unreliable"), nicht
    # das "knapp" der Zeile kopiert -- in keinem Fall gruen.
    assert entry["status"] == "unreliable" and entry["probability_ppm"] == 800_000
    assert entry["lower_bound_ppm"] < entry["tau_ppm"]
    row["probability"] = 0.95  # Sekundaerwert geaendert -> anderer Hash, Status bleibt
    again = gmc.build_goal_metric_payload([goal], mandate=SimpleNamespace(id="m", base_currency="CHF"),
                                          target_allocation=ta)
    assert again["goals"][0]["status"] == "unreliable"
    assert again["goal_metric_payload_hash"] != payload["goal_metric_payload_hash"]


# ── Kanal-Gate, PDF-Fuss, Archiv, Signatur ──────────────────────────────────


def test_pdf_footer_carries_envelope_hash_and_archive_writes_channel_row(session_factory):
    from models.snapshots import AdvisoryChannelPublication

    advisor_id, _approver, mid, *_rest = _published(session_factory, "p5-pdf")
    decision = _decision(session_factory, mid)
    with session_factory() as db:
        body = _text(_anlagestrategie(db, mid, _user(db, advisor_id)).body)
        db.commit()
    assert f"Beratungsentscheid: {decision.envelope_hash[:12]}" in body
    assert "Fassung 1" in body
    with session_factory() as db:
        rows = db.query(AdvisoryChannelPublication).filter(AdvisoryChannelPublication.mandate_id == mid).all()
    assert [(r.channel, r.bound_envelope_hash, r.parameter_set_hash, r.goal_metric_payload_hash)
            for r in rows] == [("PDF", decision.envelope_hash, decision.parameter_set_hash,
                                decision.goal_metric_payload_hash)]


def test_unpublished_pdf_footer_says_no_sealed_decision(session_factory):
    from tests.test_ccx_p4_allocation_publish import _finalized

    advisor_id, mid, _aid, _run = _finalized(session_factory, "p5-draft")
    with session_factory() as db:
        body = _text(_anlagestrategie(db, mid, _user(db, advisor_id)).body)
    assert "Beratungsentscheid: keiner versiegelt" in body


def test_signature_only_for_the_archived_artifact_of_the_current_envelope(session_factory):
    from models.review import ContractDocument
    from models.snapshots import AdvisoryChannelPublication
    from routers.review import sign_document
    from schemas.review import ContractDocumentSign

    advisor_id, _approver, mid, *_rest = _published(session_factory, "p5-sign")
    with session_factory() as db:
        _anlagestrategie(db, mid, _user(db, advisor_id))
        db.commit()
        doc = db.query(ContractDocument).filter(ContractDocument.mandate_id == mid,
                                                ContractDocument.document_type == "Anlagestrategie").one()
        doc_id = doc.id
    body = ContractDocumentSign(signed_by_advisor=True, signed_by_client=False, signer_name="Berater Test",
                                signature_image="data:image/png;base64,iVBORw0KGgo=")
    # Gegenprobe: dasselbe PDF ohne Kanalzeile dieses Envelopes -> gesperrt.
    with session_factory() as db:
        db.execute(text("DROP TRIGGER IF EXISTS trg_advisory_channel_publications_no_delete"))
        db.execute(text("DELETE FROM advisory_channel_publications WHERE artifact_id = :d"), {"d": doc_id})
        db.commit()
        with pytest.raises(DomainError) as exc:
            sign_document(mandate_id=mid, doc_id=doc_id, body=body, request=_FakeRequest(), db=db,
                          current_user=_user(db, advisor_id))
        assert exc.value.reason_code == "CCX_SIGNATURE_ENVELOPE_OUTDATED"
    with session_factory() as db:  # neu erzeugen: Artefakt wieder gebunden
        _anlagestrategie(db, mid, _user(db, advisor_id))
        db.commit()
        signed = sign_document(mandate_id=mid, doc_id=doc_id, body=body, request=_FakeRequest(), db=db,
                               current_user=_user(db, advisor_id))
        assert signed.signed_by_advisor == 1
        channels = {r.channel for r in db.query(AdvisoryChannelPublication).filter(
            AdvisoryChannelPublication.mandate_id == mid).all()}
    assert channels == {"PDF", "ADVISOR_SIGNATURE"}


# ── Querschnitt Freshness inkl. FX ───────────────────────────────────────────


def test_irrelevant_fx_change_stays_deliverable_relevant_fx_staleness_blocks(session_factory):
    advisor_id, mid, _run = _published_usd(session_factory, "p5-fx")
    assert _decision(session_factory, mid).ok
    with session_factory() as db:  # irrelevant: Kurs einer nicht verwendeten Waehrung
        _add_fx(db, "JPY", 60)
        db.commit()
    assert _decision(session_factory, mid).ok
    with session_factory() as db:  # relevant: gleicher USD-Wert, aber veraltet
        _add_fx(db, "USD", 8_800, days_old=40)
        db.commit()
    blocked = _decision(session_factory, mid)
    assert blocked.reason_code == "CCX_FX_BASIS_STALE"
    with session_factory() as db:
        with pytest.raises(DomainError) as exc:
            _anlagestrategie(db, mid, _user(db, advisor_id))
        assert exc.value.reason_code.startswith("CCX_FX_BASIS_")
        assert "Wechselkurs" in exc.value.message or "Kurs" in str(exc.value.as_detail())


def test_relevant_ic_value_change_makes_decision_undeliverable(session_factory):
    from models.allocation import BuildingBlock
    from services.allocation_publication_gate import current_target_allocation
    from core.risk_parameter_set import stored_risk_parameter_set

    advisor_id, _approver, mid, *_rest = _published(session_factory, "p5-bb")
    assert _decision(session_factory, mid).ok
    with session_factory() as db:
        record = stored_risk_parameter_set(current_target_allocation(db, mid))
        used = next(r for r in record["sub_asset_classes"] if r["within_bucket_weight_bps"] > 0)
        db.info["ares_actor_user_id"] = advisor_id
        block = db.query(BuildingBlock).filter(BuildingBlock.sub_asset_class == used["sub_asset_class"]).first()
        block.risky_fraction_bps = min(10_000, int(block.risky_fraction_bps) + 100)
        db.commit()
    decision = _decision(session_factory, mid)
    assert not decision.ok
    assert decision.reason_code in {"CCX_INPUT_STALE", "CCX_ALLOCATION_NOT_PUBLISHABLE"}


def test_parameter_hash_mismatch_is_detected(session_factory, monkeypatch):
    """Mutation: liefert die Soll-Allokation einen anderen Parametersatz als den
    versiegelten, sperrt der Kanal (Abnahme 1: Binding Solver/Payload/PDF)."""
    import services.advisory_decision_envelope as envelope_module

    _advisor, _approver, mid, *_rest = _published(session_factory, "p5-mm")
    real = envelope_module.p5_decision_hashes
    monkeypatch.setattr(envelope_module, "p5_decision_hashes",
                        lambda db, **kw: ("f" * 64, real(db, **kw)[1]))
    assert _decision(session_factory, mid).reason_code == "CCX_CHANNEL_HASH_MISMATCH"
    monkeypatch.setattr(envelope_module, "p5_decision_hashes",
                        lambda db, **kw: (real(db, **kw)[0], "e" * 64))
    assert _decision(session_factory, mid).reason_code == "CCX_GOAL_METRIC_MISMATCH"


def test_handoff_gate_reports_outdated_and_records_channel(session_factory):
    from models.mandates import Mandate
    from services.allocation_publication_gate import require_channel_envelope
    from core.reason_codes import ReasonCode

    advisor_id, _approver, mid, *_rest = _published(session_factory, "p5-ho")
    with session_factory() as db:
        decision = require_channel_envelope(db, db.get(Mandate, mid), channel="HANDOFF",
                                            user=_user(db, advisor_id),
                                            outdated_code=ReasonCode.CCX_HANDOFF_ENVELOPE_OUTDATED)
        assert decision.ok
    from tests.test_ccx_p2_invalidation import _mutate_goal

    with session_factory() as db:
        db.info["ares_actor_user_id"] = advisor_id
        _mutate_goal(db, {"mid": mid})
        db.commit()
    with session_factory() as db:
        with pytest.raises(DomainError) as exc:
            require_channel_envelope(db, db.get(Mandate, mid), channel="HANDOFF", user=_user(db, advisor_id),
                                     outdated_code=ReasonCode.CCX_HANDOFF_ENVELOPE_OUTDATED)
        assert exc.value.reason_code == "CCX_HANDOFF_ENVELOPE_OUTDATED"
        assert exc.value.as_detail()["blocker_code"] in {"CCX_INPUT_STALE", "CCX_ALLOCATION_NOT_PUBLISHABLE"}
        audit = db.execute(text("SELECT new_value FROM audit_log WHERE field_name = 'ccx.channel.blocked'")).all()
        assert audit and "HANDOFF" in audit[-1][0]


# ── Tabelle und Migration ────────────────────────────────────────────────────


def test_channel_rows_are_append_only_and_bound_to_a_sealed_envelope(session_factory):
    advisor_id, _approver, mid, *_rest = _published(session_factory, "p5-ao")
    with session_factory() as db:
        _anlagestrategie(db, mid, _user(db, advisor_id))
        db.commit()
    with session_factory() as db:
        for statement in (f"UPDATE {P5_TABLE} SET status = 'PUBLISHED'", f"DELETE FROM {P5_TABLE}"):
            with pytest.raises(Exception):
                db.execute(text(statement))
            db.rollback()
        row = db.execute(text(f"SELECT * FROM {P5_TABLE}")).mappings().first()
        clone = dict(row)
        clone.update(id="x-clone", artifact_id="other", bound_envelope_hash="0" * 64,
                     channel_sequence=int(row["channel_sequence"]) + 1)
        cols = ", ".join(clone)
        with pytest.raises(Exception) as exc:
            db.execute(text(f"INSERT INTO {P5_TABLE} ({cols}) VALUES ({', '.join(':' + k for k in clone)})"), clone)
        assert "CCX_CHANNEL_BINDING_MISSING" in str(exc.value)


def test_alembic_single_head_p5_and_upgrade_downgrade_upgrade(tmp_path):
    from alembic import command
    from alembic.script import ScriptDirectory

    db_path = tmp_path / "p5.db"
    cfg = _alembic_cfg(f"sqlite:///{db_path}")
    # H-179 L2/L3: c7e1a9d3f5b2 (Vertragsschicht) haengt hinter CCX-P5b.
    assert ScriptDirectory.from_config(cfg).get_heads() == ["9f4c2a7e1b63"]  # C-COMP-02: neuer Kopf (hinter K3)
    assert ScriptDirectory.from_config(cfg).get_revision("c7e1a9d3f5b2").down_revision == CCX_P5B_REV
    command.upgrade(cfg, "head")
    command.downgrade(cfg, K1_REV)
    with sqlite3.connect(db_path) as conn:
        assert not conn.execute("SELECT name FROM sqlite_master WHERE name = ?", (P5_TABLE,)).fetchall()
    command.upgrade(cfg, "head")
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT name FROM sqlite_master WHERE name = ?", (P5_TABLE,)).fetchall()


def test_orm_bootstrap_runtime_patch_and_alembic_are_identical_for_p5(tmp_path, monkeypatch):
    from alembic import command

    import database as db_module
    from database import (
        CHANNEL_PUBLICATION_SQLITE_TABLE_DDL,
        CHANNEL_PUBLICATION_SQLITE_TENANT_GUARDS,
        CHANNEL_PUBLICATION_SQLITE_TRIGGERS,
        Base,
    )

    def schema(conn):
        columns = [r[1] for r in conn.execute(f"PRAGMA table_info({P5_TABLE})")]
        triggers = {r[0]: " ".join(r[1].split()) for r in conn.execute(
            "SELECT name, sql FROM sqlite_master WHERE type = 'trigger' AND tbl_name = ?", (P5_TABLE,))}
        indexes = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name = ? AND name NOT LIKE 'sqlite_%'",
            (P5_TABLE,))}
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
        conn.execute(f"DROP TABLE {P5_TABLE}")
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
    assert len(orm[1]) == len(CHANNEL_PUBLICATION_SQLITE_TRIGGERS) + len(CHANNEL_PUBLICATION_SQLITE_TENANT_GUARDS)
    assert orm[2] == patched[2] == migrated[2]
    schema_sql = (BACKEND / "ares_schema.sql").read_text(encoding="utf-8")
    for ddl in CHANNEL_PUBLICATION_SQLITE_TABLE_DDL + CHANNEL_PUBLICATION_SQLITE_TRIGGERS:
        assert ddl + ";" in schema_sql
    path = BACKEND / "alembic" / "versions" / f"{CCX_P5_REV}_ccx_p5_channel_envelope.py"
    spec = importlib.util.spec_from_file_location("ccx_p5_migration_under_test", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    path_b = BACKEND / "alembic" / "versions" / f"{CCX_P5B_REV}_ccx_p5b_channel_sequence_ic_release.py"
    spec_b = importlib.util.spec_from_file_location("ccx_p5b_migration_under_test", path_b)
    migration_b = importlib.util.module_from_spec(spec_b)
    spec_b.loader.exec_module(migration_b)
    assert sorted(migration._SQLITE_TRIGGERS + migration_b._SQLITE_TRIGGERS) == sorted(
        CHANNEL_PUBLICATION_SQLITE_TRIGGERS + CHANNEL_PUBLICATION_SQLITE_TENANT_GUARDS)


# ── Fixrunde 1 / N-925-01: neuer Kurs einer gebundenen Waehrung ─────────────


def _status_of(call):
    try:
        response = call()
    except Exception as exc:  # noqa: BLE001 -- DomainError/HTTPException
        return int(getattr(exc, "status_code", 0) or 0), str(getattr(exc, "reason_code", "") or "")
    return int(getattr(response, "status_code", 200) or 200), ""


def test_new_fresh_rate_of_bound_currency_blocks_every_channel_foreign_rate_does_not(session_factory):
    """N-925-01 (Pruefer R3): USD 0.88 -> 0.93, frisch belegt. Vorher blieb das
    Kanal-Gate «auslieferbar» und Portfolio-/Protokoll-PDF wurden final mit der
    alten Pruefnummer ausgeliefert, waehrend drei andere PDF-Routen sperrten.
    Jetzt sperren Gate, Publikation, alle Entscheid-PDFs, Signatur und Handoff
    einheitlich; ein fremder Kurs (JPY) aendert nichts."""
    from core.reason_codes import ReasonCode
    from models.mandates import Mandate
    from services.allocation_publication_gate import evaluate_allocation_publication, require_channel_envelope
    from tests.test_h12_ccx_hygiene import _gated_calls

    advisor_id, mid, _run = _published_usd(session_factory, "p5-fxchg")
    calls = dict(_gated_calls())
    calls["get_anlagestrategie_pdf"] = lambda m, db, u: _anlagestrategie(db, m, u)
    with session_factory() as db:  # Querschnitt: fremde Waehrung
        _add_fx(db, "JPY", 61)
        db.commit()
    assert _decision(session_factory, mid).ok
    with session_factory() as db:
        assert {name: _status_of(lambda c=c: c(mid, db, _user(db, advisor_id)))[0]
                for name, c in calls.items()} == {name: 200 for name in calls}
        db.rollback()
    with session_factory() as db:  # relevant: neuer, frischer USD-Kurs mit anderem Wert
        _add_fx(db, "USD", 9_300)
        db.commit()
    decision = _decision(session_factory, mid)
    assert decision.reason_code == "CCX_FX_BASIS_CHANGED"
    with session_factory() as db:
        assert "CCX_FX_BASIS_CHANGED" in evaluate_allocation_publication(db, db.get(Mandate, mid)).blockers
    statuses = {}
    for name, call in calls.items():
        with session_factory() as db:
            statuses[name] = _status_of(lambda c=call: c(mid, db, _user(db, advisor_id)))[0]
    assert statuses == {name: 409 for name in calls}, statuses
    with session_factory() as db:
        with pytest.raises(DomainError) as exc:
            require_channel_envelope(db, db.get(Mandate, mid), channel="HANDOFF", user=_user(db, advisor_id),
                                     outdated_code=ReasonCode.CCX_HANDOFF_ENVELOPE_OUTDATED)
        assert exc.value.reason_code == "CCX_FX_BASIS_CHANGED"
        assert "Wechselkurs" in exc.value.as_detail()["cause"]


# ── P5b / N-925R-01: Kundenportal am Kanal-Gate ─────────────────────────────


def test_client_portal_report_uses_the_channel_gate(session_factory):
    """N-925R-01: das Kundenportal zeigte nach USD 0.88 -> 0.93 weiter den
    Bericht (200), obwohl alle anderen Kanaele sperrten. Jetzt neutral 409,
    Code nur im Audit; ein fremder Kurs (JPY) laesst den Bericht offen."""
    from fastapi import HTTPException

    from models.clients import Client
    from models.mandates import Mandate
    from routers.client_portal import _assert_portal_report_releasable

    advisor_id, mid, _run = _published_usd(session_factory, "p5b-portal")

    def check(db):
        mandate = db.get(Mandate, mid)
        return _assert_portal_report_releasable(db, mandate, db.get(Client, mandate.client_id),
                                                _user(db, advisor_id))

    with session_factory() as db:
        _add_fx(db, "JPY", 61)
        db.commit()
    with session_factory() as db:
        check(db)  # offen
    with session_factory() as db:
        _add_fx(db, "USD", 9_300)
        db.commit()
    with session_factory() as db:
        with pytest.raises(HTTPException) as exc:
            check(db)
        assert exc.value.status_code == 409
        assert "CCX_FX_BASIS_CHANGED" not in str(exc.value.detail)  # Kunde sieht neutral
        audit = db.execute(text(
            "SELECT new_value FROM audit_log WHERE field_name = 'client_portal_report_blocked'")).all()
        assert audit and audit[-1][0] == "CCX_FX_BASIS_CHANGED"


@pytest.mark.p5_no_test_vector
def test_end_to_end_finalize_and_publish_without_test_vector(session_factory):
    """N-925R-05: dauerhaft OHNE Optimierer-Testvektor -- Generate, Siegel und
    Publikation laufen, weil der Produktivpfad den kanonischen Vektor selbst
    uebergibt (jeder vergessene Vektor endet hier mit CCX_PARAMETER_SET_MISSING)."""
    from services.optimizer.constraints import test_risky_fraction

    assert test_risky_fraction() is None
    _advisor, _approver, mid, *_rest = _published(session_factory, "p5b-novec")
    decision = _decision(session_factory, mid)
    assert decision.ok and decision.parameter_set_hash


# ── P5b / N-925R-02 + Rest N-925-08 ─────────────────────────────────────────


def test_footer_distinguishes_not_deliverable_from_none_and_skips_allocation_free_docs(session_factory):
    """N-925R-02: versiegelt, aber nicht auslieferbar != keiner versiegelt;
    Risikoprofil/Vertrag ohne Entscheid-Fuss."""
    import routers.pdf_reports as pdf
    from core.customer_terms import DECISION_NONE_TEXT, DECISION_NOT_DELIVERABLE_TEXT, decision_footer_label

    assert decision_footer_label({"allocation_free": True, "ic_release_status": "UNRELEASED"}) == ""
    assert decision_footer_label({"decision_state": "sealed_not_deliverable"}) == DECISION_NOT_DELIVERABLE_TEXT
    assert decision_footer_label(None) == DECISION_NONE_TEXT
    advisor_id, mid, _run = _published_usd(session_factory, "p5b-foot")
    with session_factory() as db:
        _add_fx(db, "USD", 9_300)
        db.commit()
    decision = _decision(session_factory, mid)
    assert not decision.ok and decision.sealed
    assert decision_footer_label(decision.footer_ref()).startswith(DECISION_NOT_DELIVERABLE_TEXT)
    with session_factory() as db:
        body = _text(pdf.get_risikoprofil_pdf(mandate_id=mid, request=_FakeRequest(), db=db,
                                              current_user=_user(db, advisor_id)).body)
    assert "Beratungsentscheid" not in body


def test_fassung_is_monotone_over_refinalisations(session_factory):
    """N-925-08: «Fassung» zaehlt die Versiegelungen des Mandats (statt immer
    der Schema-Version 1)."""
    from tests.test_ccx_p4_allocation_publish import _finalize as finalize
    from tests.test_ccx_p1_snapshot_hash import _finalizable_run

    advisor_id, approver, mid, aid, run_id, _d = _published(session_factory, "p5b-fass")
    first = _decision(session_factory, mid)
    assert first.footer_ref()["fassung"] == "1"
    _a, _m, _aid, run2 = _finalizable_run(session_factory, "p5b-fass2", mandate=(advisor_id, mid, aid))
    finalize(session_factory, advisor_id, mid, run2)
    _publish(session_factory, mid, approver)
    second = _decision(session_factory, mid)
    assert second.ok and second.envelope_hash != first.envelope_hash
    assert second.footer_ref()["fassung"] == "2"


def test_channel_gate_is_evaluated_once_per_pdf(session_factory, monkeypatch):
    """N-925-08: Kontext, Entwurfsentscheid und Archiv lesen dasselbe Gate-
    Ergebnis (frueher bis zu drei Auswertungen je PDF)."""
    import routers.pdf_reports as pdf

    advisor_id, _approver, mid, *_rest = _published(session_factory, "p5b-once")
    calls = []
    real = pdf.evaluate_channel_envelope
    monkeypatch.setattr(pdf, "evaluate_channel_envelope", lambda db, m: calls.append(1) or real(db, m))
    with session_factory() as db:
        _anlagestrategie(db, mid, _user(db, advisor_id))
    assert len(calls) == 1


def test_goal_revision_ignores_timestamp_touch():
    from types import SimpleNamespace

    from core.goal_metric_contract import goal_revision

    goal = SimpleNamespace(id="g", target_amount_rappen=100, target_date="2030-01-01", hardness="Primär",
                           updated_at="2026-01-01")
    before = goal_revision(goal)
    goal.updated_at = "2026-11-21"
    assert goal_revision(goal) == before
    goal.target_amount_rappen = 101
    assert goal_revision(goal) != before


def test_p5b_migration_up_down_up_backfills_monotone_sequence_and_keeps_triggers(tmp_path):
    """N-925-08: Up/Down/Up der linearen P5b-Revision; Bestand erhaelt die
    laufende Nummer in Einfuegereihenfolge, die P5-Trigger ueberleben den
    SQLite-Neuaufbau, und die IC-Spalten bleiben leer."""
    from alembic import command

    db_path = tmp_path / "p5b.db"
    cfg = _alembic_cfg(f"sqlite:///{db_path}")
    command.upgrade(cfg, CCX_P5_REV)

    def triggers(conn):
        return sorted(r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'trigger' AND tbl_name = ?", (P5_TABLE,)))

    with sqlite3.connect(db_path) as conn:
        before = triggers(conn)
        conn.execute("DROP TRIGGER trg_advisory_channel_publications_envelope")
        conn.execute("DROP TRIGGER trg_advisory_channel_publications_tenant_guard")
        conn.execute("PRAGMA foreign_keys = OFF")
        h = "a" * 64
        for rid, mid, at in (("r2", "m1", "2026-11-21T10:00:01"), ("r1", "m1", "2026-11-21T10:00:00"),
                             ("r3", "m2", "2026-11-21T09:00:00")):
            conn.execute(
                f"INSERT INTO {P5_TABLE} (id, tenant_id, mandate_id, envelope_id, channel, artifact_id, "
                "schema_version, channel_payload_hash, rounding_policy_version, bound_envelope_hash, "
                "parameter_contract_version, parameter_set_hash, goal_metric_contract_version, "
                "goal_metric_payload_hash, status, created_at, created_by) VALUES "
                "(?, 'main', ?, 'e', 'API', ?, 'ares/channel-publication/1', ?, 'r', ?, 'p', ?, 'g', ?, "
                "'PUBLISHED', ?, 'u')", (rid, mid, rid, h, h, h, h, at))
        conn.commit()
    command.upgrade(cfg, CCX_P5B_REV)
    with sqlite3.connect(db_path) as conn:
        seq = dict(conn.execute(f"SELECT id, channel_sequence FROM {P5_TABLE}").fetchall())
        assert seq == {"r1": 1, "r2": 2, "r3": 1}
        after = triggers(conn)
        assert set(before) | {"trg_advisory_channel_publications_sequence"} == set(after) | {
            "trg_advisory_channel_publications_envelope", "trg_advisory_channel_publications_tenant_guard"}
        sql = conn.execute("SELECT sql FROM sqlite_master WHERE name = ?", (P5_TABLE,)).fetchone()[0]
        assert "mandates" in sql and "channel_sequence >= 1" in sql and "length(parameter_set_hash) = 64" in sql
        cols = {r[1]: r for r in conn.execute("PRAGMA table_info(optimizer_policies)")}
        assert {"ic_release_ref", "ic_released_at"} <= set(cols)
    command.downgrade(cfg, CCX_P5_REV)
    with sqlite3.connect(db_path) as conn:
        assert "channel_sequence" not in {r[1] for r in conn.execute(f"PRAGMA table_info({P5_TABLE})")}
        assert "ic_release_ref" not in {r[1] for r in conn.execute("PRAGMA table_info(optimizer_policies)")}
        assert conn.execute(f"SELECT COUNT(*) FROM {P5_TABLE}").fetchone()[0] == 3
    command.upgrade(cfg, "head")
    with sqlite3.connect(db_path) as conn:
        assert dict(conn.execute(f"SELECT id, channel_sequence FROM {P5_TABLE}").fetchall())["r2"] == 2


def test_channel_rows_carry_monotone_sequence_per_mandate(session_factory):
    """N-925-08: jede Kanalzeile traegt die naechste Nummer des Mandats; eine
    uebersprungene oder doppelte Nummer lehnt die DB ab."""
    from models.snapshots import AdvisoryChannelPublication

    advisor_id, _approver, mid, *_rest = _published(session_factory, "p5b-seq")
    with session_factory() as db:
        _anlagestrategie(db, mid, _user(db, advisor_id))
        db.commit()
    with session_factory() as db:
        rows = db.query(AdvisoryChannelPublication).filter(
            AdvisoryChannelPublication.mandate_id == mid).order_by(AdvisoryChannelPublication.channel_sequence).all()
        assert rows and [r.channel_sequence for r in rows] == list(range(1, len(rows) + 1))
        clone = {c: getattr(rows[-1], c) for c in rows[-1].__table__.columns.keys()}
        clone.update(id="p5b-seq-skip", artifact_id="p5b-seq-skip", channel_sequence=len(rows) + 2)
        cols = ", ".join(clone)
        with pytest.raises(Exception) as exc:
            db.execute(text(f"INSERT INTO {P5_TABLE} ({cols}) VALUES ({', '.join(':' + k for k in clone)})"), clone)
        assert "CCX_CHANNEL_SEQUENCE_RACE" in str(exc.value)


# ── P5b / N-925-04: Tier-1-Bezug und Archiv-Wiedergabe ──────────────────────


def test_api_carries_envelope_reference_channel_rows_and_parameter_set(session_factory):
    """N-925-04: TargetAllocationResponse und Publikations-Uebersicht tragen
    Pruefnummer, Fassung, Kanalzeilen und den Risikoparametersatz."""
    from models.mandates import Mandate
    from routers.allocation import get_allocation_publication, get_current_allocation
    from schemas.allocation import AllocationPublicationOverviewResponse, TargetAllocationResponse

    advisor_id, _approver, mid, *_rest = _published(session_factory, "p5b-api")
    with session_factory() as db:
        _anlagestrategie(db, mid, _user(db, advisor_id))
        db.commit()
    with session_factory() as db:
        user = _user(db, advisor_id)
        body = TargetAllocationResponse.model_validate(get_current_allocation(mid, db=db, current_user=user))
        ref = body.decision_envelope
        assert ref.state == "deliverable" and len(ref.pruefnummer) == 12 and ref.fassung == 1
        assert ref.parameter_set_hash == body.risk_parameter_set["parameter_set_hash"]
        assert [row.channel for row in ref.channel_publications] == ["PDF"]
        overview = AllocationPublicationOverviewResponse.model_validate(
            get_allocation_publication(mid, db=db, current_user=user))
        assert overview.decision_envelope.pruefnummer == ref.pruefnummer
        _add_fx(db, "USD", 9_300)  # irrelevant ohne USD-Bindung: bleibt auslieferbar (Querschnitt)
        db.flush()
        assert get_current_allocation(mid, db=db, current_user=user).decision_envelope["state"] == "deliverable"
        assert db.get(Mandate, mid) is not None


def test_archive_replay_requires_bytes_hash_of_the_channel_row(session_factory):
    """N-925-04 (§8.3 Punkt 2): Wiedergabe nur bei Bytes-Hash-Gleichheit mit
    der Kanalzeile; Pruefnummer und Fassung im Header."""
    import base64

    from core.reason_codes import DomainError
    from models.review import ContractDocument
    from routers.review import get_document_pdf
    from services.allocation_publication_gate import verify_archive_replay

    advisor_id, _approver, mid, *_rest = _published(session_factory, "p5b-replay")
    with session_factory() as db:
        _anlagestrategie(db, mid, _user(db, advisor_id))
        db.commit()
    with session_factory() as db:
        doc = db.query(ContractDocument).filter(ContractDocument.mandate_id == mid,
                                                ContractDocument.pdf_base64.isnot(None)).first()
        resp = get_document_pdf(mid, str(doc.id), db=db, current_user=_user(db, advisor_id))
        assert resp.headers["X-Ares-Pruefnummer"] and resp.headers["X-Ares-Fassung"] == "1"
        with pytest.raises(DomainError) as exc:
            verify_archive_replay(db, doc, base64.b64decode(doc.pdf_base64) + b"%tampered")
        assert exc.value.reason_code == "CCX_SEALED_ARTIFACT_HASH_MISMATCH"
