"""Every test file must be runnable alone, in any order and in any process.

``Base.metadata`` only knows the tables of model modules that were imported.
``tests/test_optimizer_shadow_mode.py`` run alone produced 2 passed / 19 errors
(``NoReferencedTableError``: ``product_eligibility_rule_sets.tenant_id`` ->
``tenants``); ``tests/test_stage8_foundation_smoketest.py`` alone 4 errors.
Both were green only in the full serial run because an earlier file had
imported ``models.tenant``. Under sharding / ``--dist loadfile`` that ordering
luck is gone, so ``tests/conftest.py`` registers all ORM models per process.

The probe below runs once in-process and once in a fresh pytest subprocess
(the only place where the ordering luck cannot help it).
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

_BACKEND_ROOT = Path(__file__).resolve().parents[1]


def test_create_all_resolves_foreign_keys_without_explicit_model_imports():
    from sqlalchemy import create_engine

    import models.product_eligibility  # noqa: F401  (references tenants.id)
    from database import Base

    engine = create_engine("sqlite://")
    try:
        Base.metadata.create_all(engine)
    finally:
        engine.dispose()
    assert "tenants" in Base.metadata.tables


def test_probe_passes_in_a_fresh_test_process(tmp_path):
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("PYTEST_XDIST") and key != "PYTEST_CURRENT_TEST"
    }
    env["DB_PATH"] = str(tmp_path / "probe.db")
    node_id = (
        f"{Path(__file__).resolve().relative_to(_BACKEND_ROOT).as_posix()}"
        "::test_create_all_resolves_foreign_keys_without_explicit_model_imports"
    )
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", node_id, "-q", "-p", "no:cacheprovider", "-p", "no:xdist"],
        cwd=_BACKEND_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert proc.returncode == 0, proc.stdout[-4000:] + proc.stderr[-2000:]
    assert "1 passed" in proc.stdout
