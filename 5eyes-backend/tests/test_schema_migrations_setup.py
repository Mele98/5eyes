"""Sprint U-41 (2026-06-06) + Folge-Sprint Roadmap #90 (2026-08-07):
Drift-Schutz fuer alembic-Setup-Doku.

test_documents_alembic_not_in_requirements hiess urspruenglich anders (siehe
Git-History) und pruefte die U-41-Entscheidung "alembic noch NICHT in
requirements.txt". Roadmap #90 ist genau der in U-41 angekuendigte
Folge-Sprint, der das umsetzt (init_db-Switch create_all<->alembic fuer
Postgres) -- die Entscheidung ist jetzt umgekehrt, der Test prueft das
Gegenteil."""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DOC = REPO_ROOT / "docs" / "SCHEMA_MIGRATIONS.md"
REQUIREMENTS = REPO_ROOT / "5eyes-backend" / "requirements.txt"


def _read() -> str:
    return DOC.read_text(encoding="utf-8")


def test_doc_exists():
    assert DOC.exists()


def test_documents_opt_in_strategy():
    text = _read()
    assert "opt-in" in text.lower()
    assert "pip install alembic" in text


def test_documents_alembic_now_in_requirements():
    """Roadmap #90 (2026-08-07): U-41 verschob dies bewusst auf einen
    Folge-Sprint ("NICHT in requirements.txt bis konkret gebraucht") --
    #90 IST dieser Folge-Sprint (Postgres-Produktion braucht den
    init_db-Switch create_all<->alembic)."""
    pkg = REQUIREMENTS.read_text(encoding="utf-8")
    assert "alembic" in pkg.lower()


def test_documents_init_workflow():
    text = _read()
    assert "alembic init" in text
    assert "env.py" in text


def test_documents_baseline_migration():
    text = _read()
    assert "baseline" in text
    assert "alembic stamp head" in text


def test_documents_per_sprint_migrations():
    text = _read()
    assert "autogenerate" in text
    assert "u_XX_" in text or "u_xx_" in text


def test_documents_sqlite_batch_pattern():
    text = _read()
    assert "batch_alter_table" in text
    assert "SQLite" in text


def test_documents_settings_integration():
    text = _read()
    assert "create_all" in text
    assert "init_db" in text


def test_documents_bewusst_nicht_in_scope():
    text = _read()
    assert "Bewusst NICHT" in text
    assert "requirements.txt" in text


def test_documents_postgres_link_to_42():
    text = _read()
    assert "#42" in text


def test_documents_cost_discipline_adr_005():
    text = _read()
    assert "ADR-005" in text


def test_lists_relevant_model_imports():
    """env.py-Beispiel muss die wichtigen Models referenzieren."""
    text = _read()
    for model in ("models.allocation", "models.users", "models.mandates"):
        assert model in text
    # U-36 sollte explizit auftauchen (neuestes Model)
    assert "client_login" in text


def test_links_to_alembic_docs():
    text = _read()
    assert "alembic.sqlalchemy.org" in text
