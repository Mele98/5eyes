# Spec — Scoring-Parameter-Editor im Admin-Modal

## Meta
- Titel: Scoring-Parameter-Editor — RisikoMatrix & Bands editierbar via Admin-UI
- Datum: 2026-04-17
- Owner: Emanuele
- Branch-Vorschlag: `codex/scoring-parameter-editor`

---

## Warum diese Spec existiert — Fachlicher Kontext

`RISK_CAPACITY_BANDS` und `RISK_CAPACITY_MATRIX` sind heute **hardcoded** in
`5eyes_v2.html`. Das bedeutet: Wenn Emanuele die Scoring-Parameter anpassen will
(z.B. weil ein Compliance-Review neue Bandbreiten fordert, oder weil Advisory-Methodik
die Horizont-Matrix aktualisiert), muss er den JS-Code direkt editieren.

**Ziel:** Diese zwei Kernparameter werden in der DB gespeichert und sind über das
Admin-Modal editierbar — mit einer visuellen Grid-Darstellung der Matrix
(Horizont-Zeilen × Risikofähigkeits-Bänder-Spalten).

**Warum jetzt:**
- Die Matrix ist das Herzstück der Risikoprofil-Logik
- FIDLEG-Compliance erfordert, dass Parameteränderungen auditiert werden
- Emanuele muss Parameter anpassen können ohne Code-Deployment

**Was NICHT verändert:** Die Berechnungs-Logik (`computeRiskProfile`,
`findRiskCapacityBand`, `RISK_CAPACITY_MATRIX`-Lookup) bleibt identisch.
Nur die Quelle der Werte ändert sich: DB → JS-Konstanten statt hardcoded.

---

## Scope

1. **Backend**: Neue `system_params`-Tabelle (key-value) + 2 Endpoints
2. **Frontend**: Neue Admin-Sektion "Scoring-Parameter" in `m-admin`
3. **Frontend**: JS-Funktion `loadScoringParams()` die beim App-Start die
   JS-Konstanten aus DB überschreibt
4. **Kein Audit-Log-Eintrag** für Parameter-Änderungen (Phase 2)

### Was NICHT ändert
- `computeRiskProfile`-Logik
- `findRiskCapacityBand`-Logik
- Alle anderen Scoring-Konstanten (`RISK_INCOME_POINTS`, etc.)
- CMA-Modul
- Alle anderen Admin-Funktionen

---

## Betroffene Dateien

| Datei | Art |
|---|---|
| `5eyes-backend/models/review.py` | ÄNDERN — SystemParam-Modell hinzufügen |
| `5eyes-backend/routers/system.py` | ÄNDERN — 2 neue Endpoints |
| `5eyes-electron/frontend/5eyes_v2.html` | ÄNDERN — Admin-Sektion + JS |

---

## DB-Schema

### Neue Tabelle `system_params`

```sql
CREATE TABLE IF NOT EXISTS system_params (
    key   TEXT PRIMARY KEY NOT NULL,
    value TEXT NOT NULL,
    updated_at TEXT,
    updated_by TEXT
);
```

**Keys die 5eyes nutzt:**

| Key | Inhalt | Beispiel |
|---|---|---|
| `scoring_matrix` | JSON-Objekt: `{"1,1":0,"1,2":0,...,"15,5":100}` | RISK_CAPACITY_MATRIX |
| `risk_capacity_bands` | JSON-Array: `[{"min":0,"max":2,"label":"Risikoarm","band":1},...]` | RISK_CAPACITY_BANDS |
| `fzk_cap` | Integer als String: `"75"` | FZK-Cap Aktienanteil % |
| `allow_single_titles` | `"false"` oder `"true"` | Phase 2 Einzeltitel |

---

## Backend — Schritt B1: SystemParam-Modell

### Datei: `5eyes-backend/models/review.py`

### Grep (Datei-Ende finden):
```
grep -n "class.*Base\|__tablename__" 5eyes-backend/models/review.py
```

