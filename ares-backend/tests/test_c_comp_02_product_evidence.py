"""C-COMP-02: Product-Evidence v1 -- Vertrag, Auswertung, Pflegeweg, DB-Regeln.

Dieses Modul steht bewusst NICHT in ``SYNTHETIC_EVIDENCE_MODULES``: ohne
ausdruecklich angelegte Nachweise gibt es keine Evidenz. Kanal- und P5-Vertraege:
``test_c_comp_02_channels.py``.
"""
from __future__ import annotations

import io
import json
import sqlite3
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import DatabaseError, IntegrityError
from sqlalchemy.orm import sessionmaker

import main as _model_registry  # noqa: F401 - vollstaendige Metadaten
import services.portfolio_engine as portfolio_engine
import services.product_eligibility as evidence
from core import product_evidence as contract
from core.reason_codes import DomainError, ReasonCode
from database import Base, new_uuid
from models.mandates import Mandate
from models.product_eligibility import ProductEvidenceItem, ProductEvidenceSnapshot
from models.review import Product, RecommendationPosition, RecommendationRun
from product_evidence_test_support import add_synthetic_product_evidence, synthetic_values
from tests.test_ccx_p1_snapshot_hash import _alembic_cfg
from tests.test_esg_manual_final_missingness import (  # noqa: F401
    SF, _add_position, _add_product, _draft_run, _generate_ta, _positions_of, _seed,
)

TENANT, OTHER = "tenant-1", "tenant-2"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today(offset: int = 0) -> str:
    return (datetime.now(timezone.utc).date() + timedelta(days=offset)).isoformat()


@pytest.fixture()
def engine(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'evidence.db'}", connect_args={"timeout": 1})
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def db(engine):
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    yield session
    session.close()


def _product(product_id="p-1", *, tenant_id=None, ter_bps=25, **extra) -> Product:
    now = _now()
    return Product(
        id=product_id, tenant_id=tenant_id, product_name=f"Synthetisches Produkt {product_id}",
        provider="Synthetischer Anbieter", product_type="Fonds", asset_class="Aktien",
        sub_asset_class="Aktien Schweiz", currency="CHF", ter_bps=ter_bps, is_active=1,
        created_at=now, updated_at=now, **extra,
    )


def _mandate_view(tenant=TENANT, jurisdiction="CH"):
    return SimpleNamespace(id="mandate-1", tenant_id=tenant, jurisdiction=jurisdiction)


def _complete(db, product, *, tenant_id=TENANT, **kw):
    return add_synthetic_product_evidence(db, [product], actor_id="creator", tenant_id=tenant_id, **kw)


def _raw_item(db, product, kind="kid", *, item_id=None, tenant_id=TENANT, status="approved", **over):
    """Direkte Zeile (Import-/Altbestandsfall) ohne Pflegeweg."""
    values = synthetic_values(product, kind)
    payload = values.pop("payload")
    canonical, digest = evidence.product_evidence_item_payload_hash(over.pop("payload", payload))
    values.update(
        id=item_id or new_uuid(), tenant_id=tenant_id, product_id=product.id, canonical_payload_json=canonical,
        canonical_payload_hash=digest, status=status, created_by="creator", created_at=_now(), updated_at=_now(),
    )
    if status != "draft":
        values.update(approved_by="approver", approved_at=_now(), approval_mode="four_eyes")
    values.update(over)
    row = ProductEvidenceItem(**values)
    db.add(row)
    db.flush()
    return row


def _run(db, *products, run_id="run-1", tenant=TENANT):
    now = _now()
    mandate = db.get(Mandate, "mandate-1")
    if mandate is None:
        mandate = Mandate(**{
            column.name: "x" for column in Mandate.__table__.columns
            if not column.nullable and column.default is None and column.server_default is None
            and str(column.type).startswith("VARCHAR")
        })
        mandate.id, mandate.tenant_id, mandate.jurisdiction, mandate.client_id = "mandate-1", tenant, "CH", "client-1"
        db.add(mandate)
    run = RecommendationRun(
        id=run_id, mandate_id="mandate-1", client_id="client-1", policy_id="policy-1", run_type="Optimizer",
        result_status="Draft", created_by="creator", created_at=now, updated_at=now,
    )
    db.add(run)
    for product in products:
        _position(db, run, product)
    db.flush()
    return run, mandate


def _position(db, run, product):
    now = _now()
    db.add(RecommendationPosition(
        id=new_uuid(), run_id=run.id, product_id=product.id, target_weight_bps=1000, created_at=now, updated_at=now,
    ))
    db.flush()


def _codes(result):
    return {issue["reason_code"] for issue in result["issues"]}


def _code(call):
    with pytest.raises(DomainError) as exc:
        call()
    return exc.value.reason_code


def _revoke(db, row):
    evidence.close_product_evidence_item(db, row, status="revoked", reason="SOURCE_WITHDRAWN", actor_id="approver")


# -- Kanonisierung -----------------------------------------------------------


def test_canonical_codec_is_domain_separated_and_rejects_binary_float():
    first = {"z": "é", "amount": 25, "nested": {"b": True, "a": None}}
    second = {"nested": {"a": None, "b": True}, "amount": 25, "z": "é"}
    assert evidence.canonical_product_evidence_json(first) == evidence.canonical_product_evidence_json(second)
    assert evidence.product_evidence_hash(first)[1] == evidence.product_evidence_hash(second)[1]
    assert evidence.product_evidence_hash(first)[1] != evidence.product_evidence_item_payload_hash(first)[1]
    with pytest.raises(ValueError, match="Binärfloat"):
        evidence.canonical_product_evidence_json({"amount": 0.1})
    canonical, digest = evidence.product_evidence_item_payload_hash(first)
    assert contract.stored_json_hash(canonical) == digest
    assert contract.stored_json_hash(canonical.replace(":", ": ", 1)) is None


