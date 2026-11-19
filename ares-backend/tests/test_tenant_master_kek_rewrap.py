"""N-870-6 (2026-11-05): Bestandsinstallation mit schwacher Passphrase-KEK.

Entscheid (H-133): Eine Passphrase-KEK, die allein an der Staerkeregel
scheitert (zu kurz / zu wenig Vielfalt), blockiert den Start weiter
(fail-closed). Die DEKs bleiben unveraendert. Der Weg heraus ist der
Offline-Rewrap auf einen Fernet-Key: services.tenant_crypto.
rewrap_tenant_deks_to_master_kek bzw. scripts/rewrap_tenant_master_kek.py.
Platzhalter, Vorlagenwerte und oeffentliche Ableitungen sind auch als Quelle
abgelehnt.
"""
from __future__ import annotations

import datetime
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

pytest.importorskip("cryptography.fernet")
from cryptography.fernet import Fernet  # noqa: E402

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import config  # noqa: E402
from config import DEFAULT_SECRET_KEY, KekStoreError, effective_tenant_master_kek, require_tenant_master_kek  # noqa: E402
from database import Base  # noqa: E402
import models.tenant  # noqa: F401,E402
from models.tenant import Tenant  # noqa: E402
from services import tenant_crypto  # noqa: E402
from services.tenant_crypto import TenantCryptoError, get_tenant_dek, rewrap_tenant_deks_to_master_kek  # noqa: E402

# Bisher (vor a9003ac8) zulaessig, jetzt zu schwach: kurz bzw. wenig Vielfalt.
WEAK_LEGACY_KEKS = ["kurz-aber-zufaellig-9f3K", "abababababababababababababababababab"]


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


@pytest.fixture
def Session(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'rewrap.db'}")
    Base.metadata.create_all(bind=engine)
    try:
        yield sessionmaker(bind=engine, expire_on_commit=False)
    finally:
        engine.dispose()


def _seed_wrapped_tenants(Session, legacy_kek: str, ids=("firm-A", "firm-B")) -> dict[str, bytes]:
    """Tenants mit DEKs, verpackt wie tenant_crypto sie unter der Bestands-
    Passphrase verpackt hat (KEK-Vertrag v2), ohne die heutige Pruefung."""
    fernet = Fernet(effective_tenant_master_kek(legacy_kek.encode("utf-8")))
    deks = {}
    with Session() as db:
        for tid in ids:
            dek = Fernet.generate_key()
            deks[tid] = dek
            db.add(Tenant(
                id=tid, display_name=tid, slug=tid.lower(), hosting_tier="tier1",
                license_status="active", max_users=10, is_active=1,
                encrypted_dek=fernet.encrypt(dek).decode("utf-8"), dek_version=1,
                kek_version=tenant_crypto.CURRENT_KEK_VERSION,
                created_at=_now(), updated_at=_now(),
            ))
        db.commit()
    return deks


def _stored(Session) -> dict[str, str]:
    with Session() as db:
        return {t.id: t.encrypted_dek for t in db.query(Tenant).all()}


class _Cfg:
    def __init__(self, kek: str):
        self.tenant_master_kek = kek
        self.secret_key = "jwt-secret-for-tests-only-0123456789"


@pytest.mark.parametrize("legacy", WEAK_LEGACY_KEKS)
def test_weak_legacy_kek_blocks_start_but_data_is_recoverable(Session, legacy):
    deks = _seed_wrapped_tenants(Session, legacy)
    with pytest.raises(KekStoreError) as exc:
        require_tenant_master_kek(_Cfg(legacy))
    assert "zu schwach" in str(exc.value) and "rewrap_tenant_master_kek.py" in str(exc.value)
    assert legacy not in str(exc.value)

    target = Fernet.generate_key().decode("ascii")
    with Session() as db:
        assert rewrap_tenant_deks_to_master_kek(db, source_kek=legacy, target_kek=target).count == 2
        db.commit()
    require_tenant_master_kek(_Cfg(target))
    with Session() as db:
        for tid, dek in deks.items():
            assert get_tenant_dek(db, tid, master_kek=target) == dek, "DEK unveraendert"


@pytest.mark.parametrize("source", [
    DEFAULT_SECRET_KEY,
    "__BITTE_ERSETZEN__",
    "changeme",
    "${TENANT_MASTER_KEK}",
])
def test_placeholder_source_stays_fail_closed(Session, source):
    _seed_wrapped_tenants(Session, source)
    before = _stored(Session)
    with Session() as db, pytest.raises(TenantCryptoError) as exc:
        rewrap_tenant_deks_to_master_kek(db, source_kek=source, target_kek=Fernet.generate_key())
    assert "Quell-KEK abgelehnt" in str(exc.value) and source not in str(exc.value)
    assert _stored(Session) == before


