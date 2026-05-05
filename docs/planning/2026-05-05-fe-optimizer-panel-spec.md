# FE-Optimizer-Panel — Spec für Codex (Phase 6)

## Meta

- **Titel**: Optimization-Panel im Allocation-View
- **Datum**: 2026-05-05
- **Owner**: Emanuele
- **Branch-Vorschlag**: `codex/fe-optimizer-panel` (von `codex/rp-ueberarbeitung`, da FE-only)
- **Workspace**: `C:\5eyes\5eyes_stage9_release_ready` (nicht der Audit-Workspace)
- **Backend-Voraussetzung**: Optimizer Phase 1–5 fertig im Audit-Branch `codex/audit-master`
  → siehe `docs/planning/2026-05-05-stochastic-optimizer-spec.md`
- **Audit-Branch ist NICHT gemerged** — vor diesem FE-Block muss Audit-Branch in develop sein.

## Ziel

Berater muss auf einen Blick verstehen:
1. **Welcher Allocation-Pfad** wurde benutzt — House-Matrix oder stochastischer Optimizer?
2. **Wie zuverlässig** ist die Allokation — Konvergenz, Iterationen, Stress-Test-Resultate?
3. **Was passiert** wenn ein Goal angepasst wird — Sensitivity-Slider live.

Diese drei Sichten kommen als zusätzliches Panel auf der Allocation-Page (Page `al`),
optional ein-/ausblendbar via Berater-Toggle "Optimizer-Detail".

## Problem (heute)

Backend liefert via `target_allocation`-API neue Felder:
- `optimization_method`, `optimization_status`, `optimization_seed`,
  `optimization_iterations`, `optimization_objective_value_milli`
- `stress_evaluations` als JSON-Object im Response-Body

Diese werden vom FE aktuell ignoriert — Berater sieht nur die Bucket-Torte.
Ergebnis: keine Erklärbarkeit (Compliance-Risiko bei FINMA-Audit), keine
Sensitivity-Analyse, kein Vertrauensmaß.

## Scope

- Optimization-Status-Pill oben in der Allocation-Page
- Reasoning-Trace als Bullet-Liste (collapsible)
- Stress-Test-Tabelle (3 Szenarien × End-Wealth, Drawdown)
- Sensitivity-Slider pro Goal (±20% target → live re-compute via API)
- Constraint-Active-Anzeige (welche Bands binden)

## Nicht-Scope

- Editing der Optimizer-Mode in der UI (das ist Backend-Config)
- Mehrere Allocations parallel vergleichen
- Export der Optimization-Trace als PDF (kommt später ins Reporting-Modul)

## Fachlogik

### Quellen
- 3eyes-Schulung 2024-04-09 Slide 9: "Differenzierungsfaktoren — Realistische Projektionen"
- Mulvey/Ziemba — Optimizer braucht Erklärbarkeit für PK-Mandate (FINMA RS 2017/2)

### Verbindliche Regeln
1. **Status-Pill mit Farbe**: grün (converged), gelb (diverged_infeasible), grau (fallback_house_matrix), grau (NULL = pre-Optimizer)
2. **Reasoning-Trace** wird 1:1 aus `target_allocation` Response gelesen (kein Frontend-Logik dazu)
3. **Sensitivity-Slider** löst neuen API-Call aus (siehe Endpoint-Sektion); UI zeigt Loading-State
4. **Stress-Tabelle** wird gerendert wenn `stress_evaluations !== null`, sonst ausgeblendet
5. **Audit-Anchor** wird unten klein angezeigt: "Method: stochastic | Seed: 42 | Iter: 47" — für FINMA-Trace

### Owner-Decisions

- **OD-FE-1**: Default-Sichtbarkeit Optimizer-Panel: ✅ "expanded wenn `optimization_method != null`, sonst collapsed"
- **OD-FE-2**: Sensitivity-Slider-Granularität: ✅ ±20% in 5%-Schritten (5 Stufen: -20, -10, 0, +10, +20)
- **OD-FE-3**: Stress-Tabelle Spalten: Szenario | End-Vermögen (CHF) | Min-Vermögen (CHF) | Max-DD (%)
- **OD-FE-4**: Wenn `optimization_status='fallback_house_matrix'`: Banner "Solver konvergierte nicht — House-Matrix-Default verwendet" mit Link auf Reasoning

