# Spec: Goal-Architektur PK-aligned — Echte Lücken

## Meta

- **Titel:** PK-aligned Goal-Architektur — Renditeziel-Warnung + Inflationsannahme-UI
- **Datum:** 2026-04-18
- **Owner:** Emanuele Konzelmann
- **Branch-Vorschlag:** `feature/goal-pk-gaps`

---

## Hinweis: Was BEREITS implementiert ist (nicht anfassen)

Vor der Implementierung unbedingt lesen — folgender Code ist korrekt und darf NICHT geändert werden:

| Feature | Datei | Zeile |
|---|---|---|
| `value_mode` real/nominal Backend | `portfolio_engine.py` | 1527–1531 |
| Inflations-Aufwertung real-Ziele | `portfolio_engine.py` | 1516–1531 |
| Härtegrad-Multiplikator Scoring | `portfolio_engine.py` | 1482–1501 |
| `_growth_goals_for_equity_tilt()` | `portfolio_engine.py` | 1534–1556, 2898 |
| `nz-value-mode-row` Toggle HTML | `5eyes_v2.html` | 1758–1773 |
| `syncGoalModalState()` zeigt Toggle | `5eyes_v2.html` | 14649–14650 |
| Renditeziel → Opportunistisch default | `5eyes_v2.html` | 14676 |
| `saveGoal()` liest value_mode aus Radio | `5eyes_v2.html` | 14843 |
| HART/PRIMÄR/OPP./REAL Badges | `5eyes_v2.html` | 14555–14572 |

---

## Ziel

Zwei echte Lücken schliessen:
1. Warnung wenn Berater einem Renditeziel den Härtegrad "Hart" gibt — das widerspricht der
   Swiss Life / PK-Logik (Renditeziel ist immer weich/opportunistisch).
2. Inflationsannahme für reale Vermögensziele im UI editierbar machen. Aktuell liest das Backend
   `PlanningAssumption.inflation_assumption_bps` korrekt, aber kein UI existiert zum Setzen.

---

## Problem

### Lücke 1 — Kein Schutz gegen Renditeziel + Hart

**Datei:** `5eyes-electron/frontend/5eyes_v2.html`
**Funktion:** `syncGoalModalState()` (Zeile ~14628)

Aktuell: `syncGoalModalState()` setzt bei neuem Renditeziel prio=3 (Opportunistisch) als Default.
Aber wenn der Berater danach manuell auf "Hart" (prio=1) wechselt: keine Warnung, kein Feedback.

Fachlich ist Hart+Renditeziel ein Widerspruch:
- Hart bedeutet: muss zwingend erfüllt werden, dominiert Portfoliokonstruktion
- Renditeziel ist inhärent unsicher, kann nicht garantiert werden
- In PK-/Swiss Life-Logik existiert diese Kombination nicht

### Lücke 2 — Inflationsannahme nicht editierbar

**Dateien:**
- Backend liest aus: `services/portfolio_engine.py` Funktion `_current_planning_inflation_bps()` (Zeile 2672)
- Wird gespeichert in: `models/wealth.py` → `PlanningAssumption.inflation_assumption_bps` (Integer, BPS)
- Aktuell keine UI zum Setzen

Konsequenz: `value_mode=real` für Kapitalerhalt-Ziele inflationiert mit dem CMA-Pfad-Fallback
(statt der mandatspezifischen Annahme des Beraters). Das ist fachlich ungenau — der Berater
muss die Inflationsannahme pro Mandat korrekt einstellen können.

---

## Scope

- **Lücke 1:** Inline-Warnung in `syncGoalModalState()` wenn Renditeziel + Hart kombiniert
- **Lücke 2:** Inflationsannahme-Feld im Mandatsbereich (Planungsannahmen) editierbar und speicherbar

## Nicht-Scope

- Keine Backend-Änderungen für Lücke 1 (rein Frontend-Warnung)
- Kein Modal-Redesign
- Keine Änderungen an bestehenden Scoring-Algorithmen
- Kein Block (nur Warnung) — Berater kann Hart+Renditeziel setzen wenn er es wirklich will

---

## Fachlogik

**Lücke 1:**
- Renditeziel darf niemals auf Hart gesetzt werden
- PK-Logik: Rendite ist Mittel zum Zweck, kein Versprechen
- Warnung (nicht Block): Berater behält Override-Recht, muss aber bewusst entscheiden

