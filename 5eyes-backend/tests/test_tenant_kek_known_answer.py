"""AF-2: Known-Answer-Test (KAT) fuer die Tenant-Master-KEK-Ableitung.

Warum: ``services/tenant_crypto.py`` leitet einen Passphrase-KEK per
PBKDF2-HMAC-SHA256 mit einem festen App-Salt ab. Der bisherige Test
(``test_tenant_crypto.py``) importiert Salt und Iterationszahl und rechnet
damit nach -- eine Aenderung des Salts (z.B. ein Umbenennen) bliebe dort
gruen, wuerde aber jede gespeicherte ``tenants.encrypted_dek`` und damit
jedes ``enc1:``-TOTP-Secret unlesbar machen.

Dieser Test importiert die KDF-Parameter bewusst NICHT. Er prueft das
Ergebnis gegen eingefrorene Erwartungswerte:

* SHA-256-Fingerprint des abgeleiteten (bzw. direkt verwendeten) KEK,
* ein fester Fernet-Ciphertext eines festen Test-DEK, der entschluesselt
  werden muss,
* ein fester ``enc1:``-TOTP-Ciphertext unter diesem DEK (Ende-zu-Ende ueber
  ``load_totp_secret``).

Alle Werte sind reine Testwerte (kein echtes Secret). Die Vektoren wurden
einmalig mit dem Code-Stand von origin/develop erzeugt; sie duerfen NUR mit
einem expliziten Migrationsentscheid (Rewrap aller DEKs) geaendert werden.
"""
from __future__ import annotations

import datetime
import hashlib
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

pytest.importorskip("cryptography.fernet")

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base  # noqa: E402
from main import app  # noqa: F401,E402  (registriert alle Models)
from models.tenant import Tenant  # noqa: E402
from models.users import User  # noqa: E402
import services.tenant_crypto as tenant_crypto  # noqa: E402
from services.tenant_crypto import (  # noqa: E402
    TenantCryptoError,
    _decrypt_dek,
    _resolve_master_kek,
    get_tenant_dek,
)
from services.totp_secret_storage import load_totp_secret  # noqa: E402

# ---------------------------------------------------------------------------
# Eingefrorene Testvektoren (NICHT neu berechnen -- siehe Modul-Docstring)
# ---------------------------------------------------------------------------

# Passphrase-Pfad (kein gueltiger Fernet-Key -> PBKDF2-Ableitung).
KAT_PASSPHRASE = "kat-only-test-passphrase-not-a-real-secret"
KAT_PASSPHRASE_KEK_SHA256 = (
    "19bd7045ad5375904d3b1bba7931291f1f3112ca976c779c193abea694aee363"
)

# Fernet-Key-Pfad (gueltiger Fernet-Key -> direkte Verwendung, keine KDF).
# Bytes 0x00..0x1f, urlsafe-base64.
KAT_FERNET_KEK = "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8="
KAT_FERNET_KEK_SHA256 = (
    "905f28def18eaac05ae6f12b2c3452744afaf626da1343d57b395b544e0519b6"
)

# Fester Test-DEK (Bytes 0x64..0x83, urlsafe-base64 = Fernet-Key-Format).
KAT_DEK = b"ZGVmZ2hpamtsbW5vcHFyc3R1dnd4eXp7fH1-f4CBgoM="

# KAT_DEK, Fernet-verpackt unter dem jeweiligen KEK (Zeitstempel 2026-01-01).
KAT_ENCRYPTED_DEK_PASSPHRASE = (
    "gAAAAABpVbkAKElylLYRD15rfqeAoZaRufYjhQSddB_jjSaHoivzAbffPT1QNh8KFPj9fsU8"
    "U8sgJm-0yPZXRxIW8mS7AozE4P03t47vXKELDsW81DbyNsItNvimNxV1r5EhujrbdPFM"
)
KAT_ENCRYPTED_DEK_FERNET = (
    "gAAAAABpVbkAYsFG6GWHi9WmRGmeluDsTXWt9lK5Miicd-f1MgI6d0UZELxwLd6CSPbVolo4"
    "XDHmkGvnvhHeCB8e3_qKU-AbLjtPAWhlKCMLpo8BG84gBLkr6WRufOe6IqHwB2HTINbn"
)

# Test-TOTP-Secret (RFC-Beispielwert), Fernet-verschluesselt unter KAT_DEK.
KAT_TOTP_PLAINTEXT = "JBSWY3DPEHPK3PXP"
KAT_TOTP_STORED = (
    "enc1:gAAAAABpVbkA4Cn_G1bHrcEXnsBWcUW8n4-e9FtkflWD95t86In16HxzPZEaGYB52SYf"
    "z0IzDQiAw-4-wOGRQV-S_7yKc2DnuuM3Oz76SIYJ6Wy0rsdZshU="
)

# Ein beliebiger anderer Salt fuer die Negativkontrolle (Struktur wie ein
# naheliegendes Umbenennen, markenneutral).
_OTHER_SALT = b"renamed.tenant.kek.pbkdf2.v1"


def _fp(key: bytes) -> str:
    return hashlib.sha256(key).hexdigest()


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


@pytest.fixture
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'tenant-kek-kat.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        yield Session
    finally:
        engine.dispose()


def _seed_tenant(db, tenant_id: str, encrypted_dek: str) -> None:
    db.add(
        Tenant(
            id=tenant_id,
            display_name="KAT Firm",
            slug=tenant_id.lower(),
            hosting_tier="tier2",
            license_status="active",
            max_users=10,
            is_active=1,
            encrypted_dek=encrypted_dek,
            dek_version=1,
            created_at=_now(),
            updated_at=_now(),
        )
    )
    db.commit()


