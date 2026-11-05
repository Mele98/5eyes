"""H-129 Teil C (2026-11-05): die Master-KEK-Pruefung lehnt auch Werte ab,
die aus dem oeffentlichen Platzhalter ABGELEITET sind.

Vorher verglich config.tenant_master_kek_problem nur den Rohwert mit
DEFAULT_SECRET_KEY. Der Platzhalter ist kein gueltiger Fernet-Key;
services.tenant_crypto leitet daraus per PBKDF2 (KEK-Vertrag v2) einen
Fernet-Key ab. Wer genau diesen abgeleiteten Key als TENANT_MASTER_KEK setzte,
verschluesselte mit demselben, oeffentlich rekonstruierbaren Schluessel wie der
Platzhalter -- und die Pruefung liess ihn durch.
"""
from __future__ import annotations

import base64
import re
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import config
from config import DEFAULT_SECRET_KEY, KekStoreError, require_tenant_master_kek, tenant_master_kek_problem
from services import tenant_crypto


def _derive_like_tenant_crypto(raw: str) -> str:
    # Unabhaengig nachgerechnet (PBKDF2-HMAC-SHA256, v2-Salt, 200'000 Iterationen),
    # nicht ueber die zu pruefende config-Funktion.
    import hashlib

    derived = hashlib.pbkdf2_hmac("sha256", raw.encode("utf-8"), b"ares.tenant.kek.pbkdf2.v2", 200_000)
    return base64.urlsafe_b64encode(derived).decode("ascii")


class _Cfg:
    def __init__(self, kek: str, secret_key: str = "jwt-secret-for-tests-only-0123456789"):
        self.tenant_master_kek = kek
        self.secret_key = secret_key


def test_placeholder_derived_fernet_kek_is_rejected():
    derived = _derive_like_tenant_crypto(DEFAULT_SECRET_KEY)
    problem = tenant_master_kek_problem(derived)
    assert problem is not None
    assert "Platzhalter" in problem
    assert derived not in problem, "Die Meldung darf den Schluessel nicht ausgeben"
    with pytest.raises(KekStoreError) as exc:
        require_tenant_master_kek(_Cfg(derived))
    assert derived not in str(exc.value)


def test_placeholder_derived_kek_is_rejected_in_tenant_crypto_too():
    derived = _derive_like_tenant_crypto(DEFAULT_SECRET_KEY)
    with pytest.raises(tenant_crypto.TenantCryptoError):
        tenant_crypto._resolve_master_kek(derived)


def test_derived_kek_with_lenient_base64_spelling_is_rejected():
    """urlsafe_b64decode ueberliest fremde Zeichen: eine andere Schreibweise
    desselben Schluesselmaterials darf die Pruefung nicht umgehen."""
    derived = _derive_like_tenant_crypto(DEFAULT_SECRET_KEY)
    variant = derived[:10] + "\n" + derived[10:]
    assert variant != derived
    assert tenant_master_kek_problem(variant) is not None


def test_secret_key_derived_kek_is_rejected():
    secret = "ein-langer-jwt-schluessel-der-kein-fernet-key-ist"
    derived = _derive_like_tenant_crypto(secret)
    problem = tenant_master_kek_problem(derived, secret_key=secret)
    assert problem is not None and "SECRET_KEY" in problem
    assert derived not in problem and secret not in problem


def test_raw_placeholder_still_rejected_with_original_message():
    problem = tenant_master_kek_problem(DEFAULT_SECRET_KEY)
    assert problem is not None and "oeffentliche Platzhalter" in problem


def test_independent_kek_is_accepted():
    """Gegenprobe: ein eigener Fernet-Key und eine eigene Passphrase bleiben zulaessig."""
    from cryptography.fernet import Fernet

    assert tenant_master_kek_problem(Fernet.generate_key().decode("ascii")) is None
    assert tenant_master_kek_problem("eine-eigene-lange-passphrase-fuer-den-test") is None
    require_tenant_master_kek(_Cfg(Fernet.generate_key().decode("ascii")))


