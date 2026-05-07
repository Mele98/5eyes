# Spec: Goal-Architektur PK-/Swiss Life-aligned

## Meta

- **Titel:** Institutionelle Goal-Architektur — Verpflichtungspriorität, real/nominal, Härtegrad-Gewichtung
- **Datum:** 2026-04-17
- **Owner:** Emanuele Konzelmann
- **Branch-Vorschlag:** `feature/goal-architecture-pk-aligned`

---

## Ziel

5eyes soll die Zielarchitektur so darstellen und verarbeiten wie Swiss Life / 3eyes und institutionelle
Pensionskassen es tun: **Verpflichtungen und Kapitalerhalt kommen vor Rendite**.
Das Renditeziel ist ein weiches, opportunistisches Ziel — kein Hauptanker der Strategie.
Drei konkrete Bugs werden in dieser Spec behoben, plus eine klare Hierarchie im Scoring und in der
Portfolio-Engine verankert.

---

## Problem

### Bug 1 — value_mode ist hardcoded «nominal» im Frontend

**Datei:** `5eyes-electron/frontend/5eyes_v2.html`
**Zeile:** 14776
```js
value_mode:'nominal',   // <-- niemals vom User wählbar
```
Das Backend-Schema (`GoalCreate`) unterstützt bereits `value_mode: "real"`, aber der Wert wird
nie gesetzt. Realer Kapitalerhalt ist daher mehr Versprechen als echte Logik.

### Bug 2 — Kapitalerhalt real inflationiert das Ziel nicht

**Datei:** `5eyes-backend/services/portfolio_engine.py`
**Zeile ~1785:**
```python
elif goal_type in ("Kapitalerhalt", "Vermoegensziel"):
    target = max(1, int(goal.target_wealth_rappen or 0))
```
Wenn `value_mode == "real"`, muss `target` mit dem kumulierten Inflationspfad hochgerechnet werden.
Aktuell wird `value_mode` im Scoring vollständig ignoriert.

### Bug 3 — Renditeziel hat Default-Härtegrad «Primär»

**Datei:** `5eyes-electron/frontend/5eyes_v2.html`
**Zeile ~14760:**
```js
var hardnessMap = {'1':'Hart','2':'Primär','3':'Opportunistisch'};
```
Das Ziel-Formular setzt `rank=2 → Primär` als Default für alle Ziele inkl. Renditeziel.
Fachlich ist Renditeziel immer Opportunistisch — nie Hart, selten Primär.

### Systemisches Problem — Härtegradgewichtung fehlt in Portfolio-Konstruktion

**Datei:** `5eyes-backend/services/portfolio_engine.py`
**Zeile 2799:**
```python
growth_goals = [goal for goal in goals if _norm_text(goal.goal_type) in
    ("Vermoegensziel", "Maximierung", "Renditeziel")]
```
`Renditeziel` beeinflusst hier die Aktienquoten-Erhöhung gleichgestellt mit `Vermögensziel` und
`Maximierung`. Das widerspricht der Swiss Life / PK-Logik: Renditeziel ist weich; Kapitalerhalt
ist hart. Die Portfolio-Konstruktion muss die Härtegrade respektieren.

---

## Scope

- value_mode-Toggle (nominal / real) im Ziel-Formular für Kapitalerhalt und Vermögensziel
- Reale Zielinflationierung in der Monte Carlo Scoring-Funktion
- Default-Härtegrad für Renditeziel = Opportunistisch
- Renditeziel aus `growth_goals` entfernen (oder nur bei Opportunistisch-Renditeziel beibehalten
  wenn kein Hart-Ziel existiert)
- Goal-Liste im Frontend: Härtegradfarben und Zielklasse sichtbar machen

## Nicht-Scope

- ALM / Duration Matching (PK-Buchhaltung)
- Deckungsgrad / technischer Zinssatz / Umwandlungssatz
- Neue Ziel-Typen
- Änderungen am DB-Schema (value_mode und hardness existieren bereits)
- Änderungen an goal_family, goal_scope oder den Cashflow-Zielen

---

## Fachlogik

**Quelle:** Swiss Life / 3eyes SLAM-Methodologie, PK-ALM-Praxis, IPS-Standard

### Verbindliche Hierarchie

```
STUFE 1 — Hart (Pflicht)
  Cashflow-Ziele (Wiederkehrende_Ausgabe, Pensionsausgabe)
  Kapitalerhalt (nominal oder real)

STUFE 2 — Primär (Wichtig)
  Einmalige_Ausgabe
  Vermögensziel

STUFE 3 — Opportunistisch (Weich)
  Renditeziel          ← darf nie Strategy dominieren
  Maximierung
```

