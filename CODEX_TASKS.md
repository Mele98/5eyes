# 5eyes — Offene Tasks für Codex
**Stand:** 2026-04-10 | **Analysiert von:** Claude
**Workspace:** `C:\5eyes\5eyes_stage9_release_ready`
**Aktiver Branch:** `codex/mc-fan-chart`

Lies zuerst `CODEX_GUIDE.md`. Dann diese Datei von oben nach unten abarbeiten.
Jeder Task ist eigenständig beschrieben — kein implizites Wissen vorausgesetzt.

---

## TASK 1 — KRITISCH | ALTER TABLE Whitelist-Guards
**Datei:** `5eyes-backend/database.py`

### Problem
Zeile 199 führt `ALTER TABLE` mit f-String aus, ohne Eingaben zu validieren:
```python
conn.execute(text(f'ALTER TABLE {table_name} ADD COLUMN {column_name} {sql_type}'))
```
`import re` fehlt in der Datei. Alle drei Guards fehlen.

### Fix
**Schritt 1:** `import re` hinzufügen (ganz oben bei den anderen Imports).

**Schritt 2:** Direkt vor Zeile 199 (vor dem `conn.execute`) diese drei Guards einfügen:
```python
if not re.match(r'^[a-z][a-z0-9_]+$', table_name):
    raise ValueError(f"Ungültiger Tabellenname: {table_name!r}")
if not re.match(r'^[a-z][a-z0-9_]+$', column_name):
    raise ValueError(f"Ungültiger Spaltenname: {column_name!r}")
if not re.match(r'^[A-Z]+$', sql_type):
    raise ValueError(f"Ungültiger SQL-Typ: {sql_type!r}")
```

### Verifikation
Alle bestehenden `additive_columns`-Einträge sind lowercase mit Unterstrichen, SQL-Typen in UPPERCASE — die Guards feuern nie bei korrektem internen Input. Keine Tests nötig, aber prüfen dass App normal startet.

---

## TASK 2 — HOCH | Frontend/Backend IST-Allokation Divergenz
**Dateien:** `5eyes-electron/frontend/5eyes_v2.html` (~Zeile 2951) + `5eyes-backend/services/portfolio_engine.py` (~Zeile 204)

### Problem
Wenn eine Vermögensposition keine expliziten `alloc_*_bps`-Felder hat, greifen Fallback-Werte. Diese sind in Frontend und Backend **unterschiedlich**:

| Position-Typ | Frontend `inferPositionBucketMixBps()` | Backend `_default_weights_for_position()` |
|---|---|---|
| `Vorsorge` | EQ 40% / BO 35% / LI 25% | EQ 45% / BO 45% / LI 10% |
| `Custom` | ALT 100% | EQ 50% / BO 20% / RE 10% / ALT 5% / LI 15% |
| `Depot` (kein alloc) | LI 100% (default-case) | EQ 60% / BO 25% / ALT 5% / LI 10% |
| Unbekannter Typ | LI 100% | Custom-Fallback (50/20/10/5/15) |

Das bedeutet: Das IST im Frontend-Chart und die IST-Berechnung der Engine divergieren für diese Positionen. Berater sieht falsche Ausgangslage.

### Fix
**In `5eyes_v2.html`, Funktion `inferPositionBucketMixBps()` (~Zeile 2951):**

Den `switch`-Block anpassen:
```javascript
switch(String(pos && pos.position_type || '')) {
  case 'Liquidität':  eq=0;    bo=0;    re=0;     li=10000; al=0;   break;
  case 'Immobilien':  eq=0;    bo=0;    re=10000; li=0;     al=0;   break;
  case 'Vorsorge':    eq=4500; bo=4500; re=0;     li=1000;  al=0;   break;  // war: 4000/3500/2500
  case 'Alternative': eq=0;    bo=0;    re=0;     li=0;     al=10000; break;
  case 'Custom':      eq=5000; bo=2000; re=1000;  li=1500;  al=500; break;  // war: 100% alt
  case 'Depot':       eq=6000; bo=2500; re=0;     li=1000;  al=500; break;  // war: default
  default:            eq=5000; bo=2000; re=1000;  li=1500;  al=500; break;  // war: 100% li
}
```

