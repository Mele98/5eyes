"""C-COMP-02 V2: verbindliche Vorab-Entscheide 6.1 bis 6.5 (26.11.2026).

* 6.1 Envelope-Schema ``ares/advisory-envelope/2`` mit versiegeltem
  ``product_evidence_set_hash``; V1 bleibt mit dem V1-Kanonisierer bytegenau
  pruefbar und read-only (historisch), wird nie hochgestuft oder neu
  versiegelt und ist fuer neue Kundenkanaele LEGACY/STALE.
* 6.2 Vor der Migration versiegelte Entscheide: STALE fuer kuenftige
  Auslieferung, nicht beschaedigt (Integritaet bleibt gueltig).
* 6.3 ``eligibility_snapshot_id``/``cost_snapshot_id``/``conflict_snapshot_id``
  sind immer gebunden; nicht anwendbare Dimensionen tragen einen typisierten
  ``not_applicable``-Snapshot mit Quelle, Freigabe und SHA-256-Hash.
* 6.4 Share-Class-Identitaet an der DB-Grenze: ein direkter Insert einer
  fremden/abweichenden Anteilsklassenzeile scheitert an der Datenbank.
* 6.5 ``override_ter_bps`` wirkt nur ueber einen tenantgebundenen,
  freigegebenen Kostennachweis (Kostennachweis) mit gleichem Satz, gebunden im
  ``cost_snapshot_id``; sonst ``PRODUCT_EVIDENCE_COST_MISSING`` -- weder
  Anwendung noch stiller Rueckfall auf den Standardwert.

Synthetische Daten, Wegwerf-SQLite. Die PostgreSQL-Gegenstuecke stehen in
``test_postgres_c_comp_02_v2_share_class_evidence.py``.
"""
from __future__ import annotations

import io
import json
import sqlite3
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

import services.advisory_decision_envelope as envelope_svc
import services.product_eligibility as evidence
from core import product_evidence as contract
from core.advisory_envelope_codec import (
    CanonicalPayloadError,
    ENVELOPE_PAYLOAD_SCHEMA_V1,
    ENVELOPE_PAYLOAD_SCHEMA_V2,
    envelope_hash,
    parse_canonical,
    root_hash,
)
from core.evidence import ADVISORY_ENVELOPE_SCHEMA_V1, ADVISORY_ENVELOPE_SCHEMA_V2
from core.reason_codes import DomainError
from database import new_uuid
from models.mandates import Mandate
from models.product_eligibility import ProductEvidenceItem, ProductEvidenceSnapshot
from models.review import ProductUniverseEntry, RecommendationRun
from models.snapshots import AdvisoryDecisionEnvelope, AdvisoryEnvelopeBinding
from services.advisory_envelope_integrity import envelope_integrity_defect, verify_root_hash
from tests.test_c_comp_02_product_evidence import (  # noqa: F401
    TENANT, _code, _complete, _mandate_view, _now, _product, _raw_item, _run, db, engine,
)
from tests.test_ccx_p1_snapshot_hash import (  # noqa: F401
    GOLDEN_CANONICAL, GOLDEN_HASH, _alembic_cfg, _finalizable_run, _finalize, session_factory,
)


# -- 6.1 / 6.2 Envelope-Schema ------------------------------------------------


def _sealed(db, mid) -> AdvisoryDecisionEnvelope:
    return db.query(AdvisoryDecisionEnvelope).filter_by(mandate_id=mid, status="SEALED").one()


