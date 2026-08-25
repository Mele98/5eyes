# CODEX IMPLEMENTATION BRIEF
## Risikoprofil Überarbeitung + Portfolio ETF Phase 1
**Datum:** 2026-04-16 | **Branch:** `codex/rp-ueberarbeitung`

---

## WICHTIG: Vor dem Start

```powershell
# Branch erstellen (im Projektverzeichnis)
.\scripts\start_codex_branch.ps1 -Slug "rp-ueberarbeitung"

# Workspace prüfen
git status --short
```

**Arbeitsverzeichnis:** `C:\5eyes\5eyes_stage9_release_ready\`
**Alle Pfade in diesem Dokument sind relativ zu diesem Verzeichnis.**

---

## ÜBERSICHT — Was wird geändert

### Feature 1: Risikoprofil (Referenzmodell Eignungspruefung)
**Warum:** Das bestehende Formular stimmt nicht mit dem offiziellen Referenzmodell-Compliance-Dokument
überein. Berater müssen dasselbe Formular digital wie auf Papier ausfüllen können.

| Datei | Änderung |
|---|---|
| `5eyes-backend/models/profiling.py` | 3 neue optionale Spalten |
| `5eyes-backend/schemas/profiling.py` | 3 neue optionale Felder |
| `5eyes-backend/database.py` | 3 ALTER TABLE in ensure_runtime_columns() |
| `5eyes-electron/frontend/5eyes_v2.html` | 9 Änderungen (Konstanten + HTML + JS) |

### Feature 2: Portfolio ETF Phase 1
**Warum:** Phase 1 verwendet nur ETFs & Fonds — keine Einzeltitel. Das muss im UI sichtbar sein.

| Datei | Änderung |
|---|---|
| `5eyes-electron/frontend/5eyes_v2.html` | 2 Änderungen (Header + Checkbox) |

---

## SCORING-LOGIK — Warum die Formel sich ändert

Das **alte System** berechnete Surplus-Punkte als Verhältnis (income - obligations) / income.
Das **neue System** nach Eignungspruefung bewertet Einkommen (F1) und Verpflichtungen (F3) separat:

```
Alt:  surplusPoints (0-4, ratio) + obligationPoints (IMMER 0) + savings (0-12) + reserve (0-12) = max 28
Neu:  F1 income (0-4) + F3 oblig (4-0 invers) + F4 wealth (0-12) + F5 savings (0-12) = max 32
```

Die Backend-Funktion `compute_scores()` in `risk_scoring.py` wird **NICHT geändert** — sie
summiert `q_income_points + q_obligations_points + q_savings_points + q_wealth_points`.
Das Schema erlaubt 0-4 für income und obligations bereits. Kein Backend-Code ausser DB nötig.

`map_surplus_points()` **NICHT löschen** — sie wird in Tests verwendet.

Das finale Scoring bleibt: `finalScore = MIN(capScore, willScore)` — FIDLEG-konform.

---

---

# TEIL 1: BACKEND

---

## B1 — `5eyes-backend/models/profiling.py`

**Grep für Einfügeposition:**
```
grep -n "override_warning_document_id" 5eyes-backend/models/profiling.py
```

**Suche genau diesen Block (eindeutig):**
```python
    override_warning_document_id = Column(String)
    assessed_at = Column(String, nullable=False)
```

**Ersetzen durch:**
```python
    override_warning_document_id = Column(String)
    # Kenntnisse & Erfahrungen — Referenzmodell Eignungspruefung Seite 1 (kein Score, nur Compliance)
    knowledge_services_json = Column(String)    # {"Vermögensverwaltung":{"known":0,"informed":1},...}
    knowledge_instruments_json = Column(String) # {"Anlagefonds":{"known":1,"informed":1},...}
    # Herkunft des Einkommens — Frage 2, rein informativ (kein Score)
    income_sources_json = Column(String)        # ["Berufliche Tätigkeit","Rente"]
    assessed_at = Column(String, nullable=False)
```

---

## B2 — `5eyes-backend/schemas/profiling.py`

### In `RiskAssessmentCreate`

**Grep:**
```
grep -n "answers: Optional\[list\[dict\]\]" 5eyes-backend/schemas/profiling.py
```

**Suche:**
```python
    answers: Optional[list[dict]] = None
```

**Ersetzen durch:**
```python
    answers: Optional[list[dict]] = None
    # Kenntnisse & Erfahrungen (Referenzmodell Eignungspruefung Seite 1) — optional, kein Score
    knowledge_services_json: Optional[str] = None
    knowledge_instruments_json: Optional[str] = None
    income_sources_json: Optional[str] = None
```

### In `RiskAssessmentResponse`

**Grep:**
```
grep -n "answers: list\[RiskAssessmentAnswerResponse\]" 5eyes-backend/schemas/profiling.py
```

**Suche:**
```python
    answers: list[RiskAssessmentAnswerResponse] = []
```

**Ersetzen durch:**
```python
    answers: list[RiskAssessmentAnswerResponse] = []
    knowledge_services_json: Optional[str] = None
    knowledge_instruments_json: Optional[str] = None
    income_sources_json: Optional[str] = None
```

---

## B3 — `5eyes-backend/database.py`

**Grep für Einfügeposition:**
```
grep -n "ensure_column\|def ensure_runtime_columns\|correlation_matrix_json" 5eyes-backend/database.py | tail -10
```

Suche den letzten `ensure_column`-Aufruf in `ensure_runtime_columns()`.
**Danach einfügen:**

```python
    # RiskAssessment — Kenntnisse & Erfahrungen (Referenzmodell Eignungspruefung, 2026-04-16)
    ensure_column(conn, "risk_assessments", "knowledge_services_json", "TEXT")
    ensure_column(conn, "risk_assessments", "knowledge_instruments_json", "TEXT")
    ensure_column(conn, "risk_assessments", "income_sources_json", "TEXT")
```

**Falls `ensure_column` nicht existiert, stattdessen:**
```python
    for _col in ["knowledge_services_json", "knowledge_instruments_json", "income_sources_json"]:
        try:
            conn.execute(text(f"ALTER TABLE risk_assessments ADD COLUMN {_col} TEXT"))
        except Exception:
            pass
