from __future__ import annotations

import io
import sys
from copy import deepcopy
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.pdf.documents.advisory_report import (  # noqa: E402
    render_advisory_report_pdf_from_payload,
)
from tests.test_advisory_report_pdf import _make_minimal_payload  # noqa: E402


def _extract_text(pdf_bytes: bytes) -> str:
    pypdf = pytest.importorskip("pypdf")
    reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
    return "\n".join((page.extract_text() or "") for page in reader.pages)


def _render_text(payload: dict) -> str:
    return _extract_text(render_advisory_report_pdf_from_payload(payload))


def test_compliance_audit_minimal_payload_renders_degraded_defaults():
    payload = _make_minimal_payload()
    for key in (
        "suitability_compliance",
        "methodology_models",
        "recommendation_methodology",
        "mandate_lock_status",
        "liquidity_cascade",
    ):
        payload.pop(key, None)

    text = _render_text(payload)

    assert "Compliance-Audit" in text
    assert "Geeignetheitspruefung" in text
    assert "Methodology-Modelle" in text
    assert "Daten ausstehend" in text


def test_compliance_audit_suitability_violation_is_visible():
    payload = _make_minimal_payload()
    payload["suitability_compliance"] = {
        "total_advisory_logs": 3,
        "logs_requiring_suitability": 2,
        "logs_with_suitability": 1,
        "logs_without_suitability": [{
            "id": "log-missing-1",
            "duty_type": "advisory_individual",
            "reason": "no_suitability_check_linked",
        }],
        "freshness_issues": [],
        "result_issues": [],
        "is_compliant": False,
        "fidleg_basis": "Art. 11/13/16 FIDLEG",
    }

    text = _render_text(payload)

    assert "Geeignetheitspruefung" in text
    assert "rot" in text
    assert "log-missing-1" in text
    assert "no_suitability_check_linked" in text


def test_compliance_audit_methodology_models_show_model_names():
    payload = _make_minimal_payload()
    payload["methodology_models"] = {
        "cma_id": "cma-1",
        "cma_version": 4,
        "active_count": 2,
        "models": [
            {
                "model_key": "nelson_siegel",
                "label": "Nelson-Siegel Yield-Curve (Bonds)",
                "active": True,
                "basis": "Bonds-Returns aus der Yield-Curve.",
            },
            {
                "model_key": "kgv_mean_reversion",
                "label": "KGV-Mean-Reversion (Equity)",
                "active": True,
                "basis": "Aktien-Returns mit zyklischem Adjustment.",
            },
        ],
        "methodology_notes": ["Bond-Renditen aus Yield-Curve."],
    }

    text = _render_text(payload)

    assert "Methodology-Modelle" in text
    assert "Nelson-Siegel" in text
    assert "KGV-Mean-Reversion" in text


def test_compliance_audit_mandate_lock_reasons_are_visible():
    payload = _make_minimal_payload()
    payload["mandate_lock_status"] = {
        "is_editable": False,
        "lock_reasons": ["risk_budget_violated"],
        "lock_reason_labels": {
            "risk_budget_violated": "Risky-Allokation verletzt das konfigurierte Risk-Budget.",
        },
        "mandate_status": "Aktiv",
        "latest_optimizer_status": "diverged_infeasible",
        "fidleg_basis": "Art. 16 / Art. 11 FIDLEG",
    }

    text = _render_text(payload)

    assert "Mandate-Lock-Status" in text
    assert "Read-only" in text
    assert "Risky-Allokation verletzt" in text


def test_compliance_audit_liquidity_emergency_warning_is_highlighted():
    payload = _make_minimal_payload()
    payload["liquidity_cascade"] = {
        "stage": "emergency",
        "stage_label": "Liquiditaet ueber dem Soll-Hard-Cap im Emergency-Bereich.",
        "liquidity_bps": 900,
        "hard_cap_bps": 300,
        "emergency_cap_bps": 1000,
        "over_hard_cap_by_bps": 600,
        "warning_required": True,
        "beratungsgespraech_pruefen": True,
        "fidleg_basis": "Art. 11 / Art. 13 FIDLEG",
    }

    text = _render_text(payload)

    assert "Liquidity-Cascade" in text
    assert "emergency" in text
    assert "Liquidity-Cascade-Warnung" in text
    assert "Emergency-Stage" in text


