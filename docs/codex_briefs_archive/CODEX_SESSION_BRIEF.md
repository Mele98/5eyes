# Codex Session Brief — mc-fan-chart Weiterführung
**Stand:** 2026-04-09 | **Erstellt von:** Claude Analyse-Session
**Workspace:** `C:\5eyes\5eyes_stage9_release_ready`
**Branch:** `codex/mc-fan-chart`

---

## Aktuelle Lage (was du gebaut hast — Bewertung)

### Gut implementiert — NICHT anfassen
| Feature | Datei | Zeile | Status |
|---|---|---|---|
| Fan Chart P10/P50/P90 | `5eyes_v2.html:8586` | `upgradeFanChartWithMonteCarlo()` | ✓ Korrekt |
| Zieldauer Horizont-Clip | `portfolio_engine.py:1696` | `_goal_duration_years()` + `_full_goal_duration_years()` | ✓ Korrekt |
| Cholesky 3-Level-Fallback | `portfolio_engine.py` (uncommitted) | `_is_valid_cholesky()` + `_identity_cholesky()` | ✓ Korrekt |
| `_rebalance_to_total` Guard | `portfolio_engine.py` (uncommitted) | wirft `ValueError` bei Normalisierungsfehler | ✓ Korrekt |
| Sub-Asset-Class CMA | `portfolio_engine.py:946` | 22 Klassen + Fallback-Kette | ✓ Korrekt |
| `generate_target_allocation` Refactor | `portfolio_engine.py` | 5 Helper-Funktionen | ✓ Korrekt |

### Uncommitted (Working Copy) — muss zuerst committed werden
```
git status --short
```
Du siehst:
- `M` Modified: `portfolio_engine.py`, `risk_scoring.py`, `schemas/allocation.py`,
  `schemas/profiling.py`, `routers/clients.py`, `routers/mandates.py`,
  `routers/wealth.py`, `5eyes_v2.html`, `main.js`
- `??` Untracked: 6 neue Testdateien + `CODEX_DEBUG_GUIDE.md`

---

## SCHRITT 1 — Uncommitted Changes committen

Prüfe jeden Modified-File: `git diff HEAD -- <datei>`
Dann stage + commit:

```bash
git add 5eyes-backend/services/portfolio_engine.py
git add 5eyes-backend/services/risk_scoring.py
git add 5eyes-backend/schemas/allocation.py
git add 5eyes-backend/schemas/profiling.py
git add 5eyes-backend/routers/clients.py
git add 5eyes-backend/routers/mandates.py
git add 5eyes-backend/routers/wealth.py
git add 5eyes-electron/main.js
git add 5eyes-backend/tests/test_goal_scoring_horizon.py
git add 5eyes-backend/tests/test_allocation_rebalance_normalization.py
git add 5eyes-backend/tests/test_cholesky_and_horizon.py
git add 5eyes-backend/tests/test_simulation_rebalance_costs.py
git add 5eyes-backend/tests/test_risk_budget_logging.py
git add 5eyes-backend/tests/test_cashflow_timeline.py
git add CODEX_DEBUG_GUIDE.md
git commit -m "Finalize security fixes, goal horizon scoring, Cholesky fallback, and uncommitted router patches"
```

---

## SCHRITT 2 — BE-2 Fix: ALTER TABLE Whitelist wiederherstellen

**Datei:** `5eyes-backend/database.py`

**Problem:** `import re` wurde gelöscht + alle drei Whitelist-Guards entfernt.

**Fix 1** — `import re` wieder an den Anfang der Datei:
```python
import re
```

**Fix 2** — In `ensure_runtime_columns()` vor `conn.execute(text(f'ALTER TABLE ...'))`:
```python
if not re.match(r'^[a-z][a-z0-9_]+$', table_name):
    raise ValueError(f"Ungültiger Tabellenname: {table_name!r}")
if not re.match(r'^[a-z][a-z0-9_]+$', column_name):
    raise ValueError(f"Ungültiger Spaltenname: {column_name!r}")
if not re.match(r'^[A-Z]+$', sql_type):
    raise ValueError(f"Ungültiger SQL-Typ: {sql_type!r}")
conn.execute(text(f'ALTER TABLE {table_name} ADD COLUMN {column_name} {sql_type}'))
```

Alle bestehenden Einträge in `additive_columns` sind bereits valide (lowercase Namen,
UPPERCASE Typen) — die Validierung greift nie bei korrektem internen Input.

---

## SCHRITT 3 — BE-1: PRAGMA key Binding prüfen

**Datei:** `5eyes-backend/database.py:138`

Aktueller Stand:
```python
_key = (db_key or settings.db_key or '').replace("'", "''")
conn.execute(f"PRAGMA key = '{_key}'")
```

Teste ob parameterized binding funktioniert:
```python
conn.execute("PRAGMA key = ?", [db_key or settings.db_key or ''])
```

- Wenn OK → verwende Binding, commit
- Wenn Exception (sqlcipher3 unterstützt `?` für PRAGMA nicht) → behalte aktuelle
  Variante, füge Kommentar hinzu: `# sqlcipher3: parameterized binding not supported for PRAGMA`