Die Werte entsprechen exakt den Backend-Defaults aus `_default_weights_for_position()`.

### Wichtig
`Hypothek` hat im Backend `{"equities":0,...,"liquidity":0}` — alle 0. Hypotheken sind Verbindlichkeiten (`assignment="Verbindlichkeit"`) und werden in `wealthScopePositions()` gefiltert. Sie kommen nie in `inferPositionBucketMixBps`. Kein Case nötig.

### Verifikation
Nach dem Fix: IST-Chart im Frontend zeigt dieselben Werte wie `bucket.current_weight_bps` vom Backend (nach Strategie-Berechnung). Manuell mit einem Mandat prüfen das Vorsorge-Positionen hat.

---

## TASK 3 — MITTEL | Tilt-Subtraktion ohne Floor-Check im Optimizer
**Datei:** `5eyes-backend/services/portfolio_engine.py`

### Problem A — Equity-Tilt (Zeile 2818-2822)
```python
# Zeile 2818 (Bedingung), 2819-2821 (Subtraktionen):
if not manual_target_override and annual_net_cashflow_rappen > 0 and growth_goals and score_bucket >= 7 and reserve_needed_rappen == 0:
    targets["equities"] += 150
    targets["bonds"] -= 100    # ← kein Floor-Check gegen minimums["bonds"]
    targets["liquidity"] -= 50 # ← kein Floor-Check gegen minimums["liquidity"]
```
Wenn `targets["bonds"]` nach vorherigen Tilts bereits knapp über `minimums["bonds"]` liegt, kann bonds negativ werden. `_rebalance_to_total()` normalisiert danach, aber der intendierte Equity-Tilt wird dann nicht vollständig applied.

### Problem B — Ziel-Tilt (Zeile 2691-2694, Funktion `_apply_goal_and_reserve_tilts()`)
```python
elif goal_type in ("Kapitalerhalt", "Vermoegensziel") and years <= 5:
    targets["equities"] -= 200   # ← kein Floor-Check gegen minimums["equities"]
    targets["liquidity"] += 100
    targets["bonds"] += 100
```
Wenn equities bereits nahe `minimums["equities"]` liegt (nach House-Matrix-Minimum + vorherigen Reduktionen), wird es negativ.

### Problem C — Bonds-Cap nach External Tilt (Zeile 2655, Funktion `_apply_external_exposure_tilts()`)
```python
targets["bonds"] += reduction  # ← kein Cap, bonds kann house_matrix.bonds_max_bps überschreiten
```
Bonds kann die House-Matrix-Obergrenze überschreiten. `_rebalance_to_total()` kürzt dann willkürlich aus anderen Klassen.

### Fix

**Problem A — Zeile 2818:** Existing `if`-condition um Floor-Guards erweitern (Zeile 2818 ersetzen):
```python
if (not manual_target_override and annual_net_cashflow_rappen > 0
        and growth_goals and score_bucket >= 7 and reserve_needed_rappen == 0
        and targets["bonds"] - minimums["bonds"] >= 100
        and targets["liquidity"] - minimums["liquidity"] >= 50):
    targets["equities"] += 150
    targets["bonds"] -= 100
    targets["liquidity"] -= 50
    reasoning.append("Positiver Cashflow und langfristige Wachstumsziele ermoeglichen einen moderaten Equity-Tilt.")
```
`minimums` ist in diesem Scope vorhanden (main body von `generate_target_allocation()`).

**Problem B — Zeile 2691:** Den `elif`-Block in `_apply_goal_and_reserve_tilts()` ersetzen:
```python
elif goal_type in ("Kapitalerhalt", "Vermoegensziel") and years <= 5:
    eq_reduction = min(200, max(0, targets["equities"] - minimums["equities"]))
    if eq_reduction > 0:
        targets["equities"] -= eq_reduction
        targets["liquidity"] += eq_reduction // 2
        targets["bonds"] += eq_reduction - eq_reduction // 2
        reasoning.append(f"Das Vermoegensziel '{goal.label}' mit kurzem Horizont reduziert den Aktienanteil leicht.")
```
`minimums` ist in `_apply_goal_and_reserve_tilts()` ein Parameter — in scope.