def test_new_decisions_are_sealed_only_as_v2_with_product_evidence_set_hash(session_factory):  # noqa: F811
    advisor_id, mid, _aid, run_id = _finalizable_run(session_factory, "v2-seal")
    _finalize(session_factory, advisor_id, mid, run_id)
    with session_factory() as db:
        sealed = _sealed(db, mid)
        run = db.get(RecommendationRun, run_id)
        payload = parse_canonical(sealed.canonical_payload_json, ENVELOPE_PAYLOAD_SCHEMA_V2)
        binding = db.query(AdvisoryEnvelopeBinding).filter_by(
            envelope_id=sealed.id, binding_kind="product_evidence_set").one()
        assert sealed.schema_version == payload["schema_version"] == ADVISORY_ENVELOPE_SCHEMA_V2
        assert payload["product_evidence_set_hash"] == run.product_evidence_hash == binding.child_hash
        assert envelope_svc.verify_envelope(db, sealed) is None
        assert envelope_svc.envelope_view(sealed)["product_evidence_set_hash"] == run.product_evidence_hash
        # V2-Bytes sind mit der V2-Domaene gehasht, nie mit der V1-Domaene.
        canonical = sealed.canonical_payload_json.encode("utf-8")
        assert root_hash(canonical, ADVISORY_ENVELOPE_SCHEMA_V2) == sealed.envelope_hash
        assert root_hash(canonical, ADVISORY_ENVELOPE_SCHEMA_V1) != sealed.envelope_hash
        assert envelope_svc.pull_freshness(db, sealed, mandate=db.get(Mandate, mid))[0] is None


def test_v1_artifact_stays_byte_exactly_verifiable_read_only_and_is_never_reinterpreted():
    """Historische V1-Bytes: V1-Kanonisierer + V1-Domaene -> gueltig; als V2
    gelesen -> abgelehnt (keine stille Hochstufung)."""
    assert verify_root_hash({"canonical_payload_json": GOLDEN_CANONICAL, "envelope_hash": GOLDEN_HASH,
                             "schema_version": ADVISORY_ENVELOPE_SCHEMA_V1})
    assert verify_root_hash({"canonical_payload_json": GOLDEN_CANONICAL, "envelope_hash": GOLDEN_HASH})
    assert parse_canonical(GOLDEN_CANONICAL, ENVELOPE_PAYLOAD_SCHEMA_V1)["schema_version"] == ADVISORY_ENVELOPE_SCHEMA_V1
    with pytest.raises(CanonicalPayloadError):
        parse_canonical(GOLDEN_CANONICAL, ENVELOPE_PAYLOAD_SCHEMA_V2)
    assert not verify_root_hash({"canonical_payload_json": GOLDEN_CANONICAL, "envelope_hash": GOLDEN_HASH,
                                 "schema_version": ADVISORY_ENVELOPE_SCHEMA_V2})
    v2 = {**json.loads(GOLDEN_CANONICAL), "schema_version": ADVISORY_ENVELOPE_SCHEMA_V2,
          "product_evidence_set_hash": "c" * 64}
    with pytest.raises(CanonicalPayloadError):
        envelope_hash({**v2, "schema_version": ADVISORY_ENVELOPE_SCHEMA_V1})  # V1 kennt das Feld nicht
    with pytest.raises(CanonicalPayloadError):
        envelope_hash({key: value for key, value in v2.items() if key != "product_evidence_set_hash"})


def test_v2_set_hash_must_equal_the_bound_product_evidence_child_hash():
    """Mutation: ein konsistent neu gehashter V2-Payload mit fremdem Satz-Hash."""
    bindings = [
        {"binding_kind": "effective_input_manifest", "ordinal": 0, "object_type": "m", "object_id": "man-1",
         "object_version": None, "child_hash": "a" * 64},
        {"binding_kind": "product_evidence_set", "ordinal": 0, "object_type": "product_evidence_snapshots",
         "object_id": "s-1", "object_version": None, "child_hash": "b" * 64},
    ]
    payload = {"schema_version": ADVISORY_ENVELOPE_SCHEMA_V2, "tenant_id": "t", "mandate_id": "m", "locale": "DE",
               "base_currency": "CHF", "rounding_policy_version": "ares-rounding/1",
               "predecessor_envelope_hash": None, "effective_input_manifest_hash": "a" * 64,
               "product_evidence_set_hash": "d" * 64, "bindings": bindings}
    canonical, digest = envelope_hash(payload)
    row = SimpleNamespace(status="SEALED", sealed_at="x", sealed_by="u", canonical_payload_json=canonical,
                          envelope_hash=digest, schema_version=ADVISORY_ENVELOPE_SCHEMA_V2, tenant_id="t",
                          mandate_id="m", locale="DE", base_currency="CHF")
    assert envelope_integrity_defect(row, bindings, None) == (
        "CCX_ENVELOPE_HASH_MISMATCH", "product_evidence_set_hash")


