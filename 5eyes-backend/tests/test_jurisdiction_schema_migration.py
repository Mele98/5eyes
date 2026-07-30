"""WP1 (Home-Bias/CMA-Parametrisierung pro Jurisdiktion, 2026-07-30):
Regressionstests fuer die additive Schema-Migration.

Deckt ab:
1. ensure_runtime_columns() ergaenzt die neuen CMA-/BuildingBlock-/
   RecommendationRun-Spalten idempotent auf einer legacy (Raw-SQL-Bootstrap)
   DB.
2. Bestehende CMA-Zeilen bekommen per Backfill status='committee_approved',
   jurisdiction bleibt NULL (impliziert "CH").
3. Eine NEU angelegte CMA-Zeile ohne status bleibt NULL -- kein ungewollter
   DB-Default, kein spaeterer Boot-Lauf ueberschreibt sie.
4. JurisdictionProfile / JurisdictionHomeBiasDefault werden von
   Base.metadata.create_all() korrekt angelegt (komplett neue Tabellen).
5. ensure_default_ch_jurisdiction() ist idempotent (genau eine CH-Zeile).
"""
from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base  # noqa: E402
# Alle Models importieren, damit SQLAlchemy alle FK-Beziehungen aufloesen
# kann (Vorbild: tests/test_tenant_foundation.py).
import models.allocation  # noqa: E402,F401
import models.clients  # noqa: E402,F401
import models.client_login  # noqa: E402,F401
import models.fx_rate  # noqa: E402,F401
import models.jurisdiction  # noqa: E402,F401
import models.mandates  # noqa: E402,F401
import models.profiling  # noqa: E402,F401
import models.review  # noqa: E402,F401
import models.snapshots  # noqa: E402,F401
import models.tenant  # noqa: E402,F401
import models.users  # noqa: E402,F401
import models.wealth  # noqa: E402,F401
from models.jurisdiction import JurisdictionHomeBiasDefault, JurisdictionProfile  # noqa: E402


def _table_columns(engine, table: str) -> set[str]:
    inspector = inspect(engine)
    if not inspector.has_table(table):
        return set()
    return {c["name"] for c in inspector.get_columns(table)}


def _bootstrap_legacy_db(tmp_path, monkeypatch, filename: str = "legacy.db"):
    """Simuliert eine Pre-WP1-Installation: vollstaendiges Bootstrap-SQL
    (das die neuen Jurisdiktions-Spalten NICHT enthaelt)."""
    db_path = tmp_path / filename
    schema_file = BACKEND_ROOT / "5eyes_schema_v4.0_FINAL.sql"
    import database as db_module
    db_module.bootstrap_sqlite_schema(db_path=db_path, schema_path=schema_file)
    test_engine = create_engine(f"sqlite:///{db_path}")
    monkeypatch.setattr(db_module, "engine", test_engine)
    return test_engine, db_module


# ===========================================================================
# 1. ensure_runtime_columns() ergaenzt die neuen Spalten idempotent
# ===========================================================================


def test_ensure_runtime_columns_adds_cma_jurisdiction_columns(tmp_path, monkeypatch):
    test_engine, db_module = _bootstrap_legacy_db(tmp_path, monkeypatch)

    cols_before = _table_columns(test_engine, "capital_market_assumptions")
    assert "jurisdiction" not in cols_before, "Bootstrap-SQL enthaelt jurisdiction schon — Test obsolet"
    assert "status" not in cols_before

    db_module.ensure_runtime_columns()

    cols_after = _table_columns(test_engine, "capital_market_assumptions")
    for expected in (
        "jurisdiction", "status", "source_detail", "computed_at", "computed_by",
        "equity_home_return_bps", "equity_home_vol_bps",
        "bonds_home_ig_return_bps", "bonds_home_ig_vol_bps",
        "real_estate_home_return_bps", "real_estate_home_vol_bps",
    ):
        assert expected in cols_after, f"{expected} fehlt nach Migration"


