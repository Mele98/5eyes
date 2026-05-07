# Claude Spec — Handelsliste / Rebalancing Trade Sheet

## Meta

- Titel: Handelsliste Modal für Live-Rebalancing-Positionen
- Datum: 2026-04-02
- Owner: Emanuele
- Branch-Vorschlag: `codex/rebalancing-trade-sheet`

## Ziel

Der Berater kann aus dem "Handlungsempfehlungen"-Panel direkt eine druckfertige Handelsliste
öffnen, die alle BUY/SELL-Transaktionen mit IST-Wert, SOLL-Wert und Delta darstellt.

## Ist-Zustand

- `applyRecommendationEngineResult(result)` (Zeile 6801): speichert `strategyState.recommendation`,
  verwendet `live = liveRebalancingPayload(result)` mit `live.position_drifts[]`
- `liveRebalancingPayload(result)` (Zeile 6328): gibt `result.live_rebalancing` zurück
- `live.position_drifts[]` (Schema `LiveRebalancingPositionResponse`): enthält pro Position:
  - `product_name`, `asset_class`, `sub_asset_class`
  - `rebalance_action` ("BUY" | "SELL" | "HOLD")
  - `current_market_value_rappen`, `target_amount_rappen`, `rebalance_amount_rappen`
  - `target_weight_bps`, `delta_weight_bps`
- `live.live_total_value_rappen`: Gesamtportfolio-Wert (für 0.5%-Schwellenwert)
- Letzte bekannte Modal-ID in der Datei: `m-contract-edit` (endet Zeile 3673)
- `formatRappen(rappen)` (Zeile 6270): `'CHF ' + Math.round(val/100).toLocaleString('de-CH')`
- `formatBpsPercent(bps)` (Zeile 6256): `bps/100` → `'10%'` etc.
- `escapeHtml()` vorhanden und muss überall verwendet werden
- `om('modal-id')` / `cm('modal-id')`: öffnet / schliesst Modal

## Scope

### Frontend only — keine Backend-Änderungen, keine Tests

1. Neues Modal `m-tl` (Handelsliste) — letztes Modal vor `<script>` (nach `m-contract-edit`)
2. Neue Funktion `openTradeList()` nach `applyRecommendationEngineResult`
3. "Handelsliste"-Button in `.chd` des "Handlungsempfehlungen"-Panels
4. Button-Visibility-Toggle am Ende von `applyRecommendationEngineResult`

---

## 1. HTML — Modal `m-tl`

**Position:** Direkt vor `</div><script>` nach `m-contract-edit` (Zeile 3673)

**Suchstring (eindeutig):**
```
</div><script>
  function showAwFields(val) {
```

**Ersetzen durch:**
```
</div>
<div class="overlay" id="m-tl">
  <div class="modal" style="width:820px;max-height:80vh;overflow-y:auto">
    <div class="mhd"><div class="mtitle">Handelsliste</div><button class="mx" onclick="cm('m-tl')">&#x2715;</button></div>
    <div class="mbody" id="m-tl-body"></div>
    <div class="mfooter">
      <button class="btn" onclick="cm('m-tl')">Schliessen</button>
      <button class="btn-g" onclick="window.print()">Drucken / PDF</button>
    </div>
  </div>
</div>
<script>
  function showAwFields(val) {
```

---

## 2. HTML — "Handelsliste"-Button im Panel-Header

**Suchstring (eindeutig in ganzer Datei):**
```
            <div class="chd"><span class="cht">Handlungsempfehlungen</span></div>
```

**Ersetzen durch:**
```
            <div class="chd"><span class="cht">Handlungsempfehlungen</span><button class="btn" id="btn-tl" style="font-size:10px;padding:3px 8px;margin-left:auto;display:none" onclick="openTradeList()">Handelsliste</button></div>
```

---

## 3. JS — `openTradeList()` (neue Funktion nach `applyRecommendationEngineResult`)

**Suchstring (eindeutig — Ende von `applyRecommendationEngineResult`):**
```
  renderStrategySummary();
}
async function loadCurrentAllocationResult(mid){
```

