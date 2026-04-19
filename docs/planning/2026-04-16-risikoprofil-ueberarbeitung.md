# Spec — Risikoprofil Überarbeitung nach SwissLife WM W305.03

## Meta
- Titel: Risikoprofil Überarbeitung (Kenntnisse & Erfahrungen + SwissLife-Scoring)
- Datum: 2026-04-16
- Owner: Emanuele
- Branch-Vorschlag: `codex/rp-ueberarbeitung`
- Referenz-Bilder: `C:\Users\Emanuele\Desktop\Consulting Firma\3eyes\Optimierungen\neues Risikoprofil\`
  - `Seite 1 neu.jpg` → Kenntnisse & Erfahrungen (keine Punkte, Compliance)
  - `Seite 2 neu.jpg` → Risikofähigkeit F1–F5 mit exakter Punkteverteilung
  - `Seite 3 neu.jpg` → Anlagehorizont F6 + Risikobereitschaft F7–F9

---

## Warum diese Spec existiert — Fachlicher Kontext

Das bestehende Risikoprofil-Formular in 5eyes basiert auf einem früheren internen Entwurf.
Der offizielle SwissLife Wealth Managers Fragebogen W305.03 (Eignungsprüfung, 3 Seiten) ist das
einzige FIDLEG-konforme Dokument das im Kundengespräch eingesetzt wird.

5eyes muss mit diesem Formular übereinstimmen:
- Dieselben Fragen, dieselbe Struktur, dieselbe Punkteverteilung
- Das Dokument das 5eyes ausdruckt muss dem offiziellen Formular entsprechen
- Prüfer, Compliance-Officer oder Kunde dürfen keinen Unterschied sehen

**Drei Hauptänderungen:**
1. Kenntnisse & Erfahrungen (Seite 1) → neue 2-Spalten-Tabellenstruktur
2. Risikofähigkeit (Seite 2) → Brackets statt Freitext, korrekte Punkteverteilung
3. Neue Frage F2 (Herkunft) → rein informativ, keine Punkte

---

## Scoring-Formel — Begründung der Änderung

### Altes System (wird ERSETZT)
```
surplusPoints = mapSurplusPoints(income, obligations)  → 0/1/2/3/4 (ratio-basiert)
obligationPoints = 0  (IMMER 0 — wird ignoriert!)
savingsPoints = RISK_SAVINGS_POINTS[idx]  → [0, 4, 8, 12]  (4 Optionen)
wealthPoints = normalizeRiskPoints(RISK_RESERVE_POINTS[idx], 9, 12)  → Liquiditätsreserve
capacityTotal (max): 4 + 0 + 12 + 12 = 28 Punkte
```

**Problem:** Der ratio-basierte Surplus-Ansatz wirft Information weg.
- Person A: 20k Einkommen / 18k Verpflichtungen → Ratio 10% → 1 Punkt
- Person B: 6k Einkommen / 5.4k Verpflichtungen → Ratio 10% → 1 Punkt
- Im offiziellen Formular: Person A = 4 + 0 = 4 Punkte, Person B = 0 + 1 = 1 Punkt
- Die alten Werte stimmen nicht mit dem Compliance-Dokument überein

### Neues System (nach W305.03)
```
F1 income_points = RISK_INCOME_POINTS[incomeIdx]  → [0, 1, 2, 3, 4]
F3 obligations_points = RISK_OBLIGATIONS_POINTS[obligIdx]  → [4, 3, 2, 1, 0] (INVERS!)
F4 wealth_points = RISK_WEALTH_POINTS[wealthIdx]  → [0, 3, 6, 9, 12]
F5 savings_points = RISK_SAVINGS_POINTS[savingsIdx]  → [0, 3, 6, 9, 12]
capacityTotal (max): 4 + 4 + 12 + 12 = 32 Punkte (bereits in Matrix abgedeckt!)
```

**Warum besser:**
- F1 und F3 sind unabhängige Dimensionen → BEIDE gehen in den Score ein
- Bracket-basiert → stimmt 1:1 mit dem offiziellen Formular überein
- Max 32 Punkte → der bestehende Backend `CAPACITY_TOTAL_TO_PROFILE` reicht bis 32, keine Änderung
- `MIN(capScore, willScore)` bleibt unverändert → FIDLEG-konform

**WICHTIG: `map_surplus_points()` in `risk_scoring.py` NICHT löschen!**
Sie ist in Tests vorhanden. Einfach nicht mehr aufrufen.

---

## Scope

### Was sich ändert
1. `models/profiling.py` — 3 neue JSON-Felder in `RiskAssessment`
2. `schemas/profiling.py` — Create + Response erweitern
3. `database.py` — 3 neue Spalten via `ensure_runtime_columns()`
4. `5eyes_v2.html` — JS-Konstanten, HTML Tab 1, HTML Tab 2, 5 Funktionen, PDF-Sektion

### Was NICHT ändert
- `risk_scoring.py` → Keine Änderungen! `compute_scores()` nimmt dieselben 4 Parameter
- `routers/profiling.py` → Keine Änderungen (die 3 neuen JSON-Felder sind optional)
- Tab 3 (Risikobereitschaft) → Q9/Q10/Q11 bleiben unverändert
- Design / Layout / Farben → bleibt wie bisher
- Profil-Labels (Kapitalschutz, Defensiv, Ausgewogen, ...) → bleiben
- `MIN(cap, will)` Formel → bleibt

---

## Betroffene Dateien

| Datei | Art |
|---|---|
| `5eyes-backend/models/profiling.py` | ÄNDERN |
| `5eyes-backend/schemas/profiling.py` | ÄNDERN |
| `5eyes-backend/database.py` | ÄNDERN |
| `5eyes-electron/frontend/5eyes_v2.html` | ÄNDERN (HTML + JS) |

---

## Backend — Schritt 1: `models/profiling.py`

### Grep um Einfügeposition zu finden
```
grep -n "override_warning_document_id" 5eyes-backend/models/profiling.py
```
Ergibt Zeile mit `override_warning_document_id = Column(String)`.

### Einfügen — nach `override_warning_document_id`:
```python
    # Kenntnisse & Erfahrungen (SwissLife W305.03 Seite 1) — kein Scoring, nur Compliance
    knowledge_services_json = Column(String)   # JSON: {"Vermögensverwaltung":{"known":0,"informed":1}, ...}
    knowledge_instruments_json = Column(String) # JSON: {"Anlagefonds":{"known":1,"informed":1}, ...}
    # Herkunft des Einkommens (Frage 2 — informativ, kein Score)
    income_sources_json = Column(String)        # JSON: ["Berufliche Tätigkeit", "Rente"]
```

---

## Backend — Schritt 2: `schemas/profiling.py`

### In `RiskAssessmentCreate` (nach `answers: Optional[list[dict]] = None`):
```python
    # Kenntnisse & Erfahrungen (optional, für Compliance-Dokumentation)
    knowledge_services_json: Optional[str] = None
    knowledge_instruments_json: Optional[str] = None
    income_sources_json: Optional[str] = None
