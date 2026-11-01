"""RB-1: Master-KEK beim Erststart erzeugen, per DPAPI ablegen, beim Start laden.

Alle Tests arbeiten auf ``tmp_path`` (Ablage und Datenbank) und mit einer
eigenen Settings-Attrappe -- nie mit der Live-DB, dem echten userData-Ordner
oder den Settings der Test-Session. Die DPAPI wird durch einen Fake ersetzt;
nur die Windows-Tests am Ende machen einen echten DPAPI-Roundtrip, und zwar
ausschliesslich auf Wegwerfdaten in ``tmp_path``.
"""
from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import config
from config import (
    KEK_STORE_ENTROPY,
    KEK_STORE_MAGIC,
    KekStoreError,
    WindowsDpapi,
    ensure_tenant_master_kek,
)


class FakeProtector:
    """Deterministische DPAPI-Attrappe: bindet an "Konto" und Entropie, kein Klartext."""

    def __init__(self, account: str = "konto-a", available: bool = True):
        self.account = account.encode()
        self._available = available
        self.protect_calls = 0

    def available(self) -> bool:
        return self._available

    def _stream(self, entropy: bytes, n: int) -> bytes:
        import hashlib

        out = b""
        counter = 0
        while len(out) < n:
            out += hashlib.sha256(self.account + entropy + counter.to_bytes(4, "big")).digest()
            counter += 1
        return out[:n]

    def protect(self, data: bytes, entropy: bytes) -> bytes:
        self.protect_calls += 1
        body = bytes(a ^ b for a, b in zip(data, self._stream(entropy, len(data))))
        return b"FAKE" + self.account + b"|" + body

    def unprotect(self, blob: bytes, entropy: bytes) -> bytes:
        prefix = b"FAKE" + self.account + b"|"
        if not blob.startswith(prefix):
            raise KekStoreError("falsches Konto")
        body = blob[len(prefix):]
        return bytes(a ^ b for a, b in zip(body, self._stream(entropy, len(body))))


def _cfg(tmp_path: Path, *, kek: str = "", store: Path | None = None, db: Path | None = None,
         database_url: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        tenant_master_kek=kek,
        tenant_master_kek_file=str(store if store is not None else tmp_path / "userData" / "tenant-master-kek.dpapi"),
        db_path=str(db if db is not None else tmp_path / "data" / "ares.db"),
        database_url=database_url,
    )


def _store(cfg) -> Path:
    return Path(cfg.tenant_master_kek_file)


# --------------------------------------------------------------------------
# Erststart / zweiter Start
# --------------------------------------------------------------------------


def test_first_start_generates_exactly_one_kek(tmp_path):
    cfg = _cfg(tmp_path)
    fake = FakeProtector()
    assert ensure_tenant_master_kek(cfg, protector=fake) == "generated"
    kek = cfg.tenant_master_kek
    assert config._is_fernet_key(kek)
    assert fake.protect_calls == 1
    store = _store(cfg)
    assert sorted(p.name for p in store.parent.iterdir()) == [store.name], "keine Temp-Reste"
    raw = store.read_bytes()
    assert raw.startswith(KEK_STORE_MAGIC)
    assert kek.encode() not in raw, "KEK nie im Klartext in der Ablage"
    # Es wird nur die Ablage angelegt -- keine Datenbank.
    assert not Path(cfg.db_path).exists()


def test_generated_kek_is_a_valid_fernet_key_for_tenant_crypto(tmp_path):
    from cryptography.fernet import Fernet

    cfg = _cfg(tmp_path)
    ensure_tenant_master_kek(cfg, protector=FakeProtector())
    token = Fernet(cfg.tenant_master_kek.encode()).encrypt(b"dek")
    assert Fernet(cfg.tenant_master_kek.encode()).decrypt(token) == b"dek"