### Regeln

1. **Renditeziel ist immer Opportunistisch.** Es darf eine Strategie plausibilisieren, aber
   nicht allein bestimmen. Default-Härtegrad im Formular: `Opportunistisch`.

2. **Kapitalerhalt real** bedeutet: Das Zielkapital wächst jährlich mit der
   `inflation_assumption_bps` aus den `PlanningAssumption` (oder fallback auf CMA-Inflation).
   Formel: `target_real = target_nominal × (1 + infl)^years`

3. **Portfolio-Konstruktion**: `growth_goals` (die zu höherem Aktienanteil führen) sollen
   nur `Hart`- und `Primär`-Wachstumsziele enthalten. `Opportunistisch`-Ziele (inkl. Renditeziel)
   dürfen die Aktienquote nicht erhöhen.

4. **Scoring-Gewicht**: Ein Hart-Ziel mit Score 40 wiegt schwerer als ein Opportunistisch-Ziel
   mit Score 90. Das Gesamt-Score soll dies widerspiegeln:
   ```
   gewichteter Score = Σ (goal_score × hardness_multiplier × weight_bps)
                       ─────────────────────────────────────────────────
                             Σ (hardness_multiplier × weight_bps)
   ```
   Multiplikatoren: Hart=2.0, Primär=1.0, Opportunistisch=0.4

### Owner-Decisions

- **OD-1:** Soll ein Renditeziel mit Härtegrad «Hart» weiterhin erlaubt sein (Spezialfall)?
  → *Default: Nein. Validierung blockiert Hart+Renditeziel oder zeigt Warnung.*
- **OD-2:** Welcher Inflationswert für reale Ziele — PlanningAssumption oder CMA-Inflation?
  → *Default: PlanningAssumption.inflation_assumption_bps; Fallback: 150 BPS (1.5%).*

---

## Betroffene Module / Dateien

### Backend

- **`services/portfolio_engine.py`**
  - `_score_goal_monte_carlo()` (Zeile ~1746): real-Inflationierung für Kapitalerhalt/Vermögensziel
  - `growth_goals` (Zeile 2799): Renditeziel entfernen oder Härtegrad-Filter
  - `_goal_weight()` (Zeile 1482): Härtegrad-Multiplikator einbauen
  - Gesamt-Score Aggregation: gewichtetes Scoring nach Härtegrad

- **`schemas/wealth.py`**
  - `GoalCreate.hardness`: Default für Renditeziel auf `"Opportunistisch"` dokumentieren
    (Schema-Default bleibt `"Primär"`, Frontend muss es setzen)

### Frontend

- **`5eyes-electron/frontend/5eyes_v2.html`**
  - Ziel-Formular (`m-nz`): value_mode-Toggle hinzufügen
  - `saveGoal()` / Payload (Zeile ~14776): `value_mode` aus Formular lesen
  - Renditeziel: Priority-Select Default auf `3` (Opportunistisch) setzen
  - Ziel-Liste: Härtegrad-Badge und Klassen-Label anzeigen

---

## Implementierungs-Checkliste (nummeriert, in Reihenfolge)

### Backend

**Schritt 1 — `portfolio_engine.py`: Real-Inflationierung in `_score_goal_monte_carlo()`**

Grep-Ankerpunkt:
```
elif goal_type in ("Kapitalerhalt", "Vermoegensziel"):
    target = max(1, int(goal.target_wealth_rappen or 0))
```

Ersetzen durch:
```python
elif goal_type in ("Kapitalerhalt", "Vermoegensziel"):
    _target_nominal = max(1, int(goal.target_wealth_rappen or 0))
    if getattr(goal, "value_mode", "nominal") == "real":
        _infl_bps = int(policy.inflation_assumption_bps or 150)
        _years = index  # Monte Carlo Jahre bis zum Ziel
        _target_nominal = int(round(_target_nominal * ((1 + _infl_bps / 10000) ** _years)))
    target = _target_nominal
```

**Schritt 2 — `portfolio_engine.py`: `_goal_weight()` mit Härtegrad-Multiplikator**

Grep-Ankerpunkt:
```python
def _goal_weight(goal: Goal) -> int:
    if goal.weight_bps:
        return int(goal.weight_bps)
    return GOAL_WEIGHT_BY_RANK.get(int(goal.rank or 5), 312)
```

