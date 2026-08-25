# 5eyes WealthArchitekten – Codex Debug & Test Guide
**Ziel:** Systematisches Entbuggen und Testen der gesamten App. Jede Sektion, jeder Button, jeder Datenfluss.

---

## 1. APP-ARCHITEKTUR

```
Electron (main.js)
  └─ Frontend: 5eyes-electron/frontend/5eyes_v2.html   ← EINZIGE Frontend-Datei (alles in 1 Datei!)
  └─ Backend:  5eyes-backend/                          ← FastAPI Python
       ├─ main.py                                       ← Uvicorn entry point
       ├─ routers/                                      ← API Endpoints
       │    ├─ auth.py          /auth/*
       │    ├─ clients.py       /clients/*
       │    ├─ mandates.py      /mandates/*
       │    ├─ profiling.py     /mandates/{id}/risk-assessments, /clients/{id}/knowledge
       │    ├─ allocation.py    /mandates/{id}/target-allocation/*
       │    ├─ assets.py        /clients/{id}/wealth-positions, /clients/{id}/assets
       │    ├─ cashflows.py     /clients/{id}/cashflows
       │    ├─ goals.py         /mandates/{id}/goals
       │    └─ review.py        /mandates/{id}/recommendations, /mandates/{id}/triggers
       ├─ services/
       │    ├─ portfolio_engine.py   ← Haupt-Engine: Allokation, Simulation, Monte Carlo
       │    └─ risk_scoring.py       ← Risiko-Score-Berechnung
       ├─ models/                    ← SQLAlchemy DB-Modelle
       └─ schemas/                   ← Pydantic Validation Schemas
  └─ Database: ~/5eyes/5eyes.db     ← SQLite (Pfad: config.py → db_path)
```

**Wichtig:** Alle Frontend-Änderungen in `5eyes_v2.html`. Backend-Änderungen erfordern Neustart.

---

## 2. GLOBALER STATE (Frontend)

```javascript
// Aktiver Kunde/Mandat
var currentClientId = null;          // UUID
var currentMandateId = null;         // UUID
var currentMandateData = null;       // {mandate_type, ...}

// Strategie-State (Allokation, Risiko, etc.)
let strategyState = {
  allocation: null,       // TargetAllocationGenerateResponse (mit sub_allocations!)
  recommendation: null,
  risk: null,             // RiskAssessmentResponse
  activeMandateId: null,
  lastGeneratedAt: 0,
  loading: false,
  dirty: true,
  buildingBlocks: [],
  marketRuntime: null
};

// Allokations-Tabelle
let alloc = [...];        // [{n, c, ist, soll, chf}] - wird von applyAllocationEngineResult() gesetzt
var allocationSuballocExpanded = {};  // {groupKey: bool}
```

---

## 3. API-CALL PATTERN

```javascript
// API-Objekt (Frontend, ca. Zeile 2400+)
API.get('/endpoint')        → GET, returns Promise<data>
API.post('/endpoint', body) → POST, returns Promise<data>
API.put('/endpoint', body)  → PUT
API.del('/endpoint')        → DELETE

// Auth: Token wird von Electron's safeStorage gespeichert
// Kein Login-UI notwendig - Token wird automatisch bei API-Calls gesetzt
```

---

## 4. SEKTION: ANMELDUNG / AUTH

### Was es tut:
- Electron lädt Token aus verschlüsseltem Store
- Token wird als Bearer-Header bei jedem API-Call gesetzt

### Zu testen:
- [ ] App starten → Auto-Login funktioniert (kein Prompt)
- [ ] Wenn Token abgelaufen → Redirect zu Login-Screen
- [ ] Abmelden → Token gelöscht, erneute Anmeldung nötig

### Code-Lokationen:
- `main.js:497` → `ipcMain.handle('auth:get-token', ...)`
- `5eyes_v2.html` → `API`-Objekt (suche `function.*API\s*=` oder `const API`)

---

## 5. SEKTION: KUNDENLISTE (linke Sidebar)

### Was es tut:
- Lädt alle Kunden via `GET /clients`
- Bei Klick → `setActiveClient(clientId)` → lädt Mandat
- Mandatauswahl → `setActiveMandate(mandateId)`

### Zu testen:
- [ ] Kundenliste wird korrekt angezeigt
- [ ] Klick auf Kunde → Name erscheint in Header
- [ ] Mandat wird geladen → alle Tabs reagieren