**Lücke 2:**
- `PlanningAssumption.inflation_assumption_bps`: BPS-Wert, z.B. 150 = 1.50% p.a.
- Wenn gesetzt: wird für alle real-Ziele dieses Mandats als Inflationspfad verwendet
- Fallback (wenn null): CMA-Inflationspfad aus `CapitalMarketAssumptions`
- Typischer Wert für Schweiz: 100–200 BPS (1.0–2.0%)
- Für Ruhestandsgelder immer den konservativeren (höheren) Wert wählen

### Owner-Decisions

- **OD-1:** Wo soll das Inflationsfeld erscheinen?
  → Empfehlung: Im bestehenden "Planungsannahmen"-Bereich des Mandats (falls vorhanden),
  sonst als eigene Card in der Strategieseite (page-al) neben dem Risikoprofil.
- **OD-2:** Soll die Warnung (Lücke 1) den Save-Button blockieren?
  → Empfehlung: NEIN — nur eine sichtbare orangefarbene Warnung, Speichern bleibt möglich.

---

## Betroffene Dateien

### Lücke 1 (Frontend only)

- **`5eyes-electron/frontend/5eyes_v2.html`**
  - `syncGoalModalState()` — Warnung-Div einblenden wenn Renditeziel+Hart
  - HTML: neues `nz-hardness-warn` Div im Ziel-Formular

### Lücke 2 (Frontend + Backend)

- **`5eyes-electron/frontend/5eyes_v2.html`**
  - Neues Input-Feld `plan-inflation-bps` (float → BPS) + Speichern-Button
  - Ladelogik beim Öffnen des Mandats

- **`5eyes-backend/routers/wealth.py`** (oder eigener Planning-Router)
  - `GET /mandates/{mandate_id}/planning-assumptions` — aktuelle Annahmen lesen
  - `PUT /mandates/{mandate_id}/planning-assumptions` — `inflation_assumption_bps` speichern

- **`5eyes-backend/models/wealth.py`** — `PlanningAssumption` bereits vorhanden, kein Schemachange
- **`5eyes-backend/schemas/wealth.py`** — Schema für PUT prüfen/ergänzen

---

## Implementierungs-Checkliste (Reihenfolge einhalten)

### LÜCKE 1 — Renditeziel + Hart Warnung

**Schritt 1 — Warn-Div im Ziel-Formular HTML einfügen**

Grep-Anker (unmittelbar nach dem Priority-Select `id="nz-prio"`):
```
<select class="fsel" id="nz-prio">
```

Nach dem schliessenden `</select>` des Priority-Selects einfügen:
```html
<div id="nz-hardness-warn" style="display:none;margin-top:6px;padding:6px 10px;background:rgba(234,88,12,0.09);border:1px solid rgba(234,88,12,0.25);border-radius:var(--r);font-size:10px;color:#c2410c;line-height:1.5">
  Renditeziele sollten nie als <strong>Hart</strong> klassifiziert werden. Renditeziele sind
  opportunistisch — sie können nicht garantiert werden. Bitte auf <strong>Primär</strong>
  oder <strong>Opportunistisch</strong> ändern.
</div>
```

**Schritt 2 — Warnung in `syncGoalModalState()` steuern**

Grep-Anker:
```
var valueModeRow=document.getElementById('nz-value-mode-row');
```

Nach dieser Zeile einfügen:
```js
var hardnessWarn = document.getElementById('nz-hardness-warn');
```

Und am Ende der Funktion, vor der letzten `}` von `syncGoalModalState`, einfügen:
```js
if (hardnessWarn) {
  var isRendite = isReturnGoalType(type);
  var isHart = getInputValue('nz-prio') === '1';
  hardnessWarn.style.display = (isRendite && isHart) ? 'block' : 'none';
}
```

**Schritt 3 — Warnung auch beim Wechsel der Priorität triggern**

Grep-Anker:
```
<select class="fsel" id="nz-prio">
```

Attribut `onchange` hinzufügen:
```html
<select class="fsel" id="nz-prio" onchange="syncGoalModalState()">
```

(Falls `onchange` bereits vorhanden: überspringen)

---

### LÜCKE 2 — Inflationsannahme editierbar

**Schritt 4 — Backend: Schema prüfen / GET + PUT Endpunkte**

Datei: `5eyes-backend/routers/wealth.py`

Grep-Anker (bestehende Planungsannahmen-Endpunkte suchen):
```
planning-assumption
```