def _seal_as_pre_migration_v1(monkeypatch, session_factory, suffix):  # noqa: F811
    """Simuliert einen VOR der Migration versiegelten Entscheid: derselbe
    Siegelweg, aber mit dem V1-Schema (ohne Satz-Hash im Payload)."""
    real = envelope_svc.compute_envelope_hash
    advisor_id, mid, _aid, run_id = _finalizable_run(session_factory, suffix)
    with monkeypatch.context() as patch:
        patch.setattr(envelope_svc, "ADVISORY_ENVELOPE_SEAL_SCHEMA", ADVISORY_ENVELOPE_SCHEMA_V1)
        patch.setattr(envelope_svc, "compute_envelope_hash", lambda payload: real(
            {key: value for key, value in payload.items() if key != "product_evidence_set_hash"}))
        _finalize(session_factory, advisor_id, mid, run_id)
    return advisor_id, mid


def test_pre_migration_v1_decision_is_stale_for_customer_channels_but_not_corrupt(monkeypatch, session_factory):  # noqa: F811
    advisor_id, mid = _seal_as_pre_migration_v1(monkeypatch, session_factory, "v1-legacy")
    with session_factory() as db:
        sealed = _sealed(db, mid)
        before = {c.name: getattr(sealed, c.name) for c in AdvisoryDecisionEnvelope.__table__.columns}
        assert sealed.schema_version == ADVISORY_ENVELOPE_SCHEMA_V1
        # Historisch: integer, bytegenau mit dem V1-Kanonisierer.
        assert envelope_svc.verify_envelope(db, sealed) is None
        assert envelope_svc.envelope_view(sealed)["product_evidence_set_hash"] is None
        # Neuer Kundenkanal: LEGACY -> STALE, ohne Schreibzugriff.
        mandate = db.get(Mandate, mid)
        assert envelope_svc.pull_freshness(db, sealed, mandate=mandate)[:2] == (
            "CCX_INPUT_STALE", envelope_svc.LEGACY_ENVELOPE_DETAIL)
        status = envelope_svc.current_envelope_freshness(db, mandate=mandate)
        assert status["freshness_status"] == "STALE"
        from models.users import User

        with pytest.raises(DomainError) as exc:
            envelope_svc.current_verified_envelope(db, mandate=mandate, user=db.get(User, advisor_id))
        assert exc.value.reason_code == "CCX_INPUT_STALE"
    with session_factory() as db:
        after = _sealed(db, mid)
        # Keine Hochstufung, kein Neuversiegeln: die Zeile ist byte-gleich.
        assert {c.name: getattr(after, c.name) for c in AdvisoryDecisionEnvelope.__table__.columns} == before


def test_reverting_the_legacy_gate_would_deliver_a_v1_decision(monkeypatch, session_factory):  # noqa: F811
    """Mutationskontrolle: ohne die LEGACY-Regel waere der V1-Entscheid FRESH."""
    _advisor, mid = _seal_as_pre_migration_v1(monkeypatch, session_factory, "v1-mut")
    monkeypatch.setattr(envelope_svc, "is_legacy_envelope", lambda _envelope: False)
    with session_factory() as db:
        assert envelope_svc.pull_freshness(db, _sealed(db, mid), mandate=db.get(Mandate, mid))[0] is None


# -- 6.3 Dimensions-Snapshots ------------------------------------------------