## Betroffene Module / Dateien

### Backend (FERTIG — Stand 2026-05-05, commits 269f6a1 + 2b21fb8 + fcc600c)

- `TargetAllocationGenerateResponse` (POST `/target-allocation/generate`):
  - `optimization_method/_status/_seed/_iterations/_objective_value_milli` (Phase 4)
  - `stress_evaluations: dict | None` (Phase 5.2 + 6 passthrough)
  - `reasoning: list[str]` mit Solver-Trace (Phase 6.2)
- Identische Felder werden auch von **GET `/target-allocation/current/payload`** geliefert
  — beim Page-Reload muss das FE NICHT erneut den Solver triggern (Persistenz Phase 6.1+6.2):
  - `target_allocations.stress_evaluations_json` (TEXT, JSON-Object)
  - `target_allocations.optimizer_reasoning_json` (TEXT, JSON-Liste)
- Neuer Endpoint **POST `/mandates/{id}/target-allocation/sensitivity`** (Phase 6).
  Gepinnter Solver-Seed → identische Scenarios baseline vs. modified → sauberes Delta.
  Body: `{goal_id: str, target_delta_pct: int}` mit delta ∈ {-20, -10, 0, 10, 20}.
  Response-Felder (alle 5 baseline+new-Paare zum direkten Rendern):
  `weights_bps_baseline/_new`, `objective_value_milli_baseline/_new`,
  `target_amount_rappen_baseline/_new`, `delta_objective_pct`,
  `status_baseline/_new`. 200/404/409/422 nach Spec.
- Robustheit: defekter JSON in den DB-Spalten fuehrt nicht zum Crash, fallt
  einfach auf None bzw. leere Reasoning-Zeile zurueck.

### Frontend (`5eyes-electron/frontend/5eyes_v2.html`)

- **Bereich `#page-al`** (Allocation-Page) bekommt nach der Asset-Allocation-Torte ein neues Panel `#al-optimizer-panel`
- **Hilfsfunktion `renderOptimizerPanel(payload)`** in der HTML-JS-Section
- **Hilfsfunktion `renderStressTable(stressEvals)`**
- **Hilfsfunktion `renderSensitivitySlider(goal, currentTarget)`**

## API / Schnittstellen

### Erweiterung Response (bereits da)

`TargetAllocationGenerateResponse` JSON enthält:
```json
{
  "target_allocation": {
    "optimization_method": "stochastic",
    "optimization_status": "converged",
    "optimization_seed": 4252227462396896290,
    "optimization_iterations": 47,
    "optimization_objective_value_milli": 12500000000,
    ...
  },
  "stress_evaluations": {
    "great_depression_1929": {
      "scenario_name": "great_depression_1929",
      "end_wealth_rappen": 67500000,
      "min_year_wealth_rappen": 41000000,
      "max_drawdown_bps": 5800
    },
    "financial_crisis_2008": { ... },
    "covid_inflation_2020_2022": { ... }
  },
  "reasoning": [
    "Stochastic Solver (SLSQP): 47 iterations across 4 multi-starts.",
    "Best objective L(w*) = 1.250e+10",
    "Stress 'great_depression_1929': End-Vermoegen 6'750'000 CHF, Max Drawdown 58.0%."
  ]
}
```

**Backend-TODO** (kleine Erweiterung in `routers/allocation.py`):
- `stress_evaluations` muss explizit ins Response-Schema (Pydantic). Aktuell ist es im Backend nur in `OptimizerResult.stress_evaluations`. Backend muss das in den `target_allocation`-Response durchschleifen.

### Neuer Endpoint: Sensitivity-Analyse

```
POST /mandates/{mandate_id}/allocation/sensitivity
Body: {
  "goal_id": "goal-pension-uuid",
  "target_delta_pct": -10        // -20, -10, 0, +10, +20
}
Response: {
  "delta_pct": -10,
  "target_amount_rappen_new": 21600_00,
  "objective_value_milli_new": 8400000000,
  "delta_objective_pct": -32.8,    // -32.8% = große Verbesserung wenn Pension reduziert
  "weights_bps_new": { "equities": 6500, ... }
}
```