### Code-Lokationen:
- Frontend `selC()`, `loadClients()`, `setActiveClient()`
- Backend: `GET /clients` in `routers/clients.py`

---

## 6. SEKTION: RISIKOPROFIL (Tab `rp`)

### Datenfluss:
```
UI-Eingaben (Fragebogen)
  → buildRiskAssessmentPayloadFromUI()    [~Zeile 6166]
  → result.payload (Scoring-Felder)
  → calcRiskScore() → renderRiskSummary() [Score anzeigen]
  → saveRiskProfile() → POST /mandates/{id}/risk-assessments
  → DB: risk_assessments Tabelle
  → strategyState.risk gesetzt
```

### Fragen und ihre Score-Auswirkung:
| Frage | Sektion | Scoring-Einfluss | Zweck |
|-------|---------|-----------------|-------|
| Q1 - Instrumente (Checkboxen) | r-ke | ❌ Kein Direktscore | FIDLEG Dokumentation |
| Q2 - Bewirtschaftungsform | r-ke | ❌ Kein Direktscore | FIDLEG Angemessenheit |
| Q3 - Erfahrung | r-ke | ❌ Kein Direktscore | FIDLEG Angemessenheit |
| Q4 - Bruttoeinkommen (CHF) | r-ke | ✅ `q_income_points` via surplusPoints | Risikofähigkeit |
| Q5 - Anlagehorizont | r-rf | ✅ `investment_horizon_label/years` | Kapazitäts-Matrix |
| Q6 - Jährl. Verpflichtungen | r-rf | ✅ Zusammen mit Q4 = Überschussquote | Risikofähigkeit |
| Q7 - Sparrate | r-rf | ✅ `q_savings_points` | Risikofähigkeit |
| Q8 - Liquiditätsreserve | r-rf | ✅ `q_wealth_points` | Risikofähigkeit |
| Q9 - Anlageziel | r-rb | ✅ `q_investment_goal_points` (1-4) | Risikobereitschaft |
| Q10 - Risikopräferenz | r-rb | ✅ `q_risk_preference_points` (1-4) | Risikobereitschaft |
| Q11 - Risikoverhalten | r-rb | ✅ `q_risk_behavior_points` (1-4) | Risikobereitschaft |

**Q2/Q3 haben absichtlich keinen Direktscore** (FIDLEG-Konformität, Label sagt "Dokumentation, kein Direktscore")

### Scoring-Formel (Frontend, ~Zeile 6190):
```javascript
// Risikofähigkeit
surplusPoints = mapSurplusPoints(monthlyIncome, monthlyObligations)  // 0-4
savingsPoints = RISK_SAVINGS_POINTS[savingsIdx]                       // 0-12
wealthPoints = normalizeRiskPoints(reservePoints, 9, 12)              // 0-12
capacityTotal = surplusPoints + savingsPoints + wealthPoints           // 0-28 (obligationPoints immer 0!)
capacityBand = findRiskCapacityBand(capacityTotal)                    // band 1-4
capScore = RISK_CAPACITY_MATRIX[horizon.years + ',' + capacityBand]   // 10-100

// Risikobereitschaft
willingnessTotal = goalPoints + prefPoints + behavPoints               // 3-12
willScore = round(((willingnessTotal - 3) / 9) * 90 + 10)             // 10-100

// Finaler Score
finalScore = min(capScore, willScore)                                  // MIN-Prinzip!
```

### KRITISCHER BUGFIX (bereits gefixt):
- `investment_horizon_label` Frontend-Labels ("1 bis 3 Jahre" etc.) passten NICHT zu Backend-Literal-Type
- Fix: Labels geändert zu "2 bis 3 Jahre", "4 bis 5 Jahre", "8 bis 11 Jahre", "12 Jahre und mehr"
- Backend `schemas/profiling.py` + `services/risk_scoring.py` auch erweitert

### Zu testen:
- [ ] Q4 Einkommen ändern → Score ändert sich sofort
- [ ] Q5 Horizont ändern → Score ändert sich
- [ ] Q6 Verpflichtungen ändern → Score ändert sich
- [ ] Q7, Q8 ändern → Score ändert sich
- [ ] Q9, Q10, Q11 ändern → Score ändert sich
- [ ] Q1, Q2, Q3 ändern → Score ändert sich NICHT (korrekt so!)
- [ ] "Risikoprofil speichern" klicken → Button zeigt "Gespeichert ✓" (grün)
- [ ] Nach Neustart App → Fragebogen ist vorausgefüllt (hydrateRiskQuestionnaire)
- [ ] Nach Neustart → Score wird korrekt angezeigt

