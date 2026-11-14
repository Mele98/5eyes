"""CCX-P1 Snapshot und Hash -- Pflichtregressionen (Vertrag 2026-11-13 §3/§4).

Abgedeckt (CCX-02/09/10/11 des Cross-Channel-Vertrags):

* Serialisierung ``ares/advisory-envelope/1``: identische Inputs -> identischer
  Hash; ein Bit Mutation -> anderer Hash; Feldreihenfolge neutral;
  Listenreihenfolge nur gemaess Vertrag; Hash-Golden; Integer-Rohwerte, NFC,
  keine Floats/NaN, unbekannte/fehlende Felder sind Fehler; Domaenen-Trennung.
* Datenbank (SQLite, echter Finalisierungspfad): Versiegeln bei der
  Finalisierung, Supersession, versiegelte Zeile unveraenderlich,
  Parallelversiegelung -> ein Sieger, Snapshot-Fence, Mandatswechsel
  A -> B -> A ohne Leck, Tenant-IDOR, Integritaetsbrueche mit Reason-Code und
  Audit, kein Fallback.
* Migration: genau ein Head (``CCX_P1_REV`` an ``e7b3d9f1a2c4``),
  upgrade/downgrade/upgrade, ORM = Bootstrap-SQL = Laufzeitpatch = Alembic.

PostgreSQL (RLS, Trigger, echte parallele Transaktionen):
``tests/test_postgres_ccx_p1_envelopes_live.py``.
"""
from __future__ import annotations

import copy
import hashlib
import itertools
import json
import math
import sqlite3
import unicodedata
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from core.advisory_envelope_codec import (
    ENVELOPE_PAYLOAD_SCHEMA,
    CanonicalPayloadError,
    canonical_bytes,
    child_hash,
    envelope_hash,
    parse_canonical,
    root_hash,
    rows_child_hash,
)
from core.evidence import ADVISORY_ENVELOPE_DOMAIN, advisory_domain
from core.reason_codes import DomainError
from services.advisory_cache_scope import advisory_cache_key
from services.advisory_envelope_integrity import verify_root_hash
from services.advisory_snapshot_transaction import NEW, OLD, RETRY, classify_snapshot_consistency
from services.effective_input_manifest import build_effective_input_hash

CCX_P1_REV = "2c62f9012c73"
CCX_P1_PARENT = "e7b3d9f1a2c4"
BACKEND = Path(__file__).resolve().parents[1]

H_A = "a" * 64
H_B = "b" * 64


def _payload(**overrides):
    payload = {
        "schema_version": "ares/advisory-envelope/1",
        "tenant_id": "t-golden",
        "mandate_id": "m-golden",
        "locale": "DE",
        "base_currency": "CHF",
        "rounding_policy_version": "ares-rounding/1",
        "predecessor_envelope_hash": None,
        "effective_input_manifest_hash": H_A,
        "bindings": [
            {"binding_kind": "target_allocation", "ordinal": 0, "object_type": "target_allocations",
             "object_id": "ta-1", "object_version": 3, "child_hash": H_B},
            {"binding_kind": "effective_input_manifest", "ordinal": 0,
             "object_type": "advisory_effective_input_manifests", "object_id": "man-1",
             "object_version": None, "child_hash": H_A},
        ],
    }
    payload.update(overrides)
    return payload


# Von Hand geschriebene kanonische Bytes (Schema-Reihenfolge, Bindings nach
# (kind, ordinal, object_id)) -- unabhaengig vom Encoder.
GOLDEN_CANONICAL = (
    '{"schema_version":"ares/advisory-envelope/1","tenant_id":"t-golden","mandate_id":"m-golden",'
    '"locale":"DE","base_currency":"CHF","rounding_policy_version":"ares-rounding/1",'
    '"predecessor_envelope_hash":null,"effective_input_manifest_hash":"' + H_A + '",'
    '"bindings":[{"binding_kind":"effective_input_manifest","ordinal":0,'
    '"object_type":"advisory_effective_input_manifests","object_id":"man-1","object_version":null,'
    '"child_hash":"' + H_A + '"},{"binding_kind":"target_allocation","ordinal":0,'
    '"object_type":"target_allocations","object_id":"ta-1","object_version":3,'
    '"child_hash":"' + H_B + '"}]}'
)
GOLDEN_HASH = "159eaffbaa09622b17f614264ff8ad0e260399f3a640d4b8333141b7cd689a7a"


# ── Serialisierung / Hash ────────────────────────────────────────────────────


def test_hash_golden_bytes_and_digest():
    canonical, digest = envelope_hash(_payload())
    assert canonical == GOLDEN_CANONICAL
    independent = hashlib.sha256(b"Ares\x00ares/advisory-envelope/1\x00" + GOLDEN_CANONICAL.encode()).hexdigest()
    assert digest == independent
    assert digest == GOLDEN_HASH, digest
    assert ADVISORY_ENVELOPE_DOMAIN == b"Ares\x00ares/advisory-envelope/1\x00"


def test_identical_inputs_give_identical_hash():
    assert envelope_hash(_payload()) == envelope_hash(copy.deepcopy(_payload()))
    assert envelope_hash(json.loads(json.dumps(_payload()))) == envelope_hash(_payload())