def test_every_new_set_binds_three_typed_hashed_dimension_snapshots(db):  # noqa: F811
    product = _product(ter_bps=None)
    product.product_type = "Cash"
    db.add(product)
    _complete(db, product)
    run, mandate = _run(db, product)
    snapshot = evidence.snapshot_run_product_evidence(db, mandate, run)
    payload = json.loads(snapshot.canonical_payload_json)
    assert payload["schema_version"] == contract.PRODUCT_EVIDENCE_SCHEMA
    dims = payload["dimension_snapshots"]
    assert set(dims) == {"eligibility", "cost", "conflict"}
    for dimension, column in contract.DIMENSION_COLUMNS.items():
        record = dims[dimension]
        assert getattr(snapshot, column) == record["snapshot_id"] == f"{dimension}:{record['snapshot_hash']}"
        assert record["snapshot_hash"] == contract.dimension_snapshot_hash(record)
        assert record["sources"] and record["approvals"]
        assert all(source["source_reference"] and len(source["source_document_sha256"]) == 64
                   for source in record["sources"])
        assert all(approval["approved_by"] and approval["approval_mode"] for approval in record["approvals"])
    # Cash ohne TER, ohne Retrozession: typisiert nicht anwendbar, mit Hash.
    assert dims["cost"]["status"] == contract.NOT_APPLICABLE
    assert dims["conflict"]["status"] == contract.NOT_APPLICABLE
    assert dims["eligibility"]["status"] == "bound"
    assert contract.run_evidence_state(evidence._evidence_query(db), run.id, today=evidence.evidence_today())[0] is None


def test_database_rejects_a_new_set_with_an_unbound_dimension(db):  # noqa: F811
    product = _product()
    db.add(product)
    _complete(db, product)
    run, mandate = _run(db, product)
    snapshot = evidence.snapshot_run_product_evidence(db, mandate, run)
    values = {c.name: getattr(snapshot, c.name) for c in ProductEvidenceSnapshot.__table__.columns}
    for column, bad in (("cost_snapshot_id", None), ("conflict_snapshot_id", "conflict:xyz"),
                        ("eligibility_snapshot_id", "cost:" + "a" * 64)):
        with pytest.raises(IntegrityError, match="Konfliktsnapshot muessen gebunden"):
            with db.begin_nested():
                db.add(ProductEvidenceSnapshot(**{**values, "id": new_uuid(), "product_evidence_hash": new_uuid(),
                                                  column: bad}))
                db.flush()


def test_tampered_dimension_snapshot_is_a_hash_mismatch(db):  # noqa: F811
    product = _product()
    db.add(product)
    _complete(db, product)
    run, mandate = _run(db, product)
    snapshot = evidence.snapshot_run_product_evidence(db, mandate, run)
    payload = json.loads(snapshot.canonical_payload_json)
    payload["dimension_snapshots"]["cost"]["status"] = contract.NOT_APPLICABLE  # Hash nicht nachgezogen
    canonical, digest = evidence.product_evidence_hash(payload)
    values = {c.name: getattr(snapshot, c.name) for c in ProductEvidenceSnapshot.__table__.columns}
    db.add(ProductEvidenceSnapshot(**{**values, "id": "tampered", "canonical_payload_json": canonical,
                                      "product_evidence_hash": digest}))
    db.flush()
    run.product_evidence_snapshot_id, run.product_evidence_hash = "tampered", digest
    db.flush()
    defect = contract.run_evidence_state(evidence._evidence_query(db), run.id, today=evidence.evidence_today())[0]
    assert defect.code == contract.HASH_MISMATCH


