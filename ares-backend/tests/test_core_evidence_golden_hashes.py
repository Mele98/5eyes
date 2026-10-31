"""K-1 (A2 M4): Golden-Hashes der Evidence-Belege -- vor und nach dem Umbau.

Fuer jede Belegart wird ein deterministischer Fixture-Beleg ueber die
oeffentliche Produktionsfunktion gehasht und gegen einen Wert verglichen,
der auf ``origin/develop`` VOR Einfuehrung von ``core.evidence`` berechnet
und hier eingefroren wurde. Wo die Kanonisierung einem benannten Schema
entspricht, muss ``core.evidence.evidence_hash`` denselben Wert liefern.

Aendert sich ein Wert, aendert sich die Kanonisierung eines Belegtyps --
gespeicherte Belege wuerden dann als manipuliert gelten. Ein solcher Diff
ist nie "Pin nachziehen", sondern ein Befund.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from core.evidence import (
    SCHEME_LEGACY_SPACED_STR_DEFAULT,
    SCHEME_LEGACY_UNSORTED_UTF8,
    SCHEME_V1,
    SCHEME_V1_ASCII,
    SCHEME_V1_ASCII_STR_DEFAULT,
    SCHEME_V1_STR_DEFAULT,
    canonical_json,
    evidence_hash,
    sha256_hex,
)

_VALUES = (
    "Zürich – Genève 💶", 125000050, 0.1 + 0.2, None, True, "2026-10-31T12:34:56.789Z",
    -0.0, "", False, 2**53 + 1, "Straße/ÄÖÜ", 4.2e-7,
)


def _fixture(fields, **overrides) -> dict:
    data = {name: _VALUES[i % len(_VALUES)] for i, name in enumerate(fields)}
    data.update(overrides)
    return data


_TRADES = [
    {"product_id": "P-1", "isin": "CH0012345678", "side": "buy", "amount_rappen": 1250000,
     "name": "Obligationen Schweiz – Zürich", "weight": 0.125},
    {"product_id": "P-2", "isin": None, "side": "sell", "amount_rappen": 0, "name": "Ä 💶"},
]


def _cases():
    from services import (
        backtest_stress,
        cma_policy,
        cost_disclosure,
        depot_snapshot,
        financial_coverage_attestation as fca,
        goal_analysis_snapshot,
        goal_revision_decision as grd,
        pension_transfer_ledger_snapshot as ptls,
        portfolio_engine,
        portfolio_engine_allocation_integrity as pai,
        portfolio_handoff,
        portfolio_reconciliation,
        product_eligibility,
        reserve_funding_ledger,
        risk_capacity_evaluation_snapshot as rces,
        risk_override_decision as rod,
        risk_profile_signoff as rps,
    )
    from services.currency import fx_rates

    signoff_v1 = _fixture(rps.HASHED_FIELDS_V1, schema_version=rps.SCHEMA_VERSION_V1)
    signoff_v2 = _fixture(rps.HASHED_FIELDS, schema_version=rps.SCHEMA_VERSION)
    decision_v1 = _fixture(rod.HASHED_FIELDS_V1, schema_version=rod.SCHEMA_VERSION_V1)
    decision_v2 = _fixture(rod.HASHED_FIELDS, schema_version=rod.SCHEMA_VERSION)
    attestation_v1 = _fixture(fca.HASHED_FIELDS_V1, schema_version=fca.SCHEMA_VERSION_V1)
    attestation_v2 = _fixture(fca.HASHED_FIELDS, schema_version=fca.SCHEMA_VERSION)
    cashflows = [_fixture(fca._FINGERPRINT_FIELDS, id=f"cf-{i}") for i in (2, 1, 3)]
    goal_decision = _fixture(grd.HASHED_FIELDS)
    capacity_eval = _fixture(rces.HASHED_FIELDS)
    assessment = _fixture(rps._INPUT_FIELDS)
    depot_body = {"snapshot_version": "DepotSnapshotV1", "mandate_id": "M-Zürich",
                  "as_of": "2026-10-31", "positions": _TRADES, "fx_evidence": {"EUR": 0.9412}}
    ledger_body = {"snapshot_version": "PensionTransferLedgerSnapshotV1", "valuation_year": 2026,
                   "currency": "CHF", "rows": [["3a", 2031, 1250000]], "sources": [], "inflows": []}
    reserve_payload = {"version": "ReserveFundingLedgerV1", "years": [2026, 2027],
                       "release_rappen": [0, 500000], "contract_hash": "ignoriert"}
    goal_json = '{"goals":[{"name":"Ruhestand Zürich","p25":0.71}]}'
    policy = SimpleNamespace(**{f: _VALUES[i % len(_VALUES)]
                                for i, f in enumerate(cma_policy._CONTENT_FIELDS)})
    components = [
        SimpleNamespace(**{f: (k if f in ("asset_key", "component") else _VALUES[i % len(_VALUES)])
                           for i, f in enumerate(cma_policy._COMPONENT_FIELDS)})
        for k in ("equities", "bonds")
    ]
    positions = [SimpleNamespace(id="pos-1", current_value_rappen=125000050,
                                 assignment="Beratungsvermögen", position_type="Depot",
                                 alloc_equities_bps=6000, alloc_bonds_bps=4000, currency="CHF")]
    context_kwargs = dict(
        engine_version="engine-v-test", policy_id="pol-1", cma_id="cma-1",
        assessment_id="ass-1", input_snapshot_hash="a" * 64,
        preferences_json='{"homeBias": "CH"}', targets={"equities": 5000, "bonds": 3000, "real_estate": 1000, "alternatives": 500, "liquidity": 500},
        sub_allocations=[{"sub_asset_class": "Aktien Schweiz", "target_weight_bps": 3000}],
        effective_constraints={"band": [0.1, 0.2], "note": "Zürich"}, optimization_seed=42,
    )

    # (Name, Produktionswert, core.evidence-Wert oder None wenn bespoke/zusammengesetzt)
    return [
        ("risk_profile_signoff.v1", rps.compute_signoff_hash(signoff_v1),
         evidence_hash(rps.signoff_payload(signoff_v1), scheme=SCHEME_V1)),
        ("risk_profile_signoff.v2", rps.compute_signoff_hash(signoff_v2),
         evidence_hash(rps.signoff_payload(signoff_v2), scheme=SCHEME_V1)),
        ("risk_profile_signoff.assessment_input", rps.assessment_input_hash(None, assessment),
         evidence_hash({**{n: assessment[n] for n in rps._INPUT_FIELDS}, "answers": []})),
        ("risk_override_decision.v1", rod.compute_decision_hash(decision_v1),
         evidence_hash(rod.decision_payload(decision_v1))),
        ("risk_override_decision.v2", rod.compute_decision_hash(decision_v2),
         evidence_hash(rod.decision_payload(decision_v2))),
        ("financial_coverage_attestation.v1", fca.compute_attestation_hash(attestation_v1),
         evidence_hash(fca.attestation_payload(attestation_v1))),
        ("financial_coverage_attestation.v2", fca.compute_attestation_hash(attestation_v2),
         evidence_hash(fca.attestation_payload(attestation_v2))),
        ("financial_coverage_attestation.cashflow_fingerprint",
         fca.fingerprint_cashflows(cashflows)[0], None),
        ("goal_revision_decision.decision", grd.compute_decision_hash(goal_decision),
         evidence_hash(grd.decision_payload(goal_decision))),
        ("risk_capacity_evaluation_snapshot", rces.compute_snapshot_hash(capacity_eval),
         evidence_hash(rces.snapshot_payload(capacity_eval))),
        ("depot_snapshot.body", depot_snapshot._sha256(depot_body),
         evidence_hash(depot_body, scheme=SCHEME_V1_ASCII)),
        ("pension_transfer_ledger_snapshot.body", ptls._sha256(ledger_body),
         evidence_hash(ledger_body, scheme=SCHEME_V1_ASCII)),
        ("portfolio_reconciliation.body", portfolio_reconciliation._sha256(depot_body),
         evidence_hash(depot_body, scheme=SCHEME_V1_ASCII)),
        ("reserve_funding_ledger.contract", reserve_funding_ledger._hash_payload(reserve_payload),
         evidence_hash({k: v for k, v in reserve_payload.items() if k != "contract_hash"},
                       scheme=SCHEME_V1_ASCII)),
        ("backtest_stress.catalog", backtest_stress.stress_catalog_hash(),
         evidence_hash(backtest_stress._SCENARIOS, scheme=SCHEME_V1_ASCII)),
        ("cma_policy.content", cma_policy.compute_content_hash(policy, components), None),
        ("portfolio_handoff.business_key", portfolio_handoff.handoff_business_key_hash(
            mandate_id="M-1", run_id="R-1", trades=_TRADES, total_value_rappen=125000050,
            recipient_name=" Bank  Zürich "),
         evidence_hash({"schema": "PortfolioHandoffBusinessKeyV1", "mandate_id": "M-1",
                        "recommendation_run_id": "R-1", "live_total_value_rappen": 125000050,
                        "recipient": "bank zürich", "trades": _TRADES},
                       scheme=SCHEME_V1_STR_DEFAULT)),
        ("portfolio_handoff.trade_snapshot", portfolio_handoff.snapshot_json_and_sha256(_TRADES)[1],
         sha256_hex(canonical_json(_TRADES, scheme=SCHEME_LEGACY_UNSORTED_UTF8))),
        ("goal_analysis_snapshot.analysis", goal_analysis_snapshot.goal_analysis_hash(goal_json),
         sha256_hex(goal_json)),
        ("allocation_context_hash.v1", pai.allocation_context_hash_for(**context_kwargs), None),
        ("allocation_context_hash.v2",
         pai.allocation_context_hash_for(**context_kwargs, analysis_result_hash="b" * 64), None),
        ("input_snapshot_hash.c8", portfolio_engine._compute_input_snapshot_hash(
            advisory_positions=positions, cashflows=[], goals=[],
            advisory_wealth_rappen=125000050, total_wealth_rappen=250000000), None),
        ("cost_disclosure.content", cost_disclosure.cost_disclosure_content_hash(
            {"total_bps": 87, "currency": "CHF", "note": "Zürich", "rows": _TRADES}),
         evidence_hash({"total_bps": 87, "currency": "CHF", "note": "Zürich", "rows": _TRADES},
                       scheme=SCHEME_LEGACY_SPACED_STR_DEFAULT)),
        ("product_eligibility.canonical", product_eligibility.canonical_hash({"rule": "Ä", "x": 1}),
         evidence_hash({"rule": "Ä", "x": 1}, scheme=SCHEME_LEGACY_SPACED_STR_DEFAULT)),
        ("fx_rates.fingerprint", fx_rates._fingerprint({"EUR": 0.9412, "src": "SNB Zürich"}),
         evidence_hash({"EUR": 0.9412, "src": "SNB Zürich"}, scheme=SCHEME_V1_ASCII_STR_DEFAULT)),
    ]


# Berechnet auf origin/develop 9e6b7dd9 (vor K-1), unveraendert einzufrieren.
GOLDEN: dict[str, str] = {
    "risk_profile_signoff.v1": "3536acbe6db84168b08aea1289c4bfb99c7683966a3b01877786201fc8a7d6c2",
    "risk_profile_signoff.v2": "fc1afe17dacaf4bccb8b67287d015bcf4c4d5da7e1665b50bb42a7b1bc8581ab",
    "risk_profile_signoff.assessment_input": "0f86c21f9ff420b130026f05e98d3d73da03a519f724dcd0350e4fb50584aa8e",
    "risk_override_decision.v1": "2c45c9a416cbdc9635610ce1cd3c687cefd82e67d4778ca1190d6761f9ade2cb",
    "risk_override_decision.v2": "1afd30be9b9e1890b8cd2322229ba3d4fca38cbf195849dcceb7a566138f3189",
    "financial_coverage_attestation.v1": "b30ae3b492a78f24b7fc9c043548efb90d83c89b2ca610e52408b9ad5e581014",
    "financial_coverage_attestation.v2": "edf062d3e5f35e1fa7955ae6971051c4410fe02cd3a379ae3c6821f65b5ae8b7",
    "financial_coverage_attestation.cashflow_fingerprint":
        "e049801bd09cd20cb4891b30e83842eaf591d467889cbb4d240e963a3ff6ca9b",
    "goal_revision_decision.decision": "30261e17b6ef2346fa4dcfe21d4ddf7a2297a576adcfe25ef1c2225e08167679",
    "risk_capacity_evaluation_snapshot": "51ac0321557707671774a1bf499a41ddc09234b5a632e0864df3c635db3a3514",
    "depot_snapshot.body": "a6d3ee3dae74f5b72eb59b2e45963e935f9ca0ca46f28eb88b5da6e44ffd9389",
    "pension_transfer_ledger_snapshot.body": "e6e5e414ea0243c88e33366a1f775e1916f4d99926ce414b4307ba873d1aa1f5",
    "portfolio_reconciliation.body": "a6d3ee3dae74f5b72eb59b2e45963e935f9ca0ca46f28eb88b5da6e44ffd9389",
    "reserve_funding_ledger.contract": "eaa960cee319faa20fc63dde34eac85f82529cb5258067dd0bf0623ac0d8083f",
    "backtest_stress.catalog": "ff21ca82810573ad467471dcdf21b3cf852d2cfeb9b403e5ec9a1172fed60e94",
    "cma_policy.content": "09869fff657d75d6c01b06ef5b914caf41ce140c261a207d8a0763c329d53525",
    "portfolio_handoff.business_key": "fe62fac39cb08ae8392256f65d7b0618dc55d343a507991526a7b6b0487c46b5",
    "portfolio_handoff.trade_snapshot": "416286c55bd359dd5c9749e52d160be1745a52927333ad0cdce493eaa0422275",
    "goal_analysis_snapshot.analysis": "a6cf0ecb0b758d012a2d354b2696046ba9dfff0b84e9da69a8f625cabbf32185",
    "allocation_context_hash.v1": "a17b7da5682f520a537a23f4d47416f783edf61677c624264b8b1dff84d1556e",
    "allocation_context_hash.v2": "44003711095e68eeb14519c1dd317065c7ae6f15eb88d999bd4e3a4c73ba3f41",
    "input_snapshot_hash.c8": "28a46e4729a590de0301758aad61a3ae342b2db83679791d6c4a3dc0aaebb6d7",
    "cost_disclosure.content": "3959a34337215af2c992eeca0629e093fdb7dd267c21dfbb9500274d06b81e9a",
    "product_eligibility.canonical": "2baadf2774d663c8fffd3ec2c79f28858470703db813becdd50a81be8f8a0ede",
    "fx_rates.fingerprint": "3a17cb901d5891be23594aa208f6498221014599b5a149482df96df39da522c0",
}


_CASES = _cases()


def test_every_case_has_a_golden_value():
    assert sorted(GOLDEN) == sorted(name for name, _, _ in _CASES)


@pytest.mark.parametrize("name,production,via_core", _CASES, ids=[c[0] for c in _CASES])
def test_golden_evidence_hash_is_unchanged(name, production, via_core):
    assert production == GOLDEN[name], f"{name}: Produktions-Hash hat sich geaendert"
    if via_core is not None:
        assert via_core == GOLDEN[name], f"{name}: core.evidence weicht vom Bestand ab"
