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
        assert rewrap_tenant_deks_to_master_kek(db, source_kek=legacy, target_kek=target) == 2
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


def test_cli_rewraps_from_configured_kek(Session, monkeypatch, capsys):
    import database
    monkeypatch.syspath_prepend(str(BACKEND_ROOT / "scripts"))
    import rewrap_tenant_master_kek as cli

    legacy = WEAK_LEGACY_KEKS[0]
    deks = _seed_wrapped_tenants(Session, legacy)
    target = Fernet.generate_key().decode("ascii")
    monkeypatch.setattr(database, "SessionLocal", Session)
    monkeypatch.setattr(config.settings, "tenant_master_kek", legacy)
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