### Am Ende der Datei hinzufügen:

```python
class SystemParam(Base):
    __tablename__ = "system_params"

    key = Column(String, primary_key=True)
    value = Column(String, nullable=False)
    updated_at = Column(String)
    updated_by = Column(String)
```

---

## Backend — Schritt B2: DB-Migration (auto create table)

### Datei: `5eyes-backend/database.py`

### Grep:
```
grep -n "create_all\|Base.metadata" 5eyes-backend/database.py
```

Prüfen ob `Base.metadata.create_all(bind=engine)` bereits vorhanden ist.
Wenn ja: Das neue Modell wird automatisch erstellt beim nächsten Start.
Wenn nein: Sicherstellen dass `create_all` nach Import aller Modelle aufgerufen wird.

**Hinweis:** Das SystemParam-Modell muss importiert sein bevor `create_all` läuft.
Prüfen ob `models/review.py` bereits in den Imports ist — normalerweise via
`from models import *` oder spezifischen Import.

---

## Backend — Schritt B3: Endpoints in `routers/system.py`

### Grep (Datei-Ende finden):
```
grep -n "^@router\|^def \|^async def " 5eyes-backend/routers/system.py
```

### Import hinzufügen (oben in system.py):
```python
from datetime import datetime, timezone
from models.review import SystemParam
```

### Endpoint 1: GET /admin/system/params

```python
@router.get('/params')
def get_system_params(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    rows = db.query(SystemParam).all()
    return {row.key: row.value for row in rows}
```

### Endpoint 2: PUT /admin/system/params

```python
@router.put('/params')
def set_system_params(
    body: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    now = datetime.now(timezone.utc).isoformat()
    for key, value in body.items():
        existing = db.query(SystemParam).filter(SystemParam.key == key).first()
        if existing:
            existing.value = str(value)
            existing.updated_at = now
            existing.updated_by = current_user.username
        else:
            db.add(SystemParam(
                key=key,
                value=str(value),
                updated_at=now,
                updated_by=current_user.username,
            ))
    db.commit()
    return {'ok': True}
```

---

## Frontend — Schritt F1: JS-Konstanten überschreiben beim App-Start

### Grep (Startup-Funktion finden):
```
grep -n "async function initApp\|function initApp\|window.onload\|DOMContentLoaded" 5eyes-electron/frontend/5eyes_v2.html
```

### Neue JS-Funktion `loadScoringParams()` — NACH den hardcodierten Konstanten einfügen

Einfügen direkt NACH der Zeile mit `var RISK_CAPACITY_MATRIX = {`:

```javascript
// Lädt Scoring-Parameter aus Admin-DB und überschreibt die Defaults
async function loadScoringParams() {
  try {
    var resp = await apiFetch('/admin/system/params');
    if (!resp || resp.error) return;
    if (resp['scoring_matrix']) {
      try {
        var m = JSON.parse(resp['scoring_matrix']);
        if (m && typeof m === 'object' && !Array.isArray(m)) {
          RISK_CAPACITY_MATRIX = m;
        }
      } catch(e) {}
    }
    if (resp['risk_capacity_bands']) {
      try {
        var b = JSON.parse(resp['risk_capacity_bands']);
        if (Array.isArray(b) && b.length > 0) {
          RISK_CAPACITY_BANDS = b;
        }
      } catch(e) {}
    }
    if (resp['fzk_cap']) {
      var cap = parseInt(resp['fzk_cap'], 10);
      if (!isNaN(cap) && cap > 0 && cap <= 100) {
        window.FZK_CAP_OVERRIDE = cap;
      }
    }
  } catch(e) {}
}
```

### Hinweis FZK_CAP_OVERRIDE:

Der FZK-Cap ist aktuell hardcoded an zwei Stellen als `75`. Codex sucht:
```
grep -n "finalScore.*FZK\|FZK.*Math.min\|min.*75" 5eyes-electron/frontend/5eyes_v2.html
```
Erwartet Treffer bei ca. Zeile 7234 und 7413:
```javascript
if(mandateType === 'FZK') finalScore = Math.min(finalScore, 75);
```
**BEIDE** Stellen ersetzen durch:
```javascript
if(mandateType === 'FZK') finalScore = Math.min(finalScore, window.FZK_CAP_OVERRIDE || 75);
```

### `loadScoringParams()` beim App-Start aufrufen:

Grep:
```
grep -n "loadScoringParams\|initApp\|async function.*app\|loadCMA\|loadInitial" 5eyes-electron/frontend/5eyes_v2.html
```

In der App-Initialisierung (wo auch CMA geladen wird, um Zeile 6219 in `openAdminModal`
oder in der initialen Load-Funktion) aufrufen:

```javascript
loadScoringParams();
```

**Wo genau einfügen:** In der Funktion die nach erfolgreichem Login aufgerufen wird.
Grep dafür:
```
grep -n "after.*login\|postLogin\|onLoginSuccess\|loginSuccess\|after_login" 5eyes-electron/frontend/5eyes_v2.html
```
Falls keine dedizierte post-login Funktion: Am Ende von `openAdminModal()` nach
dem bestehenden `loadAdminCapitalMarketAssumptions`-Aufruf.

---

## Frontend — Schritt F2: Admin-Sektion "Scoring-Parameter"

### Wo einfügen:

In `m-admin` (`id="m-admin"`), NACH der bestehenden CMA-Sektion
(nach `</div>` das die CMA-Section schliesst, vor `id="admin-result"`).

### Grep zum exakten Einfügepunkt:
```
grep -n "admin-cma-error\|admin-result\|id=\"admin-result\"" 5eyes-electron/frontend/5eyes_v2.html
```
Erwartet Treffer bei ca. Zeile 13951-13953.

### HTML-Code — Neue Sektion NACH `admin-cma-error` div, VOR `admin-result` div:

```html
        <div style="border-top:1px solid var(--b1);padding-top:12px;display:grid;gap:12px;">
          <div style="display:flex;justify-content:space-between;gap:12px;align-items:flex-start;flex-wrap:wrap">
            <div>
              <div style="font-size:11px;color:var(--g3);">Scoring-Parameter</div>
              <div style="font-size:10px;color:var(--n4);margin-top:4px;max-width:520px;line-height:1.5">Risikofähigkeits-Matrix (Horizont × Kapazitätsband → Max. Aktienanteil %) und FZK-Cap. Änderungen werden sofort wirksam.</div>
            </div>
            <div style="display:flex;gap:8px;flex-wrap:wrap">
              <button class="btn-p" style="background:var(--bg2);color:var(--n6)" onclick="loadAdminScoringParams(true)" id="btn-admin-scoring-refresh">Parameter laden</button>
              <button class="btn-p" style="background:var(--bg2);color:var(--n6)" onclick="loadAdminScoringDefaults()">Standardwerte</button>
              <button class="btn-p" style="background:var(--g4);color:#fff" onclick="saveAdminScoringParams()" id="btn-admin-scoring-save">Parameter speichern</button>
            </div>
          </div>
          <div style="border:1px solid var(--b1);border-radius:var(--r);padding:12px;background:var(--bg)">
            <div style="font-size:10px;font-weight:600;letter-spacing:0.06em;text-transform:uppercase;color:var(--n5);margin-bottom:10px">Risikofähigkeits-Matrix</div>
            <div style="font-size:10px;color:var(--n4);margin-bottom:8px;line-height:1.5">Zeilen = Anlagehorizont (Jahre). Spalten = Risikofähigkeits-Band (1=Risikoarm … 5=Dynamisch). Zellwert = Max. Aktienanteil %.</div>
            <div id="admin-scoring-matrix-grid" style="overflow-x:auto"></div>
          </div>
          <div style="display:grid;grid-template-columns:160px 1fr;gap:10px;align-items:center">
            <div>
              <label style="font-size:9px;color:var(--n4);display:block;margin-bottom:2px">FZK-Cap (Max. Aktienanteil %)</label>
              <input class="fi" id="admin-scoring-fzk-cap" type="number" min="10" max="100" step="5" value="75" style="font-size:11px">
            </div>
            <div style="font-size:10px;color:var(--n4);line-height:1.5">Für FZK-Mandate (Finanzielle Zielkunden): Maximaler Risiko-Score. Standard: 75.</div>
          </div>
          <div id="admin-scoring-error" style="display:none;color:var(--neg);font-size:10px"></div>
        </div>
```

