"""CERT-COST-CONFLICT-001 -- permanent repository reproducers.

Source of truth: the Ares/Codex audit worktree
`C:\\Users\\Emanuele\\Documents\\ChatGPT\\5eyes wird zu Ares\\asset-allocation-stochastic-core`
(branch `codex/asset-allocation-stochastic-core`),
`docs/audits/2026-10-08-cost-disclosure-inducement-conflict-finalization-certification-spec.md`.
That spec documents eight canonical P1 findings (nine current assertions --
`COST-CONTEXT-001` has two independent failure modes: wrong run selection and
after-the-fact live drift) as reproduced-but-not-committed; its own temporary
reproducer was deliberately removed after the run, per its
`product_code_mutated: false` / `tests_mutated: false` audit discipline.
This file adopts those nine assertions as PERMANENT repository tests,
mirroring the pattern already used for the sibling package
`CERT-PRODUCT-ELIGIBILITY-001`
(tests/test_cert_product_eligibility_001_reproducers.py on branch
test/cert-product-eligibility-001-reproducers).

All nine root causes below were independently re-verified against this
repo's actual current `develop` HEAD before writing these tests -- not
copied from the spec's historical evidence unchecked. In particular:

- `services/cost_disclosure.py::build_cost_disclosure` still selects the
  mandate's RecommendationRun purely by `created_at.desc()` with no status/
  explicit-run filter (lines ~76-81), still falls back to the current
  TargetAllocation by ID with no mandate ownership check (lines ~155-173),
  and still recomputes TER/fee/conflict inputs live on every call.
- `services/cost_disclosure.py::calculate_cost_disclosure` still clamps
  malformed fee rates through `_safe_int`/`max(0, ...)` instead of a typed
  validator (lines ~240-243, ~564-574), and still emits an unconditional
  "Verzicht dokumentiert" claim for any non-reimbursed, bezifferte
  Retrozession regardless of `disclosed_to_client`/`waiver_document_id`
  (lines ~440-458).
- `services/advisory_report.py::_build_conflict_disclosures` still computes
  `has_unacknowledged` only as `disclosed_to_client and not client_acknowledged`
  (lines ~3090-3093), so a conflict that was never disclosed at all stays
  `False`.
- `services/advisory_log_service.py::_build_cost_disclosure_snapshot` still
  calls the mandate-wide `build_cost_disclosure(db, mandate)` ignoring the
  log entry's own `recommendation_run_id`, and still persists only six
  reduced fields (lines ~113-137).
- `routers/review.py::_validate_recommendation_for_finalization` still has
  no CostDisclosure/ConflictEvidence/waiver/reimbursement gate at all
  (lines ~165-263); `finalize_recommendation` (lines ~2669-2706) sets the
  run to `Final` once this validator returns no errors.

Do not close any of these by weakening the assertion, deleting the test, or
patching only a narrow symptom (e.g. adding `result_status == "Final"` to
the existing `latest()` query without the full explicit-run/no-live-drift
contract, or clamping invalid values to null with an extra warning). Closure
requires the full `CostDisclosureSnapshotV1` / `ConflictEvidenceSnapshotV1`
contract from Sections 4/6/7/8 of the spec.
"""
from __future__ import annotations

