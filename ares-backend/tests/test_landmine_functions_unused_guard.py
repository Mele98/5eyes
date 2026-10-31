"""Mega-Audit (2026-08-04), Security-Dimension: zwei Funktionen im Backend
tragen bereits ausfuehrliche WARNUNG-Docstrings, weil ihre unbedachte
Verwendung schwere, stille Sicherheits-/Datenverlust-Folgen haette:

1. services/auth.py::get_current_tenant_id -- laedt den User NICHT aus der
   DB und prueft daher WEDER token_revoked_before (AUTH-04, Logout-Widerruf)
   NOCH is_active/deleted_at. Als direkte Router-Dependency verwendet
   (`Depends(get_current_tenant_id)` statt `Depends(get_current_user)`)
   wuerde sie die gesamte Token-Revocation-Mechanik lautlos umgehen.

2. services/tenant_crypto.py::rotate_tenant_dek -- ueberschreibt den
   Tenant-DEK SOFORT ohne die alte DEK aufzubewahren. Jedes mit der alten
   DEK verschluesselte Feld wuerde dadurch DAUERHAFT unlesbar, wenn nicht
   VORHER ein echter Re-Encrypt-Flow gebaut wurde. Bleibt bewusst
   vollstaendig ungenutzt.

Beide Warnungen sind nur so lange wahr, wie NIEMAND diese Funktionen
tatsaechlich verdrahtet, ohne die jeweilige Voraussetzung (Re-Encrypt-Flow
bzw. Ersatz-Pruefung fuer Revocation/is_active) zu bauen. Dieser Test macht
das zu einem CI-Guard statt einer reinen Doku-Hoffnung: er scannt den
tatsaechlichen Quellcode und schlaegt fehl, sobald eine der beiden
Landminen aktiviert wird -- so MUSS ein Mensch diesen Test bewusst
anpassen (und damit die fehlende Absicherung nachziehen), statt dass die
Luecke stillschweigend live geht.

SEC-005 (Codex-Audit 2026-08-26) hat `encrypt_for_tenant`/`decrypt_for_tenant`
(NICHT `rotate_tenant_dek`) bewusst genau EINMAL verdrahtet -- fuer neu
angelegte TOTP-Secrets, mit Dual-Read-Fallback fuer bestehende Klartext-
Secrets, siehe `services/totp_secret_storage.py`. Der Guard fuer diese
beiden Funktionen erlaubt jetzt genau diesen einen Integrationspunkt und
schlaegt weiterhin fehl, sobald ein WEITERER Aufrufer auftaucht, ohne
bewusst geprueft zu werden.
"""
from __future__ import annotations

import re
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
ROUTERS_DIR = BACKEND_ROOT / "routers"
SERVICES_DIR = BACKEND_ROOT / "services"
MODELS_DIR = BACKEND_ROOT / "models"

_TENANT_ID_DEPENDENCY_RE = re.compile(r"Depends\(\s*get_current_tenant_id\s*\)")

_ROTATE_DEK_CALL_RE = re.compile(r"\brotate_tenant_dek\s*\(")
_ENCRYPT_DECRYPT_CALL_RE = re.compile(r"\b(encrypt_for_tenant|decrypt_for_tenant)\s*\(")

# SEC-005: der einzige bewusst gebaute, gepruefte Integrationspunkt fuer
# encrypt_for_tenant/decrypt_for_tenant ausserhalb von tenant_crypto.py selbst.
_ALLOWED_ENCRYPT_DECRYPT_CALLER = "totp_secret_storage.py"


def _router_files() -> list[Path]:
    files = sorted(ROUTERS_DIR.glob("*.py"))
    assert len(files) > 5, (
        f"Nur {len(files)} Router-Dateien gefunden -- Pfad/Struktur geaendert? "
        "Guard koennte wirkungslos sein."
    )
    return files


def _non_test_source_files(*, exclude: tuple[str, ...] = ("tenant_crypto.py",)) -> list[Path]:
    files = [
        f for f in sorted(SERVICES_DIR.glob("*.py")) if f.name not in exclude
    ] + sorted(MODELS_DIR.glob("*.py"))
    assert len(files) > 10, (
        f"Nur {len(files)} Quelldateien gefunden -- Pfad/Struktur geaendert? "
        "Guard koennte wirkungslos sein."
    )
    return files


