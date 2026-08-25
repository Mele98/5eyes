# 5eyes WealthArchitekten — Packaging-Anleitung

> Roadmap-Punkt 6 (2026-05-29): Build-Pipeline wurde seit Sprint 11 nicht
> mehr aktuell gehalten. Drift in `hiddenImports` und fehlender Sub-App-
> Build-Step wurden in PR #105 gefixt. Diese Datei dokumentiert die
> aktuelle Pipeline und die Live-Verifikations-Schritte.

---

## Build-Pipeline (One-Liner)

```bash
cd 5eyes-electron
npm run dist:win
```

Das chained intern:

```
preflight:release   (release-check.js: Icons, HTML, Reporting-dist, Bundle-Exe)
    |
    v
build:reporting     (cd frontend/reporting && npm run build  -> dist/)
    |
    v
build:backend       (PyInstaller im 5eyes-backend/ -> bundle/backend/5eyes-api.exe)
    |
    v
electron-builder    (NSIS-Installer in 5eyes-electron/dist/)
```

---

## Voraussetzungen

| Tool | Version | Wofuer |
|---|---|---|
| Node.js | >= 20 | electron + electron-builder + Sub-App-Build |
| Python | >= 3.12 | PyInstaller-EXE |
| pyinstaller | aktuelle Version | `pip install pyinstaller` |
| Alle Backend-Deps | per requirements.txt | im selben Python-Env |
| 5eyes-backend/main.py | mit `if __name__ == '__main__':` Entry-Point | sonst exit immediate |
| Icons | `assets/icons/{app,installer-icon,uninstaller-icon}.ico` + `app.png` | NSIS-Installer-Branding |

---

## Schritt-fuer-Schritt-Verifikation (Live-Smoke)

Vor einem Release diese Schritte einmal lokal durchziehen:

1. **Sub-App bauen:**
   ```bash
   cd 5eyes-electron/frontend/reporting
   npm install     # einmalig
   npm run build
   ls dist/        # muss index.html + assets/ enthalten
   ```

2. **Backend bauen:**
   ```bash
   cd 5eyes-electron
   npm run build:backend
   ls ../5eyes-backend/dist/        # 5eyes-api.exe
   ls bundle/backend/                # 5eyes-api.exe (Kopie)
   ```

3. **Backend-EXE smoke-testen (vor electron-builder):**
   ```bash
   bundle/backend/5eyes-api.exe
   # Sollte uvicorn auf 127.0.0.1:8000 starten
   # Im zweiten Terminal:
   curl http://127.0.0.1:8000/health/ready
   # -> {"status":"ok","app":"5Eyes WealthArchitekten API",...}
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
   ls dist/                    # 5Eyes-Setup-<version>-x64.exe
   ```

5. **Installer-Smoke:**
   - Installer doppelklicken
   - Im Installer-Pfad: `5Eyes WealthArchitekten` -> Programm Files
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
| Fehlende `bundle/backend/5eyes-api.exe` brach electron-builder im 4. Schritt | release-check warnte nicht | Check ergaenzt, mit `STRICT_RELEASE=1` als Error |

---

## CI-Empfehlung

In GitHub-Actions empfiehlt es sich, den Pipeline-Lauf in 3 Jobs zu
splitten (cached node_modules, gemeinsamer Artifact-Store):

```yaml
jobs:
  build-reporting:
    runs-on: windows-latest
    steps:
      - cd 5eyes-electron/frontend/reporting && npm ci && npm run build
      - actions/upload-artifact reporting-dist
  build-backend:
    runs-on: windows-latest
    needs: build-reporting
    steps:
      - pip install -r 5eyes-backend/requirements.txt pyinstaller
      - cd 5eyes-electron && npm ci && npm run build:backend
      - actions/upload-artifact backend-bundle
  package:
    runs-on: windows-latest
    needs: [build-reporting, build-backend]
    steps:
      - actions/download-artifact reporting-dist
      - actions/download-artifact backend-bundle
      - cd 5eyes-electron && npm ci
      - STRICT_RELEASE=1 npm run dist:win
      - actions/upload-artifact 5Eyes-Setup
```

Heute laeuft noch kein CI fuer Packaging (das gehoert zur Backend-Tests-
Workflow als separater Job hinzu). Roadmap-Punkt 53 deckt CI-Cache ab.