import json
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import configure_mappers, sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = Path(__file__).resolve().parent
for _p in (BACKEND_ROOT, TESTS_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from database import Base, new_uuid  # noqa: E402
from models import (  # noqa: E402,F401
    allocation, clients, client_login, fx_rate, mandates, profiling,
    protocol_bausteine, review, snapshots, tenant, users, wealth,
)
configure_mappers()

from models.allocation import OptimizerPolicy, TargetAllocation  # noqa: E402
from models.clients import Client  # noqa: E402
from models.mandates import Mandate  # noqa: E402
from models.review import (  # noqa: E402
    AdvisoryLog, ConflictOfInterestDisclosure, Product, RecommendationPosition,
    RecommendationRun,
)
from models.users import User  # noqa: E402
from schemas.review import AdvisoryLogCreate  # noqa: E402
from services.advisory_log_service import create_advisory_log  # noqa: E402
from services.advisory_report import _build_conflict_disclosures  # noqa: E402
from services.cost_disclosure import (  # noqa: E402
    build_cost_disclosure, calculate_cost_disclosure,
)
from routers.review import (  # noqa: E402
    _validate_recommendation_for_finalization, finalize_recommendation,
)
from test_finalize_mandate_lock import (  # noqa: E402
    _FakeRequest, _add_full_position, _allocation_policy_and_cma,
    _current_allocation_id, _make_run as _make_finalize_run,
)
from test_optimizer_shadow_mode import _seed_realistic_mandate, session_factory  # noqa: E402,F401


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _now() -> str:
    return _iso(datetime.now(timezone.utc))


@pytest.fixture()
def cc_session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'cert_cost_conflict.db'}",
        connect_args={"check_same_thread": False},
    )
    sf = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield sf
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _seed_mandate(sf, *, suffix: str, base_currency: str = "CHF"):
    advisor_id = f"adv-{suffix}"
    client_id = f"cli-{suffix}"
    mandate_id = f"mdt-{suffix}"
    now = _now()
    with sf() as s:
        s.add(User(
            id=advisor_id, username=f"user-{suffix}", password_hash="h",
            full_name="Test Advisor", role="advisor", is_active=1,
            created_at=now, updated_at=now,
        ))
        s.add(Client(
            id=client_id, client_number=f"C-{suffix}", first_name="A", last_name="B",
            advisor_id=advisor_id, created_at=now, updated_at=now,
        ))
        s.add(Mandate(
            id=mandate_id, client_id=client_id, mandate_number=f"M-{suffix}",
            mandate_type="Anlageberatung", status="Aktiv", base_currency=base_currency,
            opened_at=now, created_at=now, updated_at=now,
        ))
        s.commit()
    return advisor_id, client_id, mandate_id


def _make_product(sf, product_id: str, *, ter_bps: int | None = 50) -> None:
    now = _now()
    with sf() as s:
        s.add(Product(
            id=product_id, product_name=f"Produkt {product_id}", provider="Test",
            product_type="ETF", asset_class="Aktien", currency="CHF",
            ter_bps=ter_bps, is_active=1, created_at=now, updated_at=now,
        ))
        s.commit()


def _make_policy(sf, policy_id: str, created_by: str) -> None:
    now = _now()
    with sf() as s:
        s.add(OptimizerPolicy(
            id=policy_id, policy_name="default", version=1, is_current=1,
            valid_from=now, created_by=created_by, created_at=now, updated_at=now,
        ))
        s.commit()


def _make_allocation(
    sf, allocation_id: str, mandate_id: str, policy_id: str, set_by: str,
    *, advisory_wealth_rappen: int,
) -> None:
    now = _now()
    with sf() as s:
        s.add(TargetAllocation(
            id=allocation_id, mandate_id=mandate_id, is_current=1,
            band_equities_min_bps=0, band_equities_max_bps=10000,
            band_bonds_min_bps=0, band_bonds_max_bps=10000,
            band_real_estate_min_bps=0, band_real_estate_max_bps=10000,
            band_alternatives_min_bps=0, band_alternatives_max_bps=10000,
            band_liquidity_min_bps=0, band_liquidity_max_bps=10000,
            policy_id=policy_id, set_by=set_by, set_at=now,
            advisory_wealth_at_generation_rappen=advisory_wealth_rappen,
            created_at=now, updated_at=now,
        ))
        s.commit()


def _make_run(
    sf, run_id: str, mandate_id: str, client_id: str, *, target_allocation_id: str | None,
    policy_id: str | None, created_by: str, result_status: str, created_at: str,
    fee_assumptions: dict | None = None,
) -> None:
    with sf() as s:
        s.add(RecommendationRun(
            id=run_id, mandate_id=mandate_id, client_id=client_id,
            target_allocation_id=target_allocation_id, policy_id=policy_id,
            run_type="Optimizer", result_status=result_status,
            fee_assumptions_json=(json.dumps(fee_assumptions) if fee_assumptions is not None else None),
            created_by=created_by, created_at=created_at, updated_at=created_at,
        ))
        s.commit()


def _make_position(sf, run_id: str, product_id: str, *, weight_bps: int, amount_rappen: int) -> None:
    now = _now()
    with sf() as s:
        s.add(RecommendationPosition(
            id=new_uuid(), run_id=run_id, product_id=product_id,
            target_weight_bps=weight_bps, target_amount_rappen=amount_rappen,
            created_at=now, updated_at=now,
        ))
        s.commit()


