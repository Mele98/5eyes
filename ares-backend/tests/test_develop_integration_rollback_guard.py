"""DEVELOP-INTEGRATION-ROLLBACK-001: release-tree regression guard.

Adopted from the audit reproducer (2026-10-23) as a regular test without
xfail. The checks are static and read-only: artifacts and integration symbols
that were already merged must not disappear again through a stale or
conflict-resolved integration tree.

Directories are located by structure, not by name, so the guard survives a
later rename of the backend or frontend directory:
* backend  = the directory containing ``main.py`` and ``database.py``
* frontend = the sibling directory containing ``frontend/reporting``
"""
from __future__ import annotations

from pathlib import Path


def _backend_root() -> Path:
    for candidate in Path(__file__).resolve().parents:
        if (candidate / "main.py").is_file() and (candidate / "database.py").is_file():
            return candidate
    raise AssertionError("backend directory (main.py + database.py) not found")


def _desktop_root() -> Path:
    repo_root = _backend_root().parent
    matches = sorted(
        child for child in repo_root.iterdir()
        if child.is_dir() and (child / "frontend" / "reporting").is_dir()
    )
    assert len(matches) == 1, f"expected exactly one frontend/reporting owner, got {matches}"
    return matches[0]


_BACKEND_ARTIFACTS = (
    "services/goal_failure_causes.py",
    "services/goal_revision_decision.py",
    "services/goal_success_status.py",
    "services/house_matrix_benchmark.py",
    "services/knowledge_asset_class_gap.py",
    "services/pii_vault.py",
    "services/recommendation_release_gate.py",
    "services/retirement_phase.py",
    "services/risk_capacity_plausibility_report.py",
    "services/sqlite_check_constraint_upgrade.py",
    "services/suitability_cap_check.py",
    "services/wealth_inflow_certainty.py",
    "alembic/versions/e3c7a91f5b28_goal_revision_decisions_v1.py",
    "alembic/versions/e5a1c7f3b9d2_wealth_inflow_certainty.py",
    "alembic/versions/e8a4c2f7d913_client_pii_keys_crypto_shredding.py",
)

_FRONTEND_ARTIFACTS = (
    "frontend/reporting/src/api/riskCapacityPlausibility.ts",
    "frontend/reporting/src/lib/fanAnnotations.ts",
    "frontend/reporting/src/lib/fanAnnotations.contract.json",
    "frontend/reporting/src/sections/profiling/RiskCapacityPlausibilityPanel.tsx",
)

_BACKEND_SYMBOLS = {
    "database.py": (
        "GoalRevisionDecisionV1",
        "ensure_sqlite_check_in_lists_current",
    ),
    "services/advisory_report.py": (
        "failure_event_distribution",
        "services.wealth_inflow_certainty",
    ),
    "routers/allocation.py": (
        "services.knowledge_asset_class_gap",
    ),
    "routers/wealth.py": (
        "GoalRevisionDecisionV1",
    ),
}


def test_previously_merged_safety_artifacts_remain_in_release_tree() -> None:
    backend = _backend_root()
    desktop = _desktop_root()
    missing = [
        f"<backend>/{relative}" for relative in _BACKEND_ARTIFACTS
        if not (backend / relative).is_file()
    ] + [
        f"<desktop>/{relative}" for relative in _FRONTEND_ARTIFACTS
        if not (desktop / relative).is_file()
    ]
    assert not missing, "already-merged release artifacts disappeared:\n" + "\n".join(missing)


def test_previously_merged_cross_channel_bindings_remain_integrated() -> None:
    backend = _backend_root()
    missing = []
    for relative, symbols in _BACKEND_SYMBOLS.items():
        path = backend / relative
        text = path.read_text(encoding="utf-8") if path.is_file() else ""
        missing.extend(
            f"<backend>/{relative}: {symbol}" for symbol in symbols if symbol not in text
        )
    assert not missing, "already-merged bindings were reverted:\n" + "\n".join(missing)