```

**Prüfung Backend:**
```bash
cd 5eyes-backend && python -c "from database import engine; print('DB OK')"
```

---

---

# TEIL 2: FRONTEND — JS-KONSTANTEN

---

## F1 — `RISK_HORIZON_OPTIONS` auf 6 Optionen erweitern

**Grep:**
```
grep -n "var RISK_HORIZON_OPTIONS" 5eyes-electron/frontend/5eyes_v2.html
```

**Suche exakt (4 Einträge):**
```javascript
var RISK_HORIZON_OPTIONS = [
  {label:'2 bis 3 Jahre', years:2},
  {label:'4 bis 5 Jahre', years:4},
  {label:'8 bis 11 Jahre', years:9},
  {label:'12 Jahre und mehr', years:15}
];
```

**Ersetzen durch (6 Einträge — Referenzmodell Eignungspruefung Seite 3):**
```javascript
var RISK_HORIZON_OPTIONS = [
  {label:'Bis 2 Jahre',       years:1},
  {label:'2 bis 3 Jahre',     years:2},
  {label:'3 bis 5 Jahre',     years:4},
  {label:'5 bis 7 Jahre',     years:6},
  {label:'8 bis 11 Jahre',    years:9},
  {label:'Mehr als 12 Jahre', years:15}
];
```

**Warum:** Eignungspruefung hat 6 Zeithorizonte. Die Jahre-Werte (1,2,4,6,9,15) entsprechen den
Zeilen der `RISK_CAPACITY_MATRIX` — keine Änderung an der Matrix nötig.
`RISK_HORIZON_CANONICAL_LABELS` enthält bereits alle 6 Labels → keine Änderung nötig.

---

## F2 — Punkte-Konstanten ersetzen

**Grep:**
```
grep -n "var RISK_SAVINGS_POINTS\|var RISK_RESERVE_POINTS\|var RISK_FREE_WEALTH" 5eyes-electron/frontend/5eyes_v2.html
```

**Suche exakt:**
```javascript
var RISK_SAVINGS_POINTS = [0, 4, 8, 12];
var RISK_RESERVE_POINTS = [0, 3, 6, 9];
var RISK_FREE_WEALTH_POINTS = [0, 3, 6, 9];
```

**Ersetzen durch:**
```javascript
// F1: Monatliches Bruttoeinkommen — Eignungspruefung Seite 2, Frage 1
// bis 6k=0 | 6-9k=1 | 9-12k=2 | 12-20k=3 | >20k=4
var RISK_INCOME_POINTS = [0, 1, 2, 3, 4];

// F3: Monatliche Verpflichtungen — Eignungspruefung Seite 2, Frage 3 (INVERS: weniger Verpfl. = mehr Punkte)
// bis 3k=4 | 3-5k=3 | 5-8k=2 | 8-12k=1 | >12k=0
var RISK_OBLIGATIONS_POINTS = [4, 3, 2, 1, 0];

// F4: Frei verfügbares Vermögen — Eignungspruefung Seite 2, Frage 4
// <100k=0 | 100-250k=3 | 250k-1M=6 | 1-2M=9 | >2M=12
var RISK_WEALTH_POINTS = [0, 3, 6, 9, 12];

// F5: Sparquote — Eignungspruefung Seite 2, Frage 5 (5 Optionen statt 4)
// 0%=0 | 1-10%=3 | 10-25%=6 | 25-50%=9 | >50%=12
var RISK_SAVINGS_POINTS = [0, 3, 6, 9, 12];

// Legacy — nicht mehr für Scoring verwendet, bleibt für Rückwärtskompatibilität in Tests
var RISK_RESERVE_POINTS = [0, 3, 6, 9];
var RISK_FREE_WEALTH_POINTS = [0, 3, 6, 9];
```

---

---

# TEIL 3: FRONTEND — HTML (page-rp)

---

## F3 — Tab 1 `r-ke` komplett ersetzen

### Grep für Start des Blocks:
```
grep -n "TAB 1: KENNTNISSE" 5eyes-electron/frontend/5eyes_v2.html
```

**Suche exakt (Beginn-Marker):**
```
                <!-- TAB 1: KENNTNISSE & ERFAHRUNGEN -->
                <div id="r-ke" class="rpanel active">
```

**Ende-Marker (NICHT ersetzen, nach dem neuen Block stehen lassen):**
```
                <!-- TAB 2: RISIKOFÄHIGKEIT -->
