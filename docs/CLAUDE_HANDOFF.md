# Claude handoff / review request

Aktueller Standard fuer neue Arbeitsbloecke:
- Spezifikationen liegen jetzt in [docs/planning](C:/5eyes/5eyes_stage9_release_ready/docs/planning)
- neue Claude-Specs bitte aus [CLAUDE_SPEC_TEMPLATE.md](C:/5eyes/5eyes_stage9_release_ready/docs/planning/CLAUDE_SPEC_TEMPLATE.md) ableiten
- Codex startet Umsetzungsbranches ueber [start_codex_branch.ps1](C:/5eyes/5eyes_stage9_release_ready/scripts/start_codex_branch.ps1)
- Review bitte gegen [REVIEW_CHECKLIST.md](C:/5eyes/5eyes_stage9_release_ready/docs/planning/REVIEW_CHECKLIST.md) ausrichten

## Bereits umgesetzt

### Backend
- Preis-Service mit `price_history`
- APScheduler-Start im FastAPI-Prozess
- Admin-Endpunkte:
  - `POST /admin/prices/refresh`
  - `GET /admin/prices/status`
  - `GET /admin/prices/mapping-gaps`
- Health-Endpunkte:
  - `GET /health`
  - `GET /health/ready`
  - `GET /health/db`
- robusteres DB-Bootstrapping über `sqlite3.executescript()`
- zentrales DB-Modul, das per `DB_USE_SQLCIPHER=true` automatisch SQLCipher aktiviert
- `.env`-Suche für Dev und packaged Backend
- Logging-Bootstrap und `.env.example`
- `setup.py` für First-Run Admin-User
- `migrate_to_sqlcipher.py` für bestehende Klartext-DBs

### Electron
- Backend-Prozessstart
- Readiness-Wait auf `/health/ready`
- `contextBridge` mit Backend-Base-URL
- Navigation-Hardening
- Single-instance lock
- `frontend/desktop-api.js` als Helfer für API-Calls
- `npm start` / `npm run dist:win`
- Packaging-Script mit optionalem `BUILD_WITH_SQLCIPHER=1`

## Was Claude jetzt am meisten reviewen / ergänzen soll

1. **Frontend-API-Wiring final prüfen**
   - Login / Token-Flows auf Race Conditions prüfen
   - Offline-Fallback sauber nur dann nutzen, wenn Backend wirklich nicht erreichbar ist
   - Fehlerzustände im UI explizit anzeigen

2. **SQLCipher-Review**
   - Prüfen, ob das zentrale Umschalten via `database.py` für seine Branch am saubersten ist
   - Validieren, ob noch irgendwo direkte Klartext-Annahmen im Code existieren

3. **Offline-Fähigkeit finalisieren**
   - `vendor_assets.py` einmal wirklich laufen lassen
   - prüfen, ob danach keinerlei CDN-Abhängigkeit mehr im HTML verbleibt

4. **Packaging-Review**
   - prüfen, ob zusätzliche PyInstaller hidden imports nötig sind
   - später App-Icon, Signierung und finalen Installer-Feinschliff ergänzen

## Review-Fragen an Claude

- Siehst du noch CORS-, Session- oder Token-Fallen bei `file://` / `Origin: null`?
- Möchtest du vor dem finalen Build einen separaten `ticker_symbol` / Override-Mechanismus im Produktuniversum ergänzen?
- Sollen wir noch einen kleinen lokalen Admin-Guard für `POST /admin/prices/refresh` ergänzen?
