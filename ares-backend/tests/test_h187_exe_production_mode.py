"""EXE-P (H-187): Produktionsmodus der gepackten EXE.

A1 SQLCipher-Pflicht (Schluessel in DPAPI-Ablage, nie Klartext), A2 kein
Laufzeit-Seeding von Hausannahmen (typisiert REFERENCE_DATA_PACKAGE_MISSING,
einzige Ausnahme das TEST-Referenzpaket des Packaging-Smokes), A3 kein
Gebuehren-Default (Kostenausweis ohne Gebuehrenvereinbarung = Entwurf).
Die gepackte EXE wird hier ueber ``sys.frozen`` bzw. ``config.PACKAGED_BUILD``
simuliert; den echten Lauf im Artefakt belegt der Packaging-Smoke.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest

import config
from config import (
    DB_KEY_STORE_MAGIC,
    PackagedDatabaseError,
    Settings,
    db_key_format_ok,
    ensure_packaged_db_key,
    packaged_plaintext_connection_refused,
    require_packaged_database,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SMOKE_PACKAGE = REPO_ROOT / "scripts" / "fixtures" / "packaging_smoke_test_reference_package.json"


class FakeProtector:
    """Umkehrbarer Ersatz fuer DPAPI (nur Tests)."""

    def __init__(self) -> None:
        self.calls = 0

    @staticmethod
    def available() -> bool:
        return True

    def protect(self, data: bytes, entropy: bytes) -> bytes:
        self.calls += 1
        return bytes(b ^ 0x5A for b in data) + entropy

    def unprotect(self, blob: bytes, entropy: bytes) -> bytes:
        assert blob.endswith(entropy)
        return bytes(b ^ 0x5A for b in blob[: -len(entropy)])


def _cfg(tmp_path: Path, **kw) -> Settings:
    return Settings(app_env="development", db_path=str(tmp_path / "data" / "ares.db"),
                    db_key_file=str(tmp_path / "userData" / "db-key.dpapi"), **kw)


# --------------------------------------------------------------------------- A1
def test_source_mode_changes_nothing(tmp_path):
    cfg = _cfg(tmp_path)
    assert ensure_packaged_db_key(cfg, packaged=False) == "not-packaged"
    assert cfg.db_use_sqlcipher is False and not cfg.db_key
    assert not (tmp_path / "userData").exists()
    assert require_packaged_database(cfg, packaged=False, state={"problem": "x"}) == "not-packaged"
    assert packaged_plaintext_connection_refused(packaged=False, cfg=cfg) is False


def test_packaged_first_start_generates_key_in_dpapi_store_then_loads_it(tmp_path):
    cfg = _cfg(tmp_path)
    protector = FakeProtector()
    assert ensure_packaged_db_key(cfg, packaged=True, protector=protector, sqlcipher_available=True) == "generated"
    store = tmp_path / "userData" / "db-key.dpapi"
    raw = store.read_bytes()
    assert raw.startswith(DB_KEY_STORE_MAGIC)
    assert cfg.db_use_sqlcipher is True and db_key_format_ok(cfg.db_key) and len(cfg.db_key) == 64
    assert cfg.db_key.encode() not in raw, "Schluessel nie im Klartext in der Ablage"
    first_key = cfg.db_key
    # Datenbank angelegt -> zweiter Start laedt, erzeugt nie neu, ueberschreibt nie.
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    (tmp_path / "data" / "ares.db").write_bytes(b"\x00" * 32)
    cfg2 = _cfg(tmp_path)
    assert ensure_packaged_db_key(cfg2, packaged=True, protector=protector, sqlcipher_available=True) == "loaded"
    assert cfg2.db_key == first_key and store.read_bytes() == raw
    assert require_packaged_database(cfg2, packaged=True, state={"outcome": "loaded", "problem": None}) == "loaded"
    assert packaged_plaintext_connection_refused(packaged=True, cfg=cfg2) is False


def test_packaged_without_sqlcipher_driver_refuses(tmp_path):
    cfg = _cfg(tmp_path)
    with pytest.raises(PackagedDatabaseError, match="SQLCipher"):
        ensure_packaged_db_key(cfg, packaged=True, protector=FakeProtector(), sqlcipher_available=False)
    assert not (tmp_path / "userData").exists()


def test_packaged_without_store_location_refuses(tmp_path):
    cfg = Settings(app_env="development", db_path=str(tmp_path / "ares.db"))
    with pytest.raises(PackagedDatabaseError, match="DB_KEY_FILE"):
        ensure_packaged_db_key(cfg, packaged=True, protector=FakeProtector(), sqlcipher_available=True)


def test_packaged_existing_database_without_store_never_generates_a_key(tmp_path):
    cfg = _cfg(tmp_path)
    (tmp_path / "data").mkdir()
    sqlite3.connect(tmp_path / "data" / "ares.db").close()  # Klartext-Bestand aus aelterer Version
    protector = FakeProtector()
    with pytest.raises(PackagedDatabaseError, match="keine Ablage"):
        ensure_packaged_db_key(cfg, packaged=True, protector=protector, sqlcipher_available=True)
    assert protector.calls == 0 and not (tmp_path / "userData" / "db-key.dpapi").exists()


def test_packaged_explicit_key_contradicting_store_refuses(tmp_path):
    cfg = _cfg(tmp_path)
    ensure_packaged_db_key(cfg, packaged=True, protector=FakeProtector(), sqlcipher_available=True)
    other = _cfg(tmp_path, db_key="b" * 64)
    with pytest.raises(PackagedDatabaseError, match="widerspricht"):
        ensure_packaged_db_key(other, packaged=True, protector=FakeProtector(), sqlcipher_available=True)


def test_lifespan_check_refuses_recorded_problem_and_plaintext(tmp_path):
    cfg = _cfg(tmp_path)
    with pytest.raises(PackagedDatabaseError, match="Ablageort"):
        require_packaged_database(cfg, packaged=True, state={"outcome": None, "problem": "Kein Ablageort ..."})
    with pytest.raises(PackagedDatabaseError, match="verschluesselter Datenbank"):
        require_packaged_database(cfg, packaged=True, state={"outcome": None, "problem": None})
    assert packaged_plaintext_connection_refused(packaged=True, cfg=cfg) is True


def test_packaged_engine_refuses_plaintext_connection(tmp_path, monkeypatch):
    """Verbindungssperre in ``database``: gepackt + ohne SQLCipher -> keine Verbindung,
    keine Klartext-Datei."""
    import database

    engine = database.create_app_engine(db_path=str(tmp_path / "plain.db"), db_key=None)
    monkeypatch.setattr(config, "PACKAGED_BUILD", True)
    monkeypatch.setattr(database.settings, "db_use_sqlcipher", False)
    with pytest.raises(Exception, match="Unverschluesselte Datenbankverbindung"):
        with engine.connect():
            pass
    engine.dispose()


def test_packaged_raw_stdlib_connect_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "PACKAGED_BUILD", True)
    with pytest.raises(PackagedDatabaseError, match="Unverschluesselte"):
        config.guarded_sqlite_connect(str(tmp_path / "raw.db"), context="Test")
    assert not (tmp_path / "raw.db").exists()
    config.guarded_sqlite_connect(":memory:", context="Test").close()


def test_smoke_cipher_pragmas_match_backend():
    import importlib.util

    import database

    spec = importlib.util.spec_from_file_location("_smoke", REPO_ROOT / "scripts" / "packaging_smoke.py")
    smoke = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(smoke)
    assert smoke.SQLCIPHER_CIPHER_PRAGMAS == database.SQLCIPHER_CIPHER_PRAGMAS
    assert smoke.DB_KEY_STORE_MAGIC == config.DB_KEY_STORE_MAGIC
    assert smoke.DB_KEY_STORE_ENTROPY == config.DB_KEY_STORE_ENTROPY
    assert smoke.DB_KEY_STORE_NAME == config.DB_KEY_STORE_NAME


# --------------------------------------------------------------------------- A2
@pytest.fixture()
def empty_session(tmp_path):
    from sqlalchemy.orm import sessionmaker

    import database

    engine = database.create_app_engine(db_path=str(tmp_path / "ref.db"), db_key=None)
    database.init_db(target_engine=engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    from models.users import User

    with factory() as session:
        session.add(User(id="u-1", username="u-1", password_hash="h", full_name="Test", role="admin",
                         is_active=1, created_at="2026-11-21T00:00:00Z", updated_at="2026-11-21T00:00:00Z"))
        session.commit()
    yield factory
    engine.dispose()


def _counts(session) -> tuple[int, int]:
    from models.allocation import CapitalMarketAssumption, OptimizerPolicy

    return session.query(OptimizerPolicy).count(), session.query(CapitalMarketAssumption).count()


def test_packaged_exe_never_seeds_house_assumptions(empty_session, monkeypatch):
    import services.portfolio_engine as pe
    from core.risk_parameter_set import ReferenceDataPackageMissing

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(pe.settings, "test_reference_package_file", "")
    assert pe.settings.production_mode and pe.settings.ic_release_required
    with empty_session() as session:
        with pytest.raises(ReferenceDataPackageMissing, match="freigegebene Referenzdaten"):
            pe.ensure_runtime_reference_data(session, "u-1", jurisdiction="CH")
        session.flush()
        assert _counts(session) == (0, 0)


def test_source_mode_still_seeds_template_values(empty_session):
    import services.portfolio_engine as pe

    assert not getattr(sys, "frozen", False)
    with empty_session() as session:
        policy, cma = pe.ensure_runtime_reference_data(session, "u-1", jurisdiction="CH")
        assert policy is not None and cma is not None


@pytest.mark.no_test_fee_model
def test_smoke_test_package_allows_seeding_without_fee_and_without_ic_release(empty_session, monkeypatch, tmp_path):
    import services.portfolio_engine as pe

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    package = tmp_path / "pkg.json"
    package.write_text(SMOKE_PACKAGE.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr(pe.settings, "test_reference_package_file", str(package))
    assert pe.settings.ic_release_required is False  # rechnen erlaubt ...
    with empty_session() as session:
        policy, _cma = pe.ensure_runtime_reference_data(session, "u-1", jurisdiction="CH")
        assert policy.fee_model_json is None, "kein Gebuehren-Default (A3)"
    # ... aber nie als IC-freigegeben gekennzeichnet (Paket behauptet keine Freigabe).
    from core.risk_parameter_set import IC_RELEASE_UNRELEASED, ic_release_for

    assert ic_release_for(policy)[0] == IC_RELEASE_UNRELEASED


def test_smoke_test_package_with_foreign_template_hash_is_rejected(empty_session, monkeypatch, tmp_path):
    import services.portfolio_engine as pe
    from core.risk_parameter_set import ReferenceDataPackageMissing

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    data = json.loads(SMOKE_PACKAGE.read_text(encoding="utf-8"))
    data["reference_data"]["sha256"] = "0" * 64
    package = tmp_path / "pkg-foreign.json"
    package.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(pe.settings, "test_reference_package_file", str(package))
    with empty_session() as session:
        with pytest.raises(ReferenceDataPackageMissing, match="passt nicht"):
            pe.ensure_runtime_reference_data(session, "u-1", jurisdiction="CH")


def test_smoke_package_is_ignored_outside_the_packaged_exe(monkeypatch):
    """Ein Server mit app_env=production nimmt nie ein Testpaket an."""
    cfg = Settings(app_env="development", test_reference_package_file=str(SMOKE_PACKAGE))
    assert config.smoke_reference_package(cfg) is not None
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    assert config.smoke_reference_package_active(cfg) is False


def test_smoke_fixture_is_marked_and_bound_to_current_template_values():
    """Das TEST-Paket enthaelt keine eigenen Zahlen, nur den Pruefwert der
    Vorlagewerte dieser Version (aendern sich die Vorlagewerte, ist das Paket
    bewusst nachzufuehren)."""
    import services.portfolio_engine as pe

    data = json.loads(SMOKE_PACKAGE.read_text(encoding="utf-8"))
    assert data["test_only"] is True and data["marker"] == config.TEST_REFERENCE_PACKAGE_MARKER
    assert data["format"] == config.TEST_REFERENCE_PACKAGE_FORMAT
    assert set(data) == {"format", "test_only", "marker", "purpose", "reference_data"}
    assert data["reference_data"]["sha256"] == pe.current_reference_template_sha256()


def test_reference_package_missing_is_typed_409():
    from core.middleware import typed_engine_error
    from core.risk_parameter_set import ReferenceDataPackageMissing

    typed = typed_engine_error(ReferenceDataPackageMissing("Es fehlen freigegebene Referenzdaten"))
    assert typed is not None and typed.reason_code == "REFERENCE_DATA_PACKAGE_MISSING"
    assert typed.status_code == 409


def test_packaged_exe_does_not_seed_demo_product_catalog():
    import inspect

    import services.portfolio_engine as pe

    source = inspect.getsource(pe.generate_recommendation_run)
    guard = source.index("if not settings.production_mode:  # EXE-P")
    assert source[guard:].split("\n")[1].strip().startswith("ensure_default_products(db")


# --------------------------------------------------------------------------- A3
@pytest.mark.no_test_fee_model
def test_template_policy_carries_no_fee_model(empty_session):
    import services.portfolio_engine as pe

    with empty_session() as session:
        policy, _ = pe.ensure_runtime_reference_data(session, "u-1", jurisdiction="CH")
        assert policy.fee_model_json is None


def test_fee_agreement_missing_judgement():
    from services.cost_disclosure import calculate_cost_disclosure, fee_agreement_missing

    positions = [{"amount_rappen": 10_000_000, "weight_bps": 10000, "ter_bps": 20}]
    no_fee = calculate_cost_disclosure(advisory_wealth_rappen=10_000_000, positions=positions, fee_model={})
    assert fee_agreement_missing(no_fee) is True
    assert not any(item.get("rate_bps") == 75 for item in no_fee["cost_items"]), "nie ein angenommener Satz"
    zero = calculate_cost_disclosure(advisory_wealth_rappen=10_000_000, positions=positions,
                                     fee_model={"default_advisory_fee_bps": 0})
    assert fee_agreement_missing(zero) is False  # ausdruecklich vereinbart: 0
    assert fee_agreement_missing({"data_pending": True}) is False


def test_cost_pdf_without_fee_agreement_is_a_draft_never_archived(auth_client, advisor_user, session_factory, monkeypatch):
    from client_onboarding_fixture import satisfy_client_onboarding
    from models.mandates import Mandate
    from models.review import ContractDocument

    mandate_id = _seed_minimal_mandate(session_factory, advisor_user)
    with session_factory() as db:
        satisfy_client_onboarding(db, db.get(Mandate, mandate_id), actor_id=advisor_user.id)
        db.commit()
    payload = _full_payload()
    payload["cost_items"] = [i for i in payload["cost_items"] if i.get("key") != "default_advisory_fee_bps"]
    monkeypatch.setattr("services.cost_disclosure.build_cost_disclosure", lambda db, mandate: payload)
    resp = auth_client.get(f"/mandates/{mandate_id}/reports/cost-disclosure.pdf")
    assert resp.status_code == 200, resp.text
    assert resp.headers.get("X-Ares-Draft") == "gebuehren"
    assert "X-Cost-Disclosure-Document-Id" not in resp.headers
    with session_factory() as db:
        assert db.query(ContractDocument).filter(ContractDocument.document_type == "Kostenausweis").count() == 0
    # Mit vereinbartem Satz: final und archiviert (unveraendert).
    monkeypatch.setattr("services.cost_disclosure.build_cost_disclosure", lambda db, mandate: _full_payload())
    final = auth_client.get(f"/mandates/{mandate_id}/reports/cost-disclosure.pdf")
    assert final.status_code == 200 and final.headers.get("X-Cost-Disclosure-Document-Id")


def test_fee_draft_texts_match():
    from services.pdf.components import footer, watermark

    assert watermark.FEE_AGREEMENT_DRAFT_TEXT == footer.FEE_AGREEMENT_DRAFT_TEXT
    assert "gebuehren" in watermark.WATERMARK_MODES


sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_cost_disclosure_pdf import (  # noqa: E402,F401
    _full_payload, _seed_minimal_mandate, advisor_user, auth_client, session_factory,
)