def test_target_must_be_a_strong_fernet_key(Session):
    legacy = WEAK_LEGACY_KEKS[0]
    _seed_wrapped_tenants(Session, legacy)
    before = _stored(Session)
    for target in (
        "eine-lange-starke-passphrase-als-ziel-0123456789",  # Passphrase statt Fernet
        "kurz-9f3K",                                          # schwach
        effective_tenant_master_kek(legacy.encode("utf-8")).decode("ascii"),  # = Quelle
    ):
        with Session() as db, pytest.raises(TenantCryptoError) as exc:
            rewrap_tenant_deks_to_master_kek(db, source_kek=legacy, target_kek=target)
        assert "Ziel-KEK abgelehnt" in str(exc.value) and target not in str(exc.value)
    assert _stored(Session) == before


def test_wrong_source_changes_nothing(Session):
    """Ein Tenant unter anderer KEK: kein einziger DEK wird umgeschrieben."""
    legacy = WEAK_LEGACY_KEKS[0]
    _seed_wrapped_tenants(Session, legacy, ids=("firm-A",))
    _seed_wrapped_tenants(Session, "andere-bestands-passphrase-0123456789", ids=("firm-Z",))
    before = _stored(Session)
    with Session() as db:
        with pytest.raises(TenantCryptoError):
            rewrap_tenant_deks_to_master_kek(db, source_kek=legacy, target_kek=Fernet.generate_key())
        assert {t.id: t.encrypted_dek for t in db.query(Tenant).all()} == before
        db.rollback()
    assert _stored(Session) == before


def test_cli_rewraps_from_configured_kek(Session, monkeypatch, capsys, tmp_path):
    import database
    monkeypatch.syspath_prepend(str(BACKEND_ROOT / "scripts"))
    import rewrap_tenant_master_kek as cli

    legacy = WEAK_LEGACY_KEKS[0]
    deks = _seed_wrapped_tenants(Session, legacy)
    target = Fernet.generate_key().decode("ascii")
    monkeypatch.setattr(database, "SessionLocal", Session)
    monkeypatch.setattr(config.settings, "tenant_master_kek", legacy)
    # Standardablage der Desktop-App (N-870-13) nie im echten Profil suchen.
    for var in ("APPDATA", "HOME", "USERPROFILE", "XDG_CONFIG_HOME"):
        monkeypatch.setenv(var, str(tmp_path / "profile"))
    monkeypatch.setenv(cli.TARGET_ENV, target)

    assert cli.main([]) == 2  # ohne --yes nichts
    assert cli.main(["--yes"]) == 0
    out = capsys.readouterr()
    assert "rewrapped_deks=2" in out.out
    assert legacy not in out.out + out.err and target not in out.out + out.err
    with Session() as db:
        for tid, dek in deks.items():
            assert get_tenant_dek(db, tid, master_kek=target) == dek

    # Zweiter Lauf mit derselben (jetzt falschen) Quelle: Abbruch, nichts geaendert.
    before = _stored(Session)
    monkeypatch.setenv(cli.TARGET_ENV, Fernet.generate_key().decode("ascii"))
    assert cli.main(["--yes"]) == 1
    assert _stored(Session) == before


# ---------------------------------------------------------------------------
# N-870-9: das CLI laeuft im frischen Interpreter gegen eine echte Datei-DB
# (kein von pytest vorgeladenes Modell-Set).
# ---------------------------------------------------------------------------

_SCRIPT = BACKEND_ROOT / "scripts" / "rewrap_tenant_master_kek.py"


def _file_db_with_wrapped_tenants(tmp_path, legacy_kek: str) -> tuple[Path, dict[str, bytes]]:
    from main import app  # noqa: F401  (alle Modelle fuer create_all im Testprozess)

    db_file = tmp_path / "ares-rewrap.db"
    engine = create_engine(f"sqlite:///{db_file}")
    Base.metadata.create_all(bind=engine)
    try:
        deks = _seed_wrapped_tenants(sessionmaker(bind=engine, expire_on_commit=False), legacy_kek)
    finally:
        engine.dispose()
    return db_file, deks


