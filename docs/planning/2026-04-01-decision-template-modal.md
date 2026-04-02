# Claude Spec — Entscheidungsvorlage-Modal: Live-Drift-Daten

## Meta

- Titel: `m-ed` Entscheidungsvorlage — dynamischer Drift-Inhalt aus `live_rebalancing`
- Datum: 2026-04-01
- Owner: Emanuele
- Branch-Vorschlag: `codex/decision-template-modal`

## Kontext & Ist-Zustand

### Was bereits funktioniert (nicht anfassen)

| Funktion | Zustand | Zeile (ca.) |
|---|---|---|
| `documentDecisionTemplate()` | FERTIG — ruft `POST /mandates/{id}/advisory-log` + `PUT /mandates/{id}/triggers/{id}/resolve` | 7825 |
| `selectDecisionOption(choice)` | FERTIG — setzt Highlight auf gewählte Karte | 5502 |
| `resetDecisionTemplateModal()` | FERTIG — setzt `currentDecisionChoice='option_a'`, ruft `selectDecisionOption()` | 5514 |
| `openDecisionTemplateModal(triggerId)` | FERTIG — schreibt `triggerId` in `ed.dataset.triggerId`, öffnet Modal | 5522 |
| `refreshReviewUI(mid)` | FERTIG — ruft `POST system-refresh` + lädt Triggers/Log/Docs neu | 7653 |
| `saveAdvisoryLogEntry()` | FERTIG — vollständig verdrahtet (`m-ne`) | 7678 |
| `saveReviewTrigger()` | FERTIG — vollständig verdrahtet (`m-nt`) | 7740 |

### Das einzige echte Gap

Das Modal `#m-ed` hat **statischen HTML-Body** mit Fake-Daten (Zeile 1414):

```html
<!-- HARDCODED — wird NICHT aus live_rebalancing befüllt -->
<div style="background:var(--neg-lt)...">
  Aktienquote 53% vs. Soll 45%. Drift +8.2%. Seit 14. November verletzt.
</div>
<div style="display:flex;flex-direction:column;gap:6px">
  <div ... onclick="this.style.borderColor=...">
    <div>✓ Option A – Zuflüsse umlenken (empfohlen)</div>
    <div>CHF 155k in Anleihen & Liquidität. Organische Normalisierung 12—18 Monate.</div>
  </div>
  ...
</div>
```

Und `getDecisionChoiceMeta(choice)` (Zeile 7460) gibt ebenfalls **hardcodierte CHF-Beträge** zurück:

```js
option_a: { title:'Option A – Zuflüsse umlenken', detail:'CHF 155k in Anleihen und Liquidität...' }
option_b: { title:'Option B – Teilverkauf Aktien', detail:'Teilverkauf Aktien CHF 300k...' }
```

Die Darstellung zeigt also immer dieselben Zahlen — unabhängig davon, welches Mandat geöffnet ist oder wie gross die tatsächliche Drift ist. Wenn ein Advisor das Modal öffnet und "Dokumentieren" klickt, wird ein korrekter Advisory-Log-Eintrag gespeichert — aber die gezeigten Optionen sind nonsense für diesen Kunden.

### Verfügbare Live-Daten

`strategyState.recommendation.live_rebalancing` wird bei jedem Strategie-Run befüllt. Struktur (aus Schema `LiveRebalancingResponse`):

```js
{
  live_total_value_rappen: 485000000,          // CHF 4.85M
  breached_asset_classes: ["Aktien"],
  bucket_drifts: [
    {
      asset_class: "Aktien",
      current_weight_bps: 5300,                // 53.0%
      target_weight_bps: 4500,                 // 45.0%
      band_min_bps: 4000,                      // 40.0%
      band_max_bps: 5000,                      // 50.0%
      current_market_value_rappen: 257050000,  // CHF 2.57M
      target_market_value_rappen: 218250000,   // CHF 2.18M
      delta_weight_bps: 800,                   // +8.0 pp
      rebalance_amount_rappen: 38800000,       // CHF 388k nötig
      breached: true,
      breach_bps: 300                          // 3.0 pp über Band-Max
    },
    // ... weitere Klassen
  ]
}
```

Dieses Objekt ist via `liveRebalancingPayload(strategyState.recommendation)` (Zeile 6254) abrufbar. Es ist `null` wenn noch kein Run gemacht wurde.