def test_ensure_runtime_columns_adds_building_block_columns(tmp_path, monkeypatch):
    test_engine, db_module = _bootstrap_legacy_db(tmp_path, monkeypatch, "legacy_bb.db")

    cols_before = _table_columns(test_engine, "building_blocks")
    assert "jurisdiction" not in cols_before
    assert "is_provisional" not in cols_before
    assert "role" not in cols_before

    db_module.ensure_runtime_columns()

    cols_after = _table_columns(test_engine, "building_blocks")
    assert {"jurisdiction", "is_provisional", "role"}.issubset(cols_after)


def test_ensure_runtime_columns_adds_recommendation_run_column(tmp_path, monkeypatch):
    test_engine, db_module = _bootstrap_legacy_db(tmp_path, monkeypatch, "legacy_rr.db")

    cols_before = _table_columns(test_engine, "recommendation_runs")
    assert "provisional_data_warning" not in cols_before

    db_module.ensure_runtime_columns()

    cols_after = _table_columns(test_engine, "recommendation_runs")
    assert "provisional_data_warning" in cols_after


def test_ensure_runtime_columns_idempotent_twice(tmp_path, monkeypatch):
    """Zweiter Lauf darf nicht crashen (duplicate column) und darf die
    Spalten-Menge nicht veraendern."""
    test_engine, db_module = _bootstrap_legacy_db(tmp_path, monkeypatch, "legacy_idem.db")

    db_module.ensure_runtime_columns()
    cols_after_first = _table_columns(test_engine, "capital_market_assumptions")

    db_module.ensure_runtime_columns()  # zweiter Lauf
    cols_after_second = _table_columns(test_engine, "capital_market_assumptions")

    assert cols_after_first == cols_after_second


# ===========================================================================
# 2 + 3. Status-Backfill: Bestandszeilen -> committee_approved,
#         neue NULL-Zeilen bleiben NULL
# ===========================================================================