def _mutations():
    yield "tenant_id", lambda p: p.update(tenant_id="t-goldeo")
    yield "mandate_id", lambda p: p.update(mandate_id="m-goldem")
    yield "locale", lambda p: p.update(locale="DF")
    yield "base_currency", lambda p: p.update(base_currency="CHG")
    yield "rounding_policy_version", lambda p: p.update(rounding_policy_version="ares-rounding/2")
    yield "predecessor", lambda p: p.update(predecessor_envelope_hash="0" * 64)
    yield "manifest_hash", lambda p: p.update(effective_input_manifest_hash="a" * 63 + "b")
    for index, field, value in (
        (0, "binding_kind", "target_allocatioo"), (0, "ordinal", 1), (0, "object_type", "target_allocationt"),
        (0, "object_id", "ta-0"), (0, "object_version", 2), (0, "child_hash", "b" * 63 + "c"),
        (1, "object_version", 0),
    ):
        yield f"binding{index}.{field}", (lambda i, f, v: lambda p: p["bindings"][i].update({f: v}))(index, field, value)
    yield "extra_binding", lambda p: p["bindings"].append({
        "binding_kind": "recommendation_run", "ordinal": 0, "object_type": "recommendation_runs",
        "object_id": "r-1", "object_version": None, "child_hash": H_B})
    yield "dropped_binding", lambda p: p["bindings"].pop()


@pytest.mark.parametrize("name,mutate", list(_mutations()), ids=[n for n, _ in _mutations()])
def test_any_field_mutation_changes_hash(name, mutate):
    payload = _payload()
    mutate(payload)
    assert envelope_hash(payload)[1] != GOLDEN_HASH