```

**Gesamten Block zwischen diesen Markern ersetzen durch:**

```html
                <!-- TAB 1: KENNTNISSE & ERFAHRUNGEN (Referenzmodell Eignungspruefung Seite 1) -->
                <!-- Rein dokumentarisch / Compliance — KEIN Einfluss auf Score -->
                <div id="r-ke" class="rpanel active">

                  <!-- TABELLE 1: Finanzdienstleistungen -->
                  <div class="qsec">
                    <div class="ql">
                      <span class="qnum">1</span>
                      <span>Mit welchen <strong>Finanzdienstleistungen</strong> haben Sie Kenntnisse und Erfahrungen?
                        <em style="font-size:9px;color:var(--n4)">(Compliance · kein Score)</em>
                      </span>
                    </div>
                    <div style="padding-left:24px;margin-top:8px">
                      <div style="display:grid;grid-template-columns:1fr 130px 130px;border:1px solid var(--b1);border-radius:var(--r);overflow:hidden;font-size:10px">
                        <div style="padding:5px 8px;background:var(--bg2,var(--bg));font-weight:600;color:var(--n5);font-size:9px;text-transform:uppercase;letter-spacing:0.05em;border-bottom:1px solid var(--b1)">Finanzdienstleistung</div>
                        <div style="padding:5px 8px;background:var(--bg2,var(--bg));font-weight:600;color:var(--n5);font-size:9px;text-align:center;border-bottom:1px solid var(--b1);border-left:1px solid var(--b1)">Kenntnisse vorhanden</div>
                        <div style="padding:5px 8px;background:var(--bg2,var(--bg));font-weight:600;color:var(--n5);font-size:9px;text-align:center;border-bottom:1px solid var(--b1);border-left:1px solid var(--b1)">Aufklärung erhalten</div>
                        <div style="padding:7px 8px;color:var(--n8);border-bottom:1px solid var(--b1)">Vermögensverwaltung</div>
                        <div style="padding:7px 8px;text-align:center;border-bottom:1px solid var(--b1);border-left:1px solid var(--b1)"><input type="checkbox" class="ke-svc" data-row="Vermögensverwaltung" data-col="known" style="accent-color:var(--g4);width:14px;height:14px;cursor:pointer"></div>
                        <div style="padding:7px 8px;text-align:center;border-bottom:1px solid var(--b1);border-left:1px solid var(--b1)"><input type="checkbox" class="ke-svc" data-row="Vermögensverwaltung" data-col="informed" style="accent-color:var(--g4);width:14px;height:14px;cursor:pointer"></div>
                        <div style="padding:7px 8px;color:var(--n8);border-bottom:1px solid var(--b1)">Anlageberatung</div>
                        <div style="padding:7px 8px;text-align:center;border-bottom:1px solid var(--b1);border-left:1px solid var(--b1)"><input type="checkbox" class="ke-svc" data-row="Anlageberatung" data-col="known" style="accent-color:var(--g4);width:14px;height:14px;cursor:pointer"></div>
                        <div style="padding:7px 8px;text-align:center;border-bottom:1px solid var(--b1);border-left:1px solid var(--b1)"><input type="checkbox" class="ke-svc" data-row="Anlageberatung" data-col="informed" style="accent-color:var(--g4);width:14px;height:14px;cursor:pointer"></div>
                        <div style="padding:7px 8px;color:var(--n8)">Stiftungsprodukte (Freizügigkeit oder Säule 3a)</div>
                        <div style="padding:7px 8px;text-align:center;border-left:1px solid var(--b1)"><input type="checkbox" class="ke-svc" data-row="Stiftungsprodukte" data-col="known" style="accent-color:var(--g4);width:14px;height:14px;cursor:pointer"></div>
                        <div style="padding:7px 8px;text-align:center;border-left:1px solid var(--b1)"><input type="checkbox" class="ke-svc" data-row="Stiftungsprodukte" data-col="informed" style="accent-color:var(--g4);width:14px;height:14px;cursor:pointer"></div>
                      </div>
                    </div>
                  </div>

                  <!-- TABELLE 2: Finanzinstrumente -->
                  <div class="qsec">
                    <div class="ql">
                      <span class="qnum">2</span>
                      <span>Mit welchen <strong>Finanzinstrumenten</strong> haben Sie Kenntnisse und Erfahrungen?
                        <em style="font-size:9px;color:var(--n4)">(Compliance · kein Score)</em>
                      </span>
                    </div>
                    <div style="padding-left:24px;margin-top:8px">
                      <div style="display:grid;grid-template-columns:1fr 130px 130px;border:1px solid var(--b1);border-radius:var(--r);overflow:hidden;font-size:10px">
                        <div style="padding:5px 8px;background:var(--bg2,var(--bg));font-weight:600;color:var(--n5);font-size:9px;text-transform:uppercase;letter-spacing:0.05em;border-bottom:1px solid var(--b1)">Finanzinstrument</div>
                        <div style="padding:5px 8px;background:var(--bg2,var(--bg));font-weight:600;color:var(--n5);font-size:9px;text-align:center;border-bottom:1px solid var(--b1);border-left:1px solid var(--b1)">Kenntnisse vorhanden</div>
                        <div style="padding:5px 8px;background:var(--bg2,var(--bg));font-weight:600;color:var(--n5);font-size:9px;text-align:center;border-bottom:1px solid var(--b1);border-left:1px solid var(--b1)">Aufklärung erhalten</div>
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

## F4 — Tab 2 `r-rf` komplett ersetzen

### Grep für Start:
```
grep -n "TAB 2: RISIKOFÄHIGKEIT" 5eyes-electron/frontend/5eyes_v2.html
```

**Suche (Beginn-Marker):**
```
                <!-- TAB 2: RISIKOFÄHIGKEIT -->
                <div id="r-rf" class="rpanel">
```

**Ende-Marker (NICHT ersetzen):**
```
                <!-- TAB 3: RISIKOBEREITSCHAFT -->
```

**Gesamten Block zwischen diesen Markern ersetzen durch:**