**Backend-TODO** (Codex schreibt Spec für neuen Endpoint, ich review):
- `routers/allocation.py` → `@router.post("/mandates/{id}/allocation/sensitivity")`
- Implementierung: `goal_to_liability_path(goal_with_modified_target)` → `run_solver(...)` → return delta vs. baseline
- Authorization: gleicher Check wie `generate_target_allocation`

## UI / UX

### Layout-Skizze

```
┌─ Page: al (Allocation) ───────────────────────────────────────┐
│ [Bucket-Torte]                                                │
│                                                                │
│ ┌─ #al-optimizer-panel ────────────────────────────────────┐ │
│ │ 🟢 Optimizer: Konvergiert (47 Iter, 4 Multi-Starts)       │ │
│ │                                                            │ │
│ │ ▼ Reasoning anzeigen                                       │ │
│ │   • Best objective L(w*) = 1.25e+10                       │ │
│ │   • Stress 1929: -58% Max-DD, End 6.75M CHF              │ │
│ │   • Stress 2008: -38% Max-DD, End 8.50M CHF              │ │
│ │   • Stress 2022: -23% Max-DD, End 9.20M CHF              │ │
│ │                                                            │ │
│ │ ▼ Stress-Tests                                             │ │
│ │ ┌──────────────────────────────────────────────────────┐ │ │
│ │ │ Szenario        │ End-Vermögen │ Min-Vermögen │ DD %  │ │ │
│ │ │ 1929 Depression │   6.75M      │   3.10M      │ 58.0% │ │ │
│ │ │ 2008 Crisis     │   8.50M      │   5.20M      │ 38.0% │ │ │
│ │ │ 2020/22 Covid   │   9.20M      │   7.80M      │ 23.0% │ │ │
│ │ └──────────────────────────────────────────────────────┘ │ │
│ │                                                            │ │
│ │ ▼ Sensitivity                                              │ │
│ │ Pension Hart: [-20%] [-10%] [→0%] [+10%] [+20%]           │ │
│ │   bei -10%: Objective sinkt um 33% (besser erfüllbar)     │ │
│ │                                                            │ │
│ │ Audit: stochastic | seed 4252... | iter 47                │ │
│ └────────────────────────────────────────────────────────────┘ │
└────────────────────────────────────────────────────────────────┘
```

### Status-Farben

| Status | Pill-Farbe | Icon |
|---|---|---|
| `converged` | grün (var(--pos)) | 🟢 |
| `diverged_infeasible` | gelb (var(--warn)) | 🟡 |
| `fallback_house_matrix` | grau (var(--n5)) | ⚙️ |
| `null` (kein Optimizer) | grau hellt (var(--n3)) | — |

### Fehlerverhalten

- Backend liefert `optimization_method=null` → Panel collapsed, nur "Allokation via House-Matrix-Default"
- Backend liefert `stress_evaluations=null` → Stress-Tabelle ausblenden
- Sensitivity-API timeout (>10s) → Toast "Sensitivity-Analyse nicht verfügbar, später erneut"
- Sensitivity-API fehler 500 → Toast Error mit Reason aus Response

### Demo-/Offline-Verhalten

- `desktop-api.js::Mock` muss für `/allocation/sensitivity` ein realistisches Mock-Response liefern
- Im Offline-Modus: Sensitivity-Slider deaktiviert mit Tooltip "Online-Verbindung nötig"

## Akzeptanzkriterien

1. ✅ Bei `OPTIMIZER_MODE=house_matrix` (Backend) zeigt FE den Panel mit "House-Matrix-Default", keine Stress-Tabelle.
2. ✅ Bei `OPTIMIZER_MODE=stochastic` zeigt FE: grünen Status-Pill, expandable Reasoning, Stress-Tabelle, Sensitivity-Slider.
3. ✅ Sensitivity-Slider bewegt: API-Call löst aus, Loading-State im UI sichtbar, Response-Werte werden angezeigt.
4. ✅ Audit-Footer zeigt method/seed/iter — für FINMA-Trace.
5. ✅ Wenn `stress_evaluations.great_depression_1929.max_drawdown_bps > 5000`: Stress-Zeile rot markiert (Risiko-Hinweis).
6. ✅ Backwards-compat: alte `target_allocation` ohne Optimizer-Felder rendert ohne Crash.

## Testfälle