---

## Scope

### Frontend only — Backend ist vollständig

- Keine Backend-Änderungen
- Kein neues Schema
- Kein neuer Endpoint

### Frontend-Änderungen

1. **`m-ed` Modal-Body umbauen** — statischen HTML durch dynamische Container ersetzen
2. **`renderDecisionTemplateModal(triggerId)` schreiben** — befüllt die Container mit Live-Daten
3. **`openDecisionTemplateModal(triggerId)` erweitern** — ruft `renderDecisionTemplateModal()` nach Reset auf
4. **`getDecisionChoiceMeta(choice, bucket)` erweitern** — nimmt optional `bucket` und berechnet echte CHF-Beträge
5. **Fallback** — wenn kein `live_rebalancing` vorhanden (kein Run): generische Optionen ohne CHF-Beträge

---

## Detaillierte Implementierung

### 1. `m-ed` Modal-Body (HTML, Zeile 1414)

**Vor** (Zeile 1414 — vollständig ersetzen):
```html
<div class="overlay" id="m-ed"><div class="modal" style="width:560px"><div class="mhd"><div class="mtitle">Entscheidungsvorlage – Drift</div><button class="mx" onclick="cm('m-ed')">✕</button></div><div class="mbody"><div style="background:var(--neg-lt);border:1px solid rgba(153,27,27,0.12);border-radius:var(--r);padding:8px;margin-bottom:12px;font-size:11px;line-height:1.6">Aktienquote 53% vs. Soll 45%. Drift +8.2%. Seit 14. November verletzt.</div><div class="fs">Optionen</div><div style="display:flex;flex-direction:column;gap:6px"><div style="border:1px solid var(--b1);border-radius:var(--r);padding:9px;cursor:pointer" onclick="this.style.borderColor='var(--n6)';this.style.background='var(--n0)'"><div style="font-size:11px;font-weight:500;margin-bottom:3px">✓ Option A – Zuflüsse umlenken (empfohlen)</div><div style="font-size:10px;color:var(--n6);line-height:1.4">CHF 155k in Anleihen &amp; Liquidität. Organische Normalisierung 12—18 Monate.</div></div><div style="border:1px solid var(--b1);border-radius:var(--r);padding:9px;cursor:pointer" onclick="this.style.borderColor='var(--n6)';this.style.background='var(--n0)'"><div style="font-size:11px;font-weight:500;margin-bottom:3px">Option B – Teilverkauf Aktien CHF 300k</div><div style="font-size:10px;color:var(--n6);line-height:1.4">Sofortige Normalisierung. Steuerfolgen prüfen.</div></div><div style="border:1px solid var(--b1);border-radius:var(--r);padding:9px;cursor:pointer" onclick="this.style.borderColor='var(--n6)';this.style.background='var(--n0)'"><div style="font-size:11px;font-weight:500;margin-bottom:3px">Option C – Drift tolerieren (dokumentiert)</div><div style="font-size:10px;color:var(--n6);line-height:1.4">Mit Begründung weiteres Quartal. Kundenkommunikation notwendig.</div></div></div></div><div class="mfooter"><button class="btn" onclick="cm('m-ed')">Schliessen</button><button class="btn-p" onclick="cm('m-ed')">Dokumentieren</button></div></div></div>
```

**Nach** (Ersatz — gleiche Position im HTML):
```html
<div class="overlay" id="m-ed"><div class="modal" style="width:560px"><div class="mhd"><div class="mtitle">Entscheidungsvorlage – Drift</div><button class="mx" onclick="cm('m-ed')">✕</button></div><div class="mbody"><div id="ed-drift-info" style="background:var(--neg-lt);border:1px solid rgba(153,27,27,0.12);border-radius:var(--r);padding:8px;margin-bottom:12px;font-size:11px;line-height:1.6"></div><div class="fs">Optionen</div><div id="ed-options" style="display:flex;flex-direction:column;gap:6px"></div><div id="ed-error" style="display:none;color:var(--neg);font-size:11px;margin-top:8px"></div></div><div class="mfooter"><button class="btn" onclick="cm('m-ed')">Schliessen</button><button class="btn-p" id="btn-ed-save" onclick="documentDecisionTemplate()">Dokumentieren</button></div></div></div>
```

