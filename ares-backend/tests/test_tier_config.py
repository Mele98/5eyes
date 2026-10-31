"""Sprint T5 (2026-06-08): Tier-Configuration Auto-Derivation Tests."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.tier_config import (
    EffectiveTenancyConfig,
    get_effective_tenancy_config,
    list_compliance_requirements,
)


def _make_settings(**fields):
    """Helper: erstellt ein settings-Mock mit den gewuenschten Feldern."""
    base = {
        "deployment_tier": "tier1",
        "tenancy_mode": None,
        "tenant_admin_ui_enabled": False,
    }
    base.update(fields)
    return SimpleNamespace(**base)


# ===========================================================================
# Tier-Defaults
# ===========================================================================


def test_tier1_self_hosted_defaults():
    cfg = get_effective_tenancy_config(_make_settings(deployment_tier="tier1"))
    assert cfg.deployment_tier == "tier1"
    assert cfg.tenancy_mode == "single"
    assert cfg.tenant_admin_ui_enabled is False
    assert cfg.recommended_db_engine == "sqlite"
    assert cfg.external_backup_required is False
    assert cfg.audit_log_streaming_required is False
    assert cfg.finma_outsourcing_notification_required is False


def test_tier2_shared_cloud_defaults():
    cfg = get_effective_tenancy_config(_make_settings(deployment_tier="tier2"))
    assert cfg.deployment_tier == "tier2"
    assert cfg.tenancy_mode == "multi"
    assert cfg.tenant_admin_ui_enabled is True
    assert cfg.recommended_db_engine == "postgres"
    assert cfg.external_backup_required is True
    assert cfg.audit_log_streaming_required is True
    assert cfg.finma_outsourcing_notification_required is True


def test_tier3_dedicated_defaults():
    cfg = get_effective_tenancy_config(_make_settings(deployment_tier="tier3"))
    assert cfg.deployment_tier == "tier3"
    assert cfg.tenancy_mode == "single"  # single-tenant per Instance
    assert cfg.tenant_admin_ui_enabled is False
    assert cfg.recommended_db_engine == "postgres"
    assert cfg.external_backup_required is True
    assert cfg.audit_log_streaming_required is True


def test_unknown_tier_fallback_tier1():
    """Unbekannter Tier → Defaults tier1 (defensive)."""
    cfg = get_effective_tenancy_config(_make_settings(deployment_tier="tierXYZ"))
    assert cfg.deployment_tier == "tier1"


# ===========================================================================
# User-Overrides
# ===========================================================================


def test_tier1_mit_explizit_multi_tenancy_override():
    """Tier 1 + User setzt tenancy_mode='multi' → respektiert."""
    cfg = get_effective_tenancy_config(_make_settings(
        deployment_tier="tier1", tenancy_mode="multi",
    ))
    assert cfg.tenancy_mode == "multi"


def test_tier1_mit_explizit_admin_ui_true():
    """Tier 1 + User aktiviert Admin-UI (z.B. Migration zu Tier 2)."""
    cfg = get_effective_tenancy_config(_make_settings(
        deployment_tier="tier1", tenant_admin_ui_enabled=True,
    ))
    assert cfg.tenant_admin_ui_enabled is True


def test_tier2_default_admin_ui_true():
    """Tier 2 default: admin_ui ist True (auch ohne explizit gesetzt)."""
    cfg = get_effective_tenancy_config(_make_settings(deployment_tier="tier2"))
    assert cfg.tenant_admin_ui_enabled is True


# ===========================================================================
# Compliance-Requirements-Liste
# ===========================================================================


def test_compliance_requirements_tier1_minimal():
    cfg = get_effective_tenancy_config(_make_settings(deployment_tier="tier1"))
    items = list_compliance_requirements(cfg)
    # Tier 1 hat nur Self-Hosted-Hinweis
    assert any("Self-Hosted" in i for i in items)
    assert not any("FINMA-Outsourcing" in i for i in items)


def test_compliance_requirements_tier2_finma_pflicht():
    cfg = get_effective_tenancy_config(_make_settings(deployment_tier="tier2"))
    items = list_compliance_requirements(cfg)
    assert any("FINMA-Outsourcing" in i for i in items)
    assert any("AVV" in i for i in items)
    assert any("Audit-Log-Streaming" in i for i in items)


def test_compliance_requirements_tier3_premium():
    cfg = get_effective_tenancy_config(_make_settings(deployment_tier="tier3"))
    items = list_compliance_requirements(cfg)
    assert any("FINMA-Outsourcing" in i for i in items)
    assert any("Audit-Log-Streaming" in i for i in items)


# ===========================================================================
# Dataclass-Eigenschaften
# ===========================================================================


def test_effective_config_ist_immutable():
    """EffectiveTenancyConfig ist frozen=True → keine Mutation."""
    cfg = get_effective_tenancy_config(_make_settings(deployment_tier="tier1"))
    import pytest
    with pytest.raises((AttributeError, Exception)):
        cfg.deployment_tier = "tier2"  # type: ignore
