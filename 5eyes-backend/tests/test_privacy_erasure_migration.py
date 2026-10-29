"""PRIVACY-001: Alembic-Revision der Privacy-Tabellen (kettenbasiert)."""
from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, inspect

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REVISION = "d3e1a7c9b4f2"
TABLES = {
    "privacy_retention_policies", "privacy_role_designations", "privacy_legal_holds",
    "privacy_erasure_cases", "privacy_erasure_dispositions",
}


def _config(url: str):
    from alembic.config import Config as AlembicConfig

    cfg = AlembicConfig(str(BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", url)
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    return cfg


def _down_revision() -> str:
    from alembic.script import ScriptDirectory

    return ScriptDirectory.from_config(_config("sqlite://")).get_revision(REVISION).down_revision


def test_revision_is_in_the_single_head_chain():
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(_config("sqlite://"))
    heads = script.get_heads()
    assert len(heads) == 1, heads
    assert REVISION in {rev.revision for rev in script.walk_revisions("base", heads[0])}


def test_upgrade_creates_and_downgrade_drops_privacy_tables(tmp_path):
    from alembic import command

    url = f"sqlite:///{tmp_path / 'privacy_chain.db'}"
    cfg = _config(url)
    down = _down_revision()
    command.upgrade(cfg, down)
    engine = create_engine(url)
    try:
        assert not TABLES & set(inspect(engine).get_table_names())
        command.upgrade(cfg, REVISION)
        assert TABLES <= set(inspect(engine).get_table_names())
        command.downgrade(cfg, down)
        assert not TABLES & set(inspect(engine).get_table_names())
        command.upgrade(cfg, REVISION)
        assert TABLES <= set(inspect(engine).get_table_names())
    finally:
        engine.dispose()
