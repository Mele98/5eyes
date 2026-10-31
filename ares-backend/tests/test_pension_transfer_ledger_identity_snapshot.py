"""PENSION-TRANSFER-LEDGER-001 -- Restbefunde A und B aus dem Codex-Closure-
Review zu PR #651 (docs/audits/2026-10-19-pension-transfer-ledger-pr651-closure-review.md).

A) Ledger-Identitaet: ``projected + valuation_adjustment = gross + closing``
   und ``gross = tax + net``, rappengenau, mit expliziter Bewertungsanpassung
   und Steuer-Provenienz observed/inferred/unavailable. Der erfasste
   Nettobetrag bleibt massgebend (CIO-Entscheid 2026-10-19).
B) PensionTransferLedgerSnapshotV1: Teil der Foundation (input_snapshot_hash),
   persistiert an der TargetAllocation, Referenz im allocation_context_hash,
   beim Reload aus den gespeicherten Daten verifiziert.
"""
from __future__ import annotations

import datetime
import json
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.pension_transfer_ledger import (  # noqa: E402
    PensionTransferLedgerError,
    PensionTransferRow,
)
from services.pension_transfer_ledger_snapshot import (  # noqa: E402
    CONSTRAINTS_REF_KEY,
    FOUNDATION_SNAPSHOT_KEY,
    PENSION_TRANSFER_LEDGER_SNAPSHOT_VERSION,
    bind_pension_transfer_ledger_snapshot,
    canonical_foundation_projection,
    verify_bound_pension_transfer_ledger_snapshot,
    verify_pension_transfer_ledger_snapshot,
)
from services.portfolio_engine_pension_positions import (  # noqa: E402
    build_pension_projection,
    pension_foundation_keys,
)

START = 2026
H = 5