Falls `GET /mandates/{mandate_id}/planning-assumptions` bereits existiert: prüfen ob er
`inflation_assumption_bps` zurückgibt. Falls nicht, Response-Schema anpassen.

Falls kein GET existiert: neuen Endpunkt hinzufügen:
```python
@router.get("/{mandate_id}/planning-assumptions")
def get_planning_assumptions(
    mandate_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    assumption = (
        db.query(PlanningAssumption)
        .filter(PlanningAssumption.mandate_id == mandate_id,
                PlanningAssumption.is_current == 1)
        .order_by(PlanningAssumption.version.desc())
        .first()
    )
    if not assumption:
        return {"inflation_assumption_bps": None}
    return {
        "id": assumption.id,
        "inflation_assumption_bps": assumption.inflation_assumption_bps,
        "retirement_age_primary": assumption.retirement_age_primary,
        "retirement_age_partner": assumption.retirement_age_partner,
        "life_expectancy_primary": assumption.life_expectancy_primary,
        "life_expectancy_partner": assumption.life_expectancy_partner,
        "notes": assumption.notes,
    }
```

Falls `PUT /mandates/{mandate_id}/planning-assumptions` nicht existiert:
```python
from datetime import datetime
from uuid import uuid4

@router.put("/{mandate_id}/planning-assumptions")
def upsert_planning_assumptions(
    mandate_id: str,
    body: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    now = datetime.utcnow().isoformat()
    existing = (
        db.query(PlanningAssumption)
        .filter(PlanningAssumption.mandate_id == mandate_id,
                PlanningAssumption.is_current == 1)
        .order_by(PlanningAssumption.version.desc())
        .first()
    )
    inflation = body.get("inflation_assumption_bps")
    if inflation is not None:
        inflation = int(inflation)
    if existing:
        if inflation is not None:
            existing.inflation_assumption_bps = inflation
        if "retirement_age_primary" in body:
            existing.retirement_age_primary = body["retirement_age_primary"]
        if "notes" in body:
            existing.notes = body.get("notes")
        existing.updated_at = now
    else:
        db.add(PlanningAssumption(
            id=str(uuid4()),
            mandate_id=mandate_id,
            client_id=body.get("client_id", ""),
            version=1,
            is_current=1,
            valid_from=now[:10],
            inflation_assumption_bps=inflation,
            created_at=now,
            updated_at=now,
        ))
    db.commit()
    return {"ok": True, "inflation_assumption_bps": inflation}
```

**Schritt 5 — Frontend: Inflationsannahme-Card im Strategiebereich**

Grep-Anker (in page-al, nach dem Risikoprofil-Card oder dem Snapshot-Bereich):
```
id="al-risk-profile"
```
(Fallback-Anker falls obiger nicht existiert: `id="page-al"`)

Nach dem Risikoprofil-Card einfügen:
```html
<div id="al-planning-card" style="background:var(--bg);border:1px solid var(--b1);border-radius:var(--r);padding:14px;margin-top:12px;display:grid;gap:10px;">
  <div style="font-size:11px;font-weight:600;color:var(--g3);">Planungsannahmen</div>
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;align-items:end;">
    <div>
      <label style="font-size:9px;color:var(--n4);display:block;margin-bottom:2px">Inflationsannahme p.a. (%)</label>
      <input class="fi" id="plan-inflation-pct" type="number" step="0.1" min="0" max="10"
        placeholder="1.5" style="font-size:11px">
      <div style="font-size:9px;color:var(--n4);margin-top:3px;line-height:1.4">
        Wird für real-Vermögensziele dieses Mandats verwendet. Konservativ: 1.5–2.0%.
      </div>
    </div>
    <div>
      <button class="btn-p" style="width:100%;background:var(--bg2);color:var(--n6)"
        onclick="savePlanningAssumptions()" id="btn-plan-save">Speichern</button>
    </div>
  </div>
  <div id="plan-feedback" style="display:none;font-size:10px"></div>
</div>
```

**Schritt 6 — Frontend: `loadPlanningAssumptions()` und `savePlanningAssumptions()`**

Diese Funktionen als neuen JS-Block einfügen (Grep-Anker: nach `async function openAdminModal`
oder in den Block der Strategie-Ladefunktionen, wo `applyAllocationEngineResult` oder
`loadAllocation` steht):