def test_contract_codes_are_catalogued_with_german_message_and_ui_mapping():
    from pathlib import Path

    codes = set(contract.MESSAGES)
    assert codes == {
        "PRODUCT_EVIDENCE_MISSING", "PRODUCT_EVIDENCE_STALE", "PRODUCT_EVIDENCE_CONFLICT",
        "PRODUCT_EVIDENCE_REVOKED", "PRODUCT_EVIDENCE_HASH_MISMATCH", "PRODUCT_EVIDENCE_SHARE_CLASS_MISMATCH",
        "PRODUCT_EVIDENCE_KID_MISSING", "PRODUCT_EVIDENCE_COST_MISSING", "PRODUCT_EVIDENCE_RETROCESSION_MISSING",
        "PRODUCT_EVIDENCE_SUITABILITY_MISSING",
    }
    catalog = {member.value for member in ReasonCode if member.value.startswith("PRODUCT_EVIDENCE_")}
    assert codes <= catalog
    ui = (Path(__file__).resolve().parents[2] / "ares-desktop" / "frontend" / "product-evidence.js").read_text("utf-8")
    assert all(f"{code}:" in ui for code in catalog), [c for c in catalog if f"{c}:" not in ui]
    assert set(contract.KIND_LABELS) >= set(contract.PRODUCT_EVIDENCE_KINDS)


# -- Identitaet (Befund 01, Regressionen 7 und 8) ----------------------------


@pytest.mark.parametrize("product_sc,item_sc,verified", [
    (None, None, True), (None, "SC-A", False), ("SC-A", None, False), ("SC-A", "SC-B", False), ("SC-A", "SC-A", True),
])
def test_share_class_binding_is_exact_and_symmetric(db, product_sc, item_sc, verified):
    product = _product(share_class_figi=product_sc)
    db.add(product)
    for kind in contract.PRODUCT_EVIDENCE_KINDS:
        _raw_item(db, product, kind, share_class_id=item_sc)
    result = evidence.evaluate_product_evidence(db, _mandate_view(), product)
    if verified:
        assert result["status"] == "verified"
    else:
        assert result["status"] == "conflict"
        assert _codes(result) == {"PRODUCT_EVIDENCE_SHARE_CLASS_MISMATCH"}
    # Erfassung prueft dieselbe Identitaet.
    create = lambda: evidence.create_product_evidence_draft(  # noqa: E731
        db, product, values=synthetic_values(product, "kid", share_class_id=item_sc), tenant_id=TENANT,
        actor_id="creator")
    if verified:
        assert create().share_class_id == product_sc
    else:
        assert _code(create) == "PRODUCT_EVIDENCE_SHARE_CLASS_MISMATCH"
    # Snapshot-Pfad ebenso.
    run, mandate = _run(db, product)
    bind = lambda: evidence.snapshot_run_product_evidence(db, mandate, run)  # noqa: E731
    if verified:
        assert bind().status == "verified"
    else:
        assert _code(bind) == "PRODUCT_EVIDENCE_SHARE_CLASS_MISMATCH"


def test_share_class_change_after_binding_blocks_and_evidence_never_jumps_between_classes(db):
    a, b = _product("p-a", isin="SYNTH0000001", share_class_figi="SC-A"), _product(
        "p-b", isin="SYNTH0000001", share_class_figi="SC-B")
    db.add_all([a, b])
    _complete(db, a)
    assert evidence.evaluate_product_evidence(db, _mandate_view(), a)["status"] == "verified"
    assert "PRODUCT_EVIDENCE_MISSING" in _codes(evidence.evaluate_product_evidence(db, _mandate_view(), b))
    run, mandate = _run(db, a)
    evidence.snapshot_run_product_evidence(db, mandate, run)
    a.share_class_figi = "SC-B"
    db.flush()
    assert _code(lambda: evidence.assert_run_product_evidence(db, mandate, run, channel="t")) == (
        "PRODUCT_EVIDENCE_SHARE_CLASS_MISMATCH")


def test_blank_share_class_counts_as_none(db):
    product = _product(share_class_figi="  ")
    db.add(product)
    _complete(db, product)
    assert evidence.evaluate_product_evidence(db, _mandate_view(), product)["status"] == "verified"


# -- Auswertung --------------------------------------------------------------


@pytest.mark.parametrize("kind", contract.PRODUCT_EVIDENCE_KINDS)
def test_each_mandatory_kind_has_exactly_its_missing_code(db, kind):
    product = _product()
    db.add(product)
    _complete(db, product, kinds=[k for k in contract.PRODUCT_EVIDENCE_KINDS if k != kind])
    result = evidence.evaluate_product_evidence(db, _mandate_view(), product)
    assert _codes(result) == {contract.MISSING_BY_KIND.get(kind, "PRODUCT_EVIDENCE_MISSING")}
    assert result["issues"][0]["evidence_kind"] == kind


@pytest.mark.parametrize("offset_from,offset_until,expected", [
    (0, 0, "verified"), (-5, 0, "verified"), (-5, -1, "stale"), (1, None, "stale"), (0, None, "verified"),
])
def test_validity_is_inclusive_on_the_utc_day(db, offset_from, offset_until, expected):
    """Regression 3: gueltig bis einschliesslich heute, ab morgen UTC veraltet."""
    product = _product()
    db.add(product)
    until = None if offset_until is None else _today(offset_until)
    _complete(db, product, overrides={"kid": {"valid_from": _today(offset_from), "valid_until": until}})
    assert evidence.evaluate_product_evidence(db, _mandate_view(), product)["status"] == expected


def test_expiry_boundary_uses_the_utc_clock_before_and_after_midnight(db, monkeypatch):
    product = _product()
    db.add(product)
    _complete(db, product, overrides={"costs": {"valid_until": _today()}})
    run, mandate = _run(db, product)
    evidence.snapshot_run_product_evidence(db, mandate, run)

    class _Clock(datetime):
        instant = datetime.fromisoformat(_today() + "T23:59:59.999999+00:00")

        @classmethod
        def now(cls, tz=None):
            return cls.instant.astimezone(tz)

    monkeypatch.setattr(evidence, "datetime", _Clock)
    assert evidence.assert_run_product_evidence(db, mandate, run, channel="t")
    _Clock.instant = datetime.fromisoformat(_today(1) + "T00:00:00+00:00")
    assert _code(lambda: evidence.assert_run_product_evidence(db, mandate, run, channel="t")) == (
        "PRODUCT_EVIDENCE_STALE")
    # Lokale Zeit Zuerich (schon naechster Tag) aendert nichts: massgeblich ist UTC.
    _Clock.instant = datetime.fromisoformat(_today(1) + "T00:30:00+02:00")
    assert evidence.assert_run_product_evidence(db, mandate, run, channel="t")