```

### In `RiskAssessmentResponse` (nach `answers: list[RiskAssessmentAnswerResponse] = []`):
```python
    knowledge_services_json: Optional[str] = None
    knowledge_instruments_json: Optional[str] = None
    income_sources_json: Optional[str] = None
```

---

## Backend — Schritt 3: `database.py`

### Grep um Einfügeposition zu finden
```
grep -n "correlation_matrix_json" 5eyes-backend/database.py
```
Die Funktion `ensure_runtime_columns()` enthält bereits ALTER TABLE Statements.
Nach dem letzten bestehenden `ensure_column`-Block für `capital_market_assumptions` einfügen:

```python
    # RiskAssessment — Kenntnisse & Erfahrungen (SwissLife W305.03)
    ensure_column(conn, "risk_assessments", "knowledge_services_json", "TEXT")
    ensure_column(conn, "risk_assessments", "knowledge_instruments_json", "TEXT")
    ensure_column(conn, "risk_assessments", "income_sources_json", "TEXT")
```

### Grep um ensure_column-Funktion zu prüfen
```
grep -n "def ensure_column" 5eyes-backend/database.py
```
Falls `ensure_column` nicht existiert, stattdessen:
```python
    for col in ["knowledge_services_json", "knowledge_instruments_json", "income_sources_json"]:
        try:
            conn.execute(text(f"ALTER TABLE risk_assessments ADD COLUMN {col} TEXT"))
        except Exception:
            pass
```

---

## Frontend — Schritt 4: JS-Konstanten aktualisieren

### Grep um Einfügeposition zu finden
```
grep -n "var RISK_HORIZON_OPTIONS" 5eyes-electron/frontend/5eyes_v2.html
```

### RISK_HORIZON_OPTIONS: 4 → 6 Optionen (SwissLife W305.03 Seite 3)
**Alten Block suchen:**
```javascript
var RISK_HORIZON_OPTIONS = [
  {label:'2 bis 3 Jahre', years:2},
  {label:'4 bis 5 Jahre', years:4},
  {label:'8 bis 11 Jahre', years:9},
  {label:'12 Jahre und mehr', years:15}
];
```
**Ersetzen durch:**
```javascript
var RISK_HORIZON_OPTIONS = [
  {label:'Bis 2 Jahre',        years:1},
  {label:'2 bis 3 Jahre',      years:2},
  {label:'3 bis 5 Jahre',      years:4},
  {label:'5 bis 7 Jahre',      years:6},
  {label:'8 bis 11 Jahre',     years:9},
  {label:'Mehr als 12 Jahre',  years:15}
];
```
**Hinweis:** Die Jahren-Werte (1,2,4,6,9,15) entsprechen exakt den Zeilen der `RISK_CAPACITY_MATRIX` und `HORIZON_YEARS` im Backend. Keine Änderung an der Matrix nötig.

### Neue Punkte-Konstanten — nach `var RISK_RESERVE_POINTS`:
**Alten Block suchen:**
```javascript
var RISK_SAVINGS_POINTS = [0, 4, 8, 12];
var RISK_RESERVE_POINTS = [0, 3, 6, 9];
```
**Ersetzen durch:**
```javascript
// F1: Monatliches Einkommen — SwissLife W305.03 Seite 2, Frage 1
// bis 6k=0, 6-9k=1, 9-12k=2, 12-20k=3, >20k=4
var RISK_INCOME_POINTS = [0, 1, 2, 3, 4];

// F3: Monatliche Verpflichtungen — SwissLife W305.03 Seite 2, Frage 3 (INVERS!)
// bis 3k=4, 3-5k=3, 5-8k=2, 8-12k=1, >12k=0
var RISK_OBLIGATIONS_POINTS = [4, 3, 2, 1, 0];

// F4: Freies Vermögen — SwissLife W305.03 Seite 2, Frage 4
// <100k=0, 100-250k=3, 250k-1M=6, 1-2M=9, >2M=12
var RISK_WEALTH_POINTS = [0, 3, 6, 9, 12];

// F5: Sparquote — SwissLife W305.03 Seite 2, Frage 5
// 0%=0, 1-10%=3, 10-25%=6, 25-50%=9, >50%=12
var RISK_SAVINGS_POINTS = [0, 3, 6, 9, 12];

// Legacy — wird nicht mehr für Scoring verwendet, bleibt für Rückwärtskompatibilität
var RISK_RESERVE_POINTS = [0, 3, 6, 9];
```

---

## Frontend — Schritt 5: HTML Tab 1 (r-ke) komplett ersetzen

### Grep um Einfügeposition zu finden
```
grep -n "id=\"r-ke\"" 5eyes-electron/frontend/5eyes_v2.html
```

### Alten Block suchen (vom `<div id="r-ke"` bis zum schliessenden `</div>` vor `<!-- TAB 2`):
**Suchstring (eindeutig):**
```
<div id="r-ke" class="rpanel active">
```
bis:
```
                <!-- TAB 2: RISIKOFÄHIGKEIT -->