**Wichtige Änderungen:**
- `#ed-drift-info` — leerer Container, wird von `renderDecisionTemplateModal()` befüllt
- `#ed-options` — leerer Container, wird von `renderDecisionTemplateModal()` befüllt
- `#ed-error` — vorhanden, damit `ensureModalError()` ihn nicht doppelt anlegt
- `btn-ed-save` direkt im HTML mit `onclick="documentDecisionTemplate()"` — `initReviewModals()` muss ihn nicht mehr per `setAttribute` nachsetzen (guard bleibt trotzdem drin)

### 2. `getDecisionChoiceMeta(choice, bucket)` erweitern (Zeile 7460)

Ersetze die bestehende Funktion vollständig:

```js
function getDecisionChoiceMeta(choice, bucket) {
  // bucket ist optional: LiveRebalancingBucketResponse (JS-Objekt aus API)
  var assetClass = bucket ? escapeHtml(bucket.asset_class || 'Anlageklasse') : 'Anlageklasse';
  
  // Umschichtungsbetrag in CHF (gerundet auf 10k)
  var rebalAmtChf = bucket && bucket.rebalance_amount_rappen
    ? Math.round(bucket.rebalance_amount_rappen / 100)     // Rappen → CHF
    : null;
  // Teilverkauf = 80% des Umschichtungsbetrags (sofort, Rest via Zuflüsse)
  var partialSaleChf = rebalAmtChf ? Math.round(rebalAmtChf * 0.8 / 1000) * 1000 : null;
  // Runde Umschichtungssumme auf 5k
  var rebalRoundedChf = rebalAmtChf ? Math.round(rebalAmtChf / 5000) * 5000 : null;

  var fmtChf = function(v) {
    if (v == null) return null;
    if (v >= 1000000) return 'CHF ' + (v / 1000000).toFixed(1).replace('.0','') + ' Mio.';
    if (v >= 1000) return 'CHF ' + Math.round(v / 1000) + 'k';
    return 'CHF ' + v;
  };

  var map = {
    option_a: {
      title: 'Option A – Zuflüsse umlenken',
      detail: rebalRoundedChf
        ? fmtChf(rebalRoundedChf) + ' in defensivere Klassen umlenken. Organische Normalisierung 12–18 Monate.'
        : 'Nächste Zuflüsse in defensivere Klassen umlenken. Organische Normalisierung 12–18 Monate.',
      decision: 'Strategie angepasst'
    },
    option_b: {
      title: 'Option B – Teilverkauf ' + assetClass,
      detail: partialSaleChf
        ? 'Teilverkauf ' + assetClass + ' ' + fmtChf(partialSaleChf) + '. Sofortige Normalisierung, Steuerfolgen separat prüfen.'
        : 'Teilverkauf ' + assetClass + '. Sofortige Normalisierung, Steuerfolgen separat prüfen.',
      decision: 'Transaktion empfohlen'
    },
    option_c: {
      title: 'Option C – Drift tolerieren',
      detail: 'Drift für ein weiteres Quartal dokumentiert tolerieren. Kundenkommunikation und schriftliche Bestätigung notwendig.',
      decision: 'Override bestätigt'
    }
  };
  return map[choice] || map.option_a;
}
```

### 3. `renderDecisionTemplateModal(triggerId)` — neue Funktion

Diese Funktion wird von `openDecisionTemplateModal()` aufgerufen. Sie liest `live_rebalancing` und `currentReviewState.triggers` und befüllt `#ed-drift-info` + `#ed-options`.

Füge diese Funktion **direkt nach** `resetDecisionTemplateModal()` (nach Zeile 5527) ein:

```js
function renderDecisionTemplateModal(triggerId) {
  var live = liveRebalancingPayload(strategyState.recommendation);
  
  // Trigger finden (für Trigger-Name und Asset-Class)
  var trigger = null;
  if (triggerId) {
    trigger = (currentReviewState.triggers || []).find(function(t) {
      return String(t.id || '') === String(triggerId || '');
    }) || null;
  }
  
  // Breachenden Bucket ermitteln
  // Priorität: 1) Bucket der zum Trigger-Namen passt, 2) erster breached Bucket, 3) null
  var bucket = null;
  if (live && Array.isArray(live.bucket_drifts)) {
    var breached = live.bucket_drifts.filter(function(b) { return b.breached; });
    if (trigger && trigger.trigger_name) {
      // trigger_name enthält den asset_class-String (wird von review_engine.py so gesetzt)
      var matched = breached.find(function(b) {
        return b.asset_class && b.asset_class.toLowerCase() === (trigger.trigger_name || '').toLowerCase();
      });
      bucket = matched || breached[0] || null;
    } else {
      bucket = breached[0] || null;
    }
  }
  
  // Drift-Info-Box befüllen
  var driftInfo = document.getElementById('ed-drift-info');
  if (driftInfo) {
    if (bucket) {
      var currentPct = (bucket.current_weight_bps / 100).toFixed(1);
      var targetPct  = (bucket.target_weight_bps  / 100).toFixed(1);
      var bandMaxPct = (bucket.band_max_bps        / 100).toFixed(1);
      var driftPp    = (Math.abs(bucket.delta_weight_bps) / 100).toFixed(1);
      var rebalChf   = bucket.rebalance_amount_rappen
        ? formatRappen(bucket.rebalance_amount_rappen) : null;
      var triggerName = trigger ? escapeHtml(trigger.trigger_name || bucket.asset_class) : escapeHtml(bucket.asset_class);
      driftInfo.innerHTML =
        '<strong>' + triggerName + '</strong>: Ist ' + currentPct + '% vs. Soll ' + targetPct + '% '
        + '(Band-Max ' + bandMaxPct + '%). Drift +' + driftPp + ' Prozentpunkte.'
        + (rebalChf ? ' Umschichtungsbedarf: ' + rebalChf + '.' : '');
      driftInfo.style.display = '';
    } else if (trigger) {
      // Trigger vorhanden, aber kein Live-Rebalancing (noch kein Strategie-Run)
      driftInfo.innerHTML = escapeHtml(trigger.trigger_name || 'Markt-Trigger') + ' ausgelöst. Keine Live-Kursdaten verfügbar — Strategie-Run erforderlich.';
      driftInfo.style.display = '';
    } else {
      driftInfo.innerHTML = 'Drift-Daten nicht verfügbar. Bitte Strategie neu berechnen.';
      driftInfo.style.display = '';
    }
  }
  
  // Optionskarten rendern
  var optionsDiv = document.getElementById('ed-options');
  if (optionsDiv) {
    var choices = ['option_a', 'option_b', 'option_c'];
    optionsDiv.innerHTML = '';
    choices.forEach(function(key) {
      var meta = getDecisionChoiceMeta(key, bucket);
      var card = document.createElement('div');
      card.dataset.choice = key;
      card.style.cssText = 'border:1px solid var(--b1);border-radius:var(--r);padding:9px;cursor:pointer';
      card.innerHTML =
        '<div style="font-size:11px;font-weight:500;margin-bottom:3px">'
        + (key === 'option_a' ? '✓ ' : '') + escapeHtml(meta.title) + (key === 'option_a' ? ' (empfohlen)' : '')
        + '</div>'
        + '<div style="font-size:10px;color:var(--n6);line-height:1.4">' + escapeHtml(meta.detail) + '</div>';
      card.onclick = (function(k) { return function() { selectDecisionOption(k); }; })(key);
      optionsDiv.appendChild(card);
    });
  }
  
  // Initial Auswahl hervorheben (option_a)
  selectDecisionOption(currentDecisionChoice);
}
```

**Hilfsfunktion `formatRappen()`** — prüfen ob sie existiert (Zeile ca. 6200-6400), wenn nicht anlegen:
```js
// Nur hinzufügen wenn formatRappen noch nicht existiert
function formatRappen(rappen) {
  var chf = Math.round(rappen / 100);
  if (chf >= 1000000) return 'CHF ' + (chf / 1000000).toFixed(2).replace(/\.?0+$/, '') + ' Mio.';
  if (chf >= 1000)    return 'CHF ' + Math.round(chf / 1000) + '\'000';
  return 'CHF ' + chf;
}
```
→ Vor dem Hinzufügen prüfen: `grep -n "function formatRappen"` — wenn bereits vorhanden, nicht doppeln.

### 4. `openDecisionTemplateModal(triggerId)` erweitern (Zeile 5522)