def test_legacy_v1_set_without_dimensions_is_stale_not_corrupt(engine, db):  # noqa: F811
    product = _product()
    db.add(product)
    _complete(db, product)
    run, mandate = _run(db, product)
    items = [evidence._evidence_row_view(row) for row in evidence.effective_product_evidence_items(
        db, mandate, [product.id])]
    items.sort(key=contract.item_sort_key)
    payload = evidence.product_evidence_set(mandate, run, [product.id], items)
    payload.pop("dimension_snapshots")
    payload["schema_version"] = contract.PRODUCT_EVIDENCE_SCHEMA_LEGACY
    canonical, digest = evidence.product_evidence_hash(payload)
    db.commit()
    # Altbestand vor der Migration: ohne den Einfuege-Trigger angelegt.
    with engine.begin() as conn:
        conn.execute(text("DROP TRIGGER trg_product_evidence_snapshot_binding_insert"))
        conn.execute(text(
            "INSERT INTO product_evidence_snapshots (id, tenant_id, mandate_id, recommendation_run_id, "
            "product_ids_json, item_ids_json, item_hashes_json, as_of, evaluated_at, status, reason_codes_json, "
            "canonical_payload_json, product_evidence_hash, schema_version, evaluator_version, created_at) "
            "VALUES ('legacy', :t, :m, :r, :p, :i, :h, :a, :a, 'verified', '[]', :c, :d, :s, "
            "'ares-product-evidence/1', :a)"
        ), {"t": TENANT, "m": mandate.id, "r": run.id, "p": json.dumps([product.id]),
            "i": json.dumps([item["id"] for item in payload["items"]]),
            "h": json.dumps([item["canonical_payload_hash"] for item in payload["items"]]),
            "a": payload["as_of"], "c": canonical, "d": digest, "s": contract.PRODUCT_EVIDENCE_SCHEMA_LEGACY})
        conn.execute(text(
            "UPDATE recommendation_runs SET product_evidence_snapshot_id = 'legacy', product_evidence_hash = :d, "
            "product_evidence_status = 'verified' WHERE id = :r"), {"d": digest, "r": run.id})
    db.expire_all()
    defect = contract.run_evidence_state(evidence._evidence_query(db), run.id, today=evidence.evidence_today())[0]
    assert defect.code == contract.STALE
    assert contract.stored_json_hash(canonical, domain=contract.PRODUCT_EVIDENCE_DOMAIN) == digest  # integer


# -- 6.4 Share-Class-Identitaet an der DB-Grenze ------------------------------


@pytest.mark.parametrize("product_sc,item_sc", [(None, "SC-OTHER"), ("SC-A", None), ("SC-A", "SC-B")])
def test_direct_insert_of_a_foreign_share_class_row_fails_at_the_database(db, product_sc, item_sc):  # noqa: F811
    product = _product(share_class_figi=product_sc)
    db.add(product)
    db.flush()
    with pytest.raises(IntegrityError, match="PRODUCT_EVIDENCE_SHARE_CLASS_MISMATCH"):
        with db.begin_nested():
            _raw_item(db, product, "kid", share_class_id=item_sc)
    with pytest.raises(IntegrityError, match="PRODUCT_EVIDENCE_SHARE_CLASS_MISMATCH"):
        with db.begin_nested():
            _raw_item(db, product, "kid", stable_instrument_id="SYNTH-OTHER-INSTRUMENT")
    assert db.query(ProductEvidenceItem).count() == 0
    # Positivkontrolle: die exakt passende Zeile (Leerraum == NULL) ist zulaessig.
    _raw_item(db, product, "kid", share_class_id=f"  {product_sc}  " if product_sc else "   ")
    assert db.query(ProductEvidenceItem).count() == 1


def test_identity_update_is_guarded_but_revocation_after_product_change_still_works(db):  # noqa: F811
    product = _product(share_class_figi="SC-A")
    db.add(product)
    draft = _raw_item(db, product, "kid", status="draft", share_class_id="SC-A")
    with pytest.raises(IntegrityError, match="PRODUCT_EVIDENCE_SHARE_CLASS_MISMATCH"):
        with db.begin_nested():
            db.execute(text("UPDATE product_evidence_items SET share_class_id = 'SC-B' WHERE id = :i"),
                       {"i": draft.id})
    approved = _raw_item(db, product, "costs", share_class_id="SC-A")
    product.share_class_figi = "SC-B"
    db.flush()
    evidence.close_product_evidence_item(db, approved, status="revoked", reason="SHARE_CLASS_CHANGED",
                                         actor_id="approver")
    db.flush()
    assert approved.status == "revoked"