**Problem C — Zeile 2655:** Zeile in `_apply_external_exposure_tilts()` ersetzen:
```python
# Vorher:
targets["bonds"] += reduction
# Nachher:
targets["bonds"] = min(int(house_matrix.bonds_max_bps), targets["bonds"] + reduction)
```
`house_matrix` ist ein Parameter von `_apply_external_exposure_tilts()` — in scope. `maximums` ist **nicht** in scope hier, daher `house_matrix.bonds_max_bps` als Cap verwenden.

### Verifikation
Bestehende Tests in `tests/test_allocation_rebalance_normalization.py` laufen durch. Manuell prüfen: Mandat mit sehr hohem Immobilienanteil im Gesamtvermögen → Engine soll valide Allokation zurückgeben, kein negativer targets-Wert vor `_rebalance_to_total()`.

---

## TASK 4 — MITTEL | SR-Page zeigt falschen Advisory-Log
**Datei:** `5eyes-electron/frontend/5eyes_v2.html`

### Problem
`renderSrImplementationDecision()` nimmt immer `currentReviewState.logs[0]` ohne Status-Filter:
- **Zeile 9773:** `currentReviewState.logs[0]` — kein Status-Filter ← **hier fixen**
- **Zeile 11379:** `currentReviewState.logs[0]` — **NICHT ändern** (Demo-Save-Pfad, `logs[0]` ist dort absichtlich der gerade gespeicherte neue Eintrag)

Die API liefert Logs sortiert nach `entry_date DESC`, also ist `logs[0]` der neueste Eintrag. Das ist OK. **Aber:** Wenn der neueste Eintrag Status `Umgesetzt` hat, zeigt die SR-Page diesen Entry als "aktiven Entscheid" — obwohl die Strategie bereits vollständig umgesetzt ist.

Das SR-Panel soll den neuesten **offenen** Entscheid zeigen (`Empfohlen` oder `Beschlossen`). Falls alle umgesetzt, `logs[0]` als Fallback.

### Fix
**Nur Zeile 9773** in `renderSrImplementationDecision()` anpassen:

```javascript
// Vorher (Zeile 9773):
var activeEntry = entry || (currentReviewState.logs && currentReviewState.logs[0]) || null;

// Nachher:
var activeEntry = entry
  || (currentReviewState.logs || []).find(function(e){
       return e.status === 'Beschlossen' || e.status === 'Empfohlen';
     })
  || (currentReviewState.logs || [])[0]
  || null;
```

**Zeile 11379 bleibt unverändert.** Dort ist `logs[0]` der gerade per Demo-Save erzeugte Eintrag — das ist korrekt und absichtlich.

### Verifikation
In Demo-Modus: Advisory-Log-Eintrag erfassen (Status `Empfohlen`), dann Status auf `Umgesetzt` setzen. SR-Page soll danach **nicht** mehr diesen Entry als aktiven Entscheid zeigen — stattdessen leer oder Fallback-Anzeige.

---

## TASK 5 — MITTEL | CORS Regex zu breit
**Datei:** `5eyes-backend/config.py` Zeile 74

### Problem
```python
cors_allow_origin_regex: str | None = r'^(null|file://.*)$'
```
Electron's `loadFile()` sendet Origin `null` (der String). Nicht `file://...`. Die `file://.*`-Variante ist nie nötig und erlaubt theoretisch jeder lokalen HTML-Datei API-Zugriff.

### Fix
```python
cors_allow_origin_regex: str | None = r'^null$'
```

### Verifikation
App starten, normal einloggen und Strategie berechnen → funktioniert. Kein 403 im Backend-Log.

---

## TASK 6 — NIEDRIG | Frontend IST-Projektion ignoriert Backend-CMA
**Datei:** `5eyes-electron/frontend/5eyes_v2.html` (~Zeile 2959)