def _isolated_env(tmp_path, db_file: Path, **extra: str) -> dict[str, str]:
    import os

    env = {
        k: v for k, v in os.environ.items()
        if not k.startswith(("TENANT_MASTER_KEK", "DATABASE_URL", "DB_KEY", "SECRET_KEY", "PYTEST"))
    }
    home = tmp_path / "home"
    for sub in ("appdata", "local", "temp"):
        (home / sub).mkdir(parents=True, exist_ok=True)
    env.update({
        "HOME": str(home), "USERPROFILE": str(home),
        "APPDATA": str(home / "appdata"), "LOCALAPPDATA": str(home / "local"),
        "TEMP": str(home / "temp"), "TMP": str(home / "temp"),
        "DB_PATH": str(db_file),
        "PYTHONPATH": "",
    })
    env.update(extra)
    return env


def _run_cli(tmp_path, env: dict[str, str]):
    import subprocess

    return subprocess.run(
        [sys.executable, "-I", str(_SCRIPT), "--yes"],
        cwd=str(tmp_path), env=env, capture_output=True, text=True, timeout=180,
    )


def test_cli_runs_standalone_against_file_db(tmp_path):
    legacy = WEAK_LEGACY_KEKS[0]
    db_file, deks = _file_db_with_wrapped_tenants(tmp_path, legacy)
    target = Fernet.generate_key().decode("ascii")
    proc = _run_cli(tmp_path, _isolated_env(
        tmp_path, db_file, TENANT_MASTER_KEK=legacy, TENANT_MASTER_KEK_NEW=target,
    ))
    out = proc.stdout + proc.stderr
    assert proc.returncode == 0, out[-2000:]
    assert "rewrapped_deks=2" in proc.stdout
    assert legacy not in out and target not in out

    engine = create_engine(f"sqlite:///{db_file}")
    try:
        S = sessionmaker(bind=engine, expire_on_commit=False)
        with S() as db:
            for tid, dek in deks.items():
                assert get_tenant_dek(db, tid, master_kek=target) == dek
    finally:
        engine.dispose()


def test_cli_db_error_prints_no_sql_parameters(tmp_path):
    """N-870-11: Ein DB-Fehler beim Schreiben (hier ein Trigger, der das UPDATE
    abbricht) darf keinen Traceback mit "[parameters: ...]" drucken -- darin
    stuende der neu verpackte DEK. Nichts geaendert, Exit 1."""
    from sqlalchemy import text

    legacy = WEAK_LEGACY_KEKS[0]
    db_file, _ = _file_db_with_wrapped_tenants(tmp_path, legacy)
    engine = create_engine(f"sqlite:///{db_file}")
    try:
        with engine.begin() as conn:
            conn.execute(text(
                "CREATE TRIGGER trg_block_dek BEFORE UPDATE OF encrypted_dek ON tenants "
                "BEGIN SELECT RAISE(ABORT, 'rewrap blockiert (Test)'); END"
            ))
            before = dict(conn.execute(text("SELECT id, encrypted_dek FROM tenants")).fetchall())
    finally:
        engine.dispose()

    target = Fernet.generate_key().decode("ascii")
    proc = _run_cli(tmp_path, _isolated_env(
        tmp_path, db_file, TENANT_MASTER_KEK=legacy, TENANT_MASTER_KEK_NEW=target,
    ))
    out = proc.stdout + proc.stderr
    assert proc.returncode == 1, out[-2000:]
    assert "Datenbankfehler" in proc.stderr and "rewrap blockiert" in proc.stderr
    assert "Traceback" not in out and "parameters" not in out
    assert "gAAAA" not in out, "kein Fernet-Token in der Ausgabe"
    assert legacy not in out and target not in out
    for value in before.values():
        assert value not in out

    engine = create_engine(f"sqlite:///{db_file}")
    try:
        with engine.connect() as conn:
            assert dict(conn.execute(text("SELECT id, encrypted_dek FROM tenants")).fetchall()) == before
    finally:
        engine.dispose()


def _audit_rows(db_file: Path) -> list[dict]:
    from sqlalchemy import text

    engine = create_engine(f"sqlite:///{db_file}")
    try:
        with engine.connect() as conn:
            return [dict(r._mapping) for r in conn.execute(text(
                "SELECT table_name, record_id, action, field_name, old_value, new_value, user_id "
                "FROM audit_log WHERE table_name = 'tenants'"
            ))]
    finally:
        engine.dispose()