**Ersetzen durch:**
```javascript
  renderStrategySummary();
}
function openTradeList(){
  var result=strategyState.recommendation;
  var live=liveRebalancingPayload(result);
  var body=document.getElementById('m-tl-body');
  if(!body)return;
  if(!live||!Array.isArray(live.position_drifts)||!live.position_drifts.length){
    body.innerHTML='<div style="font-size:11px;color:var(--n5);padding:12px">Keine Live-Rebalancing-Daten verf\u00fcgbar.</div>';
    om('m-tl');
    return;
  }
  var totalWealth=live.live_total_value_rappen||0;
  var minThreshold=Math.round(totalWealth*0.005);
  var trades=live.position_drifts.filter(function(p){
    return Math.abs(p.rebalance_amount_rappen||0)>=minThreshold;
  }).slice().sort(function(a,b){
    return Math.abs(b.rebalance_amount_rappen||0)-Math.abs(a.rebalance_amount_rappen||0);
  });
  var totalBuy=0,totalSell=0;
  trades.forEach(function(p){
    var amt=p.rebalance_amount_rappen||0;
    if(p.rebalance_action==='BUY')totalBuy+=amt;
    else if(p.rebalance_action==='SELL')totalSell+=amt;
  });
  var actionColor=function(action){
    if(action==='BUY')return 'var(--pos)';
    if(action==='SELL')return 'var(--neg)';
    return 'var(--n5)';
  };
  var fmtDelta=function(rappen){
    var chf=Math.round(Math.abs(rappen||0)/100);
    var sign=(rappen||0)<0?'\u2212':'+';
    if(chf>=1000000)return sign+'CHF\u00a0'+(chf/1000000).toFixed(2).replace('.',"'")+'\u00a0Mio.';
    if(chf>=1000)return sign+'CHF\u00a0'+Math.round(chf/1000)+'k';
    return sign+'CHF\u00a0'+chf;
  };
  var rows=trades.map(function(p){
    var color=actionColor(p.rebalance_action);
    return '<tr style="border-bottom:1px solid var(--b1)">'
      +'<td style="padding:6px 8px;font-size:11px;font-weight:500">'+escapeHtml(p.product_name||'')+'</td>'
      +'<td style="padding:6px 8px;font-size:10px;color:var(--n5)">'+escapeHtml(p.sub_asset_class||p.asset_class||'')+'</td>'
      +'<td style="padding:6px 8px;font-size:10px;font-weight:700;color:'+color+'">'+escapeHtml(p.rebalance_action||'')+'</td>'
      +'<td style="padding:6px 8px;font-size:10px;text-align:right">'+escapeHtml(formatRappen(p.current_market_value_rappen))+'</td>'
      +'<td style="padding:6px 8px;font-size:10px;text-align:right">'+escapeHtml(formatRappen(p.target_amount_rappen))+'</td>'
      +'<td style="padding:6px 8px;font-size:10px;text-align:right;font-weight:600;color:'+color+'">'+escapeHtml(fmtDelta(p.rebalance_amount_rappen))+'</td>'
      +'<td style="padding:6px 8px;font-size:10px;text-align:right">'+escapeHtml(formatBpsPercent(p.target_weight_bps))+'</td>'
      +'</tr>';
  }).join('');
  var thStyle='padding:6px 8px;text-align:left;font-size:9px;font-weight:600;letter-spacing:0.07em;text-transform:uppercase;color:var(--n4);border-bottom:2px solid var(--b1)';
  var thR=thStyle+';text-align:right';
  var html='<div style="margin-bottom:10px;font-size:11px;color:var(--n5)">'
    +escapeHtml(String(trades.length))+' Positionen'
    +' &middot; Kaufvolumen: <span style="color:var(--pos)">'+escapeHtml(formatRappen(totalBuy))+'</span>'
    +' &middot; Verkaufsvolumen: <span style="color:var(--neg)">'+escapeHtml(formatRappen(totalSell))+'</span>'
    +'</div>'
    +'<div style="overflow-x:auto"><table style="width:100%;border-collapse:collapse">'
    +'<thead><tr>'
    +'<th style="'+thStyle+'">Wertpapier</th>'
    +'<th style="'+thStyle+'">Anlageklasse</th>'
    +'<th style="'+thStyle+'">Aktion</th>'
    +'<th style="'+thR+'">IST-Wert</th>'
    +'<th style="'+thR+'">SOLL-Wert</th>'
    +'<th style="'+thR+'">Delta</th>'
    +'<th style="'+thR+'">Soll-%</th>'
    +'</tr></thead>'
    +'<tbody>'+rows+'</tbody>'
    +'</table></div>';
  body.innerHTML=html;
  om('m-tl');
}
async function loadCurrentAllocationResult(mid){
```