```html
                <!-- TAB 2: RISIKOFÄHIGKEIT (Referenzmodell Eignungspruefung Seite 2) -->
                <!-- Punkte: F1(0-4) + F3(4-0 invers) + F4(0-12) + F5(0-12) = max 32 -->
                <div id="r-rf" class="rpanel">

                  <!-- F1: Regelmässiges Einkommen — Punkte: 0/1/2/3/4 -->
                  <div class="qsec">
                    <div class="ql">
                      <span class="qnum">3</span>
                      <span>Regelmässiges Einkommen – Wie hoch ist Ihr regelmässiges Bruttoeinkommen pro Monat aus selbstständiger und unselbstständiger Erwerbstätigkeit, Miete, Anlagen und Rente?</span>
                    </div>
                    <div class="qopts">
                      <div class="qopt" onclick="sq(this,'rf-income')"><div class="qrad"></div><span class="qtxt">Bis CHF 6'000</span></div>
                      <div class="qopt" onclick="sq(this,'rf-income')"><div class="qrad"></div><span class="qtxt">CHF 6'000 bis 9'000</span></div>
                      <div class="qopt" onclick="sq(this,'rf-income')"><div class="qrad"></div><span class="qtxt">CHF 9'000 bis 12'000</span></div>
                      <div class="qopt" onclick="sq(this,'rf-income')"><div class="qrad"></div><span class="qtxt">CHF 12'000 bis 20'000</span></div>
                      <div class="qopt" onclick="sq(this,'rf-income')"><div class="qrad"></div><span class="qtxt">Über CHF 20'000</span></div>
                    </div>
                  </div>

                  <!-- F2: Herkunft des Einkommens — NUR INFORMATIV, kein Score -->
                  <div class="qsec">
                    <div class="ql">
                      <span class="qnum">4</span>
                      <span>Herkunft des Einkommens – Woher stammt Ihr regelmässiges Einkommen?
                        <em style="font-size:9px;color:var(--n4)">(Mehrfachauswahl · informativ · kein Score)</em>
                      </span>
                    </div>
                    <div class="qcbs">
                      <div class="qcb" onclick="this.classList.toggle('sel');riskAssessmentUiDirty=true;"><div class="qbox"></div>Berufliche Tätigkeit (selbstständig oder unselbstständig)</div>
                      <div class="qcb" onclick="this.classList.toggle('sel');riskAssessmentUiDirty=true;"><div class="qbox"></div>Rente</div>
                      <div class="qcb" onclick="this.classList.toggle('sel');riskAssessmentUiDirty=true;"><div class="qbox"></div>Vermietung von Liegenschaften</div>
                      <div class="qcb" onclick="this.classList.toggle('sel');riskAssessmentUiDirty=true;"><div class="qbox"></div>Erträgen aus Anlagen</div>
                      <div class="qcb" onclick="this.classList.toggle('sel');riskAssessmentUiDirty=true;"><div class="qbox"></div>Sonstige Quellen</div>
                    </div>
                  </div>

                  <!-- F3: Finanzielle Verpflichtungen — Punkte: 4/3/2/1/0 (INVERS) -->
                  <div class="qsec">
                    <div class="ql">
                      <span class="qnum">5</span>
                      <span>Finanzielle Verpflichtungen – Wie hoch sind Ihre aktuellen und künftig absehbaren finanziellen Verpflichtungen pro Monat?
                        <em style="font-size:9px;color:var(--n4)">(z.B. Miete, Hypothek, Krankenkasse, Unterhalt)</em>
                      </span>
                    </div>
                    <div class="qopts">
                      <div class="qopt" onclick="sq(this,'rf-oblig')"><div class="qrad"></div><span class="qtxt">Bis CHF 3'000</span></div>
                      <div class="qopt" onclick="sq(this,'rf-oblig')"><div class="qrad"></div><span class="qtxt">CHF 3'000 bis 5'000</span></div>
                      <div class="qopt" onclick="sq(this,'rf-oblig')"><div class="qrad"></div><span class="qtxt">CHF 5'000 bis 8'000</span></div>
                      <div class="qopt" onclick="sq(this,'rf-oblig')"><div class="qrad"></div><span class="qtxt">CHF 8'000 bis 12'000</span></div>
                      <div class="qopt" onclick="sq(this,'rf-oblig')"><div class="qrad"></div><span class="qtxt">Über CHF 12'000</span></div>
                    </div>
                  </div>

                  <!-- F4: Freies Vermögen — Punkte: 0/3/6/9/12 -->
                  <div class="qsec">
                    <div class="ql">
                      <span class="qnum">6</span>
                      <span>Vermögen – Wie hoch ist Ihr frei verfügbares Vermögen (z.B. Kontoguthaben, Wertschriften), welches Sie nicht zur Deckung von aktuellen oder zukünftigen finanziellen Verpflichtungen benötigen?</span>
                    </div>
                    <div class="qopts">
                      <div class="qopt" onclick="sq(this,'rf-wealth')"><div class="qrad"></div><span class="qtxt">Bis CHF 100'000</span></div>
                      <div class="qopt" onclick="sq(this,'rf-wealth')"><div class="qrad"></div><span class="qtxt">CHF 100'000 bis 250'000</span></div>
                      <div class="qopt" onclick="sq(this,'rf-wealth')"><div class="qrad"></div><span class="qtxt">CHF 250'000 bis 1'000'000</span></div>
                      <div class="qopt" onclick="sq(this,'rf-wealth')"><div class="qrad"></div><span class="qtxt">CHF 1'000'000 bis 2'000'000</span></div>
                      <div class="qopt" onclick="sq(this,'rf-wealth')"><div class="qrad"></div><span class="qtxt">Über CHF 2'000'000</span></div>
                    </div>
                  </div>

                  <!-- F5: Sparquote — Punkte: 0/3/6/9/12 -->
                  <div class="qsec">
                    <div class="ql">
                      <span class="qnum">7</span>
                      <span>Sparen – Wie viel Prozent Ihres Einkommens können Sie unter Berücksichtigung des regelmässigen Einkommens, der finanziellen Verpflichtungen und der sonstigen Ausgaben zur Seite legen?</span>
                    </div>
                    <div class="qopts">
                      <div class="qopt" onclick="sq(this,'rf-savings')"><div class="qrad"></div><span class="qtxt">0 %</span></div>
                      <div class="qopt" onclick="sq(this,'rf-savings')"><div class="qrad"></div><span class="qtxt">1 bis 10 %</span></div>
                      <div class="qopt" onclick="sq(this,'rf-savings')"><div class="qrad"></div><span class="qtxt">10 bis 25 %</span></div>
                      <div class="qopt" onclick="sq(this,'rf-savings')"><div class="qrad"></div><span class="qtxt">25 bis 50 %</span></div>
                      <div class="qopt" onclick="sq(this,'rf-savings')"><div class="qrad"></div><span class="qtxt">Über 50 %</span></div>
                    </div>
                  </div>

                  <!-- F6: Anlagehorizont — 6 Optionen (Eignungspruefung Seite 3) — kein direkter Punktewert, Matrix-Faktor -->
                  <div class="qsec" style="margin-bottom:0">
                    <div class="ql">
                      <span class="qnum">8</span>
                      <span>Anlagehorizont – Wie lange können Sie das investierte Kapital mindestens anlegen?
                        <em style="font-size:9px;color:var(--n4)">(Matrix-Faktor)</em>
                      </span>
                    </div>
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

---

---

# TEIL 4: FRONTEND — JS-FUNKTIONEN (6 Funktionen + 2 Einzeiler)

---

## F5 — `sq()` um neues Horizont-Kürzel erweitern

**Warum:** `sq()` setzt `riskHorizonTouched=true` nur bei Gruppe `'q5'`. Die neue
Horizont-Gruppe heisst `'rf-horizon'` — muss ebenfalls erfasst werden.

**Grep:**
```
grep -n "function sq(el,g)" 5eyes-electron/frontend/5eyes_v2.html
```

**Suche exakt:**
```javascript
  if(g==='q5')riskHorizonTouched=true;
```

**Ersetzen durch:**
```javascript
  if(g==='q5'||g==='rf-horizon')riskHorizonTouched=true;