**Vor:**
```js
function openDecisionTemplateModal(triggerId){
  var ed=document.getElementById('m-ed');
  if(ed)ed.dataset.triggerId=triggerId||'';
  resetDecisionTemplateModal();
  if(ed)ed.classList.add('open');
}
```

**Nach:**
```js
function openDecisionTemplateModal(triggerId){
  // Falls triggerId leer: ersten aktiven Markt-Trigger nehmen
  var resolvedTriggerId = triggerId || '';
  if (!resolvedTriggerId) {
    var firstMarkt = (currentReviewState.triggers || []).find(function(t) {
      return t.trigger_type === 'Markt' && t.status !== 'Erledigt';
    });
    if (firstMarkt) resolvedTriggerId = String(firstMarkt.id || '');
  }
  var ed = document.getElementById('m-ed');
  if (ed) ed.dataset.triggerId = resolvedTriggerId;
  resetDecisionTemplateModal();
  renderDecisionTemplateModal(resolvedTriggerId);
  if (ed) ed.classList.add('open');
}
```

### 5. `initReviewModals()` Guard für `m-ed` (Zeile 5431–5444)

Der bestehende Block in `initReviewModals()` setzt IDs und verdrahtet den Save-Button. Da der Button jetzt direkt im HTML mit `onclick` steht, wird das `setAttribute` zum No-Op (harmlos). Aber der Block ruft auch `ensureModalError('m-ed','ed-error')` auf — das ist jetzt überflüssig, da `#ed-error` im HTML steht. Beide Guards bleiben drin (idempotent), nichts anfassen.

### 6. `om()` guard für `m-ed` (Zeile 5105)

```js
if(id==='m-ed'){
  var modal=document.getElementById('m-ed');
  // ...
}
```
Zeile 5105-5108 prüfen was hier steht. Wenn es ein Redirect oder early-return gibt, muss `openDecisionTemplateModal()` statt `om('m-ed')` verwendet werden. Konkret: alle Stellen wo `om('m-ed')` aufgerufen wird, prüfen ob sie direkt durch `openDecisionTemplateModal(triggerId)` ersetzt werden können.

Grep-Befehl: `grep -n "om('m-ed')\|om(\"m-ed\")" 5eyes_v2.html`

Erwartete Stellen (aus Analyse):
- Zeile 783: `<button ... onclick="om('m-ed')">Entscheidungsvorlage →</button>` — das ist im **statischen Demo-Strip**, der durch `renderReviewAlertStrip()` ersetzt wird. Trotzdem: auf `onclick="openDecisionTemplateModal('')"` ändern.
- Zeile 1112: `rv-alert-strip` static placeholder — gleiche Änderung
- Zeile 1150: trigger list button — auf `openDecisionTemplateModal('')` ändern
- Zeile 1173: strip button — auf `openDecisionTemplateModal('')` ändern

Alle diese `om('m-ed')` Aufrufe ersetzen durch `openDecisionTemplateModal('')` — die Funktion löst selbst den Trigger-Lookup auf.

### 7. `selectDecisionOption()` — Kompatibilität sicherstellen

`selectDecisionOption()` (Zeile 5502) liest `ed.querySelectorAll('[data-choice]')`. Da `#ed-options` jetzt dynamisch gerendert wird und `data-choice` auf den Karten steht, funktioniert das selector-basierte Highlighting weiterhin ohne Änderung. ✓

---

## Tests (Backend: keine / Frontend: manuell)

Da es ausschliesslich Frontend-Änderungen sind, gibt es keine neuen Backend-Tests. Manuelle Test-Checkliste:

### Test 1 — Demo-Modus: Kein Strategie-Run
- Neuen Client anlegen (Demo)
- `openDecisionTemplateModal('')` aufrufen (via Trigger-Button)
- Erwartet: `#ed-drift-info` zeigt "Drift-Daten nicht verfügbar. Bitte Strategie neu berechnen."
- Erwartet: `#ed-options` zeigt 3 Karten ohne CHF-Beträge (generische Texte)
- "Dokumentieren" klicken → Demo-Feedback, kein API-Call