def test_one_bit_flip_in_canonical_bytes_changes_root():
    raw = bytearray(GOLDEN_CANONICAL.encode())
    seen = {root_hash(bytes(raw))}
    for position in (0, len(raw) // 2, len(raw) - 1):
        flipped = bytearray(raw)
        flipped[position] ^= 0x01
        seen.add(root_hash(bytes(flipped)))
    assert len(seen) == 4


def test_field_order_is_neutral():
    payload = _payload()
    reordered = dict(reversed(list(payload.items())))
    reordered["bindings"] = [dict(reversed(list(b.items()))) for b in payload["bindings"]]
    assert envelope_hash(reordered) == envelope_hash(payload)


def test_list_order_only_as_contract():
    payload = _payload()
    for permutation in itertools.permutations(payload["bindings"]):
        assert envelope_hash(_payload(bindings=list(permutation)))[1] == GOLDEN_HASH
    # Reihenfolge ist fachlich (kind, ordinal, object_id) -- ein anderer Ordinal
    # ist eine andere Aussage, kein Umsortieren.
    moved = _payload()
    moved["bindings"][0]["ordinal"] = 1
    assert envelope_hash(moved)[1] != GOLDEN_HASH
    rows = [{"id": "r2", "v": 2}, {"id": "r1", "v": 1}]
    assert rows_child_hash("k", ["id", "v"], rows, lambda r: (r["id"],)) == rows_child_hash(
        "k", ["id", "v"], list(reversed(rows)), lambda r: (r["id"],))


def test_duplicate_sort_key_is_rejected():
    payload = _payload()
    payload["bindings"].append(dict(payload["bindings"][0]))
    with pytest.raises(CanonicalPayloadError):
        envelope_hash(payload)


@pytest.mark.parametrize("mutate", [
    lambda p: p.update(unknown="x"),
    lambda p: p.pop("locale"),
    lambda p: p["bindings"][0].update(extra=1),
    lambda p: p["bindings"][0].pop("object_version"),
    lambda p: p.update(schema_version="ares/advisory-envelope/2"),
    lambda p: p.update(effective_input_manifest_hash="A" * 64),
    lambda p: p.update(locale=""),
])
def test_unknown_missing_or_invalid_fields_are_errors(mutate):
    payload = _payload()
    mutate(payload)
    with pytest.raises(CanonicalPayloadError):
        envelope_hash(payload)


@pytest.mark.parametrize("value", [3.0, float("nan"), float("inf"), True, Decimal("3"), "3", 2 ** 63])
def test_integer_raw_values_only(value):
    payload = _payload()
    payload["bindings"][0]["object_version"] = value
    with pytest.raises(CanonicalPayloadError):
        envelope_hash(payload)


def test_unicode_nfc_bom_and_surrogates():
    nfd = unicodedata.normalize("NFD", "Zürich")
    assert nfd != "Zürich"
    assert envelope_hash(_payload(locale=nfd)) == envelope_hash(_payload(locale="Zürich"))
    assert "Zürich" in envelope_hash(_payload(locale=nfd))[0]  # UTF-8 im Klartext, NFC
    for bad in ("﻿DE", "D\ud800E"):
        with pytest.raises(CanonicalPayloadError):
            envelope_hash(_payload(locale=bad))


def test_domain_separation():
    data = GOLDEN_CANONICAL.encode()
    root = root_hash(data)
    assert root != hashlib.sha256(data).hexdigest()
    assert root != child_hash("target-allocation", data)
    assert child_hash("goals", data) != child_hash("cashflows", data)
    assert advisory_domain("goals") == b"Ares\x00ares/advisory-envelope/1/goals\x00"
    with pytest.raises(ValueError):
        advisory_domain("a/b")


def test_stored_payload_must_be_canonical():
    assert parse_canonical(GOLDEN_CANONICAL, ENVELOPE_PAYLOAD_SCHEMA)["tenant_id"] == "t-golden"
    for bad in (GOLDEN_CANONICAL.replace('","', '", "', 1), GOLDEN_CANONICAL.replace(':3,', ':3.0,')):
        with pytest.raises(CanonicalPayloadError):
            parse_canonical(bad, ENVELOPE_PAYLOAD_SCHEMA)


def test_rounding_policy_version_is_hashed_never_rounded_text():
    canonical, _ = envelope_hash(_payload())
    assert '"rounding_policy_version":"ares-rounding/1"' in canonical
    assert "%" not in canonical and "'" not in canonical


# ── CCX-02/09/10/11 Adapter ──────────────────────────────────────────────────


def test_ccx02_every_effective_input_changes_the_manifest_hash():
    base = {name: f"{name}-v1" for name in (
        "client", "mandate", "goals", "cashflows", "risk", "preference", "cma", "policy",
        "constraints", "holdings")}
    base.update(engine_version="e1", random_stream_id="s1", rounding_policy_version="ares-rounding/1")
    reference = build_effective_input_hash(base)
    assert reference == build_effective_input_hash(copy.deepcopy(base))
    for key in base:
        assert build_effective_input_hash({**base, key: base[key] + "x"}) != reference, key
    with pytest.raises(ValueError):
        build_effective_input_hash({**base, "unknown": "x"})


def test_ccx09_child_mutation_breaks_root():
    children = {"goal": H_A, "allocation": H_B}
    from services.advisory_envelope_integrity import _children_root

    envelope = {"children": children, "root_hash": _children_root(children)}
    assert verify_root_hash(envelope) is True
    assert verify_root_hash({**envelope, "children": {**children, "goal": "c" * 64}}) is False
    row = {"canonical_payload_json": GOLDEN_CANONICAL, "envelope_hash": GOLDEN_HASH}
    assert verify_root_hash(row) is True
    assert verify_root_hash({**row, "canonical_payload_json": GOLDEN_CANONICAL.replace(H_B, "c" * 64)}) is False


def test_ccx10_cache_key_is_tenant_mandate_envelope_scoped():
    a1 = advisory_cache_key("tenant-1", "mandate-a", "hash-1")
    b = advisory_cache_key("tenant-1", "mandate-b", "hash-1")
    a2 = advisory_cache_key("tenant-1", "mandate-a", "hash-2")
    other = advisory_cache_key("tenant-2", "mandate-a", "hash-1")
    none = advisory_cache_key("tenant-1", "mandate-a", None)
    assert len({a1, b, a2, other, none}) == 5
    assert advisory_cache_key("tenant-1", "mandate-a", "hash-1") == a1  # A -> B -> A: stabil


def test_ccx11_snapshot_is_old_new_or_retry_never_mixed():
    one, two = {"goal": "1", "risk": "1"}, {"goal": "2", "risk": "2"}
    assert classify_snapshot_consistency(one, dict(one), sealed=one) == OLD
    assert classify_snapshot_consistency(two, dict(two), sealed=one) == NEW
    assert classify_snapshot_consistency(one, {"goal": "2", "risk": "1"}, sealed=one) == RETRY
    assert classify_snapshot_consistency(one, {"goal": "1"}) == RETRY
    assert classify_snapshot_consistency({"goal": None}, {"goal": None}) == RETRY  # unknown != complete


# ── Datenbank: echter Finalisierungspfad (SQLite) ────────────────────────────

from tests.sustainability_test_support import answer_question_one_for_all_mandates  # noqa: E402
from tests.test_finalize_mandate_lock import (  # noqa: E402
    _add_full_position,
    _allocation_policy_and_cma,
    _current_allocation_id,
    _FakeRequest,
    _make_run,
    _seed_realistic_mandate,
)
from tests.test_optimizer_shadow_mode import session_factory  # noqa: E402,F401


def _finalizable_run(session_factory, suffix, mandate=None):
    if mandate is None:
        advisor_id, _cid, mid, aid, _gid = _seed_realistic_mandate(session_factory, suffix=suffix)
    else:
        advisor_id, mid, aid = mandate
    alloc_id = _current_allocation_id(session_factory, mid, advisor_id)
    policy, cma = _allocation_policy_and_cma(session_factory, alloc_id)
    run_id = _make_run(session_factory, mid, alloc_id, aid, advisor_id, policy, cma)
    _add_full_position(session_factory, run_id)
    return advisor_id, mid, aid, run_id


def _finalize(session_factory, advisor_id, mid, run_id):
    from models.users import User
    from routers.review import finalize_recommendation

    with session_factory() as db:
        advisor = db.query(User).filter(User.id == advisor_id).first()
        answer_question_one_for_all_mandates(db)
        return finalize_recommendation(
            mandate_id=mid, run_id=run_id, request=_FakeRequest(), db=db, current_user=advisor,
        )


def _audit(db, field):
    return db.execute(text(
        "SELECT record_id, new_value, mandate_id, tenant_id FROM audit_log WHERE field_name = :f ORDER BY sequence"
    ), {"f": field}).all()


def test_finalize_seals_envelope_bindings_manifest_and_audit(session_factory):
    from models.snapshots import AdvisoryDecisionEnvelope, AdvisoryEffectiveInputManifest, AdvisoryEnvelopeBinding
    from services.advisory_decision_envelope import verify_envelope

    advisor_id, mid, _aid, run_id = _finalizable_run(session_factory, "seal")
    result = _finalize(session_factory, advisor_id, mid, run_id)
    with session_factory() as db:
        envelope = db.query(AdvisoryDecisionEnvelope).one()
        assert (envelope.status, envelope.optimistic_version, envelope.mandate_id) == ("SEALED", 2, mid)
        assert result.advisory_envelope_id == envelope.id
        assert result.advisory_envelope_hash == envelope.envelope_hash
        assert root_hash(envelope.canonical_payload_json.encode()) == envelope.envelope_hash
        kinds = sorted(b.binding_kind for b in db.query(AdvisoryEnvelopeBinding).all())
        assert kinds == ["effective_input_manifest", "recommendation_positions", "recommendation_run",
                         "target_allocation"]
        manifest = db.query(AdvisoryEffectiveInputManifest).one()
        assert manifest.rounding_policy_version == "ares-rounding/1"
        assert json.loads(envelope.canonical_payload_json)["effective_input_manifest_hash"] == manifest.manifest_hash
        assert verify_envelope(db, envelope) is None
        sealed = _audit(db, "ccx.envelope.sealed")
        assert len(sealed) == 1 and sealed[0].record_id == envelope.id and sealed[0].mandate_id == mid
        assert envelope.envelope_hash in sealed[0].new_value
        assert manifest.manifest_hash in sealed[0].new_value
        assert "canonical" not in sealed[0].new_value and "{" not in sealed[0].new_value  # nie Payload
        assert sealed[0].tenant_id == envelope.tenant_id


def test_refinalize_supersedes_and_chains_predecessor(session_factory):
    from models.snapshots import AdvisoryDecisionEnvelope

    advisor_id, mid, aid, run1 = _finalizable_run(session_factory, "chain")
    first = _finalize(session_factory, advisor_id, mid, run1)
    _a, _m, _x, run2 = _finalizable_run(session_factory, "chain", mandate=(advisor_id, mid, aid))
    second = _finalize(session_factory, advisor_id, mid, run2)
    with session_factory() as db:
        rows = {e.id: e for e in db.query(AdvisoryDecisionEnvelope).all()}
        old, new = rows[first.advisory_envelope_id], rows[second.advisory_envelope_id]
        assert (old.status, old.optimistic_version) == ("SUPERSEDED", 3)
        assert (new.status, new.predecessor_id) == ("SEALED", old.id)
        assert json.loads(new.canonical_payload_json)["predecessor_envelope_hash"] == old.envelope_hash
        assert new.envelope_hash != old.envelope_hash
        superseded = _audit(db, "ccx.envelope.superseded")
        assert [r.record_id for r in superseded] == [old.id]
        assert new.id in superseded[0].new_value


IMMUTABLE_STATEMENTS = [
    "UPDATE advisory_decision_envelopes SET canonical_payload_json = '{}', optimistic_version = optimistic_version + 1",
    "UPDATE advisory_decision_envelopes SET envelope_hash = '" + "0" * 64 + "', optimistic_version = optimistic_version + 1",
    "UPDATE advisory_decision_envelopes SET status = 'DRAFT', optimistic_version = optimistic_version + 1",
    "UPDATE advisory_decision_envelopes SET status = 'SUPERSEDED'",  # Version nicht +1
    "UPDATE advisory_decision_envelopes SET status = 'SUPERSEDED', canonical_payload_json = '{}', "
    "optimistic_version = optimistic_version + 1",
    "UPDATE advisory_decision_envelopes SET mandate_id = 'other', optimistic_version = optimistic_version + 1",
    "DELETE FROM advisory_decision_envelopes",
    "UPDATE advisory_envelope_bindings SET child_hash = '" + "0" * 64 + "'",
    "DELETE FROM advisory_envelope_bindings",
    "INSERT INTO advisory_envelope_bindings (id, tenant_id, envelope_id, binding_kind, object_type, object_id, "
    "child_hash, ordinal, created_at, created_by) SELECT 'b-x', tenant_id, id, 'extra', 'x', 'x', '"
    + "0" * 64 + "', 9, created_at, created_by FROM advisory_decision_envelopes",
    "UPDATE advisory_effective_input_manifests SET goals_hash = 'x'",
    "DELETE FROM advisory_effective_input_manifests",
]


@pytest.mark.parametrize("statement", IMMUTABLE_STATEMENTS)
def test_sealed_rows_are_immutable(session_factory, statement):
    advisor_id, mid, _aid, run_id = _finalizable_run(session_factory, "immut")
    _finalize(session_factory, advisor_id, mid, run_id)
    with session_factory() as db:
        before = db.execute(text("SELECT envelope_hash, status FROM advisory_decision_envelopes")).all()
        with pytest.raises((IntegrityError, DBAPIError)):
            db.execute(text(statement))
        db.rollback()
        assert db.execute(text("SELECT envelope_hash, status FROM advisory_decision_envelopes")).all() == before


def test_insert_only_as_draft_and_seal_requires_manifest_binding(session_factory):
    advisor_id, mid, _aid, _run = _finalizable_run(session_factory, "draft")
    with session_factory() as db:
        tenant = db.execute(text("SELECT tenant_id FROM mandates WHERE id = :m"), {"m": mid}).scalar()
        insert = (
            "INSERT INTO advisory_decision_envelopes (id, tenant_id, mandate_id, schema_version, status, "
            "locale, base_currency, created_at, created_by, optimistic_version, canonical_payload_json, "
            "envelope_hash, sealed_at, sealed_by) VALUES (:id, :t, :m, 'ares/advisory-envelope/1', :s, 'DE', "
            "'CHF', '2026-11-14T00:00:00.000000Z', :u, 1, :p, :h, :sa, :sb)"
        )
        args = {"t": tenant, "m": mid, "u": advisor_id, "p": "{}", "h": "1" * 64,
                "sa": "2026-11-14T00:00:00.000000Z", "sb": advisor_id}
        with pytest.raises((IntegrityError, DBAPIError)):
            db.execute(text(insert), {**args, "id": "e-sealed", "s": "SEALED"})
        db.rollback()
        db.execute(text(insert), {**args, "id": "e-draft", "s": "DRAFT"})
        with pytest.raises((IntegrityError, DBAPIError), match="CCX_BINDING_MISSING"):
            db.execute(text(
                "UPDATE advisory_decision_envelopes SET status = 'SEALED', optimistic_version = 2 "
                "WHERE id = 'e-draft'"
            ))
        db.rollback()


def test_tenant_guards_reject_foreign_tenant(session_factory):
    from models.tenant import Tenant

    advisor_id, mid, _aid, run_id = _finalizable_run(session_factory, "tenant")
    _finalize(session_factory, advisor_id, mid, run_id)
    with session_factory() as db:
        db.add(Tenant(id="t-foreign", display_name="Fremd", slug="fremd",
                      created_at="2026-11-14T00:00:00Z", updated_at="2026-11-14T00:00:00Z"))
        db.commit()
        envelope = db.execute(text("SELECT id, tenant_id FROM advisory_decision_envelopes")).one()
        with pytest.raises((IntegrityError, DBAPIError), match="MANDATE_EVIDENCE_TENANT_MISMATCH"):
            db.execute(text(
                "INSERT INTO advisory_decision_envelopes (id, tenant_id, mandate_id, schema_version, status, "
                "locale, base_currency, created_at, created_by, optimistic_version) VALUES ('e-x', 't-foreign', "
                ":m, 'ares/advisory-envelope/1', 'DRAFT', 'DE', 'CHF', 'x', :u, 1)"
            ), {"m": mid, "u": advisor_id})
        db.rollback()
        manifest_cols = ", ".join(f"{c}_hash" for c in (
            "client", "mandate", "goals", "cashflows", "risk", "preference", "cma", "policy", "constraints",
            "holdings"))
        with pytest.raises((IntegrityError, DBAPIError), match="MANDATE_EVIDENCE_TENANT_MISMATCH"):
            db.execute(text(
                f"INSERT INTO advisory_effective_input_manifests (id, tenant_id, mandate_id, {manifest_cols}, "
                "engine_version, random_stream_id, rounding_policy_version, manifest_hash, created_at, created_by) "
                "VALUES ('man-x', 't-foreign', :m, " + ", ".join(["'h'"] * 10) + ", 'e', 's', 'r', '"
                + "0" * 64 + "', 'x', :u)"
            ), {"m": mid, "u": advisor_id})
        db.rollback()
        # Bindung mit fremdem Mandanten: zusammengesetzter FK (tenant_id, envelope_id).
        with pytest.raises((IntegrityError, DBAPIError)):
            db.execute(text(
                "INSERT INTO advisory_envelope_bindings (id, tenant_id, envelope_id, binding_kind, object_type, "
                "object_id, child_hash, ordinal, created_at, created_by) VALUES ('b-y', 't-foreign', :e, 'k', "
                "'t', 'o', '" + "0" * 64 + "', 0, 'x', :u)"
            ), {"e": envelope.id, "u": advisor_id})
        db.rollback()


def test_parallel_seal_with_stale_read_has_exactly_one_winner(session_factory, monkeypatch):
    """Zweite Transaktion hat den Vorgaenger vor dem Commit der ersten gelesen
    (kein versiegelter Entscheid sichtbar): Unique ``ux_..._one_sealed`` laesst
    sie scheitern -> CCX_ENVELOPE_UNSEALED, Audit, kein zweites SEALED."""
    import services.advisory_decision_envelope as svc

    advisor_id, mid, aid, run1 = _finalizable_run(session_factory, "race")
    _finalize(session_factory, advisor_id, mid, run1)
    _a, _m, _x, run2 = _finalizable_run(session_factory, "race", mandate=(advisor_id, mid, aid))
    monkeypatch.setattr(svc, "current_sealed_envelope", lambda *a, **k: None)
    with pytest.raises(DomainError) as caught:
        _finalize(session_factory, advisor_id, mid, run2)
    assert caught.value.reason_code == "CCX_ENVELOPE_UNSEALED"
    with session_factory() as db:
        assert db.execute(text(
            "SELECT count(*) FROM advisory_decision_envelopes WHERE status = 'SEALED'")).scalar() == 1
        assert db.execute(text("SELECT result_status FROM recommendation_runs WHERE id = :r"),
                          {"r": run2}).scalar() != "Final"
        rejected = _audit(db, "ccx.envelope.rejected")
        assert len(rejected) == 1 and "reason_code=CCX_ENVELOPE_UNSEALED" in rejected[0].new_value
        assert rejected[0].mandate_id == mid and rejected[0].tenant_id


def test_parallel_seal_with_stale_predecessor_version_loses(session_factory, monkeypatch):
    """Zweite Transaktion hat Vorgaenger P (Version 2) gelesen; inzwischen hat
    eine dritte P abgeloest -> optimistisches UPDATE trifft 0 Zeilen."""
    import services.advisory_decision_envelope as svc
    from models.snapshots import AdvisoryDecisionEnvelope

    advisor_id, mid, aid, run1 = _finalizable_run(session_factory, "stale")
    first = _finalize(session_factory, advisor_id, mid, run1)
    with session_factory() as db:
        p = db.get(AdvisoryDecisionEnvelope, first.advisory_envelope_id)
        stale = SimpleNamespace(id=p.id, envelope_hash=p.envelope_hash, optimistic_version=p.optimistic_version)
    _a, _m, _x, run2 = _finalizable_run(session_factory, "stale", mandate=(advisor_id, mid, aid))
    _finalize(session_factory, advisor_id, mid, run2)  # der Sieger
    _a, _m, _x, run3 = _finalizable_run(session_factory, "stale", mandate=(advisor_id, mid, aid))
    monkeypatch.setattr(svc, "current_sealed_envelope", lambda *a, **k: stale)
    with pytest.raises(DomainError) as caught:
        _finalize(session_factory, advisor_id, mid, run3)
    assert caught.value.reason_code == "CCX_ENVELOPE_UNSEALED"
    with session_factory() as db:
        assert db.execute(text(
            "SELECT count(*) FROM advisory_decision_envelopes WHERE status = 'SEALED'")).scalar() == 1


def test_snapshot_fence_mixed_view_is_retry_and_blocks_finalization(session_factory, monkeypatch):
    import services.advisory_decision_envelope as svc

    real = svc.collect_effective_input_components
    calls = {"n": 0}

    def drifting(db, **kw):
        calls["n"] += 1
        components = real(db, **kw)
        if calls["n"] == 2:  # Ziel wurde zwischen beiden Lesungen geaendert
            components = {**components, "goals_hash": "f" * 64}
        return components

    advisor_id, mid, _aid, run_id = _finalizable_run(session_factory, "fence")
    monkeypatch.setattr(svc, "collect_effective_input_components", drifting)
    with pytest.raises(DomainError) as caught:
        _finalize(session_factory, advisor_id, mid, run_id)
    assert caught.value.reason_code == "CCX_INPUT_MANIFEST_MISMATCH"
    with session_factory() as db:
        assert db.execute(text("SELECT count(*) FROM advisory_decision_envelopes")).scalar() == 0
        assert db.execute(text("SELECT count(*) FROM advisory_effective_input_manifests")).scalar() == 0
        assert db.execute(text("SELECT result_status FROM recommendation_runs WHERE id = :r"),
                          {"r": run_id}).scalar() == "Draft"
        assert "stage=fence" in _audit(db, "ccx.envelope.rejected")[0].new_value


def test_mandate_switch_a_b_a_does_not_leak(session_factory):
    from models.mandates import Mandate
    from models.users import User
    from services.advisory_decision_envelope import advisory_report_cache_scope, current_verified_envelope

    adv_a, mid_a, aid_a, run_a1 = _finalizable_run(session_factory, "switch-a")
    adv_b, mid_b, _aid_b, run_b = _finalizable_run(session_factory, "switch-b")
    env_a1 = _finalize(session_factory, adv_a, mid_a, run_a1).advisory_envelope_hash
    with session_factory() as db:
        scope_a1 = advisory_report_cache_scope(db, db.get(Mandate, mid_a))
    env_b = _finalize(session_factory, adv_b, mid_b, run_b).advisory_envelope_hash
    with session_factory() as db:
        user_a, user_b = db.get(User, adv_a), db.get(User, adv_b)
        view_a = current_verified_envelope(db, mandate=db.get(Mandate, mid_a), user=user_a)
        view_b = current_verified_envelope(db, mandate=db.get(Mandate, mid_b), user=user_b)
        assert (view_a["mandate_id"], view_a["envelope_hash"]) == (mid_a, env_a1)
        assert (view_b["mandate_id"], view_b["envelope_hash"]) == (mid_b, env_b)
        scope_b = advisory_report_cache_scope(db, db.get(Mandate, mid_b))
        assert advisory_report_cache_scope(db, db.get(Mandate, mid_a)) == scope_a1 != scope_b
    _a, _m, _x, run_a2 = _finalizable_run(session_factory, "switch-a", mandate=(adv_a, mid_a, aid_a))
    env_a2 = _finalize(session_factory, adv_a, mid_a, run_a2).advisory_envelope_hash
    assert env_a2 not in (env_a1, env_b)
    with session_factory() as db:
        assert advisory_report_cache_scope(db, db.get(Mandate, mid_a)) not in (scope_a1, scope_b)
        assert current_verified_envelope(
            db, mandate=db.get(Mandate, mid_b), user=db.get(User, adv_b))["envelope_hash"] == env_b


def test_tenant_idor_foreign_advisor_sees_nothing(session_factory):
    from fastapi import HTTPException

    from models.mandates import Mandate
    from models.tenant import Tenant
    from models.users import User
    from routers.review import get_current_advisory_envelope
    from services.advisory_decision_envelope import current_sealed_envelope

    advisor_id, mid, _aid, run_id = _finalizable_run(session_factory, "idor")
    _finalize(session_factory, advisor_id, mid, run_id)
    with session_factory() as db:
        db.add(Tenant(id="t-idor", display_name="Andere Firma", slug="andere",
                      created_at="2026-11-14T00:00:00Z", updated_at="2026-11-14T00:00:00Z"))
        db.add(User(id="adv-idor", username="adv-idor", password_hash="h", full_name="Fremd",
                    role="advisor", is_active=1, tenant_id="t-idor",
                    created_at="2026-11-14T00:00:00Z", updated_at="2026-11-14T00:00:00Z"))
        db.commit()
        with pytest.raises(HTTPException) as caught:
            get_current_advisory_envelope(mandate_id=mid, request=_FakeRequest(), db=db,
                                          current_user=db.get(User, "adv-idor"))
        assert caught.value.status_code == 404
        assert current_sealed_envelope(db, "t-idor", mid) is None
        own = get_current_advisory_envelope(mandate_id=mid, request=_FakeRequest(), db=db,
                                            current_user=db.get(User, advisor_id))
        assert own["mandate_id"] == mid
        assert db.get(Mandate, mid).tenant_id != "t-idor"


def test_missing_envelope_has_reason_code_and_no_fallback(session_factory):
    from models.mandates import Mandate
    from models.users import User
    from services.advisory_decision_envelope import current_verified_envelope

    advisor_id, mid, _aid, _run = _finalizable_run(session_factory, "missing")
    with session_factory() as db:
        with pytest.raises(DomainError) as caught:
            current_verified_envelope(db, mandate=db.get(Mandate, mid), user=db.get(User, advisor_id))
    assert caught.value.reason_code == "CCX_ENVELOPE_MISSING"
    assert caught.value.http_status == 404


TAMPER = [
    ("CCX_ENVELOPE_HASH_MISMATCH", "trg_advisory_decision_envelopes_update_guard",
     "UPDATE advisory_decision_envelopes SET envelope_hash = '" + "e" * 64 + "'"),
    ("CCX_ENVELOPE_HASH_MISMATCH", "trg_advisory_decision_envelopes_update_guard",
     "UPDATE advisory_decision_envelopes SET canonical_payload_json = replace(canonical_payload_json, "
     "'\"locale\":\"', '\"locale\":\"X')"),
    ("CCX_BINDING_MISSING", "trg_advisory_envelope_bindings_no_update",
     "UPDATE advisory_envelope_bindings SET child_hash = '" + "e" * 64 + "' "
     "WHERE binding_kind = 'target_allocation'"),
    ("CCX_BINDING_MISSING", "trg_advisory_envelope_bindings_no_delete",
     "DELETE FROM advisory_envelope_bindings WHERE binding_kind = 'recommendation_run'"),
    ("CCX_INPUT_MANIFEST_MISMATCH", "trg_advisory_effective_input_manifests_no_update",
     "UPDATE advisory_effective_input_manifests SET goals_hash = '" + "e" * 64 + "'"),
    ("CCX_INPUT_MANIFEST_MISMATCH", "trg_advisory_effective_input_manifests_no_update",
     "UPDATE advisory_effective_input_manifests SET rounding_policy_version = 'ares-rounding/0'"),
]


@pytest.mark.parametrize("code,trigger,statement", TAMPER)
def test_integrity_break_is_rejected_with_code_and_audit(session_factory, code, trigger, statement):
    """Owner-Bypass (Trigger entfernt) simuliert Manipulation: jeder Bruch der
    Kette wird mit dem katalogisierten Code abgelehnt und auditiert."""
    from models.mandates import Mandate
    from models.users import User
    from services.advisory_decision_envelope import current_verified_envelope

    advisor_id, mid, _aid, run_id = _finalizable_run(session_factory, "tamper")
    _finalize(session_factory, advisor_id, mid, run_id)
    with session_factory() as db:
        db.execute(text(f"DROP TRIGGER {trigger}"))
        db.execute(text(statement))
        db.commit()
        with pytest.raises(DomainError) as caught:
            current_verified_envelope(db, mandate=db.get(Mandate, mid), user=db.get(User, advisor_id))
        assert caught.value.reason_code == code
        rejected = _audit(db, "ccx.envelope.rejected")
        assert rejected and f"reason_code={code}" in rejected[-1].new_value
        assert rejected[-1].mandate_id == mid


def test_cache_entry_is_scoped_by_envelope(session_factory, monkeypatch):
    import services.advisory_report_cache as cache
    from models.mandates import Mandate

    advisor_id, mid, aid, run1 = _finalizable_run(session_factory, "cache")
    monkeypatch.setattr(cache.settings, "aggregator_cache_enabled", True, raising=False)
    cache.reset_for_tests()
    computed = []
    monkeypatch.setattr(cache, "compute_advisory_report",
                        lambda db, mandate, advisor=None: computed.append(1) or {"n": len(computed)})
    with session_factory() as db:
        cache.cached_compute_advisory_report(db, db.get(Mandate, mid))
        cache.cached_compute_advisory_report(db, db.get(Mandate, mid))
    assert len(computed) == 1
    _finalize(session_factory, advisor_id, mid, run1)  # neuer Entscheid -> neuer Scope
    with session_factory() as db:
        cache.cached_compute_advisory_report(db, db.get(Mandate, mid))
    assert len(computed) == 2
    cache.reset_for_tests()


# ── Migration und Paritaet ───────────────────────────────────────────────────


def _alembic_cfg(db_url):
    from alembic.config import Config

    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", db_url)
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    return cfg


ENVELOPE_TABLES = ("advisory_decision_envelopes", "advisory_envelope_bindings", "advisory_effective_input_manifests")


def test_alembic_single_head_and_upgrade_downgrade_upgrade(tmp_path):
    from alembic import command
    from alembic.script import ScriptDirectory
    from sqlalchemy import create_engine, inspect

    script = ScriptDirectory.from_config(_alembic_cfg("sqlite://"))
    assert script.get_heads() == [CCX_P1_REV]
    assert script.get_revision(CCX_P1_REV).down_revision == CCX_P1_PARENT
    url = f"sqlite:///{tmp_path / 'ccx.db'}"
    cfg = _alembic_cfg(url)

    def tables():
        engine = create_engine(url)
        try:
            return set(inspect(engine).get_table_names())
        finally:
            engine.dispose()

    command.upgrade(cfg, "head")
    assert set(ENVELOPE_TABLES) <= tables()
    command.downgrade(cfg, CCX_P1_PARENT)
    assert not set(ENVELOPE_TABLES) & tables()
    command.upgrade(cfg, "head")
    assert set(ENVELOPE_TABLES) <= tables()


def _schema(conn):
    columns = {t: [r[1] for r in conn.execute(f"PRAGMA table_info({t})")] for t in ENVELOPE_TABLES}
    names = ", ".join(f"'{t}'" for t in ENVELOPE_TABLES)
    triggers = {r[0] for r in conn.execute(
        f"SELECT name FROM sqlite_master WHERE type = 'trigger' AND tbl_name IN ({names})")}
    indexes = {r[0] for r in conn.execute(
        f"SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name IN ({names}) "
        "AND name NOT LIKE 'sqlite_%'")}
    return columns, triggers, indexes


def test_orm_bootstrap_runtime_patch_and_alembic_are_identical(tmp_path, monkeypatch):
    from alembic import command
    from sqlalchemy import create_engine

    import database as db_module
    from database import (
        ADVISORY_ENVELOPE_SQLITE_TENANT_GUARDS,
        ADVISORY_ENVELOPE_SQLITE_TRIGGERS,
        Base,
    )

    orm_db = tmp_path / "orm.db"
    engine = create_engine(f"sqlite:///{orm_db}")
    Base.metadata.create_all(engine)
    engine.dispose()
    with sqlite3.connect(orm_db) as conn:
        orm = _schema(conn)

    boot_db = tmp_path / "boot.db"
    db_module.bootstrap_sqlite_schema(db_path=boot_db, schema_path=BACKEND / "ares_schema.sql")
    with sqlite3.connect(boot_db) as conn:
        boot_columns = _schema(conn)[0]
        for table in reversed(ENVELOPE_TABLES):
            conn.execute(f"DROP TABLE {table}")
        conn.commit()
    engine = create_engine(f"sqlite:///{boot_db}")
    monkeypatch.setattr(db_module, "engine", engine)
    db_module.ensure_runtime_columns()
    engine.dispose()
    with sqlite3.connect(boot_db) as conn:
        patched = _schema(conn)

    alembic_db = tmp_path / "alembic.db"
    command.upgrade(_alembic_cfg(f"sqlite:///{alembic_db}"), "head")
    with sqlite3.connect(alembic_db) as conn:
        migrated = _schema(conn)

    assert orm[0] == boot_columns == patched[0] == migrated[0]
    assert orm[1] == patched[1] == migrated[1]
    assert len(orm[1]) == len(ADVISORY_ENVELOPE_SQLITE_TRIGGERS) + len(ADVISORY_ENVELOPE_SQLITE_TENANT_GUARDS)
    assert orm[2] == patched[2] == migrated[2]

    import importlib.util

    path = BACKEND / "alembic" / "versions" / f"{CCX_P1_REV}_ccx_p1_advisory_decision_envelopes.py"
    spec = importlib.util.spec_from_file_location("ccx_p1_migration_under_test", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    # Eingefrorene Alembic-Kopie == Laufzeit-Konstanten (gleiche Trigger-Texte).
    assert migration._SQLITE_TRIGGERS == ADVISORY_ENVELOPE_SQLITE_TRIGGERS + ADVISORY_ENVELOPE_SQLITE_TENANT_GUARDS
    assert migration.revision == CCX_P1_REV and migration.down_revision == CCX_P1_PARENT


def test_bootstrap_sql_is_textually_identical_to_constants():
    from database import ADVISORY_ENVELOPE_SQLITE_TABLE_DDL, ADVISORY_ENVELOPE_SQLITE_TRIGGERS

    schema = (BACKEND / "ares_schema.sql").read_text(encoding="utf-8")
    for ddl in ADVISORY_ENVELOPE_SQLITE_TABLE_DDL + ADVISORY_ENVELOPE_SQLITE_TRIGGERS:
        assert ddl + ";" in schema
    assert "trg_advisory_decision_envelopes_tenant_guard" not in schema  # braucht mandates.tenant_id


def test_no_float_in_any_new_table_column():
    from models.snapshots import AdvisoryDecisionEnvelope, AdvisoryEffectiveInputManifest, AdvisoryEnvelopeBinding

    for model in (AdvisoryDecisionEnvelope, AdvisoryEnvelopeBinding, AdvisoryEffectiveInputManifest):
        for column in model.__table__.columns:
            assert column.type.python_type in (str, int), (model.__tablename__, column.name)
    assert not math.isnan(0.0)  # Kontrolle: Modul importiert
