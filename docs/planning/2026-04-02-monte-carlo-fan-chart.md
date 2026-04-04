# Claude Spec — Monte Carlo P10/P50/P90 Fan-Chart

## Meta

- Titel: Monte Carlo Konfidenzband im Optimierten-Prognose-Chart
- Datum: 2026-04-02
- Owner: Emanuele
- Branch-Vorschlag: `codex/mc-fan-chart`

## Ziel

Der Chart `ch-opt` ("Optimierte Prognose") zeigt bisher nur einen einzigen P50-Mediankurs.
Mit dieser Änderung wird er zu einem echten Monte-Carlo-Fan-Chart mit drei Bändern (P10/P50/P90),
sodass der Berater das Konfidenzintervall der Projektion auf einen Blick sieht.

## Ist-Zustand

- `initCharts()` (Zeile 2764): erstellt `charts.opt` als 2-Dataset-Chart (opt P50 + IST P50)
- `updateProjectionChartsFromSimulation(result)` (Zeile 6347): überschreibt `datasets[0].data` (Soll) und `datasets[1].data` (IST)
- `monteCarloPayload(result)` (Zeile 6325): gibt `result.monte_carlo` zurück wenn `target_p50_series_rappen[]` vorhanden
- `simulationSeriesK(series)` (Zeile 6331): konvertiert Rappen → CHF-Tausend (÷ 100 000, gerundet)
- `applyAllocationEngineResult` (Zeile ~6700): ruft auf Zeile 6756 `updateProjectionChartsFromSimulation(result)` auf

## Scope

### Frontend only — keine Backend-Änderungen, keine Tests

1. Neue Funktion `upgradeFanChartWithMonteCarlo(result)` nach `updateProjectionChartsFromSimulation`
2. Call `upgradeFanChartWithMonteCarlo(result)` direkt nach `updateProjectionChartsFromSimulation(result)` im Result-Handler

---

## Technische Grundlage

**Chart.js 4.4.1 Fill-between-Datasets:**
- `fill: '+1'` füllt die Fläche zwischen dem aktuellen Dataset und dem Dataset bei Index+1
- Dataset-Reihenfolge ist kritisch für die Bandform:
  - Index 0 (P90, `fill: '+1'`): oberes Band → Fläche zwischen P90 und P50
  - Index 1 (P50, `fill: '+1'`): unteres Band → Fläche zwischen P50 und P10
  - Index 2 (P10, `fill: false`): untere Grenzlinie, keine Fläche
  - Index 3 (IST P50, `fill: false`): gestrichelt, keine Fläche
- Der `Filler`-Plugin ist im vollen Chart.js 4.x Bundle enthalten — kein separates Register nötig

**Datenquellen:**
- `mc.target_p90_series_rappen[]` → P90-Linie
- `mc.target_p50_series_rappen[]` → Medianlinie (Hauptlinie)
- `mc.target_p10_series_rappen[]` → P10-Linie
- `mc.current_p50_series_rappen[]` → IST-Kurve (gestrichelt)
- `mc.year_labels[]` → X-Achsen-Labels

**Idempotenz:** `upgradeFanChartWithMonteCarlo` ersetzt IMMER das gesamte `datasets`-Array.
Das ist korrekt, weil sie NACH `updateProjectionChartsFromSimulation` aufgerufen wird, welche
die ersten beiden Datasets kurz setzt — der Fan-Chart überschreibt das sofort korrekt.

**Fallback:** Wenn `monteCarloPayload(result)` null zurückgibt (Backend ohne MC-Daten), passiert
nichts — der Chart bleibt im 2-Dataset-Modus von `updateProjectionChartsFromSimulation`.

---

## Neue Funktion `upgradeFanChartWithMonteCarlo(result)`

**Position im Code:** Direkt nach dem schliessenden `}` von `updateProjectionChartsFromSimulation`
und vor `function simulationCagrBps`.

**Suchstring (eindeutig):**
```
}
function simulationCagrBps(series){
```