# -- 6.5 override_ter_bps nur mit tenantgebundenem Kostennachweis -------------


def _override(db, product, bps, *, tenant=TENANT, jurisdiction="CH"):
    db.add(ProductUniverseEntry(id=new_uuid(), tenant_id=tenant, jurisdiction=jurisdiction, product_id=product.id,
                                override_ter_bps=bps, created_by="creator", created_at=_now(), updated_at=_now()))
    db.flush()


def test_override_without_tenant_cost_evidence_blocks_with_cost_missing(db):  # noqa: F811
    product = _product(ter_bps=20)
    db.add(product)
    _complete(db, product, tenant_id=None)  # nur Plattform-Kostennachweis (20 bps)
    _override(db, product, 5)
    result = evidence.evaluate_product_evidence(db, _mandate_view(), product)
    assert {issue["reason_code"] for issue in result["issues"]} == {"PRODUCT_EVIDENCE_COST_MISSING"}
    run, mandate = _run(db, product)
    assert _code(lambda: evidence.snapshot_run_product_evidence(db, mandate, run)) == "PRODUCT_EVIDENCE_COST_MISSING"
    # Positivkontrolle ohne Override: der Plattform-Nachweis genuegt.
    other = _product("p-2", ter_bps=20)
    db.add(other)
    _complete(db, other, tenant_id=None)
    assert evidence.evaluate_product_evidence(db, _mandate_view(), other)["status"] == "verified"
    # Override eines anderen Tenants / anderer Jurisdiktion wirkt nicht.
    _override(db, other, 5, tenant="tenant-2")
    _override(db, other, 5, jurisdiction="DE")
    assert evidence.evaluate_product_evidence(db, _mandate_view(), other)["status"] == "verified"


@pytest.mark.parametrize("tenant_value,expected", [(5, "verified"), (7, "missing")])
def test_override_needs_tenant_cost_evidence_with_exactly_that_rate(db, tenant_value, expected):  # noqa: F811
    product = _product(ter_bps=20)
    db.add(product)
    _complete(db, product, tenant_id=None)
    _complete(db, product, kinds=("costs",), overrides={"costs": {"payload": {"value": tenant_value,
                                                                              "unit": "bps_per_year"}}})
    _override(db, product, 5)
    result = evidence.evaluate_product_evidence(db, _mandate_view(), product)
    assert result["status"] == expected
    if expected != "verified":
        assert {issue["reason_code"] for issue in result["issues"]} == {"PRODUCT_EVIDENCE_COST_MISSING"}
        return
    run, mandate = _run(db, product)
    snapshot = evidence.snapshot_run_product_evidence(db, mandate, run)
    cost = json.loads(snapshot.canonical_payload_json)["dimension_snapshots"]["cost"]
    tenant_item = next(item for item in result["items"] if item.evidence_kind == "costs")
    assert tenant_item.tenant_id == TENANT
    assert cost["negotiated_conditions"] == [
        {"product_id": product.id, "override_ter_bps": 5, "item_id": tenant_item.id}]
    assert snapshot.cost_snapshot_id == f"cost:{cost['snapshot_hash']}"
    terms = contract.bound_rate_terms(evidence._evidence_query(db), run.id, today=evidence.evidence_today())
    assert contract.bound_term(terms, product.id, "costs") == ("known", 5)


def test_override_set_after_binding_blocks_finalisation_and_disclosure_never_falls_back(db):  # noqa: F811
    product = _product(ter_bps=20)
    db.add(product)
    _complete(db, product, tenant_id=None)
    run, mandate = _run(db, product)
    evidence.snapshot_run_product_evidence(db, mandate, run)
    query = evidence._evidence_query(db)
    assert contract.bound_term(contract.bound_rate_terms(query, run.id, today=evidence.evidence_today()),
                               product.id, "costs") == ("known", 20)
    _override(db, product, 5)
    assert _code(lambda: evidence.bind_run_product_evidence(db, mandate, run, channel="finalize")) == (
        "PRODUCT_EVIDENCE_COST_MISSING")
    defect = contract.run_evidence_state(query, run.id, today=evidence.evidence_today())[0]
    assert defect.code == "PRODUCT_EVIDENCE_COST_MISSING"
    # Weder der Override (5) noch der Standardwert (20): unbekannt.
    assert contract.bound_term(contract.bound_rate_terms(query, run.id, today=evidence.evidence_today()),
                               product.id, "costs") == ("missing", None)