---

## Frontend — Schritt F3: JS-Funktionen für Scoring-Parameter-Editor

### Einfügen NACH der `saveAdminCapitalMarketAssumptions`-Funktion:

Grep:
```
grep -n "async function saveAdminCapitalMarketAssumptions\|function saveAdminCapitalMarket" 5eyes-electron/frontend/5eyes_v2.html
```

### JS-Code:

```javascript
// ─── SCORING PARAMETER ADMIN ───────────────────────────────────────────────
var SCORING_HORIZON_ROWS = [1, 2, 4, 6, 9, 15];
var SCORING_BAND_COLS = [
  {band:1, label:'Risikoarm'},
  {band:2, label:'Sicherheits-\norientiert'},
  {band:3, label:'Ausgewogen'},
  {band:4, label:'Wachstums-\norientiert'},
  {band:5, label:'Dynamisch'}
];

function renderAdminScoringMatrixGrid(matrix) {
  var html = '<table style="border-collapse:collapse;font-size:10px;width:100%">';
  // Header row
  html += '<tr><th style="text-align:left;padding:4px 8px;color:var(--n4);font-weight:600;border-bottom:1px solid var(--b1)">Horizont</th>';
  SCORING_BAND_COLS.forEach(function(col) {
    html += '<th style="text-align:center;padding:4px 6px;color:var(--n4);font-weight:600;border-bottom:1px solid var(--b1);min-width:72px">' + col.label.replace('\n','<br>') + '</th>';
  });
  html += '</tr>';
  // Data rows
  SCORING_HORIZON_ROWS.forEach(function(horizonYears) {
    var rowLabel = horizonYears === 1 ? '< 2 J.' :
                   horizonYears === 2 ? '2-3 J.' :
                   horizonYears === 4 ? '4-5 J.' :
                   horizonYears === 6 ? '6-8 J.' :
                   horizonYears === 9 ? '9-14 J.' : '15+ J.';
    html += '<tr>';
    html += '<td style="padding:4px 8px;color:var(--g3);font-weight:500;white-space:nowrap">' + rowLabel + '</td>';
    SCORING_BAND_COLS.forEach(function(col) {
      var key = horizonYears + ',' + col.band;
      var val = matrix && matrix[key] != null ? matrix[key] : 0;
      var bg = val === 0 ? 'var(--bg2)' :
               val <= 20 ? 'rgba(201,168,76,0.08)' :
               val <= 50 ? 'rgba(201,168,76,0.15)' :
               val <= 75 ? 'rgba(201,168,76,0.22)' : 'rgba(201,168,76,0.30)';
      html += '<td style="padding:3px 4px;text-align:center;background:' + bg + ';border:1px solid var(--b1)">';
      html += '<input type="number" min="0" max="100" step="5" '
            + 'data-mkey="' + key + '" '
            + 'value="' + val + '" '
            + 'style="width:52px;text-align:center;font-size:11px;border:none;background:transparent;color:var(--g4);padding:2px 0">';
      html += '</td>';
    });
    html += '</tr>';
  });
  html += '</table>';
  return html;
}

function getAdminScoringMatrixFromGrid() {
  var matrix = {};
  var inputs = document.querySelectorAll('#admin-scoring-matrix-grid [data-mkey]');
  inputs.forEach(function(inp) {
    var key = inp.getAttribute('data-mkey');
    var val = parseInt(inp.value, 10);
    matrix[key] = isNaN(val) ? 0 : Math.max(0, Math.min(100, val));
  });
  return matrix;
}

function loadAdminScoringDefaults() {
  var grid = document.getElementById('admin-scoring-matrix-grid');
  if (!grid) return;
  // RISK_CAPACITY_MATRIX contains the current (possibly DB-overridden) values
  var defaultMatrix = {
    '1,1':0,   '1,2':0,   '1,3':0,   '1,4':0,   '1,5':0,
    '2,1':10,  '2,2':10,  '2,3':20,  '2,4':20,  '2,5':20,
    '4,1':10,  '4,2':40,  '4,3':45,  '4,4':50,  '4,5':50,
    '6,1':20,  '6,2':45,  '6,3':55,  '6,4':60,  '6,5':60,
    '9,1':20,  '9,2':50,  '9,3':60,  '9,4':65,  '9,5':70,
    '15,1':30, '15,2':50, '15,3':60, '15,4':75, '15,5':100
  };
  grid.innerHTML = renderAdminScoringMatrixGrid(defaultMatrix);
  setInputValue('admin-scoring-fzk-cap', '75');
}

async function loadAdminScoringParams(force) {
  var grid = document.getElementById('admin-scoring-matrix-grid');
  if (!grid) return;
  try {
    var resp = await apiFetch('/admin/system/params');
    var matrix = RISK_CAPACITY_MATRIX;
    if (resp && resp['scoring_matrix']) {
      try { matrix = JSON.parse(resp['scoring_matrix']); } catch(e) {}
    }
    grid.innerHTML = renderAdminScoringMatrixGrid(matrix);
    if (resp && resp['fzk_cap']) setInputValue('admin-scoring-fzk-cap', resp['fzk_cap']);
    var errEl = document.getElementById('admin-scoring-error');
    if (errEl) errEl.style.display = 'none';
  } catch(e) {
    grid.innerHTML = renderAdminScoringMatrixGrid(RISK_CAPACITY_MATRIX);
  }
}

async function saveAdminScoringParams() {
  var errEl = document.getElementById('admin-scoring-error');
  if (errEl) errEl.style.display = 'none';
  var btn = document.getElementById('btn-admin-scoring-save');
  if (btn) { btn.disabled = true; btn.textContent = 'Speichern…'; }
  try {
    var matrix = getAdminScoringMatrixFromGrid();
    var fzkCap = parseInt(getInputValue('admin-scoring-fzk-cap') || '75', 10);
    if (isNaN(fzkCap) || fzkCap < 10 || fzkCap > 100) fzkCap = 75;
    var payload = {
      scoring_matrix: JSON.stringify(matrix),
      fzk_cap: String(fzkCap)
    };
    var resp = await apiFetch('/admin/system/params', {method:'PUT', body:JSON.stringify(payload)});
    if (resp && resp.ok) {
      // Update in-memory constants immediately
      RISK_CAPACITY_MATRIX = matrix;
      window.FZK_CAP_OVERRIDE = fzkCap;
      if (errEl) { errEl.style.display = 'block'; errEl.style.color = 'var(--pos)'; errEl.textContent = 'Gespeichert.'; }
      setTimeout(function(){ if(errEl && errEl.textContent==='Gespeichert.') errEl.style.display='none'; }, 2000);
    } else {
      throw new Error((resp && resp.detail) || 'Fehler beim Speichern');
    }
  } catch(e) {
    if (errEl) { errEl.style.display = 'block'; errEl.style.color = 'var(--neg)'; errEl.textContent = String(e.message || e); }
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = 'Parameter speichern'; }
  }
}
// ─── END SCORING PARAMETER ADMIN ──────────────────────────────────────────
```