### Code-Lokationen:
- `buildRiskAssessmentPayloadFromUI()` ~Zeile 6166 - Payload aufbauen
- `calcRiskScore()` ~Zeile 6437 - Score berechnen + anzeigen
- `saveRiskProfile()` ~Zeile 6449 - API-Call zum Speichern
- `hydrateRiskQuestionnaire()` ~Zeile 6116 - UI aus DB-Daten befüllen
- Backend: `routers/profiling.py` → `create_risk_assessment()`
- Backend: `services/risk_scoring.py` → `compute_scores()`

### Potenzielle Bugs zu prüfen:
1. `obligationPoints` ist IMMER 0 (Zeile 6199: `var obligationPoints = 0`). Ist das korrekt?
2. Wird `applyGoalDerivedRiskHorizon()` korrekt aufgerufen wenn Ziele gesetzt werden?
3. Tab-Navigation innerhalb des Fragebogens - werden alle 3 Tabs (Kenntnisse/Fähigkeit/Bereitschaft) korrekt aktiviert?

---

## 7. SEKTION: VERMÖGEN (Tab `as`)

### Datenfluss:
```
Vermögenspositionen
  → GET /clients/{id}/wealth-positions     [Wertschriften-Depots]
  → GET /clients/{id}/assets               [sonstige Assets: Immobilien, Pension, Cash]
  → renderWealthPositions()
  → TOTAL wird berechnet = advisory_wealth + nicht-advisory

Für Allokations-Engine:
  → advisory_wealth_rappen = Summe aller "advisable" Positionen
  → current_amounts per asset_class = aktuelle Allokation für Drift-Berechnung
```

### Bekannte Bugs vom User:
1. **Mehrere Börsenkonti** - angeblich nicht möglich
2. **Cash geht direkt in Liquidität** - wird nicht als investierbar behandelt

#### Bug 1: Mehrere Börsenkonti
Zu prüfen: `addWealthPosition()` oder ähnliche Funktion - verhindert sie mehrfache Einträge vom selben Typ?
- Suche nach: Depot/Konto/Brokerage in HTML Formular-Sektion
- Prüfe ob DB unique constraint auf (client_id, depot_type) oder ähnlich
- Prüfe Backend: `POST /clients/{id}/wealth-positions` - was passiert bei Duplikat?

#### Bug 2: Cash → Liquidität
Zu prüfen in `portfolio_engine.py`:
- Funktion `_load_allocation_inputs()` - wie wird Cash kategorisiert?
- `advisory_summary.amounts_rappen` - wie wird Cash verteilt?
- Suche: `cash`, `liquidity`, `liquiditaet` in portfolio_engine.py

### Zu testen:
- [ ] Depot hinzufügen → erscheint in Liste
- [ ] Zweites Depot hinzufügen → sollte auch erscheinen (Bug?)
- [ ] Depot löschen → verschwindet
- [ ] Wertschriften-Positionen in Depot → werden nach Asset-Klasse kategorisiert
- [ ] Cash-Position → wie wird sie in Allokation gezeigt?
- [ ] Immobilien → werden sie im Advisory-Vermögen gezählt?
- [ ] Pension/Vorsorge → wird sie für Allokation berücksichtigt?

### Code-Lokationen:
- Frontend: Suche `page-as` oder `wealth` im HTML
- Backend: `routers/assets.py`
- Backend: `_load_allocation_inputs()` in `services/portfolio_engine.py` (ca. Zeile 2683)

---

## 8. SEKTION: CASHFLOWS (Tab `cf`)

### Datenfluss:
```
Cashflow-Einträge (Einkommen, Ausgaben, Zuflüsse, Abflüsse)
  → GET /clients/{id}/cashflows
  → renderCashflows()
  → GET /clients/{id}/cashflow-summary → {surplus_rappen}

Für Strategie-Engine:
  → annual_net_cashflow_rappen = Jahres-Überschuss
  → cashflow_projection_series_rappen = Jahres-Cashflows über Horizont
```