Gleiche Prüfung für `migrate_to_sqlcipher.py:52` und `:102`.

---

## SCHRITT 4 — Performance Fix: _sub_asset_class_assumption_map Loop

**Datei:** `5eyes-backend/services/portfolio_engine.py`
**Funktion:** `_build_sub_asset_class_assumption_reference` (ca. Zeile 1358)

**Problem:** `_sub_asset_class_assumption_map(cma)` wird einmal pro Loop-Iteration extra
aufgerufen für die `"source"`-Entscheidung → O(n) JSON-Parses.

**Fix:** Vor der Schleife berechnen:
```python
def _build_sub_asset_class_assumption_reference(
    sub_allocations: list[dict],
    cma: CapitalMarketAssumption,
) -> list[dict]:
    returns, vols = _asset_class_expected_metrics(cma)
    assumption_map = _sub_asset_class_assumption_map(cma)   # ← einmal holen
    seen: set[tuple[str, str]] = set()
    items: list[dict] = []
    for item in sub_allocations:
        ...
        expected_return_bps, expected_volatility_bps = _sub_asset_class_metrics(
            sub_asset_class, asset_class, cma, returns, vols,
        )
        items.append({
            ...
            "source": "CMA Sub-Asset-Class" if sub_asset_class in assumption_map else "Asset-Class fallback",
        })
    return items
```

---

## SCHRITT 5 — Tests laufen lassen

```bash
cd C:\5eyes\5eyes_stage9_release_ready\5eyes-backend
python -m pytest tests/ -v
```

Alle Tests müssen grün sein.

---

## Was du NICHT anfassen sollst

- `upgradeFanChartWithMonteCarlo()` — korrekt implementiert
- `_goal_duration_years()` + `_full_goal_duration_years()` — korrekte Logik
- Cholesky-Fallback-Kette — korrekt
- Sub-Asset-Class Assumptions Dict (22 Klassen) — korrekt
- `generate_target_allocation` Refactor — korrekt

---

## SCHRITT 6 — Uncommitted HTML-Refactor: Status prüfen und committen

**Die aktuelle Working Copy von `5eyes_v2.html` ist ein aktiver Refactor-Zustand.**

Gegenüber HEAD wurden bereits 601 Zeilen geändert (noch nicht staged):

| Was wurde geändert | Alt | Neu |
|---|---|---|
| DOM-Init | `applyClaudeUxMidTermStructure()` | `initDomLayout()` |
| Pref-Summary | `applyClaudeUxQuickWins()` | `initPrefSummaryText()` |
| Override-Modal | `applyOv()` (sync) | `openOverrideModal()` + `async applyOv()` |
| Modal-Bindings | `bindLegacyReviewModalActions()` | `bindReviewModals()` |
| Cashflow-Editor | `openCashflowEditor()` (sync) | `async openCashflowEditor()` |
| Legacy-Funktionen | `resetCashflowModalLegacy`, `applyAllocationEngineResultLegacy__unused`, `renderAdvisoryLogListLegacy__unused` | ENTFERNT |
| Neue Funktionen | — | `saveConflictDisclosure()`, `renderSuitabilityChecks()`, `saveSuitabilityCheck()`, `toggleSuitabilityWarningDate()`, `refreshBaselineChartFromClientData()`, `toggleCompareSection()`, `goalEvaluationNoteHtml()` |

**Bevor du `5eyes_v2.html` committetest**: Sicherstellen dass die umbenannten Funktionen
korrekt aufgerufen werden (keine dead references auf alte Namen).

Prüfe mit grep:
```bash
grep -n "applyClaudeUxQuickWins\|applyClaudeUxMidTermStructure\|bindLegacyReviewModalActions\|openCashflowEditorLegacy\|resetCashflowModalLegacy\|renderAdvisoryLogListLegacy" 5eyes-electron/frontend/5eyes_v2.html
```
Wenn Null Treffer → alles OK, dann committen.

---

## SCHRITT 7 — Dead Code: buildMonteCarloGoalsHtml verbinden

**Datei:** `5eyes-electron/frontend/5eyes_v2.html`

`buildMonteCarloGoalsHtml(mc)` (Zeile 3080) ist definiert aber wird nirgends aufgerufen.
Die Funktion rendert Goal-Scores mit Pfaderfolg und Funded-Ratio — fachlich wertvoll.

Fehlend: ein `<div id="aa-mc-goals">` im Engine-Panel und ein Aufruf in `renderEngineRuntimePanels()`.

**Fix:**
1. In `renderEngineRuntimePanels()` nach der Zeile `var mcSummary=document.getElementById('aa-mc-summary');` ergänzen:
   ```js
   var mcGoals=document.getElementById('aa-mc-goals');
   ```
2. In der Null-Branch ergänzen:
   ```js
   if(mcGoals)mcGoals.innerHTML=engineRuntimeInfoBox('Ziel-Pfadanalyse erscheint nach der ersten Berechnung.');
   ```
