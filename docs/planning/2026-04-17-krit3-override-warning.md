# Spec — KRIT-3: Override-Warnung bei Profil-Sprung > 2 Bänder

## Meta
- Titel: FIDLEG-konforme Warnung beim Profil-Override
- Datum: 2026-04-17
- Owner: Emanuele
- Branch-Vorschlag: `codex/krit3-override-warning`
- Priorität: KRITISCH — FIDLEG Art. 9/10 verlangt dokumentierte Warnung bei Profil-Überschreitung

---

## Problem

Der Override-Modal sendet `override_warning_delivered: true` **immer**, ohne dass
dem Berater eine tatsächliche Warnung angezeigt wird. Ausserdem wird
`override_client_confirmed: true` hardcodiert — ohne je die tatsächliche
Kundenbestätigung einzuholen.

Dies bedeutet: Ein Berater kann ein Profil von Kapitalschutz auf Aktien (5 Bänder)
hochstufen ohne jede Warnung, und die Datenbank zeigt trotzdem `warning_delivered=1`.

Dies ist ein Compliance-Verstoss gegen FIDLEG Art. 9 Abs. 2.

### Zweiter Bug — Backend kein Upper-Bound

`RiskAssessmentOverride` in `schemas/profiling.py` validiert `override_score_x10`
nicht gegen eine Obergrenze. Ein fehlerhafter Client könnte `override_score_x10=9999`
senden.

---

## Scope

Zwei Dateien:
1. `5eyes-electron/frontend/5eyes_v2.html` — Override-Modal + `applyOv()` Funktion
2. `5eyes-backend/schemas/profiling.py` — `RiskAssessmentOverride` Validator

---

## Logik: Wann wird eine Warnung angezeigt?

Jeder Score 1–10 gehört zu einem von 6 Bändern:

```javascript
// Index 0 ungenutzt, Index 1–10 = Score-Werte
var _bandOf = [0, 0, 0, 1, 1, 2, 2, 3, 3, 4, 5];
// Band 0 = Kapitalschutz, 1 = Defensiv, 2 = Ausgewogen,
// 3 = Wachstumsorientiert, 4 = Dynamisch, 5 = Aktien
```

**Warnung erforderlich wenn:** `_bandOf[newScore] - _bandOf[computedScore] >= 2`
(Aufwärts-Sprung von 2 oder mehr Bändern)

Beispiele:
- Ausgewogen (5) → Wachstumsorientiert (7): delta = 3-2 = 1 Band → KEIN Warning
- Defensiv (3) → Wachstumsorientiert (7): delta = 3-1 = 2 Bänder → WARNING
- Kapitalschutz (2) → Aktien (10): delta = 5-0 = 5 Bänder → WARNING

---

## Änderung 1 — Override-Modal HTML: Warning-Box hinzufügen

**Grep zum Lokalisieren:**
```
grep -n "ov-error\|ov-reason\|Override bestätigen" 5eyes-electron/frontend/5eyes_v2.html
```
Erwartet: Treffer ~Zeile 4832, 4831, 4837.

Nach dem `<div id="ov-error" ...>` (Zeile ~4832) und vor dem `</div></div>` (Ende frow),
einen neuen Warning-Block und eine Checkbox einfügen.

**Alt (die gesamte frow für Begründung — Zeile ~4829 bis ~4834):**
```html
      <div class="frow"><div class="fg">
        <label class="fl">Begründung (FIDLEG-Pflicht)</label>
        <textarea class="fi" id="ov-reason" rows="2" placeholder="Kunde wünscht explizit höheres Risiko..." style="resize:none;min-height:55px"></textarea>
        <div id="ov-error" style="display:none;font-size:10px;color:var(--neg);margin-top:4px">Bitte Begründung erfassen (FIDLEG-Pflicht).</div>
      </div></div>
```