def test_get_current_tenant_id_never_used_as_direct_router_dependency():
    offenders: list[str] = []
    for path in _router_files():
        text = path.read_text(encoding="utf-8")
        if _TENANT_ID_DEPENDENCY_RE.search(text):
            offenders.append(path.name)
    assert not offenders, (
        f"Depends(get_current_tenant_id) direkt als Router-Dependency in "
        f"{offenders} gefunden -- das umgeht AUTH-04 Token-Revocation UND "
        "is_active/deleted_at-Pruefung lautlos (siehe Warnung im Docstring "
        "von services/auth.py::get_current_tenant_id). Verwende "
        "Depends(get_current_user) und leite tenant_id vom geladenen User ab, "
        "oder -- falls diese Dependency wirklich gebraucht wird -- baue "
        "zuerst die fehlenden Revocation-/is_active-Pruefungen nach und "
        "aktualisiere diesen Guard bewusst."
    )


def test_rotate_tenant_dek_never_called_outside_own_module():
    offenders: list[str] = []
    for path in _router_files() + _non_test_source_files():
        text = path.read_text(encoding="utf-8")
        if _ROTATE_DEK_CALL_RE.search(text):
            offenders.append(path.name)
    assert not offenders, (
        f"Aufruf(e) von rotate_tenant_dek ausserhalb von "
        f"services/tenant_crypto.py gefunden: {offenders}. rotate_tenant_dek "
        "ueberschreibt den Tenant-DEK SOFORT ohne Backup der alten DEK -- "
        "jedes damit verschluesselte Live-Feld wuerde ohne einen VORHER "
        "gebauten Re-Encrypt-Flow dauerhaft unlesbar (siehe Warnung im "
        "Docstring von services/tenant_crypto.py::rotate_tenant_dek). Baue den "
        "Re-Encrypt-Flow zuerst, dann aktualisiere diesen Guard bewusst."
    )


def test_encrypt_decrypt_for_tenant_only_called_from_totp_secret_storage():
    """SEC-005: encrypt_for_tenant/decrypt_for_tenant duerfen ausserhalb von
    tenant_crypto.py NUR aus dem einen, bewusst gebauten und getesteten
    Integrationspunkt (services/totp_secret_storage.py) aufgerufen werden.
    Jeder WEITERE Aufrufer muss diesen Guard bewusst erweitern -- statt
    stillschweigend ein weiteres Feld an die Tenant-Krypto zu haengen ohne
    Feldklassifikation/Rotationsvertrag (siehe Audit-Fixvertrag SEC-005)."""
    offenders: list[str] = []
    for path in _router_files() + _non_test_source_files(
        exclude=("tenant_crypto.py", _ALLOWED_ENCRYPT_DECRYPT_CALLER)
    ):
        text = path.read_text(encoding="utf-8")
        matches = _ENCRYPT_DECRYPT_CALL_RE.findall(text)
        if matches:
            offenders.append(f"{path.name}: {sorted(set(matches))}")
    assert not offenders, (
        f"Aufruf(e) von encrypt_for_tenant/decrypt_for_tenant ausserhalb von "
        f"tenant_crypto.py/{_ALLOWED_ENCRYPT_DECRYPT_CALLER} gefunden: {offenders}. "
        "Ein neues Feld an die Tenant-Krypto zu haengen braucht zuerst "
        "Feldklassifikation + Rotationsvertrag (SEC-005-Fixvertrag) -- "
        "aktualisiere diesen Guard erst NACH bewusster Pruefung."
    )


def test_totp_secret_storage_module_actually_calls_encrypt_and_decrypt():
    """Gegenprobe zum Guard oben: der erlaubte Integrationspunkt existiert
    wirklich und ruft tatsaechlich beide Funktionen auf -- sonst waere der
    Guard wirkungslos (Datei umbenannt/Code entfernt, Test bliebe trotzdem
    gruen)."""
    path = SERVICES_DIR / _ALLOWED_ENCRYPT_DECRYPT_CALLER
    assert path.exists(), f"{_ALLOWED_ENCRYPT_DECRYPT_CALLER} nicht gefunden"
    text = path.read_text(encoding="utf-8")
    matches = set(_ENCRYPT_DECRYPT_CALL_RE.findall(text))
    assert matches == {"encrypt_for_tenant", "decrypt_for_tenant"}, (
        f"Erwartete beide Funktionsaufrufe in {_ALLOWED_ENCRYPT_DECRYPT_CALLER}, "
        f"gefunden: {matches}"
    )
