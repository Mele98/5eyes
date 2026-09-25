"""Sprint U-21 (Roadmap-Punkt 21, 2026-06-03): Liquidity-Cascade-Warning Audit.

Pre-U-21
--------
portfolio_engine eskaliert SAA-Liquiditaet 2-stufig (Hard-Cap 3% ->
Emergency 10%) + Reasoning-Trail-Eintrag + generische WARN_FALLBACK.
Keine strukturierte UI-Sichtbarkeit ob ein Mandate in Stage 3 ist.

Post-U-21
---------
- services/liquidity_cascade_audit.py: classify_liquidity_stage +
  audit_mandate_liquidity_cascade
- Aggregator-Sektion 23 liquidity_cascade
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.liquidity_cascade_audit import (  # noqa: E402
    LIQUIDITY_EMERGENCY_CAP_BPS,
    LIQUIDITY_HARD_CAP_BPS,
    STAGE_EMERGENCY,
    STAGE_HARD_CAP,
    STAGE_LABELS,
    STAGE_NORMAL,
    STAGE_UNKNOWN,
    _extract_liquidity_bps,
    audit_mandate_liquidity_cascade,
    classify_liquidity_stage,
)


def _mandate(mid="MX-TEST"):
    m = MagicMock()
    m.id = mid
    return m


def _ta(**overrides):
    base = {
        "is_current": 1,
        "deleted_at": None,
        "liquidity_target_bps": None,
        "liquidity_bps": None,
        "target_liquidity_bps": None,
        "targets_json": None,
    }
    base.update(overrides)
    return MagicMock(spec=list(base.keys()), **base)


def _stub_db(active_ta):
    db = MagicMock()
    chain = MagicMock()
    chain.filter.return_value = chain
    chain.first.return_value = active_ta
    db.query.return_value = chain
    return db


# ---------------------------------------------------------------------------
# Konstanten Drift-Schutz
# ---------------------------------------------------------------------------

def test_hard_cap_matches_engine_value():
    """portfolio_engine._SAA_LIQUIDITY_HARD_CAP_BPS = 300 — drift-test."""
    assert LIQUIDITY_HARD_CAP_BPS == 300


def test_emergency_cap_matches_engine_value():
    assert LIQUIDITY_EMERGENCY_CAP_BPS == 1000


def test_engine_constants_synced():
    """Source-Parse portfolio_engine.py — wenn jemand die Engine-
    Werte aendert, MUSS der Audit-Service mitgehen."""
    engine_src = (BACKEND_ROOT / "services" / "portfolio_engine.py").read_text(
        encoding="utf-8",
    )
    assert "_SAA_LIQUIDITY_HARD_CAP_BPS: int = 300" in engine_src
    assert "_SAA_LIQUIDITY_EMERGENCY_CAP_BPS: int = 1000" in engine_src


def test_stage_labels_cover_all_stages():
    """Drift-Schutz: jeder Stage-Code hat einen Berater-Text."""
    for stage in (STAGE_NORMAL, STAGE_HARD_CAP, STAGE_EMERGENCY, STAGE_UNKNOWN):
        assert stage in STAGE_LABELS
        assert len(STAGE_LABELS[stage]) > 20


# ---------------------------------------------------------------------------
# classify_liquidity_stage
# ---------------------------------------------------------------------------

def test_classify_normal_at_zero():
    assert classify_liquidity_stage(0) == STAGE_NORMAL


def test_classify_normal_below_hard_cap():
    assert classify_liquidity_stage(200) == STAGE_NORMAL


def test_classify_normal_just_below_hard_cap_boundary():
    """299 bps = knapp unter dem Hard-Cap -> normal (nicht eskaliert)."""
    assert classify_liquidity_stage(299) == STAGE_NORMAL


def test_classify_hard_cap_at_exact_boundary():
    """LIQUIDITY-CASCADE-HARD-CAP-DEAD-BRANCH-001 (Kontrollrunde 2026-09-25):
    300 bps = exakt am Soll-Hard-Cap gedeckelt (Stage-2-Eskalation griff,
    aber NICHT bis in den Emergency-Bereich getrieben) -> STAGE_HARD_CAP,
    nicht STAGE_NORMAL. Vorher war STAGE_HARD_CAP unerreichbar (toter
    Zweig); dieser exakte Grenzwert war faelschlich als STAGE_NORMAL
    (keine Pflicht-Warnung) statt STAGE_EMERGENCY (Pflicht-Warnung)
    eingeordnet -- fachlich mit dem Auftraggeber als korrekte, minimal-
    invasive Grenze abgestimmt."""
    assert classify_liquidity_stage(300) == STAGE_HARD_CAP


def test_classify_emergency_above_hard_cap():
    """Eine Einheit ueber dem exakten Hard-Cap -> Emergency-Stage
    (unveraendert -- nur der exakte Grenzwert 300 selbst wechselte von
    STAGE_NORMAL zu STAGE_HARD_CAP, siehe test_classify_hard_cap_at_exact_boundary)."""
    assert classify_liquidity_stage(301) == STAGE_EMERGENCY


def test_classify_emergency_at_emergency_boundary():
    """1000 bps = 10% genau am Emergency-Cap -> immer noch emergency."""
    assert classify_liquidity_stage(1000) == STAGE_EMERGENCY


def test_classify_emergency_above_emergency_cap():
    """Ueber 10% -> defensiv weiter als emergency markiert."""
    assert classify_liquidity_stage(2000) == STAGE_EMERGENCY


def test_classify_unknown_for_none():
    assert classify_liquidity_stage(None) == STAGE_UNKNOWN


def test_classify_unknown_for_invalid_string():
    assert classify_liquidity_stage("not a number") == STAGE_UNKNOWN  # type: ignore[arg-type]


def test_classify_custom_thresholds():
    """Custom hard_cap_bps fuer striktere Audit-Mode."""
    assert classify_liquidity_stage(250, hard_cap_bps=200) == STAGE_EMERGENCY


# ---------------------------------------------------------------------------
# _extract_liquidity_bps
# ---------------------------------------------------------------------------

def test_extract_direct_field_liquidity_target_bps():
    ta = _ta(liquidity_target_bps=300)
    assert _extract_liquidity_bps(ta) == 300


def test_extract_falls_back_to_targets_json():
    ta = _ta(targets_json='{"liquidity": 500, "equities": 6000}')
    assert _extract_liquidity_bps(ta) == 500


def test_extract_returns_none_when_no_data():
    ta = _ta()
    assert _extract_liquidity_bps(ta) is None


def test_extract_handles_invalid_targets_json():
    ta = _ta(targets_json="not json")
    assert _extract_liquidity_bps(ta) is None


# ---------------------------------------------------------------------------
# audit_mandate_liquidity_cascade — Szenarien
# ---------------------------------------------------------------------------

def test_audit_no_active_ta_returns_unknown():
    db = _stub_db(None)
    result = audit_mandate_liquidity_cascade(db, _mandate())
    assert result["stage"] == STAGE_UNKNOWN
    assert result["warning_required"] is False
    assert result["liquidity_bps"] is None


def test_audit_normal_liquidity_no_warning():
    db = _stub_db(_ta(liquidity_target_bps=200))
    result = audit_mandate_liquidity_cascade(db, _mandate())
    assert result["stage"] == STAGE_NORMAL
    assert result["warning_required"] is False
    assert result["beratungsgespraech_pruefen"] is False
    assert result["over_hard_cap_by_bps"] is None


def test_audit_emergency_stage_triggers_warning():
    """Liquidity 800 bps (8%) -> stage emergency, warning_required, action_required."""
    db = _stub_db(_ta(liquidity_target_bps=800))
    result = audit_mandate_liquidity_cascade(db, _mandate())
    assert result["stage"] == STAGE_EMERGENCY
    assert result["warning_required"] is True
    assert result["beratungsgespraech_pruefen"] is True
    assert result["over_hard_cap_by_bps"] == 500  # 800 - 300


def test_audit_hard_cap_stage_does_not_trigger_mandatory_warning():
    """LIQUIDITY-CASCADE-HARD-CAP-DEAD-BRANCH-001: exakt am Hard-Cap (300
    bps) gedeckelt -> STAGE_HARD_CAP, KEINE Pflicht-Warnung (nur
    STAGE_EMERGENCY loest warning_required/beratungsgespraech_pruefen
    aus). Vorher wurde dieser exakte Grenzwert faelschlich als
    STAGE_EMERGENCY mit Pflicht-Warnung gemeldet."""
    db = _stub_db(_ta(liquidity_target_bps=300))
    result = audit_mandate_liquidity_cascade(db, _mandate())
    assert result["stage"] == STAGE_HARD_CAP
    assert result["warning_required"] is False
    assert result["beratungsgespraech_pruefen"] is False
    assert result["over_hard_cap_by_bps"] is None


def test_audit_exposes_correct_caps():
    db = _stub_db(_ta(liquidity_target_bps=200))
    result = audit_mandate_liquidity_cascade(db, _mandate())
    assert result["hard_cap_bps"] == 300
    assert result["emergency_cap_bps"] == 1000


def test_audit_fidleg_basis_stable():
    db = _stub_db(_ta(liquidity_target_bps=200))
    result = audit_mandate_liquidity_cascade(db, _mandate())
    assert result["fidleg_basis"] == "Art. 11 / Art. 13 FIDLEG"


def test_audit_db_error_returns_unknown_degraded():
    """Mega-Audit (2026-08-04): audit_degraded unterscheidet jetzt explizit
    einen echten Query-Fehler von "noch keine Allokation vorhanden" (beide
    zeigten vorher identisch stage=unknown, ohne diese Unterscheidung)."""
    db = MagicMock()
    db.query.side_effect = RuntimeError("table missing")
    result = audit_mandate_liquidity_cascade(db, _mandate())
    assert result["stage"] == STAGE_UNKNOWN
    assert result["warning_required"] is False
    assert result["audit_degraded"] is True


def test_audit_db_error_is_logged_with_mandate_id(caplog):
    """AUDIT-SILENT-DEGRADED-LOGGING-001 (Kontrollrunde 2026-09-25): vorher
    lief der degraded-Pfad komplett ohne Log-Eintrag."""
    import logging

    db = MagicMock()
    db.query.side_effect = RuntimeError("table missing")
    with caplog.at_level(logging.WARNING, logger="services.liquidity_cascade_audit"):
        audit_mandate_liquidity_cascade(db, _mandate(mid="MX-LOG-TEST"))
    assert any(
        "MX-LOG-TEST" in record.getMessage() and "table missing" in record.getMessage()
        for record in caplog.records
    )


# ---------------------------------------------------------------------------
# Aggregator-Integration (Sektion 23)
# ---------------------------------------------------------------------------

def test_compute_advisory_report_includes_section_23():
    # Seit PR #110 liegt die Sektions-Verdrahtung in _compute_advisory_report_inner.
    from services.advisory_report import _compute_advisory_report_inner
    import inspect
    source = inspect.getsource(_compute_advisory_report_inner)
    assert "liquidity_cascade" in source
    assert "Sektion 23" in source


def test_build_liquidity_cascade_degraded_on_error():
    from services.advisory_report import _build_liquidity_cascade
    db = MagicMock()
    db.query.side_effect = RuntimeError("simulated")
    result = _build_liquidity_cascade(db, _mandate())
    assert result["stage"] == "unknown"
    assert result["warning_required"] is False
    assert result["audit_degraded"] is True