**Neu:**
```html
      <div class="frow"><div class="fg">
        <label class="fl">Begründung (FIDLEG-Pflicht)</label>
        <textarea class="fi" id="ov-reason" rows="2" placeholder="Kunde wünscht explizit höheres Risiko..." style="resize:none;min-height:55px"></textarea>
        <div id="ov-error" style="display:none;font-size:10px;color:var(--neg);margin-top:4px">Bitte Begründung erfassen (FIDLEG-Pflicht).</div>
      </div></div>
      <div id="ov-warn-block" style="display:none;margin:8px 0;padding:10px 12px;background:rgba(201,68,68,0.10);border:1px solid rgba(201,68,68,0.4);border-radius:var(--r)">
        <div style="font-size:11px;font-weight:600;color:var(--neg);margin-bottom:6px">&#9888; FIDLEG-Warnung: Erhebliche Profil-Überschreitung</div>
        <div style="font-size:11px;color:var(--n6);margin-bottom:8px">Das neue Profil liegt 2 oder mehr Risikostufen über dem berechneten Profil. Der Kunde muss ausdrücklich auf das erhöhte Verlustrisiko hingewiesen werden (FIDLEG Art. 9 Abs. 2).</div>
        <label style="display:flex;align-items:flex-start;gap:8px;cursor:pointer">
          <input type="checkbox" id="ov-warn-confirm" style="margin-top:2px" onchange="updOvWarnBtn()">
          <span style="font-size:11px;color:var(--n6)">Ich bestätige, dass ich den Kunden über das erhöhte Risiko informiert habe und der Kunde schriftlich zugestimmt hat.</span>
        </label>
      </div>
```

---

## Änderung 2 — `updOv()` Funktion: Warning-Block ein-/ausblenden

**Grep zum Lokalisieren:**
```
grep -n "function updOv" 5eyes-electron/frontend/5eyes_v2.html
```
Erwartet: Zeile ~4948.

**Alt:**
```javascript
function updOv(v){
  var d=document.getElementById('ov-disp');var n=document.getElementById('ov-name');
  if(d)d.textContent=v+'/10'; if(n)n.textContent=_pnames[parseInt(v)]||'';
}
```

**Neu:**
```javascript
var _bandOf=[0,0,0,1,1,2,2,3,3,4,5];
function updOv(v){
  var d=document.getElementById('ov-disp');var n=document.getElementById('ov-name');
  if(d)d.textContent=v+'/10'; if(n)n.textContent=_pnames[parseInt(v)]||'';
  var risk=currentPersistedRiskForMandate(getActiveMandateId());
  var computedScore=risk?Math.round(Number(risk.final_score_x10||0)/10):0;
  var newScore=parseInt(v)||1;
  var delta=_bandOf[newScore]-_bandOf[Math.max(1,Math.min(10,computedScore))];
  var wb=document.getElementById('ov-warn-block');
  var wc=document.getElementById('ov-warn-confirm');
  if(wb){wb.style.display=delta>=2?'block':'none';}
  if(wc&&delta<2){wc.checked=false;}
  updOvWarnBtn();
}
function updOvWarnBtn(){
  var v=parseInt((document.getElementById('ov-sl')||{value:7}).value)||7;
  var risk=currentPersistedRiskForMandate(getActiveMandateId());
  var computedScore=risk?Math.round(Number(risk.final_score_x10||0)/10):0;
  var delta=_bandOf[v]-_bandOf[Math.max(1,Math.min(10,computedScore))];
  var wc=document.getElementById('ov-warn-confirm');
  var btn=document.querySelector('#m-overr .btn-g');
  if(btn){btn.disabled=(delta>=2&&(!wc||!wc.checked));}
}
```

---

## Änderung 3 — `openOverrideModal()`: Warning beim Öffnen zurücksetzen

**Grep zum Lokalisieren:**
```
grep -n "function openOverrideModal" 5eyes-electron/frontend/5eyes_v2.html
```
Erwartet: Zeile ~4952.

**Alt (letzte 3 Zeilen der Funktion vor der `om()`-Zeile):**
```javascript
  var re=document.getElementById('ov-reason');if(re)re.value='';
  var er=document.getElementById('ov-error');if(er)er.style.display='none';
  if(btn){btn.disabled=false;btn.textContent='Override bestätigen & protokollieren';}
  updOv(score);
  om('m-overr');
```

**Neu:**
```javascript
  var re=document.getElementById('ov-reason');if(re)re.value='';
  var er=document.getElementById('ov-error');if(er)er.style.display='none';
  var wb=document.getElementById('ov-warn-block');if(wb)wb.style.display='none';
  var wc=document.getElementById('ov-warn-confirm');if(wc)wc.checked=false;
  if(btn){btn.disabled=false;btn.textContent='Override bestätigen & protokollieren';}
  updOv(score);
  om('m-overr');
```

---

## Änderung 4 — `applyOv()`: warning_delivered nur true wenn Warnung tatsächlich bestätigt

**Grep zum Lokalisieren:**
```
grep -n "override_warning_delivered\|override_client_confirmed" 5eyes-electron/frontend/5eyes_v2.html
```
Erwartet: Zeile ~4987-4988.