def _make_conflict(sf, mandate_id: str, disclosed_by: str, **overrides) -> str:
    conflict_id = overrides.pop("id", new_uuid())
    now = _now()
    defaults = dict(
        conflict_type="Retrozession",
        description="Vertriebsentschaedigung Fondsanbieter",
        inducement_provider="Fund XY",
        inducement_amount_rappen=50_000,
        inducement_frequency="jährlich",
        disclosed_to_client=0,
        client_acknowledged=0,
        reimbursed_to_client=0,
        waiver_document_id=None,
        disclosed_by=disclosed_by,
        created_at=now,
        updated_at=now,
    )
    defaults.update(overrides)
    with sf() as s:
        s.add(ConflictOfInterestDisclosure(id=conflict_id, mandate_id=mandate_id, **defaults))
        s.commit()
    return conflict_id


def _advisory_log_payload(**overrides) -> AdvisoryLogCreate:
    defaults = dict(
        entry_type="Initialer Beratungsabschluss",
        title="Erstberatung",
        description="A" * 40,
        entry_datetime=_now(),
        duration_minutes=45,
        communication_channel="persoenlich",
        language="de",
        topics=["Kosten"],
        risk_warnings_given=["Marktrisiko"],
        cost_disclosure_given=True,
    )
    defaults.update(overrides)
    return AdvisoryLogCreate(**defaults)


# ---------------------------------------------------------------------------
# COST-CONTEXT-001a -- a newer Draft run displaces a certified Final run as
# the cost-disclosure source. build_cost_disclosure() picks purely by
# created_at.desc() with no result_status/explicit-run filter.
#
# FIXED (CERT-COST-CONFLICT-001, 2026-10-13): the query now selects by a
# STATUS PRIORITY ('Final' before 'Draft'), not by date. A Draft remains a
# legitimate source while advice is being prepared -- the advisor wants to
# see costs before finalising -- but it can no longer displace a certified
# Final. Found alongside and also closed: 'Rejected' and 'Superseded' are
# valid `result_status` values (CHECK in 5eyes_schema_v4.0_FINAL.sql) and
# could likewise become the client's cost basis; they are now no source at
# all, and a mandate holding only such runs gets a `_pending_payload` naming
# the reason. The payload additionally carries `source_run_status`, so a
# draft-based disclosure is visibly provisional. xfail removed: strict=True
# would otherwise report an unexpected XPASS.
#
# NOT closed by this: COST-CONTEXT-001b (live drift of a certified run's
# evidence) stays xfail below -- that needs a persisted run-bound snapshot,
# the same contract as COST-EVIDENCE-001.
# ---------------------------------------------------------------------------


def test_newer_draft_must_not_displace_certified_final_run_as_cost_source(cc_session_factory):
    sf = cc_session_factory
    advisor_id, client_id, mandate_id = _seed_mandate(sf, suffix="ctx-a")
    _make_product(sf, "prd-ctx-a", ter_bps=50)
    _make_policy(sf, "pol-ctx-a", advisor_id)
    _make_allocation(
        sf, "ta-ctx-a", mandate_id, "pol-ctx-a", advisor_id,
        advisory_wealth_rappen=1_000_000_00,
    )
    t0 = datetime.now(timezone.utc)
    final_run_id = "run-ctx-a-final"
    _make_run(
        sf, final_run_id, mandate_id, client_id,
        target_allocation_id="ta-ctx-a", policy_id="pol-ctx-a",
        created_by=advisor_id, result_status="Final", created_at=_iso(t0),
        fee_assumptions={"default_advisory_fee_bps": 25},
    )
    _make_position(sf, final_run_id, "prd-ctx-a", weight_bps=10000, amount_rappen=1_000_000_00)

    draft_run_id = "run-ctx-a-draft"
    _make_run(
        sf, draft_run_id, mandate_id, client_id,
        target_allocation_id="ta-ctx-a", policy_id="pol-ctx-a",
        created_by=advisor_id, result_status="Draft", created_at=_iso(t0 + timedelta(minutes=5)),
        fee_assumptions={"default_advisory_fee_bps": 999},
    )

    with sf() as db:
        mandate = db.query(Mandate).filter(Mandate.id == mandate_id).first()
        payload = build_cost_disclosure(db, mandate)

    # Soll: the certified Final run remains the cost-disclosure source even
    # though an unrelated, later Draft run exists for the same mandate.
    assert payload["source_run_id"] == final_run_id


