# 5eyes WealthArchitekten

Lokale Beratungssoftware für Schweizer Vermögensberater (Electron + FastAPI).

## Subsysteme

| Komponente | Pfad | Zweck |
|------------|------|-------|
| **Backend** | `5eyes-backend/` | FastAPI + SQLite/SQLCipher (Berater-Workflow, Aggregator, PDF-Rendering) |
| **Hauptapp** | `5eyes-electron/frontend/5eyes_v2.html` | Monolithische Electron-App (Kunden/Mandat/SAA/Reports) |
| **Reporting Sub-App** | `5eyes-electron/frontend/reporting/` | React/Vite — Advisory-Report-Anzeige (Vite-Dev → :5173) |
| **Electron-Shell** | `5eyes-electron/main.js` | Wrapper + safeStorage-Token + Backend-Spawn |

## Branch-Strategie

- `main` — stabile Version (Backup)
- `develop` — aktive Entwicklung
- `v1` — Version 1 Snapshot

## Backend starten (Dev)

```powershell
cd 5eyes-backend
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python main.py
```

Backend lauscht standardmäßig auf `http://127.0.0.1:8000` (siehe `5eyes-backend/.env`).

## API-Dokumentation (Sprint U-80, 2026-06-05)

Während das Backend läuft, sind diese Endpoints verfügbar:

| URL | Zweck |
|-----|-------|
| `http://127.0.0.1:8000/docs` | **Swagger UI** — interaktive API-Doku |
| `http://127.0.0.1:8000/redoc` | **ReDoc** — alternative API-Doku |
| `http://127.0.0.1:8000/openapi.json` | OpenAPI-Schema (JSON) |
| `http://127.0.0.1:8000/health` | Health-Check (root) |
| `http://127.0.0.1:8000/health/live` | Liveness (kein DB-Hit, U-63) |
| `http://127.0.0.1:8000/health/ready` | Readiness (mit DB-Check → 503 bei Outage, U-63) |

**Auth:** Alle Berater-Endpoints brauchen `Authorization: Bearer <jwt>`. Token via `POST /auth/login` mit `username` + `password`.

**TTL:** 8h default (U-59), in Production max. 24h erzwungen.

## Reporting Sub-App starten (Dev)

```powershell
cd 5eyes-electron/frontend/reporting
npm install
npm run dev    # Vite-Dev auf :5173
```

Token-Handoff vom Hauptapp-Button via URL-Fragment (`#token=<jwt>`) — der Sub-App räumt das Fragment nach Read.

## Test-Suiten

```powershell
# Backend
cd 5eyes-backend
pytest --maxfail=5 -q

# Reporting Sub-App
cd 5eyes-electron/frontend/reporting
npm test       # vitest
npm run build  # tsc + vite build
```

CI läuft beides parallel (siehe `.github/workflows/test.yml`).

## Aggregator-Sektionen (Stand 2026-06-05)

| Nr | Key | Sprint |
|----|-----|--------|
| 1-15 | Standard (Cover/Disclaimer/TOC/Ausgangslage/Positionen/Pruefpunkte/Erkenntnisse/AssetAllocation/Risikowaehrungen/Branchen/Goals/Risikoprofil/BuildingBlocks/StatementPm/WeiteresVorgehen) | U-P21 |
| 16 | `beratungsprotokoll` | U-FINMA-2.2 |
| 17 | `stress_replay` | U-70 (Codex) |
| 18 | `conflict_disclosures` | U-68 |
| 19 | `suitability_compliance` | U-66 (PR #163) |
| 20 | `methodology_models` | U-73+U-74 (PR #163) |
| 21 | `recommendation_methodology` | U-69 (PR #163) |
| 22 | `mandate_lock_status` | U-22 (PR #163) |
| 23 | `liquidity_cascade` | U-21 (PR #163) |
| 24 | `optimizer_run_history` | U-94 |

## Compliance-Stack 3-Schichten

| Schicht | Pfad |
|---------|------|
| Backend-Aggregator | `5eyes-backend/services/advisory_report.py` |
| PDF-Renderer | `5eyes-backend/services/pdf/components/compliance_audit.py` |
| Sub-App-Page | `5eyes-electron/frontend/reporting/src/pages/Compliance.tsx` (Sub-App Sektion 17) |

## Weitere Doku

- `docs/RELEASE_TAGS.md` — Semver + Release-Workflow
- `docs/CHANGELOG_TEMPLATE.md` — Changelog-Format
- `docs/REPO_HYGIENE_2026-06-04.md` — Stash/Branch-Cleanup-Strategie
- `docs/data_pipeline_README.md` — Multi-Source Marktdaten-Pipeline
- `5eyes-electron/PACKAGING.md` — Electron-Build-Pipeline
- `5eyes-electron/frontend/reporting/DESIGN_SYSTEM.md` — Tailwind-Tokens + Editorial-Disziplin
- `5eyes-backend/README_price_updater.md` — Tägliche Marktdaten-Cron