def test_cli_writes_one_audit_entry_and_updated_at(tmp_path):
    """N-870-10: genau ein audit_log-Eintrag in derselben Transaktion (Anzahl,
    SHA-256 der sortierten Tenant-IDs, kein Schluesselmaterial); updated_at
    der Tenants gesetzt."""
    import hashlib
    import json

    from sqlalchemy import text

    legacy = WEAK_LEGACY_KEKS[0]
    db_file, deks = _file_db_with_wrapped_tenants(tmp_path, legacy)
    engine = create_engine(f"sqlite:///{db_file}")
    try:
        with engine.connect() as conn:
            before = dict(conn.execute(text("SELECT id, updated_at FROM tenants")).fetchall())
            envelopes = [r[0] for r in conn.execute(text("SELECT encrypted_dek FROM tenants"))]
    finally:
        engine.dispose()
    assert _audit_rows(db_file) == []

    target = Fernet.generate_key().decode("ascii")
    proc = _run_cli(tmp_path, _isolated_env(
        tmp_path, db_file, TENANT_MASTER_KEK=legacy, TENANT_MASTER_KEK_NEW=target,
    ))
    assert proc.returncode == 0, (proc.stdout + proc.stderr)[-2000:]

    rows = _audit_rows(db_file)
    assert len(rows) == 1
    row = rows[0]
    assert (row["action"], row["record_id"], row["field_name"]) == ("UPDATE", "*", "encrypted_dek")
    payload = json.loads(row["new_value"])
    assert payload == {
        "operation": "master_kek_rewrap",
        "rewrapped_deks": 2,
        "tenant_ids_sha256": hashlib.sha256(",".join(sorted(deks)).encode("utf-8")).hexdigest(),
    }
    dump = json.dumps(row)
    for secret in (legacy, target, *envelopes, *(d.decode("ascii") for d in deks.values())):
        assert secret not in dump
    assert "gAAAA" not in dump

    engine = create_engine(f"sqlite:///{db_file}")
    try:
        with engine.connect() as conn:
            after = dict(conn.execute(text("SELECT id, updated_at FROM tenants")).fetchall())
    finally:
        engine.dispose()
    assert all(after[tid] != before[tid] for tid in before)


def test_failed_rewrap_writes_no_audit_entry(tmp_path):
    """Gegenprobe N-870-10: scheitert der Lauf (Trigger), gibt es weder DEK-
    Aenderung noch Audit-Eintrag (ein Commit fuer beides)."""
    from sqlalchemy import text

    legacy = WEAK_LEGACY_KEKS[0]
    db_file, _ = _file_db_with_wrapped_tenants(tmp_path, legacy)
    engine = create_engine(f"sqlite:///{db_file}")
    try:
        with engine.begin() as conn:
            conn.execute(text(
                "CREATE TRIGGER trg_block_dek BEFORE UPDATE OF encrypted_dek ON tenants "
                "BEGIN SELECT RAISE(ABORT, 'rewrap blockiert (Test)'); END"
            ))
    finally:
        engine.dispose()
    proc = _run_cli(tmp_path, _isolated_env(
        tmp_path, db_file, TENANT_MASTER_KEK=legacy,
        TENANT_MASTER_KEK_NEW=Fernet.generate_key().decode("ascii"),
    ))
    assert proc.returncode == 1
    assert _audit_rows(db_file) == []


def test_cli_refuses_when_kek_store_exists(tmp_path):
    """N-870-12: Mit vorhandener KEK-Ablage (TENANT_MASTER_KEK_FILE) verweigert
    das CLI den Lauf, bevor etwas geaendert wird (kein Zustand, in dem DB und
    Ablage auseinanderlaufen)."""
    from sqlalchemy import text

    legacy = WEAK_LEGACY_KEKS[0]
    db_file, _ = _file_db_with_wrapped_tenants(tmp_path, legacy)
    store = tmp_path / "tenant-master-kek.dpapi"
    store.write_bytes(b"opaque-test-store")
    engine = create_engine(f"sqlite:///{db_file}")
    try:
        with engine.connect() as conn:
            before = dict(conn.execute(text("SELECT id, encrypted_dek FROM tenants")).fetchall())
    finally:
        engine.dispose()

    target = Fernet.generate_key().decode("ascii")
    proc = _run_cli(tmp_path, _isolated_env(
        tmp_path, db_file, TENANT_MASTER_KEK=legacy, TENANT_MASTER_KEK_NEW=target,
        TENANT_MASTER_KEK_FILE=str(store),
    ))
    out = proc.stdout + proc.stderr
    assert proc.returncode == 2, out[-2000:]
    assert "KEK-Ablage" in proc.stderr and "nichts geaendert" in proc.stderr
    assert legacy not in out and target not in out
    assert store.read_bytes() == b"opaque-test-store"
    assert _audit_rows(db_file) == []
    engine = create_engine(f"sqlite:///{db_file}")
    try:
        with engine.connect() as conn:
            assert dict(conn.execute(text("SELECT id, encrypted_dek FROM tenants")).fetchall()) == before
    finally:
        engine.dispose()

    # Kontrolle: Einstellung gesetzt, aber keine Datei -> Lauf erlaubt.
    store.unlink()
    proc = _run_cli(tmp_path, _isolated_env(
        tmp_path, db_file, TENANT_MASTER_KEK=legacy, TENANT_MASTER_KEK_NEW=target,
        TENANT_MASTER_KEK_FILE=str(store),
    ))
    assert proc.returncode == 0, (proc.stdout + proc.stderr)[-2000:]