def test_tenant_overlay_precedence_and_foreign_tenant_isolation(db):
    product = _product()
    db.add(product)
    for kind in contract.PRODUCT_EVIDENCE_KINDS:
        _raw_item(db, product, kind, item_id=f"g-{kind}", tenant_id=None)
        _raw_item(db, product, kind, item_id=f"o-{kind}", tenant_id=OTHER)
    result = evidence.evaluate_product_evidence(db, _mandate_view(), product)
    assert {row.id for row in result["items"]} == {f"g-{k}" for k in contract.PRODUCT_EVIDENCE_KINDS}
    _raw_item(db, product, "kid", item_id="t-draft", status="draft")
    assert evidence.evaluate_product_evidence(db, _mandate_view(), product)["status"] == "verified"
    run, mandate = _run(db, product)
    evidence.snapshot_run_product_evidence(db, mandate, run)
    overlay = _raw_item(db, product, "kid", item_id="t-kid")
    result = evidence.evaluate_product_evidence(db, _mandate_view(), product)
    assert "t-kid" in {row.id for row in result["items"]} and "g-kid" not in {row.id for row in result["items"]}
    # Neuer Tenant-Vorrang = anderer Satz: gebundener Lauf ist veraltet.
    assert _code(lambda: evidence.assert_run_product_evidence(db, mandate, run, channel="t")) == (
        "PRODUCT_EVIDENCE_STALE")
    # Widerrufener Tenant-Nachweis faellt nie still auf den Plattform-Nachweis zurueck.
    _revoke(db, overlay)
    assert _codes(evidence.evaluate_product_evidence(db, _mandate_view(), product)) == {"PRODUCT_EVIDENCE_REVOKED"}
    # Fremder Tenant ohne Plattform-Nachweis: nichts sichtbar.
    private = _product("p-2")
    db.add(private)
    _complete(db, private, tenant_id=OTHER)
    assert "PRODUCT_EVIDENCE_MISSING" in _codes(evidence.evaluate_product_evidence(db, _mandate_view(), private))


def test_two_effective_items_of_one_line_are_a_conflict(db):
    product = _product()
    db.add(product)
    _complete(db, product)
    _raw_item(db, product, "kid", as_of=_today(-1), valid_from=_today(-1))
    assert _codes(evidence.evaluate_product_evidence(db, _mandate_view(), product)) == {"PRODUCT_EVIDENCE_CONFLICT"}


def test_jurisdiction_is_part_of_the_line(db):
    product = _product()
    db.add(product)
    _complete(db, product, jurisdiction="DE")
    assert "PRODUCT_EVIDENCE_MISSING" in _codes(evidence.evaluate_product_evidence(db, _mandate_view(), product))
    assert evidence.evaluate_product_evidence(db, _mandate_view(jurisdiction="DE"), product)["status"] == "verified"


# -- Kosten/Retrozession (Regressionen 9 und 10) -----------------------------


@pytest.mark.parametrize("payload,status", [
    ({"value": 0}, "known"), ({"value": 25}, "known"), ({"value": None}, "missing"), ({}, "missing"),
    ({"status": "not_applicable"}, "not_applicable"), ({"status": "not_applicable", "value": 0}, "missing"),
    ({"value": True}, "missing"), ({"value": "25"}, "missing"), ({"value": -1}, "missing"),
])
def test_null_missing_not_applicable_and_zero_are_distinct(payload, status):
    assert contract.rate_terms(payload)[0] == status
    assert (contract.payload_defect_code("costs", payload, "Quelle") is None) is (status != "missing")


@pytest.mark.parametrize("kind", contract.RATE_KINDS)
def test_rate_evidence_without_value_or_source_is_rejected_on_create_and_evaluate(db, kind):
    product = _product()
    db.add(product)
    expected = contract.MISSING_BY_KIND[kind]
    for over in ({"payload": {"value": None}}, {"payload": {"status": "not_applicable"}, "source_reference": "  "}):
        assert _code(lambda: evidence.create_product_evidence_draft(
            db, product, values=synthetic_values(product, kind, **over), tenant_id=TENANT, actor_id="creator",
        )) == expected
    _complete(db, product, kinds=[k for k in contract.PRODUCT_EVIDENCE_KINDS if k != kind])
    _raw_item(db, product, kind, payload={"status": "not_applicable"}, source_reference=" ")
    assert _codes(evidence.evaluate_product_evidence(db, _mandate_view(), product)) == {expected}


def test_unknown_ter_never_wins_and_master_data_is_not_the_cost_source(db):
    """Regression 9: belegte TER schlaegt NULL; Mutation ``or 0`` waere rot."""
    from services.portfolio_engine_payload import _product_selection_key, _ranking_ter
    from services.portfolio_engine import _normalize_preferences

    known, unknown = _product("p-known", ter_bps=90), _product("p-null", ter_bps=None)
    stale_master = _product("p-master", ter_bps=1)
    db.add_all([known, unknown, stale_master])
    _complete(db, known)
    _complete(db, unknown)
    _complete(db, stale_master, overrides={"costs": {"payload": {"value": 300}}})
    context = evidence.ProductEvidenceContext(db, _mandate_view(), [known, unknown, stale_master])
    assert _ranking_ter(unknown, context) == ("missing", None)
    assert _ranking_ter(stale_master, context) == ("known", 300)
    prefs = _normalize_preferences(None)
    order = sorted([unknown, stale_master, known], key=lambda p: _product_selection_key(
        p, "Aktien Schweiz", prefs, evidence=context))
    assert [p.id for p in order] == ["p-known", "p-master", "p-null"]
    run, _mandate = _run(db, known, run_id="run-legacy")
    terms = contract.bound_rate_terms(evidence._evidence_query(db), run.id, today=_today())
    assert contract.bound_term(terms, known.id, "costs") == ("missing", None)  # ungebunden -> unbekannt


def test_portfolio_weighted_ter_never_counts_unknown_as_zero():
    from services.portfolio_engine_cma import _portfolio_weighted_ter_bps

    items = [{"target_weight_bps": 5000, "ter_bps": 40}, {"target_weight_bps": 5000, "ter_bps": None}]
    assert _portfolio_weighted_ter_bps(None, items) == 40
    items[1]["ter_status"] = "not_applicable"
    assert _portfolio_weighted_ter_bps(None, items) == 20


# -- Snapshot, Revalidierung, Rennen (Befund 02, Regressionen 4, 5, 11, 12) ---