def test_second_start_loads_the_same_kek_and_never_rewrites(tmp_path):
    fake = FakeProtector()
    first = _cfg(tmp_path)
    ensure_tenant_master_kek(first, protector=fake)
    store = _store(first)
    before = store.read_bytes()
    mtime = store.stat().st_mtime_ns
    # Zweiter Start: die DB existiert inzwischen.
    Path(first.db_path).parent.mkdir(parents=True, exist_ok=True)
    Path(first.db_path).write_bytes(b"SQLite format 3\x00")

    second = _cfg(tmp_path)
    assert ensure_tenant_master_kek(second, protector=fake) == "loaded"
    assert second.tenant_master_kek == first.tenant_master_kek
    assert fake.protect_calls == 1, "kein zweites Erzeugen"
    assert store.read_bytes() == before
    assert store.stat().st_mtime_ns == mtime


def test_disabled_without_store_path_changes_nothing(tmp_path):
    cfg = _cfg(tmp_path)
    cfg.tenant_master_kek_file = ""
    assert ensure_tenant_master_kek(cfg, protector=FakeProtector()) == "disabled"
    assert cfg.tenant_master_kek == ""
    assert list(tmp_path.iterdir()) == []


def test_session_settings_have_no_store_path():
    # Test-Isolation: keine Test-Session darf eine echte Ablage anlegen.
    assert config.settings.tenant_master_kek_file == ""


# --------------------------------------------------------------------------
# Fail-closed: vorhandene Daten, unlesbare Ablage, Widerspruch
# --------------------------------------------------------------------------


@pytest.mark.parametrize("suffix", ["", "-wal"])
def test_existing_db_without_kek_never_generates(tmp_path, suffix):
    db = tmp_path / "data" / "ares.db"
    db.parent.mkdir(parents=True)
    Path(str(db) + suffix).write_bytes(b"x")
    cfg = _cfg(tmp_path, db=db)
    fake = FakeProtector()

    with pytest.raises(KekStoreError) as exc:
        ensure_tenant_master_kek(cfg, protector=fake, require_for_existing_data=True)
    message = str(exc.value)
    assert "existiert" in message and "keine neue KEK" in message and "Migrator" in message
    assert fake.protect_calls == 0
    assert not _store(cfg).exists()
    assert cfg.tenant_master_kek == ""


def test_existing_db_under_predecessor_contract_keeps_legacy_start(tmp_path):
    """Vor W4-c: Bestandsinstallation startet weiter (Rueckfall), aber ohne neue KEK."""
    db = tmp_path / "data" / "ares.db"
    db.parent.mkdir(parents=True)
    db.write_bytes(b"x")
    cfg = _cfg(tmp_path, db=db)
    fake = FakeProtector()
    assert config.KEK_REQUIRED_FOR_EXISTING_DATA is False
    assert ensure_tenant_master_kek(cfg, protector=fake) == "legacy-existing-db"
    assert fake.protect_calls == 0
    assert not _store(cfg).exists()
    assert cfg.tenant_master_kek == ""


def test_server_database_url_counts_as_existing_data(tmp_path):
    cfg = _cfg(tmp_path, database_url="postgresql://u@h/db")
    with pytest.raises(KekStoreError):
        ensure_tenant_master_kek(cfg, protector=FakeProtector(), require_for_existing_data=True)
    assert not _store(cfg).exists()


def test_sqlite_database_url_is_checked_like_database(tmp_path):
    db = tmp_path / "elsewhere" / "x.db"
    cfg = _cfg(tmp_path, database_url=f"sqlite:///{db.as_posix()}")
    assert ensure_tenant_master_kek(cfg, protector=FakeProtector()) == "generated"
    db.parent.mkdir(parents=True)
    db.write_bytes(b"x")
    cfg2 = _cfg(tmp_path, database_url=f"sqlite:///{db.as_posix()}")
    _store(cfg2).unlink()
    with pytest.raises(KekStoreError):
        ensure_tenant_master_kek(cfg2, protector=FakeProtector(), require_for_existing_data=True)


def test_store_of_other_account_aborts_and_is_kept(tmp_path):
    cfg = _cfg(tmp_path)
    ensure_tenant_master_kek(cfg, protector=FakeProtector("konto-a"))
    store = _store(cfg)
    before = store.read_bytes()

    other = _cfg(tmp_path)
    with pytest.raises(KekStoreError) as exc:
        ensure_tenant_master_kek(other, protector=FakeProtector("konto-b"))
    assert "nicht entschluesseln" in str(exc.value) and "KEINE neue KEK" in str(exc.value)
    assert store.read_bytes() == before, "nie ueberschreiben"
    assert other.tenant_master_kek == ""