def test_compliance_audit_changes_pdf_bytes_against_without_section(monkeypatch):
    import services.pdf.documents.advisory_report as advisory_pdf

    payload = _make_minimal_payload()
    with_section = render_advisory_report_pdf_from_payload(payload)

    original = advisory_pdf.render_compliance_audit_section

    def no_op(_payload, _story, _styles):
        return None

    monkeypatch.setattr(advisory_pdf, "render_compliance_audit_section", no_op)
    without_section = advisory_pdf.render_advisory_report_pdf_from_payload(deepcopy(payload))

    assert original is not no_op
    assert len(with_section) > len(without_section)
    assert "Compliance-Audit" in _extract_text(with_section)
    assert "Compliance-Audit" not in _extract_text(without_section)


# ---------------------------------------------------------------------------
# Fail-closed (2026-07-18): ein fehlgeschlagenes Compliance-Audit darf NIE
# 'compliant' behaupten. Builder liefern is_compliant=None + audit_degraded,
# der Renderer zeigt 'Pruefung nicht moeglich' (amber) statt gruen.
# ---------------------------------------------------------------------------

def test_suitability_builder_fails_closed_on_audit_exception(monkeypatch):
    """Wenn audit_mandate_suitability wirft, darf der Builder NICHT
    is_compliant=True zurueckgeben (frueherer Fail-open-Bug)."""
    import services.suitability_audit as sa
    from services.advisory_report import _build_suitability_compliance

    def _boom(_db, _mandate):
        raise RuntimeError("audit kaputt")

    monkeypatch.setattr(sa, "audit_mandate_suitability", _boom)
    result = _build_suitability_compliance(db=None, mandate=None)

    assert result["is_compliant"] is None, "Fail-open: behauptet faelschlich Konformitaet"
    assert result["audit_degraded"] is True


def test_recommendation_builder_fails_closed_on_audit_exception(monkeypatch):
    import services.recommendation_audit as ra
    from services.advisory_report import _build_recommendation_methodology

    def _boom(_db, _mandate):
        raise RuntimeError("audit kaputt")

    monkeypatch.setattr(ra, "audit_recommendation_methodology", _boom)
    result = _build_recommendation_methodology(db=None, mandate=None)

    assert result["is_compliant"] is None
    assert result["audit_degraded"] is True


def test_degraded_suitability_renders_pruefung_nicht_moeglich():
    """Renderer: degraded Suitability-Payload -> sichtbarer Fail-closed-Hinweis,
    nicht stilles Gruen."""
    payload = _make_minimal_payload()
    payload["suitability_compliance"] = {
        "total_advisory_logs": 0,
        "logs_requiring_suitability": 0,
        "logs_with_suitability": 0,
        "logs_without_suitability": [],
        "freshness_issues": [],
        "result_issues": [],
        "is_compliant": None,
        "audit_degraded": True,
        "fidleg_basis": "Art. 11/13/16 FIDLEG",
    }
    text = _render_text(payload)
    assert "Pruefung nicht moeglich" in text


def test_mandate_lock_builder_fails_closed_on_audit_exception(monkeypatch):
    """Mega-Audit (2026-08-04): analog Commit 23585cf, jetzt auch fuer
    Mandate-Lock-Status. Vorher: is_editable=True bei jedem Audit-Fehler."""
    import services.mandate_lock_audit as mla
    from services.advisory_report import _build_mandate_lock_status

    def _boom(_db, _mandate):
        raise RuntimeError("audit kaputt")

    monkeypatch.setattr(mla, "audit_mandate_editability", _boom)
    result = _build_mandate_lock_status(db=None, mandate=None)

    assert result["is_editable"] is None, "Fail-open: behauptet faelschlich editierbar"
    assert result["audit_degraded"] is True