```

### Gesamten Tab-1-Block ersetzen durch:
```html
                <!-- TAB 1: KENNTNISSE & ERFAHRUNGEN (SwissLife W305.03 Seite 1) -->
                <!-- Rein dokumentarisch / Compliance — kein Einfluss auf Score -->
                <!-- Referenz-Bild: Seite 1 neu.jpg -->
                <div id="r-ke" class="rpanel active">

                  <!-- TABELLE 1: Finanzdienstleistungen -->
                  <div class="qsec">
                    <div class="ql"><span class="qnum">1</span><span>Mit welchen <strong>Finanzdienstleistungen</strong> haben Sie Kenntnisse und Erfahrungen? <em style="font-size:9px;color:var(--n4)">(Compliance-Dokumentation · kein Score)</em></span></div>
                    <div style="padding-left:24px;margin-top:6px">
                      <div style="display:grid;grid-template-columns:1fr 130px 130px;gap:0;border:1px solid var(--b1);border-radius:var(--r);overflow:hidden;font-size:10px">
                        <div style="padding:5px 8px;background:var(--bg);font-weight:600;color:var(--n5);font-size:9px;text-transform:uppercase;letter-spacing:0.05em;border-bottom:1px solid var(--b1)">Finanzdienstleistung</div>
                        <div style="padding:5px 8px;background:var(--bg);font-weight:600;color:var(--n5);font-size:9px;text-align:center;border-bottom:1px solid var(--b1);border-left:1px solid var(--b1)">Kenntnisse vorhanden</div>
                        <div style="padding:5px 8px;background:var(--bg);font-weight:600;color:var(--n5);font-size:9px;text-align:center;border-bottom:1px solid var(--b1);border-left:1px solid var(--b1)">Aufklärung erhalten</div>
                        <!-- Vermögensverwaltung -->
                        <div style="padding:7px 8px;color:var(--n8);border-bottom:1px solid var(--b1)">Vermögensverwaltung</div>
                        <div style="padding:7px 8px;text-align:center;border-bottom:1px solid var(--b1);border-left:1px solid var(--b1)"><input type="checkbox" class="ke-svc" data-row="Vermögensverwaltung" data-col="known" style="accent-color:var(--g4);width:14px;height:14px;cursor:pointer"></div>
                        <div style="padding:7px 8px;text-align:center;border-bottom:1px solid var(--b1);border-left:1px solid var(--b1)"><input type="checkbox" class="ke-svc" data-row="Vermögensverwaltung" data-col="informed" style="accent-color:var(--g4);width:14px;height:14px;cursor:pointer"></div>
                        <!-- Anlageberatung -->
                        <div style="padding:7px 8px;color:var(--n8);border-bottom:1px solid var(--b1)">Anlageberatung</div>
                        <div style="padding:7px 8px;text-align:center;border-bottom:1px solid var(--b1);border-left:1px solid var(--b1)"><input type="checkbox" class="ke-svc" data-row="Anlageberatung" data-col="known" style="accent-color:var(--g4);width:14px;height:14px;cursor:pointer"></div>
                        <div style="padding:7px 8px;text-align:center;border-bottom:1px solid var(--b1);border-left:1px solid var(--b1)"><input type="checkbox" class="ke-svc" data-row="Anlageberatung" data-col="informed" style="accent-color:var(--g4);width:14px;height:14px;cursor:pointer"></div>
                        <!-- Stiftungsprodukte -->
                        <div style="padding:7px 8px;color:var(--n8)">Stiftungsprodukte (Freizügigkeit oder Säule 3a)</div>
                        <div style="padding:7px 8px;text-align:center;border-left:1px solid var(--b1)"><input type="checkbox" class="ke-svc" data-row="Stiftungsprodukte" data-col="known" style="accent-color:var(--g4);width:14px;height:14px;cursor:pointer"></div>
                        <div style="padding:7px 8px;text-align:center;border-left:1px solid var(--b1)"><input type="checkbox" class="ke-svc" data-row="Stiftungsprodukte" data-col="informed" style="accent-color:var(--g4);width:14px;height:14px;cursor:pointer"></div>
                      </div>
                    </div>
                  </div>

                  <!-- TABELLE 2: Finanzinstrumente -->
                  <div class="qsec">
                    <div class="ql"><span class="qnum">2</span><span>Mit welchen <strong>Finanzinstrumenten</strong> haben Sie Kenntnisse und Erfahrungen? <em style="font-size:9px;color:var(--n4)">(Compliance-Dokumentation · kein Score)</em></span></div>
                    <div style="padding-left:24px;margin-top:6px">
                      <div style="display:grid;grid-template-columns:1fr 130px 130px;gap:0;border:1px solid var(--b1);border-radius:var(--r);overflow:hidden;font-size:10px">
                        <div style="padding:5px 8px;background:var(--bg);font-weight:600;color:var(--n5);font-size:9px;text-transform:uppercase;letter-spacing:0.05em;border-bottom:1px solid var(--b1)">Finanzinstrument</div>
                        <div style="padding:5px 8px;background:var(--bg);font-weight:600;color:var(--n5);font-size:9px;text-align:center;border-bottom:1px solid var(--b1);border-left:1px solid var(--b1)">Kenntnisse vorhanden</div>
                        <div style="padding:5px 8px;background:var(--bg);font-weight:600;color:var(--n5);font-size:9px;text-align:center;border-bottom:1px solid var(--b1);border-left:1px solid var(--b1)">Aufklärung erhalten</div>
                        <div style="padding:7px 8px;color:var(--n8);border-bottom:1px solid var(--b1)">Anlagefonds (Kollektive Kapitalanlagen)</div>
                        <div style="padding:7px 8px;text-align:center;border-bottom:1px solid var(--b1);border-left:1px solid var(--b1)"><input type="checkbox" class="ke-ins" data-row="Anlagefonds" data-col="known" style="accent-color:var(--g4);width:14px;height:14px;cursor:pointer"></div>
                        <div style="padding:7px 8px;text-align:center;border-bottom:1px solid var(--b1);border-left:1px solid var(--b1)"><input type="checkbox" class="ke-ins" data-row="Anlagefonds" data-col="informed" style="accent-color:var(--g4);width:14px;height:14px;cursor:pointer"></div>
                        <div style="padding:7px 8px;color:var(--n8);border-bottom:1px solid var(--b1)">Aktien (Beteiligungspapiere)</div>
                        <div style="padding:7px 8px;text-align:center;border-bottom:1px solid var(--b1);border-left:1px solid var(--b1)"><input type="checkbox" class="ke-ins" data-row="Aktien" data-col="known" style="accent-color:var(--g4);width:14px;height:14px;cursor:pointer"></div>
                        <div style="padding:7px 8px;text-align:center;border-bottom:1px solid var(--b1);border-left:1px solid var(--b1)"><input type="checkbox" class="ke-ins" data-row="Aktien" data-col="informed" style="accent-color:var(--g4);width:14px;height:14px;cursor:pointer"></div>
                        <div style="padding:7px 8px;color:var(--n8);border-bottom:1px solid var(--b1)">Obligationen</div>
                        <div style="padding:7px 8px;text-align:center;border-bottom:1px solid var(--b1);border-left:1px solid var(--b1)"><input type="checkbox" class="ke-ins" data-row="Obligationen" data-col="known" style="accent-color:var(--g4);width:14px;height:14px;cursor:pointer"></div>
                        <div style="padding:7px 8px;text-align:center;border-bottom:1px solid var(--b1);border-left:1px solid var(--b1)"><input type="checkbox" class="ke-ins" data-row="Obligationen" data-col="informed" style="accent-color:var(--g4);width:14px;height:14px;cursor:pointer"></div>
                        <div style="padding:7px 8px;color:var(--n8);border-bottom:1px solid var(--b1)">Geldmarktprodukte</div>
                        <div style="padding:7px 8px;text-align:center;border-bottom:1px solid var(--b1);border-left:1px solid var(--b1)"><input type="checkbox" class="ke-ins" data-row="Geldmarktprodukte" data-col="known" style="accent-color:var(--g4);width:14px;height:14px;cursor:pointer"></div>
                        <div style="padding:7px 8px;text-align:center;border-bottom:1px solid var(--b1);border-left:1px solid var(--b1)"><input type="checkbox" class="ke-ins" data-row="Geldmarktprodukte" data-col="informed" style="accent-color:var(--g4);width:14px;height:14px;cursor:pointer"></div>
                        <div style="padding:7px 8px;color:var(--n8);border-bottom:1px solid var(--b1)">Immobilien</div>
                        <div style="padding:7px 8px;text-align:center;border-bottom:1px solid var(--b1);border-left:1px solid var(--b1)"><input type="checkbox" class="ke-ins" data-row="Immobilien" data-col="known" style="accent-color:var(--g4);width:14px;height:14px;cursor:pointer"></div>
                        <div style="padding:7px 8px;text-align:center;border-bottom:1px solid var(--b1);border-left:1px solid var(--b1)"><input type="checkbox" class="ke-ins" data-row="Immobilien" data-col="informed" style="accent-color:var(--g4);width:14px;height:14px;cursor:pointer"></div>
                        <div style="padding:7px 8px;color:var(--n8);border-bottom:1px solid var(--b1)">Infrastruktur</div>
                        <div style="padding:7px 8px;text-align:center;border-bottom:1px solid var(--b1);border-left:1px solid var(--b1)"><input type="checkbox" class="ke-ins" data-row="Infrastruktur" data-col="known" style="accent-color:var(--g4);width:14px;height:14px;cursor:pointer"></div>
                        <div style="padding:7px 8px;text-align:center;border-bottom:1px solid var(--b1);border-left:1px solid var(--b1)"><input type="checkbox" class="ke-ins" data-row="Infrastruktur" data-col="informed" style="accent-color:var(--g4);width:14px;height:14px;cursor:pointer"></div>
                        <div style="padding:7px 8px;color:var(--n8)">Edelmetalle</div>
                        <div style="padding:7px 8px;text-align:center;border-left:1px solid var(--b1)"><input type="checkbox" class="ke-ins" data-row="Edelmetalle" data-col="known" style="accent-color:var(--g4);width:14px;height:14px;cursor:pointer"></div>
                        <div style="padding:7px 8px;text-align:center;border-left:1px solid var(--b1)"><input type="checkbox" class="ke-ins" data-row="Edelmetalle" data-col="informed" style="accent-color:var(--g4);width:14px;height:14px;cursor:pointer"></div>
                      </div>
                    </div>
                  </div>

                </div>
