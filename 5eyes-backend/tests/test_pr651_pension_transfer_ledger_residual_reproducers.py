"""Residual contracts for merged PR #651 / develop@662670b85f796544.

The five original PR-#642 adversarial contracts pass on the reviewed merge.
Uebernommen aus dem Codex-Reproducer (Branch
codex/asset-allocation-stochastic-core,
docs/audits/reproducers/test_2026_10_19_pr651_pension_transfer_ledger_residual_adversarial.py)
als regulaere Tests ohne xfail (Fix: fix/pension-ledger-identity-snapshot).
The two former strict xfails preserve the remaining accounting-identity and
durable-evidence requirements without undoing the source lifecycle, one-time,
cardinality, or horizon fixes.

Certification::

    pytest -q --runxfail \
      docs/audits/reproducers/test_2026_10_19_pr651_pension_transfer_ledger_residual_adversarial.py

must pass only after an adviser-supplied net amount can no longer create an
unexplained source-balance adjustment and the ledger identity is carried into
the foundation/run evidence.  This file is audit evidence, not product code.
"""
from __future__ import annotations

from types import SimpleNamespace


START = 2026
HORIZON = 5


def _position(**overrides):
    values = {
        "id": "p-pr651-audit",
        "label": "3a Quelle",
        "position_type": "Vorsorge",
        "assignment": "Anderes Vermögen",
        "current_value_rappen": 10_000_000,
        "currency": "CHF",
        "pension_type": "Säule 3a",
        "pension_vehicle": "Konto",
        "pension_interest_rate_bps": 0,
        "pension_maturity_value_rappen": None,
        "pension_maturity_date": None,
        "pension_retirement_age": None,
        "liquidity_available_from": "2028-06-30",
        "pension_lumpsum_tax_rappen": None,
        "pension_lumpsum_tax_bps": None,
        "is_active": 1,
        "deleted_at": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _linked(**overrides):
    values = {
        "id": "i-pr651-audit",
        "label": "Erfasster Kapitalbezug",
        "source_type": "Saeule3b",
        "amount_rappen": 10_500_000,
        "expected_year": 2028,
        "linked_position_id": "p-pr651-audit",
        "is_active": 1,
        "is_recurring": 0,
        "frequency": None,
        "duration_years": None,
        "value_mode": "nominal",
        "deleted_at": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_full_transfer_reconciles_projected_source_to_gross_and_closing_balance():
    """A full-transfer ledger may restate value, but must book the bridge.

    The adviser-supplied net remains authoritative.  If it exceeds the
    projected source balance, the row therefore needs an explicit, named
    valuation/reconciliation adjustment.  Silently setting gross := net makes
    ``projected source = gross + closing`` false and creates 500,000 rappen in
    the ledger without a balancing field.
    """
    from services.portfolio_engine_pension_positions import build_pension_projection

    projection = build_pension_projection(
        [_position()],
        [_linked()],
        start_year=START,
        horizon_years=HORIZON,
        value_of=lambda item: item.current_value_rappen,
    )
    assert projection is not None
    (row,) = projection.ledger.rows

    adjustment = getattr(row, "valuation_adjustment_rappen", 0)
    assert (
        row.projected_bound_balance_rappen + adjustment
        == row.gross_withdrawal_rappen + row.closing_bound_balance_rappen
    )


def test_foundation_payload_carries_replayable_transfer_ledger_identity():
    """A transient dataclass/hash cannot certify later consumers or reloads."""
    from services.portfolio_engine_pension_positions import pension_foundation_keys

    foundation = pension_foundation_keys(
        [_position()],
        [_linked(amount_rappen=9_000_000)],
        start_year=START,
        horizon_years=HORIZON,
        target_currency="CHF",
    )

    assert foundation["pension_transfer_ledger_version"] == "PensionTransferLedgerV1"
    assert len(foundation["pension_transfer_ledger_input_hash"]) == 64
    assert foundation["pension_transfer_ledger_rows"][0]["source_position_id"] == "p-pr651-audit"
