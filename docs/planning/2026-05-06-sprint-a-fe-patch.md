# Sprint A FE-Patch — Codex-Spec

**Datum:** 2026-05-06
**Owner:** Emanuele
**Wer fuehrt aus:** Codex
**Workspace:** `C:\5eyes\5eyes_stage9_release_ready`
**Branch:** `codex/sprint-a-fe` von `codex/sprint-a-quick-wins` (FE only, Backend ist fertig)

## Vorbedingung

Backend von Sprint A ist gemerged via PR #2 (Branch `codex/sprint-a-quick-wins`).
- Endpoints: GET/POST/PUT/DELETE `/clients/{id}/wealth-inflows`, POST `/wealth-inflows/{id}`, etc.
- Endpoint: POST `/mandates/{id}/goals/calculate-max-pension-spending`
- Mandate-Update-Schema: neue Felder `retirement_year`, `life_expectancy_year`

## Drei FE-Aufgaben

### FE-A1: Card "Vermögenszuflüsse" auf #page-cf

**Position:** auf Cashflow-Page (`#page-cf`), zwischen den Cashflow-Listen und der Goals-Sektion. Anchor: nach dem `<div class="cashflow-lists">`-Container.

**Markup:**
```html
<div class="card" id="cf-wealth-inflows-card">
  <div class="chd"><span class="cht">Erwartete Vermögenszuflüsse</span>
    <button class="btn-p" onclick="om('m-add-inflow')">+ Hinzufügen</button>
  </div>
  <div class="cbody">
    <div id="wealth-inflows-list" style="display:flex;flex-direction:column;gap:8px"></div>
  </div>
</div>
```

**Modal `m-add-inflow`** (analog zu existierenden Cashflow-Modals): Felder
- `label` (text)
- `source_type` (dropdown: Erbschaft, Bonus, Saeule3b, Verkaufserloes, Andere)
- `amount_rappen` (input mit CHF-Formatter, intern *100)
- `expected_year` (number, default current_year+5)
- `is_recurring` (checkbox)
- `frequency` (jaehrlich/monatlich, nur wenn recurring)
- `duration_years` (number, nur wenn recurring)
- `value_mode` (toggle nominal/real)
- `notes` (textarea)

**JS-Funktionen:**
```js
async function loadWealthInflows(cid) {
  const list = await API.get('/clients/'+cid+'/wealth-inflows');
  renderWealthInflows(list);
}

function renderWealthInflows(items) {
  const el = document.getElementById('wealth-inflows-list');
  if (!el) return;
  if (!items || !items.length) {
    el.innerHTML = '<div style="font-size:11px;color:var(--n5);padding:8px">Keine Vermögenszuflüsse erfasst.</div>';
    return;
  }
  el.innerHTML = items.map(infl => {
    const chf = Math.round(infl.amount_rappen / 100).toLocaleString('de-CH');
    const recur = infl.is_recurring ? ` · ${infl.frequency} ${infl.duration_years}J` : '';
    return `<div class="cf-row" data-inflow-id="${escapeHtml(infl.id)}">
      <div class="cfi" style="background:var(--pos-lt)">+</div>
      <div class="cfn">
        <div class="cfna">${escapeHtml(infl.label)}</div>
        <div class="cfnd">${escapeHtml(infl.source_type)} · ${infl.expected_year}${recur} · ${escapeHtml(infl.value_mode)}</div>
      </div>
      <div class="cfa ci">+CHF ${chf}</div>
      <div>
        <button class="btn-ico e" onclick="editWealthInflow('${escapeHtml(infl.id)}')">✎</button>
        <button class="btn-ico" onclick="deleteWealthInflow('${escapeHtml(infl.id)}')">✕</button>
      </div>
    </div>`;
  }).join('');
}

async function saveWealthInflow() { /* form-collect → POST */ }
async function editWealthInflow(id) { /* GET single → fill form → reopen modal */ }
async function deleteWealthInflow(id) { /* DELETE */ }
```

**Hook:** in `loadClientById()` nach `loadCurrentRiskAssessment` ergänzen:
```js
loadWealthInflows(c.id).catch(e => console.warn('inflows:', e));
```

### FE-A2: Modal "Maximale Ausgaben Ruhestand"

**Position:** Modal neben Goals-Liste auf `#page-cf` oder eigener Button auf Goals-Card.

**Markup:**
```html
<button class="btn-p" onclick="openMaxSpendingModal()">📊 Max. Ausgaben Ruhestand berechnen</button>

<div class="overlay" id="m-max-spending">
  <div class="modal">
    <div class="mhd"><div class="mtitle">Maximale Ausgaben im Ruhestand</div>
      <button class="mx" onclick="cm('m-max-spending')">✕</button>
    </div>
    <div class="mbody">
      <label>Renteneintritt (Jahr)<input id="msp-retirement" type="number" value="2035"></label>
      <label>Lebenserwartung (Jahr)<input id="msp-life" type="number" value="2065"></label>
      <label>
        <input id="msp-mode-real" type="radio" name="msp-mode" value="real" checked> Real (heute-Wert)
        <input id="msp-mode-nominal" type="radio" name="msp-mode" value="nominal"> Nominal
      </label>
      <label>Sicherheits-Margin<input id="msp-margin" type="number" min="0" max="50" value="0"> %</label>
      <button class="btn-p" onclick="runMaxSpending()">Berechnen</button>
      <div id="msp-result" style="display:none;margin-top:14px;padding:12px;background:var(--bg2);border-radius:var(--r)">
        <div class="msp-amount" style="font-size:24px;font-weight:700"></div>
        <div class="msp-reasoning" style="font-size:10px;color:var(--n5);margin-top:8px"></div>
        <button class="btn-p" onclick="createPensionGoalFromMax()">Als Ziel anlegen</button>
      </div>
    </div>
  </div>
</div>
```

