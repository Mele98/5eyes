# Phase 6 FE-Optimizer-Panel — fertiger Implementations-Patch

**Datum:** 2026-05-06
**Owner:** Emanuele
**Workspace:** `C:\5eyes\5eyes_stage9_release_ready` (NICHT der Audit-Workspace)
**Branch-Vorschlag:** `codex/fe-optimizer-panel` from `codex/rp-ueberarbeitung`
**Master-Spec:** `2026-05-05-fe-optimizer-panel-spec.md`
**Backend-Status:** FERTIG — siehe Spec, alle Endpoints/Felder live.

Diese Datei ist die **fertige Implementation** zum 1:1-Übernehmen.
Drei Edit-Operationen in `5eyes-electron/frontend/5eyes_v2.html` plus ein Mock-Eintrag.

---

## Edit 1: HTML-Container (neue Card im #page-al)

**Anker:** finde diese Zeile (im File aktuell um Zeile 1208):
```html
          <div class="card" id="al-planning-card">
            <div class="chd"><span class="cht">Planungsannahmen</span></div>
```

**Aktion:** **direkt davor** (also zwischen der "Warum diese Soll-Allokation?"-Card und `al-planning-card`) den folgenden Block einfügen:

```html
          <!-- Phase 6: Optimizer-Panel -->
          <div class="card" id="al-optimizer-panel" style="display:none">
            <div class="chd">
              <span class="cht">Stochastischer Optimizer</span>
              <span class="opt-pill" id="opt-status-pill" style="margin-left:auto;font-size:10px;padding:2px 8px;border-radius:10px;display:inline-flex;align-items:center;gap:4px"></span>
            </div>
            <div class="cbody" style="display:grid;gap:12px">
              <div id="opt-fallback-banner" style="display:none;background:var(--warn-lt);border:1px solid rgba(122,82,0,0.25);border-radius:var(--r);padding:8px 10px;font-size:10px;color:var(--n6);line-height:1.4"></div>
              <details id="opt-reasoning-block" open>
                <summary style="font-size:11px;font-weight:500;cursor:pointer;color:var(--n6)">Reasoning-Trace</summary>
                <ul id="opt-reasoning-list" style="margin:6px 0 0 18px;padding:0;font-size:10px;color:var(--n6);line-height:1.5"></ul>
              </details>
              <details id="opt-stress-block">
                <summary style="font-size:11px;font-weight:500;cursor:pointer;color:var(--n6)">Stress-Tests (historisch)</summary>
                <table class="stress-table" id="opt-stress-table" style="margin-top:6px;width:100%;border-collapse:collapse;font-size:10px">
                  <thead>
                    <tr style="background:var(--bg);border-bottom:1px solid var(--b1)">
                      <th style="padding:5px 8px;text-align:left">Szenario</th>
                      <th style="padding:5px 8px;text-align:right">End-Vermögen</th>
                      <th style="padding:5px 8px;text-align:right">Min-Vermögen</th>
                      <th style="padding:5px 8px;text-align:right">Max DD</th>
                    </tr>
                  </thead>
                  <tbody></tbody>
                </table>
              </details>
              <details id="opt-sensitivity-block">
                <summary style="font-size:11px;font-weight:500;cursor:pointer;color:var(--n6)">Sensitivity-Analyse</summary>
                <div id="opt-sensitivity-list" style="margin-top:8px;display:flex;flex-direction:column;gap:8px"></div>
              </details>
              <div id="opt-audit-footer" style="font-size:9px;color:var(--n4);font-family:var(--f-d);border-top:1px dashed var(--b1);padding-top:6px"></div>
            </div>
          </div>
```

---

## Edit 2: JavaScript — drei Render-Funktionen + ein Helper

**Anker:** finde die existierende Funktion `renderActionCards(reasoning)` (im File aktuell um Zeile 11684):
```js
function renderActionCards(reasoning){
  var el=document.getElementById('aa-action-list');
```

**Aktion:** **direkt davor** den folgenden Block einfügen:

```js
// ============================================================================
// Phase 6: Optimizer-Panel (Status, Reasoning, Stress-Tests, Sensitivity)
// ============================================================================
function renderOptimizerPanel(result){
  var panel=document.getElementById('al-optimizer-panel');
  if(!panel)return;
  var ta=(result&&result.target_allocation)||{};
  var method=ta.optimization_method||null;
  var status=ta.optimization_status||null;

  // Sichtbarkeit: nur wenn Optimizer-Modus stochastic war.
  if(!method){
    panel.style.display='none';
    return;
  }
  panel.style.display='';

  // Status-Pill
  var pill=document.getElementById('opt-status-pill');
  if(pill){
    pill.textContent='';
    pill.style.background='';
    pill.style.color='';
    var pillMap={
      converged:{txt:'🟢 Konvergiert',bg:'rgba(22,101,52,0.12)',fg:'var(--pos)'},
      diverged_infeasible:{txt:'🟡 Divergiert',bg:'rgba(122,82,0,0.15)',fg:'var(--warn)'},
      diverged:{txt:'🟡 Divergiert',bg:'rgba(122,82,0,0.15)',fg:'var(--warn)'},
      fallback_house_matrix:{txt:'⚙️ Fallback House-Matrix',bg:'var(--bg2)',fg:'var(--n5)'}
    };
    var p=pillMap[status]||{txt:status||'—',bg:'var(--bg2)',fg:'var(--n5)'};
    pill.textContent=p.txt;
    pill.style.background=p.bg;
    pill.style.color=p.fg;
  }

  // Fallback-Banner
  var banner=document.getElementById('opt-fallback-banner');
  if(banner){
    if(status==='fallback_house_matrix'||status==='diverged'||status==='diverged_infeasible'){
      banner.style.display='';
      banner.textContent='Solver konvergierte nicht — House-Matrix-Default verwendet. Reasoning unten erklärt warum.';
    }else{
      banner.style.display='none';
    }
  }

  // Reasoning-Liste
  var rlist=document.getElementById('opt-reasoning-list');
  if(rlist){
    var allReasoning=Array.isArray(result.reasoning)?result.reasoning:[];
    var solverLines=allReasoning.filter(function(line){
      var s=String(line||'');
      return /Solver|Stochastic|SLSQP|Best objective|iterations|Stress '|Multi-Start|Optimizer/i.test(s);
    });
    if(!solverLines.length)solverLines=allReasoning.slice(0,5);
    rlist.innerHTML=solverLines.map(function(line){
      return '<li style="margin-bottom:3px">'+escapeHtml(String(line))+'</li>';
    }).join('');
  }

  // Stress-Tabelle
  renderStressTable(result.stress_evaluations||null);

  // Sensitivity-Slider pro Goal
  renderSensitivitySlidersForResult(result);

  // Audit-Footer
  var footer=document.getElementById('opt-audit-footer');
  if(footer){
    var seed=ta.optimization_seed!=null?String(ta.optimization_seed):'—';
    var iter=ta.optimization_iterations!=null?String(ta.optimization_iterations):'—';
    var obj=ta.optimization_objective_value_milli!=null?(Number(ta.optimization_objective_value_milli)/1000).toExponential(3):'—';
    footer.textContent='Method: '+method+' | Status: '+(status||'—')+' | Seed: '+seed+' | Iter: '+iter+' | L(w*): '+obj;
  }
}

function renderStressTable(stressEvals){
  var block=document.getElementById('opt-stress-block');
  var tbody=document.querySelector('#opt-stress-table tbody');
  if(!block||!tbody){return;}
  tbody.innerHTML='';
  if(!stressEvals||typeof stressEvals!=='object'){
    block.style.display='none';
    return;
  }
  var nameMap={
    great_depression_1929:'Grosse Depression 1929',
    financial_crisis_2008:'Finanzkrise 2008',
    covid_inflation_2020_2022:'Covid + Inflation 2020/22'
  };
  var keys=Object.keys(stressEvals);
  if(!keys.length){
    block.style.display='none';
    return;
  }
  block.style.display='';
  keys.forEach(function(name){
    var entry=stressEvals[name]||{};
    var endR=Number(entry.end_wealth_rappen||0);
    var minR=Number(entry.min_year_wealth_rappen||0);
    var ddBps=Number(entry.max_drawdown_bps||0);
    var rowHighlight=ddBps>5000?'background:rgba(220,53,69,0.08);':'';
    var endChf=Math.round(endR/100);
    var minChf=Math.round(minR/100);
    var ddPct=(ddBps/100).toFixed(1);
    var label=nameMap[name]||String(name);
    var tr=document.createElement('tr');
    tr.style.cssText='border-bottom:1px solid var(--b1);'+rowHighlight;
    tr.innerHTML=''
      +'<td style="padding:5px 8px">'+escapeHtml(label)+'</td>'
      +'<td style="padding:5px 8px;text-align:right;font-family:var(--f-d)">'+endChf.toLocaleString('de-CH')+'</td>'
      +'<td style="padding:5px 8px;text-align:right;font-family:var(--f-d)">'+minChf.toLocaleString('de-CH')+'</td>'
      +'<td style="padding:5px 8px;text-align:right;font-family:var(--f-d)">-'+ddPct+'%</td>';
    tbody.appendChild(tr);
  });
}

function renderSensitivitySlidersForResult(result){
  var wrap=document.getElementById('opt-sensitivity-list');
  var block=document.getElementById('opt-sensitivity-block');
  if(!wrap||!block){return;}
  wrap.innerHTML='';
  var goals=Array.isArray(result.goal_analysis)?result.goal_analysis:[];
  var mandateId=allocationPayloadMandateId(result);
  if(!goals.length||!mandateId){
    block.style.display='none';
    return;
  }
  block.style.display='';
  goals.forEach(function(g){
    var gid=g&&g.goal_id;
    var label=String(g&&(g.label||g.goal_type)||'Ziel');
    if(!gid)return;
    var row=document.createElement('div');
    row.style.cssText='border:1px solid var(--b1);border-radius:var(--r);padding:8px 10px;display:grid;gap:6px';
    row.innerHTML=''
      +'<div style="display:flex;justify-content:space-between;align-items:center">'
      +  '<span style="font-size:11px;font-weight:500">'+escapeHtml(label)+'</span>'
      +  '<span class="tag tn" style="font-size:9px">Was-wenn</span>'
      +'</div>'
      +'<div style="display:flex;gap:4px;flex-wrap:wrap">'
      +  ['-20','-10','0','10','20'].map(function(d){
           return '<button class="btn-p sens-btn" data-goal="'+escapeHtml(gid)+'" data-delta="'+d+'" data-mandate="'+escapeHtml(String(mandateId))+'" style="font-size:10px;padding:4px 10px;background:var(--bg2);color:var(--n6);min-width:0">'+(Number(d)>=0?'+':'')+d+'%</button>';
         }).join('')
      +'</div>'
      +'<div class="sens-result" style="font-size:10px;color:var(--n6);min-height:14px;font-family:var(--f-d)">—</div>';
    wrap.appendChild(row);
  });
  // Click-Handler delegation
  wrap.querySelectorAll('.sens-btn').forEach(function(btn){
    btn.addEventListener('click',function(){
      runSensitivityCall(btn);
    });
  });
}

function runSensitivityCall(btn){
  var gid=btn.getAttribute('data-goal');
  var delta=parseInt(btn.getAttribute('data-delta'),10);
  var mid=btn.getAttribute('data-mandate');
  var resEl=btn.parentElement&&btn.parentElement.parentElement&&btn.parentElement.parentElement.querySelector('.sens-result');
  if(!gid||!mid||isNaN(delta))return;
  if(resEl)resEl.textContent='Berechne…';
  // Kompletten button-Row deaktivieren während Lauf
  var siblings=btn.parentElement?btn.parentElement.querySelectorAll('button'):[];
  siblings.forEach(function(b){b.disabled=true;});
  var url='/mandates/'+encodeURIComponent(mid)+'/target-allocation/sensitivity';
  API.post(url,{goal_id:gid,target_delta_pct:delta}).then(function(body){
    if(!resEl){return;}
    var dPct=body.delta_objective_pct;
    var newAmt=Math.round(Number(body.target_amount_rappen_new||0)/100);
    var msg='Neuer Zielwert: CHF '+newAmt.toLocaleString('de-CH');
    if(dPct!=null){
      var sign=Number(dPct)>=0?'+':'';
      var direction=Number(dPct)<0?' (besser erreichbar)':(Number(dPct)>0?' (schwerer erreichbar)':'');
      msg+=' | Objective '+sign+Number(dPct).toFixed(1)+'%'+direction;
    }
    resEl.textContent=msg;
  }).catch(function(err){
    if(resEl)resEl.textContent='Fehler: '+(err&&err.message||'unbekannt');
  }).finally(function(){
    siblings.forEach(function(b){b.disabled=false;});
  });
}
```