# ---------------------------------------------------------------------------
# COST-CONTEXT-001b -- a certified run's cost evidence drifts when the
# underlying Product.ter_bps is corrected later: build_cost_disclosure()
# re-reads live TER on every call instead of freezing it at certification.
#
# FIXED (CERT-COST-CONFLICT-001, 2026-10-13): `finalize_recommendation()`
# now freezes the full cost disclosure onto
# `RecommendationRun.cost_disclosure_snapshot_json` (payload + SHA-256), and
# `build_cost_disclosure()` returns that snapshot instead of recomputing.
# The hash is re-derived on read; a snapshot whose content does not match it
# is refused rather than served.
#
# The test BODY had to move to the production path, and that is the point
# rather than a convenience. The original seeded `result_status="Final"`
# straight into the database -- a state no production path produces, because
# certification only happens through `finalize_recommendation()`. Satisfying
# it literally would have required freezing lazily on first read, i.e.
# labelling TODAY's live numbers as the evidence of a certification that
# happened earlier. That is a fabricated provenance, and worse than the
# drift it would hide.
#
# So the run is now seeded as a Draft and certified through the real
# endpoint. The Soll is unchanged in substance -- a certified run's totals
# must not move when a live input is corrected afterwards -- and it is now
# tested end to end instead of against a hand-made state.
#
# Runs finalised BEFORE this change carry no snapshot. They are computed
# live and say so (`evidence_frozen=False` plus a warning); they are NOT
# retro-frozen, for the same reason.
# ---------------------------------------------------------------------------


def test_certified_final_run_cost_totals_must_not_drift_with_later_live_ter_correction(session_factory):
    advisor_id, _cid, mid, aid, _gid = _seed_realistic_mandate(session_factory, suffix="ctx-b")
    alloc_id = _current_allocation_id(session_factory, mid, advisor_id)
    policy, cma = _allocation_policy_and_cma(session_factory, alloc_id)
    run_id = _make_finalize_run(session_factory, mid, alloc_id, aid, advisor_id, policy, cma)
    _add_full_position(session_factory, run_id)

    with session_factory() as db:
        product_id = (
            db.query(RecommendationPosition)
            .filter(RecommendationPosition.run_id == run_id)
            .first()
            .product_id
        )

    # Zertifizierung ueber die PRODUKTIONSSTRECKE -- dort wird eingefroren.
    with session_factory() as db:
        mandate = db.query(Mandate).filter(Mandate.id == mid).first()
        advisor = db.query(User).filter(User.id == advisor_id).first()
        finalize_recommendation(
            mandate_id=mid, run_id=run_id, request=_FakeRequest(),
            db=db, current_user=advisor,
        )

    with session_factory() as db:
        mandate = db.query(Mandate).filter(Mandate.id == mid).first()
        before = build_cost_disclosure(db, mandate)
    assert before["evidence_frozen"] is True, (
        "Die Finalisierung hat keinen Nachweis eingefroren -- ohne ihn kann "
        f"der Test unten nichts beweisen: {before.get('warnings')}"
    )

    # Eine spaetere TER-Korrektur am SELBEN Produkt, ohne neuen Lauf.
    with session_factory() as db:
        db.query(Product).filter(Product.id == product_id).update({"ter_bps": 5000})
        db.commit()

    with session_factory() as db:
        mandate = db.query(Mandate).filter(Mandate.id == mid).first()
        after = build_cost_disclosure(db, mandate)

    # Soll: a certified Final run's cost disclosure is an immutable snapshot
    # -- a later correction to a live input must not change its totals.
    assert after["totals"] == before["totals"]
    assert after["content_hash"] == before["content_hash"]


# ---------------------------------------------------------------------------
# COST-BASIS-001 -- target_allocation_id is loaded by ID alone, with no
# check that the allocation actually belongs to the same mandate.
# ---------------------------------------------------------------------------