### Zu testen:
- [ ] Cashflow hinzufügen → erscheint in Liste
- [ ] Cashflow editieren → Änderung wird gespeichert
- [ ] Cashflow löschen → verschwindet
- [ ] Surplus/Überschuss wird korrekt berechnet
- [ ] Regelmässige vs. einmalige Cashflows korrekt unterschieden
- [ ] Cashflow-Vorschau über Jahre korrekt dargestellt

---

## 9. SEKTION: ZIELE (Tab `zi` oder `go`)

### Datenfluss:
```
Anlageziele
  → GET /mandates/{id}/goals
  → renderGoals()
  → beeinflusst applyGoalDerivedRiskHorizon() → Risikohorizont
  → beeinflusst _build_goal_analysis() in portfolio_engine.py
  → beeinflusst Liquiditäts-Tilts in generate_target_allocation()
```

### Zu testen:
- [ ] Ziel hinzufügen → erscheint
- [ ] Ziel mit Datum → beeinflusst Risikohorizont?
- [ ] Ziel löschen
- [ ] Goal-Score in Strategie-Summary korrekt

---

## 10. SEKTION: ANLAGESTRATEGIE (Tab `al`)

### KRITISCHER DATENFLUSS:
```
PREREQUISITEN (müssen in DB existieren):
  1. risk_assessments WHERE mandate_id = X AND is_current = 1
  2. (optional) cashflows, goals, wealth_positions

USER KLICKT "Anlagestrategie berechnen":
  → calculateInvestmentStrategy()          [~Zeile 8906]
  → refreshStrategyData(force=true)        [~Zeile 9478]
  → POST /mandates/{id}/target-allocation/generate
       {preferences: collectAllocationPreferencesFromUI()}
  → Backend: generate_target_allocation()  [portfolio_engine.py ~Zeile 2663]
       → Lädt: risk_assessment, cashflows, goals, wealth_positions
       → Berechnet: targets, sub_allocations, simulation, monte_carlo
       → Speichert: target_allocations Tabelle
       → Return: TargetAllocationGenerateResponse (mit sub_allocations!)
  → applyAllocationEngineResult(result)    [~Zeile 9261]
       → strategyState.allocation = result
       → alloc[] Array neu befüllt von result.buckets
       → buildAT() → Allokations-Tabelle mit Expand-Buttons
       → Charts aktualisiert

BEIM TAB-WECHSEL ZU 'al' (kein Force):
  → refreshStrategyData(false, false)
  → Wenn Cache frisch: rendert aus strategyState
  → Wenn nicht: GET /mandates/{id}/target-allocation/current/payload
       → Gibt auch TargetAllocationGenerateResponse zurück (MIT sub_allocations)
       → applyAllocationEngineResult() wird aufgerufen ✓
```

### Sub-Allokationen (aufklappbar):
```javascript
// In alloc[]: r.n = "Aktien", "Obligationen", etc. (von assetDisplayName())
// In strategyState.allocation.sub_allocations[]:
//   {asset_class: "Aktien", sub_asset_class: "Aktien Schweiz", target_weight_bps: 4500, rationale: "..."}

// Matching via allocationBucketKey():
//   "Aktien (global+CH)" → "Aktien"
//   "Obligationen"      → "Obligationen"
//   "Liquidität"        → "Liquiditaet"
//   etc.

// Expand-Button onclick (Zeile ~3190):
//   onclick="event.stopPropagation();toggleAllocationTableGroup('table:Aktien');"
```

### Zu testen:
- [ ] "Anlagestrategie berechnen" klicken → Overlay erscheint → verschwindet nach ~3s
- [ ] Allokations-Tabelle wird befüllt (5 Asset-Klassen)
- [ ] Auf Aktien-Zeile klicken → Subanlageklassen erscheinen (aufklappbar)
- [ ] Auf Obligationen-Zeile klicken → Subanlageklassen
- [ ] Auf Liquidität-Zeile klicken → (ggf. nur 1 Subanlageklasse)
- [ ] Donut-Chart zeigt korrekte Gewichtungen
- [ ] Optimierungs-Chart (opt) zeigt Wachstumspfad
- [ ] Vergleichs-Section ist VERSTECKT by default → "Vergleich einblenden" öffnet sie
- [ ] Bandbreiten-Tabelle korrekt
- [ ] Prognose-Zahlen plausibel (kein 0-Wert, kein NaN)