Ersetzen durch:
```python
_HARDNESS_MULTIPLIER = {"Hart": 20000, "Primär": 10000, "Opportunistisch": 4000}

def _goal_weight(goal: Goal) -> int:
    base = int(goal.weight_bps) if goal.weight_bps else GOAL_WEIGHT_BY_RANK.get(int(goal.rank or 5), 312)
    hardness = str(goal.hardness or "Primär")
    mult = _HARDNESS_MULTIPLIER.get(hardness, 10000)
    return int(round(base * mult / 10000))
```

**Schritt 3 — `portfolio_engine.py`: `growth_goals` — Renditeziel entfernen**

Grep-Ankerpunkt:
```python
growth_goals = [goal for goal in goals if _norm_text(goal.goal_type) in ("Vermoegensziel", "Maximierung", "Renditeziel")]
```

Ersetzen durch:
```python
growth_goals = [
    goal for goal in goals
    if _norm_text(goal.goal_type) in ("Vermoegensziel", "Maximierung")
    or (
        _norm_text(goal.goal_type) == "Renditeziel"
        and str(goal.hardness or "Primär") != "Opportunistisch"
        and not any(
            _norm_text(g.goal_type) in ("Kapitalerhalt", "Vermoegensziel", "Pensionsausgabe", "Wiederkehrende_Ausgabe")
            and str(g.hardness or "Primär") == "Hart"
            for g in goals
        )
    )
]
```

### Frontend

**Schritt 4 — Ziel-Formular: value_mode-Toggle**

Grep-Ankerpunkt (Ort: im Formular `m-nz`, unmittelbar nach dem Scope-Select):
```
id="nz-scope"
```

Nach dem div/row des Scope-Selects einfügen:
```html
<div id="nz-value-mode-row" style="display:none">
  <label style="font-size:9px;color:var(--n4);display:block;margin-bottom:4px">Wertbasis</label>
  <div style="display:flex;gap:8px;">
    <label style="display:flex;align-items:center;gap:5px;font-size:11px;color:var(--n5);cursor:pointer">
      <input type="radio" name="nz-value-mode" id="nz-vm-nominal" value="nominal" checked> Nominal
    </label>
    <label style="display:flex;align-items:center;gap:5px;font-size:11px;color:var(--n5);cursor:pointer">
      <input type="radio" name="nz-value-mode" id="nz-vm-real" value="real"> Real (inflationsbereinigt)
    </label>
  </div>
  <div style="font-size:9px;color:var(--n4);margin-top:3px;line-height:1.4">
    Real: Das Zielkapital wird jährlich mit der Inflationsannahme aufgewertet.
  </div>
</div>
```

**Schritt 5 — value_mode-Toggle: Sichtbarkeit steuern**

In der Funktion `onChangeGoalType(type)` (oder wo `nz-type` geändert wird) einfügen:
```js
var vmRow = document.getElementById('nz-value-mode-row');
if (vmRow) vmRow.style.display = (type === 'Kapitalerhalt' || type === 'Vermögensziel') ? 'block' : 'none';
```
Ausserdem beim Hydrate (beim Bearbeiten eines bestehenden Ziels) den Radio-Button korrekt setzen:
```js
var vm = goal.value_mode || 'nominal';
var vmEl = document.getElementById('nz-vm-' + vm);
if (vmEl) vmEl.checked = true;
```

**Schritt 6 — Payload: value_mode aus Formular lesen**

Grep-Ankerpunkt:
```js
value_mode:'nominal',
```

Ersetzen durch:
```js
value_mode:(document.querySelector('input[name="nz-value-mode"]:checked')||{value:'nominal'}).value,
```

**Schritt 7 — Default Renditeziel → Opportunistisch**

Grep-Ankerpunkt (im onchange des Typ-Selects oder in der Reset-Funktion des Ziel-Formulars):
```js
var hardnessMap={'1':'Hart','2':'Primär','3':'Opportunistisch'};
```

Direkt nach diesem Statement oder beim Typ-Wechsel:
```js
if (type === 'Renditeziel') {
  setSelectValue('nz-prio', '3');  // Opportunistisch
}
```
Suche auch nach der Stelle wo `nz-prio` auf einen Default gesetzt wird und stelle sicher, dass
für neue Ziele vom Typ `Renditeziel` initial `3` (Opportunistisch) selektiert ist.

**Schritt 8 — Ziel-Liste: Härtegrad-Badge**