def test_check_uses_the_same_derivation_as_tenant_crypto():
    """Drift-Schutz: Startpruefung und tenant_crypto teilen Ableitung und Konstanten."""
    assert tenant_crypto._KEK_KDF_SALT == config.TENANT_KEK_KDF_SALT
    assert tenant_crypto._KEK_KDF_ITERATIONS == config.TENANT_KEK_KDF_ITERATIONS
    passphrase = "drift-schutz-passphrase-fuer-den-vergleich-01"
    assert tenant_crypto._resolve_master_kek(passphrase) == config.effective_tenant_master_kek(
        passphrase.encode("utf-8")
    )
    assert config.effective_tenant_master_kek(DEFAULT_SECRET_KEY.encode("utf-8")).decode("ascii") == (
        _derive_like_tenant_crypto(DEFAULT_SECRET_KEY)
    )


# ---------------------------------------------------------------------------
# N-870-2: fruehere Ableitungen des Platzhalters (gepinnt als SHA-256 des
# Schluesselmaterials)
# ---------------------------------------------------------------------------


def _saltless_sha256_kek(raw: str) -> str:
    """Ableitung vor #355: url-safe-Base64 des saltlosen SHA-256."""
    import hashlib

    return base64.urlsafe_b64encode(hashlib.sha256(raw.encode("utf-8")).digest()).decode("ascii")


def test_saltless_sha256_placeholder_kek_is_rejected():
    derived = _saltless_sha256_kek(DEFAULT_SECRET_KEY)
    problem = tenant_master_kek_problem(derived)
    assert problem is not None and "frueheren" in problem
    assert derived not in problem
    with pytest.raises(tenant_crypto.TenantCryptoError):
        tenant_crypto._resolve_master_kek(derived)


def test_pinned_saltless_hash_is_the_known_answer():
    """Der gepinnte Wert ist nachrechenbar (kein Tippfehler im Pin)."""
    import hashlib

    material = hashlib.sha256(DEFAULT_SECRET_KEY.encode("utf-8")).digest()
    assert hashlib.sha256(material).hexdigest() in config._KNOWN_PUBLIC_KEK_MATERIAL_SHA256


def test_any_pinned_material_is_rejected(monkeypatch):
    """Mechanik fuer den v1-Pin: der alte Salt steht nicht im Repo (Altname);
    geprueft wird, dass jedes Material mit gepinntem SHA-256 abgelehnt wird."""
    import hashlib

    from cryptography.fernet import Fernet

    key = Fernet.generate_key().decode("ascii")
    assert tenant_master_kek_problem(key) is None
    pinned = hashlib.sha256(base64.urlsafe_b64decode(key)).hexdigest()
    monkeypatch.setattr(
        config, "_KNOWN_PUBLIC_KEK_MATERIAL_SHA256",
        config._KNOWN_PUBLIC_KEK_MATERIAL_SHA256 | {pinned},
    )
    problem = tenant_master_kek_problem(key)
    assert problem is not None and key not in problem


def test_pin_set_holds_only_hashes():
    assert len(config._KNOWN_PUBLIC_KEK_MATERIAL_SHA256) == 2
    assert all(re_hex(v) for v in config._KNOWN_PUBLIC_KEK_MATERIAL_SHA256)


def re_hex(value: str) -> bool:
    import re

    return re.fullmatch(r"[0-9a-f]{64}", value) is not None


# ---------------------------------------------------------------------------
# N-870-4: Platzhalter aus Deploy-Vorlagen, Platzhalter-Muster, schwache
# Passphrasen. Die Vorlagenwerte werden aus den Dateien abgeleitet, nicht
# hart kodiert: eine neue oder geaenderte Vorlage wird automatisch geprueft.
# ---------------------------------------------------------------------------

_REPO_ROOT = BACKEND_ROOT.parent
_TEMPLATE_LINE = re.compile(
    r"^\s*(?:export\s+)?(TENANT_MASTER_KEK|SECRET_KEY|DB_KEY)\s*=\s*(.*?)\s*$"
)
_TEMPLATE_TEXT_SUFFIXES = {".md", ".ps1", ".sh", ".yml", ".yaml", ".txt", ".env"}


