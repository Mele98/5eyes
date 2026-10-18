"""Kostenausweis Ex-ante (FIDLEG Art. 8/9) als Advisory-Report-Aggregator-Sektion.

Vorher: nur der PDF-Renderer populierte cost_disclosure selbst. Jetzt liegt die
Sektion im Aggregator-Payload -> alle Konsumenten (React-Reporting, API) erhalten
sie konsistent. Wrapper ist fail-closed (degraded, nie stille 0-Kosten).
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path
from unittest.mock import MagicMock

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import services.cost_disclosure as cost_disclosure  # noqa: E402
from services.advisory_report import (  # noqa: E402
    _build_cost_disclosure_section,
    _compute_advisory_report_inner,
)


def _mandate():
    m = MagicMock()
    m.id = "MX-COST"
    return m


def test_aggregator_payload_wires_cost_disclosure_section():
    """Die Sektion ist im Aggregator-Payload verdrahtet (Source-Wiring)."""
    src = inspect.getsource(_compute_advisory_report_inner)
    assert '"cost_disclosure": _build_cost_disclosure_section' in src


def test_wrapper_passes_through_service_result(monkeypatch):
    import services.advisory_report as advisory_report

    seen: dict = {}

    def _fake(db, mandate, *, target_allocation_id=None):
        seen["ta_id"] = target_allocation_id
        return {"available": True, "total_cost_bps": 120}

    # COST-RUN-RESOLVER-001: der Wrapper reicht die aktuelle TA aus dem
    # Aggregator-Cache durch (keine eigene TA-Abfrage im Kostenausweis).
    monkeypatch.setattr(
        advisory_report, "_cached_current_ta",
        lambda db, mandate: MagicMock(id="TA-CURRENT"),
    )
    monkeypatch.setattr(cost_disclosure, "build_cost_disclosure", _fake)
    result = _build_cost_disclosure_section(db=None, mandate=_mandate())
    assert result["available"] is True
    assert result["total_cost_bps"] == 120
    assert seen["ta_id"] == "TA-CURRENT"


def test_wrapper_fails_closed_on_service_error(monkeypatch):
    def _boom(db, mandate):
        raise RuntimeError("cost service kaputt")

    monkeypatch.setattr(cost_disclosure, "build_cost_disclosure", _boom)
    result = _build_cost_disclosure_section(db=None, mandate=_mandate())
    assert result["available"] is False
    assert result["audit_degraded"] is True
    # NIE stille 0-Kosten behaupten:
    assert "total_cost_bps" not in result or result.get("total_cost_bps") in (None, 0) and result["available"] is False