# GEFIXT am 2026-10-12: der Lookup war an NICHTS gebunden -- nicht an das
# Mandat, nicht an deleted_at. Gemessen lieferte eine fremde Allokation die
# Vermoegensbasis 999'900'000 Rappen (CHF 9'999'000 aus Mandat B), waehrend
# Mandat A CHF 100'000 haelt: die Vermoegenszahl eines anderen Kunden floss
# in dieses Kundendokument, und die Kostenquote wurde um Faktor 100 zu
# niedrig ausgewiesen.
#
# Fail-closed statt Ersatz: nennt der Lauf eine Allokation, die nicht zu
# diesem Mandat gehoert, ist die Basis dieses Ausweises unbestimmt. Auf die
# aktuelle Allokation zurueckzufallen waere dieselbe stille Substitution,
# nur innerhalb des Mandats.
def test_run_bound_to_foreign_mandates_allocation_must_block_not_adopt_its_basis(cc_session_factory):
    sf = cc_session_factory
    # Mandate B owns a TargetAllocation with a distinctive wealth basis.
    advisor_b, client_b, mandate_b = _seed_mandate(sf, suffix="basis-b")
    _make_policy(sf, "pol-basis-b", advisor_b)
    _make_allocation(
        sf, "ta-basis-foreign", mandate_b, "pol-basis-b", advisor_b,
        advisory_wealth_rappen=9_999_000_00,
    )

    # Mandate A's run points at Mandate B's allocation (cross-mandate leak)
    # and has no allocation of its own.
    advisor_a, client_a, mandate_a = _seed_mandate(sf, suffix="basis-a")
    _make_product(sf, "prd-basis-a", ter_bps=50)
    run_id = "run-basis-a"
    _make_run(
        sf, run_id, mandate_a, client_a,
        target_allocation_id="ta-basis-foreign", policy_id="pol-basis-b",
        created_by=advisor_a, result_status="Final", created_at=_now(),
        fee_assumptions={"default_advisory_fee_bps": 25},
    )
    _make_position(sf, run_id, "prd-basis-a", weight_bps=10000, amount_rappen=100_000_00)

    with sf() as db:
        mandate = db.query(Mandate).filter(Mandate.id == mandate_a).first()
        payload = build_cost_disclosure(db, mandate)

    # Soll: a foreign/unrelated allocation must block (fail-closed), never
    # silently supply its wealth basis to another mandate's cost disclosure.
    assert payload["data_pending"] is True, (
        f"Fremde Allokation lieferte Vermoegensbasis {payload.get('advisory_wealth_rappen')} "
        "statt zu blockieren"
    )


# ---------------------------------------------------------------------------
# COST-DOMAIN-001 -- a malformed fee rate is clamped to 0 via _safe_int
# instead of being typed-rejected.
#
# FIXED (CERT-COST-CONFLICT-001, 2026-10-12): `_require_rate_bps()` replaces
# `max(0, _safe_int(...))` at every fee-rate entry point. It raises
# CostDisclosureDomainError (a ValueError subclass) carrying a stable
# `reason_code`, following the check order of the existing
# `cma_validation._integral_bps` precedent. Deliberately no upper bound:
# there is no precedent for a fee-rate ceiling in this repo, and an absurdly
# HIGH rate is visible in the document whereas the silent zero was not.
# xfail removed: strict=True would otherwise report an unexpected XPASS.
# ---------------------------------------------------------------------------


def test_malformed_fee_rate_must_be_typed_rejected_not_normalized_to_zero():
    # Soll: a non-parseable fee rate must raise/be rejected with a stable
    # reason code. Today _first_present_rate -> _safe_int() silently turns
    # "not-a-rate" into 0 and the key is accepted as "configured".
    with pytest.raises((ValueError, TypeError)):
        calculate_cost_disclosure(
            advisory_wealth_rappen=1_000_000_00,
            positions=[{"amount_rappen": 1_000_000_00, "weight_bps": 10000, "ter_bps": 50}],
            fee_model={"default_advisory_fee_bps": "not-a-rate"},
            source_run_id="run-domain-1",
            currency="CHF",
        )


# ---------------------------------------------------------------------------
# COST-COMPLETENESS-001 -- is_complete only checks key-presence + 100% TER
# coverage, so a malformed-but-present fee value can still yield complete=True.
#
# FIXED (CERT-COST-CONFLICT-001, 2026-10-12), and the assertion had to MOVE
# to a different boundary. This reproducer and COST-DOMAIN-001 above
# originally called the SAME function with the SAME input
# (`{"default_advisory_fee_bps": "not-a-rate"}`) and demanded opposite
# things: one a raise, the other a returned payload with is_complete=False.
# Both could never be green at once -- a genuine contradiction inside the
# cluster, not an implementation gap.
#
# Resolution, which keeps both Soll statements intact:
#
#   pure function  `calculate_cost_disclosure()`  -> raises (COST-DOMAIN-001).
#                  A malformed rate is a broken ARGUMENT; no number may come
#                  back, not even a different one.
#   data boundary  `build_cost_disclosure()`      -> _pending_payload, which
#                  carries is_complete=False and names the reason. Letting
#                  the exception reach the endpoint would tear down the
#                  FIDLEG document with HTTP 500 over one legacy value --
#                  the advisor would see an error page instead of the cause.
#
# So the Soll below is unchanged in substance ("an invalid configured fee
# value must never let is_complete=True"); it is now asserted where a
# payload actually exists. The pure-function half is covered above.
# ---------------------------------------------------------------------------


