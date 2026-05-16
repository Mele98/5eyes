# 5eyes WealthArchitekten — Codex Operating Guide
**Version:** 2026-04-10 | **Workspace:** `C:\5eyes\5eyes_stage9_release_ready`

---

## 0. IDENTITÄT DIESES PROJEKTS

Desktop-App für Schweizer Finanzberater (Wealth-Management-Referenz Umfeld).
Stack: **Electron + FastAPI (Python) + SQLite/SQLCipher**.
Plattform: Windows only. Kein Web-Deployment, kein Cloud.

Der Berater berät, empfiehlt und protokolliert — er verwaltet keine Vermögen diskretionär.
Kunden kommen 1–2x/Jahr. Dann Rebalancing-Vergleich: gespeicherte SOLL-Strategie vs. aktueller IST-Stand.

---

## 1. SINGLE SOURCE OF TRUTH — DATEIEN

| Rolle | Pfad | Grösse |
|---|---|---|
| **Frontend (alles)** | `5eyes-electron/frontend/5eyes_v2.html` | ~12'000 Zeilen — **eine Datei** |
| **Electron Host** | `5eyes-electron/main.js` | IPC-Brücke, Token, URL-Guards |
| **Backend Engine** | `5eyes-backend/services/portfolio_engine.py` | Allokation, Monte Carlo, Simulation |
| **Risk Scoring** | `5eyes-backend/services/risk_scoring.py` | Score-Formel, Kapazitäts-Matrix |
| **API Routers** | `5eyes-backend/routers/*.py` | REST-Endpunkte |
| **DB-Modelle** | `5eyes-backend/models/*.py` | SQLAlchemy |
| **Pydantic Schemas** | `5eyes-backend/schemas/*.py` | Validation, Request/Response |
| **DB-Init** | `5eyes-backend/database.py` | Schema-Migration, SQLCipher PRAGMA |

**Nie eine zweite Frontend-Datei anlegen. Nie Backend-Logik ins Frontend duplizieren.**

---

## 2. ARCHITEKTUR-INVARIANTEN

### Frontend
- **Kein Build-Step.** Vanilla JS + Chart.js. `<script>`-Tags direkt in der HTML.
- **Ein globaler State:** `strategyState`, `alloc[]`, `quoten[]`, `currentClientId`, `currentMandateId`.
- **API-Aufrufe:** Immer über das `API`-Objekt (`API.get()`, `API.post()`, `API.put()`, `API.del()`). Nie `fetch()` direkt.
- **XSS-Schutz:** Alle User-Inputs mit `escapeHtml()` wrappen bevor in `innerHTML`. Immer.
- **Demo-Modus:** `isDemoMandateId(mid)` prüfen bevor API-Calls. Im Demo-Modus keine echten Calls.

### Backend
- **FastAPI + Pydantic v2.** Response-Schemas sind immer explizit. Kein `dict` zurückgeben.
- **SQLAlchemy 2.x** mit `Session`-Injection via `Depends(get_db)`.
- **Soft-Delete:** Alle Haupt-Entitäten haben `deleted_at`. Alle Queries brauchen `WHERE deleted_at IS NULL`.
- **Rappen-Arithmetik:** Alle Geldwerte intern in Rappen (Integer). Kein Float für Geld.
- **BPS-Arithmetik:** Alle Gewichtungen/Renditen intern in Basispunkten (Integer). 10000 bps = 100%.

### Electron / IPC
- `main.js` ist der einzige Ort für IPC-Handler (`ipcMain.handle`).
- Token-Storage: `safeStorage` (verschlüsselt). Nie Token ins Frontend-localStorage.
- URL-Guard: `isSafeExternalUrl()` in `main.js` — alle externen Links müssen durch diese Funktion.

---

## 3. FACHLOGIK — KRITISCH

### Gesamtvermögen vs. Beratungsvermögen
```
Gesamtvermögen   = ALLES (Liegenschaften, Pension, extern verwaltete Depots, Custom Assets, Schulden)
Beratungsvermögen = Nur der investierbare Teil (Zuweisung: Beratungsvermögen = Ja/Nein pro Position)
```

**Kernregel:** Empfehlung wird auf Beratungsvermögen gebaut — aber unter Berücksichtigung der Gesamtvermögensstruktur.
Beispiel: Kunde hat 10 Mio. Liegenschaften im Gesamtvermögen → im Beratungsvermögen wird Immobilienquote bewusst tief gehalten (Klumpenrisiko).

### IST vs. SOLL
```
IST  = heutige Allokation des Kunden (was er tatsächlich hält)
SOLL = optimierte Zielallokation des Beratungsvermögens (Engine-Output)
```