```js
async function loadPlanningAssumptions() {
  var mid = getActiveMandateId();
  if (!mid || isDemoMandateId(mid)) return;
  try {
    var data = await API.get('/mandates/' + mid + '/planning-assumptions');
    var bps = data && data.inflation_assumption_bps;
    var pctEl = document.getElementById('plan-inflation-pct');
    if (pctEl) pctEl.value = bps != null ? (bps / 100).toFixed(2) : '';
  } catch(e) {}
}

async function savePlanningAssumptions() {
  var mid = getActiveMandateId();
  if (!mid || isDemoMandateId(mid)) return;
  var btn = document.getElementById('btn-plan-save');
  var fbEl = document.getElementById('plan-feedback');
  var pctVal = parseFloat((document.getElementById('plan-inflation-pct')||{}).value || '');
  if (isNaN(pctVal) || pctVal < 0 || pctVal > 10) {
    if (fbEl) { fbEl.textContent = 'Bitte gültigen Wert eingeben (0–10%).'; fbEl.style.color = 'var(--neg)'; fbEl.style.display = 'block'; }
    return;
  }
  var bps = Math.round(pctVal * 100);
  if (btn) { btn.disabled = true; btn.textContent = 'Speichert…'; }
  try {
    await API.put('/mandates/' + mid + '/planning-assumptions', { inflation_assumption_bps: bps });
    if (fbEl) { fbEl.textContent = '✓ Inflationsannahme gespeichert (' + pctVal.toFixed(2) + '% = ' + bps + ' BPS).'; fbEl.style.color = 'var(--pos)'; fbEl.style.display = 'block'; setTimeout(function(){ if(fbEl)fbEl.style.display='none'; }, 3000); }
  } catch(e) {
    if (fbEl) { fbEl.textContent = 'Fehler: ' + (e.message || e); fbEl.style.color = 'var(--neg)'; fbEl.style.display = 'block'; }
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = 'Speichern'; }
  }
}
```

**Schritt 7 — `loadPlanningAssumptions()` beim Mandatwechsel aufrufen**

Grep-Anker (in der Funktion die beim Mandatwechsel aufgerufen wird — suche nach
`loadAllocation` oder `applyAllocationEngineResult` oder `refreshGoalsUI`):
```
await refreshGoalsUI(mid)
```

Nach dieser Zeile einfügen:
```js
loadPlanningAssumptions();
```

---

## API / Schnittstellen

| Methode | Pfad | Beschreibung |
|---|---|---|
| GET | `/mandates/{mandate_id}/planning-assumptions` | Planungsannahmen laden |
| PUT | `/mandates/{mandate_id}/planning-assumptions` | Inflationsannahme speichern |

Request (PUT):
```json
{ "inflation_assumption_bps": 150 }
```

Response:
```json
{ "ok": true, "inflation_assumption_bps": 150 }
```

---

## Akzeptanzkriterien

1. Wenn Typ = Renditeziel und Priorität = Hart → oranges Warn-Div sichtbar, Speichern bleibt möglich
2. Wenn Priorität ändert (Hart → Primär) → Warn-Div sofort verschwindet (ohne Seite neu laden)
3. Inflationsfeld zeigt aktuellen Wert beim Öffnen des Mandats (z.B. "1.50")
4. Speichern schreibt `inflation_assumption_bps` in DB → Backend verwendet diesen Wert danach
   für alle real-Ziele des Mandats in `_current_planning_inflation_bps()`
5. Feld leer = Fallback auf CMA-Inflationspfad (kein Fehler)

---

## Testfälle

- Neues Renditeziel, Priorität auf Hart setzen → Warnung erscheint
- Priorität zurück auf Opportunistisch → Warnung verschwindet
- Anderer Zieltyp + Hart → keine Warnung
- Inflationsfeld: Wert "1.5" eingeben, speichern → DB-Wert = 150 BPS
- Inflationsfeld: leer lassen, speichern → validiert, kein Crash
- Wert > 10% → Fehlermeldung (unplausibel)
- Demo-Modus: Speichern deaktiviert (isDemoMandateId-Check)

---

## Risiken

- `PlanningAssumption.client_id` ist `NOT NULL` im Model — beim Erstellen einer neuen
  Assumption muss `client_id` aus dem Mandat geholt werden. Endpoint muss das korrekt handhaben.
- `nz-prio` hat möglicherweise kein `onchange` → Schritt 3 explizit prüfen ob Attribut schon da