### Error-Handling:
```javascript
// Bei 409 "Kein Risikoprofil":
// → calculateInvestmentStrategy() catch → renderStrategyCalcOverlay mit Fehlermeldung
// → updateStrategyStatus('...Bitte zuerst ein aktuelles Risikoprofil speichern...', true)

// Bei 404 (kein gespeichertes Mandat):
// → Stille Ignorierung (isDemoMandateId Check)
```

---

## 11. SEKTION: PORTFOLIO (Tab `po`)

### Datenfluss:
```
GET /mandates/{id}/recommendations/current/payload
  → PositionsList mit Kauf/Verkauf-Empfehlungen
  → Live-Rebalancing-Ansicht
  → Drift-Analyse pro Asset-Klasse
```

### Zu testen:
- [ ] Portfolio-Tab nach Strategie-Berechnung → Empfehlungen erscheinen
- [ ] Kauf/Verkauf-Aktionen logisch
- [ ] Live-Preise werden geholt (oder Fallback auf gespeicherte Preise)

---

## 12. VOLLSTÄNDIGE TEST-CHECKLISTE (Schritt für Schritt mit Tschi als Testmandant)

```
SCHRITT 1: SETUP
  □ App starten
  □ Backend läuft (port 8000)
  □ Tschi-Yin Huynh in Kundenliste auswählen

SCHRITT 2: VERMÖGEN ÜBERPRÜFEN
  □ Tab "Vermögen/Assets" öffnen
  □ Gibt es Depots/Konten?
  □ Zweites Depot hinzufügen → funktioniert?
  □ Cash-Position hinzufügen → wie kategorisiert?

SCHRITT 3: CASHFLOWS PRÜFEN
  □ Tab "Cashflows" öffnen  
  □ 6 Cashflows sollten vorhanden sein (laut DB)
  □ Surplus korrekt berechnet?

SCHRITT 4: RISIKOPROFIL SPEICHERN ← KRITISCH
  □ Tab "Risikoprofil" öffnen
  □ Alle 3 Tabs (Kenntnisse/Fähigkeit/Bereitschaft) durchgehen
  □ Q4 Einkommen = CHF 380'000 (oder anpassen)
  □ Q6 Verpflichtungen = CHF 290'000 (oder anpassen)
  □ Q5 Horizont = "8 bis 11 Jahre" (default)
  □ Score wird unten angezeigt (sollte ~5-7/10 sein)
  □ "Risikoprofil speichern" klicken → "Gespeichert ✓" erscheint
  □ App neu starten → Risikoprofil noch vorhanden?

SCHRITT 5: STRATEGIE GENERIEREN
  □ Tab "Anlagestrategie" öffnen
  □ "Anlagestrategie berechnen" klicken
  □ Overlay zeigt Fortschritt
  □ Allokations-Tabelle befüllt sich (5 Zeilen)
  □ Subanlageklassen aufklappbar (Aktien anklicken)
  □ Chart zeigt Wachstumspfad

SCHRITT 6: VERGLEICH
  □ "Vergleich einblenden" klicken → Vergleichs-Section öffnet sich
  □ Zahlen plausibel?
  □ Chart zeigt zwei Linien (Ist vs. Soll)?

SCHRITT 7: REVIEW/EMPFEHLUNG
  □ Tab "Review" oder "Portfolio" öffnen
  □ Kauf/Verkauf-Liste erscheint?
```

---

## 13. BEKANNTE BUGS UND FIXES (Stand Session)

| # | Bug | Status | Fix-Location |
|---|-----|--------|-------------|
| 1 | `parseCHF("CHF 120'000")` = NaN | ✅ GEFIXT | `5eyes_v2.html` ~Zeile 6948 |
| 2 | Risikoprofil-Score verschwindet nach Reload | ✅ GEFIXT | `parseRiskAnnualInput()` + `parseCHF()` |
| 3 | `investment_horizon_label` 422-Fehler | ✅ GEFIXT | Frontend RISK_HORIZON_OPTIONS + Backend Literal |
| 4 | Vergleichs-Section immer sichtbar | ✅ GEFIXT | `toggleCompareSection()`, hidden by default |
| 5 | Opt-Chart zu klein | ✅ GEFIXT | 340px height, 260px wenn Vergleich offen |
| 6 | Sub-Allokations onclick fehlerhaft | ✅ GEFIXT | Direkte key-Einbettung: `onclick="...toggleAllocationTableGroup('table:Aktien')"` |
| 7 | Prognose reinvestiert Cashflows nicht | ✅ GEFIXT | `buildBaselineProjectionFromInputs()` half-year convention |
| 8 | Mehrere Börsenkonti nicht möglich | ❓ UNKLAR | `routers/assets.py`, Frontend Wealth-Sektion |
| 9 | Cash → immer Liquidität (nicht optimierbar) | ❓ OFFEN | `_load_allocation_inputs()` in portfolio_engine.py |