**Alt:**
```javascript
    var saved=await API.post('/mandates/'+mid+'/risk-assessments/'+raId+'/override',{
      override_score_x10:v*10,override_profile:n,override_reason:reason,
      override_client_confirmed:true,override_warning_delivered:true
    });
```

**Neu:**
```javascript
    var risk2=currentPersistedRiskForMandate(mid);
    var computedScore2=risk2?Math.round(Number(risk2.final_score_x10||0)/10):0;
    var delta2=_bandOf[v]-_bandOf[Math.max(1,Math.min(10,computedScore2))];
    var wc2=document.getElementById('ov-warn-confirm');
    var warnConfirmed=delta2>=2?(wc2&&wc2.checked):false;
    var saved=await API.post('/mandates/'+mid+'/risk-assessments/'+raId+'/override',{
      override_score_x10:v*10,override_profile:n,override_reason:reason,
      override_client_confirmed:warnConfirmed,override_warning_delivered:warnConfirmed
    });
```

---

## Änderung 5 — Backend Schema: override_score_x10 Obergrenze (schemas/profiling.py)

**Grep zum Lokalisieren:**
```
grep -n "override_score_x10\|RiskAssessmentOverride" 5eyes-backend/schemas/profiling.py
```
Erwartet: Zeile ~79-88.

**Alt:**
```python
class RiskAssessmentOverride(BaseModel):
    override_score_x10: int
    override_profile: Literal[
        "Kapitalschutz", "Defensiv", "Ausgewogen",
        "Wachstumsorientiert", "Dynamisch", "Aktien"
    ]
    override_reason: str  # NOT NULL per FIDLEG
    override_client_confirmed: bool = False
    override_warning_delivered: bool = False
    override_warning_document_id: Optional[str] = None
```

**Neu:**
```python
class RiskAssessmentOverride(BaseModel):
    override_score_x10: int
    override_profile: Literal[
        "Kapitalschutz", "Defensiv", "Ausgewogen",
        "Wachstumsorientiert", "Dynamisch", "Aktien"
    ]
    override_reason: str  # NOT NULL per FIDLEG
    override_client_confirmed: bool = False
    override_warning_delivered: bool = False
    override_warning_document_id: Optional[str] = None

    @model_validator(mode="after")
    def validate_override_score(self):
        assert 10 <= self.override_score_x10 <= 100, \
            "override_score_x10 muss zwischen 10 (Score 1) und 100 (Score 10) liegen"
        return self
```

**Hinweis**: Der Import `model_validator` ist bereits in dieser Datei vorhanden (Zeile 1).

---

## Implementierungs-Checkliste für Codex

1. HTML: Warning-Block `<div id="ov-warn-block">` nach `<div id="ov-error">` einfügen
2. JS: `_bandOf`-Array vor `updOv()` definieren
3. JS: `updOv()` um Warning-Logik erweitern
4. JS: neue Funktion `updOvWarnBtn()` hinzufügen (direkt nach `updOv`)
5. JS: `openOverrideModal()` — Warning zurücksetzen beim Öffnen
6. JS: `applyOv()` — `override_warning_delivered` und `override_client_confirmed` dynamisch berechnen
7. Python: `RiskAssessmentOverride` — `@model_validator` für override_score_x10 Bounds hinzufügen
8. Verifikation Frontend: `node --check 5eyes-electron/frontend/5eyes_v2.html` → 0 Fehler
9. Verifikation Backend: `python -c "from schemas.profiling import RiskAssessmentOverride; print('OK')"` → OK

---

## Akzeptanzkriterien

1. Slider auf Score 7 (Wachstumsorientiert) bei berechnetem Score 5 (Ausgewogen): delta=1 → kein Warning, Button enabled
2. Slider auf Score 7 (Wachstumsorientiert) bei berechnetem Score 3 (Defensiv): delta=2 → Warning sichtbar, Button disabled bis Checkbox aktiviert
3. Slider auf Score 10 (Aktien) bei Score 1 (Kapitalschutz): delta=5 → Warning sichtbar, Button disabled bis Checkbox aktiviert
4. Checkbox aktiviert → Button wird enabled
5. API-Call mit Checkbox aktiviert: `override_warning_delivered=true, override_client_confirmed=true`
6. API-Call ohne Warning (delta<2): `override_warning_delivered=false, override_client_confirmed=false`
7. Backend lehnt `override_score_x10=0` ab (ValidationError)
8. Backend lehnt `override_score_x10=110` ab (ValidationError)
9. Backend akzeptiert `override_score_x10=50` ✓