def test_is_complete_must_not_be_true_when_a_configured_fee_value_is_invalid(cc_session_factory):
    sf = cc_session_factory
    advisor_id, client_id, mandate_id = _seed_mandate(sf, suffix="completeness")
    _make_product(sf, "prd-completeness", ter_bps=50)
    _make_policy(sf, "pol-completeness", advisor_id)
    _make_allocation(
        sf, "ta-completeness", mandate_id, "pol-completeness", advisor_id,
        advisory_wealth_rappen=1_000_000_00,
    )
    run_id = "run-completeness-1"
    _make_run(
        sf, run_id, mandate_id, client_id,
        target_allocation_id="ta-completeness", policy_id="pol-completeness",
        created_by=advisor_id, result_status="Final", created_at=_now(),
        # Der kaputte Wert, wie er in einem Altlauf persistiert sein kann.
        fee_assumptions={"default_advisory_fee_bps": "not-a-rate"},
    )
    # 100 % TER-Deckung auf der einzigen Position -- die zweite Bedingung von
    # `is_complete` ist also erfuellt. Nur der Gebuehrenwert ist kaputt.
    _make_position(sf, run_id, "prd-completeness", weight_bps=10000, amount_rappen=1_000_000_00)

    with sf() as db:
        mandate = db.query(Mandate).filter(Mandate.id == mandate_id).first()
        payload = build_cost_disclosure(db, mandate)

    # Soll: an invalid configured fee value must never let is_complete=True.
    assert payload["is_complete"] is False
    # Und es darf auch keine Kostenzahl ausgewiesen werden, die auf der
    # stillen Null beruht -- sonst waere is_complete=False nur Kosmetik.
    assert payload["data_pending"] is True
    assert payload["cost_items"] == []
    assert any("unverwertbar" in w for w in payload["warnings"]), payload["warnings"]


# ---------------------------------------------------------------------------
# COST-EVIDENCE-001 -- AdvisoryLog's cost_disclosure_snapshot_json binds
# neither the chosen recommendation_run_id nor a replayable snapshot (items,
# status, warnings, hash); it stores six reduced sum fields from the
# mandate-wide (not run-bound) builder.
#
# FIXED (CERT-COST-CONFLICT-001, 2026-10-13): `_build_cost_disclosure_
# snapshot()` now takes the log entry's own `recommendation_run_id`,
# resolves that run bound to the mandate (same hardening as COST-BASIS-001 --
# a foreign mandate's run must not become this log's evidence), and stores
# the full payload: items, totals, warnings, completeness, the run id and
# its status, plus a SHA-256 over the record. Where the run carries the
# snapshot frozen at certification (COST-CONTEXT-001b), THAT is the source,
# so the log holds the numbers the client actually received rather than a
# recomputation. Without a named run it falls back to the mandate-wide
# builder as before and leaves the binding explicitly empty instead of
# claiming a run. Still fail-soft: no numbers means no snapshot, and the
# `cost_disclosure_given` flag stays valid. xfail removed: strict=True would
# otherwise report an unexpected XPASS.
# ---------------------------------------------------------------------------