@pytest.mark.parametrize("content", [b"", b"garbage", KEK_STORE_MAGIC + b"FAKEkonto-a|kaputt"])
def test_corrupt_store_aborts_and_is_kept(tmp_path, content):
    cfg = _cfg(tmp_path)
    store = _store(cfg)
    store.parent.mkdir(parents=True)
    store.write_bytes(content)
    with pytest.raises(KekStoreError):
        ensure_tenant_master_kek(cfg, protector=FakeProtector())
    assert store.read_bytes() == content


def test_explicit_kek_wins_without_store(tmp_path):
    from cryptography.fernet import Fernet

    explicit = Fernet.generate_key().decode()
    cfg = _cfg(tmp_path, kek=explicit)
    fake = FakeProtector()
    assert ensure_tenant_master_kek(cfg, protector=fake) == "configured"
    assert cfg.tenant_master_kek == explicit
    assert not _store(cfg).exists(), "eine extern gelieferte KEK wird nicht still abgelegt"
    assert fake.protect_calls == 0


def test_explicit_kek_contradicting_store_aborts(tmp_path):
    from cryptography.fernet import Fernet

    fake = FakeProtector()
    first = _cfg(tmp_path)
    ensure_tenant_master_kek(first, protector=fake)
    same = _cfg(tmp_path, kek=first.tenant_master_kek)
    assert ensure_tenant_master_kek(same, protector=fake) == "configured"

    other = _cfg(tmp_path, kek=Fernet.generate_key().decode())
    with pytest.raises(KekStoreError) as exc:
        ensure_tenant_master_kek(other, protector=fake)
    assert "widerspricht" in str(exc.value)


def test_no_dpapi_on_first_start_aborts_without_file(tmp_path):
    cfg = _cfg(tmp_path)
    with pytest.raises(KekStoreError):
        ensure_tenant_master_kek(cfg, protector=FakeProtector(available=False))
    assert not _store(cfg).exists()


def test_concurrent_winner_is_loaded_not_overwritten(tmp_path, monkeypatch):
    fake = FakeProtector()
    winner = _cfg(tmp_path)
    ensure_tenant_master_kek(winner, protector=fake)
    winner_bytes = _store(winner).read_bytes()

    # Der Verlierer hat "keine Ablage" gesehen und schreibt gleichzeitig.
    loser = _cfg(tmp_path)
    real_exists = Path.exists
    store = _store(loser)
    calls = {"n": 0}

    def fake_exists(self):
        if self == store and calls["n"] == 0:
            calls["n"] += 1
            return False
        return real_exists(self)

    monkeypatch.setattr(Path, "exists", fake_exists)
    assert ensure_tenant_master_kek(loser, protector=fake) == "loaded"
    assert loser.tenant_master_kek == winner.tenant_master_kek
    assert store.read_bytes() == winner_bytes


def test_failed_read_back_removes_only_the_fresh_store(tmp_path):
    class BrokenUnprotect(FakeProtector):
        def unprotect(self, blob, entropy):
            raise KekStoreError("kaputt")

    cfg = _cfg(tmp_path)
    with pytest.raises(KekStoreError) as exc:
        ensure_tenant_master_kek(cfg, protector=BrokenUnprotect())
    assert "zuruecklesen" in str(exc.value)
    assert not _store(cfg).exists()
    assert cfg.tenant_master_kek == ""


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX-Dateirechte")
def test_store_file_mode_is_owner_only_on_posix(tmp_path):
    cfg = _cfg(tmp_path)
    ensure_tenant_master_kek(cfg, protector=FakeProtector())
    assert _store(cfg).stat().st_mode & 0o777 == 0o600


# --------------------------------------------------------------------------
# DPAPI-Scope und echter Roundtrip (nur Windows, nur Wegwerfdaten)
# --------------------------------------------------------------------------


def test_dpapi_uses_user_scope_flags_only():
    assert WindowsDpapi.flags & config.CRYPTPROTECT_LOCAL_MACHINE == 0
    assert WindowsDpapi.flags == config.CRYPTPROTECT_UI_FORBIDDEN