---

## Frontend — Schritt F4: Scoring-Params beim Modal-Öffnen laden

### Grep:
```
grep -n "function openAdminModal\|async function openAdminModal" 5eyes-electron/frontend/5eyes_v2.html
```
Erwartet Treffer ca. Zeile 6219.

### Bestehende Funktion anpassen:

**Alt (Ende der Funktion, ca. Zeile 6231):**
```javascript
  normalizeVisibleMojibake(document.getElementById('m-admin')||document.body);
}
```

**Neu:**
```javascript
  loadAdminScoringParams(false);
  normalizeVisibleMojibake(document.getElementById('m-admin')||document.body);
}
```

---

## Implementierungs-Checkliste für Codex

1. `models/review.py` — `SystemParam`-Klasse am Ende hinzufügen
2. `database.py` — sicherstellen dass `SystemParam` importiert ist vor `create_all`
3. `routers/system.py` — `datetime`-Import + `SystemParam`-Import oben hinzufügen
4. `routers/system.py` — GET `/admin/system/params` Endpoint hinzufügen
5. `routers/system.py` — PUT `/admin/system/params` Endpoint hinzufügen
6. `5eyes_v2.html` — `loadScoringParams()` Funktion nach `RISK_CAPACITY_MATRIX`-Konstante einfügen
7. `5eyes_v2.html` — Beide FZK-`Math.min(finalScore, 75)` auf `window.FZK_CAP_OVERRIDE || 75` ändern
8. `5eyes_v2.html` — `loadScoringParams()` in App-Init aufrufen (nach Login)
9. `5eyes_v2.html` — Admin-Sektion HTML in `m-admin` einfügen (nach `admin-cma-error`)
10. `5eyes_v2.html` — JS-Funktionen (`renderAdminScoringMatrixGrid`, etc.) nach CMA-Funktionen einfügen
11. `5eyes_v2.html` — `loadAdminScoringParams(false)` in `openAdminModal()` aufrufen
12. `node --check 5eyes-electron/frontend/5eyes_v2.html` → 0 Fehler

