"""POLICY-ACTIVATION-COMPLETENESS-001 (round 40 red test).

Audit 2026-10-04-optimizer-policy-version-and-activation-integrity-audit.md
(not committed in this repo) claims that
`routers/allocation.py::clone_optimizer_policy()` (POST
`/admin/optimizer-policies/{policy_id}/clone`) produces an INCOMPLETE clone:
it copies `HouseMatrix` rows explicitly, but never touches `BuildingBlock`
rows -- a separate, policy-scoped table (`building_blocks.policy_id` FK ->
`optimizer_policies.id`) that carries each policy's risk-fraction /
jurisdiction- and universe-basis data (`risky_fraction_bps`, `jurisdiction`,
`universe`, `advisory`, `contribution_standard_bps`,
`contribution_alternative_bps`, `is_provisional`, `role`).

Verified directly against models/allocation.py:
- `OptimizerPolicy.building_blocks = relationship("BuildingBlock", ...)`
  exists alongside `OptimizerPolicy.house_matrix_entries`.
- `GET /building-blocks/current` (routers/allocation.py) resolves the
  *currently active* policy and returns only ITS BuildingBlock rows.

So once an admin activates a clone (making it `is_current=1`), any endpoint
that reads "the current policy's building blocks" -- i.e. the clone's
risk-fraction / jurisdiction-universe basis -- comes back EMPTY, because
`clone_optimizer_policy()` never created BuildingBlock rows for the clone.
This is a real, independently-activatable-copy violation: the clone is not
equivalent to its source despite looking complete (same House-Matrix bands).

This test seeds a source OptimizerPolicy with House-Matrix rows AND
BuildingBlock rows (a realistic policy has both -- see
`routers/allocation.py::get_current_building_blocks`), clones it through the
real HTTP endpoint, and asserts the clone ends up with the same set of
BuildingBlock rows as the source. It also walks the full ORM column list of
OptimizerPolicy and HouseMatrix against clone_optimizer_policy's explicit
field lists to catch any additional silently-dropped scalar field.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

BACKEND_ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = Path(__file__).resolve().parent
for path in (BACKEND_ROOT, TESTS_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from database import get_db, new_uuid
from main import app
from models.allocation import BuildingBlock, HouseMatrix, OptimizerPolicy
from services.auth import require_admin
from test_optimizer_shadow_mode import session_factory  # noqa: F401


_ADMIN_ID = "admin-clonecompleteness"
_NOW = "2026-10-04T10:00:00.000Z"

# Columns that are intentionally allowed to differ between source and clone
# (identity / versioning / provenance fields -- NOT policy content).
_OPTIMIZER_POLICY_IDENTITY_COLUMNS = {
    "id", "version", "is_current", "valid_from", "valid_to",
    "notes", "created_by", "created_at", "updated_at",
    # policy_name is deliberately overridable via ?new_name=, so it is
    # exempt from the "must be byte-identical" check but is still required
    # to be *set* (handled separately).
    "policy_name",
}


def _ensure_admin(session_factory) -> None:
    from models.users import User as UserModel
    with session_factory() as s:
        if not s.query(UserModel).filter(UserModel.id == _ADMIN_ID).first():
            s.add(UserModel(
                id=_ADMIN_ID, username="admin-clonecompleteness",
                password_hash="x", full_name="Admin CloneCompleteness",
                role="admin", is_active=1,
                created_at=_NOW, updated_at=_NOW,
            ))
            s.commit()


def _seed_full_policy(session_factory) -> str:
    """Erzeugt eine realistische OptimizerPolicy MIT House-Matrix- UND
    BuildingBlock-Zeilen (wie sie in Produktion gemeinsam existieren,
    siehe get_current_building_blocks())."""
    _ensure_admin(session_factory)
    pid = new_uuid()
    with session_factory() as s:
        s.add(OptimizerPolicy(
            id=pid,
            policy_name="Clone-Completeness-Source",
            version=1,
            is_current=1,
            valid_from=_NOW,
            valid_to=None,
            optimizer_engine="goal_based_v1",
            max_real_estate_bps=2000,
            max_alternatives_bps=1000,
            min_liquidity_bps=100,
            allow_other_assets_for_goals=1,
            fee_model_json='{"fee_bps":50}',
            notes="seed-source",
            created_by=_ADMIN_ID,
            created_at=_NOW,
            updated_at=_NOW,
        ))
        s.add(HouseMatrix(
            id=new_uuid(), policy_id=pid,
            score_from=1, score_to=10, profile_name="Konservativ",
            liq_min_bps=0, liq_target_bps=500, liq_max_bps=1000,
            bonds_min_bps=3000, bonds_target_bps=4000, bonds_max_bps=5000,
            equity_min_bps=1000, equity_target_bps=2000, equity_max_bps=3000,
            real_estate_min_bps=0, real_estate_target_bps=1000, real_estate_max_bps=2000,
            alt_min_bps=0, alt_target_bps=500, alt_max_bps=1000,
            equity_minimum_bps=500, max_risky_fraction_bps=4000,
            is_active=1, created_at=_NOW, updated_at=_NOW,
        ))
        # Zwei realistische BuildingBlock-Zeilen: Standard-Universum + ein
        # jurisdiktionsspezifischer / Alternative-Baustein, damit der Test
        # auch die Jurisdiktions-/Universumsbasis mitverifiziert.
        s.add(BuildingBlock(
            id=new_uuid(), policy_id=pid,
            asset_class="Equity", sub_asset_class="Equity CH",
            universe="Standard", advisory=1,
            risky_fraction_bps=10000,
            contribution_standard_bps=10000, contribution_alternative_bps=None,
            is_active=1, created_at=_NOW, updated_at=_NOW,
            jurisdiction="CH", is_provisional=0, role="core",
        ))
        s.add(BuildingBlock(
            id=new_uuid(), policy_id=pid,
            asset_class="Alternatives", sub_asset_class="Private Equity",
            universe="Alternative", advisory=0,
            risky_fraction_bps=10000,
            contribution_standard_bps=None, contribution_alternative_bps=10000,
            is_active=1, created_at=_NOW, updated_at=_NOW,
            jurisdiction="DE", is_provisional=1, role="satellite",
        ))
        s.commit()
    return pid


def _client(session_factory) -> TestClient:
    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    admin_user = SimpleNamespace(
        id=_ADMIN_ID, full_name="Admin CloneCompleteness",
        email="admin-clonecompleteness@test.local",
    )
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[require_admin] = lambda: admin_user
    return TestClient(app)


def _clone(session_factory, pid: str) -> dict:
    try:
        with _client(session_factory) as client:
            resp = client.post(f"/admin/optimizer-policies/{pid}/clone")
            assert resp.status_code == 201, resp.text
            return resp.json()
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Sanity: HouseMatrix rows ARE copied (this part of the endpoint is correct
# per the code at routers/allocation.py ~1414-1446). Kept as a (non-xfail)
# regression guard so a future change to the HouseMatrix-copy logic is
# caught here too.
# ---------------------------------------------------------------------------

def test_clone_copies_house_matrix_rows_completely(session_factory):
    pid = _seed_full_policy(session_factory)
    clone_json = _clone(session_factory, pid)
    clone_id = clone_json["id"]

    with session_factory() as s:
        src_rows = s.query(HouseMatrix).filter(HouseMatrix.policy_id == pid).all()
        clone_rows = s.query(HouseMatrix).filter(HouseMatrix.policy_id == clone_id).all()

    assert len(clone_rows) == len(src_rows) == 1

    src_row, clone_row = src_rows[0], clone_rows[0]
    hm_value_columns = [
        c.name for c in HouseMatrix.__table__.columns
        if c.name not in {"id", "policy_id", "created_at", "updated_at"}
    ]
    for col in hm_value_columns:
        assert getattr(clone_row, col) == getattr(src_row, col), (
            f"HouseMatrix.{col} diverged between source and clone"
        )


# ---------------------------------------------------------------------------
# RED: BuildingBlock rows are the documented gap -- clone_optimizer_policy()
# never queries or copies them, so an activated clone has NO risk-fraction /
# jurisdiction-universe basis of its own.
# ---------------------------------------------------------------------------

@pytest.mark.xfail(
    strict=True,
    reason="POLICY-ACTIVATION-COMPLETENESS-001 — round 40 red test, see audit "
           "2026-10-04-optimizer-policy-version-and-activation-integrity-audit.md "
           "(not committed in this repo)",
)
def test_clone_copies_building_block_rows(session_factory):
    pid = _seed_full_policy(session_factory)
    clone_json = _clone(session_factory, pid)
    clone_id = clone_json["id"]

    with session_factory() as s:
        src_blocks = s.query(BuildingBlock).filter(BuildingBlock.policy_id == pid).all()
        clone_blocks = (
            s.query(BuildingBlock).filter(BuildingBlock.policy_id == clone_id).all()
        )

    # Source has 2 realistic BuildingBlock rows seeded above.
    assert len(src_blocks) == 2

    # clone_optimizer_policy() only copies HouseMatrix, never BuildingBlock --
    # this currently fails with 0 != 2 (clone_blocks is empty).
    assert len(clone_blocks) == len(src_blocks), (
        "clone_optimizer_policy() dropped all BuildingBlock rows (risk-fraction / "
        "jurisdiction-universe basis) -- an activated clone has none of its own"
    )

    src_by_key = {(b.asset_class, b.sub_asset_class, b.jurisdiction): b for b in src_blocks}
    clone_by_key = {(b.asset_class, b.sub_asset_class, b.jurisdiction): b for b in clone_blocks}
    assert set(src_by_key) == set(clone_by_key)
    for key, src_b in src_by_key.items():
        clone_b = clone_by_key[key]
        assert clone_b.universe == src_b.universe
        assert clone_b.advisory == src_b.advisory
        assert clone_b.risky_fraction_bps == src_b.risky_fraction_bps
        assert clone_b.contribution_standard_bps == src_b.contribution_standard_bps
        assert clone_b.contribution_alternative_bps == src_b.contribution_alternative_bps
        assert clone_b.is_provisional == src_b.is_provisional
        assert clone_b.role == src_b.role


# ---------------------------------------------------------------------------
# Full-column sweep: every OptimizerPolicy scalar field that
# clone_optimizer_policy() does NOT explicitly list (lines ~1394-1410) is
# either an identity/versioning field (expected to differ -- see
# _OPTIMIZER_POLICY_IDENTITY_COLUMNS) or a genuinely dropped content field.
# As of this audit, the explicit field list happens to cover every non-
# identity scalar column that currently exists on OptimizerPolicy, so this
# guard is NOT expected to go red today -- it exists so that if a future
# column is added to the model without updating clone_optimizer_policy(),
# this test (not strict=True, so it will actually fail CI, unlike the
# xfail above) catches the regression immediately.
# ---------------------------------------------------------------------------

def test_clone_covers_every_optimizer_policy_content_column(session_factory):
    pid = _seed_full_policy(session_factory)
    clone_json = _clone(session_factory, pid)
    clone_id = clone_json["id"]

    with session_factory() as s:
        src = s.query(OptimizerPolicy).filter(OptimizerPolicy.id == pid).first()
        clone = s.query(OptimizerPolicy).filter(OptimizerPolicy.id == clone_id).first()

    all_columns = [c.name for c in OptimizerPolicy.__table__.columns]
    content_columns = [c for c in all_columns if c not in _OPTIMIZER_POLICY_IDENTITY_COLUMNS]

    missing = [
        col for col in content_columns
        if getattr(clone, col) != getattr(src, col)
    ]
    assert missing == [], (
        f"clone_optimizer_policy() silently dropped/defaulted OptimizerPolicy "
        f"content column(s) not in its explicit copy list: {missing}"
    )