### Unit (Frontend)
- `renderOptimizerPanel({optimization_method: 'stochastic', ...})` → DOM enthält "Stochastisch" + grüner Pill
- `renderOptimizerPanel({optimization_method: null})` → DOM zeigt "House-Matrix-Default", keine Stress-Tabelle
- `renderStressTable(emptyStress)` → kein Crash, leerer Container

### API (Backend)
- `POST /allocation/sensitivity` mit gültigem goal_id+delta_pct=-10 → 200, neue weights_bps
- `POST /allocation/sensitivity` mit unbekanntem goal_id → 404
- `POST /allocation/sensitivity` ohne Auth → 401

### GUI / E2E (manuell)
- Mandant mit Pension-Hart-Goal anlegen → Allocation generieren → Optimizer-Panel zeigt grün
- Sensitivity-Slider auf -20% → Objective sinkt deutlich
- Sensitivity-Slider auf +20% → Objective steigt (Pension wird schwerer erreichbar)

### Edge Cases
- Mandant ohne Goals → Stress-Tabelle leer/ausgeblendet, Sensitivity-Slider deaktiviert
- Optimizer-Status `fallback_house_matrix` → orange Banner mit Link auf Reasoning
- Stress-Eval missing für eines der 3 Szenarien → übrige zeigen, fehlendes als "—"

## Risiken

| Risiko | Wahrscheinlichkeit | Mitigation |
|---|---|---|
| Sensitivity-API zu langsam (>5s) | mittel | Cache-Eintrag pro (mandate_id, goal_id, delta) gültig 60s |
| Stress-Tabelle visuell überfordernd für Berater | niedrig | Default collapsed, expand-on-click |
| FINMA verlangt mehr Audit-Detail (z.B. Lokal-Optima) | hoch | Phase 7 Spec: PDF-Export der Optimization-Trace |
| Rendering-Performance bei vielen Goals (>10) | niedrig | Sensitivity-Slider lazy-rendern (nur sichtbares Goal) |

## Implementierungs-Checkliste für Codex

1. Backend ✅ FERTIG (commits 269f6a1, 2b21fb8, fcc600c — 525/525 Tests gruen).

2. Frontend `5eyes_v2.html`:
   - [ ] Container `<div id="al-optimizer-panel"></div>` nach der Asset-Allocation-Torte einfügen
   - [ ] CSS-Klassen: `.opt-panel`, `.opt-pill`, `.opt-pill-green`, `.opt-pill-yellow`, `.opt-pill-grey`, `.stress-table`, `.sens-slider`
   - [ ] JS: `renderOptimizerPanel(allocationPayload)` — wird nach API-Response in `applyAllocationEngineResult()` aufgerufen
   - [ ] JS: `renderStressTable(stressEvals)`
   - [ ] JS: `renderSensitivitySlider(goal, currentTarget, mandateId)` mit fetch-Call
   - [ ] grep-Suche: `applyAllocationEngineResult` (existing function in HTML) — nach dem Bucket-Torten-Render Code einfügen

3. desktop-api.js Mock:
   - [ ] Mock für `/allocation/sensitivity` mit zufälligen aber konsistenten Werten

4. Manueller Test:
   - [ ] Backend mit `OPTIMIZER_MODE=stochastic` starten
   - [ ] Test-Mandant mit 2 Goals (Hart + Primaer) anlegen
   - [ ] Allocation generieren → Optimizer-Panel sichtbar
   - [ ] Sensitivity-Slider bewegen → Werte ändern sich live
   - [ ] Stress-Tabelle korrekt gerendert

## Branch-Befehl (Codex)

```powershell
.\scripts\start_codex_branch.ps1 -Slug "fe-optimizer-panel" -FromCurrent
```
(`-FromCurrent` weil rp-ueberarbeitung noch nicht in develop ist)

## Offene Fragen an Owner

1. **Position des Panels**: oberhalb oder unterhalb der Bucket-Torte? Vorschlag: unterhalb, weil Berater zuerst die Allokation visuell verstehen will.
2. **Default-Hardness-Erklärung**: soll im Sensitivity-Slider auch `hardness` änderbar sein (Hart→Primaer→Opp)? Aktuell nur target_amount.
3. **Stress-Szenario-Erweiterung**: nur 3 vordefinierte oder Berater kann eigene definieren? Vorschlag: 3 fest in Phase 6, eigene Szenarien in Phase 7.

Wenn alle 3 Defaults okay: Codex startet sofort.
