# Claude handoff / review request

## UI-Guardrail ab 2026-05-16

Claude: Der Admin-P17/Datenpipeline-Block hat den alten Navy-Gold/Inline-Card-Stil wieder in die App gebracht. Das war ein klarer Rueckfall gegen die aktuelle UI-Richtung und darf nicht wieder passieren.

Ab jetzt gilt fuer alle sichtbaren Frontend-Aenderungen:
- Cashflow und Asset Allocation sind der Referenzstil: ruhig, schlicht, helle Flaechen, wenig Gold, keine dekorativen Mini-Karten.
- Keine neuen `style="color:var(--g3)"`, `style="color:var(--g4)"`, schweren Navy-Gold-Header oder isolierten Inline-Statuskarten in neuen UI-Bloecken.
- Neue Admin-Bereiche muessen die vorhandenen Klassen nutzen: `admin-section-title`, `admin-section-sub`, `admin-summary-panel`, `admin-metric-panel`, `admin-metric-label`, `admin-metric-value`, `admin-metric-meta`, `admin-code-input`.
- Wenn ein neuer Bereich eigene Struktur braucht, zuerst eine kleine wiederverwendbare Klasse im Admin-Komponentenlayer anlegen, nicht Inline-CSS kopieren.
- Vor Abgabe per Suche pruefen:
  - `font-size:13px;font-weight:600;color:var(--g3)`
  - `color:var(--g4)`
  - `font-family:Consolas,monospace`
  - `background:var(--bg2);border-radius:6px;padding`
Neue Treffer in Admin/Frontend sind nur mit begruendetem Ausnahmefall ok.

## Dokument-/Vorlagen-Guardrail ab 2026-05-16

Claude: Vorlagen-PDFs duerfen nur als Struktur-, Text- und Designreferenz dienen. Kundennamen, Kontaktangaben, Marken oder andere personenbezogene Beispielangaben aus einer Vorlage niemals uebernehmen, hardcoden oder in generische Reports schreiben.

Fuer die Anlagestrategie gilt:
- Branding aus Vorlagen wie Referenzanbieter/Banken/Beispielberater nie kopieren. Fuer diesen Report ist `Emanuele Konzelmann` der Absender/Brand.
- Das Report-Template darf keine Namen hardcoden. Im echten kundenspezifischen Export darf der aktive Kunde aus der App (`currentPersona`/API-Daten) in Titel, Kopfzeile, Signatur und Kundendaten erscheinen.
- Namen aus einer PDF-Vorlage bleiben verboten. Beispielkundennamen duerfen weder als Fallback noch als Demo-Default verwendet werden.

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