**Cashflow/Ziele-Tab:** Zeigt IST-Vermögensentwicklung des Gesamtvermögens.
**Asset-Allocation-Tab (Tortendiagramm):** Zeigt SOLL-Allokation des Beratungsvermögens.
**Die Tabelle "Ist vs. Soll":** Zeigt beides nebeneinander mit Delta.

### SOLL-Kuchen — wichtige Frontend-Invariante
`alloc[]` hat `{ist, soll}` pro Anlageklasse.
`syncAllocationDonutFromStrategyState()` rendert den Chart mit `r.soll`.
`renderWealthPositions()` rebuildet `alloc` mit `ist === soll` (Placeholder vor Strategie-Berechnung).
**Nach `applyAllocationEngineResult()`:** `soll` kommt aus `bucket.target_weight_bps` — das ist der echte SOLL-Wert.
**Invariante:** Wenn `strategyState.allocation` existiert, darf `renderWealthPositions()` die `soll`-Werte nicht überschreiben.

### Risikoprofil-Score (MIN-Prinzip)
```
finalScore = min(capScore, willScore)   ← nie ändern, das ist FIDLEG-Logik
capScore   = HORIZON_CAPACITY_MATRIX[(horizon_years, capacity_band)]
willScore  = round(((willingnessTotal - 3) / 9) * 90 + 10)
```
Das Risikoprofil setzt die **maximale** Risikoexposition — nicht die Zielallokation.
Profil 8 ≠ automatisch 80% Aktien.

---

## 4. GIT-WORKFLOW

```
main        ← stabiles Backup (nur mit expliziter Bestätigung mergen)
develop     ← stabile Hauptbasis
v1          ← Stage-9-Snapshot, nie pushen, nie ändern
codex/<slug>← Feature-Branches für Codex (von develop oder current)
```

### Neues Feature starten
```powershell
# Von develop:
.\scripts\start_codex_branch.ps1 -Slug "feature-name"
# Von aktuellem Branch (uncommitted changes):
.\scripts\start_codex_branch.ps1 -Slug "feature-name" -FromCurrent
```

### Commit-Konventionen
```bash
git add <exakte Dateipfade>   # nie "git add -A" oder "git add ."
git commit -m "fix: kurze beschreibung was und warum"
```
Keine `.env`, keine `*.db`, keine `tmp_*` committen.

### Vor dem ersten Commit immer:
```bash
git status --short
git diff HEAD -- <datei>   # für jede Modified-Datei
```

---

## 5. BACKEND PATTERNS

### Neuer API-Endpunkt — Checkliste
1. Router in `routers/*.py` → `APIRouter` mit `prefix` und `tags`
2. Pydantic Schema in `schemas/*.py` → Create + Response getrennt
3. Response-Schema explizit typen: `response_model=MyResponse`
4. `deleted_at IS NULL` in jedem Query
5. Duplikat-Check excludiert soft-gelöschte Einträge
6. `updated_at = datetime.utcnow()` bei jedem Update setzen

### Soft-Delete Pattern
```python
# Query immer mit Filter:
db.query(Model).filter(Model.deleted_at == None, ...)
# Löschen:
obj.deleted_at = datetime.utcnow()
db.commit()
```

### portfolio_engine.py — Struktur
```
generate_target_allocation()    ← Haupt-Entrypoint (von /target-allocation/generate)
  → _load_allocation_inputs()   ← Holt Risk, Cashflows, Goals, Wealth aus DB
  → _compute_target_weights()   ← House-Matrix + Optimizer
  → _run_simulation()           ← Zeitserie (deterministische Projektion)
  → _run_monte_carlo()          ← 1000 Pfade, Cholesky-korreliert
  → _build_goal_analysis()      ← Zielerreichungs-Scores
  → _build_sub_asset_class_*()  ← Subanlageklassen-Gewichtung
```

**Nie** die Log-Normal-Formel ändern: `value *= exp(μ - 0.5σ² + σZ)` (Itô-Korrektur, absichtlich so).
**Nie** die Korrelationsmatrix-Dimensionen ändern ohne Cholesky-Fallback zu prüfen.

---

## 6. FRONTEND PATTERNS

### Tab-Navigation
```javascript
go('al')   // Wechselt zu Asset Allocation Tab
go('cf')   // Cashflow/Ziele Tab
go('rp')   // Risikoprofil Tab
go('as')   // Vermögen Tab
go('po')   // Portfolio Tab
```
Tab-Wechsel triggert Daten-Reload via `refreshStrategyData(false, page==='po'||page==='sr')`.

