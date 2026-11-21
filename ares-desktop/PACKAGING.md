# Ares — Packaging-Anleitung

> Roadmap-Punkt 6 (2026-05-29): Build-Pipeline wurde seit Sprint 11 nicht
> mehr aktuell gehalten. Drift in `hiddenImports` und fehlender Sub-App-
> Build-Step wurden in PR #105 gefixt. Diese Datei dokumentiert die
> aktuelle Pipeline und die Live-Verifikations-Schritte.

---

## Produktionsmodus der gepackten EXE (EXE-P, H-187)

- **SQLCipher ist Pflicht.** `build:backend` baut standardmaessig mit SQLCipher
  (`BUILD_WITH_SQLCIPHER` ist `1`, wenn nicht ausdruecklich `0`) und bricht ab,
  wenn `sqlcipher3` fehlt. Vorher installieren:
  `pip install --require-hashes --only-binary=:all: -r ares-backend/requirements-sqlcipher.txt`.
- Der Datenbankschluessel liegt DPAPI-geschuetzt (Benutzer-Scope) als
  `db-key.dpapi` im userData-Ordner (wie die Master-KEK). Die Shell setzt
  `DB_KEY_FILE`; ohne Ablageort, ohne SQLCipher oder bei vorhandener Datenbank
  ohne Ablage startet die EXE mit klarem Fehler und oeffnet nie eine Klartext-DB.
- Keine Hausannahmen zur Laufzeit, kein Muster-Fondskatalog, kein
  Gebuehren-Default. Rechnen erst mit freigegebenem Referenzpaket und IC-Freigabe.
- `TEST_REFERENCE_PACKAGE_FILE` (Datei `scripts/fixtures/packaging_smoke_test_reference_package.json`)
  laedt nur der Packaging-Smoke; die Shell reicht die Variable nie weiter.

## Build-Pipeline (One-Liner)

```bash
cd ares-desktop
npm run dist:win
```

Das chained intern:

```
build:reporting     (cd frontend/reporting && npm run build  -> dist/)
    |
    v
build:backend       (PyInstaller im ares-backend/ -> bundle/backend/ares-api.exe,
    |                Reporting-dist als reporting_dist in die EXE eingebettet)
    v
preflight:release   (release-check.js: Icons, HTML, Reporting-dist, Bundle-Exe)
    |
    v
scan:bundle-secrets (bundle/backend ohne echte .env / private Schluessel)
    |
    v
electron-builder    (NSIS-Installer in ares-desktop/dist/)
```

---

## Voraussetzungen

| Tool | Version | Wofuer |
|---|---|---|
| Node.js | >= 20 | electron + electron-builder + Sub-App-Build |
| Python | >= 3.12 | PyInstaller-EXE |
| pyinstaller | aktuelle Version | `pip install pyinstaller` |
| Alle Backend-Deps | per requirements.txt | im selben Python-Env |
| ares-backend/main.py | mit `if __name__ == '__main__':` Entry-Point | sonst exit immediate |
| Icons | `assets/icons/{app,installer-icon,uninstaller-icon}.ico` + `app.png` | NSIS-Installer-Branding |

---

## Schritt-fuer-Schritt-Verifikation (Live-Smoke)

Vor einem Release diese Schritte einmal lokal durchziehen:

1. **Sub-App bauen:**
   ```bash
   cd ares-desktop/frontend/reporting
   npm install     # einmalig
   npm run build
   ls dist/        # muss index.html + assets/ enthalten
   ```

2. **Backend bauen:**
   ```bash
   cd ares-desktop
   npm run build:backend
   ls ../ares-backend/dist/        # ares-api.exe
   ls bundle/backend/                # ares-api.exe (Kopie)
   ```

3. **Backend-EXE smoke-testen (vor electron-builder):**
   ```bash
   bundle/backend/ares-api.exe
   # Sollte uvicorn auf 127.0.0.1:8000 starten
   # Im zweiten Terminal:
   curl http://127.0.0.1:8000/health/ready
   # -> {"status":"ok","app":"Ares API",...}
   ```

   **Kritischer Subtest** — Advisory-Report-PDF muss ohne ModuleNotFoundError
   funktionieren (haengt an `services.pdf.documents.advisory_report` —
   das fehlte vor U-6 in den hiddenImports):
   ```bash
   curl -X GET "http://127.0.0.1:8000/mandates/<MID>/advisory-report" \
        -H "Authorization: Bearer <JWT>"
   ```

4. **Preflight + electron-builder:**
   ```bash
   npm run preflight:release   # statische Checks
   npm run pack                # baut Installer-Layout ohne NSIS
   npm run dist:win            # voller NSIS-Installer
   ls dist/                    # *-Setup-<version>-x64.exe (Name gemaess artifactName)
   ```