def _position(**overrides):
    values = {
        "id": "p-a", "label": "3a Quelle", "position_type": "Vorsorge",
        "assignment": "Anderes Vermögen", "current_value_rappen": 10_000_000, "currency": "CHF",
        "pension_type": "Säule 3a", "pension_vehicle": "Konto", "pension_interest_rate_bps": 0,
        "pension_maturity_value_rappen": None, "pension_maturity_date": None,
        "pension_retirement_age": None, "liquidity_available_from": "2028-06-30",
        "pension_lumpsum_tax_rappen": None, "pension_lumpsum_tax_bps": None,
        "is_active": 1, "deleted_at": None, "updated_at": "2026-10-01T00:00:00Z",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _linked(**overrides):
    values = dict(
        id="i-a", label="Kapitalbezug", source_type="Saeule3b", amount_rappen=10_000_000,
        expected_year=2028, linked_position_id="p-a", is_active=1, is_recurring=0,
        frequency=None, duration_years=None, value_mode="nominal", deleted_at=None,
        updated_at="2026-10-02T00:00:00Z",
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def _row(positions, inflows, horizon=H):
    projection = build_pension_projection(
        positions, inflows, start_year=START, horizon_years=horizon,
        value_of=lambda item: item.current_value_rappen,
    )
    (row,) = projection.ledger.rows
    return row


def _identities_hold(row) -> bool:
    return (
        row.projected_bound_balance_rappen + row.valuation_adjustment_rappen
        == row.gross_withdrawal_rappen + row.closing_bound_balance_rappen
        and row.gross_withdrawal_rappen == row.lumpsum_tax_rappen + row.net_advisory_inflow_rappen
    )


# ---------------------------------------------------------------------------
# A) Identitaet + Provenienz
# ---------------------------------------------------------------------------


def test_recorded_net_above_projection_books_explicit_positive_adjustment():
    row = _row([_position()], [_linked(amount_rappen=10_500_000)])
    assert row.net_advisory_inflow_rappen == 10_500_000  # massgebend
    assert row.valuation_adjustment_rappen == 500_000
    assert row.lumpsum_tax_rappen == 0 and row.tax_provenance == "unavailable"
    assert _identities_hold(row)


def test_recorded_net_below_projection_separates_inferred_tax_and_adjustment():
    # Default 10 % auf 100'000 = 10'000 abgeleitete Steuer; Luecke 13'000.
    row = _row([_position()], [_linked(amount_rappen=8_700_000)])
    assert row.net_advisory_inflow_rappen == 8_700_000
    assert row.lumpsum_tax_rappen == 1_000_000
    assert row.tax_provenance == "inferred" and row.tax_source == "default"
    assert row.valuation_adjustment_rappen == -300_000
    assert _identities_hold(row)


def test_inferred_tax_never_exceeds_the_gap_below_projection():
    row = _row([_position(pension_lumpsum_tax_rappen=2_000_000)], [_linked(amount_rappen=9_500_000)])
    assert row.lumpsum_tax_rappen == 500_000 and row.tax_provenance == "inferred"
    assert row.valuation_adjustment_rappen == 0
    assert _identities_hold(row)


def test_recorded_net_equal_to_projection_has_zero_adjustment_and_no_tax_claim():
    row = _row([_position()], [_linked(amount_rappen=10_000_000)])
    assert row.valuation_adjustment_rappen == 0
    assert row.lumpsum_tax_rappen == 0 and row.tax_provenance == "unavailable"
    assert _identities_hold(row)


def test_auto_payout_provenance_observed_vs_inferred():
    observed = _row([_position(pension_lumpsum_tax_rappen=700_000)], [])
    assert observed.tax_provenance == "observed" and observed.valuation_adjustment_rappen == 0
    rate = _row([_position(pension_lumpsum_tax_bps=500)], [])
    assert rate.tax_provenance == "inferred" and rate.tax_source == "erfasst_satz"
    default = _row([_position()], [])
    assert default.tax_provenance == "inferred" and default.tax_source == "default"
    assert all(_identities_hold(r) for r in (observed, rate, default))


def test_row_rejects_unnamed_source_delta():
    good = _row([_position()], [_linked(amount_rappen=10_500_000)])
    data = {**good.identity(), "within_horizon": True}
    data["valuation_adjustment_rappen"] = 0  # die alte, unbenannte Differenz
    with pytest.raises(PensionTransferLedgerError) as exc:
        PensionTransferRow(**data)
    assert exc.value.reason_code == "PENSION_TRANSFER_UNRECONCILED"
    data = {**good.identity(), "within_horizon": True, "lumpsum_tax_rappen": 1}
    with pytest.raises(ValueError):
        PensionTransferRow(**data)


def test_unavailable_tax_must_be_zero_and_auto_rows_carry_no_adjustment():
    auto = _row([_position()], [])
    with pytest.raises(ValueError):
        PensionTransferRow(**{**auto.identity(), "within_horizon": True, "tax_provenance": "unavailable"})
    with pytest.raises(PensionTransferLedgerError):
        PensionTransferRow(**{
            **auto.identity(), "within_horizon": True,
            "valuation_adjustment_rappen": 1, "gross_withdrawal_rappen": auto.gross_withdrawal_rappen + 1,
            "net_advisory_inflow_rappen": auto.net_advisory_inflow_rappen + 1,
        })


def test_net_payout_series_is_unchanged_by_the_reconciliation():
    projection = build_pension_projection(
        [_position()], [_linked(amount_rappen=10_500_000)], start_year=START, horizon_years=H,
        value_of=lambda item: item.current_value_rappen,
    )
    assert projection.payout_series_rappen == [0, 0, 10_500_000, 0, 0]
    assert any("Bewertungsanpassung" in note for note in projection.notes)


# ---------------------------------------------------------------------------
# B) Snapshot
# ---------------------------------------------------------------------------


def _foundation(positions, inflows, horizon=H, **kwargs):
    return pension_foundation_keys(positions, inflows, start_year=START, horizon_years=horizon, **kwargs)


def test_snapshot_carries_versions_policy_fx_sources_rows_and_hash():
    foundation = _foundation([_position()], [_linked(amount_rappen=10_500_000)])
    snapshot = foundation[FOUNDATION_SNAPSHOT_KEY]
    assert snapshot["snapshot_version"] == PENSION_TRANSFER_LEDGER_SNAPSHOT_VERSION
    assert snapshot["ledger_version"] == foundation["pension_transfer_ledger_version"]
    assert snapshot["ledger_input_hash"] == foundation["pension_transfer_ledger_input_hash"]
    assert snapshot["policy_version"].startswith("vorsorge-projektion-")
    assert snapshot["valuation_year"] == START and snapshot["currency"] == "CHF"
    assert snapshot["fx_evidence"] == {"status": "not_applied", "target_currency": "CHF"}
    assert snapshot["sources"] == [{
        "position_id": "p-a", "updated_at": "2026-10-01T00:00:00Z", "currency": "CHF",
        "current_value_rappen": 10_000_000,
    }]
    assert snapshot["inflows"][0]["inflow_id"] == "i-a"
    assert snapshot["inflows"][0]["updated_at"] == "2026-10-02T00:00:00Z"
    (row,) = snapshot["rows"]
    assert row["valuation_adjustment_rappen"] == 500_000 and row["tax_provenance"] == "unavailable"
    assert snapshot["snapshot_id"] == f"ptls-{snapshot['snapshot_hash'][:24]}"
    assert verify_pension_transfer_ledger_snapshot(snapshot) is snapshot


def test_snapshot_records_applied_fx_basis():
    from services.currency.fx_rates import FXRateSource

    fx = FXRateSource()
    foundation = _foundation([_position(currency="EUR")], [], fx_source=fx)
    evidence = foundation[FOUNDATION_SNAPSHOT_KEY]["fx_evidence"]
    assert evidence["status"] == "applied" and evidence["basis_id"] == fx.basis_id
    assert [c for c, _rate in evidence["effective_rates_x1e8"]] == ["CHF", "EUR"]


def test_snapshot_hash_is_horizon_invariant_but_binds_inputs():
    base = _foundation([_position()], [_linked()])[FOUNDATION_SNAPSHOT_KEY]
    longer = _foundation([_position()], [_linked()], horizon=15)[FOUNDATION_SNAPSHOT_KEY]
    assert base["snapshot_hash"] == longer["snapshot_hash"]
    changed_amount = _foundation([_position()], [_linked(amount_rappen=9_000_000)])[FOUNDATION_SNAPSHOT_KEY]
    changed_version = _foundation([_position()], [_linked(updated_at="2026-10-20T00:00:00Z")])
    changed_source = _foundation([_position(updated_at="2026-10-20T00:00:00Z")], [_linked()])
    hashes = {
        base["snapshot_hash"], changed_amount["snapshot_hash"],
        changed_version[FOUNDATION_SNAPSHOT_KEY]["snapshot_hash"],
        changed_source[FOUNDATION_SNAPSHOT_KEY]["snapshot_hash"],
    }
    assert len(hashes) == 4


@pytest.mark.parametrize("mutate", [
    lambda s: s["rows"][0].update(net_advisory_inflow_rappen=1),
    lambda s: s["rows"][0].update(valuation_adjustment_rappen=0),
    lambda s: s.update(policy_version="other"),
    lambda s: s["inflows"][0].update(amount_rappen=1),
    lambda s: s.pop("fx_evidence"),
])
def test_tampered_snapshot_is_rejected(mutate):
    snapshot = json.loads(json.dumps(
        _foundation([_position()], [_linked(amount_rappen=10_500_000)])[FOUNDATION_SNAPSHOT_KEY]
    ))
    mutate(snapshot)
    with pytest.raises(ValueError):
        verify_pension_transfer_ledger_snapshot(snapshot)


def test_rehashed_snapshot_with_broken_identity_is_still_rejected():
    from services.pension_transfer_ledger_snapshot import _BODY_KEYS, _sha256

    snapshot = _foundation([_position()], [_linked(amount_rappen=10_500_000)])[FOUNDATION_SNAPSHOT_KEY]
    forged = json.loads(json.dumps(snapshot))
    forged["rows"][0]["valuation_adjustment_rappen"] = 0
    body = {key: forged[key] for key in _BODY_KEYS}
    forged["snapshot_hash"] = _sha256(body)
    forged["snapshot_id"] = f"ptls-{forged['snapshot_hash'][:24]}"
    with pytest.raises(ValueError):
        verify_pension_transfer_ledger_snapshot(forged)


def test_bind_and_verify_roundtrip_and_pairing():
    foundation = _foundation([_position()], [_linked()])
    constraints: dict = {"engine_version": "x"}
    raw = bind_pension_transfer_ledger_snapshot(constraints, foundation)
    ref = constraints[CONSTRAINTS_REF_KEY]
    assert ref["snapshot_hash"] == foundation[FOUNDATION_SNAPSHOT_KEY]["snapshot_hash"]
    allocation = SimpleNamespace(pension_transfer_ledger_snapshot_json=raw)
    assert verify_bound_pension_transfer_ledger_snapshot(allocation, constraints)["snapshot_id"] == ref["snapshot_id"]
    with pytest.raises(ValueError):
        verify_bound_pension_transfer_ledger_snapshot(SimpleNamespace(pension_transfer_ledger_snapshot_json=None), constraints)
    with pytest.raises(ValueError):
        verify_bound_pension_transfer_ledger_snapshot(allocation, {})
    other = bind_pension_transfer_ledger_snapshot({}, _foundation([_position()], [_linked(amount_rappen=1)]))
    with pytest.raises(ValueError):
        verify_bound_pension_transfer_ledger_snapshot(
            SimpleNamespace(pension_transfer_ledger_snapshot_json=other), constraints,
        )
    # ohne externe Vorsorge: Constraints byte-identisch, keine Spalte
    plain: dict = {"engine_version": "x"}
    assert bind_pension_transfer_ledger_snapshot(plain, {"property_series_rappen": [0]}) is None
    assert plain == {"engine_version": "x"}
    assert verify_bound_pension_transfer_ledger_snapshot(SimpleNamespace(), plain) is None


def test_canonical_foundation_keeps_ledger_identity_and_ints_series():
    foundation = {"property_series_rappen": [1, 2], **_foundation([_position()], [_linked()])}
    canonical = canonical_foundation_projection(foundation)
    assert canonical["pension_transfer_ledger_snapshot"] == foundation["pension_transfer_ledger_snapshot"]
    assert canonical["property_series_rappen"] == [1, 2]
    json.dumps(canonical, sort_keys=True)


# ---------------------------------------------------------------------------
# B) End-to-End: Generate -> persistiert/gebunden -> Reload verifiziert
# ---------------------------------------------------------------------------


from test_optimizer_shadow_mode import _seed_realistic_mandate, session_factory  # noqa: E402,F401


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


def _seed_pension(session, client_id: str, start_year: int) -> tuple[str, str]:
    from models.wealth import WealthInflow, WealthPosition

    pid, iid = f"pos-3a-{uuid.uuid4().hex[:8]}", f"inf-3a-{uuid.uuid4().hex[:8]}"
    session.add(WealthPosition(
        id=pid, client_id=client_id, label="3a Konto", position_type="Vorsorge",
        assignment="Anderes Vermögen", current_value_rappen=100_000_00, currency="CHF",
        pension_type="Säule 3a", liquidity_available_from=f"{start_year + 2}-03-31",
        is_active=1, created_at=_now(), updated_at=_now(),
    ))
    session.add(WealthInflow(
        id=iid, client_id=client_id, label="3a-Bezug", source_type="Saeule3b",
        amount_rappen=105_000_00, expected_year=start_year + 2, is_recurring=0,
        value_mode="nominal", linked_position_id=pid, is_active=1,
        created_at=_now(), updated_at=_now(),
    ))
    session.flush()
    return pid, iid


def _reload(session, mandate, ta):
    import services.portfolio_engine as pe
    from models.allocation import OptimizerPolicy
    from models.profiling import RiskAssessment
    from models.allocation import CapitalMarketAssumption

    policy = session.query(OptimizerPolicy).filter(OptimizerPolicy.id == ta.policy_id).one()
    cma = session.query(CapitalMarketAssumption).filter(
        CapitalMarketAssumption.id == ta.capital_market_assumptions_id
    ).one()
    assessment = session.query(RiskAssessment).filter(RiskAssessment.id == ta.based_on_assessment_id).one()
    return pe.build_target_payload_from_allocation(
        db=session, mandate=mandate, allocation=ta, policy=policy, cma=cma,
        assessment=assessment, preferences=None,
    ), policy, cma, assessment


def test_generate_persists_and_binds_snapshot_reload_verifies(session_factory, monkeypatch):  # noqa: F811
    import services.portfolio_engine as pe
    from models.mandates import Mandate
    from models.wealth import WealthInflow

    monkeypatch.setattr(pe.settings, "optimizer_mode", "house_matrix")
    advisor_id, client_id, mandate_id, _aid, _gid = _seed_realistic_mandate(
        session_factory, suffix=f"ptl-{uuid.uuid4().hex[:6]}",
    )
    with session_factory() as session:
        mandate = session.query(Mandate).filter(Mandate.id == mandate_id).one()
        _pid, iid = _seed_pension(session, client_id, datetime.date.today().year)
        result = pe.generate_target_allocation(session, mandate, advisor_id, preferences=None)
        ta = result["target_allocation"]
        session.commit()

        snapshot = json.loads(ta.pension_transfer_ledger_snapshot_json)
        verify_pension_transfer_ledger_snapshot(snapshot)
        constraints = json.loads(ta.effective_constraints_json)
        assert constraints[CONSTRAINTS_REF_KEY]["snapshot_hash"] == snapshot["snapshot_hash"]
        (row,) = snapshot["rows"]
        assert row["net_advisory_inflow_rappen"] == 105_000_00
        assert row["valuation_adjustment_rappen"] == 5_000_00
        assert result["pension_transfer_ledger_snapshot"]["snapshot_id"] == snapshot["snapshot_id"]

        payload, policy, cma, assessment = _reload(session, mandate, ta)
        assert payload["pension_transfer_ledger_snapshot"] == snapshot

        # manueller Speicherpfad bindet denselben Snapshot
        from services.manual_target_allocation import build_manual_target_allocation

        targets = {b: getattr(ta, f"target_{b}_bps") for b in pe.BUCKET_FIELDS}
        bounds = {b: (getattr(ta, f"band_{b}_min_bps"), getattr(ta, f"band_{b}_max_bps")) for b in pe.BUCKET_FIELDS}
        manual = build_manual_target_allocation(
            session, mandate=mandate, policy=policy, cma=cma, assessment=assessment,
            previous=ta, targets_bps=targets, bounds_bps=bounds, reason="Test",
            user_id=advisor_id, now=_now(),
        ).allocation
        assert json.loads(manual.pension_transfer_ledger_snapshot_json)["snapshot_hash"] == snapshot["snapshot_hash"]
        assert json.loads(manual.effective_constraints_json)[CONSTRAINTS_REF_KEY] == constraints[CONSTRAINTS_REF_KEY]

        # Manipulierte Spalte -> Reload fail-closed
        original = ta.pension_transfer_ledger_snapshot_json
        forged = json.loads(original)
        forged["rows"][0]["net_advisory_inflow_rappen"] += 1
        ta.pension_transfer_ledger_snapshot_json = json.dumps(forged)
        with pytest.raises(ValueError):
            _reload(session, mandate, ta)
        ta.pension_transfer_ledger_snapshot_json = None
        with pytest.raises(ValueError):
            _reload(session, mandate, ta)
        ta.pension_transfer_ledger_snapshot_json = original

        # Aenderung eines gebundenen Inputs -> alte Allokation stale
        inflow = session.query(WealthInflow).filter(WealthInflow.id == iid).one()
        inflow.amount_rappen = 104_000_00
        session.flush()
        with pytest.raises(pe.StaleAllocationInputError):
            _reload(session, mandate, ta)