def test_advisory_log_snapshot_must_bind_full_replayable_run_evidence(cc_session_factory):
    sf = cc_session_factory
    advisor_id, client_id, mandate_id = _seed_mandate(sf, suffix="evidence")
    _make_product(sf, "prd-evidence", ter_bps=50)
    _make_policy(sf, "pol-evidence", advisor_id)
    _make_allocation(
        sf, "ta-evidence", mandate_id, "pol-evidence", advisor_id,
        advisory_wealth_rappen=1_000_000_00,
    )
    run_id = "run-evidence-final"
    _make_run(
        sf, run_id, mandate_id, client_id,
        target_allocation_id="ta-evidence", policy_id="pol-evidence",
        created_by=advisor_id, result_status="Final", created_at=_now(),
        fee_assumptions={"default_advisory_fee_bps": 25},
    )
    _make_position(sf, run_id, "prd-evidence", weight_bps=10000, amount_rappen=1_000_000_00)

    with sf() as db:
        advisor = db.query(User).filter(User.id == advisor_id).first()
        mandate = db.query(Mandate).filter(Mandate.id == mandate_id).first()
        entry = create_advisory_log(
            db, mandate_id=mandate_id, advisor=advisor,
            payload=_advisory_log_payload(recommendation_run_id=run_id),
            mandate=mandate,
        )
        db.commit()
        snapshot_json = entry.cost_disclosure_snapshot_json

    assert snapshot_json is not None
    snapshot = json.loads(snapshot_json)
    # Soll: the AdvisoryLog must bind a full replayable snapshot of the
    # chosen run -- at minimum its id, items, status, warnings and a content
    # hash. Today only generated_at/currency/advisory_wealth_rappen and three
    # reduced totals are stored.
    required_keys = {"recommendation_run_id", "cost_items", "status", "warnings", "content_hash"}
    missing = required_keys - snapshot.keys()
    assert not missing, f"AdvisoryLog-Snapshot ist kein vollstaendiger Nachweis, fehlt: {sorted(missing)}"


# ---------------------------------------------------------------------------
# INDUCEMENT-EVIDENCE-001 -- a retrocession the advisor keeps is labelled
# "Verzicht dokumentiert" (waiver on record) unconditionally, even when it
# was never disclosed to the client and has no waiver_document_id.
#
# FIXED (CERT-COST-CONFLICT-001, 2026-10-12): the root cause was one layer
# above the emitting branch -- build_cost_disclosure()'s projection dropped
# `disclosed_to_client` and `waiver_document_id`, so calculate_cost_disclosure()
# structurally could not know whether a waiver existed, and asserted it anyway.
# Both fields are now threaded through and _has_documented_waiver() gates the
# claim. Without evidence the item stays visible (FIDLEG Art. 26) but under
# key "retrocession_retained_unwaived" with requires_resolution=True and no
# waiver claim. The Soll-assertion below is unchanged. xfail removed:
# strict=True would otherwise report an unexpected XPASS.
# ---------------------------------------------------------------------------


def test_undisclosed_unwaived_retained_inducement_must_not_claim_waiver_on_record(cc_session_factory):
    sf = cc_session_factory
    advisor_id, client_id, mandate_id = _seed_mandate(sf, suffix="inducement")
    _make_product(sf, "prd-inducement", ter_bps=50)
    _make_policy(sf, "pol-inducement", advisor_id)
    _make_allocation(
        sf, "ta-inducement", mandate_id, "pol-inducement", advisor_id,
        advisory_wealth_rappen=1_000_000_00,
    )
    run_id = "run-inducement-final"
    _make_run(
        sf, run_id, mandate_id, client_id,
        target_allocation_id="ta-inducement", policy_id="pol-inducement",
        created_by=advisor_id, result_status="Final", created_at=_now(),
        fee_assumptions={"default_advisory_fee_bps": 25},
    )
    _make_position(sf, run_id, "prd-inducement", weight_bps=10000, amount_rappen=1_000_000_00)

    # Retained (not reimbursed) retrocession, but NEVER disclosed to the
    # client, and with no waiver document on file.
    _make_conflict(
        sf, mandate_id, advisor_id,
        reimbursed_to_client=0, disclosed_to_client=0, client_acknowledged=0,
        waiver_document_id=None, inducement_amount_rappen=50_000,
        inducement_frequency="jährlich",
    )

    with sf() as db:
        mandate = db.query(Mandate).filter(Mandate.id == mandate_id).first()
        payload = build_cost_disclosure(db, mandate)

    retained_items = [item for item in payload["cost_items"] if item["key"] == "retrocession_disclosed"]
    # Soll: without disclosure AND a verified waiver document, no "Verzicht
    # dokumentiert" (waiver on record) claim may appear at all.
    assert not retained_items, (
        "Unbelegter Verzicht-Claim ohne Offenlegung/Waiver-Dokument erschien im Kostenausweis: "
        f"{retained_items}"
    )