def test_complete_evidence_binds_sorted_set_and_replacement_is_always_stale(db):
    product = _product()
    db.add(product)
    rows = _complete(db, product)
    run, mandate = _run(db, product)
    snapshot = evidence.snapshot_run_product_evidence(db, mandate, run)
    payload = json.loads(snapshot.canonical_payload_json)
    assert payload["items"] == sorted(payload["items"], key=contract.item_sort_key)
    assert run.product_evidence_hash == snapshot.product_evidence_hash
    assert evidence.assert_run_product_evidence(db, mandate, run, channel="t").id == snapshot.id
    values = evidence.run_product_evidence_values(db, mandate, run, channel="t")
    assert values[product.id]["costs"]["payload"]["value"] == 25
    # Regression 6: unverbundene Entwurfsnotiz ist irrelevant.
    draft = _raw_item(db, product, "costs", status="draft")
    draft.note = "Nur interne Notiz"
    product.notes = "irrelevant" if hasattr(product, "notes") else None
    db.flush()
    evidence.assert_run_product_evidence(db, mandate, run, channel="t")
    # Regression 5: inhaltsgleicher Ersatz hat eine neue Lebenszyklusidentitaet.
    costs = next(row for row in rows if row.evidence_kind == "costs")
    successor = evidence.create_product_evidence_draft(
        db, product, values=synthetic_values(product, "costs", supersedes_id=costs.id), tenant_id=TENANT,
        actor_id="creator")
    db.flush()
    assert successor.canonical_payload_hash == costs.canonical_payload_hash
    evidence.approve_product_evidence_items(
        db, product, seen=[(successor.id, successor.canonical_payload_hash)], tenant_id=TENANT, actor_id="approver",
        is_same_person=lambda c: c == "approver", approver_ids=[], attestation=None, min_attestation_length=1)
    assert (costs.status, costs.reason_code) == ("retired", "PRODUCT_EVIDENCE_SUPERSEDED")
    assert _code(lambda: evidence.assert_run_product_evidence(db, mandate, run, channel="t")) == (
        "PRODUCT_EVIDENCE_STALE")
    assert _code(lambda: evidence.bind_run_product_evidence(db, mandate, run, channel="finalize")) == (
        "PRODUCT_EVIDENCE_STALE")


def test_manual_position_rebinds_but_never_reseals_a_changed_bound_item(db):
    a, b = _product("p-a"), _product("p-b")
    db.add_all([a, b])
    rows = _complete(db, a)
    _complete(db, b)
    run, mandate = _run(db, a)
    first = evidence.snapshot_run_product_evidence(db, mandate, run)
    _position(db, run, b)
    assert _code(lambda: evidence.assert_run_product_evidence(db, mandate, run, channel="t")) == (
        "PRODUCT_EVIDENCE_STALE")
    second = evidence.bind_run_product_evidence(db, mandate, run, channel="finalize")
    assert second.id != first.id and json.loads(second.product_ids_json) == ["p-a", "p-b"]
    _position(db, run, _add_third(db))
    kid = next(row for row in rows if row.evidence_kind == "kid")
    successor = evidence.create_product_evidence_draft(
        db, a, values=synthetic_values(a, "kid", supersedes_id=kid.id), tenant_id=TENANT, actor_id="creator")
    db.flush()
    evidence.approve_product_evidence_items(
        db, a, seen=[(successor.id, successor.canonical_payload_hash)], tenant_id=TENANT, actor_id="approver",
        is_same_person=lambda c: c == "approver", approver_ids=[], attestation=None, min_attestation_length=1)
    assert _code(lambda: evidence.bind_run_product_evidence(db, mandate, run, channel="finalize")) == (
        "PRODUCT_EVIDENCE_STALE")


def _add_third(db):
    product = _product("p-c")
    db.add(product)
    _complete(db, product)
    return product


@pytest.mark.parametrize("change,expected", [
    ("revoke", "PRODUCT_EVIDENCE_REVOKED"), ("replace", "PRODUCT_EVIDENCE_STALE"),
    ("overlay", "PRODUCT_EVIDENCE_STALE"), ("conflict", "PRODUCT_EVIDENCE_CONFLICT"),
])
def test_change_between_evaluation_and_snapshot_leaves_no_row(db, monkeypatch, change, expected):
    """Regression 12: zweite Pruefung unter Sperre; nichts bleibt zurueck."""
    product = _product()
    db.add(product)
    rows = _complete(db, product, tenant_id=TENANT)
    if change == "overlay":
        rows = []
        db.execute(text("DROP TRIGGER trg_product_evidence_immutable_delete"))
        db.execute(text("DELETE FROM product_evidence_items"))
        db.expire_all()
        for kind in contract.PRODUCT_EVIDENCE_KINDS:
            _raw_item(db, product, kind, tenant_id=None)
    db.commit()
    run, mandate = _run(db, product)
    original = evidence.evaluate_product_evidence
    raced = []

    def racing(session, current_mandate, current_product, **kw):
        result = original(session, current_mandate, current_product, **kw)
        if not raced:
            raced.append(True)
            kid = next((r for r in rows if r.evidence_kind == "kid"), None)
            if change == "revoke":
                _revoke(session, kid)
            elif change == "overlay":
                _raw_item(session, product, "kid")
            elif change == "conflict":
                _raw_item(session, product, "kid", as_of=_today(-1), valid_from=_today(-1))
            else:
                evidence._close_evidence(kid, "retired", "approver", _now(), reason_code="PRODUCT_EVIDENCE_SUPERSEDED")
                session.flush()
                _raw_item(session, product, "kid")
        return result

    monkeypatch.setattr(evidence, "evaluate_product_evidence", racing)
    assert _code(lambda: evidence.snapshot_run_product_evidence(db, mandate, run)) == expected
    assert db.query(ProductEvidenceSnapshot).count() == 0
    assert run.product_evidence_snapshot_id is None and run.product_evidence_status is None
    db.rollback()
    assert db.query(RecommendationRun).count() == 0 and db.query(RecommendationPosition).count() == 0