```

---

## F6 — `captureRiskQuestionnaireState()` ersetzen

**Warum:** Diese Funktion liest die Initialwerte der alten Tab-1-Struktur (rp-income-annual
Input-Feld, alte keSections). Nach der Umstrukturierung gibt es diese Felder nicht mehr.
Die Funktion wird nur zum Speichern des Defaults beim ersten Laden verwendet.

**Grep:**
```
grep -n "function captureRiskQuestionnaireState" 5eyes-electron/frontend/5eyes_v2.html
```

**Gesamte Funktion ersetzen:**
```javascript
function captureRiskQuestionnaireState(){
  // Liefert den initialen Default-Zustand des Formulars (alle Felder leer)
  // Wird von ensureRiskQuestionnaireDefaults() einmalig aufgerufen
  var rfSections = document.querySelectorAll('#r-rf .qsec');
  var rbSections = document.querySelectorAll('#r-rb .qsec');
  return {
    incomeIdx:     getSelectedRiskIndex(rfSections[0]),
    obligIdx:      getSelectedRiskIndex(rfSections[2]),
    wealthIdx:     getSelectedRiskIndex(rfSections[3]),
    savingsIdx:    getSelectedRiskIndex(rfSections[4]),
    horizonIdx:    getSelectedRiskIndex(rfSections[5]),
    goalIdx:       getSelectedRiskIndex(rbSections[0]),
    prefIdx:       getSelectedRiskIndex(rbSections[1]),
    behavIdx:      getSelectedRiskIndex(rbSections[2])
  };
}
```

---

## F7 — `collectRiskAssessmentUiState()` ersetzen

**Grep:**
```
grep -n "function collectRiskAssessmentUiState" 5eyes-electron/frontend/5eyes_v2.html
```

**Gesamte Funktion ersetzen:**
```javascript
function collectRiskAssessmentUiState(){
  var rfSections = document.querySelectorAll('#r-rf .qsec');
  var rbSections = document.querySelectorAll('#r-rb .qsec');

  // Tab 2: Risikofähigkeit — Reihenfolge der .qsec in #r-rf:
  // [0]=F1 Einkommen  [1]=F2 Herkunft(Checkboxen)  [2]=F3 Verpflichtungen
  // [3]=F4 Vermögen   [4]=F5 Sparquote              [5]=F6 Horizont
  var incomeIdx  = getSelectedRiskIndex(rfSections[0]);
  var obligIdx   = getSelectedRiskIndex(rfSections[2]);
  var wealthIdx  = getSelectedRiskIndex(rfSections[3]);
  var savingsIdx = getSelectedRiskIndex(rfSections[4]);
  var horizonIdx = getSelectedRiskIndex(rfSections[5]);

  // Tab 3: Risikobereitschaft (unverändert)
  var goalIdx = -1, prefIdx = -1, behavIdx = -1;
  rbSections.forEach(function(sec, si){
    var sel = sec.querySelector('.qopt.sel');
    if(!sel) return;
    var idx = Array.from(sec.querySelectorAll('.qopt')).indexOf(sel);
    if(si===0) goalIdx=idx;
    else if(si===1) prefIdx=idx;
    else if(si===2) behavIdx=idx;
  });

  // Tab 1: Kenntnisse & Erfahrungen — 2-Spalten-Tabellen als JSON-Objekte
  function collectKeTable(cssClass){
    var result={};
    document.querySelectorAll('input.'+cssClass).forEach(function(cb){
      var row=cb.getAttribute('data-row');
      var col=cb.getAttribute('data-col');
      if(!row||!col) return;
      if(!result[row]) result[row]={known:0,informed:0};
      result[row][col]=cb.checked?1:0;
    });
    return result;
  }
  var knowledgeServices    = collectKeTable('ke-svc');
  var knowledgeInstruments = collectKeTable('ke-ins');

  // F2 Herkunft-Checkboxen (rfSections[1])
  var incomeSources=[];
  var herkunftSection=rfSections[1];
  if(herkunftSection){
    herkunftSection.querySelectorAll('.qcb.sel').forEach(function(el){
      var t=(el.textContent||'').trim();
      if(t) incomeSources.push(t);
    });
  }

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

## F8 — `collectRiskAssessmentUiIssues()` ersetzen

**Grep:**
```
grep -n "function collectRiskAssessmentUiIssues" 5eyes-electron/frontend/5eyes_v2.html
```

**Gesamte Funktion ersetzen:**
```javascript
function collectRiskAssessmentUiIssues(state){
  var s=state||collectRiskAssessmentUiState();
  var issues=[];
  if(s.incomeIdx<0)  issues.push('Frage 3: Regelmässiges Einkommen');
  if(s.obligIdx<0)   issues.push('Frage 5: Finanzielle Verpflichtungen');
  if(s.wealthIdx<0)  issues.push('Frage 6: Freies Vermögen');
  if(s.savingsIdx<0) issues.push('Frage 7: Sparquote');
  if(s.horizonIdx<0) issues.push('Frage 8: Anlagehorizont');
  if(s.goalIdx<0)    issues.push('Frage 9: Anlageziel');
  if(s.prefIdx<0)    issues.push('Frage 10: Risikopräferenz');
  if(s.behavIdx<0)   issues.push('Frage 11: Verlustverhalten');
  return issues;
}
```

---

## F9 — `buildRiskAssessmentPayloadFromUI()` ersetzen

**Grep:**
```
grep -n "function buildRiskAssessmentPayloadFromUI" 5eyes-electron/frontend/5eyes_v2.html
```

**Gesamte Funktion ersetzen:**
```javascript
function buildRiskAssessmentPayloadFromUI(){
  var state=collectRiskAssessmentUiState();
  var issues=collectRiskAssessmentUiIssues(state);
  if(issues.length) return null;

  // ── Risikofähigkeit — Bracket-basiert nach Referenzmodell Eignungspruefung ────────────────
  var incomePoints     = RISK_INCOME_POINTS[Math.max(0,Math.min(RISK_INCOME_POINTS.length-1,     state.incomeIdx))];
  var obligationPoints = RISK_OBLIGATIONS_POINTS[Math.max(0,Math.min(RISK_OBLIGATIONS_POINTS.length-1, state.obligIdx))];
  var wealthPoints     = RISK_WEALTH_POINTS[Math.max(0,Math.min(RISK_WEALTH_POINTS.length-1,     state.wealthIdx))];
  var savingsPoints    = RISK_SAVINGS_POINTS[Math.max(0,Math.min(RISK_SAVINGS_POINTS.length-1,   state.savingsIdx))];

  var horizon=RISK_HORIZON_OPTIONS[state.horizonIdx];
  var horizonStorageLabel=canonicalRiskHorizonLabel(horizon.label);
  var capacityTotal=incomePoints+obligationPoints+wealthPoints+savingsPoints;
  var capacityBand=findRiskCapacityBand(capacityTotal);
  var capScore=RISK_CAPACITY_MATRIX[horizon.years+','+capacityBand.band];

  // ── Risikobereitschaft (unverändert) ──────────────────────────────────────
  var goalPoints  = Math.max(1,state.goalIdx+1);
  var prefPoints  = Math.max(1,state.prefIdx+1);
  var behavPoints = Math.max(1,state.behavIdx+1);
  var willingnessTotal=goalPoints+prefPoints+behavPoints;
  var rawWillScore=Math.round(((willingnessTotal-3)/9)*90+10);
  var willScore=Math.max(10,Math.min(100,rawWillScore));

  // ── Final: MIN(cap, will) — FIDLEG-konform ────────────────────────────────
  var finalScore=Math.min(capScore,willScore);
  var mandateType=(currentMandateData&&currentMandateData.mandate_type)||null;
  if(mandateType==='FZK') finalScore=Math.min(finalScore,75);
  var finalProfile=riskScoreToProfile(finalScore);

  // ── Answer-Labels für Audit-Trail ─────────────────────────────────────────
  var rfSecs=state.rfSections, rbSecs=state.rbSections;
  function optLabel(secs,si,idx){
    var sec=secs[si]; if(!sec) return '';
    var opts=sec.querySelectorAll('.qopt');
    var el=opts[idx]; if(!el) return '';
    var t=el.querySelector('.qtxt');
    return t?t.textContent.trim():el.textContent.trim();
  }
  var incomeSrcLabel=state.incomeSources.length?state.incomeSources.join(', '):'Keine Angabe';

  return {
    payload:{
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
      answers:[
        {question_number:1,question_section:'Kenntnisse & Erfahrungen',answer_label:'Finanzdienstleistungen: '+JSON.stringify(state.knowledgeServices),answer_points:0},
        {question_number:2,question_section:'Kenntnisse & Erfahrungen',answer_label:'Finanzinstrumente: '+JSON.stringify(state.knowledgeInstruments),answer_points:0},
        {question_number:3,question_section:'Risikofähigkeit',answer_label:optLabel(rfSecs,0,state.incomeIdx),answer_points:incomePoints},
        {question_number:4,question_section:'Risikofähigkeit',answer_label:'Herkunft: '+incomeSrcLabel,answer_points:0},
        {question_number:5,question_section:'Risikofähigkeit',answer_label:optLabel(rfSecs,2,state.obligIdx),answer_points:obligationPoints},
        {question_number:6,question_section:'Risikofähigkeit',answer_label:optLabel(rfSecs,3,state.wealthIdx),answer_points:wealthPoints},
        {question_number:7,question_section:'Risikofähigkeit',answer_label:optLabel(rfSecs,4,state.savingsIdx),answer_points:savingsPoints},
        {question_number:8,question_section:'Risikofähigkeit',answer_label:horizon.label+' · Matrix-Faktor',answer_points:0},
        {question_number:9,question_section:'Risikobereitschaft',answer_label:optLabel(rbSecs,0,state.goalIdx),answer_points:goalPoints},
        {question_number:10,question_section:'Risikobereitschaft',answer_label:optLabel(rbSecs,1,state.prefIdx),answer_points:prefPoints},
        {question_number:11,question_section:'Risikobereitschaft',answer_label:optLabel(rbSecs,2,state.behavIdx),answer_points:behavPoints}
      ]
    },
    capScore:capScore,
    capProfile:capacityBand.label,
    willScore:willScore,
    willProfile:riskWillingnessProfile(willScore),
    finalScore:finalScore,
    finalProfile:finalProfile,
    raw:{
      incomeIdx:state.incomeIdx,      obligIdx:state.obligIdx,
      wealthIdx:state.wealthIdx,      savingsIdx:state.savingsIdx,
      horizonIdx:state.horizonIdx,    goalIdx:state.goalIdx,
      prefIdx:state.prefIdx,          behavIdx:state.behavIdx,
      incomePoints:incomePoints,      obligationPoints:obligationPoints,
      wealthPoints:wealthPoints,      savingsPoints:savingsPoints,
      capacityTotal:capacityTotal,    horizonLabel:horizon.label
    }
  };
}
```

---

## F10 — `resetRiskQuestionnaireToDefaults()` ersetzen

**Grep:**
```
grep -n "function resetRiskQuestionnaireToDefaults" 5eyes-electron/frontend/5eyes_v2.html
```

**Gesamte Funktion ersetzen:**
```javascript
function resetRiskQuestionnaireToDefaults(){
  riskHorizonTouched=false;
  riskAssessmentUiDirty=false;
  // Tab 1: Kenntnisse-Checkboxen leeren
  document.querySelectorAll('input.ke-svc,input.ke-ins').forEach(function(cb){ cb.checked=false; });
  // Tab 2: F2 Herkunft-Checkboxen leeren
  var rfSections=document.querySelectorAll('#r-rf .qsec');
  if(rfSections[1]) rfSections[1].querySelectorAll('.qcb').forEach(function(el){ el.classList.remove('sel'); });
  // Tab 2: Radio-Optionen leeren
  document.querySelectorAll('#r-rf .qopt').forEach(function(el){ el.classList.remove('sel'); });
  // Tab 3: Radio-Optionen leeren
  document.querySelectorAll('#r-rb .qopt').forEach(function(el){ el.classList.remove('sel'); });
}
```

---

## F11 — `hydrateRiskQuestionnaire()` ersetzen

**Warum:** Diese Funktion stellt den Zustand des Formulars aus einem gespeicherten
Risk-Assessment wieder her. Sie muss auf die neue DOM-Struktur angepasst werden.

**Grep:**
```
grep -n "function hydrateRiskQuestionnaire" 5eyes-electron/frontend/5eyes_v2.html
```

**Gesamte Funktion ersetzen:**
```javascript
function hydrateRiskQuestionnaire(saved){
  resetRiskQuestionnaireToDefaults();
  if(!saved) return;
  var answers=saved.answers||[];
  function findAnswer(num){ return answers.find(function(a){ return a.question_number===num; }); }
  var rfSections=document.querySelectorAll('#r-rf .qsec');
  var rbSections=document.querySelectorAll('#r-rb .qsec');

  // Tab 1: Kenntnisse-Tabellen aus JSON-Feldern des gespeicherten Assessments
  if(saved.knowledge_services_json){
    try{
      var svc=JSON.parse(saved.knowledge_services_json);
      Object.keys(svc).forEach(function(row){
        ['known','informed'].forEach(function(col){
          var cb=document.querySelector('input.ke-svc[data-row="'+row+'"][data-col="'+col+'"]');
          if(cb) cb.checked=!!(svc[row]&&svc[row][col]);
        });
      });
    }catch(e){}
  }
  if(saved.knowledge_instruments_json){
    try{
      var ins=JSON.parse(saved.knowledge_instruments_json);
      Object.keys(ins).forEach(function(row){
        ['known','informed'].forEach(function(col){
          var cb=document.querySelector('input.ke-ins[data-row="'+row+'"][data-col="'+col+'"]');
          if(cb) cb.checked=!!(ins[row]&&ins[row][col]);
        });
      });
    }catch(e){}
  }

  // F2: Herkunft-Checkboxen wiederherstellen (aus income_sources_json oder Answer Q4)
  var sourcesToRestore=[];
  if(saved.income_sources_json){
    try{ sourcesToRestore=JSON.parse(saved.income_sources_json); }catch(e){}
  } else {
    var q4=findAnswer(4);
    if(q4&&q4.answer_label){
      var idx=q4.answer_label.indexOf('Herkunft:');
      if(idx>=0){
        sourcesToRestore=q4.answer_label.slice(idx+'Herkunft:'.length).split(',')
          .map(function(s){ return normalizeRiskText(s); }).filter(Boolean);
      }
    }
  }
  if(sourcesToRestore.length&&rfSections[1]){
    rfSections[1].querySelectorAll('.qcb').forEach(function(el){
      var t=normalizeRiskText((el.textContent||''));
      if(sourcesToRestore.indexOf(t)>=0) el.classList.add('sel');
    });
  }

  // Tab 2: Bracket-Optionen via Answer-Label wiederherstellen
  var q3=findAnswer(3);  // F1 Einkommen
  var q5=findAnswer(5);  // F3 Verpflichtungen
  var q6=findAnswer(6);  // F4 Vermögen
  var q7=findAnswer(7);  // F5 Sparquote
  var q8=findAnswer(8);  // F6 Horizont
  if(q3) selectRiskOptionByLabel(rfSections[0],q3.answer_label);
  if(q5) selectRiskOptionByLabel(rfSections[2],q5.answer_label);
  if(q6) selectRiskOptionByLabel(rfSections[3],q6.answer_label);
  if(q7) selectRiskOptionByLabel(rfSections[4],q7.answer_label);
  if(q8){
    var hLabel=(q8.answer_label||'').replace(' · Matrix-Faktor','').trim();
    selectRiskOptionByLabel(rfSections[5],hLabel);
    riskHorizonTouched=true;
  }

  // Tab 3: Risikobereitschaft (unverändert)
  var q9=findAnswer(9); var q10=findAnswer(10); var q11=findAnswer(11);
  if(q9)  selectRiskOptionByLabel(rbSections[0],q9.answer_label);
  if(q10) selectRiskOptionByLabel(rbSections[1],q10.answer_label);
  if(q11) selectRiskOptionByLabel(rbSections[2],q11.answer_label);
}
```

---

---

# TEIL 5: FRONTEND — PDF-SEKTION

---

## F12 — Kenntnisse & Erfahrungen im PDF (Anlagestrategie)

**Grep für Einfügeposition im PDF:**
```
grep -n "Section 2: Risikoprofil" 5eyes-electron/frontend/5eyes_v2.html
```

**Suche exakt diese Zeile (eindeutig):**
```javascript
  // Section 2: Risikoprofil
  var riskHtml='<div style="margin-top:28px;margin-bottom:22px">'
```

**Davor einfügen (neue Sektion "Kenntnisse & Erfahrungen" erscheint VOR dem Risikoprofil-Block):**
```javascript
  // Section 1b: Kenntnisse & Erfahrungen (Referenzmodell Eignungspruefung Seite 1)
  var keHtml='';
  if(riskData&&(riskData.knowledge_services_json||riskData.knowledge_instruments_json)){
    function _buildKeTable(title,jsonStr){
      var data={}; try{data=JSON.parse(jsonStr||'{}');}catch(e){}
      var keys=Object.keys(data);
      if(!keys.length) return '';
      var rows=keys.map(function(row){
        return '<tr>'
          +'<td style="padding:5px 10px;font-size:10px;color:#334155;border-bottom:1px solid #f1f5f9">'+escapeHtml(row)+'</td>'
          +'<td style="padding:5px 10px;text-align:center;border-bottom:1px solid #f1f5f9;border-left:1px solid #e2e8f0;font-size:11px">'+(data[row]&&data[row].known?'☑':'☐')+'</td>'
          +'<td style="padding:5px 10px;text-align:center;border-bottom:1px solid #f1f5f9;border-left:1px solid #e2e8f0;font-size:11px">'+(data[row]&&data[row].informed?'☑':'☐')+'</td>'
          +'</tr>';
      }).join('');
      return '<div style="margin-bottom:10px">'
        +'<table style="width:100%;border-collapse:collapse;border:1px solid #e2e8f0;border-radius:6px;overflow:hidden">'
        +'<thead><tr style="background:#f8fafc">'
        +'<th style="padding:6px 10px;text-align:left;font-size:9px;font-weight:600;letter-spacing:0.06em;text-transform:uppercase;color:#64748b">'+escapeHtml(title)+'</th>'
        +'<th style="padding:6px 10px;text-align:center;font-size:9px;font-weight:600;letter-spacing:0.06em;text-transform:uppercase;color:#64748b;border-left:1px solid #e2e8f0">Kenntnisse vorhanden</th>'
        +'<th style="padding:6px 10px;text-align:center;font-size:9px;font-weight:600;letter-spacing:0.06em;text-transform:uppercase;color:#64748b;border-left:1px solid #e2e8f0">Aufklärung erhalten</th>'
        +'</tr></thead>'
        +'<tbody>'+rows+'</tbody>'
        +'</table></div>';
    }
    keHtml='<div style="margin-bottom:24px">'
      +'<div style="font-size:9px;font-weight:700;letter-spacing:0.13em;text-transform:uppercase;color:#64748b;border-bottom:2px solid #e2e8f0;padding-bottom:6px;margin-bottom:12px">Kenntnisse &amp; Erfahrungen (Eignungspruefung)</div>'
      +_buildKeTable('Finanzdienstleistungen',riskData.knowledge_services_json||'{}')
      +_buildKeTable('Finanzinstrumente',riskData.knowledge_instruments_json||'{}')
      +'</div>';
  }
```

**Dann die Variable `keHtml` in die endgültige HTML-Ausgabe einfügen.**

**Grep für den Output-Zusammenbau:**
```
grep -n "riskHtml\+\|keHtml\|docContent\s*=" 5eyes-electron/frontend/5eyes_v2.html | head -10
```

Suche den Block wo `riskHtml` in den finalen HTML-String eingefügt wird.
**`riskHtml` an der Stelle wo es zugewiesen wird durch `keHtml + riskHtml` ersetzen:**

Beispiel — wenn dort steht:
```javascript
var docContent = headerHtml + riskHtml + allocHtml + ...
```
Ersetzen durch:
```javascript
var docContent = headerHtml + keHtml + riskHtml + allocHtml + ...
```

---

---

# TEIL 6: FEATURE 2 — PORTFOLIO ETF PHASE 1

---

## P1 — Portfolio-Tab Header

**Grep:**
```
grep -n "Portfolio.*Einzeltitel" 5eyes-electron/frontend/5eyes_v2.html
```

**Suche:**
```
Portfolio &amp; Einzeltitel
```

**Ersetzen durch:**
```
Portfolio — ETFs &amp; Fonds
```

---

## P2 — Checkbox "Nur Fonds/ETFs" standardmässig aktiv

**Grep:**
```
grep -n "aa-product-funds-only" 5eyes-electron/frontend/5eyes_v2.html
```

**Suche:**
```html
<input type="checkbox" id="aa-product-funds-only">
```

**Ersetzen durch:**
```html
<input type="checkbox" id="aa-product-funds-only" checked>
```

---

---

# TEIL 7: VERIFIKATION

---

## Schritt A — JS-Syntax prüfen
```bash
node --check 5eyes-electron/frontend/5eyes_v2.html
```
**Erwartetes Ergebnis:** Keine Ausgabe (0 Fehler).

## Schritt B — Backend starten
```bash
cd 5eyes-backend
python -m uvicorn main:app --reload --port 8000
```
**Erwartetes Ergebnis:** Kein Fehler beim Start, DB-Migration läuft durch.

## Schritt C — DB-Spalten prüfen
```bash
cd 5eyes-backend
python -c "
from sqlalchemy import text
from database import SessionLocal
db = SessionLocal()
cols = db.execute(text('PRAGMA table_info(risk_assessments)')).fetchall()
names = [c[1] for c in cols]
for col in ['knowledge_services_json','knowledge_instruments_json','income_sources_json']:
    print(col, '-> OK' if col in names else '-> FEHLT!')
db.close()
"
```
**Erwartetes Ergebnis:** Alle 3 Spalten zeigen `-> OK`.

## Schritt D — API-Test Risikoprofil speichern
```bash
# Token holen (Backend muss laufen)
TOKEN=$(curl -s -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin"}' | python -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

# Risikoprofil mit neuen Feldern speichern (Mandat-ID anpassen)
curl -s -X POST http://localhost:8000/mandates/TEST-MANDATE-ID/risk-assessments \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "q_income_points": 3,
    "q_obligations_points": 3,
    "q_savings_points": 6,
    "q_wealth_points": 9,
    "investment_horizon_label": "8 bis 11 Jahre",
    "investment_horizon_years": 9,
    "q_investment_goal_points": 3,
    "q_risk_preference_points": 3,
    "q_risk_behavior_points": 3,
    "knowledge_services_json": "{\"Anlageberatung\":{\"known\":1,\"informed\":1}}",
    "knowledge_instruments_json": "{\"Anlagefonds\":{\"known\":1,\"informed\":1}}",
    "income_sources_json": "[\"Berufliche Tätigkeit\"]"
  }' | python -m json.tool | grep -E "knowledge|income_sources|final_profile"
```
**Erwartetes Ergebnis:** Alle 3 neuen Felder erscheinen im Response.

## Schritt E — Scoring-Check
Manuelle Rechnung für Verifikation:
- `q_income_points=3` + `q_obligations_points=3` + `q_savings_points=6` + `q_wealth_points=9` = **21 Punkte** → Band "Wachstumsorientiert" (10-13 wäre Wachstumsorientiert... 21 ist Dynamisch)
- Horizont 8-11 Jahre → years=9, Band=5 → Matrix[9,5]=70 → capScore=70
- willingness=3+3+3=9 → raw=(9-3/9)*90+10=70 → willScore=70
- finalScore=MIN(70,70)=70 → Profil "Wachstumsorientiert"

---

---

# CHECKLISTE — Revision vor Commit

**Backend:**
- [ ] `models/profiling.py`: 3 neue optionale Columns eingefügt
- [ ] `schemas/profiling.py`: `RiskAssessmentCreate` UND `RiskAssessmentResponse` erweitert
- [ ] `database.py`: 3 ensure_column Calls vorhanden
- [ ] `risk_scoring.py`: NICHT verändert (kein Touch)
- [ ] `routers/profiling.py`: NICHT verändert (kein Touch)

**Frontend — Konstanten:**
- [ ] `RISK_HORIZON_OPTIONS` hat 6 Einträge
- [ ] `RISK_INCOME_POINTS` existiert
- [ ] `RISK_OBLIGATIONS_POINTS` existiert (INVERS: [4,3,2,1,0])
- [ ] `RISK_WEALTH_POINTS` existiert
- [ ] `RISK_SAVINGS_POINTS` hat 5 Einträge [0,3,6,9,12]
- [ ] `RISK_RESERVE_POINTS` und `RISK_FREE_WEALTH_POINTS` noch vorhanden (Legacy, nicht gelöscht)

**Frontend — HTML:**
- [ ] Tab 1 (`r-ke`): Zeigt 2 Grid-Tabellen mit `.ke-svc` und `.ke-ins` Checkboxen
- [ ] Tab 2 (`r-rf`): Zeigt F1-F6 als `.qopt`-Selections (F2 als `.qcb` Checkboxen)
- [ ] Tab 2: F6 Horizont hat 6 Optionen
- [ ] Tab 3 (`r-rb`): NICHT verändert

**Frontend — JS-Funktionen:**
- [ ] `sq()`: `g==='rf-horizon'` Bedingung eingefügt
- [ ] `captureRiskQuestionnaireState()`: Neue Version ohne alte Felder
- [ ] `collectRiskAssessmentUiState()`: Neue Version mit rfSections[0..5]
- [ ] `collectRiskAssessmentUiIssues()`: Neue Version, 8 Checks
- [ ] `buildRiskAssessmentPayloadFromUI()`: Neue Version mit Bracket-Scoring
- [ ] `resetRiskQuestionnaireToDefaults()`: Neue Version
- [ ] `hydrateRiskQuestionnaire()`: Neue Version

**Frontend — PDF:**
- [ ] `keHtml` Variable wird vor `riskHtml` erzeugt
- [ ] `keHtml` wird im finalen Document-Content eingefügt

**Feature 2:**
- [ ] Portfolio-Tab Header geändert
- [ ] Checkbox `aa-product-funds-only` hat `checked`-Attribut

**Abschlusskontrolle:**
- [ ] `node --check 5eyes-electron/frontend/5eyes_v2.html` → 0 Fehler
- [ ] Backend startet ohne Fehler
- [ ] DB-Spalten vorhanden (Schritt C bestanden)

---

## NICHT ÄNDERN (explizite Ausschlüsse)

Die folgenden Dateien/Funktionen dürfen **nicht** angefasst werden:
- `risk_scoring.py` — keine Änderungen
- `routers/profiling.py` — keine Änderungen
- Tab 3 (`r-rb`) HTML — keine Änderungen
- `riskOptionText()` — keine Änderungen
- `selectRiskOptionByLabel()` — keine Änderungen
- `parseRiskAnnualInput()` — keine Änderungen (Legacy, bleibt)
- `parseRiskIncomeOrigins()` — keine Änderungen (Legacy, bleibt)
- `getSelectedRiskIndex()` — keine Änderungen
- `normalizeRiskText()` — keine Änderungen