def _is_template_file(path: Path) -> bool:
    rel = path.relative_to(_REPO_ROOT).as_posix()
    if "node_modules" in path.parts or ".git" in path.parts or "/tests/" in f"/{rel}":
        return False
    if path.name.endswith(".example"):
        return True
    if path.suffix not in _TEMPLATE_TEXT_SUFFIXES:
        return False
    return rel.startswith(("docs/deploy/", "docs/deployment/")) or path.parent == _REPO_ROOT / "docs"


def _template_values() -> list[tuple[str, str, str]]:
    found = []
    for path in sorted(_REPO_ROOT.rglob("*")):
        if not path.is_file() or not _is_template_file(path):
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            match = _TEMPLATE_LINE.match(line)
            if match:
                value = match.group(2).strip().strip("'\"")
                found.append((f"{path.relative_to(_REPO_ROOT).as_posix()}:{lineno}", match.group(1), value))
    return found


def test_template_scan_finds_the_known_templates():
    sources = {src.split(":", 1)[0] for src, _, _ in _template_values()}
    assert {
        "ares-backend/.env.example",
        "docs/deploy/.env.staging.example",
        "docs/deployment/tier1-self-hosted.md",
    } <= sources


@pytest.mark.parametrize("source,key,value", _template_values(), ids=lambda v: str(v)[:60])
def test_every_template_placeholder_is_rejected_as_kek(source, key, value):
    """Jeder Wert von TENANT_MASTER_KEK, SECRET_KEY oder DB_KEY in einer
    Deploy-Vorlage wird als Master-KEK abgelehnt, ohne Ausgabe des Werts."""
    problem = tenant_master_kek_problem(value)
    assert problem is not None, f"{source} ({key}) waere als KEK akzeptiert"
    if value.strip():
        assert value not in problem


_GENERATOR_COMMAND = (
    'python -c "from cryptography.fernet import Fernet; '
    'print(Fernet.generate_key().decode())"'
)


@pytest.mark.parametrize("value", [
    # N-870-6/N-870-7: nur Ganzwert-Formen, nie Teilstrings
    "__IRGENDWAS_EINSETZEN_BITTE_LANG_GENUG__",
    "<hier-den-echten-schluessel-eintragen-0123456789>",
    "changeme", "CHANGE_ME", "change-me", "Change Me",
    "replace_me", "REPLACE-ME",
    "bitte ersetzen", "BITTE_ERSETZEN", "Bitte-Ersetzen",
    "example", "EXAMPLE", "placeholder", "Placeholder",
    "xxx", "XXXXXXXX", "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
    "  changeme  ",
    "${TENANT_MASTER_KEK}",
    "${TENANT_MASTER_KEK:-ein-langer-default-wert-0123456789}",
    "%TENANT_MASTER_KEK%",
    "%ein-langer-windows-ausdruck-0123456789abcdef%",
    "$(openssl rand -base64 32)",
    '$(python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")',
    "$(cat /run/secrets/tenant-master-kek-langer-pfad)",
    # woertlicher Befehl aus der eigenen KEK-Fehlermeldung (N-870-8)
    _GENERATOR_COMMAND,
    f"'{_GENERATOR_COMMAND}'",
    "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())",
    'python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key())"',
])
def test_obvious_placeholder_patterns_are_rejected(value):
    problem = tenant_master_kek_problem(value)
    assert problem is not None and "Platzhalter" in problem, value
    assert value.strip() not in problem


def test_generator_command_from_own_message_is_rejected():
    """Der Befehl steht so in MISSING_TENANT_MASTER_KEK_MESSAGE; wer ihn statt
    seiner Ausgabe in die .env kopiert, darf nicht starten (dotenv fuehrt
    nichts aus)."""
    assert _GENERATOR_COMMAND in config.MISSING_TENANT_MASTER_KEK_MESSAGE
    assert len(_GENERATOR_COMMAND) >= 32 and len(set(_GENERATOR_COMMAND)) >= 10
    assert tenant_master_kek_problem(_GENERATOR_COMMAND) is not None


