"""ANSWERS-MIGRATION-IDEMPOTENT-001 (Incident 2026-10-15).

``run_risk_assessment_answer_migration`` decided "needs upgrade" with
``'KENNTNISSE & ERFAHRUNGEN' not in ddl_text`` -- an UPPER-case needle in the
original-case DDL that contains 'Kenntnisse & Erfahrungen'. The condition was
therefore always true: EVERY app start renamed, recreated, copied and dropped
the answers table. pysqlite commits the RENAME immediately, so an interrupted
or concurrent start left ``risk_assessment_answers__old`` with all rows next
to an empty ORM-created ``risk_assessment_answers`` -- and every later start
failed on the RENAME ("there is already another table ... __old").

Found on the live DB after parallel test runs had executed the app lifespan
against the default database path (see tests/conftest.py isolation guard).
"""
from __future__ import annotations

from sqlalchemy import create_engine, text

from database import Base, run_risk_assessment_answer_migration
from models import profiling  # noqa: F401


def _engine(tmp_path, name="m.db"):
    eng = create_engine(f"sqlite:///{tmp_path / name}")
    return eng


def _canonical(eng):
    with eng.begin() as conn:
        conn.execute(text("CREATE TABLE risk_assessments (id TEXT PRIMARY KEY)"))
        conn.execute(text("""
            CREATE TABLE risk_assessment_answers (
                id TEXT PRIMARY KEY,
                assessment_id TEXT NOT NULL REFERENCES risk_assessments(id) ON UPDATE CASCADE,
                question_number INTEGER NOT NULL CHECK(question_number BETWEEN 1 AND 12),
                question_section TEXT NOT NULL CHECK(question_section IN ('Kenntnisse & Erfahrungen','Risikofähigkeit','Risikobereitschaft')),
                answer_label TEXT NOT NULL,
                answer_points INTEGER NOT NULL,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                UNIQUE(assessment_id, question_number)
            )"""))
        conn.execute(text("INSERT INTO risk_assessments VALUES ('ra1')"))
        for q, sec in ((1, "Kenntnisse & Erfahrungen"), (5, "Risikofähigkeit"), (9, "Risikobereitschaft")):
            conn.execute(text(
                "INSERT INTO risk_assessment_answers (id, assessment_id, question_number, question_section, "
                "answer_label, answer_points, created_at) VALUES (:i,'ra1',:q,:s,'x',1,'2026-01-01T00:00:00.000Z')"
            ), {"i": f"a{q}", "q": q, "s": sec})


def _table_sql(eng, name):
    with eng.connect() as conn:
        return conn.execute(text("SELECT sql FROM sqlite_master WHERE name=:n"), {"n": name}).scalar()


def test_canonical_table_is_not_rebuilt_on_every_start(tmp_path):
    eng = _engine(tmp_path)
    _canonical(eng)
    with eng.begin() as conn:  # marker: a rebuild would recreate the table and lose this view
        conn.execute(text("CREATE VIEW v_marker AS SELECT id FROM risk_assessment_answers"))
    before = _table_sql(eng, "risk_assessment_answers")
    run_risk_assessment_answer_migration(eng)
    assert _table_sql(eng, "risk_assessment_answers") == before
    with eng.connect() as conn:
        # sqlite rewrites the view text on RENAME -> a rebuild would point it at __old
        view_sql = conn.execute(text("SELECT sql FROM sqlite_master WHERE name='v_marker'")).scalar()
    assert "__old" not in view_sql


def test_interrupted_rebuild_is_completed_on_next_start(tmp_path):
    eng = _engine(tmp_path)
    _canonical(eng)
    # Simulate the interrupted state found on the live DB: rows in __old,
    # empty ORM-created table.
    with eng.begin() as conn:
        conn.execute(text("ALTER TABLE risk_assessment_answers RENAME TO risk_assessment_answers__old"))
    Base.metadata.tables["risk_assessment_answers"].create(bind=eng)
    run_risk_assessment_answer_migration(eng)
    with eng.connect() as conn:
        names = {r[0] for r in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))}
        rows = conn.execute(text("SELECT id, question_number, question_section FROM risk_assessment_answers ORDER BY id")).fetchall()
    assert "risk_assessment_answers__old" not in names
    assert [tuple(r) for r in rows] == [
        ("a1", 1, "Kenntnisse & Erfahrungen"), ("a5", 5, "Risikofähigkeit"), ("a9", 9, "Risikobereitschaft"),
    ]
    assert "BETWEEN 1 AND 12" in _table_sql(eng, "risk_assessment_answers")


def test_interrupted_state_with_nonempty_new_table_fails_loudly(tmp_path):
    eng = _engine(tmp_path)
    _canonical(eng)
    with eng.begin() as conn:
        conn.execute(text("ALTER TABLE risk_assessment_answers RENAME TO risk_assessment_answers__old"))
    Base.metadata.tables["risk_assessment_answers"].create(bind=eng)
    with eng.begin() as conn:
        conn.execute(text(
            "INSERT INTO risk_assessment_answers (id, assessment_id, question_number, question_section, "
            "answer_label, answer_points, created_at) VALUES ('n1','ra1',2,'Risikofähigkeit','y',1,'2026-01-02')"
        ))
    import pytest
    with pytest.raises(RuntimeError, match="manuell"):
        run_risk_assessment_answer_migration(eng)


def test_test_suite_never_points_at_the_live_database():
    from config import settings
    from core.db_location import is_live_db_path

    assert not is_live_db_path(settings.db_path)


def test_migration_preserves_the_connection_foreign_key_mode(tmp_path):
    """The rebuild toggles PRAGMA foreign_keys; it must restore the PREVIOUS
    mode on the pooled connection, not force ON (that silently changed FK
    enforcement for every later session on that connection)."""
    from sqlalchemy.pool import StaticPool

    eng = create_engine(f"sqlite:///{tmp_path / 'fk.db'}", poolclass=StaticPool)
    _canonical(eng)
    with eng.connect() as conn:
        before = conn.exec_driver_sql("PRAGMA foreign_keys").scalar()
    with eng.begin() as conn:  # force a real rebuild
        conn.execute(text("ALTER TABLE risk_assessment_answers RENAME TO risk_assessment_answers__old"))
    Base.metadata.tables["risk_assessment_answers"].create(bind=eng)
    run_risk_assessment_answer_migration(eng)
    with eng.connect() as conn:
        assert conn.exec_driver_sql("PRAGMA foreign_keys").scalar() == before
