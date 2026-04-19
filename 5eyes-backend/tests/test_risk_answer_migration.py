from pathlib import Path

from sqlalchemy import create_engine, inspect, text

from database import run_risk_assessment_answer_migration


def test_risk_answer_migration_upgrades_legacy_constraints(tmp_path: Path):
    db_path = tmp_path / "legacy_risk_answers.db"
    engine = create_engine(f"sqlite:///{db_path}")

    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE risk_assessments (
                id TEXT PRIMARY KEY
            )
        """))
        conn.execute(text("""
            CREATE TABLE risk_assessment_answers (
                id TEXT PRIMARY KEY,
                assessment_id TEXT NOT NULL REFERENCES risk_assessments(id) ON UPDATE CASCADE,
                question_number INTEGER NOT NULL CHECK(question_number BETWEEN 1 AND 9),
                question_section TEXT NOT NULL CHECK(question_section IN ('Risikofähigkeit','Risikobereitschaft')),
                answer_label TEXT NOT NULL,
                answer_points INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(assessment_id, question_number)
            )
        """))
        conn.execute(text("CREATE INDEX idx_risk_answers ON risk_assessment_answers(assessment_id)"))
        conn.execute(text("INSERT INTO risk_assessments (id) VALUES ('ra-1')"))
        conn.execute(text("""
            INSERT INTO risk_assessment_answers (
                id, assessment_id, question_number, question_section,
                answer_label, answer_points, created_at
            ) VALUES (
                'ans-1', 'ra-1', 9, 'Risikobereitschaft',
                'legacy', 3, '2026-04-10T00:00:00Z'
            )
        """))

    run_risk_assessment_answer_migration(engine)

    inspector = inspect(engine)
    assert inspector.has_table("risk_assessment_answers")
    with engine.begin() as conn:
        ddl = conn.execute(
            text("SELECT sql FROM sqlite_master WHERE type='table' AND name='risk_assessment_answers'")
        ).scalar_one()
        rows = conn.execute(
            text("SELECT id, question_number, question_section FROM risk_assessment_answers")
        ).fetchall()

    assert "BETWEEN 1 AND 11" in ddl
    assert "Kenntnisse & Erfahrungen" in ddl
    assert rows == [("ans-1", 9, "Risikobereitschaft")]