---

## 4. JS — Button-Visibility-Toggle in `applyRecommendationEngineResult`

**Suchstring (Ende der Funktion, eindeutig):**
```
  renderStrategySummary();
}
function openTradeList(){
```

**Ersetzen durch:**
```javascript
  var btnTl=document.getElementById('btn-tl');
  if(btnTl){
    var hasTrades=live&&(live.position_drifts||[]).some(function(p){return p.rebalance_action!=='HOLD';});
    btnTl.style.display=hasTrades?'':'none';
  }
  renderStrategySummary();
}
function openTradeList(){
```

**Wichtig:** Diese 4 Zeilen kommen ZWISCHEN dem bisherigen `renderStrategySummary();` und dem
neuen `function openTradeList()`. Der finale Suchstring (Schritt 4) setzt voraus, dass
Schritt 3 bereits angewendet wurde (er sucht nach `renderStrategySummary();\n}\nfunction openTradeList(){`).

**Codex muss Schritt 3 VOR Schritt 4 anwenden.**

---

## Reihenfolge der Änderungen (kritisch)

1. Modal HTML einfügen (`m-tl`)
2. Handelsliste-Button in `.chd` hinzufügen
3. `openTradeList()` Funktion nach `applyRecommendationEngineResult` einfügen
4. Button-Visibility-Toggle am Ende von `applyRecommendationEngineResult` einfügen
   (NACH Schritt 3, weil der Suchstring nach `function openTradeList()` sucht)

---

## Akzeptanzkriterien

1. "Handelsliste"-Button im Handlungsempfehlungen-Header ist zunächst `display:none`
2. Nach Laden einer Recommendation mit BUY/SELL-Positionen: Button wird sichtbar
3. Klick auf Button öffnet `m-tl` Modal
4. Tabelle zeigt alle Positionen mit |rebalance_amount| ≥ 0.5% des Portfolios
5. Positionen sortiert nach |Delta| absteigend
6. BUY = grün (`var(--pos)`), SELL = rot (`var(--neg)`)
7. Kein XSS: alle Werte über `escapeHtml()` gerendert
8. "Drucken / PDF"-Button: `window.print()`
9. Wenn keine Recommendation / kein live rebalancing: Modal zeigt Hinweis, kein Absturz
10. `node --check 5eyes-electron/frontend/5eyes_v2.html` muss grün sein

---

## Implementierungs-Checkliste für Codex

1. Änderung 1 (Modal): `grep -n "function showAwFields" 5eyes-electron/frontend/5eyes_v2.html`
   → sicherstellen, dass Suchstring einmalig ist, dann einfügen
2. Änderung 2 (Button): `grep -n "Handlungsempfehlungen" 5eyes-electron/frontend/5eyes_v2.html`
   → nur 1 Treffer bei Zeile ~905 → sicher
3. Änderung 3 (`openTradeList`): Suchstring `renderStrategySummary();\n}\nasync function loadCurrentAllocationResult`
4. Änderung 4 (Button-Toggle): NACH Schritt 3 ausführen; sucht `renderStrategySummary();\n}\nfunction openTradeList()`
5. `node --check 5eyes-electron/frontend/5eyes_v2.html` → muss 0 Fehler zeigen