# ---------------------------------------------------------------------------
# CONFLICT-STATE-001 -- a conflict that was never disclosed to the client at
# all is reported as acknowledged (has_unacknowledged=False), the opposite
# of fail-closed.
#
# FIXED (CERT-COST-CONFLICT-001, 2026-10-12): the rule is inverted -- only a
# fully resolved conflict (disclosed AND acknowledged) counts as resolved, so
# every other state, the never-disclosed one included, now sets the flag.
# Each entry additionally carries a typed `resolution_state`, because "go
# disclose it" and "go collect the acknowledgement" are different next steps
# and a single boolean cannot say which; `client_acknowledged=1` with
# `disclosed_to_client=0` is reported as the data contradiction it is.
# Found alongside and also fixed: the except-branch answered
# has_unacknowledged=False on a read error -- a read error is not an
# all-clear. xfail removed: strict=True would otherwise report an
# unexpected XPASS.
# ---------------------------------------------------------------------------


def test_never_disclosed_conflict_must_be_flagged_unresolved_not_acknowledged(cc_session_factory):
    sf = cc_session_factory
    advisor_id, client_id, mandate_id = _seed_mandate(sf, suffix="conflict-state")
    _make_conflict(
        sf, mandate_id, advisor_id,
        disclosed_to_client=0, client_acknowledged=0,
    )

    with sf() as db:
        mandate = db.query(Mandate).filter(Mandate.id == mandate_id).first()
        result = _build_conflict_disclosures(db, mandate)

    # Soll: a conflict that was never disclosed is unresolved/indeterminate
    # and must set has_unacknowledged=True (fail-closed), not False.
    assert result["has_unacknowledged"] is True


# ---------------------------------------------------------------------------
# COST-FINALIZATION-001 -- finalize_recommendation() has no cost-disclosure
# or conflict-evidence gate at all; an undisclosed, unresolved inducement
# conflict does not block finalization.
#
# FIXED (CERT-COST-CONFLICT-001, 2026-10-13):
# `_validate_recommendation_for_finalization()` now consults the same
# conflict-evidence resolver as the Advisory-Report (CONFLICT-STATE-001), so
# gate and report cannot diverge. `indeterminate` and `action_required` both
# refuse certification, and the error names what is missing per conflict.
#
# The gate deliberately landed only together with the resolution endpoints
# (/disclose, /acknowledge, /mitigate, /attach-document). Before those
# existed, `result_status` could only ever be 0/0 -- the gate would have
# blocked every mandate holding a single conflict row with no way for an
# advisor to clear it. Fail-closed would not have been safe, it would have
# been inoperable.
#
# The sanity assertion below had to go, and that is not a weakening. It read
# `assert errors == []` with the comment "demonstrating it never looks at
# conflict/cost evidence" -- it pinned the DEFECT as the expected state, so
# fixing the defect necessarily makes it false. The Soll (finalize must
# raise) is unchanged and now additionally checks that the refusal names the
# conflicts. xfail removed: strict=True would otherwise report an unexpected
# XPASS.
# ---------------------------------------------------------------------------


def test_finalize_must_block_when_mandate_has_unresolved_conflict_evidence(session_factory):
    advisor_id, _cid, mid, aid, _gid = _seed_realistic_mandate(session_factory, suffix="cost-fin")
    alloc_id = _current_allocation_id(session_factory, mid, advisor_id)
    policy, cma = _allocation_policy_and_cma(session_factory, alloc_id)
    run_id = _make_finalize_run(session_factory, mid, alloc_id, aid, advisor_id, policy, cma)
    _add_full_position(session_factory, run_id)

    # Undisclosed, unacknowledged, unwaived retrocession for this mandate.
    _make_conflict(
        session_factory, mid, advisor_id,
        disclosed_to_client=0, client_acknowledged=0, reimbursed_to_client=0,
        waiver_document_id=None,
    )

    with session_factory() as db:
        mandate = db.query(Mandate).filter(Mandate.id == mid).first()
        advisor = db.query(User).filter(User.id == advisor_id).first()
        run = db.query(RecommendationRun).filter(RecommendationRun.id == run_id).first()
        # Der Validator MUSS den Konfliktzustand sehen -- und sagen, was
        # fehlt. Eine blosse Ablehnung ohne Begruendung waere fuer den
        # Berater nicht handhabbar.
        errors, _warnings = _validate_recommendation_for_finalization(db, mandate, run)
        assert errors, "Der Validator uebergeht den Konflikt-Nachweiszustand"
        assert any("Interessenkonflikte" in error for error in errors), errors

        # Soll: finalize must refuse to certify a run while unresolved
        # conflict evidence exists for the mandate.
        with pytest.raises(HTTPException):
            finalize_recommendation(
                mandate_id=mid, run_id=run_id, request=_FakeRequest(),
                db=db, current_user=advisor,
            )
