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
# ---------------------------------------------------------------------------


@pytest.mark.xfail(strict=True, reason="COST-CONTEXT-001 -- CERT-COST-CONFLICT-001 (run selection)")
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
# ---------------------------------------------------------------------------


@pytest.mark.xfail(strict=True, reason="COST-CONTEXT-001 -- CERT-COST-CONFLICT-001 (live drift)")
def test_certified_final_run_cost_totals_must_not_drift_with_later_live_ter_correction(cc_session_factory):
    sf = cc_session_factory
    advisor_id, client_id, mandate_id = _seed_mandate(sf, suffix="ctx-b")
    _make_product(sf, "prd-ctx-b", ter_bps=50)
    _make_policy(sf, "pol-ctx-b", advisor_id)
    _make_allocation(
        sf, "ta-ctx-b", mandate_id, "pol-ctx-b", advisor_id,
        advisory_wealth_rappen=1_000_000_00,
    )
    run_id = "run-ctx-b-final"
    _make_run(
        sf, run_id, mandate_id, client_id,
        target_allocation_id="ta-ctx-b", policy_id="pol-ctx-b",
        created_by=advisor_id, result_status="Final", created_at=_now(),
        fee_assumptions={"default_advisory_fee_bps": 25},
    )
    _make_position(sf, run_id, "prd-ctx-b", weight_bps=10000, amount_rappen=1_000_000_00)

    with sf() as db:
        mandate = db.query(Mandate).filter(Mandate.id == mandate_id).first()
        before = build_cost_disclosure(db, mandate)

    # A later TER correction on the SAME product, with NO new run created.
    with sf() as db:
        db.query(Product).filter(Product.id == "prd-ctx-b").update({"ter_bps": 500})
        db.commit()

    with sf() as db:
        mandate = db.query(Mandate).filter(Mandate.id == mandate_id).first()
        after = build_cost_disclosure(db, mandate)

    # Soll: a certified Final run's cost disclosure is an immutable snapshot
    # -- a later correction to a live input must not change its totals.
    assert after["totals"] == before["totals"]


# ---------------------------------------------------------------------------
# COST-BASIS-001 -- target_allocation_id is loaded by ID alone, with no
# check that the allocation actually belongs to the same mandate.
# ---------------------------------------------------------------------------


@pytest.mark.xfail(strict=True, reason="COST-BASIS-001 -- CERT-COST-CONFLICT-001")
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
# ---------------------------------------------------------------------------


@pytest.mark.xfail(strict=True, reason="COST-DOMAIN-001 -- CERT-COST-CONFLICT-001")
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
# ---------------------------------------------------------------------------


@pytest.mark.xfail(strict=True, reason="COST-COMPLETENESS-001 -- CERT-COST-CONFLICT-001")
def test_is_complete_must_not_be_true_when_a_configured_fee_value_is_invalid():
    payload = calculate_cost_disclosure(
        advisory_wealth_rappen=1_000_000_00,
        # 100% TER coverage on the only position.
        positions=[{"amount_rappen": 1_000_000_00, "weight_bps": 10000, "ter_bps": 50}],
        fee_model={"default_advisory_fee_bps": "not-a-rate"},
        source_run_id="run-completeness-1",
        currency="CHF",
    )
    # Soll: an invalid configured fee value must never let is_complete=True.
    assert payload["is_complete"] is False


# ---------------------------------------------------------------------------
# COST-EVIDENCE-001 -- AdvisoryLog's cost_disclosure_snapshot_json binds
# neither the chosen recommendation_run_id nor a replayable snapshot (items,
# status, warnings, hash); it stores six reduced sum fields from the
# mandate-wide (not run-bound) builder.
# ---------------------------------------------------------------------------


@pytest.mark.xfail(strict=True, reason="COST-EVIDENCE-001 -- CERT-COST-CONFLICT-001")
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
# ---------------------------------------------------------------------------


@pytest.mark.xfail(strict=True, reason="INDUCEMENT-EVIDENCE-001 -- CERT-COST-CONFLICT-001")
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
# ---------------------------------------------------------------------------


@pytest.mark.xfail(strict=True, reason="CONFLICT-STATE-001 -- CERT-COST-CONFLICT-001")
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
# ---------------------------------------------------------------------------


@pytest.mark.xfail(strict=True, reason="COST-FINALIZATION-001 -- CERT-COST-CONFLICT-001")
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
        # Sanity: today's validator sees no errors at all for this run --
        # demonstrating it never looks at conflict/cost evidence.
        errors, _warnings = _validate_recommendation_for_finalization(db, mandate, run)
        assert errors == []

        # Soll: finalize must refuse to certify a run while unresolved
        # conflict evidence exists for the mandate.
        with pytest.raises(HTTPException):
            finalize_recommendation(
                mandate_id=mid, run_id=run_id, request=_FakeRequest(),
                db=db, current_user=advisor,
            )