### Test 2 — Live-Mandat mit Strategie-Run + Drift
- Echtes Mandat mit Strategie-Run (Drift vorhanden, `breached_asset_classes` nicht leer)
- `openDecisionTemplateModal(triggerId)` mit einem Markt-Trigger-ID aufrufen
- Erwartet: `#ed-drift-info` zeigt echte Zahlen (Ist/Soll %, Drift pp, CHF-Umschichtungsbedarf)
- Erwartet: Option A zeigt gerundeten CHF-Betrag; Option B zeigt 80% davon als Teilverkauf
- Erwartet: Option C zeigt generischen Text (keine CHF)
- Option B auswählen → Highlight wechselt korrekt
- "Dokumentieren" → POST `/mandates/{id}/advisory-log` + PUT `.../triggers/{id}/resolve` → Modal schliesst

### Test 3 — Live-Mandat mit Strategie-Run, kein Drift
- Mandat ohne breached Klassen
- Trigger-Button öffnet Modal
- Erwartet: `#ed-drift-info` zeigt "Drift-Daten nicht verfügbar..." oder findet keinen Bucket
- Optionen werden trotzdem angezeigt (mit generischen Texten, kein Crash)

### Test 4 — `om('m-ed')` Aufrufe (alte Buttons)
- Alle geänderten Buttons (`om('m-ed')` → `openDecisionTemplateModal('')`) testen
- Erwartet: Modal öffnet mit automatisch gefundenem Trigger (oder leerem State)

### Test 5 — `selectDecisionOption()` nach `renderDecisionTemplateModal()`
- Modal öffnen → option_a ist highlighted
- option_b klicken → option_b ist highlighted, option_a nicht mehr
- option_a klicken → zurück zu option_a
- "Dokumentieren" → sendet `decision: 'Transaktion empfohlen'` wenn option_b gewählt

---

## Wichtige Invarianten

1. **`documentDecisionTemplate()` NICHT anfassen** — ist fertig und korrekt
2. **`resetDecisionTemplateModal()` NICHT anfassen** — sie setzt `currentDecisionChoice='option_a'` und ruft `selectDecisionOption()`, das reicht
3. **`selectDecisionOption()` NICHT anfassen** — liest `[data-choice]` dynamisch, kompatibel mit neuem DOM
4. **`initReviewModals()` minimal anfassen** — bestehende Guards bleiben, werden idempotent
5. **Demo-Modus MUSS funktionieren** — wenn `isDemoMandateId(mid)`: `documentDecisionTemplate()` macht Demo-Feedback und kein API-Call (bereits so implementiert)
6. **Null-Safety überall** — `live_rebalancing` kann null sein (kein Run), `bucket` kann null sein, `trigger` kann null sein → alle drei Fälle in `renderDecisionTemplateModal()` behandeln
7. **`escapeHtml()` für alle User-/API-Daten** — trigger_name, asset_class, etc.

---

## Dateien die geändert werden

| Datei | Art der Änderung |
|---|---|
| `5eyes-electron/frontend/5eyes_v2.html` | Modal-HTML (Zeile 1414), `getDecisionChoiceMeta()` (Zeile 7460), neue Funktion `renderDecisionTemplateModal()`, `openDecisionTemplateModal()` (Zeile 5522), `om('m-ed')` Aufrufe (~4 Stellen) |

**Keine anderen Dateien.** Backend ist vollständig.

---

## Codex-Anweisungen

1. Lese `5eyes_v2.html` vollständig (es ist eine Datei, ~8000 Zeilen)
2. Ersetze den statischen Modal-Body von `#m-ed` (Zeile 1414) mit dem oben gezeigten neuen HTML
3. Ersetze `getDecisionChoiceMeta(choice)` (Zeile 7460) durch die neue Version mit `bucket`-Parameter
4. Füge `renderDecisionTemplateModal(triggerId)` direkt nach `resetDecisionTemplateModal()` (nach Zeile 5527) ein
5. Ersetze `openDecisionTemplateModal(triggerId)` (Zeile 5522) durch die neue Version
6. Prüfe ob `formatRappen()` bereits existiert (`grep -n "function formatRappen"`); falls nicht, füge sie hinzu
7. Ersetze alle `om('m-ed')` in HTML-onclick-Attributen durch `openDecisionTemplateModal('')`
8. Führe `node --check 5eyes_v2.html` aus — kein Syntax-Fehler erlaubt
9. Manuell testen: Modal öffnen in Demo-Modus → keine JS-Fehler, generische Texte erscheinen

**Kein Backend-Code ändern. Keine Tests schreiben (rein Frontend).**