def _insert_legacy_cma_row(engine, row_id: str, assumption_set_name: str = "Standard") -> None:
    """Legt eine CMA-Zeile GENAU wie eine Pre-WP1-Installation an -- die
    Insert-Spaltenliste enthaelt bewusst NUR Spalten, die im Bootstrap-SQL
    (5eyes_schema_v4.0_FINAL.sql) schon vor WP1 existierten."""
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO capital_market_assumptions
                    (id, assumption_set_name, version, valid_from, is_current,
                     created_by, created_at, updated_at)
                VALUES
                    (:id, :name, 1, '2026-01-01', 1,
                     'legacy-user', '2026-01-01T00:00:00.000Z', '2026-01-01T00:00:00.000Z')
                """
            ),
            {"id": row_id, "name": assumption_set_name},
        )


def test_status_backfill_marks_existing_ch_rows_committee_approved(tmp_path, monkeypatch):
    test_engine, db_module = _bootstrap_legacy_db(tmp_path, monkeypatch, "backfill.db")
    _insert_legacy_cma_row(test_engine, "cma-existing-1")

    db_module.ensure_runtime_columns()

    with test_engine.connect() as conn:
        row = conn.execute(
            text("SELECT status, jurisdiction FROM capital_market_assumptions WHERE id = 'cma-existing-1'")
        ).fetchone()
    assert row is not None
    assert row[0] == "committee_approved", "Bestandszeile muss nach Backfill status=committee_approved haben"
    assert row[1] is None, "jurisdiction bleibt NULL (impliziert CH) -- kein Backfill-Wert dafuer noetig"


def test_status_backfill_idempotent_on_second_run(tmp_path, monkeypatch):
    """Zweiter ensure_runtime_columns()-Lauf darf den Wert nicht veraendern
    (Column existiert dann schon -> Backfill-Zweig greift nicht mehr)."""
    test_engine, db_module = _bootstrap_legacy_db(tmp_path, monkeypatch, "backfill_idem.db")
    _insert_legacy_cma_row(test_engine, "cma-existing-2")

    db_module.ensure_runtime_columns()
    db_module.ensure_runtime_columns()

    with test_engine.connect() as conn:
        row = conn.execute(
            text("SELECT status FROM capital_market_assumptions WHERE id = 'cma-existing-2'")
        ).fetchone()
    assert row[0] == "committee_approved"


def test_new_cma_row_without_status_stays_null_after_later_boot(tmp_path, monkeypatch):
    """Eine NEUE Zeile (z.B. ein spaeteres Arbeitspaket legt eine provisorische
    Nicht-CH-CMA-Zeile an) mit status=NULL darf NICHT beim naechsten
    Backend-Start automatisch auf committee_approved hochgestuft werden --
    nur echte Bestandszeilen (zum Zeitpunkt der Spalten-Einfuehrung) werden
    per Backfill migriert."""
    test_engine, db_module = _bootstrap_legacy_db(tmp_path, monkeypatch, "no_promote.db")
    _insert_legacy_cma_row(test_engine, "cma-existing-3")

    # Erster Lauf: Spalte wird neu angelegt, Bestandszeile wird migriert.
    db_module.ensure_runtime_columns()

    # Jetzt legt ein spaeteres Arbeitspaket (hier simuliert) eine neue,
    # bewusst NICHT-freigegebene Zeile mit status=NULL an.
    with test_engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO capital_market_assumptions
                    (id, assumption_set_name, version, valid_from, is_current,
                     jurisdiction, status, created_by, created_at, updated_at)
                VALUES
                    ('cma-new-de', 'DE-Test', 1, '2026-07-30', 0,
                     'DE', NULL, 'legacy-user', '2026-07-30T00:00:00.000Z', '2026-07-30T00:00:00.000Z')
                """
            )
        )

    # Zweiter (und dritter) Boot-Lauf: darf die neue Zeile NICHT anfassen.
    db_module.ensure_runtime_columns()
    db_module.ensure_runtime_columns()

    with test_engine.connect() as conn:
        row = conn.execute(
            text("SELECT status, jurisdiction FROM capital_market_assumptions WHERE id = 'cma-new-de'")
        ).fetchone()
    assert row[0] is None, "status einer NEUEN Zeile darf nicht automatisch committee_approved werden"
    assert row[1] == "DE"

    # Die alte Bestandszeile bleibt weiterhin committee_approved.
    with test_engine.connect() as conn:
        old_row = conn.execute(
            text("SELECT status FROM capital_market_assumptions WHERE id = 'cma-existing-3'")
        ).fetchone()
    assert old_row[0] == "committee_approved"


# ===========================================================================
# 4. JurisdictionProfile / JurisdictionHomeBiasDefault -- neue Tabellen
# ===========================================================================


def test_jurisdiction_profile_table_created_by_metadata_create_all(tmp_path):
    fresh_engine = create_engine(f"sqlite:///{tmp_path / 'fresh_jp.db'}")
    Base.metadata.create_all(bind=fresh_engine)

    cols = _table_columns(fresh_engine, "jurisdiction_profiles")
    expected = {
        "id", "code", "display_name", "home_currency", "is_active",
        "is_provisional", "status", "notes", "created_by", "created_at",
        "updated_at", "deleted_at",
    }
    assert expected.issubset(cols)
    fresh_engine.dispose()


def test_jurisdiction_home_bias_default_table_created_by_metadata_create_all(tmp_path):
    fresh_engine = create_engine(f"sqlite:///{tmp_path / 'fresh_hb.db'}")
    Base.metadata.create_all(bind=fresh_engine)

    cols = _table_columns(fresh_engine, "jurisdiction_home_bias_defaults")
    expected = {
        "id", "jurisdiction_code", "preference_key", "preference_value",
        "sub_asset_class", "split_bps", "rationale_text", "is_provisional",
        "sort_order", "created_by", "created_at", "updated_at", "deleted_at",
    }
    assert expected.issubset(cols)

    inspector = inspect(fresh_engine)
    index_names = {ix["name"] for ix in inspector.get_indexes("jurisdiction_home_bias_defaults")}
    assert "ix_jurisdiction_home_bias_lookup" in index_names
    fresh_engine.dispose()