def test_override_changed_after_binding_is_stale_via_the_bound_cost_snapshot(db):  # noqa: F811
    product = _product(ter_bps=20)
    db.add(product)
    _complete(db, product, tenant_id=None)
    _complete(db, product, kinds=("costs",), overrides={"costs": {"payload": {"value": 5, "unit": "bps_per_year"}}})
    _override(db, product, 5)
    run, mandate = _run(db, product)
    evidence.snapshot_run_product_evidence(db, mandate, run)
    entry = db.query(ProductUniverseEntry).filter_by(product_id=product.id).one()
    entry.deleted_at = _now()  # Kondition beendet; Tenant-Nachweis bleibt wirksam
    db.flush()
    defect = contract.run_evidence_state(evidence._evidence_query(db), run.id, today=evidence.evidence_today())[0]
    assert defect.code == contract.STALE


# -- SQLite-Bestand und Migration --------------------------------------------


def _legacy_envelope_db(tmp_path, check):
    import database

    path = tmp_path / "legacy.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE tenants (id TEXT PRIMARY KEY)")
    conn.execute("CREATE TABLE users (id TEXT PRIMARY KEY)")
    ddl = database.ADVISORY_ENVELOPE_SQLITE_TABLE_DDL[0].replace(
        "CHECK(schema_version IN ('ares/advisory-envelope/1','ares/advisory-envelope/2'))", check)
    conn.execute(ddl)
    conn.commit()
    conn.close()
    return create_engine(f"sqlite:///{path}")


def test_existing_sqlite_envelope_check_is_widened_verified_and_idempotent(tmp_path):
    from services.sqlite_check_constraint_upgrade import CheckUpgradeOutcome, upgrade_sqlite_exact_check_rewrites

    engine = _legacy_envelope_db(tmp_path, "CHECK(schema_version = 'ares/advisory-envelope/1')")
    insert = ("INSERT INTO advisory_decision_envelopes (id, tenant_id, mandate_id, schema_version, locale, "
              "base_currency, created_at, created_by) VALUES (:i, 't', 'm', :s, 'DE', 'CHF', 'x', 'u')")
    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.execute(text(insert), {"i": "e0", "s": ADVISORY_ENVELOPE_SCHEMA_V2})
    with engine.begin() as conn:
        conn.execute(text(insert), {"i": "e1", "s": ADVISORY_ENVELOPE_SCHEMA_V1})  # Bestand
    result = upgrade_sqlite_exact_check_rewrites(engine, backup_dir=tmp_path / "backup")
    assert result.outcome is CheckUpgradeOutcome.APPLIED_VERIFIED
    assert result.backup_file is not None and result.backup_file.exists()
    with engine.begin() as conn:
        conn.execute(text(insert), {"i": "e2", "s": ADVISORY_ENVELOPE_SCHEMA_V2})
        assert conn.execute(text("SELECT schema_version FROM advisory_decision_envelopes WHERE id = 'e1'")
                            ).scalar() == ADVISORY_ENVELOPE_SCHEMA_V1  # unveraendert, nicht hochgestuft
    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.execute(text(insert), {"i": "e3", "s": "ares/advisory-envelope/3"})
    assert upgrade_sqlite_exact_check_rewrites(engine, backup_dir=tmp_path / "backup").outcome is (
        CheckUpgradeOutcome.NOOP)
    engine.dispose()