# ---------------------------------------------------------------------------
# Passphrase-/PBKDF2-Pfad
# ---------------------------------------------------------------------------


def test_passphrase_kek_matches_frozen_fingerprint():
    assert _fp(_resolve_master_kek(KAT_PASSPHRASE)) == KAT_PASSPHRASE_KEK_SHA256


def test_passphrase_kek_decrypts_frozen_dek_ciphertext():
    assert _decrypt_dek(KAT_ENCRYPTED_DEK_PASSPHRASE, KAT_PASSPHRASE) == KAT_DEK


def test_passphrase_kek_decrypts_stored_tenant_dek_and_totp_secret(
    session_factory, monkeypatch
):
    # Ende-zu-Ende wie im Betrieb: KEK aus der Umgebung, DEK aus der Tenant-
    # Zeile, TOTP-Secret aus der User-Zeile (enc1:).
    monkeypatch.setenv("TENANT_MASTER_KEK", KAT_PASSPHRASE)
    Session = session_factory
    with Session() as db:
        _seed_tenant(db, "kat-pass", KAT_ENCRYPTED_DEK_PASSPHRASE)
        assert get_tenant_dek(db, "kat-pass") == KAT_DEK
        user = User(tenant_id="kat-pass", totp_secret=KAT_TOTP_STORED)
        assert load_totp_secret(db, user) == KAT_TOTP_PLAINTEXT


def test_negative_control_changed_salt_breaks_passphrase_kat(
    session_factory, monkeypatch
):
    """Belegt, dass der KAT ein geaendertes Salt erkennt (nicht nur gruen ist)."""
    monkeypatch.setattr(tenant_crypto, "_KEK_KDF_SALT", _OTHER_SALT)
    assert _fp(_resolve_master_kek(KAT_PASSPHRASE)) != KAT_PASSPHRASE_KEK_SHA256
    with pytest.raises(TenantCryptoError):
        _decrypt_dek(KAT_ENCRYPTED_DEK_PASSPHRASE, KAT_PASSPHRASE)

    # Und die stille Folge im Betrieb: das TOTP-Secret wird unlesbar ("").
    monkeypatch.setenv("TENANT_MASTER_KEK", KAT_PASSPHRASE)
    with session_factory() as db:
        _seed_tenant(db, "kat-salt", KAT_ENCRYPTED_DEK_PASSPHRASE)
        user = User(tenant_id="kat-salt", totp_secret=KAT_TOTP_STORED)
        assert load_totp_secret(db, user) == ""


def test_negative_control_changed_iterations_breaks_passphrase_kat(monkeypatch):
    monkeypatch.setattr(tenant_crypto, "_KEK_KDF_ITERATIONS", 100_000)
    assert _fp(_resolve_master_kek(KAT_PASSPHRASE)) != KAT_PASSPHRASE_KEK_SHA256
    with pytest.raises(TenantCryptoError):
        _decrypt_dek(KAT_ENCRYPTED_DEK_PASSPHRASE, KAT_PASSPHRASE)


# ---------------------------------------------------------------------------
# Fernet-Key-Pfad (keine KDF)
# ---------------------------------------------------------------------------


def test_fernet_kek_is_used_directly_and_matches_frozen_fingerprint():
    resolved = _resolve_master_kek(KAT_FERNET_KEK)
    assert resolved == KAT_FERNET_KEK.encode("ascii")
    assert _fp(resolved) == KAT_FERNET_KEK_SHA256


def test_fernet_kek_decrypts_frozen_dek_ciphertext(session_factory, monkeypatch):
    assert _decrypt_dek(KAT_ENCRYPTED_DEK_FERNET, KAT_FERNET_KEK) == KAT_DEK
    monkeypatch.setenv("TENANT_MASTER_KEK", KAT_FERNET_KEK)
    with session_factory() as db:
        _seed_tenant(db, "kat-fern", KAT_ENCRYPTED_DEK_FERNET)
        assert get_tenant_dek(db, "kat-fern") == KAT_DEK
        user = User(tenant_id="kat-fern", totp_secret=KAT_TOTP_STORED)
        assert load_totp_secret(db, user) == KAT_TOTP_PLAINTEXT


def test_fernet_kek_path_is_independent_of_kdf_parameters(monkeypatch):
    # Ein Fernet-KEK darf NIE durch die KDF laufen: Salt/Iterationen aendern
    # darf diesen Pfad nicht beruehren.
    monkeypatch.setattr(tenant_crypto, "_KEK_KDF_SALT", _OTHER_SALT)
    monkeypatch.setattr(tenant_crypto, "_KEK_KDF_ITERATIONS", 100_000)
    assert _fp(_resolve_master_kek(KAT_FERNET_KEK)) == KAT_FERNET_KEK_SHA256
    assert _decrypt_dek(KAT_ENCRYPTED_DEK_FERNET, KAT_FERNET_KEK) == KAT_DEK


def test_paths_are_not_interchangeable():
    # Ein unter dem Passphrase-KEK verpackter DEK darf mit dem Fernet-KEK
    # nicht entschluesselbar sein und umgekehrt.
    with pytest.raises(TenantCryptoError):
        _decrypt_dek(KAT_ENCRYPTED_DEK_PASSPHRASE, KAT_FERNET_KEK)
    with pytest.raises(TenantCryptoError):
        _decrypt_dek(KAT_ENCRYPTED_DEK_FERNET, KAT_PASSPHRASE)