### Problem
`wealthProjectionInputs()` baut die IST-Gesamtvermögens-Projektion mit hartcodierten Renditen aus `ADMIN_CMA_DEFAULTS`:
```javascript
var returnMap = {
  equities: Number(ADMIN_CMA_DEFAULTS && ADMIN_CMA_DEFAULTS.equity_intl_return_bps || 690),
  bonds:    Number(ADMIN_CMA_DEFAULTS && ADMIN_CMA_DEFAULTS.bonds_fx_hedged_return_bps || 220),
  ...
};
```
Wenn der Admin im Backend andere CMA-Werte gepflegt hat (z.B. Aktien nur 5.5% statt 6.9%), gilt das nur für die SOLL-Prognose — nicht für den IST-Chart.

### Fix
`strategyState.allocation.asset_class_assumptions` ist ein **Array** von Objekten (nicht ein flaches Objekt). Jedes Objekt hat `asset_class` (String) und `expected_return_bps` (Integer).

Die `asset_class`-Werte sind: `"Aktien"`, `"Obligationen"`, `"Immobilien"`, `"Alternative"`, `"Liquiditaet"`.

Den bestehenden `returnMap`-Block in `wealthProjectionInputs()` (~Zeile 2959) ersetzen:

```javascript
// Vorher:
var returnMap = {
  equities: Number(ADMIN_CMA_DEFAULTS && ADMIN_CMA_DEFAULTS.equity_intl_return_bps || 690),
  ...
};

// Nachher:
var _acaList = strategyState && strategyState.allocation && strategyState.allocation.asset_class_assumptions;
var _acaMap = {};
if (Array.isArray(_acaList)) {
  _acaList.forEach(function(ac) { if (ac && ac.asset_class) _acaMap[ac.asset_class] = ac; });
}
var returnMap = {
  equities:     Number(_acaMap['Aktien']        && _acaMap['Aktien'].expected_return_bps        || ADMIN_CMA_DEFAULTS.equity_intl_return_bps       || 690),
  bonds:        Number(_acaMap['Obligationen']  && _acaMap['Obligationen'].expected_return_bps  || ADMIN_CMA_DEFAULTS.bonds_fx_hedged_return_bps    || 220),
  realEstate:   Number(_acaMap['Immobilien']    && _acaMap['Immobilien'].expected_return_bps    || ADMIN_CMA_DEFAULTS.real_estate_ch_return_bps     || 330),
  liquidity:    Number(_acaMap['Liquiditaet']   && _acaMap['Liquiditaet'].expected_return_bps   || ADMIN_CMA_DEFAULTS.liquidity_return_bps          || 80),
  alternatives: Number(_acaMap['Alternative']   && _acaMap['Alternative'].expected_return_bps   || ADMIN_CMA_DEFAULTS.alternatives_gold_return_bps  || 300),
};
```

**Wichtig:** Der alte Code verwendete `strategyState.allocation.capital_market_assumptions` — dieses Feld **existiert nicht** in der Backend-Response (`TargetAllocationGenerateResponse`). Das korrekte Feld ist `asset_class_assumptions` (Array).

### Verifikation
Strategie berechnen → IST- und SOLL-Projektionslinie verwenden dieselben CMA-Renditen. `console.log(_acaMap)` prüfen: Sollte 5 Einträge mit den deutschen Asset-Class-Namen zeigen.

---

## TASK 7 — NIEDRIG | buildMonteCarloGoalsHtml() nie aufgerufen
**Datei:** `5eyes-electron/frontend/5eyes_v2.html`

### Problem
Funktion `buildMonteCarloGoalsHtml(mc)` (~Zeile 3337) ist vollständig implementiert und rendert Ziel-Scores mit Pfaderfolg und Funded-Ratio. Wird aber **nirgends aufgerufen**.

### Fix
**Schritt 1:** In `renderEngineRuntimePanels()` ein `mcGoals`-Element hinzufügen (analog zu `aa-mc-summary`):
```javascript
var mcGoals = document.getElementById('aa-mc-goals');
```

**Schritt 2:** In der Null-Branch (wenn kein mc):
```javascript
if (mcGoals) mcGoals.innerHTML = engineRuntimeInfoBox('Ziel-Pfadanalyse erscheint nach der ersten Berechnung.');
```