def test_unknown_envelope_check_form_requires_manual_migration(tmp_path):
    from services.sqlite_check_constraint_upgrade import CheckUpgradeOutcome, upgrade_sqlite_exact_check_rewrites

    engine = _legacy_envelope_db(tmp_path, "CHECK(length(schema_version) > 0)")
    result = upgrade_sqlite_exact_check_rewrites(engine, backup_dir=tmp_path / "backup")
    assert result.outcome is CheckUpgradeOutcome.MANUAL_MIGRATION_REQUIRED
    engine.dispose()


_V2_REVISION = "4b8e2d6f1a9c"


def test_alembic_head_admits_v2_envelopes_and_guards_identity_and_dimensions(tmp_path):
    from alembic import command
    from alembic.script import ScriptDirectory

    url = f"sqlite:///{(tmp_path / 'm.db').as_posix()}"
    cfg = _alembic_cfg(url)
    assert ScriptDirectory.from_config(cfg).get_heads() == [_V2_REVISION]
    command.upgrade(cfg, "head")
    engine = create_engine(url)
    with engine.connect() as conn:
        ddl = conn.execute(text("SELECT sql FROM sqlite_master WHERE name = 'advisory_decision_envelopes'")).scalar()
        triggers = {row[0] for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type = 'trigger'"))}
    assert "'ares/advisory-envelope/2'" in ddl
    assert {"trg_product_evidence_identity_insert", "trg_product_evidence_identity_update",
            "trg_product_evidence_snapshot_binding_insert"} <= triggers
    command.downgrade(cfg, "9f4c2a7e1b63")
    with engine.connect() as conn:
        ddl = conn.execute(text("SELECT sql FROM sqlite_master WHERE name = 'advisory_decision_envelopes'")).scalar()
    assert "'ares/advisory-envelope/2'" not in ddl
    command.upgrade(cfg, "head")
    engine.dispose()


def test_postgres_revision_sql_widens_the_envelope_check_and_installs_both_triggers():
    from alembic import command

    buffer = io.StringIO()
    cfg = _alembic_cfg("postgresql://u:p@localhost/db")
    cfg.output_buffer = buffer
    command.upgrade(cfg, f"9f4c2a7e1b63:{_V2_REVISION}", sql=True)
    sql = buffer.getvalue()
    assert "ares/advisory-envelope/2" in sql
    assert "CREATE TRIGGER trg_product_evidence_identity BEFORE INSERT OR UPDATE OF" in sql
    assert "CREATE TRIGGER trg_product_evidence_snapshot_binding BEFORE INSERT" in sql


def test_reproducer_scenario_direct_foreign_row_cannot_reach_evaluation(db):  # noqa: F811
    """Wie der Deep-Contracts-Reproducer: die fremde Zeile wird direkt
    eingefuegt und scheitert an der DB-Grenze (vor jeder Auswertung)."""
    product = _product("deep-mismatch")
    db.add(product)
    db.flush()
    with pytest.raises(IntegrityError, match="PRODUCT_EVIDENCE_SHARE_CLASS_MISMATCH"):
        with db.begin_nested():
            _raw_item(db, product, "kid", share_class_id="synthetic-other-share-class")
    assert evidence.evaluate_product_evidence(db, _mandate_view(), product)["status"] == "missing"


def test_spelled_out_trigger_sql_matches_the_single_identity_and_binding_rule():
    """Die ausgeschriebenen Trigger-Bedingungen (Stdlib-Blatt) sind exakt die
    Regel aus ``identity_mismatch_sql``/``dimension_id_check_sql``."""
    assert contract.SQLITE_IDENTITY_MISMATCH_SQL == contract.identity_mismatch_sql("sqlite")
    assert contract.PG_IDENTITY_MISMATCH_SQL == contract.identity_mismatch_sql("postgresql")
    assert contract.SNAPSHOT_BINDING_SQL == " AND ".join(
        [contract.dimension_id_check_sql(f"NEW.{column}", dimension)
         for dimension, column in contract.DIMENSION_COLUMNS.items()]
        + [f"NEW.schema_version = '{contract.PRODUCT_EVIDENCE_SCHEMA}'"]
    )