def test_jurisdiction_tables_survive_orm_roundtrip(tmp_path):
    """Legt ueber das ORM je eine Zeile an und liest sie zurueck -- pinnt,
    dass die Column-Typen/-Constraints tatsaechlich funktionsfaehig sind
    (nicht nur syntaktisch vorhanden)."""
    fresh_engine = create_engine(f"sqlite:///{tmp_path / 'orm_roundtrip.db'}")
    Base.metadata.create_all(bind=fresh_engine)
    session_factory = sessionmaker(bind=fresh_engine)

    with session_factory() as db:
        profile = JurisdictionProfile(
            id="jp-de",
            code="DE",
            display_name="Deutschland",
            home_currency="EUR",
            is_active=1,
            is_provisional=1,
            status="pending_ic_review",
            created_by=None,
            created_at="2026-07-30T00:00:00.000Z",
            updated_at="2026-07-30T00:00:00.000Z",
        )
        db.add(profile)
        default = JurisdictionHomeBiasDefault(
            id="jhb-de-1",
            jurisdiction_code="DE",
            preference_key="equity_home_market",
            preference_value="DAX",
            sub_asset_class="Aktien Heimmarkt",
            split_bps=3000,
            rationale_text="Provisorisch, noch nicht IC-geprueft",
            is_provisional=1,
            sort_order=1,
            created_by=None,
            created_at="2026-07-30T00:00:00.000Z",
            updated_at="2026-07-30T00:00:00.000Z",
        )
        db.add(default)
        db.commit()

    with session_factory() as db:
        loaded_profile = db.query(JurisdictionProfile).filter(JurisdictionProfile.code == "DE").first()
        loaded_default = db.query(JurisdictionHomeBiasDefault).filter(
            JurisdictionHomeBiasDefault.jurisdiction_code == "DE"
        ).first()

    assert loaded_profile is not None
    assert loaded_profile.home_currency == "EUR"
    assert loaded_profile.is_provisional == 1
    assert loaded_default is not None
    assert loaded_default.split_bps == 3000
    fresh_engine.dispose()


# ===========================================================================
# 5. ensure_default_ch_jurisdiction() idempotent
# ===========================================================================


def test_ensure_default_ch_jurisdiction_idempotent(tmp_path, monkeypatch):
    """Drei Aufrufe -> genau eine CH-Zeile (Vorbild:
    test_tenant_foundation.py::test_ensure_default_tenant_idempotent)."""
    import database as db_module

    fresh_engine = create_engine(
        f"sqlite:///{tmp_path / 'ch_idem.db'}",
        connect_args={"check_same_thread": False},
    )
    fresh_sf = sessionmaker(autocommit=False, autoflush=False, bind=fresh_engine)
    Base.metadata.create_all(bind=fresh_engine)
    monkeypatch.setattr(db_module, "SessionLocal", fresh_sf, raising=False)

    db_module.ensure_default_ch_jurisdiction()
    db_module.ensure_default_ch_jurisdiction()
    db_module.ensure_default_ch_jurisdiction()

    with fresh_sf() as db:
        count = db.query(JurisdictionProfile).filter(JurisdictionProfile.code == "CH").count()
        assert count == 1
        ch = db.query(JurisdictionProfile).filter(JurisdictionProfile.code == "CH").first()
        assert ch.home_currency == "CHF"
        assert ch.is_active == 1
        assert ch.is_provisional == 0
        assert ch.status == "approved"
    fresh_engine.dispose()