**Schritt 3:** In der Haupt-Branch (nach `mcSummary.innerHTML = buildMonteCarloSummaryHtml(mc)`):
```javascript
if (mcGoals) mcGoals.innerHTML = buildMonteCarloGoalsHtml(mc);
```

**Schritt 4:** Im HTML (Engine-Panel, nach dem `aa-mc-summary`-Div):
```html
<div class="ae-label">Ziel-Pfadanalyse</div>
<div id="aa-mc-goals" class="ae-body"></div>
```

Achtung: `evaluation_note` wird bereits durch `goalEvaluationNoteHtml()` in der Strategie-Zusammenfassung angezeigt. Das neue Panel ist eine ergänzende Detailansicht — kein Duplikat.

### Verifikation
Nach Strategie-Berechnung: Im Engine-Panel erscheint ein neues "Ziel-Pfadanalyse"-Panel mit Scores pro Ziel.

---

## TASK 8 — NIEDRIG | Admin-CMA-UI: 6 Thema-Sub-Asset-Klassen fehlen
**Datei:** `5eyes-electron/frontend/5eyes_v2.html` (~Zeile 5032, `ADMIN_CMA_SUBASSET_DEFAULTS`)

### Problem
Backend hat 24 Einträge in `_DEFAULT_SUB_ASSET_CLASS_ASSUMPTIONS`. Frontend hat 18 in `ADMIN_CMA_SUBASSET_DEFAULTS`. Es fehlen:
- `Thema Verteidigung`
- `Thema Fossile Energie`
- `Thema Tabak`
- `Thema Alkohol`
- `Thema Gluecksspiel`
- `Thema Kernenergie`

**Auswirkung:** Admin kann Thema-CMA-Annahmen nicht per UI konfigurieren. Backend-Defaults greifen immer (unkritisch für Funktionalität, aber Admin-UI ist unvollständig).

### Fix
Die 6 fehlenden Einträge in `ADMIN_CMA_SUBASSET_DEFAULTS` ergänzen. Rendite-/Volatilitäts-Defaults aus `portfolio_engine.py: _DEFAULT_SUB_ASSET_CLASS_ASSUMPTIONS` übernehmen.

### Verifikation
Admin-CMA-Seite öffnen → alle 24 Subanlageklassen erscheinen editierbar.

---

## REIHENFOLGE FÜR CODEX

Empfohlene Abarbeitungsreihenfolge nach Prio und Abhängigkeit:

```
1. TASK 1  (BE-2 Whitelist)          ← sofort, unabhängig, kritisch
2. TASK 2  (IST-Divergenz)           ← sofort, Frontend-only
3. TASK 3  (Tilt Floor-Checks)       ← Backend-only, Tests danach
4. TASK 4  (SR-Page Log-Filter)      ← Frontend, 2 Stellen
5. TASK 5  (CORS)                    ← config.py, 1 Zeile
6. TASK 6  (CMA IST-Projektion)      ← Frontend, abhängig von strategyState
7. TASK 7  (MC Goals Panel)          ← Frontend, neues UI-Element
8. TASK 8  (Admin CMA UI)            ← Frontend, Daten-Ergänzung
```

**Nach jedem Task:**
```bash
cd C:\5eyes\5eyes_stage9_release_ready\5eyes-backend
python -m pytest tests/ -v
git add <exakte Dateipfade>
git commit -m "<type>: <beschreibung>"
```

---

## WAS NICHT IN DIESEM DOKUMENT STEHT

Diese Tasks kommen aus der Code-Analyse. Folgende Punkte sind bewusst **nicht** drin, weil sie entweder Fachentscheide erfordern oder ausserhalb des Codex-Scope liegen:

- **Drift-Schwellenwerte** für Review-Trigger: Fachentscheid Owner
- **Kapitalmarktannahmen-Update**: Jährlicher manueller Prozess Portfolio Management
- **Produktliste Best-in-Class**: Manueller Update-Prozess
- **Kandidatenportfolios V1**: Architekturentscheid noch offen (Musterportfolios vs. Sampling)

---
*Erstellt: Claude Analyse-Session 2026-04-10*