### Globaler State lesen/setzen
```javascript
// Lesen:
var mid = getActiveMandateId();   // null wenn kein Mandat aktiv
var cid = getActiveClientId();

// Strategie prüfen:
if (strategyState && strategyState.allocation) { /* SOLL vorhanden */ }

// Alloc-Array:
// alloc[].n = Display-Name ("Aktien (global+CH)")
// alloc[].ist = aktuelle IST-%
// alloc[].soll = SOLL-% (nach Engine-Lauf, sonst = ist)
// alloc[].chf = aktueller CHF-Wert (IST)
```

### Chart-Zugriff
```javascript
charts.dn   // Donut-Chart (Asset Allocation)
charts.opt  // Optimierungs-Chart (Zeitserie)
charts.fan  // Fan-Chart (Monte Carlo P10/P50/P90)
```

### Modals öffnen/schliessen
```javascript
om('m-eq')   // openModal
cm('m-eq')   // closeModal
```

### DOM-Text setzen (XSS-safe für text, nicht HTML)
```javascript
setText('element-id', value);   // setzt textContent
```

### escapeHtml — wann verwenden
```javascript
// IMMER bei innerHTML mit user-generated oder DB-Daten:
el.innerHTML = '<div>' + escapeHtml(userInput) + '</div>';

// Nicht nötig bei:
setText(id, value);              // setzt textContent, kein HTML
el.textContent = value;         // kein HTML-Parsing
```

---

## 7. TESTING

### Backend-Tests ausführen
```bash
cd C:\5eyes\5eyes_stage9_release_ready\5eyes-backend
python -m pytest tests/ -v
```

### Einzelner Test
```bash
python -m pytest tests/test_cashflow_timeline.py -v
```

### Neuen Test anlegen
- Datei: `5eyes-backend/tests/test_<feature>.py`
- Pattern: pytest, keine Mocks für DB (echte SQLite in-memory), keine Mocks für Scoring
- Fixture: `db_session` (in-memory SQLite) + `test_client` (FastAPI TestClient)

### DB direkt abfragen (Debugging)
```bash
# Windows PowerShell:
sqlite3 $env:USERPROFILE\5eyes\5eyes.db "SELECT * FROM risk_assessments LIMIT 5;"
```

### Backend neu starten (nach Python-Änderungen)
```bash
# Electron killen und neu starten — Backend startet automatisch
# Oder manuell:
cd C:\5eyes\5eyes_stage9_release_ready\5eyes-backend
uvicorn main:app --reload --port 8000
```

### Frontend testen (nach HTML-Änderungen)
- Datei speichern → Electron-Fenster `Ctrl+R` (oder Electron neu starten)
- Kein Build nötig, kein npm run erforderlich

---

## 8. HÄUFIGE FEHLER & WAS ZU TUN IST

### "422 Unprocessable Entity" vom Backend
→ Pydantic-Validierung fehlgeschlagen. Response-Body lesen: welches Feld, welcher Wert.
→ Häufig: `investment_horizon_label` hat falsches Literal, `bps`-Summe ≠ 10000, Pflichtfeld fehlt.

### "404 Not Found" bei `/target-allocation/current/payload`
→ Kein gespeichertes Ergebnis für dieses Mandat. Erst "Anlagestrategie berechnen" ausführen.

### Strategy zeigt nicht SOLL sondern IST im Donut
→ `strategyState.allocation` prüfen: ist es `null`? Falls ja: Strategie noch nicht berechnet.
→ Falls nicht null: prüfen ob `renderWealthPositions()` danach aufgerufen wurde und `soll` überschrieben hat (bekannter Bug-Typ).

### Score ändert sich nicht nach Q-Eingaben
→ `calcRiskScore()` wird von `sq()` (Option-Klick) und `parseRiskAnnualInput()` aufgerufen.
→ `parseCHF()` checken: Apostroph-Trenner (`'`) wird unterstützt.

### Electron startet Backend nicht
→ `main.js`: Backend-Prozess-Start in `startBackend()` prüfen.
→ Pfad zum Python-Binary: relativ zu `process.resourcesPath` oder `__dirname`.
→ Port 8000 bereits belegt? `netstat -ano | findstr :8000`

### ALTER TABLE Fehler in DB-Migration
→ `database.py: ensure_runtime_columns()` — Whitelist-Guards für Tabellen-/Spaltennamen müssen aktiv sein.
→ Immer: `re.match(r'^[a-z][a-z0-9_]+$', column_name)` vor `ALTER TABLE`.

---

## 9. WAS NICHT ANFASSEN / NEVER CHANGE