def test_sqlite_revocation_from_another_connection_waits_until_snapshot_commit(engine, db):
    """SQLite-Schreibtransaktion: zwischen Revalidierung und Commit kann keine
    zweite Verbindung widerrufen; danach ist der Lauf sofort veraltet."""
    product = _product()
    db.add(product)
    rows = _complete(db, product)
    kid = next(row.id for row in rows if row.evidence_kind == "kid")
    db.commit()
    evidence.lock_product_evidence(db, _mandate_view(), [product.id])  # allein die Sperre, ohne Vorschreiben
    other = sqlite3.connect(engine.url.database, timeout=0.2)
    sql = ("UPDATE product_evidence_items SET status='revoked', retired_or_revoked_by='x', "
           "retired_or_revoked_at='2026-01-01', reason_code='RACE' WHERE id = ?")
    with pytest.raises(sqlite3.OperationalError, match="locked"):
        other.execute(sql, (kid,))
    run, mandate = _run(db, product)
    evidence.snapshot_run_product_evidence(db, mandate, run)
    db.commit()
    other.execute(sql, (kid,))
    other.commit()
    other.close()
    db.expire_all()
    assert _code(lambda: evidence.assert_run_product_evidence(db, mandate, run, channel="t")) == (
        "PRODUCT_EVIDENCE_REVOKED")


def test_tampered_payload_or_hash_blocks_without_reseal(db):
    """Regression 11."""
    product = _product()
    db.add(product)
    rows = _complete(db, product)
    run, mandate = _run(db, product)
    snapshot = evidence.snapshot_run_product_evidence(db, mandate, run)
    db.commit()
    rows[0].canonical_payload_hash = "0" * 64
    with pytest.raises(DatabaseError, match="unveränderlich"):
        db.flush()
    db.rollback()
    snapshot.status = "stale"
    with pytest.raises(DatabaseError, match="unveränderlich"):
        db.flush()
    db.rollback()
    with pytest.raises(DatabaseError, match="unveränderlich"):
        db.execute(text("DELETE FROM product_evidence_snapshots"))
    db.rollback()
    # Angreifer mit DB-Zugriff: Trigger umgangen, Inhalt veraendert.
    db.execute(text("DROP TRIGGER trg_product_evidence_immutable_update"))
    db.execute(text("UPDATE product_evidence_items SET canonical_payload_json = replace("
                    "canonical_payload_json, '25', '5') WHERE evidence_kind = 'costs'"))
    db.commit()
    db.expire_all()
    for call in (
        lambda: evidence.assert_run_product_evidence(db, mandate, run, channel="t"),
        lambda: evidence.bind_run_product_evidence(db, mandate, run, channel="finalize"),
        lambda: evidence.snapshot_run_product_evidence(db, mandate, run),
    ):
        assert _code(call) == "PRODUCT_EVIDENCE_HASH_MISMATCH"
    assert db.query(ProductEvidenceSnapshot).count() == 1


@pytest.mark.parametrize("statement", [
    "UPDATE recommendation_runs SET product_evidence_hash = '" + "0" * 64 + "'",
    "UPDATE recommendation_runs SET mandate_id = 'mandate-2'",
    "UPDATE product_evidence_snapshots SET item_ids_json = '[]'",
    "UPDATE product_evidence_snapshots SET canonical_payload_json = '{}'",
])
def test_snapshot_binding_mismatch_is_a_hash_mismatch(db, statement):
    product = _product()
    db.add(product)
    _complete(db, product)
    run, mandate = _run(db, product)
    evidence.snapshot_run_product_evidence(db, mandate, run)
    db.execute(text("DROP TRIGGER trg_product_evidence_snapshot_immutable_update"))
    db.execute(text("INSERT INTO mandates SELECT * FROM mandates WHERE 0"))
    if "mandate-2" in statement:
        columns = [c["name"] for c in inspect(db.get_bind()).get_columns("mandates")]
        picked = ", ".join("'mandate-2'" if c == "id" else (
            "'other-number'" if c == "mandate_number" else c) for c in columns)
        db.execute(text(f"INSERT INTO mandates ({', '.join(columns)}) SELECT {picked} FROM mandates"))
    db.execute(text(statement))
    db.expire_all()
    defect, _payload, _items = contract.run_evidence_state(evidence._evidence_query(db), run.id, today=_today())
    assert defect.code == "PRODUCT_EVIDENCE_HASH_MISMATCH"


def test_empty_run_is_never_verified(db):
    run, mandate = _run(db)
    assert _code(lambda: evidence.snapshot_run_product_evidence(db, mandate, run)) == "PRODUCT_EVIDENCE_MISSING"


# -- Generate/manuelle Position (Regressionen 1 und 2) -----------------------


def _counts(SF):  # noqa: F811
    with SF() as db:
        return {model.__tablename__: db.query(model).count() for model in (
            RecommendationRun, RecommendationPosition, ProductEvidenceSnapshot)}


def test_generate_without_evidence_persists_nothing_and_with_evidence_binds(SF):  # noqa: F811
    from routers.review import generate_recommendation_run_endpoint
    from models.users import User
    from schemas.review import RecommendationGenerateRequest
    from tests.sustainability_test_support import answer_question_one_for_all_mandates
    from tests.test_finalize_mandate_lock import _FakeRequest

    advisor_id, mandate_id = _seed(SF, "c02-generate")
    _generate_ta(SF, mandate_id, advisor_id, {})
    with SF() as db:
        answer_question_one_for_all_mandates(db)
        db.commit()
    before = _counts(SF)

    def generate():
        with SF() as db:
            return generate_recommendation_run_endpoint(
                mandate_id=mandate_id, body=RecommendationGenerateRequest(), request=_FakeRequest(), db=db,
                current_user=db.get(User, advisor_id))

    with pytest.raises(DomainError) as exc:
        generate()
    assert exc.value.reason_code == "PRODUCT_EVIDENCE_MISSING" and exc.value.http_status == 409
    assert set(exc.value.extra) == {"channel", "product_id", "evidence_kind"}
    assert _counts(SF) == before
    with SF() as db:
        audit = db.execute(text(
            "SELECT new_value, mandate_id FROM audit_log WHERE field_name = 'product_evidence_blocked'")).all()
        assert len(audit) == 1 and audit[0][1] == mandate_id
        assert json.loads(audit[0][0])["channel"] == "recommendation_generate"
        mandate = db.get(Mandate, mandate_id)
        tenant = evidence.mandate_tenant_id(mandate)
        add_synthetic_product_evidence(db, db.query(Product).filter(Product.tenant_id.is_(None)).all(),
                                       actor_id=advisor_id, tenant_id=tenant)
        db.commit()
    result = generate()
    with SF() as db:
        run = db.get(RecommendationRun, result["run"].id)
        snapshot = db.get(ProductEvidenceSnapshot, run.product_evidence_snapshot_id)
        assert run.product_evidence_status == "verified"
        assert json.loads(snapshot.product_ids_json) == sorted(p["product_id"] for p in result["positions"])
        assert all(p["ter_status"] != "missing" for p in result["positions"])