```

---

## Frontend — Schritt 6: HTML Tab 2 (r-rf) komplett ersetzen

### Grep um Einfügeposition zu finden
```
grep -n "id=\"r-rf\"" 5eyes-electron/frontend/5eyes_v2.html
```

### Alten Block suchen (von `<div id="r-rf"` bis `<!-- TAB 3`):
**Suchstring (eindeutig):**
```
<!-- TAB 2: RISIKOFÄHIGKEIT -->
```

### Gesamten Tab-2-Block ersetzen durch:
```html
                <!-- TAB 2: RISIKOFÄHIGKEIT (SwissLife W305.03 Seite 2) -->
                <!-- Referenz-Bild: Seite 2 neu.jpg — exakte Punkteverteilung -->
                <div id="r-rf" class="rpanel">

                  <!-- F1: Regelmässiges Einkommen (monatlich, Brackets) — Punkte: 0/1/2/3/4 -->
                  <div class="qsec">
                    <div class="ql"><span class="qnum">3</span><span>Regelmässiges Einkommen – Wie hoch ist Ihr regelmässiges Bruttoeinkommen pro Monat? <em style="font-size:9px;color:var(--n4)">(Erwerbstätigkeit, Miete, Rente, Kapitalerträge etc.)</em></span></div>
                    <div class="qopts">
                      <div class="qopt" onclick="sq(this,'rf-income')"><div class="qrad"></div><span class="qtxt">Bis CHF 6'000</span><span class="qpts">0 Pkt.</span></div>
                      <div class="qopt" onclick="sq(this,'rf-income')"><div class="qrad"></div><span class="qtxt">CHF 6'000 bis 9'000</span><span class="qpts">1 Pkt.</span></div>
                      <div class="qopt" onclick="sq(this,'rf-income')"><div class="qrad"></div><span class="qtxt">CHF 9'000 bis 12'000</span><span class="qpts">2 Pkt.</span></div>
                      <div class="qopt" onclick="sq(this,'rf-income')"><div class="qrad"></div><span class="qtxt">CHF 12'000 bis 20'000</span><span class="qpts">3 Pkt.</span></div>
                      <div class="qopt" onclick="sq(this,'rf-income')"><div class="qrad"></div><span class="qtxt">Über CHF 20'000</span><span class="qpts">4 Pkt.</span></div>
                    </div>
                  </div>

                  <!-- F2: Herkunft des Einkommens — NUR INFORMATIV, kein Score (Seite 2 W305.03) -->
                  <div class="qsec">
                    <div class="ql"><span class="qnum">4</span><span>Herkunft des Einkommens – Woher stammt Ihr regelmässiges Einkommen? <em style="font-size:9px;color:var(--n4)">(Mehrfachauswahl · informativ · kein Score)</em></span></div>
                    <div class="qcbs">
                      <div class="qcb" onclick="this.classList.toggle('sel')"><div class="qbox"></div>Berufliche Tätigkeit (selbstständig oder unselbstständig)</div>
                      <div class="qcb" onclick="this.classList.toggle('sel')"><div class="qbox"></div>Rente</div>
                      <div class="qcb" onclick="this.classList.toggle('sel')"><div class="qbox"></div>Vermietung von Liegenschaften</div>
                      <div class="qcb" onclick="this.classList.toggle('sel')"><div class="qbox"></div>Erträgen aus Anlagen</div>
                      <div class="qcb" onclick="this.classList.toggle('sel')"><div class="qbox"></div>Sonstige Quellen</div>
                    </div>
                  </div>

                  <!-- F3: Finanzielle Verpflichtungen (monatlich, Brackets, INVERS) — Punkte: 4/3/2/1/0 -->
                  <div class="qsec">
                    <div class="ql"><span class="qnum">5</span><span>Finanzielle Verpflichtungen – Wie hoch sind Ihre aktuellen und künftig absehbaren finanziellen Verpflichtungen pro Monat? <em style="font-size:9px;color:var(--n4)">(Miete, Hypothek, Krankenkasse, Unterhalt etc.)</em></span></div>
                    <div class="qopts">
                      <div class="qopt" onclick="sq(this,'rf-oblig')"><div class="qrad"></div><span class="qtxt">Bis CHF 3'000</span><span class="qpts">4 Pkt.</span></div>
                      <div class="qopt" onclick="sq(this,'rf-oblig')"><div class="qrad"></div><span class="qtxt">CHF 3'000 bis 5'000</span><span class="qpts">3 Pkt.</span></div>
                      <div class="qopt" onclick="sq(this,'rf-oblig')"><div class="qrad"></div><span class="qtxt">CHF 5'000 bis 8'000</span><span class="qpts">2 Pkt.</span></div>
                      <div class="qopt" onclick="sq(this,'rf-oblig')"><div class="qrad"></div><span class="qtxt">CHF 8'000 bis 12'000</span><span class="qpts">1 Pkt.</span></div>
                      <div class="qopt" onclick="sq(this,'rf-oblig')"><div class="qrad"></div><span class="qtxt">Über CHF 12'000</span><span class="qpts">0 Pkt.</span></div>
                    </div>
                  </div>

                  <!-- F4: Freies Vermögen (Brackets) — Punkte: 0/3/6/9/12 -->
                  <div class="qsec">
                    <div class="ql"><span class="qnum">6</span><span>Vermögen – Wie hoch ist Ihr frei verfügbares Vermögen, welches Sie nicht zur Deckung von aktuellen oder zukünftigen finanziellen Verpflichtungen benötigen? <em style="font-size:9px;color:var(--n4)">(Kontoguthaben, Wertschriften — ohne beabsichtigte Investition)</em></span></div>
                    <div class="qopts">
                      <div class="qopt" onclick="sq(this,'rf-wealth')"><div class="qrad"></div><span class="qtxt">Bis CHF 100'000</span><span class="qpts">0 Pkt.</span></div>
                      <div class="qopt" onclick="sq(this,'rf-wealth')"><div class="qrad"></div><span class="qtxt">CHF 100'000 bis 250'000</span><span class="qpts">3 Pkt.</span></div>
                      <div class="qopt" onclick="sq(this,'rf-wealth')"><div class="qrad"></div><span class="qtxt">CHF 250'000 bis 1'000'000</span><span class="qpts">6 Pkt.</span></div>
                      <div class="qopt" onclick="sq(this,'rf-wealth')"><div class="qrad"></div><span class="qtxt">CHF 1'000'000 bis 2'000'000</span><span class="qpts">9 Pkt.</span></div>
                      <div class="qopt" onclick="sq(this,'rf-wealth')"><div class="qrad"></div><span class="qtxt">Über CHF 2'000'000</span><span class="qpts">12 Pkt.</span></div>
                    </div>
                  </div>

                  <!-- F5: Sparquote — Punkte: 0/3/6/9/12 -->
                  <div class="qsec">
                    <div class="ql"><span class="qnum">7</span><span>Sparen – Wie viel Prozent Ihres Einkommens können Sie unter Berücksichtigung des regelmässigen Einkommens, der finanziellen Verpflichtungen und der sonstigen Ausgaben zur Seite legen?</span></div>
                    <div class="qopts">
                      <div class="qopt" onclick="sq(this,'rf-savings')"><div class="qrad"></div><span class="qtxt">0 %</span><span class="qpts">0 Pkt.</span></div>
                      <div class="qopt" onclick="sq(this,'rf-savings')"><div class="qrad"></div><span class="qtxt">1 bis 10 %</span><span class="qpts">3 Pkt.</span></div>
                      <div class="qopt" onclick="sq(this,'rf-savings')"><div class="qrad"></div><span class="qtxt">10 bis 25 %</span><span class="qpts">6 Pkt.</span></div>
                      <div class="qopt" onclick="sq(this,'rf-savings')"><div class="qrad"></div><span class="qtxt">25 bis 50 %</span><span class="qpts">9 Pkt.</span></div>
                      <div class="qopt" onclick="sq(this,'rf-savings')"><div class="qrad"></div><span class="qtxt">Über 50 %</span><span class="qpts">12 Pkt.</span></div>
                    </div>
                  </div>

                  <!-- F6: Anlagehorizont — 6 Optionen nach W305.03 Seite 3 -->
                  <!-- Matrix-Werte: 1→Bis2J, 2→2-3J, 4→3-5J, 6→5-7J, 9→8-11J, 15→>12J -->
                  <div class="qsec" style="margin-bottom:0">
                    <div class="ql"><span class="qnum">8</span><span>Anlagehorizont – Wie lange können Sie das investierte Kapital mindestens anlegen? <em style="font-size:9px;color:var(--n4)">(Matrix-Faktor · beeinflusst Risikofähigkeits-Score)</em></span></div>
                    <div class="qopts">
                      <div class="qopt" onclick="sq(this,'rf-horizon')"><div class="qrad"></div><span class="qtxt">Bis 2 Jahre</span></div>
                      <div class="qopt" onclick="sq(this,'rf-horizon')"><div class="qrad"></div><span class="qtxt">2 bis 3 Jahre</span></div>
                      <div class="qopt" onclick="sq(this,'rf-horizon')"><div class="qrad"></div><span class="qtxt">3 bis 5 Jahre</span></div>
                      <div class="qopt" onclick="sq(this,'rf-horizon')"><div class="qrad"></div><span class="qtxt">5 bis 7 Jahre</span></div>
                      <div class="qopt" onclick="sq(this,'rf-horizon')"><div class="qrad"></div><span class="qtxt">8 bis 11 Jahre</span></div>
                      <div class="qopt" onclick="sq(this,'rf-horizon')"><div class="qrad"></div><span class="qtxt">Mehr als 12 Jahre</span></div>
                    </div>
                  </div>

                </div>