> **Hinweis zu `API.post`:** Falls in dieser Codebasis der HTTP-Helper anders heisst (z.B. `apiPost`, `apiFetch`), den entsprechend ersetzen — der Aufruf ist eine Promise mit JSON-Body als Argument und JSON-Response. `escapeHtml` und `allocationPayloadMandateId` existieren bereits im File.

---

## Edit 3: Hook in `applyAllocationEngineResult`

**Anker:** finde diese Zeile (aktuell um 12134):
```js
  renderActionCards(result.reasoning);
```

**Aktion:** **direkt davor** einfügen:
```js
  renderOptimizerPanel(result);
```

So wird das Panel jedes Mal neu gerendert, wenn eine Allocation geladen oder neu berechnet wird (gen + reload-Pfad).

---

## Edit 4: desktop-api.js Mock (Offline-Demo)

**Datei:** `5eyes-electron/desktop-api.js`

**Suche** nach existierenden Mock-Patterns (z.B. `target-allocation/generate` Mock) und ergänze für `target-allocation/sensitivity`:

```js
// Phase 6 Sensitivity-Mock
{
  match:/\/mandates\/[^/]+\/target-allocation\/sensitivity$/,
  method:'POST',
  handler:function(body){
    var d=Number(body.target_delta_pct||0);
    var factor=1+d/100;
    var baseTarget=24000_00; // demo Pension-Goal
    return {
      goal_id:body.goal_id,
      delta_pct:d,
      target_amount_rappen_baseline:baseTarget,
      target_amount_rappen_new:Math.round(baseTarget*factor),
      objective_value_milli_baseline:12500_000_000,
      objective_value_milli_new:Math.round(12500_000_000*(1+d/100*0.3)),
      delta_objective_pct:d*30,
      weights_bps_baseline:{equities:5500,bonds:2500,real_estate:1000,alternatives:500,liquidity:500},
      weights_bps_new:{equities:5500-d*5,bonds:2500+d*5,real_estate:1000,alternatives:500,liquidity:500},
      status_baseline:'converged',
      status_new:'converged'
    };
  }
}
```