@pytest.mark.skipif(sys.platform != "win32", reason="DPAPI nur unter Windows")
def test_real_dpapi_roundtrip_on_throwaway_data():
    dpapi = WindowsDpapi()
    secret = b"wegwerf-" + bytes(range(32))
    blob = dpapi.protect(secret, KEK_STORE_ENTROPY)
    assert secret not in blob
    assert dpapi.unprotect(blob, KEK_STORE_ENTROPY) == secret
    with pytest.raises(KekStoreError):
        dpapi.unprotect(blob, b"andere-entropie")


@pytest.mark.skipif(sys.platform != "win32", reason="DPAPI nur unter Windows")
def test_real_dpapi_first_and_second_start(tmp_path):
    first = _cfg(tmp_path)
    assert ensure_tenant_master_kek(first) == "generated"
    second = _cfg(tmp_path)
    assert ensure_tenant_master_kek(second) == "loaded"
    assert second.tenant_master_kek == first.tenant_master_kek
    assert first.tenant_master_kek.encode() not in _store(first).read_bytes()


def test_non_windows_dpapi_refuses():
    if sys.platform == "win32":
        pytest.skip("nur ausserhalb von Windows")
    with pytest.raises(KekStoreError):
        WindowsDpapi().protect(b"x", KEK_STORE_ENTROPY)


# --------------------------------------------------------------------------
# Lifespan: Reihenfolge, Abbruch, kein Klartext im Log
# --------------------------------------------------------------------------


def _run_lifespan(monkeypatch, cfg_attrs: dict, protector):
    import main

    calls: list[str] = []
    for key, value in cfg_attrs.items():
        monkeypatch.setattr(main.settings, key, value)
    monkeypatch.setattr(main, "configure_logging", lambda: None)

    def fake_init_db():
        calls.append("init_db")
        raise _StopAfterInitDb

    monkeypatch.setattr(main, "init_db", fake_init_db)
    real_ensure = config.ensure_tenant_master_kek

    def ensure_with_fake(cfg):
        calls.append("ensure")
        return real_ensure(cfg, protector=protector)

    monkeypatch.setattr(main, "ensure_tenant_master_kek", ensure_with_fake)

    async def run():
        async with main.lifespan(main.app):
            pass

    with pytest.raises((KekStoreError, _StopAfterInitDb)) as exc:
        asyncio.run(run())
    return calls, exc.value


class _StopAfterInitDb(Exception):
    pass


def test_lifespan_provisions_before_init_db_and_never_logs_the_kek(tmp_path, monkeypatch, caplog):
    store = tmp_path / "userData" / "tenant-master-kek.dpapi"
    attrs = {
        "tenant_master_kek": "",
        "tenant_master_kek_file": str(store),
        "db_path": str(tmp_path / "data" / "ares.db"),
        "database_url": None,
    }
    caplog.set_level(logging.DEBUG)
    calls, _ = _run_lifespan(monkeypatch, attrs, FakeProtector())
    assert calls == ["ensure", "init_db"]
    import main

    kek = main.settings.tenant_master_kek
    assert config._is_fernet_key(kek)
    assert "Master-KEK: generated" in caplog.text
    assert kek not in caplog.text
    for record in caplog.records:
        assert kek not in record.getMessage()


def test_lifespan_aborts_before_init_db_on_unreadable_store(tmp_path, monkeypatch, caplog):
    store = tmp_path / "userData" / "tenant-master-kek.dpapi"
    store.parent.mkdir(parents=True)
    store.write_bytes(KEK_STORE_MAGIC + b"fremd")
    attrs = {
        "tenant_master_kek": "",
        "tenant_master_kek_file": str(store),
        "db_path": str(tmp_path / "data" / "ares.db"),
        "database_url": None,
    }
    caplog.set_level(logging.DEBUG)
    calls, err = _run_lifespan(monkeypatch, attrs, FakeProtector())
    assert isinstance(err, KekStoreError)
    assert calls == ["ensure"], "init_db darf nicht laufen"
    assert "Start abgebrochen" in caplog.text
    assert store.read_bytes() == KEK_STORE_MAGIC + b"fremd"