```

**CSS-Hinweis für `.qpts`:** Falls die Klasse noch nicht vorhanden ist, am Ende der existierenden `.qtxt`-Stile einfügen:
```css
.qpts{font-size:9px;color:var(--n4);margin-left:auto;padding-left:8px;white-space:nowrap;font-weight:500;}
```
Grep: `grep -n "\.qtxt{" 5eyes-electron/frontend/5eyes_v2.html` → nach diesem CSS-Block einfügen.

---

## Frontend — Schritt 7: `collectRiskAssessmentUiState()` ersetzen

### Grep:
```
grep -n "function collectRiskAssessmentUiState" 5eyes-electron/frontend/5eyes_v2.html
```

### Gesamte Funktion ersetzen:
```javascript
function collectRiskAssessmentUiState(){
  var rfSections = document.querySelectorAll('#r-rf .qsec');
  var rbSections = document.querySelectorAll('#r-rb .qsec');

  // F1–F5 (r-rf): bracket selections
  var incomeIdx      = getSelectedRiskIndex(rfSections[0]);  // F1
  // F2 (rfSections[1]) = Herkunft Checkboxen, kein Index
  var obligIdx       = getSelectedRiskIndex(rfSections[2]);  // F3
  var wealthIdx      = getSelectedRiskIndex(rfSections[3]);  // F4
  var savingsIdx     = getSelectedRiskIndex(rfSections[4]);  // F5
  var horizonIdx     = getSelectedRiskIndex(rfSections[5]);  // F6

  // Risikobereitschaft (r-rb)
  var goalIdx = -1, prefIdx = -1, behavIdx = -1;
  rbSections.forEach(function(sec, si) {
    var sel = sec.querySelector('.qopt.sel');
    if (!sel) return;
    var opts = Array.from(sec.querySelectorAll('.qopt'));
    var idx = opts.indexOf(sel);
    if (si === 0) goalIdx = idx;
    else if (si === 1) prefIdx = idx;
    else if (si === 2) behavIdx = idx;
  });

  // Kenntnisse & Erfahrungen (r-ke): 2-Spalten-Tabellen als JSON
  function collectKeTable(selector) {
    var result = {};
    document.querySelectorAll(selector).forEach(function(cb) {
      var row = cb.getAttribute('data-row');
      var col = cb.getAttribute('data-col');
      if (!row || !col) return;
      if (!result[row]) result[row] = {known:0, informed:0};
      result[row][col] = cb.checked ? 1 : 0;
    });
    return result;
  }
  var knowledgeServices    = collectKeTable('.ke-svc');
  var knowledgeInstruments = collectKeTable('.ke-ins');
  var incomeSources = Array.from(document.querySelectorAll('#r-rf .qsec:nth-child(2) .qcb.sel'))
    .map(function(el){ return (el.textContent||'').trim(); }).filter(Boolean);

  return {
    rfSections:rfSections,
    rbSections:rbSections,
    incomeIdx:incomeIdx,
    obligIdx:obligIdx,
    wealthIdx:wealthIdx,
    savingsIdx:savingsIdx,
    horizonIdx:horizonIdx,
    goalIdx:goalIdx,
    prefIdx:prefIdx,
    behavIdx:behavIdx,
    knowledgeServices:knowledgeServices,
    knowledgeInstruments:knowledgeInstruments,
    incomeSources:incomeSources
  };
}
```

---

## Frontend — Schritt 8: `collectRiskAssessmentUiIssues()` ersetzen

### Grep:
```
grep -n "function collectRiskAssessmentUiIssues" 5eyes-electron/frontend/5eyes_v2.html
```

### Gesamte Funktion ersetzen:
```javascript
function collectRiskAssessmentUiIssues(state){
  var s = state || collectRiskAssessmentUiState();
  var issues = [];
  if (s.incomeIdx < 0)   issues.push('Frage 3: Regelmässiges Einkommen');
  if (s.obligIdx < 0)    issues.push('Frage 5: Finanzielle Verpflichtungen');
  if (s.wealthIdx < 0)   issues.push('Frage 6: Freies Vermögen');
  if (s.savingsIdx < 0)  issues.push('Frage 7: Sparquote');
  if (s.horizonIdx < 0)  issues.push('Frage 8: Anlagehorizont');
  if (s.goalIdx < 0)     issues.push('Frage 9: Anlageziel');
  if (s.prefIdx < 0)     issues.push('Frage 10: Risikopräferenz');
  if (s.behavIdx < 0)    issues.push('Frage 11: Verlustverhalten');
  return issues;
}
```

---

## Frontend — Schritt 9: `buildRiskAssessmentPayloadFromUI()` ersetzen

### Grep:
```
grep -n "function buildRiskAssessmentPayloadFromUI" 5eyes-electron/frontend/5eyes_v2.html
```

### Gesamte Funktion ersetzen:
```javascript
function buildRiskAssessmentPayloadFromUI(){
  var state = collectRiskAssessmentUiState();
  var issues = collectRiskAssessmentUiIssues(state);
  if (issues.length) return null;

  // ── Risikofähigkeit: neue Bracket-basierte Punkte (SwissLife W305.03) ──────
  // F1: Einkommen (0/1/2/3/4)
  var incomePoints = RISK_INCOME_POINTS[Math.max(0, Math.min(RISK_INCOME_POINTS.length-1, state.incomeIdx))];
  // F3: Verpflichtungen (4/3/2/1/0 — invers, weniger Verpflichtungen = mehr Punkte)
  var obligationPoints = RISK_OBLIGATIONS_POINTS[Math.max(0, Math.min(RISK_OBLIGATIONS_POINTS.length-1, state.obligIdx))];
  // F4: Freies Vermögen (0/3/6/9/12)
  var wealthPoints = RISK_WEALTH_POINTS[Math.max(0, Math.min(RISK_WEALTH_POINTS.length-1, state.wealthIdx))];
  // F5: Sparquote (0/3/6/9/12)
  var savingsPoints = RISK_SAVINGS_POINTS[Math.max(0, Math.min(RISK_SAVINGS_POINTS.length-1, state.savingsIdx))];
  // F6: Anlagehorizont
  var horizon = RISK_HORIZON_OPTIONS[state.horizonIdx];
  var horizonStorageLabel = canonicalRiskHorizonLabel(horizon.label);
  var capacityTotal = incomePoints + obligationPoints + wealthPoints + savingsPoints;
  var capacityBand = findRiskCapacityBand(capacityTotal);
  var capScore = RISK_CAPACITY_MATRIX[horizon.years + ',' + capacityBand.band];

  // ── Risikobereitschaft ────────────────────────────────────────────────────
  var goalPoints  = Math.max(1, state.goalIdx + 1);   // F7: 1-4
  var prefPoints  = Math.max(1, state.prefIdx + 1);   // F8: 1-4
  var behavPoints = Math.max(1, state.behavIdx + 1);  // F9: 1-4
  var willingnessTotal = goalPoints + prefPoints + behavPoints;
  var rawWillScore = Math.round(((willingnessTotal - 3) / 9) * 90 + 10);
  var willScore = Math.max(10, Math.min(100, rawWillScore));

  // ── Final: MIN(cap, will) — FIDLEG-konform ────────────────────────────────
  var finalScore = Math.min(capScore, willScore);
  var mandateType = (currentMandateData && currentMandateData.mandate_type) || null;
  if (mandateType === 'FZK') finalScore = Math.min(finalScore, 75);
  var finalProfile = riskScoreToProfile(finalScore);

  // ── Answer-Labels für Audit-Trail ─────────────────────────────────────────
  var rfSections = state.rfSections;
  var rbSections = state.rbSections;
  function optLabel(sections, si, idx) {
    var sec = sections[si];
    if (!sec) return '';
    var opts = sec.querySelectorAll('.qopt');
    return (opts[idx] && opts[idx].querySelector('.qtxt')) ? opts[idx].querySelector('.qtxt').textContent.trim() : '';
  }
  var incomeSrcLabel = state.incomeSources.length ? state.incomeSources.join(', ') : 'Keine Angabe';

  return {
    payload: {
      q_income_points:           incomePoints,
      q_obligations_points:      obligationPoints,
      q_savings_points:          savingsPoints,
      q_wealth_points:           wealthPoints,
      investment_horizon_label:  horizonStorageLabel,
      investment_horizon_years:  horizon.years,
      q_investment_goal_points:  goalPoints,
      q_risk_preference_points:  prefPoints,
      q_risk_behavior_points:    behavPoints,
      knowledge_services_json:   JSON.stringify(state.knowledgeServices),
      knowledge_instruments_json:JSON.stringify(state.knowledgeInstruments),
      income_sources_json:       JSON.stringify(state.incomeSources),
      answers: [
        {question_number:1, question_section:'Kenntnisse & Erfahrungen', answer_label:'Finanzdienstleistungen: ' + JSON.stringify(state.knowledgeServices), answer_points:0},
        {question_number:2, question_section:'Kenntnisse & Erfahrungen', answer_label:'Finanzinstrumente: ' + JSON.stringify(state.knowledgeInstruments), answer_points:0},
        {question_number:3, question_section:'Risikofähigkeit', answer_label:optLabel(rfSections,0,state.incomeIdx), answer_points:incomePoints},
        {question_number:4, question_section:'Risikofähigkeit', answer_label:'Herkunft: ' + incomeSrcLabel, answer_points:0},
        {question_number:5, question_section:'Risikofähigkeit', answer_label:optLabel(rfSections,2,state.obligIdx), answer_points:obligationPoints},
        {question_number:6, question_section:'Risikofähigkeit', answer_label:optLabel(rfSections,3,state.wealthIdx), answer_points:wealthPoints},
        {question_number:7, question_section:'Risikofähigkeit', answer_label:optLabel(rfSections,4,state.savingsIdx), answer_points:savingsPoints},
        {question_number:8, question_section:'Risikofähigkeit', answer_label:horizon.label + ' · Matrix-Faktor', answer_points:0},
        {question_number:9, question_section:'Risikobereitschaft', answer_label:optLabel(rbSections,0,state.goalIdx), answer_points:goalPoints},
        {question_number:10, question_section:'Risikobereitschaft', answer_label:optLabel(rbSections,1,state.prefIdx), answer_points:prefPoints},
        {question_number:11, question_section:'Risikobereitschaft', answer_label:optLabel(rbSections,2,state.behavIdx), answer_points:behavPoints}
      ]
    },
    capScore:capScore,
    capProfile:capacityBand.label,
    willScore:willScore,
    willProfile:riskWillingnessProfile(willScore),
    finalScore:finalScore,
    finalProfile:finalProfile,
    raw:{
      incomeIdx:state.incomeIdx,
      obligIdx:state.obligIdx,
      wealthIdx:state.wealthIdx,
      savingsIdx:state.savingsIdx,
      horizonIdx:state.horizonIdx,
      goalIdx:state.goalIdx,
      prefIdx:state.prefIdx,
      behavIdx:state.behavIdx,
      incomePoints:incomePoints,
      obligationPoints:obligationPoints,
      wealthPoints:wealthPoints,
      savingsPoints:savingsPoints,
      capacityTotal:capacityTotal,
      horizonLabel:horizon.label
    }
  };
}
```

---

## Frontend — Schritt 10: `resetRiskQuestionnaireToDefaults()` aktualisieren

### Grep:
```
grep -n "function resetRiskQuestionnaireToDefaults" 5eyes-electron/frontend/5eyes_v2.html
```

### Gesamte Funktion ersetzen:
```javascript
function resetRiskQuestionnaireToDefaults(){
  riskHorizonTouched = false;
  riskAssessmentUiDirty = false;
  // Checkboxen leeren
  document.querySelectorAll('.ke-svc, .ke-ins').forEach(function(cb){ cb.checked = false; });
  document.querySelectorAll('#r-rf .qsec:nth-child(2) .qcb').forEach(function(el){ el.classList.remove('sel'); });
  // Alle Radio-Optionen abwählen
  document.querySelectorAll('#r-rf .qopt, #r-rb .qopt').forEach(function(el){ el.classList.remove('sel'); });
}
```

---

## Frontend — Schritt 11: `hydrateRiskQuestionnaire()` aktualisieren

### Grep:
```
grep -n "function hydrateRiskQuestionnaire" 5eyes-electron/frontend/5eyes_v2.html
```

### Gesamte Funktion ersetzen:
```javascript
function hydrateRiskQuestionnaire(saved){
  resetRiskQuestionnaireToDefaults();
  if (!saved) return;

  var rfSections = document.querySelectorAll('#r-rf .qsec');
  var rbSections = document.querySelectorAll('#r-rb .qsec');
  var answers = saved.answers || [];

  function findAnswer(num) { return answers.find(function(a){ return a.question_number === num; }); }

  // Kenntnisse & Erfahrungen (Q1/Q2 aus JSON-Feldern)
  if (saved.knowledge_services_json) {
    try {
      var svc = JSON.parse(saved.knowledge_services_json);
      Object.keys(svc).forEach(function(row) {
        ['known','informed'].forEach(function(col) {
          var cb = document.querySelector('.ke-svc[data-row="'+row+'"][data-col="'+col+'"]');
          if (cb) cb.checked = !!(svc[row] && svc[row][col]);
        });
      });
    } catch(e){}
  }
  if (saved.knowledge_instruments_json) {
    try {
      var ins = JSON.parse(saved.knowledge_instruments_json);
      Object.keys(ins).forEach(function(row) {
        ['known','informed'].forEach(function(col) {
          var cb = document.querySelector('.ke-ins[data-row="'+row+'"][data-col="'+col+'"]');
          if (cb) cb.checked = !!(ins[row] && ins[row][col]);
        });
      });
    } catch(e){}
  }
  if (saved.income_sources_json) {
    try {
      var sources = JSON.parse(saved.income_sources_json);
      var herkunftCbs = document.querySelectorAll('#r-rf .qsec:nth-child(2) .qcb');
      herkunftCbs.forEach(function(el){
        var text = (el.textContent||'').trim();
        if (sources.indexOf(text) >= 0) el.classList.add('sel');
      });
    } catch(e){}
  }

  // Risikofähigkeit via Answer-Labels
  var q3 = findAnswer(3); // F1 Einkommen
  var q5 = findAnswer(5); // F3 Verpflichtungen
  var q6 = findAnswer(6); // F4 Vermögen
  var q7 = findAnswer(7); // F5 Sparquote
  var q8 = findAnswer(8); // F6 Horizont
  if (q3) selectRiskOptionByLabel(rfSections[0], q3.answer_label);
  if (q5) selectRiskOptionByLabel(rfSections[2], q5.answer_label);
  if (q6) selectRiskOptionByLabel(rfSections[3], q6.answer_label);
  if (q7) selectRiskOptionByLabel(rfSections[4], q7.answer_label);
  if (q8) {
    var hLabel = (q8.answer_label||'').replace(' · Matrix-Faktor','').trim();
    selectRiskOptionByLabel(rfSections[5], hLabel);
    riskHorizonTouched = true;
  }

  // Risikobereitschaft
  var q9 = findAnswer(9); var q10 = findAnswer(10); var q11 = findAnswer(11);
  if (q9)  selectRiskOptionByLabel(rbSections[0], q9.answer_label);
  if (q10) selectRiskOptionByLabel(rbSections[1], q10.answer_label);
  if (q11) selectRiskOptionByLabel(rbSections[2], q11.answer_label);
}
```

---

## Frontend — Schritt 12: PDF-Sektion "Kenntnisse & Erfahrungen"

### Grep um PDF-Funktion zu finden:
```
grep -n "buildAnlagestrategieDocHtml\|buildRiskProfilePdf\|Risikoprofil.*PDF\|Section 2.*Risikoprofil" 5eyes-electron/frontend/5eyes_v2.html | head -10
```

### Grep für Einfügeposition im PDF:
```
grep -n "Section 2: Risikoprofil\|// Section 2\|Risikobereitschaft.*Punkte\|Risikofähigkeit.*Punkte" 5eyes-electron/frontend/5eyes_v2.html | head -10
```

Die PDF-Funktion baut das Risikoprofil-Dokument. Vor dem bestehenden Block der Risikofähigkeits-Antworten eine neue Sektion einfügen:

```javascript
// KENNTNISSE & ERFAHRUNGEN (SwissLife W305.03 Seite 1)
// Einfügen am ANFANG der PDF-Risikoprofil-Sektion, vor den Q-Antworten
var keHtml = '';
if (riskData && (riskData.knowledge_services_json || riskData.knowledge_instruments_json)) {
  function buildKeTable(title, jsonStr) {
    var data = {};
    try { data = JSON.parse(jsonStr || '{}'); } catch(e){}
    var rows = Object.keys(data).map(function(row) {
      return '<tr><td style="padding:4px 8px;border-bottom:1px solid #eee;font-size:10px">' + escapeHtml(row) + '</td>'
        + '<td style="padding:4px 8px;border-bottom:1px solid #eee;text-align:center;font-size:10px">' + (data[row].known ? '☑' : '☐') + '</td>'
        + '<td style="padding:4px 8px;border-bottom:1px solid #eee;text-align:center;font-size:10px">' + (data[row].informed ? '☑' : '☐') + '</td>'
        + '</tr>';
    }).join('');
    return '<table style="width:100%;border-collapse:collapse;border:1px solid #ddd;border-radius:4px;margin-bottom:10px">'
      + '<thead><tr>'
      + '<th style="padding:5px 8px;background:#f5f5f5;text-align:left;font-size:9px;font-weight:600;text-transform:uppercase;letter-spacing:0.05em">' + escapeHtml(title) + '</th>'
      + '<th style="padding:5px 8px;background:#f5f5f5;text-align:center;font-size:9px;font-weight:600;border-left:1px solid #ddd">Kenntnisse vorhanden</th>'
      + '<th style="padding:5px 8px;background:#f5f5f5;text-align:center;font-size:9px;font-weight:600;border-left:1px solid #ddd">Aufklärung erhalten</th>'
      + '</tr></thead><tbody>' + rows + '</tbody></table>';
  }
  keHtml = '<div style="margin-bottom:16px">'
    + '<div style="font-size:11px;font-weight:700;color:#1a1a1a;margin-bottom:8px">1 · Kenntnisse &amp; Erfahrungen</div>'
    + buildKeTable('Finanzdienstleistungen', riskData.knowledge_services_json)
    + buildKeTable('Finanzinstrumente', riskData.knowledge_instruments_json)
    + '</div>';
}
// keHtml in die PDF-HTML einfügen (vor Risikofähigkeit-Block)
```

---

## Implementierungs-Checkliste für Codex

### Backend (in dieser Reihenfolge)
1. `models/profiling.py`: 3 neue optionale Columns in `RiskAssessment` (knowledge_services_json, knowledge_instruments_json, income_sources_json)
2. `schemas/profiling.py`: 3 neue optionale Felder in `RiskAssessmentCreate` UND `RiskAssessmentResponse`
3. `database.py`: 3 neue `ensure_column` Calls in `ensure_runtime_columns()`
4. Backend starten und testen: `GET /mandates/{id}/risk-assessments` — sollte die 3 neuen Felder im Response zurückgeben (als null für bestehende Datensätze)

### Frontend (in dieser Reihenfolge)
5. CSS: `.qpts` Klasse hinzufügen (falls nicht vorhanden)
6. JS-Konstanten: `RISK_HORIZON_OPTIONS` auf 6 Optionen, neue Punkte-Konstanten
7. HTML Tab 1 (`r-ke`): Gesamten Block ersetzen (2-Spalten-Tabellen)
8. HTML Tab 2 (`r-rf`): Gesamten Block ersetzen (Brackets, F2 Herkunft, F6 Horizont 6 Optionen)
9. `collectRiskAssessmentUiState()`: Neue Funktion
10. `collectRiskAssessmentUiIssues()`: Neue Funktion
11. `buildRiskAssessmentPayloadFromUI()`: Neue Funktion mit Bracket-Scoring
12. `resetRiskQuestionnaireToDefaults()`: Neue Funktion
13. `hydrateRiskQuestionnaire()`: Neue Funktion
14. PDF-Funktion: Kenntnisse & Erfahrungen Sektion einfügen
15. `node --check 5eyes-electron/frontend/5eyes_v2.html` → 0 JS-Fehler

### Tests
16. `tests/test_risk_scoring.py`: Sicherstellen dass bestehende Tests noch laufen (risk_scoring.py wurde nicht geändert)
17. Neuer Testfall: `test_risk_assessment_with_knowledge_json` — POST mit knowledge_services_json, verifizieren dass es gespeichert und im GET zurückgegeben wird

---

## Akzeptanzkriterien

1. Tab 1 "Kenntnisse & Erfahrungen" zeigt 2 Tabellen mit je 2 Spalten (Kenntnisse / Aufklärung) — exakt wie `Seite 1 neu.jpg`
2. Tab 2 "Risikofähigkeit" zeigt Brackets für F1/F3/F4/F5 mit Punkteangabe — exakt wie `Seite 2 neu.jpg`
3. F2 (Herkunft) ist Mehrfachauswahl, hat keine Punkte, aber wird gespeichert
4. Tab 2 Anlagehorizont hat 6 Optionen — wie `Seite 3 neu.jpg`
5. "Risikoprofil speichern" funktioniert, knowledge_services_json wird in DB gespeichert
6. Nach Neuladen: alle Checkboxen und Selections werden korrekt wiederhergestellt
7. Scoring: Mandat mit Einkommen >20k / Verpflichtungen <3k / Vermögen >2M / Sparen >50% = capacityTotal = 4+4+12+12 = 32 Punkte → Band "Dynamisch"
8. Scoring: FZK-Mandat → finalScore max 75 (bestehende Logik bleibt)
9. PDF (Anlagestrategie) enthält Sektion "Kenntnisse & Erfahrungen" mit beiden Tabellen
10. `node --check` → 0 Fehler

---

## OWNER-DECISIONS

1. **Bestehende Risikoprofile**: Kunden mit bereits gespeicherten Profilen haben `knowledge_services_json = NULL`. Die UI zeigt leere Tabellen — Berater füllt beim nächsten Gespräch aus. OK so?
2. **Scoring-Diskontinuität**: Bestehende Mandate haben alte Scores (surplus-basiert). Nach Update können sich Scores leicht verschieben (neue Bracket-Methode). Das ist gewollt (Compliance), aber beim ersten Gespräch nach dem Update wird der Berater informiert. OK?