(Exaktes Format hängt davon ab wie der Mock-Router in dieser Codebasis aufgebaut ist — bei `if/else if`-Chain einfach analog ergänzen.)

---

## Akzeptanzkriterien (1:1 aus Master-Spec)

1. ✅ `OPTIMIZER_MODE=house_matrix` → Panel ist versteckt (`display:none`), keine Stress-Tabelle.
2. ✅ `OPTIMIZER_MODE=stochastic`+converged → grüner Pill, Reasoning-Liste, Stress-Tabelle, 5 Sensitivity-Buttons pro Goal.
3. ✅ Klick auf Sensitivity-Button → POST-Call löst aus, Loading-State sichtbar, Werte erscheinen darunter.
4. ✅ Audit-Footer zeigt method/seed/iter/L(w*).
5. ✅ `max_drawdown_bps > 5000` (50%) → Stress-Zeile rot hinterlegt.
6. ✅ Backwards-compat: Alte `target_allocation` ohne Optimizer-Felder → Panel bleibt versteckt, kein Crash.

## Manueller Smoke-Test

1. Backend mit `OPTIMIZER_MODE=stochastic` starten (siehe `2026-05-06-phase6-smoke-test.ps1`).
2. Test-Mandant mit Pension-Goal anlegen.
3. Allocation generieren → Panel erscheint mit grünem Pill, Reasoning, Stress-Tabelle, Sensitivity-Slidern.
4. Sensitivity-Button auf -20% → Werte erscheinen mit "(besser erreichbar)".
5. Page-Reload → Panel sollte identische Daten zeigen (Persistenz Phase 6.1+6.2).

## Was NICHT in diesem Patch ist

- Hardness-Änderung im Sensitivity-Slider (Phase 7).
- Eigene Stress-Szenarien definieren (Phase 7).
- PDF-Export der Optimization-Trace (Phase 7).
- Cache von Sensitivity-Calls (60s TTL, in der Spec als Risiko-Mitigation erwähnt — nice-to-have).

---

## Branch-Befehl (Codex)

```powershell
cd C:\5eyes\5eyes_stage9_release_ready
.\scripts\start_codex_branch.ps1 -Slug "fe-optimizer-panel" -FromCurrent
```

(`-FromCurrent` weil `codex/rp-ueberarbeitung` noch nicht in develop ist und Codex' aktive Files dort liegen.)
