"""Sprint C2 (2026-06-07): IS-Status sichtbar im PDF-Audit-Block.

Verifiziert dass _engine_configuration_block korrekt rendert wenn der
Aggregator-Payload einen 'engine_configuration'-Key enthaelt. Damit kann
FINMA/Codex/Berater auf einen Blick sehen mit welchen Engine-Einstellungen
das Mandat berechnet wurde.
"""
from __future__ import annotations

import pytest
from reportlab.platypus import Paragraph, Table

from services.pdf.components.advisory_palette import make_advisory_styles
from services.pdf.components.compliance_audit import (
    _engine_configuration_block,
    render_compliance_audit_section,
)


@pytest.fixture
def styles():
    return make_advisory_styles()


# ===========================================================================
# Backwards-Compat: Ohne engine_configuration → kein Block
# ===========================================================================


def test_c2_backwards_compat_payload_ohne_engine_cfg_kein_block(styles):
    """Wenn payload.engine_configuration fehlt: nur die 5 Standard-Bloecke."""
    payload = {
        "suitability_compliance": {}, "methodology_models": {},
        "recommendation_methodology": {}, "mandate_lock_status": {},
        "liquidity_cascade": {},
        # KEIN engine_configuration
    }
    story: list = []
    render_compliance_audit_section(payload, story, styles)
    # Story ist nicht leer (Standard-Sektionen drin)
    assert len(story) > 0


def test_c2_payload_mit_engine_cfg_appended_block(styles):
    """Wenn engine_configuration vorhanden: zusaetzlicher 6. Block."""
    payload_basic = {
        "suitability_compliance": {}, "methodology_models": {},
        "recommendation_methodology": {}, "mandate_lock_status": {},
        "liquidity_cascade": {},
    }
    payload_with = dict(payload_basic)
    payload_with["engine_configuration"] = {
        "importance_sampling_active": True,
        "importance_sampling_reason": "konservatives Risikoprofil",
        "tax_mode": "binned",
        "sub_allocation_aware": True,
        "optimizer_mode": "stochastic",
    }
    story_basic: list = []
    story_with: list = []
    render_compliance_audit_section(payload_basic, story_basic, styles)
    render_compliance_audit_section(payload_with, story_with, styles)
    # Mit cfg hat mehr Elemente in der story
    assert len(story_with) > len(story_basic)


# ===========================================================================
# Block-Inhalt
# ===========================================================================


def test_c2_engine_cfg_block_zeigt_is_aktiv(styles):
    """IS aktiv → 'aktiv' im Block."""
    flowables = _engine_configuration_block({
        "importance_sampling_active": True,
        "importance_sampling_reason": "hart-Goal",
        "tax_mode": "median",
        "sub_allocation_aware": False,
    }, styles)
    # flowables ist eine Liste mit panel-element
    assert len(flowables) >= 1


def test_c2_engine_cfg_block_zeigt_is_inaktiv(styles):
    """IS inaktiv → 'inaktiv' im Block, kein muted_note."""
    flowables = _engine_configuration_block({
        "importance_sampling_active": False,
        "tax_mode": "median",
        "sub_allocation_aware": False,
    }, styles)
    assert len(flowables) >= 1


def test_c2_engine_cfg_block_alle_modi_kein_crash(styles):
    """Verschiedene Engine-Modi rendern ohne Crash."""
    for tax_mode in ("median", "binned", "per_path"):
        for is_active in (True, False):
            for sub_aware in (True, False):
                flowables = _engine_configuration_block({
                    "importance_sampling_active": is_active,
                    "importance_sampling_reason": "test",
                    "tax_mode": tax_mode,
                    "sub_allocation_aware": sub_aware,
                    "optimizer_mode": "stochastic",
                }, styles)
                assert flowables is not None
                assert len(flowables) >= 1


def test_c2_engine_cfg_block_leeres_dict_funktioniert(styles):
    """Leeres engine_configuration-Dict rendert ohne Crash."""
    flowables = _engine_configuration_block({}, styles)
    assert flowables is not None


def test_c2_engine_cfg_block_partial_data_funktioniert(styles):
    """Nur ein Feld gesetzt → Defaults fuer alle anderen, kein Crash."""
    flowables = _engine_configuration_block({
        "importance_sampling_active": True,
        # Alle anderen Felder fehlen
    }, styles)
    assert flowables is not None


# ===========================================================================
# Integration mit render_compliance_audit_section
# ===========================================================================


def test_c2_full_compliance_audit_mit_engine_cfg(styles):
    """End-to-End: render_compliance_audit_section mit engine_configuration."""
    payload = {
        "suitability_compliance": {"is_compliant": True, "total_advisory_logs": 5},
        "methodology_models": {"models": [{"name": "MC"}], "active_count": 1},
        "recommendation_methodology": {},
        "mandate_lock_status": {"is_editable": True},
        "liquidity_cascade": {"stage": "normal", "warning_required": False},
        "engine_configuration": {
            "importance_sampling_active": True,
            "importance_sampling_reason": "konservativ + hart-Goal",
            "tax_mode": "binned",
            "sub_allocation_aware": True,
            "optimizer_mode": "stochastic",
        },
    }
    story: list = []
    render_compliance_audit_section(payload, story, styles)
    # Mind. 10 Elemente (Header + 5 Standard-Bloecke + Spacer + Engine-Block)
    assert len(story) >= 10