def test_engine_prefers_an_evidenced_candidate_but_never_relaxes_the_gate(SF):  # noqa: F811
    advisor_id, mandate_id = _seed(SF, "c02-prefer")
    _generate_ta(SF, mandate_id, advisor_id, {})
    with SF() as db:
        mandate = db.get(Mandate, mandate_id)
        products = db.query(Product).filter(Product.tenant_id.is_(None)).all()
        subs = {}
        for product in sorted(products, key=lambda p: p.id):
            subs.setdefault(product.sub_asset_class, []).append(product)
        evidenced = [group[-1] for group in subs.values()]  # je Subklasse genau eines
        add_synthetic_product_evidence(db, evidenced, actor_id=advisor_id,
                                       tenant_id=evidence.mandate_tenant_id(mandate))
        db.commit()
        result = portfolio_engine.generate_recommendation_run(db, mandate, advisor_id, None)
        assert {p["product_id"] for p in result["positions"]} <= {p.id for p in evidenced}


def test_manual_position_is_blocked_then_bound(SF):  # noqa: F811
    advisor_id, mandate_id = _seed(SF, "c02-manual")
    _generate_ta(SF, mandate_id, advisor_id, {})
    run_id = _draft_run(SF, mandate_id, advisor_id)
    product_id = _add_product(SF, product_name="Synthetisches Produkt", ter_bps=20)
    with pytest.raises(DomainError) as exc:
        _add_position(SF, mandate_id, run_id, advisor_id, product_id, weight=5000)
    assert exc.value.reason_code == "PRODUCT_EVIDENCE_MISSING"
    assert _positions_of(SF, run_id) == []
    with SF() as db:
        add_synthetic_product_evidence(db, [db.get(Product, product_id)], actor_id=advisor_id,
                                       tenant_id=evidence.mandate_tenant_id(db.get(Mandate, mandate_id)))
        db.commit()
    _add_position(SF, mandate_id, run_id, advisor_id, product_id, weight=5000)
    with SF() as db:
        run = db.get(RecommendationRun, run_id)
        assert evidence.assert_run_product_evidence(db, db.get(Mandate, mandate_id), run, channel="t")


def test_assert_product_evidenced_is_the_public_gate_for_general_evidence(db):
    product = _product()
    db.add(product)
    _run(db)
    mandate = db.get(Mandate, "mandate-1")
    assert _code(lambda: evidence.assert_product_evidenced(db, mandate, product)) == "PRODUCT_EVIDENCE_MISSING"
    _complete(db, product)
    evidence.assert_product_evidenced(db, mandate, product)


def test_mutation_bypassing_the_generate_gate_is_detected(SF, monkeypatch):  # noqa: F811
    """Negativkontrolle: ohne Gate wuerde der Lauf gespeichert -- die Sperre
    oben kommt also aus diesem Aufruf und nicht aus einer anderen Regel."""
    advisor_id, mandate_id = _seed(SF, "c02-mutation")
    _generate_ta(SF, mandate_id, advisor_id, {})
    monkeypatch.setattr(evidence, "snapshot_run_product_evidence", lambda *a, **kw: None)
    with SF() as db:
        before = db.query(RecommendationRun).count()
        portfolio_engine.generate_recommendation_run(db, db.get(Mandate, mandate_id), advisor_id, None)
        assert db.query(RecommendationRun).count() == before + 1


# -- Pflege- und Freigabeweg -------------------------------------------------


def _draft(db, product, kind="kid", **over):
    row = evidence.create_product_evidence_draft(
        db, product, values=synthetic_values(product, kind, **over), tenant_id=TENANT, actor_id="creator")
    db.flush()
    return row


def _approve(db, product, rows, *, actor="approver", seen=None, approvers=(), attestation=None, same=None):
    return evidence.approve_product_evidence_items(
        db, product, seen=seen or [(r.id, r.canonical_payload_hash) for r in rows], tenant_id=TENANT, actor_id=actor,
        is_same_person=same or (lambda creator: creator == actor), approver_ids=list(approvers),
        attestation=attestation, min_attestation_length=20)


def test_four_eyes_seen_hash_and_single_approver_attestation(db):
    product = _product()
    db.add(product)
    row = _draft(db, product)
    assert _code(lambda: _approve(db, product, [row], seen=[(row.id, "0" * 64)])) == "PRODUCT_EVIDENCE_HASH_MISMATCH"
    assert _code(lambda: _approve(db, product, [row], actor="creator")) == "PRODUCT_EVIDENCE_FOUR_EYES_REQUIRED"
    # Alias-Postfach: andere ID, gleiche Person.
    assert _code(lambda: _approve(db, product, [row], same=lambda _c: True, approvers=["approver", "x"])) == (
        "PRODUCT_EVIDENCE_FOUR_EYES_REQUIRED")
    assert _code(lambda: _approve(db, product, [row], actor="creator", approvers=["creator"], attestation="kurz")) == (
        "PRODUCT_EVIDENCE_FOUR_EYES_REQUIRED")
    db.rollback()
    db.add(product)
    row = _draft(db, product)
    approved, = _approve(db, product, [row], actor="creator", approvers=["creator"],
                         attestation="Dokumentierte Ein-Personen-Ausnahme Tier 1")
    assert (approved.status, approved.approval_mode) == ("approved", "single_approver_attested")
    assert _code(lambda: _approve(db, product, [row])) == "PRODUCT_EVIDENCE_STATE_INVALID"


def test_approval_is_all_or_nothing_and_rejects_overlap_and_foreign_rows(db):
    product, other = _product(), _product("p-2")
    db.add_all([product, other])
    good, foreign = _draft(db, product), _draft(db, other)
    db.commit()
    assert _code(lambda: _approve(db, product, [good, foreign])) == "PRODUCT_EVIDENCE_STATE_INVALID"
    db.rollback()
    assert db.get(ProductEvidenceItem, good.id).status == "draft"
    _approve(db, product, [db.get(ProductEvidenceItem, good.id)])
    second = _draft(db, product, as_of=_today(-1), valid_from=_today(-1))
    assert _code(lambda: _approve(db, product, [second])) == "PRODUCT_EVIDENCE_CONFLICT"


def test_identity_change_between_draft_and_approval_is_rejected(db):
    product = _product()
    db.add(product)
    row = _draft(db, product)
    product.isin = "SYNTH0000009"
    db.flush()
    assert _code(lambda: _approve(db, product, [row])) == "PRODUCT_EVIDENCE_SHARE_CLASS_MISMATCH"