@pytest.mark.parametrize("value", [
    # Enthaelt ein frueheres Muster nur als Teilstring -> starke Passphrase
    "9fK2-Replacement-Policy-42-vQz7Tm4Wp8NdHs6Yb3",
    "Mein Bitteres Geheimnis liegt im Keller 2026!",
    "Sexxxy-Tarantula-Orbit-73-Quarz-Fjord-Libelle",
    "k9#Lr2!vQz7@bitte@Tm4$Wp8^Nd1&Hs6*Yb3%",
    "k9#Lr2!vQz7@replace@Tm4$Wp8^Nd1&Hs6*Yb3%",
    "k9#Lr2!vQz7@example@Tm4$Wp8^Nd1&Hs6*Yb3%",
    "k9#Lr2!vQz7@placeholder@Tm4$Wp8^Nd1&Hs6*Yb3",
    "k9#Lr2!vQz7@ersetzen@Tm4$Wp8^Nd1&Hs6*Yb3%",
    "k9#Lr2!vQz7@changeme@Tm4$Wp8^Nd1&Hs6*Yb3%",
    "k9#Lr2!vQz7@xxx@Tm4$Wp8^Nd1&Hs6*Yb3%-lang",
    "k9#Lr2!vQz7%Tm4$Wp8^Nd1&Hs6*Yb3-endet-ohne",
    "_k9#Lr2!vQz7@Tm4$Wp8^Nd1&Hs6*Yb3%-unterstrich_",
])
def test_patterns_are_not_applied_as_substrings(value):
    """N-870-7: Muster nur auf den ganzen Wert. Vorher abgelehnt (Teilstring),
    jetzt zulaessig."""
    assert tenant_master_kek_problem(value) is None


def test_token_urlsafe_48_is_never_rejected():
    """N-870-7 Statistik: 50'000 Werte im Format secrets.token_urlsafe(48)
    (deterministischer Seed) bestehen Muster- und Staerkeregel. Die volle
    Pruefung (mit PBKDF2) laeuft fuer eine Stichprobe.

    Gegenprobe im selben Satz: die frueheren Teilstring-Muster haetten einen
    Teil davon abgelehnt (sonst waere die Stichprobe wertlos)."""
    import random

    rng = random.Random(8707)
    values = [
        base64.urlsafe_b64encode(rng.randbytes(48)).rstrip(b"=").decode("ascii")
        for _ in range(50_000)
    ]
    assert all(len(v) == 64 for v in values)
    rejected = [
        i for i, v in enumerate(values)
        if config._looks_like_kek_placeholder(v) or config._kek_passphrase_too_weak(v)
    ]
    assert rejected == []
    old_substring = re.compile(r"change[\W_]*me|replace|ersetzen|bitte|example|placeholder|xxx", re.I)
    assert sum(1 for v in values if old_substring.search(v)) > 0
    for v in values[:25]:
        assert tenant_master_kek_problem(v) is None


@pytest.mark.parametrize("value", [
    "kurz-aber-zufaellig-9f3K",                 # zu kurz
    "abababababababababababababababababab",     # lang, aber zu wenig Vielfalt
])
def test_weak_passphrases_are_rejected(value):
    problem = tenant_master_kek_problem(value)
    assert problem is not None and "zu schwach" in problem and value not in problem
    # N-870-6: die Meldung nennt den Weg fuer Bestandsinstallationen.
    assert "rewrap_tenant_master_kek.py" in problem


def test_strong_passphrase_and_fernet_keys_are_accepted():
    """Gegenprobe: Muster und Laengenregel gelten nur fuer Passphrasen; ein
    gueltiger Fernet-Key wird nicht auf Muster geprueft (zufaelliges Base64
    darf z. B. "xxx" enthalten)."""
    from cryptography.fernet import Fernet

    assert tenant_master_kek_problem("k9#Lr2!vQz7@Tm4$Wp8^Nd1&Hs6*Yb3%") is None
    raw =base64.urlsafe_b64encode(b"\xc7\x1c\x71" + bytes(range(1, 30))).decode("ascii")
    assert raw.lower().startswith("xxx")
    assert tenant_master_kek_problem(raw) is None
    for _ in range(50):
        assert tenant_master_kek_problem(Fernet.generate_key().decode("ascii")) is None