---

## 14. CODEX-SPEZIFISCHE ANWEISUNGEN

### Wenn du einen Bug debuggst:
1. **Zuerst lesen:** Die relevante Frontend-Funktion in `5eyes_v2.html` UND den entsprechenden Backend-Router/Service
2. **Datenpfad verfolgen:** Wo kommt der Wert her? UI → JS-Funktion → API-Call → Backend-Validierung → DB → Response → JS-Render
3. **Nie blind ändern** ohne den Kontext beider Seiten (Frontend + Backend) zu kennen

### Wenn du testest:
1. Backend direkt via `curl` oder Python-`requests` testen (auth-Token aus DB oder frontend)
2. DB-Stand prüfen: `sqlite3 ~/5eyes/5eyes.db "SELECT * FROM risk_assessments WHERE mandate_id='...';"`
3. Frontend-Änderungen: Electron neu starten (kill alle `electron` Prozesse, dann `npm start`)
4. Backend-Änderungen: Python-Prozess auf Port 8000 killen, Electron neu starten (startet Backend auto)

### Wichtige Backend-Validierungen die Silent-Fehler verursachen:
- `RiskAssessmentCreate.investment_horizon_label` → Literal-Type (jetzt erweitert)
- `TargetAllocationCreate` → Summe muss genau 10000 bps ergeben
- `SuitabilityCheckCreate` → warning_delivered_at Pflicht wenn warning_delivered=True

### Frontend State-Reset nach Neuladen:
```javascript
// Diese Variablen werden bei Tab-Wechsel nicht automatisch gesetzt:
strategyState.allocation  // Nur gesetzt nach API-Call oder Engine-Lauf
strategyState.risk        // Nur gesetzt nach Risk-Assessment-Load
alloc[]                   // Initialer Hardcode-Demo-Wert bis Engine läuft!
```

---

## 15. DATENBANKSTRUKTUR (Wichtigste Tabellen)

```sql
clients          (id, first_name, last_name, ...)
mandates         (id, client_id, mandate_type, ...)
risk_assessments (id, mandate_id, final_score_x10, final_profile, investment_horizon_label, is_current, ...)
target_allocations (id, mandate_id, target_equities_bps, ..., is_current, ...)
cashflows        (id, client_id, amount_rappen, frequency, nature, ...)
goals            (id, mandate_id, goal_type, target_amount_rappen, target_date, ...)
wealth_positions (id, client_id, asset_class, sub_asset_class, market_value_rappen, ...)
products         (id, asset_class, sub_asset_class, ticker_symbol, ...)
optimizer_policies (id, is_current, ...)
house_matrix     (id, policy_id, score_from, score_to, profile_name, equity_target_bps, ...)
capital_market_assumptions (id, is_current, equity_ch_return_bps, ...)
```

---

## 16. SCORING-LOGIK BACKEND (risk_scoring.py)

```python
# HORIZON_CAPACITY_MATRIX: (horizon_years, capacity_band) → score_x10
# capacity_band: 1=Risikoarm, 2=Sicherheitsorientiert, 3=Ausgewogen, 4=Wachstumsorientiert, 5=Dynamisch
# horizon_years: 1,2,4,6,9,15

# Beispiel: horizon=9 Jahre, capacity_band=3 (Ausgewogen) → score_x10 = ?
# Final: min(capacity_score, willingness_score) = final_score_x10 → /10 = final score (1-10)

# Profile-Mapping (riskScoreToProfile in frontend, CAPACITY_SCORE_TO_PROFILE in backend):
# 1-2: Kapitalschutz
# 3-4: Defensiv
# 5-6: Ausgewogen
# 7-8: Wachstumsorientiert
# 9:   Dynamisch
# 10:  Aktien
```

---

*Erstellt: 2026-04-06 | Version: 1.0 | Für: Codex/Claude systematisches Debugging*
