"""DEPOT-E2E-SNAPSHOT-001: DepotCheckAnalysisSnapshot.

Vertrag (CIO-Entscheid):
* Das Depot-Check-Ergebnis ist an genau einen DepotSnapshotV1 gebunden
  (``snapshot_id`` + ``snapshot_hash``), traegt Analyse-Version und
  Ergebnis-Hash und wird append-only gespeichert.
* Der IST-Bestand der Analyse ist der Bestand des Depot-Snapshots -- nie die
  Kopie ``current_amount_rappen`` eines Laufs und nie der Zielbetrag als
  Ersatz. SOLL-Vergleichswerte kommen weiter aus dem gueltigen Lauf.
* JSON-Endpunkt (``GET /depot-check?analysis_snapshot_id=``) und PDF lesen
  denselben gespeicherten Analysis-Snapshot; Manipulation -> 409.
* Kein Depot-Check-PDF bei erfasstem Bestand ohne gebundenen Snapshot oder wenn
  die Soll-Allokation seit dem Snapshot gewechselt hat (fail-closed).
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, inspect, text

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from models.allocation import TargetAllocation  # noqa: E402
from models.snapshots import DepotCheckAnalysisSnapshot  # noqa: E402
from services import depot_check_snapshot as dca  # noqa: E402
from services import depot_snapshot as ds  # noqa: E402
from services.depot_check import compute_depot_check  # noqa: E402
from tests.test_depot_snapshot_ist_stress import (  # noqa: E402,F401
    AS_OF,
    FX,
    NOW,
    SCHEMA_FILE,
    _seed,
    session_factory,
)

REVISION = "e7a3c9d1b5f2"
DOWN_REVISION = "b5d2e8f1c4a7"


def _snapshot(s, mandate):
    snapshot = ds.build_depot_snapshot(s, mandate, as_of=AS_OF, fx_source=FX)
    ds.persist_depot_snapshot(s, snapshot, mandate=mandate, created_by="adv-a", created_at=NOW)
    s.flush()
    return snapshot


def _request():
    return SimpleNamespace(headers={}, client=SimpleNamespace(host="127.0.0.1"))


def _create_api(s, mandate, advisor, snapshot_id):
    from routers.allocation import create_depot_check_analysis

    return create_depot_check_analysis(
        mandate.id, snapshot_id, _request(), db=s, current_user=advisor,
    )


def _json_api(s, mandate, advisor, analysis_id):
    from routers.allocation import get_depot_check

    return get_depot_check(
        mandate.id, analysis_snapshot_id=analysis_id, db=s, current_user=advisor,
    )


# --- IST-Bestand = Depot-Snapshot ------------------------------------------

def test_analysis_ist_is_the_depot_snapshot_not_the_run_copy(session_factory):
    with session_factory() as s:
        _advisor, mandate = _seed(s)
        snapshot = _snapshot(s, mandate)
        live = compute_depot_check(s, mandate)
        analysis = dca.build_depot_check_analysis(s, mandate, snapshot)
    held = sum(p["amount_base_rappen"] for p in snapshot["positions"])
    result = analysis["result"]
    # Die ungebundene Live-Analyse liest die Lauf-Kopie (999'999'999 je Position).
    assert live["total_advisory_wealth_rappen"] == 3 * 999_999_999_00
    assert result["total_advisory_wealth_rappen"] == held == 988_000_00
    assert result["buckets"]["equities"]["ist_rappen"] == 600_000_00 + 88_000_00
    assert result["buckets"]["bonds"]["ist_rappen"] == 300_000_00
    assert sum(p["amount_rappen"] for p in result["top_positions"]) == held
    # SOLL-Vergleich bleibt aus dem gueltigen Lauf (Zielbetraege).
    assert result["soll_currency_exposure_bps"]
    assert analysis["recommendation_run_id"] == "run-a"
    assert analysis["target_allocation_id"] == "ta-a"


def test_run_target_is_never_used_as_ist_for_unheld_products(session_factory):
    with session_factory() as s:
        _advisor, mandate = _seed(s, holdings=(
            ("rp-eq", "Aktien", "CHF", 6_000_000, 10_000),
        ))
        snapshot = _snapshot(s, mandate)
        from models.review import Product, RecommendationPosition

        s.add(Product(
            id="prod-new", isin="CH00000NEW01", product_name="Neu", product_type="ETF",
            asset_class="Obligationen", currency="CHF", ter_bps=10, provider="Test",
            is_active=1, created_at=NOW, updated_at=NOW,
        ))
        s.flush()
        s.add(RecommendationPosition(
            id="rp-new", run_id="run-a", product_id="prod-new", target_weight_bps=0,
            target_amount_rappen=500_000_00, current_amount_rappen=0,
            created_at=NOW, updated_at=NOW,
        ))
        s.flush()
        result = dca.build_depot_check_analysis(s, mandate, snapshot)["result"]
    assert result["total_advisory_wealth_rappen"] == 600_000_00
    assert result["buckets"]["bonds"]["ist_rappen"] == 0
    # Das nur empfohlene Produkt zaehlt im SOLL (Zielbetrag 500k von 600k).
    assert result["soll_country_exposure_bps"] or result["soll_currency_exposure_bps"]
    assert all(p["amount_rappen"] > 0 for p in result["top_positions"])


# --- Identitaet, Hashes, Verifikation --------------------------------------

def test_analysis_binds_snapshot_identity_and_result_hash(session_factory):
    with session_factory() as s:
        _advisor, mandate = _seed(s)
        snapshot = _snapshot(s, mandate)
        first = dca.build_depot_check_analysis(s, mandate, snapshot)
        second = dca.build_depot_check_analysis(s, mandate, snapshot)
    assert first == second
    assert first["analysis_version"] == "DepotCheckAnalysisV1"
    assert first["snapshot_id"] == snapshot["snapshot_id"]
    assert first["snapshot_hash"] == snapshot["snapshot_hash"]
    assert first["as_of"] == snapshot["as_of"]
    assert first["result_hash"] == ds._sha256(first["result"])
    assert first["analysis_snapshot_id"] == f"dca-{first['analysis_hash'][:24]}"
    assert dca.verify_depot_check_analysis(first) is first


@pytest.mark.parametrize("tamper", ["result", "snapshot_hash", "result_hash", "extra"])
def test_verify_rejects_manipulated_analysis(session_factory, tamper):
    with session_factory() as s:
        _advisor, mandate = _seed(s)
        analysis = dca.build_depot_check_analysis(s, mandate, _snapshot(s, mandate))
    forged = json.loads(json.dumps(analysis))
    if tamper == "result":
        forged["result"]["total_advisory_wealth_rappen"] += 1
    elif tamper == "snapshot_hash":
        forged["snapshot_hash"] = "0" * 64
    elif tamper == "result_hash":
        forged["result_hash"] = "0" * 64
    else:
        forged["extra"] = 1
    with pytest.raises(dca.DepotCheckAnalysisIntegrityError):
        dca.verify_depot_check_analysis(forged)


def test_snapshot_of_another_mandate_is_rejected(session_factory):
    with session_factory() as s:
        _advisor, mandate = _seed(s)
        snapshot = _snapshot(s, mandate)
        other = SimpleNamespace(**{**{c: getattr(mandate, c) for c in ("client_id", "base_currency")},
                                   "id": "m-other"})
        with pytest.raises(dca.DepotCheckAnalysisIntegrityError):
            dca.build_depot_check_analysis(s, other, snapshot)


# --- API: speichern, JSON lesen, Manipulation ------------------------------

def test_api_stores_idempotently_and_json_reads_the_stored_analysis(session_factory):
    with session_factory() as s:
        advisor, mandate = _seed(s)
        s.commit()
        from routers.allocation import create_depot_snapshot

        snap = create_depot_snapshot(mandate.id, _request(), db=s, current_user=advisor)["snapshot"]
        first = _create_api(s, mandate, advisor, snap["snapshot_id"])
        second = _create_api(s, mandate, advisor, snap["snapshot_id"])
        assert first["created"] is True and second["created"] is False
        assert s.query(DepotCheckAnalysisSnapshot).count() == 1
        stored = _json_api(s, mandate, advisor, first["analysis_snapshot_id"])
        # Spaeter veraenderte Livewerte duerfen den gespeicherten Stand nicht aendern.
        s.execute(text("UPDATE recommendation_holdings SET units_milli = units_milli * 2"))
        again = _json_api(s, mandate, advisor, first["analysis_snapshot_id"])
    assert stored == again
    for key in ("analysis_snapshot_id", "snapshot_id", "snapshot_hash", "as_of", "result_hash"):
        assert stored[key] == first[key]
    assert stored["snapshot_id"] == snap["snapshot_id"]
    assert stored["total_advisory_wealth_rappen"] == sum(
        p["amount_base_rappen"] for p in snap["positions"]
    )


def test_api_detects_tampered_analysis_row_with_409(session_factory):
    with session_factory() as s:
        advisor, mandate = _seed(s)
        snapshot = _snapshot(s, mandate)
        s.commit()
        created = _create_api(s, mandate, advisor, snapshot["snapshot_id"])
        row = s.query(DepotCheckAnalysisSnapshot).one()
        forged = json.loads(row.analysis_json)
        forged["result"]["total_advisory_wealth_rappen"] = 1
        s.add(DepotCheckAnalysisSnapshot(
            id="dca-forged", schema_version=row.schema_version, mandate_id=row.mandate_id,
            client_id=row.client_id, depot_snapshot_id=row.depot_snapshot_id,
            depot_snapshot_hash=row.depot_snapshot_hash, as_of_date=row.as_of_date,
            analysis_json=json.dumps(forged), analysis_hash=row.analysis_hash,
            result_hash=row.result_hash, created_by=advisor.id, created_at=NOW,
        ))
        s.commit()
        with pytest.raises(HTTPException) as exc:
            _json_api(s, mandate, advisor, "dca-forged")
        assert exc.value.status_code == 409
        with pytest.raises(HTTPException) as missing:
            _json_api(s, mandate, advisor, "dca-unknown")
        assert missing.value.status_code == 404
        with pytest.raises(HTTPException) as no_snapshot:
            _create_api(s, mandate, advisor, "dps-unknown")
        assert no_snapshot.value.status_code == 404
    assert created["created"] is True


def test_analysis_rows_are_immutable(session_factory):
    with session_factory() as s:
        advisor, mandate = _seed(s)
        snapshot = _snapshot(s, mandate)
        s.commit()
        analysis_id = _create_api(s, mandate, advisor, snapshot["snapshot_id"])["analysis_snapshot_id"]
        for statement in (
            "UPDATE depot_check_analysis_snapshots SET result_hash = 'x' WHERE id = :id",
            "DELETE FROM depot_check_analysis_snapshots WHERE id = :id",
        ):
            with pytest.raises(Exception, match="immutable"):
                s.execute(text(statement), {"id": analysis_id})
            s.rollback()


# --- PDF-Bindung ------------------------------------------------------------

def test_latest_analysis_is_loaded_and_none_without_snapshot(session_factory):
    with session_factory() as s:
        advisor, mandate = _seed(s)
        assert dca.load_depot_check_analysis(s, mandate) is None
        snapshot = _snapshot(s, mandate)
        s.commit()
        created = _create_api(s, mandate, advisor, snapshot["snapshot_id"])
        loaded = dca.load_depot_check_analysis(s, mandate)
    assert loaded["analysis_snapshot_id"] == created["analysis_snapshot_id"]


def test_pdf_binding_rejects_analysis_for_a_replaced_target_allocation(session_factory):
    with session_factory() as s:
        _advisor, mandate = _seed(s)
        analysis = dca.build_depot_check_analysis(s, mandate, _snapshot(s, mandate))
        dca.assert_analysis_matches_current_allocation(s, mandate, analysis)
        s.query(TargetAllocation).filter(TargetAllocation.id == "ta-a").update({"is_current": 0})
        s.flush()
        with pytest.raises(ValueError, match="Soll-Allokation"):
            dca.assert_analysis_matches_current_allocation(s, mandate, analysis)


def test_pdf_shows_snapshot_identity_and_as_of():
    from datetime import date
    from io import BytesIO

    from pypdf import PdfReader

    from services.pdf.base import DepotCheckData, PDFContext
    from services.pdf.reportlab_renderer import ReportLabRenderer

    ctx = PDFContext(
        mandate_name="Muster Mandat", advisor_name="Anna Beratung",
        advisor_org="Beratungshaus", report_date=date(2026, 10, 28), audit_hash="dca-test",
    )
    pdf = ReportLabRenderer().render_depotcheck(ctx, DepotCheckData(
        mandate_number="M-DCA",
        analysis_snapshot_id="dca-0123456789abcdef01234567",
        snapshot_id="dps-abcdef0123456789abcdef01",
        snapshot_hash="f" * 64,
        as_of="2026-10-26",
        result_hash="e" * 64,
        cost_disclosure={"data_pending": True, "note": "Daten ausstehend."},
        performance={"data_pending": True, "note": "Daten ausstehend."},
    ))
    flat = " ".join(
        " ".join((page.extract_text() or "") for page in PdfReader(BytesIO(pdf)).pages).split()
    )
    assert "dps-abcdef0123456789abcdef01" in flat
    assert "ffffffffffff" in flat
    assert "26.10.2026" in flat
    assert "dca-0123456789abcdef01234567" in flat


# --- Schema: Bootstrap, Runtime-Patch, Alembic -----------------------------

def _tables(db_path):
    with sqlite3.connect(str(db_path)) as conn:
        return {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def test_bootstrap_plus_runtime_patch_creates_immutable_table(tmp_path, monkeypatch):
    import database as db_module

    db_path = tmp_path / "fresh.db"
    db_module.bootstrap_sqlite_schema(db_path=db_path, schema_path=SCHEMA_FILE)
    assert "depot_check_analysis_snapshots" in _tables(db_path)
    test_engine = create_engine(f"sqlite:///{db_path}")
    monkeypatch.setattr(db_module, "engine", test_engine)
    db_module.ensure_runtime_columns()
    db_module.ensure_runtime_columns()  # idempotent
    with test_engine.connect() as conn:
        triggers = {row[0] for row in conn.execute(text(
            "SELECT name FROM sqlite_master WHERE type='trigger' "
            "AND tbl_name='depot_check_analysis_snapshots'"
        ))}
        columns = {c["name"] for c in inspect(conn).get_columns("depot_check_analysis_snapshots")}
    test_engine.dispose()
    assert triggers == {
        "trg_depot_check_analysis_snapshots_no_update",
        "trg_depot_check_analysis_snapshots_no_delete",
    }
    assert columns == {c.name for c in DepotCheckAnalysisSnapshot.__table__.columns}


def test_alembic_chain_contains_revision_and_round_trips(tmp_path):
    from alembic import command
    from alembic.config import Config as AlembicConfig
    from alembic.script import ScriptDirectory

    db_path = tmp_path / "alembic.db"
    cfg = AlembicConfig(str(BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    script = ScriptDirectory.from_config(cfg)
    heads = script.get_heads()
    assert len(heads) == 1, heads
    assert REVISION in {rev.revision for rev in script.walk_revisions("base", heads[0])}
    assert script.get_revision(REVISION).down_revision == DOWN_REVISION
    command.upgrade(cfg, DOWN_REVISION)
    assert "depot_check_analysis_snapshots" not in _tables(db_path)
    command.upgrade(cfg, REVISION)
    assert "depot_check_analysis_snapshots" in _tables(db_path)
    command.downgrade(cfg, DOWN_REVISION)
    assert "depot_check_analysis_snapshots" not in _tables(db_path)