def test_only_approved_items_can_be_closed(db):
    product = _product()
    db.add(product)
    row = _draft(db, product)
    db.commit()
    assert _code(lambda: _revoke(db, row)) == "PRODUCT_EVIDENCE_STATE_INVALID"


def test_synthetic_evidence_never_counts_in_production(db, monkeypatch):
    """Regression 15: allein ``production_mode`` entscheidet (app_env=production
    oder gepackte EXE); Vorgabe des Blatts ist NEIN."""
    import sys

    from config import settings

    product = _product()
    db.add(product)
    _complete(db, product)
    run, mandate = _run(db, product)
    evidence.snapshot_run_product_evidence(db, mandate, run)
    assert evidence.evaluate_product_evidence(db, _mandate_view(), product)["status"] == "verified"
    for activate in (
        lambda m: m.setattr(settings, "app_env", "production"), lambda m: m.setattr(sys, "frozen", True, raising=False),
    ):
        with monkeypatch.context() as m:
            activate(m)
            assert settings.production_mode
            assert "PRODUCT_EVIDENCE_MISSING" in _codes(evidence.evaluate_product_evidence(db, _mandate_view(), product))
            assert _code(lambda: evidence.assert_run_product_evidence(db, mandate, run, channel="t")).startswith(
                "PRODUCT_EVIDENCE_")
            assert _code(lambda: _draft(db, product, as_of=_today(-3))) == "PRODUCT_EVIDENCE_STATE_INVALID"
            assert evidence.ensure_demo_product_evidence(
                db, _mandate_view(), [product], actor_id="creator", make_approver=lambda: 1 / 0) == 0
    previous = contract.configure_synthetic_evidence(None)
    try:
        assert contract.synthetic_evidence_allowed() is False
    finally:
        contract.configure_synthetic_evidence(previous)
    # Positivkontrolle: nicht synthetische Quelle zaehlt auch in Produktion.
    real = _product("p-real")
    db.add(real)
    with monkeypatch.context() as m:
        m.setattr(settings, "app_env", "production")
        for kind in contract.PRODUCT_EVIDENCE_KINDS:
            _raw_item(db, real, kind, source_type="issuer_document")
        assert evidence.evaluate_product_evidence(db, _mandate_view(), real)["status"] == "verified"


def test_product_code_never_imports_the_test_support():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    hits = [str(p) for folder in ("services", "routers", "core", "models", "schemas") for p in (
        root / folder).rglob("*.py") if "product_evidence_test_support" in p.read_text("utf-8")]
    assert hits == []


# -- API ---------------------------------------------------------------------


def test_request_schemas_reject_bad_hash_dates_timezone_and_free_text_reason():
    from schemas.review import (
        ProductEvidenceApprovalRequest, ProductEvidenceItemCreate, ProductEvidenceLifecycleRequest,
    )

    body = {
        "stable_instrument_id": "x", "jurisdiction": "CH", "evidence_kind": "kid", "source_type": "issuer_document",
        "source_reference": "ref", "source_document_title": "t", "retrieved_at": "2026-01-01T00:00:00Z",
        "source_document_sha256": "a" * 64, "payload": {}, "as_of": "2026-01-01", "valid_from": "2026-01-01",
    }
    assert ProductEvidenceItemCreate(**body)
    for bad in ({"source_document_sha256": "g" * 64}, {"source_document_sha256": "a" * 63},
                {"valid_until": "2025-12-31"}, {"retrieved_at": "2026-01-01T00:00:00"}, {"evidence_kind": "x"},
                {"source_reference": "  "}, {"jurisdiction": "ch"}):
        with pytest.raises(ValidationError):
            ProductEvidenceItemCreate(**{**body, **bad})
    with pytest.raises(ValidationError):
        ProductEvidenceApprovalRequest(items=[])
    with pytest.raises(ValidationError):
        ProductEvidenceLifecycleRequest(reason_code="freier Text über Kunden")


def test_compliance_reviewer_may_only_read_and_approve_product_evidence():
    from services.auth import compliance_reviewer_may_call, readonly_may_call

    assert compliance_reviewer_may_call("GET", "/products/evidence/overview")
    assert compliance_reviewer_may_call("GET", "/products/p1/evidence")
    assert compliance_reviewer_may_call("POST", "/products/p1/evidence/approve")
    for method, path in (("POST", "/products/p1/evidence"), ("POST", "/products/evidence/e1/revoke"),
                         ("POST", "/products/evidence/e1/retire"), ("GET", "/products")):
        assert not compliance_reviewer_may_call(method, path)
    assert not readonly_may_call("POST", "/products/p1/evidence/approve")


# -- Datenbankregeln und Migration -------------------------------------------


@pytest.mark.parametrize("over", [
    {"status": "unknown"}, {"evidence_kind": "unknown"}, {"valid_until": "2000-01-01"},
    {"source_document_sha256": "Z" * 64}, {"canonical_payload_hash": "ab"}, {"approved_by": None},
    {"approved_at": None}, {"approval_mode": None}, {"approval_mode": "self"}, {"approved_by": "creator"},
    {"status": "revoked"}, {"status": "retired", "retired_or_revoked_by": "x", "retired_or_revoked_at": "t"},
])
def test_database_checks_reject_invalid_items(db, over):
    product = _product()
    db.add(product)
    db.flush()
    with pytest.raises(IntegrityError):
        _raw_item(db, product, **over)


def test_database_enforces_one_active_line_tenant_scope_and_immutability(db):
    product, private = _product(), _product("p-priv", tenant_id=OTHER)
    db.add_all([product, private])
    _raw_item(db, product)
    db.commit()
    with pytest.raises(IntegrityError):
        _raw_item(db, product)  # gleiche Linie (share_class NULL) und gleicher Stichtag
    db.rollback()
    for tenant in (TENANT, None):
        with pytest.raises(IntegrityError, match="verschiedenen Tenants"):
            _raw_item(db, db.get(Product, "p-priv"), tenant_id=tenant)
        db.rollback()
    with pytest.raises(DatabaseError, match="unveränderlich"):
        db.execute(text("DELETE FROM product_evidence_items"))
    db.rollback()
    row = db.query(ProductEvidenceItem).one()
    row.note = "geändert"
    with pytest.raises(DatabaseError, match="unveränderlich"):
        db.flush()
    db.rollback()
    _revoke(db, db.query(ProductEvidenceItem).one())
    db.commit()
    with pytest.raises(DatabaseError, match="unveränderlich"):
        db.execute(text("UPDATE product_evidence_items SET status = 'approved'"))
    db.rollback()
    draft = _raw_item(db, db.get(Product, "p-1"), status="draft")
    db.delete(draft)
    db.flush()


