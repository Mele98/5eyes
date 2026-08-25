"""Mega-Audit (2026-08-04), Security-Dimension: zwei Funktionen im Backend
tragen bereits ausfuehrliche WARNUNG-Docstrings, weil ihre unbedachte
Verwendung schwere, stille Sicherheits-/Datenverlust-Folgen haette:

1. services/auth.py::get_current_tenant_id -- laedt den User NICHT aus der
   DB und prueft daher WEDER token_revoked_before (AUTH-04, Logout-Widerruf)
   NOCH is_active/deleted_at. Als direkte Router-Dependency verwendet
   (`Depends(get_current_tenant_id)` statt `Depends(get_current_user)`)
   wuerde sie die gesamte Token-Revocation-Mechanik lautlos umgehen.

2. services/tenant_crypto.py::rotate_tenant_dek/encrypt_for_tenant/
   decrypt_for_tenant -- rotate_tenant_dek ueberschreibt den Tenant-DEK
   SOFORT ohne die alte DEK aufzubewahren. Jedes mit der alten DEK
   verschluesselte Feld wuerde dadurch DAUERHAFT unlesbar, wenn nicht VORHER
   ein echter Re-Encrypt-Flow gebaut wurde. Stand Audit: kein Live-Feld
   nutzt diese Funktionen.

Beide Warnungen sind nur so lange wahr, wie NIEMAND diese Funktionen
tatsaechlich verdrahtet, ohne die jeweilige Voraussetzung (Re-Encrypt-Flow
bzw. Ersatz-Pruefung fuer Revocation/is_active) zu bauen. Dieser Test macht
das zu einem CI-Guard statt einer reinen Doku-Hoffnung: er scannt den
tatsaechlichen Quellcode und schlaegt fehl, sobald eine der beiden
Landminen aktiviert wird -- so MUSS ein Mensch diesen Test bewusst
anpassen (und damit die fehlende Absicherung nachziehen), statt dass die
Luecke stillschweigend live geht.
"""
from __future__ import annotations

import re
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
ROUTERS_DIR = BACKEND_ROOT / "routers"
SERVICES_DIR = BACKEND_ROOT / "services"
MODELS_DIR = BACKEND_ROOT / "models"

_TENANT_ID_DEPENDENCY_RE = re.compile(r"Depends\(\s*get_current_tenant_id\s*\)")

_TENANT_CRYPTO_CALL_RE = re.compile(
    r"\b(rotate_tenant_dek|encrypt_for_tenant|decrypt_for_tenant)\s*\("
)


def _router_files() -> list[Path]:
    files = sorted(ROUTERS_DIR.glob("*.py"))
    assert len(files) > 5, (
        f"Nur {len(files)} Router-Dateien gefunden -- Pfad/Struktur geaendert? "
        "Guard koennte wirkungslos sein."
    )
    return files


def _non_test_source_files() -> list[Path]:
    files = [
        f for f in sorted(SERVICES_DIR.glob("*.py")) if f.name != "tenant_crypto.py"
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


def test_tenant_crypto_functions_never_called_outside_tests_or_own_module():
    offenders: list[str] = []
    for path in _non_test_source_files():
        text = path.read_text(encoding="utf-8")
        matches = _TENANT_CRYPTO_CALL_RE.findall(text)
        if matches:
            offenders.append(f"{path.name}: {sorted(set(matches))}")
    assert not offenders, (
        f"Aufruf(e) von rotate_tenant_dek/encrypt_for_tenant/decrypt_for_tenant "
        f"außerhalb von services/tenant_crypto.py gefunden: {offenders}. "
        "rotate_tenant_dek ueberschreibt den Tenant-DEK SOFORT ohne Backup der "
        "alten DEK -- jedes damit verschluesselte Live-Feld wuerde ohne einen "
        "VORHER gebauten Re-Encrypt-Flow dauerhaft unlesbar (siehe Warnung im "
        "Docstring von services/tenant_crypto.py::rotate_tenant_dek). Baue den "
        "Re-Encrypt-Flow zuerst, dann aktualisiere diesen Guard bewusst."
    )