**Ersetzen durch:**
```javascript
}
function upgradeFanChartWithMonteCarlo(result){
  if(!charts.opt||!charts.opt.data)return;
  var mc=monteCarloPayload(result);
  if(!mc)return;
  var labels=(mc.year_labels||[]).map(function(y){return String(y);});
  var p90=simulationSeriesK(mc.target_p90_series_rappen);
  var p50=simulationSeriesK(mc.target_p50_series_rappen);
  var p10=simulationSeriesK(mc.target_p10_series_rappen);
  var cur=simulationSeriesK(mc.current_p50_series_rappen);
  if(!p90.length||!p50.length||!p10.length)return;
  charts.opt.data.labels=labels;
  charts.opt.data.datasets=[
    {
      label:'P90',
      data:p90,
      borderColor:'rgba(22,101,52,0.30)',
      backgroundColor:'rgba(22,101,52,0.10)',
      borderWidth:1,
      borderDash:[3,3],
      pointRadius:0,
      fill:'+1',
      tension:0.4
    },
    {
      label:'P50 (Median)',
      data:p50,
      borderColor:'rgb(22,101,52)',
      backgroundColor:'rgba(22,101,52,0.10)',
      borderWidth:2,
      pointRadius:0,
      fill:'+1',
      tension:0.4
    },
    {
      label:'P10',
      data:p10,
      borderColor:'rgba(22,101,52,0.30)',
      backgroundColor:'transparent',
      borderWidth:1,
      borderDash:[3,3],
      pointRadius:0,
      fill:false,
      tension:0.4
    },
    {
      label:'IST-Prognose',
      data:cur,
      borderColor:'rgba(146,64,14,0.65)',
      backgroundColor:'transparent',
      borderWidth:1.5,
      borderDash:[3,3],
      pointRadius:0,
      fill:false,
      tension:0.4
    }
  ];
  charts.opt.options.plugins.legend.display=true;
  charts.opt.options.plugins.legend.labels={font:{size:9},boxWidth:9,padding:7};
  charts.opt.update();
}
function simulationCagrBps(series){
```

---

## Call-Site: `upgradeFanChartWithMonteCarlo` aufrufen

**Position im Code:** In `applyAllocationEngineResult`, direkt nach `updateProjectionChartsFromSimulation(result);`

**Suchstring (eindeutig):**
```
  updateProjectionChartsFromSimulation(result);
  var projectedRappen=simulationTerminalRappen
```

**Ersetzen durch:**
```
  updateProjectionChartsFromSimulation(result);
  upgradeFanChartWithMonteCarlo(result);
  var projectedRappen=simulationTerminalRappen
```

---

## Akzeptanzkriterien

1. `charts.opt` zeigt 4 Datasets wenn `result.monte_carlo.target_p*_series_rappen` vorhanden
2. Oberes Band (P90→P50): grüne Fläche mit `fill: '+1'`
3. Unteres Band (P50→P10): grüne Fläche mit `fill: '+1'`
4. P50-Linie: durchgezogen grün (rgb(22,101,52)), 2px
5. IST-Linie: gestrichelt braun (rgba(146,64,14,0.65)), 1.5px
6. Legende zeigt P90 / P50 (Median) / P10 / IST-Prognose
7. Wenn `monteCarloPayload(result)` null → kein Absturz, Chart bleibt 2-Dataset-Modus
8. `node --check 5eyes-electron/frontend/5eyes_v2.html` muss grün sein

---

## Implementierungs-Checkliste für Codex

1. `grep -n "function simulationCagrBps" 5eyes-electron/frontend/5eyes_v2.html`
   → Zeile ~6365 finden, neue Funktion DAVOR einfügen
2. `grep -n "updateProjectionChartsFromSimulation(result);" 5eyes-electron/frontend/5eyes_v2.html`
   → Zeile ~6756 finden, Call `upgradeFanChartWithMonteCarlo(result);` dahinter einfügen
3. Kein Import, kein Backend, kein Test nötig
4. `node --check 5eyes-electron/frontend/5eyes_v2.html` → muss 0 Fehler zeigen
