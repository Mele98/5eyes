"""DEPOT-E2E-SNAPSHOT-001 (P1, open).

Audit: docs/audits/2026-10-05-depotcheck-end-to-end-product-identity-and-
publication-integrity-audit.md (Ares worktree:
"5eyes wird zu Ares"/asset-allocation-stochastic-core).

Finding: there is no single, shared, immutable snapshot artifact binding
together holdings valuation, TargetAllocation, recommendation run, cost
snapshot, benchmark definition and stress catalog for a given depot-check.
The JSON API (``services/depot_check.py::compute_depot_check``) and the PDF
builder (``routers/pdf_reports.py::_build_depotcheck_data``, which internally
calls ``compute_depot_check`` again plus ``compute_stress_replays``,
``build_cost_disclosure`` and ``_build_portfolio_data``) each independently
re-query/re-resolve the current state. Neither payload carries a shared
``snapshot_id``, ``as_of``, ``holdings_hash``, ``allocation_id``, ``run_id``,
``benchmark_definition_id`` or ``stress_catalog_id`` that both sides could
compare to prove they describe the same underlying state.

This test proves the gap structurally: it seeds one realistic mandate (the
Foundation example case -- the same fixture
``tests/test_asset_allocation_reference_integrity_edges.py`` uses to drive
``_build_anlagestrategie_data``/``_build_depotcheck_data``, since the minimal
engine-only fixtures in ``tests/test_depot_check.py`` do not satisfy the
decision-anchor requirements of the full PDF-building pipeline), then calls
BOTH the real JSON depot-check function and the real PDF payload-building
function for that same mandate/session, and asserts they share at least one
matching identity/version/hash field. Today they do not share any -- confirmed
by inspecting the actual dict keys of ``compute_depot_check``'s return value
and the actual dataclass fields of ``services.pdf.base.DepotCheckData`` -- so
this is marked ``xfail(strict=True)`` until DEPOT-E2E-SNAPSHOT-001 is fixed
(a ``DepotCheckAnalysisSnapshot`` model binding all these sources with a
content hash -- deferred pending explicit design/product sign-off).
"""
from __future__ import annotations

import sys
from dataclasses import fields
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from routers.pdf_reports import _build_depotcheck_data
from services.depot_check import compute_depot_check
from tests.test_portfolio_generate_after_saa_recalc import (  # noqa: F401
    _seed_foundation,
    session_factory,
)

# Candidate identity/version/hash fields named by the audit
# (DEPOT-E2E-SNAPSHOT-001) as the kind of field that *would* let a caller
# prove the JSON depot-check response and the depot-check PDF describe the
# exact same underlying state.
_IDENTITY_FIELD_CANDIDATES = (
    "snapshot_id",
    "as_of",
    "holdings_hash",
    "allocation_id",
    "run_id",
    "benchmark_definition_id",
    "stress_catalog_id",
)


@pytest.mark.xfail(
    strict=True,
    reason=(
        "DEPOT-E2E-SNAPSHOT-001: compute_depot_check() (the JSON depot-check "
        "payload) and _build_depotcheck_data() (the depot-check PDF payload, "
        "services.pdf.base.DepotCheckData) carry no shared snapshot_id/"
        "as_of/holdings_hash/allocation_id/run_id/benchmark_definition_id/"
        "stress_catalog_id at all -- there is no field in either payload "
        "that could prove the two describe the same underlying state. Real "
        "fix is a dedicated DepotCheckAnalysisSnapshot model, deferred "
        "pending design/product sign-off."
    ),
)
def test_json_depot_check_and_pdf_payload_share_no_snapshot_identity(session_factory):
    """Both the JSON API and the PDF builder independently re-derive the
    depot-check from the mandate's current DB state, but neither payload
    exposes an identity/version/hash field the other side could match
    against -- so nothing lets a caller prove, after the fact, that a JSON
    response and a PDF the client later received describe one consistent
    snapshot (same holdings valuation, same TargetAllocation, same
    recommendation run, same cost snapshot, same benchmark definition, same
    stress catalog)."""
    with session_factory() as session:
        mandate = _seed_foundation(session)

        # The real JSON-producing function, exactly as routers/allocation.py's
        # GET /mandates/{mandate_id}/depot-check endpoint returns it today
        # (``return compute_depot_check(db, mandate)`` with no further
        # wrapping -- see routers/allocation.py around line 713).
        json_payload = compute_depot_check(session, mandate)

        # The real PDF payload-building function, exactly as
        # routers/pdf_reports.py's GET
        # /mandates/{mandate_id}/reports/depotcheck.pdf endpoint builds it
        # today (``data = _build_depotcheck_data(mandate, db)`` -- see
        # routers/pdf_reports.py around line 1838). It internally calls
        # compute_depot_check() a SECOND, independent time (plus
        # compute_stress_replays, build_cost_disclosure, _build_portfolio_data
        # and _build_anlagestrategie_data), rather than reusing json_payload.
        pdf_payload = _build_depotcheck_data(mandate, session)

        assert isinstance(json_payload, dict)
        json_keys = set(json_payload.keys())
        pdf_field_names = {f.name for f in fields(pdf_payload)}

        # Confirm, concretely, what the two payloads actually carry today --
        # this is the inspection the audit asked for, not an assumption.
        json_identity_values = {
            key: json_payload[key]
            for key in _IDENTITY_FIELD_CANDIDATES
            if key in json_payload
        }
        pdf_identity_values = {
            key: getattr(pdf_payload, key)
            for key in _IDENTITY_FIELD_CANDIDATES
            if key in pdf_field_names
        }

        matching_shared_identity_fields = {
            key
            for key in json_identity_values.keys() & pdf_identity_values.keys()
            if json_identity_values[key] == pdf_identity_values[key]
        }

        assert matching_shared_identity_fields, (
            "Expected the JSON depot-check payload and the PDF depot-check "
            "payload to share at least one matching identity/version/hash "
            "field (snapshot_id/as_of/holdings_hash/allocation_id/run_id/"
            "benchmark_definition_id/stress_catalog_id) proving they "
            "describe the same underlying state. Found none.\n"
            f"Candidate identity fields present in JSON payload: "
            f"{sorted(json_identity_values)}\n"
            f"Candidate identity fields present in PDF payload: "
            f"{sorted(pdf_identity_values)}\n"
            f"Full JSON depot-check payload keys: {sorted(json_keys)}\n"
            f"Full PDF DepotCheckData field names: {sorted(pdf_field_names)}"
        )