Grep-Ankerpunkt (in der Render-Funktion der Ziel-Liste, dort wo `goal.hardness` verwendet wird):
```js
'<div class="pd '+(pc[goal.hardness]||'p2')+'">'+(index+1)+'</div>'
```

Nach dem Rang-Badge das Härtegrad-Label ergänzen:
```js
var hardnessBadge = {
  'Hart':           '<span style="background:#e8f5e9;color:#1b5e20;font-size:9px;padding:1px 5px;border-radius:3px;font-weight:700">HART</span>',
  'Primär':         '<span style="background:#fff8e1;color:#f57f17;font-size:9px;padding:1px 5px;border-radius:3px;font-weight:700">PRIMÄR</span>',
  'Opportunistisch':'<span style="background:var(--bg2);color:var(--n5);font-size:9px;padding:1px 5px;border-radius:3px;font-weight:600">OPP.</span>'
};
// In die Ziel-Zeile einfügen: (hardnessBadge[goal.hardness]||'')
```

---

## API / Schnittstellen

Keine neuen Endpoints. `GoalCreate` und `GoalUpdate` unterstützen `value_mode` und `hardness`
bereits korrekt. Nur die Frontend-Logik und die Portfolio-Engine ändern sich.

---

## UI / UX

- value_mode-Toggle erscheint **nur** bei Kapitalerhalt und Vermögensziel, bei allen anderen Typen
  bleibt er verborgen
- Beim Laden eines bestehenden Ziels wird `value_mode` korrekt vorbelegt
- Renditeziel öffnet das Formular mit vorselektiertem Opportunistisch
- In der Ziel-Liste: Härtegrad-Farbcode (Hart=grün, Primär=gelb, Opportunistisch=grau)
- Keine modalen Warnungen — rein visuelle Klarheit

---

## Akzeptanzkriterien

1. Kapitalerhalt mit `value_mode=real` → Score-Berechnung inflationiert das Zielkapital korrekt
   (Test: 1.5% Inflation, 10 Jahre, CHF 500k Ziel → scoring target ≈ CHF 580k)
2. Neues Renditeziel → Formular öffnet mit Opportunistisch vorselektiert
3. Renditeziel (Opportunistisch) erhöht Aktienquote **nicht**, wenn ein Hart-Kapitalerhalt-Ziel
   existiert — `growth_goals` enthält es dann nicht
4. `_goal_weight()` gibt für Hart-Ziele 2× höhere Gewichte als für Primär-Ziele zurück
5. Frontend sendet `value_mode:'real'` wenn Real-Radio geklickt wurde (Network-Tab)

---

## Testfälle

- **Unit (backend):** `_score_goal_monte_carlo` mit `value_mode=real`, `inflation_assumption_bps=150`,
  `years=10` → target inflationiert
- **Unit (backend):** `_goal_weight(hart_goal)` = 2× `_goal_weight(primaer_goal)` bei identischem rank
- **Unit (backend):** `growth_goals` enthält Renditeziel nicht, wenn Hart-Kapitalerhalt vorhanden
- **Frontend:** Ziel-Formular mit Typ Kapitalerhalt → value_mode-Row sichtbar
- **Frontend:** Ziel-Formular mit Typ Renditeziel → Scope Opportunistisch vorselektiert,
  value_mode-Row versteckt
- **Edge Case:** `inflation_assumption_bps = None` → Fallback 150 BPS (keine Exception)
- **Edge Case:** `value_mode = None` oder fehlt → wie `'nominal'` behandeln

---

## Risiken

- `inflation_assumption_bps` sitzt in `OptimizerPolicy`, nicht in `Goal` — sicherstellen, dass
  `_score_goal_monte_carlo` Zugriff auf `policy` hat (aktuell: ja, `policy` wird übergeben)
- `_HARDNESS_MULTIPLIER` als Modul-Konstante verringert Konfigurierbarkeit — akzeptabel für V1
- Bestehende Ziele haben `value_mode=nominal` in der DB — kein Migration nötig, Verhalten bleibt

---

## Offene Fragen an Owner (OD)

- **OD-1:** Soll `Hart + Renditeziel` im Frontend blockiert oder nur gewarnt werden?
  (Empfehlung: Warnung, kein harter Block — Advisor soll override können)
- **OD-2:** Inflationsquelle für real-Ziele: `PlanningAssumption.inflation_assumption_bps` oder
  CMA-Wert aus `CapitalMarketAssumptions`?
  (Empfehlung: `PlanningAssumption` wenn vorhanden, sonst `policy.inflation_assumption_bps`,
   sonst hardcoded 150 BPS)