3. Nach `mcSummary.innerHTML=buildMonteCarloSummaryHtml(mc);` ergänzen:
   ```js
   if(mcGoals)mcGoals.innerHTML=buildMonteCarloGoalsHtml(mc);
   ```
4. Im HTML (nach dem `aa-mc-summary`-Div) ein neues Panel einfügen:
   ```html
   <div class="ae-label">Ziel-Pfadanalyse</div>
   <div id="aa-mc-goals" class="ae-body"></div>
   ```

Achtung: `evaluation_note` wird bereits durch `goalEvaluationNoteHtml()` in der
Strategie-Zusammenfassung (Zeile 11849) angezeigt — dieses Panel wäre eine zweite Stelle.

---

## Sauberes Frontend-Backend Alignment (neu in dieser Session)

### RiskAssessmentResponse — erweitert (committed)
`schemas/profiling.py` hat neue Felder in `RiskAssessmentResponse`:
- Einzelpunkte: `q_income_points`, `q_obligations_points`, `q_savings_points`, `q_wealth_points`
- Einzelpunkte Bereitschaft: `q_investment_goal_points`, `q_risk_preference_points`, `q_risk_behavior_points`
- Neue Unterklasse: `RiskAssessmentAnswerResponse` (id, question_number, section, label, points)
- `answers: list[RiskAssessmentAnswerResponse] = []` in der Response

`profiling.py` lädt `answers` jetzt eagerly via `selectinload(RiskAssessment.answers)` — kein N+1.

### Client-Horizont (committed)
Neue Felder `investment_horizon_start` + `investment_horizon_end` auf `Client`-Ebene (nicht Mandat).
Frontend: `currentMandateHorizonRange()` → `inferMandateRiskHorizon()` → Vorschlag in Risikofragebogen.
Mapping: ≤4 J → "2 bis 3 Jahre", 5-7 J → "4 bis 5 Jahre", 8-11 J → "8 bis 11 Jahre", ≥12 J → "12 Jahre und mehr".
Diese Labels sind alle in `HORIZON_YEARS` (Backend) und im Schema-`Literal` vorhanden ✓

### Sub-Asset-Class Defaults: FE/BE Abweichung
Backend hat 24 Einträge in `_DEFAULT_SUB_ASSET_CLASS_ASSUMPTIONS`, FE hat 18 in `ADMIN_CMA_SUBASSET_DEFAULTS`.
Die 6 fehlenden Einträge im FE: `Thema Verteidigung`, `Thema Fossile Energie`, `Thema Tabak`,
`Thema Alkohol`, `Thema Gluecksspiel`, `Thema Kernenergie`.
**Auswirkung:** Admin kann Thema-Annahmen nicht per UI konfigurieren (Backend-Defaults werden immer verwendet).
**Priorität:** Niedrig — BE-Defaults greifen korrekt; nur UI-Gap.

### Advisory Log Status-Machine (neu — korrekt implementiert)

`PUT /mandates/{id}/advisory-log/{log_id}` mit State Machine:
- `Empfohlen` → `Beschlossen` → `Umgesetzt` (forward-only)
- `entry.status = None` wird als `"Empfohlen"` behandelt ✓
- Unbekannte Status-Werte → 422 ✓
- Audit-Log bei jeder Transition ✓
- Test-Coverage: 3 Szenarien in `test_advisory_log_status.py` ✓

---

## Nächstes Feature nach dieser Session: Handelsliste

Spec bereits fertig: `docs/planning/2026-04-02-rebalancing-trade-sheet.md`
Branch-Vorschlag: `codex/rebalancing-trade-sheet`

Scope: Frontend only — Modal `m-tl` + `openTradeList()` + Button in Handlungsempfehlungen-Panel.
Alle nötigen Daten sind bereits vorhanden in `live.position_drifts[]`.

---

## Bekannte offene Punkte (für spätere Session)

| ID | Thema | Datei | Priorität |
|---|---|---|---|
| FE-Dead | `buildMonteCarloGoalsHtml` nie aufgerufen | `5eyes_v2.html:3080` | Mittel |
| FE-Thema | 6 Thema Sub-Asset-Klassen fehlen in Admin-CMA-UI | `5eyes_v2.html:4759` | Niedrig |
| BE-7 | CORS `allow_origin_regex` — Klärung Electron-Origin nötig | `main.py:74` | Mittel |
| Merge | `develop` → `mc-fan-chart` Merge-Konflikt-Prüfung | — | Nach BE-2 Fix |
| ~~BE-8~~ | ~~MC Transaction Costs~~ — effektiv gelöst: Gesamtwert korrekt, nur per-Bucket-Attribution proportional (für MC-Zwecke ausreichend) | — | Geschlossen |
| SR-Page | `renderSrImplementationDecision` zeigt immer `logs[0]` — kein Status-Filter | `5eyes_v2.html:9153` | Niedrig |

---
*Generiert von Claude Analyse-Session 2026-04-09*
