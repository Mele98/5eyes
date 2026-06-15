#!/usr/bin/env python
"""Security-Gate: schneller, dedizierter Lauf der sicherheitskritischen Tests.

Single Source of Truth fuer CI (.github/workflows/test.yml) UND lokale Nutzung.
Faellt bei der ERSTEN Verletzung (--maxfail=1) — eine Mandanten-Trennungs- oder
Auth-Regression soll NICHT im 3900-Test-Vollauf untergehen, sondern den PR
sofort und sichtbar rot machen.

Aufruf (aus Repo-Root ODER 5eyes-backend):
    python scripts/security_gate.py
    python -m pytest $(python scripts/security_gate.py --list)   # nur die Pfade

Neue sicherheitskritische Tests bitte HIER eintragen, damit das Gate sie schuetzt.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

# Relativ zu 5eyes-backend/ — harte Mandanten-Trennung, Auth, 2FA, Onboarding.
SECURITY_TESTS: list[str] = [
    # — Mandanten-Trennung (oberste Maxime) —
    "tests/test_strict_tenant_isolation.py",
    "tests/test_tenant_backfill.py",
    "tests/test_tenant_foundation.py",
    "tests/test_repository_tenant_scoping.py",
    "tests/test_auth_tenant_aware.py",
    "tests/test_tenant_endpoint_leak_regression.py",
    "tests/test_tenant_leak_wealth_endpoints.py",
    "tests/test_audit_log_tenant_scoping.py",
    "tests/test_user_admin_tenant_scoping.py",
    "tests/test_mandate_tenant_inheritance.py",
    "tests/test_user_tenant_inheritance.py",
    "tests/test_client_portal_tenant_isolation.py",
    "tests/test_shadow_comparison_aggregator.py",
    # — Authentifizierung / 2FA / Onboarding —
    "tests/test_totp.py",
    "tests/test_2fa_login.py",
    "tests/test_onboarding_password.py",
    "tests/test_invite_onboarding.py",
    "tests/test_mailer.py",
    "tests/test_account_recovery.py",
]


def _backend_dir() -> Path:
    here = Path(__file__).resolve().parent          # scripts/
    repo = here.parent                               # repo root
    backend = repo / "5eyes-backend"
    return backend if backend.is_dir() else Path.cwd()


def main(argv: list[str]) -> int:
    backend = _backend_dir()

    # Fehlende Pfade hart melden (Tippfehler / verschobene Datei nicht still ignorieren).
    missing = [t for t in SECURITY_TESTS if not (backend / t).is_file()]
    if missing:
        print("SECURITY-GATE FEHLER — gelistete Tests fehlen:", file=sys.stderr)
        for m in missing:
            print("  - " + m, file=sys.stderr)
        return 2

    if "--list" in argv:
        # Maschinen-lesbar: Pfade space-separated (fuer `pytest $(... --list)`).
        print(" ".join(SECURITY_TESTS))
        return 0

    cmd = [
        sys.executable, "-m", "pytest",
        *SECURITY_TESTS,
        "-p", "no:cacheprovider",
        "--maxfail=1", "-q",
    ]
    print("Security-Gate:", len(SECURITY_TESTS), "Test-Dateien (--maxfail=1)\n", flush=True)
    return subprocess.call(cmd, cwd=str(backend))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
