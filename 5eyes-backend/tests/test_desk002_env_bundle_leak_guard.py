"""Regression-Lock fuer DESK-002 (Codex-Audit 2026-08-26,
docs/audits/2026-08-26-electron-runtime-release-security-audit.md).

5eyes-electron/scripts/build-backend.js kopierte ein evtl. auf dem
Build-Rechner vorhandenes 5eyes-backend/.env (mit echten Werten fuer
SECRET_KEY, DB_KEY, Marktdaten-API-Keys, DB-Connection-Strings) 1:1 nach
bundle/backend/.env. 5eyes-electron/package.json packt bundle/backend
per `extraResources` VOLLSTAENDIG in jeden gebauten Installer -- damit
haetten echte Produktionsgeheimnisse in jeder auf diesem Rechner gebauten
.exe gesteckt. Zusaetzlich lief der bisherige `preflight:release`-Check
VOR `build:backend`, konnte also strukturell nichts pruefen, was der
Backend-Build erst danach erzeugt.

Fix:
- der `.env`-Copy-Schritt in build-backend.js wurde entfernt (nur die
  secret-freie `.env.example` bleibt Teil des Bundles)
- ein neuer Scan (scripts/bundle-secret-scan.js) laeuft NACH
  `build:backend` und VOR `electron-builder` und bricht den Build ab,
  wenn eine echte `.env` oder ein eingebetteter privater Schluessel im
  Bundle-Ordner gefunden wird

Dies ist ein reiner Text-Scan der Node-Skripte (kein Node-Runner in dieser
Python-Test-Suite verfuegbar) -- analog zu bestehenden Raw-Text-Scan-Tests
fuer Skript-Dateien in dieser Suite, siehe
tests/test_ops001_external_tunnel_db_guard.py. Die funktionale Scan-LOGIK
selbst wird separat in 5eyes-electron/tests/bundle-secret-scan.test.js
gegen echte temporaere Verzeichnisse getestet (Node-Testrunner der
Electron-Teilanwendung).
"""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ELECTRON_ROOT = REPO_ROOT / "5eyes-electron"
BUILD_BACKEND_SCRIPT = ELECTRON_ROOT / "scripts" / "build-backend.js"
SECRET_SCAN_SCRIPT = ELECTRON_ROOT / "scripts" / "bundle-secret-scan.js"
PACKAGE_JSON = ELECTRON_ROOT / "package.json"
README = ELECTRON_ROOT / "README.md"


def _text(path: Path) -> str:
    assert path.exists(), f"{path} fehlt -- DESK-002-Fix-Dateien verschoben/umbenannt?"
    return path.read_text(encoding="utf-8")


def test_build_backend_no_longer_copies_a_real_env_file_into_the_bundle():
    text = _text(BUILD_BACKEND_SCRIPT)
    assert "copyIfExists(path.join(backendRoot, '.env')," not in text, (
        "build-backend.js kopiert wieder eine echte .env in den Bundle-Ordner -- "
        "DESK-002-Fix rueckgaengig gemacht?"
    )
    assert "copyIfExists(path.join(backendRoot, '.env.example')" in text, (
        "Die secret-freie .env.example sollte weiterhin als Vorlage mitgeliefert werden."
    )


def test_bundle_secret_scan_script_exists_and_flags_dotenv_files():
    text = _text(SECRET_SCAN_SCRIPT)
    assert "scanForSecrets" in text
    # .env als Muster erkannt, aber .env.example bewusst ausgenommen.
    assert "ALLOWED_ENV_FILENAMES" in text
    assert ".env.example" in text
    assert "module.exports" in text, (
        "Scan-Funktion muss exportiert sein, damit Tests sie ohne CLI-Aufruf pruefen koennen."
    )


def test_secret_scan_runs_after_build_backend_not_before_in_every_dist_script():
    package_json = _text(PACKAGE_JSON)
    import json

    data = json.loads(package_json)
    scripts = data["scripts"]

    assert "scan:bundle-secrets" in scripts, "npm-Script fuer den Bundle-Secret-Scan fehlt."

    for script_name in ["pack", "dist:win", "dist:win:portable", "dist:mac", "dist:linux"]:
        chain = scripts[script_name]
        build_backend_pos = chain.find("build:backend")
        scan_pos = chain.find("scan:bundle-secrets")
        builder_pos = chain.find("electron-builder")
        assert build_backend_pos != -1, f"{script_name} ruft build:backend nicht auf."
        assert scan_pos != -1, f"{script_name} ruft scan:bundle-secrets nicht auf."
        assert builder_pos != -1, f"{script_name} ruft electron-builder nicht auf."
        assert build_backend_pos < scan_pos < builder_pos, (
            f"{script_name}: scan:bundle-secrets muss NACH build:backend und VOR "
            f"electron-builder laufen (aktuelle Reihenfolge falsch) -- sonst ist der Scan "
            f"strukturell blind wie der alte preflight:release-Lauf vor build:backend."
        )

    # preflight:release darf weiterhin vor build:backend laufen (prueft andere,
    # unabhaengige Release-Voraussetzungen wie Icons/CDN-Referenzen) -- nur der
    # NEUE Secret-Scan muss danach laufen.
    assert "preflight:release" in scripts


def test_readme_no_longer_documents_env_copy_as_a_normal_build_step():
    text = _text(README)
    assert "the executable plus `.env` / `.env.example` are copied" not in text, (
        "README dokumentiert das Kopieren einer echten .env weiterhin als normalen "
        "Build-Schritt -- DESK-002-Doku-Fix rueckgaengig gemacht?"
    )
    assert "bundle-secret-scan" in text, (
        "README sollte den neuen Bundle-Secret-Scan erwaehnen."
    )