def test_liquidity_cascade_builder_fails_closed_on_audit_exception(monkeypatch):
    import services.liquidity_cascade_audit as lca
    from services.advisory_report import _build_liquidity_cascade

    def _boom(_db, _mandate):
        raise RuntimeError("audit kaputt")

    monkeypatch.setattr(lca, "audit_mandate_liquidity_cascade", _boom)
    result = _build_liquidity_cascade(db=None, mandate=None)

    assert result["stage"] == "unknown"
    assert result["audit_degraded"] is True


def test_degraded_mandate_lock_renders_pruefung_nicht_moeglich():
    payload = _make_minimal_payload()
    payload["mandate_lock_status"] = {
        "is_editable": None,
        "lock_reasons": [],
        "lock_reason_labels": {},
        "mandate_status": None,
        "latest_optimizer_status": None,
        "audit_degraded": True,
        "fidleg_basis": "Art. 16 / Art. 11 FIDLEG",
    }
    text = _render_text(payload)
    assert "Pruefung nicht moeglich" in text


def test_editable_mandate_lock_does_not_show_degraded_hint():
    """Gegenprobe: ein sauberes, editierbares Payload zeigt den Fail-closed-
    Hinweis NICHT."""
    payload = _make_minimal_payload()
    payload["mandate_lock_status"] = {
        "is_editable": True,
        "lock_reasons": [],
        "lock_reason_labels": {},
        "mandate_status": "Aktiv",
        "latest_optimizer_status": "converged",
        "fidleg_basis": "Art. 16 / Art. 11 FIDLEG",
    }
    text = _render_text(payload)
    assert "Pruefung nicht moeglich" not in text


def test_degraded_liquidity_cascade_renders_pruefung_nicht_moeglich():
    payload = _make_minimal_payload()
    payload["liquidity_cascade"] = {
        "stage": "unknown",
        "stage_label": "Liquidity-Cascade-Stage kann nicht bestimmt werden.",
        "liquidity_bps": None,
        "hard_cap_bps": 300,
        "emergency_cap_bps": 1000,
        "over_hard_cap_by_bps": None,
        "warning_required": False,
        "beratungsgespraech_pruefen": False,
        "audit_degraded": True,
        "fidleg_basis": "Art. 11 / Art. 13 FIDLEG",
    }
    text = _render_text(payload)
    assert "Pruefung nicht moeglich" in text


def test_normal_liquidity_cascade_does_not_show_degraded_hint():
    """Gegenprobe: eine echte 'noch keine Allokation'-Situation (kein
    audit_degraded) zeigt den Fail-closed-Hinweis NICHT."""
    payload = _make_minimal_payload()
    payload["liquidity_cascade"] = {
        "stage": "unknown",
        "stage_label": "Liquidity-Cascade-Stage kann nicht bestimmt werden.",
        "liquidity_bps": None,
        "hard_cap_bps": 300,
        "emergency_cap_bps": 1000,
        "over_hard_cap_by_bps": None,
        "warning_required": False,
        "beratungsgespraech_pruefen": False,
        "fidleg_basis": "Art. 11 / Art. 13 FIDLEG",
    }
    text = _render_text(payload)
    assert "Pruefung nicht moeglich" not in text


def test_compliant_suitability_does_not_show_degraded_hint():
    """Gegenprobe: ein sauberes, konformes Payload zeigt den Fail-closed-
    Hinweis NICHT (sonst wuerde der Test oben nichts beweisen)."""
    payload = _make_minimal_payload()
    payload["suitability_compliance"] = {
        "total_advisory_logs": 2,
        "logs_requiring_suitability": 2,
        "logs_with_suitability": 2,
        "logs_without_suitability": [],
        "freshness_issues": [],
        "result_issues": [],
        "is_compliant": True,
        "fidleg_basis": "Art. 11/13/16 FIDLEG",
    }
    text = _render_text(payload)
    assert "Pruefung nicht moeglich" not in text