---

## Akzeptanzkriterien

1. Admin-Modal zeigt neue Sektion "Scoring-Parameter" unter CMA
2. Matrix-Grid zeigt 6 Zeilen (Horizonte) × 5 Spalten (Bänder) mit editierbaren Feldern
3. Farbliche Kodierung: 0 = grau, >0 = leicht gold, >50 = mittel gold, 100 = voll gold
4. "Parameter speichern" speichert in DB, zeigt "Gespeichert." Bestätigung
5. "Standardwerte" lädt die hardcodierten Defaults zurück in das Grid
6. Nach Speichern: `RISK_CAPACITY_MATRIX` im Browser-Memory ist sofort aktualisiert
7. Nach App-Neustart: Gespeicherte Parameter werden aus DB geladen und überschreiben Defaults
8. FZK-Cap editierbar, wird in DB gespeichert, wirkt sofort auf Score-Berechnung
9. Keine Regression in `computeRiskProfile` — Scores bleiben korrekt
10. `node --check` → 0 Fehler

---

## Risiken & Hinweise

- **Nur Admin-Rolle** kann Parameter ändern — `require_admin` auf beiden Endpoints
- **Sofortige Wirksamkeit:** Änderungen wirken sofort in der laufenden Session.
  Andere offene Sessions bekommen die Änderung erst nach Neustart — das ist akzeptabel.
- **Rollback:** `loadAdminScoringDefaults()` lädt Hardcode-Defaults zurück ins Grid,
  "Parameter speichern" macht sie dann DB-persistent. Sicherer Rollback-Pfad.
- **`body: dict` in PUT:** FastAPI akzeptiert `dict` als Body-Typ — falls es Probleme gibt,
  als Pydantic-Schema definieren: `class SystemParamsUpdate(BaseModel): __root__: dict[str,str]`