5. **Installer-Smoke:**
   - Installer doppelklicken
   - Im Installer-Pfad: `Ares` -> Programm Files
   - Desktop-Shortcut wird angelegt
   - App startet, zeigt Login-Screen
   - Login mit Test-User
   - Mandat oeffnen -> Advisory-Report-Button -> Sub-App oeffnet in Browser-Tab
   - Token-Handoff funktioniert (siehe `frontend/reporting/README.md`)
   - PDF-Download funktioniert

---

## Was vor U-6 (Punkt 6) kaputt war

| Symptom | Ursache | Fix |
|---|---|---|
| EXE crashed bei Advisory-Report-Request mit `ModuleNotFoundError: services.pdf.documents.advisory_report` | hiddenImports-Liste in build-backend.js fehlte 3 Module (`advisory_report`, `depotcheck`, `backtest`) | Liste ergaenzt, defensive `--collect-submodules services routers models` zusaetzlich |
| Reporting-Sub-App im Installer war veraltet oder fehlte ganz | `pack`/`dist:win` chained kein `npm run build` der Sub-App | Neues `build:reporting`-Script, in Pack/Dist-Chains eingehaengt |
| Installer war unnoetig gross (Sub-App-Source + node_modules ungewollt mitgepackt) | `files: ["frontend/**/*"]` Wildcard | Explizite includes + Negativ-Patterns fuer src/, node_modules/, configs |
| Veralteter Sub-App-Build wurde stillschweigend mitgepackt | release-check.js prueft nichts dazu | Check ergaenzt: `reporting/dist` muss aktueller als `reporting/src/main.tsx` sein |
| Fehlende `bundle/backend/ares-api.exe` brach electron-builder im 4. Schritt | release-check warnte nicht | Check ergaenzt, mit `STRICT_RELEASE=1` als Error |

---

## CI-Empfehlung

In GitHub-Actions empfiehlt es sich, den Pipeline-Lauf in 3 Jobs zu
splitten (cached node_modules, gemeinsamer Artifact-Store):

```yaml
jobs:
  build-reporting:
    runs-on: windows-latest
    steps:
      - cd ares-desktop/frontend/reporting && npm ci && npm run build
      - actions/upload-artifact reporting-dist
  build-backend:
    runs-on: windows-latest
    needs: build-reporting
    steps:
      - pip install -r ares-backend/requirements.txt pyinstaller
      - cd ares-desktop && npm ci && npm run build:backend
      - actions/upload-artifact backend-bundle
  package:
    runs-on: windows-latest
    needs: [build-reporting, build-backend]
    steps:
      - actions/download-artifact reporting-dist
      - actions/download-artifact backend-bundle
      - cd ares-desktop && npm ci
      - STRICT_RELEASE=1 npm run dist:win
      - actions/upload-artifact <Setup-Datei>
```

Heute laeuft noch kein CI fuer Packaging (das gehoert zur Backend-Tests-
Workflow als separater Job hinzu). Roadmap-Punkt 53 deckt CI-Cache ab.

---

## H-180 (2026-11-21): Release-Pruefungen und lokaler Build

- `scripts/packaging_smoke.py` prueft zusaetzlich (Modul `scripts/packaging_release_checks.py`):
  Import-Selbsttest im Artefakt (`ares-api.exe --self-test-imports`), Build-Kennung
  (`/health`: Version aus `package.json`, `build_sha` = gebauter Git-SHA), Demo-Systemfall
  gesperrt, Dateieigenschaften beider EXEs (ProductName `Ares`), keine Fremd-/Altmarken
  (Digest-Pruefung, nie Klartext) in app.asar/Metadaten/Backend-EXE und den Start der
  Electron-Shell im isolierten Profil bis zum sauberen Beenden.
- Lokaler Build ohne Symlink-Recht (kein Entwicklermodus): electron-builder kann das
  winCodeSign-Archiv nicht entpacken (`Cannot create symbolic link`, nur macOS-Dateien).
  Abhilfe: das Archiv aus `%LOCALAPPDATA%\electron-builder\Cache\winCodeSign\<nr>.7z` mit
  `node_modules\7zip-bin\win\x64\7za.exe x -y <nr>.7z -owinCodeSign-2.6.0` entpacken und
  `npx electron-builder --dir` erneut starten. In CI (windows-latest) nicht noetig.
- Gepackte App NIE mit dem normalen Profil testen: Electron ignoriert die Umgebungsvariable
  `APPDATA` (Known-Folder-API). Nur `--user-data-dir=<Testordner>` lenkt userData sicher um;
  dazu `USERPROFILE`/`HOME`/`TEMP` und `DB_PATH` auf einen Testordner setzen (das Backend
  leitet seinen Datenpfad aus `USERPROFILE` ab).