| Was | Warum |
|---|---|
| Log-Normal-Formel in `portfolio_engine.py` | Itô-Korrektur — absichtlich, mathematisch korrekt |
| `finalScore = min(capScore, willScore)` in `risk_scoring.py` | FIDLEG-Compliance (MIN-Prinzip) |
| `v1`-Branch | Unveränderliches Backup |
| `isSafeExternalUrl()` in `main.js` | Security-Gate, darf nie geschwächt werden |
| `escapeHtml()` bei innerHTML | XSS-Schutz |
| Rappen-Arithmetik (kein Float für Geld) | Rundungsfehler-Prävention |

---

## 10. SPEC-DRIVEN WORKFLOW

Für jedes neue Feature:
1. **Spec lesen:** `docs/planning/<datum>-<feature>.md`
2. **Branch erstellen:** `.\scripts\start_codex_branch.ps1 -Slug "<slug>"`
3. **Implementieren** nach Spec (Scope, Nicht-Scope, Akzeptanzkriterien)
4. **Tests schreiben** für neue Backend-Logik
5. **`OWNER-DECISION`-Marker** in der Spec für offene Fachentscheide stehen lassen
6. **Commit** mit `git add <exakte Dateien>`

Nach Implementierung: Claude reviewt gegen `docs/planning/REVIEW_CHECKLIST.md`.

---

## 11. ASSET CLASS KEYS — MAPPING

Das System verwendet zwei Namensräume:

| Engine-Key (intern) | Display-Name (Frontend) | BPS-Felder |
|---|---|---|
| `Aktien` | `Aktien (global+CH)` | `alloc_equities_bps` |
| `Obligationen` | `Anleihen / Defensiv` | `alloc_bonds_bps` |
| `Immobilien` | `Immobilien (ind.)` | `alloc_real_estate_bps` |
| `Liquiditaet` | `Liquiditätsreserve` | `alloc_liquidity_bps` |
| `Alternative` | `Alternative / Gold` | `alloc_alternatives_bps` |

`assetDisplayName(key)` konvertiert Engine-Key → Display-Name.
`allocationBucketKey(displayName)` konvertiert zurück (für Tabellen-Matching).

---

## 12. DATENBANK-SCHEMA KURZÜBERSICHT

```sql
clients              id, first_name, last_name, deleted_at, investment_horizon_start, investment_horizon_end
mandates             id, client_id, mandate_type, deleted_at
risk_assessments     id, mandate_id, final_score_x10, final_profile, investment_horizon_label,
                     investment_horizon_years, is_current, deleted_at
target_allocations   id, mandate_id, is_current, target_equities_bps, target_bonds_bps,
                     target_real_estate_bps, target_liquidity_bps, target_alternatives_bps
wealth_positions     id, client_id, label, assignment ('Beratungsvermögen'|'Anderes Vermögen'|'Verbindlichkeit'),
                     position_type, current_value_rappen, alloc_equities_bps, ...
cashflows            id, client_id, nature ('Einnahme'|'Ausgabe'), amount_rappen, frequency, deleted_at
goals                id, mandate_id, goal_type, target_amount_rappen, target_date, rank, deleted_at
products             id, asset_class, sub_asset_class, isin, product_name, ter_bps
capital_market_assumptions  id, is_current, equity_ch_return_bps, ..., correlation_matrix_json
house_matrix         id, policy_id, score_from, score_to, equity_target_bps, ...
```

`is_current = 1` + `deleted_at IS NULL` = aktiver Datensatz. Immer beide Filter setzen.

---

## 13. OFFENE TASKS (vollständige Liste in `CODEX_TASKS.md`)

| Task | Prio | Datei | Problem |
|---|---|---|---|
| 1 | KRITISCH | `database.py:199` | ALTER TABLE ohne `import re` + Whitelist-Guards |
| 2 | HOCH | `5eyes_v2.html:2951` + `portfolio_engine.py:204` | IST-Allokation Fallbacks divergieren FE vs. BE |
| 3 | MITTEL | `portfolio_engine.py:2692,2819,2655` | Tilt-Subtraktion ohne Floor/Cap-Check |
| 4 | MITTEL | `5eyes_v2.html:9773,11379` | SR-Page `logs[0]` kein Status-Filter |
| 5 | MITTEL | `config.py:74` | CORS Regex `file://.*` zu breit → `^null$` |
| 6 | NIEDRIG | `5eyes_v2.html:2959` | IST-Projektion ignoriert Backend-CMA |
| 7 | NIEDRIG | `5eyes_v2.html:~3337` | `buildMonteCarloGoalsHtml()` definiert, nie aufgerufen |
| 8 | NIEDRIG | `5eyes_v2.html:~5032` | 6 Thema-Sub-Asset-Klassen fehlen in Admin-CMA-UI |

Detaillierte Beschreibung + exakter Fix-Code: `CODEX_TASKS.md`

---

*Erstellt: Claude, 2026-04-10 — optimiert für LLM-Coding-Agenten*