**JS:**
```js
async function runMaxSpending() {
  const mid = getActiveMandateId();
  if (!mid) return;
  const body = {
    retirement_year: parseInt(document.getElementById('msp-retirement').value, 10),
    life_expectancy_year: parseInt(document.getElementById('msp-life').value, 10),
    value_mode: document.querySelector('input[name="msp-mode"]:checked').value,
    safety_margin_pct: parseInt(document.getElementById('msp-margin').value, 10) || 0,
  };
  const res = await API.post('/mandates/'+mid+'/goals/calculate-max-pension-spending', body);
  const monthly = Math.round(res.max_monthly_chf_rappen / 100);
  document.querySelector('#msp-result .msp-amount').textContent = 'CHF ' + monthly.toLocaleString('de-CH') + ' / Monat';
  document.querySelector('#msp-result .msp-reasoning').innerHTML = res.reasoning.map(r => '<div>• ' + escapeHtml(r) + '</div>').join('');
  document.getElementById('msp-result').style.display = '';
  window._lastMaxSpending = res;
}

async function createPensionGoalFromMax() {
  const r = window._lastMaxSpending;
  if (!r) return;
  const mid = getActiveMandateId();
  await API.post('/mandates/'+mid+'/goals', {
    goal_family: 'Cashflow', goal_type: 'Pensionsausgabe',
    label: 'Pension (auto)', rank: 1,
    target_amount_rappen: r.max_monthly_chf_rappen,
    frequency: 'monatlich',
    target_date: r.life_expectancy_year + '-01-01',
    start_date: r.retirement_year + '-01-01',
    is_ongoing: 0, hardness: 'Primaer', value_mode: r.value_mode,
  });
  cm('m-max-spending');
  refreshGoalsUI(mid);
}
```

### FE-A3: Renteneintrittsalter + Lebenserwartung Inputs

**Position:** auf Risikoprofil-Page (`#page-rp`) als Karte unter "Allgemein".

**Markup:**
```html
<div class="card" id="rp-life-card">
  <div class="chd"><span class="cht">Lebenserwartung & Renteneintritt</span></div>
  <div class="cbody" style="display:grid;grid-template-columns:1fr 1fr;gap:10px">
    <label>Renteneintritt (Jahr)
      <input class="fi" id="mandate-retirement-year" type="number" min="2024" max="2100" placeholder="z.B. 2035">
    </label>
    <label>Lebenserwartung (Jahr)
      <input class="fi" id="mandate-life-expectancy-year" type="number" min="2024" max="2150" placeholder="z.B. 2080">
    </label>
    <button class="btn-p" style="grid-column:1/-1" onclick="saveMandateRetirementSettings()">Speichern</button>
  </div>
</div>
```

**JS:**
```js
async function saveMandateRetirementSettings() {
  const mid = getActiveMandateId();
  if (!mid) return;
  const body = {
    retirement_year: parseInt(document.getElementById('mandate-retirement-year').value, 10) || null,
    life_expectancy_year: parseInt(document.getElementById('mandate-life-expectancy-year').value, 10) || null,
  };
  await API.put('/mandates/'+mid, body);
  markStrategyDirty('Lebenserwartung/Renteneintritt aktualisiert.', true);
}
```

**Hook in `loadCurrentMandate(mid)` o.ae.:** beim Laden des Mandanten die Werte in die Inputs füllen.

## Akzeptanzkriterien

1. ✅ Mandant mit Erbschaft 100k in Year 5: Card zeigt Eintrag, Allocation berücksichtigt Inflow
2. ✅ Klick "Max Ausgaben berechnen" → Modal zeigt Annuität + Reasoning
3. ✅ Klick "Als Ziel anlegen" → Pensionsausgabe-Goal wird angelegt
4. ✅ Renteneintritt + Lebenserwartung Inputs persistieren auf Mandate
5. ✅ Backend FE-Contract-Tests bleiben grün (11/11)

## Smoke-Test (Codex manuell)

1. App starten, Mandant öffnen, auf Cashflow-Page
2. "+ Hinzufügen" Erbschaft 50k in 2030 → Liste zeigt Eintrag
3. "Max Ausgaben" klicken, 2035-2065 → Annuität ~25k
4. Auf Risikoprofil-Page: Lebenserwartung 2080 setzen → "Speichern"
5. Allocation generieren → Horizont jetzt > 50 Jahre

## Was NICHT in diesem Patch ist

- WealthInflow als Goal-Type (separates Konzept beibehalten)
- Conditional Goals (Phase B6)
- Time-Bucket-Reserve (Phase B5)
- Steuer-Brutto/Netto (Phase C3)