# ---------------------------------------------------------------------------
# N-870-13: nur schwache Bestands-Passphrasen; Desktop-Standardablage
# ---------------------------------------------------------------------------


def _envelopes(db_file: Path) -> dict:
    from sqlalchemy import text

    engine = create_engine(f"sqlite:///{db_file}")
    try:
        with engine.connect() as conn:
            return dict(conn.execute(text("SELECT id, encrypted_dek FROM tenants")).fetchall())
    finally:
        engine.dispose()


@pytest.mark.parametrize("kind", ["fernet", "strong_passphrase"])
def test_cli_refuses_valid_source_kek_no_rewrap_needed(tmp_path, kind):
    """Eine gueltige Quelle (Fernet-Key oder starke Passphrase) startet ohnehin;
    ein Rewrap waere nur ein KEK-Wechsel. Exit 2, nichts geaendert."""
    source = (
        Fernet.generate_key().decode("ascii") if kind == "fernet"
        else "eine-starke-bestands-passphrase-k9#Lr2!vQz7@Tm4"
    )
    db_file, _ = _file_db_with_wrapped_tenants(tmp_path, source)
    before = _envelopes(db_file)
    target = Fernet.generate_key().decode("ascii")
    proc = _run_cli(tmp_path, _isolated_env(
        tmp_path, db_file, TENANT_MASTER_KEK=source, TENANT_MASTER_KEK_NEW=target,
    ))
    out = proc.stdout + proc.stderr
    assert proc.returncode == 2, out[-2000:]
    assert "kein Rewrap" in proc.stderr and "nichts geaendert" in proc.stderr
    assert source not in out and target not in out
    assert _envelopes(db_file) == before
    assert _audit_rows(db_file) == []


def test_rewrap_function_refuses_valid_source(Session):
    from services.tenant_crypto import KekRewrapNotNeeded

    source = Fernet.generate_key().decode("ascii")
    _seed_wrapped_tenants(Session, source)
    before = _stored(Session)
    with Session() as db, pytest.raises(KekRewrapNotNeeded):
        rewrap_tenant_deks_to_master_kek(db, source_kek=source, target_kek=Fernet.generate_key())
    assert _stored(Session) == before


@pytest.mark.parametrize("app_dir", ["Ares", "ares-desktop"])
def test_cli_refuses_when_desktop_default_store_exists(tmp_path, app_dir):
    """Desktop-Ablage am Standardort (userData/tenant-master-kek.dpapi), ohne
    TENANT_MASTER_KEK_FILE in der Shell: verweigert, Pfad nicht im Output."""
    legacy = WEAK_LEGACY_KEKS[0]
    db_file, _ = _file_db_with_wrapped_tenants(tmp_path, legacy)
    env = _isolated_env(
        tmp_path, db_file, TENANT_MASTER_KEK=legacy,
        TENANT_MASTER_KEK_NEW=Fernet.generate_key().decode("ascii"),
    )
    store = Path(env["APPDATA"]) / app_dir / "tenant-master-kek.dpapi"
    store.parent.mkdir(parents=True, exist_ok=True)
    store.write_bytes(b"opaque-test-store")
    before = _envelopes(db_file)

    proc = _run_cli(tmp_path, env)
    out = proc.stdout + proc.stderr
    assert proc.returncode == 2, out[-2000:]
    assert "KEK-Ablage" in proc.stderr
    assert str(store) not in out and str(store.parent) not in out, "kein Pfad im Output"
    assert _envelopes(db_file) == before and _audit_rows(db_file) == []
    assert store.read_bytes() == b"opaque-test-store"