_REVISION = "9f4c2a7e1b63"
_TABLES = ("product_evidence_items", "product_evidence_snapshots")


def test_migration_single_head_and_up_down_up(tmp_path):
    from alembic import command
    from alembic.script import ScriptDirectory

    url = f"sqlite:///{(tmp_path / 'mig.db').as_posix()}"
    cfg = _alembic_cfg(url)
    script = ScriptDirectory.from_config(cfg)
    assert len(script.get_heads()) == 1 and script.get_revision(_REVISION) is not None
    parent = script.get_revision(_REVISION).down_revision
    assert f"Revises: {parent}" in script.get_revision(_REVISION).doc or f"Revises: {parent}" in (
        script.get_revision(_REVISION).module.__doc__)

    def state():
        engine = create_engine(url)
        try:
            insp = inspect(engine)
            with engine.connect() as conn:
                triggers = sorted(r[0] for r in conn.execute(text(
                    "SELECT name FROM sqlite_master WHERE type='trigger' AND name LIKE 'trg_product_evidence%'")))
            columns = {c["name"] for c in insp.get_columns("recommendation_runs")}
            return ({t for t in _TABLES if insp.has_table(t)}, triggers,
                    {c for c in columns if c.startswith("product_evidence_")})
        finally:
            engine.dispose()

    command.upgrade(cfg, _REVISION)
    up = state()
    assert up[0] == set(_TABLES) and len(up[1]) == 6 and len(up[2]) == 3
    command.downgrade(cfg, parent)
    assert state() == (set(), [], set())
    command.upgrade(cfg, _REVISION)
    assert state() == up


def test_orm_alembic_and_raw_schema_agree(tmp_path):
    from alembic import command
    from pathlib import Path

    url = f"sqlite:///{(tmp_path / 'a.db').as_posix()}"
    command.upgrade(_alembic_cfg(url), _REVISION)
    orm = create_engine(f"sqlite:///{tmp_path / 'o.db'}")
    Base.metadata.create_all(orm)
    raw = create_engine(f"sqlite:///{tmp_path / 'r.db'}")
    sql = (Path(__file__).resolve().parents[1] / "ares_schema.sql").read_text("utf-8")
    connection = sqlite3.connect(tmp_path / "r.db")
    connection.executescript(sql)
    connection.close()

    def shape(engine):
        insp = inspect(engine)
        out = {}
        for table in _TABLES:
            out[table] = (
                {(c["name"], bool(c["nullable"]) and not c["primary_key"]) for c in insp.get_columns(table)},
                {i["name"] for i in insp.get_indexes(table) if i["name"] and not i["name"].startswith("sqlite_")},
            )
        with engine.connect() as conn:
            def rows(kind):
                return {r[0]: " ".join(str(r[1]).split()).replace("IF NOT EXISTS ", "").replace("( ", "(")
                        .replace(" )", ")").replace("', '", "','") for r in conn.execute(text(
                            f"SELECT name, sql FROM sqlite_master WHERE type='{kind}' "
                            "AND (name LIKE 'trg_product_evidence%' OR name LIKE 'ux_product_evidence_item%')"))}
            out["triggers"], out["indexes"] = rows("trigger"), rows("index")
        return out

    engines = [create_engine(url), orm, raw]
    shapes = [shape(e) for e in engines]
    assert shapes[0] == shapes[1]
    assert {t: shapes[2][t] for t in _TABLES} == {t: shapes[0][t] for t in _TABLES}
    tenant = {name for name in shapes[0]["triggers"] if "_tenant_" in name}
    assert len(tenant) == 2
    assert shapes[2]["triggers"] == {k: v for k, v in shapes[0]["triggers"].items() if k not in tenant}
    # Laufzeit-Patch: Rohschema + products.tenant_id -> dieselben Trigger.
    from database import ensure_product_evidence_tenant_triggers

    ensure_product_evidence_tenant_triggers(raw)  # ohne products.tenant_id: wirkungslos
    assert shape(raw)["triggers"] == shapes[2]["triggers"]
    with raw.begin() as conn:
        conn.execute(text("ALTER TABLE products ADD COLUMN tenant_id TEXT"))
    ensure_product_evidence_tenant_triggers(raw)
    ensure_product_evidence_tenant_triggers(raw)
    assert shape(raw)["triggers"] == shapes[0]["triggers"]
    for engine in engines:
        engine.dispose()


def test_postgres_migration_sql_has_rls_append_only_and_tenant_guard():
    from alembic import command

    buffer = io.StringIO()
    cfg = _alembic_cfg("postgresql://u:p@localhost/db")
    cfg.output_buffer = buffer
    from alembic.script import ScriptDirectory

    parent = ScriptDirectory.from_config(cfg).get_revision(_REVISION).down_revision
    command.upgrade(cfg, f"{parent}:{_REVISION}", sql=True)
    sql = buffer.getvalue()
    for table in _TABLES:
        assert f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY" in sql
    assert "BEFORE INSERT OR UPDATE OR DELETE ON product_evidence_items" in sql
    assert "verschiedenen Tenants" in sql
    assert "tenant_reference_update" in sql and "tenant_isolation" in sql


def test_inventories_cover_both_tables():
    from services.postgres_rls import GLOBAL_REFERENCE_TABLES, tenant_scoped_table_names
    from services.privacy_erasure_inventory import PERSONAL_DATA_INVENTORY
    from services.tenant_scope_inventory import GLOBAL_REFERENCE_TENANT_TABLES, TENANT_DIRECT_TABLES

    assert set(_TABLES) <= set(tenant_scoped_table_names())
    assert "product_evidence_items" in GLOBAL_REFERENCE_TABLES & GLOBAL_REFERENCE_TENANT_TABLES
    assert "product_evidence_snapshots" in TENANT_DIRECT_TABLES
    assert "product_evidence_snapshots" in PERSONAL_DATA_INVENTORY


def test_valid_until_is_a_date_not_a_timestamp():
    assert date.fromisoformat(evidence.evidence_today())
