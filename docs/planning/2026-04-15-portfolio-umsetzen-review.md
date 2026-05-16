# Spec — Portfolio Umsetzen & Review Strategie-Spiegel

## Meta

- Titel: Portfolio Umsetzen (Snapshot + PDF) + Review Strategie-Spiegel (Drift + Rebalancing)
- Datum: 2026-04-15
- Owner: Emanuele
- Branch-Vorschlag: `codex/portfolio-umsetzen-review`

---

## Warum dieses Feature existiert — Fachlicher Kontext

5eyes ist ein **Beratungs-Tool, kein Vermögensverwaltungs-System**.
Der Berater trifft den Kunden 1–2x pro Jahr. Er hat **keine Echtzeit-Depotdaten**.

Das bedeutet:

- Die SOLL-Allokation wird nach jedem Beratungsgespräch **eingefroren** ("Portfolio umsetzen")
- Beim nächsten Gespräch zeigt der Review: wie hätte sich diese Strategie entwickeln sollen?
- Der Vergleich basiert auf historischen Asset-Class-Returns — keine API, keine Live-Daten
- Compliance-Nachweis: jeder Snapshot = datiertes Dokument mit Berater + Risikoprofil + Allokation

**Tab-Reihenfolge im System:**
`sd → vg → cf → ub → rp → al → po → rv → sr`
- `al` = Asset Allocation (SOLL berechnen, hier sitzt der neue "Portfolio Umsetzen"-Button)
- `rv` = Review (hier sitzt der neue Strategie-Spiegel + Rebalancing-Sektion)
- `sr` = Zusammenfassung (Monte Carlo, Ziele, Zukunftsprojektion — NICHT Teil dieser Spec)

---

## Scope dieser Spec

### Sprint A — Portfolio Umsetzen

1. Neue DB-Tabelle `strategy_snapshots`
2. Neue DB-Tabelle `asset_class_annual_returns` (historische Jahres-Returns, pre-seeded)
3. Neuer Backend-Router `routers/snapshots.py` mit 3 Endpoints
4. Frontend: "Portfolio Umsetzen"-Button in `page-al` + Modal
5. Frontend: Modal speichert Snapshot via API und öffnet danach `printAnlagestrategie()`

### Sprint B — Review Strategie-Spiegel

6. Neuer Backend-Endpoint `GET /mandates/{id}/strategy-snapshots/latest/drift`
   → berechnet theoretische Drift der SOLL-Allokation seit Snapshot-Datum
7. Frontend: neue Sektion "Strategie-Spiegel" in `page-rv` (oberhalb des existierenden Portfolio-Check)
8. Frontend: einfacher Line-Chart mit 3 Linien (Strategie / SPI-Proxy / Konservativ-Proxy)
9. Frontend: Drift-Tabelle mit Ampel-Status pro Asset Class (nutzt bestehende Band-Logik)

---

## Nicht-Scope

- PDF-Layout (der bestehende `buildAnlagestrategieDocHtml()` + `printAnlagestrategie()` bleibt unverändert — wir rufen ihn nur gezielt nach dem Snapshot auf)
- Monte Carlo / Zukunftsprojektion → bleibt in `sr` (Zusammenfassung)
- Echte Live-Depotdaten → existiert nicht, wird nicht eingebaut
- Benchmark-Daten von einer externen API → kein Live-Feed, nur statische Jahrestabelle
- Mehrere Snapshots gleichzeitig vergleichen → nur neuester Snapshot wird im Review verwendet

---

## DB-Schema — Neue Tabellen

### Tabelle: `strategy_snapshots`

```sql
CREATE TABLE IF NOT EXISTS strategy_snapshots (
  id                        TEXT PRIMARY KEY,
  mandate_id                TEXT NOT NULL REFERENCES mandates(id),
  snapshot_date             TEXT NOT NULL,          -- ISO-Date, z.B. '2024-03-15'
  advisory_assets_rappen    INTEGER NOT NULL,        -- Beratungsvermögen in Rappen
  risk_profile_score        INTEGER NOT NULL,        -- finalScore×10, z.B. 65
  risk_profile_label        TEXT NOT NULL,           -- 'Ausgewogen', 'Wachstum', etc.
  -- SOLL-Allokation in BPS (muss zusammen 10000 ergeben)
  soll_equities_bps         INTEGER NOT NULL,
  soll_bonds_bps            INTEGER NOT NULL,
  soll_real_estate_bps      INTEGER NOT NULL,
  soll_liquidity_bps        INTEGER NOT NULL,
  soll_alternatives_bps     INTEGER NOT NULL,
  -- Band-Grenzen aus target_allocations (für spätere Drift-Beurteilung)
  band_equities_lo_bps      INTEGER,
  band_equities_hi_bps      INTEGER,
  band_bonds_lo_bps         INTEGER,
  band_bonds_hi_bps         INTEGER,
  band_real_estate_lo_bps   INTEGER,
  band_real_estate_hi_bps   INTEGER,
  band_liquidity_lo_bps     INTEGER,
  band_liquidity_hi_bps     INTEGER,
  band_alternatives_lo_bps  INTEGER,
  band_alternatives_hi_bps  INTEGER,
  -- Optionale Zusatzinfos
  advisor_note              TEXT,                    -- Freitext des Beraters
  goals_summary_json        TEXT,                    -- JSON: [{label, target_amount_rappen, target_date}]
  -- Audit
  created_by                TEXT NOT NULL REFERENCES users(id),
  created_at                TEXT NOT NULL,
  updated_at                TEXT NOT NULL,
  deleted_at                TEXT                     -- Soft-Delete (Standard-Pattern)
);
CREATE INDEX IF NOT EXISTS ix_strategy_snapshots_mandate
  ON strategy_snapshots(mandate_id, deleted_at, snapshot_date DESC);
```

### Tabelle: `asset_class_annual_returns`

Speichert **realisierte** Jahres-Returns pro Asset Class. Wird vom Admin jährlich manuell aktualisiert.
Wird für die theoretische Drift-Berechnung und den Line-Chart im Review verwendet.

```sql
CREATE TABLE IF NOT EXISTS asset_class_annual_returns (
  id            TEXT PRIMARY KEY,
  year          INTEGER NOT NULL,   -- z.B. 2023
  asset_class   TEXT NOT NULL,      -- 'Aktien' | 'Obligationen' | 'Immobilien' | 'Liquiditaet' | 'Alternative'
  return_bps    INTEGER NOT NULL,   -- realisierter Jahres-Return in BPS, z.B. 1850 = +18.5%
  source        TEXT,               -- 'SPI', 'SBI', 'REAL_EST_CH', intern, etc.
  created_at    TEXT NOT NULL,
  updated_at    TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_asset_class_annual_returns_year_class
  ON asset_class_annual_returns(year, asset_class);
```

**Pre-Seed-Daten (in `database.py` einfügen, nur wenn Tabelle leer):**

Asset Class Keys sind identisch zu den Engine-Keys aus CODEX_GUIDE.md Abschnitt 11:
`Aktien`, `Obligationen`, `Immobilien`, `Liquiditaet`, `Alternative`

```python
SEED_ASSET_CLASS_RETURNS = [
  # year, asset_class,     return_bps  (Quelle: SPI / SBI / KGAST / interne CMA)
  (2015, 'Aktien',         290),
  (2015, 'Obligationen',   100),
  (2015, 'Immobilien',     180),
  (2015, 'Liquiditaet',   -30),
  (2015, 'Alternative',    50),
  (2016, 'Aktien',        -180),
  (2016, 'Obligationen',   20),
  (2016, 'Immobilien',    640),
  (2016, 'Liquiditaet',   -30),
  (2016, 'Alternative',   380),
  (2017, 'Aktien',        2010),
  (2017, 'Obligationen',   140),
  (2017, 'Immobilien',    550),
  (2017, 'Liquiditaet',   -30),
  (2017, 'Alternative',   490),
  (2018, 'Aktien',        -870),
  (2018, 'Obligationen',    30),
  (2018, 'Immobilien',    110),
  (2018, 'Liquiditaet',   -10),
  (2018, 'Alternative',  -980),
  (2019, 'Aktien',        3040),
  (2019, 'Obligationen',   390),
  (2019, 'Immobilien',    820),
  (2019, 'Liquiditaet',   -30),
  (2019, 'Alternative',   910),
  (2020, 'Aktien',         360),
  (2020, 'Obligationen',   180),
  (2020, 'Immobilien',    250),
  (2020, 'Liquiditaet',   -50),
  (2020, 'Alternative',   420),
  (2021, 'Aktien',        2320),
  (2021, 'Obligationen',  -120),
  (2021, 'Immobilien',    710),
  (2021, 'Liquiditaet',   -70),
  (2021, 'Alternative',   630),
  (2022, 'Aktien',       -1650),
  (2022, 'Obligationen', -1280),
  (2022, 'Immobilien',  -1030),
  (2022, 'Liquiditaet',   180),
  (2022, 'Alternative',  -810),
  (2023, 'Aktien',        1980),
  (2023, 'Obligationen',   510),
  (2023, 'Immobilien',    -90),
  (2023, 'Liquiditaet',   150),
  (2023, 'Alternative',   720),
  (2024, 'Aktien',        1320),
  (2024, 'Obligationen',   310),
  (2024, 'Immobilien',    420),
  (2024, 'Liquiditaet',   100),
  (2024, 'Alternative',   890),
]
```

OWNER-DECISION: Zahlen oben sind Schätzwerte — Emanuele soll diese mit Referenzanbieter-internen CMA-Daten kalibrieren bevor Produktion.

---

## Backend — Neue Datei: `routers/snapshots.py`

**Neuen Router in `main.py` registrieren** (analog zu allen anderen Routern):
```python
from routers import snapshots
app.include_router(snapshots.router)
```

### Endpoint 1: Snapshot erstellen

```
POST /mandates/{mandate_id}/strategy-snapshots
```

**Request Body (Pydantic Schema):**
```python
class StrategySnapshotCreate(BaseModel):
    snapshot_date: str                    # ISO-Date 'YYYY-MM-DD'
    advisory_assets_rappen: int
    risk_profile_score: int               # final_score_x10
    risk_profile_label: str
    soll_equities_bps: int
    soll_bonds_bps: int
    soll_real_estate_bps: int
    soll_liquidity_bps: int
    soll_alternatives_bps: int
    band_equities_lo_bps: Optional[int] = None
    band_equities_hi_bps: Optional[int] = None
    band_bonds_lo_bps: Optional[int] = None
    band_bonds_hi_bps: Optional[int] = None
    band_real_estate_lo_bps: Optional[int] = None
    band_real_estate_hi_bps: Optional[int] = None
    band_liquidity_lo_bps: Optional[int] = None
    band_liquidity_hi_bps: Optional[int] = None
    band_alternatives_lo_bps: Optional[int] = None
    band_alternatives_hi_bps: Optional[int] = None
    advisor_note: Optional[str] = None
    goals_summary_json: Optional[str] = None   # JSON-String

    @validator('soll_equities_bps')
    def check_bps_sum(cls, v, values):
        total = v + values.get('soll_bonds_bps', 0) + values.get('soll_real_estate_bps', 0) \
                + values.get('soll_liquidity_bps', 0) + values.get('soll_alternatives_bps', 0)
        if abs(total - 10000) > 50:   # 0.5% Toleranz für Rundung
            raise ValueError(f'BPS-Summe {total} != 10000')
        return v
```

**Response:** `StrategySnapshotResponse` (alle Felder + `id`, `created_at`)

**Logik:**
- `mandate_id` aus URL prüfen: Mandat muss existieren und `deleted_at IS NULL`
- `created_by` = aktueller User aus JWT-Token
- `id` = `str(uuid4())`
- `created_at` = `updated_at` = `datetime.utcnow().isoformat()`
- Kein Soft-Delete-Check der vorherigen Snapshots — mehrere Snapshots pro Mandat erlaubt

### Endpoint 2: Alle Snapshots eines Mandats

```
GET /mandates/{mandate_id}/strategy-snapshots
```

**Response:** `List[StrategySnapshotResponse]`, sortiert nach `snapshot_date DESC`
Filter: `deleted_at IS NULL`

### Endpoint 3: Drift-Berechnung (neuester Snapshot)

```
GET /mandates/{mandate_id}/strategy-snapshots/latest/drift
```

**Was dieser Endpoint berechnet:**

Schritt 1 — Neuesten Snapshot laden:
```python
snapshot = db.query(StrategySnapshot)\
  .filter(StrategySnapshot.mandate_id == mandate_id,
          StrategySnapshot.deleted_at == None)\
  .order_by(StrategySnapshot.snapshot_date.desc())\
  .first()
```

Schritt 2 — Alle Jahres-Returns seit `snapshot_date` laden:
```python
snapshot_year = int(snapshot.snapshot_date[:4])
current_year = datetime.utcnow().year
returns = db.query(AssetClassAnnualReturn)\
  .filter(AssetClassAnnualReturn.year >= snapshot_year,
          AssetClassAnnualReturn.year < current_year)\
  .all()
```

Schritt 3 — Theoretische Portfolio-Drift berechnen:

Startallokation = SOLL in BPS pro Asset Class.
Für jedes Jahr werden die Werte mit `(1 + return_bps / 10000)` skaliert:

```python
ASSET_CLASSES = ['Aktien', 'Obligationen', 'Immobilien', 'Liquiditaet', 'Alternative']
SOLL_FIELDS = {
  'Aktien': 'soll_equities_bps', 'Obligationen': 'soll_bonds_bps',
  'Immobilien': 'soll_real_estate_bps', 'Liquiditaet': 'soll_liquidity_bps',
  'Alternative': 'soll_alternatives_bps'
}
# Startwerte (normiert auf 10000 als Gesamtportfolio-Wert)
weights = {ac: getattr(snapshot, SOLL_FIELDS[ac]) / 10000.0 for ac in ASSET_CLASSES}
# returns_by_year: dict[year -> dict[asset_class -> return_bps]]
for year in sorted(returns_by_year.keys()):
    new_weights = {}
    for ac in ASSET_CLASSES:
        r = returns_by_year[year].get(ac, 0) / 10000.0
        new_weights[ac] = weights[ac] * (1 + r)
    total = sum(new_weights.values())
    weights = {ac: v / total for ac, v in new_weights.items()} if total > 0 else weights
# Drift-Result: neue Gewichte in BPS
drifted_bps = {ac: round(w * 10000) for ac, w in weights.items()}
```

Schritt 4 — Benchmark-Linien berechnen (für den Chart):

Zwei synthetische Benchmarks aus denselben Jahres-Returns:
- **"SPI-Proxy"**: 70% Aktien / 20% Obligationen / 5% Immobilien / 5% Liquiditaet (aggressiv)
- **"Konservativ-Proxy"**: 20% Aktien / 55% Obligationen / 15% Immobilien / 10% Liquiditaet

Pro Benchmark: kumulierter Portfolio-Return ab `snapshot_date` pro Jahr, normiert auf 100 als Startwert.

**Response Schema:**
```python
class DriftResult(BaseModel):
    snapshot_id: str
    snapshot_date: str
    advisory_assets_rappen: int
    risk_profile_label: str
    # Originale SOLL-Allokation
    original: dict           # {'Aktien': 4500, 'Obligationen': 3000, ...} in BPS
    # Theoretisch gedriftete Allokation heute
    drifted: dict            # {'Aktien': 5200, 'Obligationen': 2700, ...} in BPS
    # Delta in BPS (positiv = übergewichtet)
    delta: dict              # {'Aktien': 700, 'Obligationen': -300, ...}
    # Bandgrenzen aus Snapshot
    bands: dict              # {'Aktien': {'lo': 4000, 'hi': 5500}, ...}
    # Ampel pro Asset Class
    status: dict             # {'Aktien': 'red'|'yellow'|'green', ...}
    # Chart-Daten (kumulierter Return, Startwert = 100)
    chart_years: list        # [2024, 2025]
    chart_strategy: list     # [100, 114.2]   — Ihre Strategie
    chart_spi_proxy: list    # [100, 123.1]   — SPI-ähnlich
    chart_conservative: list # [100, 108.3]   — Konservativ
    # Hat sich überhaupt etwas verändert (nur relevant wenn < 1 Jahr)
    has_drift_data: bool
```

**Ampel-Logik:**
```python
def classify_status(ac, drifted_bps, snapshot) -> str:
    delta = drifted_bps[ac] - original_bps[ac]
    lo_field = f'band_{FIELD_MAP[ac]}_lo_bps'
    hi_field = f'band_{FIELD_MAP[ac]}_hi_bps'
    lo = getattr(snapshot, lo_field)
    hi = getattr(snapshot, hi_field)
    if lo is None or hi is None:
        # Kein Band gespeichert: Faustregeln
        if abs(delta) <= 100: return 'green'    # <= 1% Abweichung
        if abs(delta) <= 300: return 'yellow'   # <= 3% Abweichung
        return 'red'
    drifted_val = drifted_bps[ac]
    if lo <= drifted_val <= hi: return 'green'
    band_width = hi - lo
    tolerance = max(200, round(band_width * 0.25))  # 25% Bandbreite als Puffer
    if (lo - tolerance) <= drifted_val <= (hi + tolerance): return 'yellow'
    return 'red'
```

---

## Backend — DB-Migration in `database.py`

In `ensure_runtime_columns()` (oder analog als separate `ensure_tables()`-Funktion) hinzufügen:

```python
# Neue Tabellen anlegen falls nicht vorhanden
db.execute(text("""
  CREATE TABLE IF NOT EXISTS strategy_snapshots (
    id TEXT PRIMARY KEY, mandate_id TEXT NOT NULL, snapshot_date TEXT NOT NULL,
    advisory_assets_rappen INTEGER NOT NULL, risk_profile_score INTEGER NOT NULL,
    risk_profile_label TEXT NOT NULL, soll_equities_bps INTEGER NOT NULL,
    soll_bonds_bps INTEGER NOT NULL, soll_real_estate_bps INTEGER NOT NULL,
    soll_liquidity_bps INTEGER NOT NULL, soll_alternatives_bps INTEGER NOT NULL,
    band_equities_lo_bps INTEGER, band_equities_hi_bps INTEGER,
    band_bonds_lo_bps INTEGER, band_bonds_hi_bps INTEGER,
    band_real_estate_lo_bps INTEGER, band_real_estate_hi_bps INTEGER,
    band_liquidity_lo_bps INTEGER, band_liquidity_hi_bps INTEGER,
    band_alternatives_lo_bps INTEGER, band_alternatives_hi_bps INTEGER,
    advisor_note TEXT, goals_summary_json TEXT,
    created_by TEXT NOT NULL, created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL, deleted_at TEXT
  )
"""))
db.execute(text("""
  CREATE TABLE IF NOT EXISTS asset_class_annual_returns (
    id TEXT PRIMARY KEY, year INTEGER NOT NULL, asset_class TEXT NOT NULL,
    return_bps INTEGER NOT NULL, source TEXT,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
  )
"""))
db.execute(text("""
  CREATE UNIQUE INDEX IF NOT EXISTS uq_acr_year_class
  ON asset_class_annual_returns(year, asset_class)
"""))
# Seed-Daten einmalig einfügen (nur wenn Tabelle noch leer)
count = db.execute(text("SELECT COUNT(*) FROM asset_class_annual_returns")).scalar()
if count == 0:
    now = datetime.utcnow().isoformat()
    for (year, ac, ret) in SEED_ASSET_CLASS_RETURNS:
        db.execute(text("""
          INSERT OR IGNORE INTO asset_class_annual_returns
          (id, year, asset_class, return_bps, source, created_at, updated_at)
          VALUES (:id, :year, :ac, :ret, 'seed', :now, :now)
        """), {'id': str(uuid4()), 'year': year, 'ac': ac, 'ret': ret, 'now': now})
    db.commit()
```

---

## Backend — Neues Modell: `models/snapshots.py`

```python
from sqlalchemy import Column, String, Integer, ForeignKey
from sqlalchemy.orm import relationship
from database import Base

class StrategySnapshot(Base):
    __tablename__ = "strategy_snapshots"
    id = Column(String, primary_key=True)
    mandate_id = Column(String, ForeignKey("mandates.id"), nullable=False)
    snapshot_date = Column(String, nullable=False)
    advisory_assets_rappen = Column(Integer, nullable=False)
    risk_profile_score = Column(Integer, nullable=False)
    risk_profile_label = Column(String, nullable=False)
    soll_equities_bps = Column(Integer, nullable=False)
    soll_bonds_bps = Column(Integer, nullable=False)
    soll_real_estate_bps = Column(Integer, nullable=False)
    soll_liquidity_bps = Column(Integer, nullable=False)
    soll_alternatives_bps = Column(Integer, nullable=False)
    band_equities_lo_bps = Column(Integer)
    band_equities_hi_bps = Column(Integer)
    band_bonds_lo_bps = Column(Integer)
    band_bonds_hi_bps = Column(Integer)
    band_real_estate_lo_bps = Column(Integer)
    band_real_estate_hi_bps = Column(Integer)
    band_liquidity_lo_bps = Column(Integer)
    band_liquidity_hi_bps = Column(Integer)
    band_alternatives_lo_bps = Column(Integer)
    band_alternatives_hi_bps = Column(Integer)
    advisor_note = Column(String)
    goals_summary_json = Column(String)
    created_by = Column(String, ForeignKey("users.id"), nullable=False)
    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)
    deleted_at = Column(String)
    mandate = relationship("Mandate")

class AssetClassAnnualReturn(Base):
    __tablename__ = "asset_class_annual_returns"
    id = Column(String, primary_key=True)
    year = Column(Integer, nullable=False)
    asset_class = Column(String, nullable=False)
    return_bps = Column(Integer, nullable=False)
    source = Column(String)
    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)
```

---

## Frontend — Sprint A: "Portfolio Umsetzen"-Button

### Wo der Button hinkommt

**In `page-al`, im `.ph-r` Header-Bereich** (Zeile ~952).

Aktuell:
```html
<button class="btn" id="btn-aa-pref-open" onclick="openAllocationPreferencesModal()">Anlagepräferenzen &amp; Tilts</button><button class="btn" id="btn-aa-params-open" onclick="openAllocationParametersModal()">Parameter</button><button class="btn-g" id="btn-aa-calc" onclick="calculateInvestmentStrategy()">Anlagestrategie berechnen</button><button class="btn" onclick="openAllocationEngineModal()">Soll-Quoten</button><button class="btn-p" onclick="go('po')">Portfolio →</button>
```

Ersetzen durch (neuen Button vor `Portfolio →` einfügen):
```html
<button class="btn" id="btn-aa-pref-open" onclick="openAllocationPreferencesModal()">Anlagepräferenzen &amp; Tilts</button><button class="btn" id="btn-aa-params-open" onclick="openAllocationParametersModal()">Parameter</button><button class="btn-g" id="btn-aa-calc" onclick="calculateInvestmentStrategy()">Anlagestrategie berechnen</button><button class="btn" onclick="openAllocationEngineModal()">Soll-Quoten</button><button class="btn-p" id="btn-portfolio-umsetzen" onclick="openPortfolioUmsetzenModal()" style="display:none">Portfolio umsetzen ✓</button><button class="btn-p" onclick="go('po')">Portfolio →</button>
```

Der Button ist zunächst `display:none`. Er wird eingeblendet in `applyAllocationEngineResult()` (Zeile ~10532):

**Suchstring (eindeutig in `applyAllocationEngineResult`):**
```
charts.opt.update();
  charts.fan&&charts.fan.update();
```

**Dahinter einfügen:**
```javascript
  var btnUmsetzen = document.getElementById('btn-portfolio-umsetzen');
  if (btnUmsetzen) btnUmsetzen.style.display = '';
```

### Das Modal `m-pu` (Portfolio Umsetzen)

**Neues Modal-HTML** am Ende der Modal-Sektion einfügen (grep: `<!-- MODALS END -->`  oder kurz vor `</body>`):

```html
<!-- MODAL: Portfolio Umsetzen -->
<div class="modal" id="m-pu">
  <div class="mbox" style="max-width:460px">
    <div class="mhd"><span class="mtitle">Strategie verbindlich festlegen</span><button class="mclose" onclick="cm('m-pu')">✕</button></div>
    <div class="mbody" style="padding:18px 20px">
      <div style="font-size:12px;color:var(--n6);line-height:1.65;margin-bottom:16px">
        Die aktuelle SOLL-Allokation wird als Strategie gespeichert und als PDF-Dokument erzeugt.
        Beim nächsten Gespräch können Sie im Review sehen, wie sich diese Strategie entwickelt haben sollte.
      </div>
      <div style="margin-bottom:14px">
        <label style="font-size:11px;font-weight:600;color:var(--n7);display:block;margin-bottom:5px">Datum der Strategiefestlegung</label>
        <input type="date" id="pu-date" class="inp" style="width:100%">
      </div>
      <div style="margin-bottom:18px">
        <label style="font-size:11px;font-weight:600;color:var(--n7);display:block;margin-bottom:5px">Notiz (optional)</label>
        <textarea id="pu-note" class="inp" rows="3" style="width:100%;resize:vertical" placeholder="z.B. Beratungsgespräch Zürich, Kunde hat Renteneintritt geplant..."></textarea>
      </div>
      <div id="pu-summary" style="background:var(--bg);border:1px solid var(--b1);border-radius:var(--r);padding:10px 12px;font-size:11px;color:var(--n6);margin-bottom:18px"></div>
      <div id="pu-error" style="display:none;color:var(--neg);font-size:11px;margin-bottom:10px"></div>
      <div style="display:flex;gap:8px;justify-content:flex-end">
        <button class="btn" onclick="cm('m-pu')">Abbrechen</button>
        <button class="btn-g" id="btn-pu-save" onclick="savePortfolioUmsetzen()">Strategie festlegen &amp; PDF</button>
      </div>
    </div>
  </div>
</div>
```

### Funktion `openPortfolioUmsetzenModal()`

```javascript
function openPortfolioUmsetzenModal() {
  var alloc = strategyState && strategyState.allocation;
  if (!alloc) {
    showToast('Bitte zuerst Anlagestrategie berechnen.', 'warn');
    return;
  }
  // Datum vorbelegen: heute
  var dateEl = document.getElementById('pu-date');
  if (dateEl) dateEl.value = new Date().toISOString().slice(0, 10);
  // Zusammenfassung anzeigen
  var sumEl = document.getElementById('pu-summary');
  if (sumEl) {
    var risk = strategyState.risk || {};
    var label = risk.final_profile || risk.risk_profile_label || '—';
    var buckets = alloc && alloc.buckets ? alloc.buckets : [];
    var lines = buckets.map(function(b) {
      return escapeHtml(b.asset_class_label || b.asset_class || '') + ': ' +
             escapeHtml(formatBpsPercent(b.target_weight_bps));
    });
    sumEl.innerHTML =
      '<div style="font-weight:600;margin-bottom:6px">Zu speichernde Strategie</div>' +
      '<div>Risikoprofil: <strong>' + escapeHtml(label) + '</strong></div>' +
      '<div>' + lines.join(' · ') + '</div>';
  }
  var errEl = document.getElementById('pu-error');
  if (errEl) errEl.style.display = 'none';
  om('m-pu');
}
```

### Funktion `savePortfolioUmsetzen()`

```javascript
async function savePortfolioUmsetzen() {
  var mid = getActiveMandateId();
  if (!mid || isDemoMandateId(mid)) {
    showToast('Demo-Modus: Snapshot wird nicht gespeichert.', 'info');
    printAnlagestrategie();
    cm('m-pu');
    return;
  }
  var alloc = strategyState && strategyState.allocation;
  var risk = strategyState && strategyState.risk;
  if (!alloc) return;

  var dateVal = (document.getElementById('pu-date') || {}).value;
  var noteVal = (document.getElementById('pu-note') || {}).value || null;
  var errEl = document.getElementById('pu-error');

  // BPS-Werte aus alloc.buckets extrahieren (Engine-Key-Mapping)
  function getBps(engineKey) {
    if (!alloc.buckets) return 0;
    var b = alloc.buckets.find(function(x) { return x.asset_class === engineKey; });
    return b ? (b.target_weight_bps || 0) : 0;
  }
  function getBandLo(engineKey) {
    if (!alloc.buckets) return null;
    var b = alloc.buckets.find(function(x) { return x.asset_class === engineKey; });
    return b ? (b.band_min_bps || null) : null;
  }
  function getBandHi(engineKey) {
    if (!alloc.buckets) return null;
    var b = alloc.buckets.find(function(x) { return x.asset_class === engineKey; });
    return b ? (b.band_max_bps || null) : null;
  }

  // Beratungsvermögen berechnen
  var advRappen = 0;
  (alloc.buckets || []).forEach(function(b) { advRappen += (b.current_value_rappen || 0); });

  var body = {
    snapshot_date: dateVal || new Date().toISOString().slice(0, 10),
    advisory_assets_rappen: advRappen,
    risk_profile_score: risk ? (risk.final_score_x10 || 0) : 0,
    risk_profile_label: risk ? (risk.final_profile || risk.risk_profile_label || '') : '',
    soll_equities_bps: getBps('Aktien'),
    soll_bonds_bps: getBps('Obligationen'),
    soll_real_estate_bps: getBps('Immobilien'),
    soll_liquidity_bps: getBps('Liquiditaet'),
    soll_alternatives_bps: getBps('Alternative'),
    band_equities_lo_bps: getBandLo('Aktien'),
    band_equities_hi_bps: getBandHi('Aktien'),
    band_bonds_lo_bps: getBandLo('Obligationen'),
    band_bonds_hi_bps: getBandHi('Obligationen'),
    band_real_estate_lo_bps: getBandLo('Immobilien'),
    band_real_estate_hi_bps: getBandHi('Immobilien'),
    band_liquidity_lo_bps: getBandLo('Liquiditaet'),
    band_liquidity_hi_bps: getBandHi('Liquiditaet'),
    band_alternatives_lo_bps: getBandLo('Alternative'),
    band_alternatives_hi_bps: getBandHi('Alternative'),
    advisor_note: noteVal
  };

  var btn = document.getElementById('btn-pu-save');
  if (btn) { btn.disabled = true; btn.textContent = 'Speichert…'; }

  try {
    await API.post('/mandates/' + mid + '/strategy-snapshots', body);
    cm('m-pu');
    showToast('Strategie gespeichert. PDF wird geöffnet…', 'success');
    printAnlagestrategie();   // bestehende Funktion — öffnet PDF in neuem Fenster
  } catch (e) {
    if (errEl) {
      errEl.textContent = 'Fehler beim Speichern: ' + (e.message || String(e));
      errEl.style.display = '';
    }
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = 'Strategie festlegen & PDF'; }
  }
}
```

---

## Frontend — Sprint B: Review Strategie-Spiegel

### Neue HTML-Sektion in `page-rv`

**Suchstring (eindeutig in `page-rv`):**
```html
        <!-- ② PORTFOLIO-CHECK — IST vs. SOLL, Cashflow, Ziel — Kern jedes Reviews -->
```

**Davor einfügen** (neue Sektion ganz oben, noch vor Portfolio-Check):
```html
        <!-- ① STRATEGIE-SPIEGEL — Vergleich gespeicherte Strategie vs. Markt-Benchmarks -->
        <div class="card" id="rv-spiegel-card" style="margin-bottom:10px;display:none">
          <div class="chd">
            <span class="cht">Strategie-Spiegel</span>
            <span style="font-size:9px;color:var(--n4);margin-left:8px">Entwicklung seit Festlegung</span>
            <div class="chr">
              <span id="rv-spiegel-date" style="font-size:10px;color:var(--n5)"></span>
            </div>
          </div>
          <div class="cbody" style="padding-bottom:10px">
            <!-- Chart -->
            <div style="height:180px;margin-bottom:14px"><canvas id="ch-rv-spiegel"></canvas></div>
            <!-- 3 KPI-Tiles -->
            <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-bottom:14px">
              <div style="background:var(--bg);border:1px solid var(--b1);border-radius:var(--r);padding:10px 12px">
                <div style="font-size:9px;text-transform:uppercase;letter-spacing:0.07em;color:var(--n4);margin-bottom:4px">Ihre Strategie</div>
                <div id="rv-kpi-strategy" style="font-size:16px;font-weight:700;color:var(--n8)">—</div>
              </div>
              <div style="background:var(--bg);border:1px solid var(--b1);border-radius:var(--r);padding:10px 12px">
                <div style="font-size:9px;text-transform:uppercase;letter-spacing:0.07em;color:var(--n4);margin-bottom:4px">vs. SPI-Proxy</div>
                <div id="rv-kpi-delta" style="font-size:16px;font-weight:700;color:var(--n8)">—</div>
              </div>
              <div style="background:var(--bg);border:1px solid var(--b1);border-radius:var(--r);padding:10px 12px">
                <div style="font-size:9px;text-transform:uppercase;letter-spacing:0.07em;color:var(--n4);margin-bottom:4px">Risikoprofil</div>
                <div id="rv-kpi-profile" style="font-size:14px;font-weight:700;color:var(--n8)">—</div>
              </div>
            </div>
            <!-- Drift-Tabelle -->
            <div id="rv-drift-table"></div>
          </div>
        </div>
```

### Funktion `loadReviewSpiegel(mandateId)`

**Position:** Nach der Funktion `renderReviewStrategyComparison` (Zeile ~14020).

```javascript
var _rvSpiegelChart = null;

async function loadReviewSpiegel(mandateId) {
  var card = document.getElementById('rv-spiegel-card');
  if (!card || !mandateId || isDemoMandateId(mandateId)) return;

  var data;
  try {
    data = await API.get('/mandates/' + mandateId + '/strategy-snapshots/latest/drift');
  } catch (e) {
    // Kein Snapshot vorhanden → Karte bleibt versteckt
    if (card) card.style.display = 'none';
    return;
  }

  if (!data || !data.has_drift_data) {
    card.style.display = 'none';
    return;
  }

  card.style.display = '';

  // Datum anzeigen
  var dateEl = document.getElementById('rv-spiegel-date');
  if (dateEl) dateEl.textContent = 'Festgelegt am ' + (data.snapshot_date || '—');

  // KPI-Tiles füllen
  var stratLast = data.chart_strategy[data.chart_strategy.length - 1] || 100;
  var spiLast = data.chart_spi_proxy[data.chart_spi_proxy.length - 1] || 100;
  var stratReturn = ((stratLast / 100) - 1) * 100;
  var deltaVsSpi = stratReturn - (((spiLast / 100) - 1) * 100);
  var stratSign = stratReturn >= 0 ? '+' : '';
  var deltaSign = deltaVsSpi >= 0 ? '+' : '';
  var deltaColor = deltaVsSpi >= 0 ? 'var(--pos)' : 'var(--neg)';

  setText('rv-kpi-strategy', stratSign + stratReturn.toFixed(1) + '%');
  var deltaEl = document.getElementById('rv-kpi-delta');
  if (deltaEl) {
    deltaEl.textContent = deltaSign + deltaVsSpi.toFixed(1) + '%';
    deltaEl.style.color = deltaColor;
  }
  setText('rv-kpi-profile', data.risk_profile_label || '—');

  // Drift-Tabelle rendern
  renderDriftTable(data);

  // Chart rendern
  renderSpiegelChart(data);
}

function renderSpiegelChart(data) {
  var canvas = document.getElementById('ch-rv-spiegel');
  if (!canvas) return;
  if (_rvSpiegelChart) { _rvSpiegelChart.destroy(); _rvSpiegelChart = null; }

  var years = (data.chart_years || []).map(String);
  _rvSpiegelChart = new Chart(canvas, {
    type: 'line',
    data: {
      labels: years,
      datasets: [
        {
          label: 'Ihre Strategie',
          data: data.chart_strategy,
          borderColor: 'rgb(22,101,52)',
          backgroundColor: 'rgba(22,101,52,0.06)',
          borderWidth: 2,
          pointRadius: 3,
          fill: false,
          tension: 0.35
        },
        {
          label: 'SPI-Proxy',
          data: data.chart_spi_proxy,
          borderColor: 'rgba(100,116,139,0.6)',
          backgroundColor: 'transparent',
          borderWidth: 1.5,
          borderDash: [4, 4],
          pointRadius: 0,
          fill: false,
          tension: 0.35
        },
        {
          label: 'Konservativ',
          data: data.chart_conservative,
          borderColor: 'rgba(100,116,139,0.35)',
          backgroundColor: 'transparent',
          borderWidth: 1,
          borderDash: [2, 4],
          pointRadius: 0,
          fill: false,
          tension: 0.35
        }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: true, labels: { font: { size: 9 }, boxWidth: 9, padding: 7 } },
        tooltip: { mode: 'index', intersect: false }
      },
      scales: {
        x: { ticks: { font: { size: 9 } }, grid: { display: false } },
        y: {
          ticks: {
            font: { size: 9 },
            callback: function(v) { return (v - 100).toFixed(0) + '%'; }
          },
          grid: { color: 'rgba(0,0,0,0.05)' }
        }
      }
    }
  });
}

function renderDriftTable(data) {
  var el = document.getElementById('rv-drift-table');
  if (!el) return;

  var LABELS = {
    'Aktien': 'Aktien', 'Obligationen': 'Obligationen',
    'Immobilien': 'Immobilien', 'Liquiditaet': 'Liquidität', 'Alternative': 'Alternative'
  };
  var STATUS_CONFIG = {
    'green': { cls: 'tag-pos', label: 'Im Band',    action: 'Keine Massnahme' },
    'yellow': { cls: 'tag-warn', label: 'Beobachten', action: 'Beim nächsten Gespräch prüfen' },
    'red':   { cls: 'tag-neg', label: 'Rebalancen',  action: 'Reduktion empfohlen' }
  };

  var keys = ['Aktien', 'Obligationen', 'Immobilien', 'Liquiditaet', 'Alternative'];
  var rows = keys.map(function(ac) {
    var orig = data.original[ac] || 0;
    var drift = data.drifted[ac] || 0;
    var delta = drift - orig;
    var status = data.status[ac] || 'green';
    var cfg = STATUS_CONFIG[status] || STATUS_CONFIG['green'];
    var deltaSign = delta >= 0 ? '+' : '';
    var deltaColor = status === 'red' ? 'var(--neg)' : (status === 'yellow' ? 'var(--warn)' : 'var(--n5)');
    return '<div style="display:grid;grid-template-columns:1.4fr 70px 80px 70px 1fr 100px;gap:6px;align-items:center;padding:9px 10px;border-bottom:1px solid var(--b1)">'
      + '<div style="font-size:11px;font-weight:600;color:var(--n8)">' + escapeHtml(LABELS[ac] || ac) + '</div>'
      + '<div style="text-align:right;font-size:11px;color:var(--n6)">' + escapeHtml(formatBpsPercent(orig)) + '</div>'
      + '<div style="text-align:right;font-size:11px;color:var(--n8);font-weight:600">' + escapeHtml(formatBpsPercent(drift)) + '</div>'
      + '<div style="text-align:right;font-size:11px;font-weight:600;color:' + deltaColor + '">' + escapeHtml(deltaSign + formatBpsPercent(delta)) + '</div>'
      + '<div></div>'
      + '<div style="text-align:right"><span class="tag ' + escapeHtml(cfg.cls) + '">' + escapeHtml(cfg.label) + '</span></div>'
      + '</div>';
  });

  el.innerHTML = '<div style="border:1px solid var(--b1);border-radius:var(--r2);overflow:hidden">'
    + '<div style="display:grid;grid-template-columns:1.4fr 70px 80px 70px 1fr 100px;gap:6px;padding:7px 10px;background:var(--bg);border-bottom:1px solid var(--b1);font-size:9px;color:var(--n4);text-transform:uppercase;letter-spacing:0.06em">'
    + '<div>Anlageklasse</div><div style="text-align:right">SOLL</div><div style="text-align:right">Drift heute</div><div style="text-align:right">Delta</div><div></div><div style="text-align:right">Status</div>'
    + '</div>'
    + rows.join('')
    + '</div>';
}
```

### `loadReviewSpiegel` aufrufen beim Tab-Wechsel

**Suchstring (eindeutig, Zeile ~11488):**
```javascript
      if(activePage==='rv'||activePage==='sr')renderReviewStrategyComparison(currentReviewState||{});
```

**Ersetzen durch:**
```javascript
      if(activePage==='rv'||activePage==='sr')renderReviewStrategyComparison(currentReviewState||{});
      if(activePage==='rv'){var _mid=getActiveMandateId();if(_mid)loadReviewSpiegel(_mid);}
```

---

## Betroffene Dateien (Zusammenfassung)

| Datei | Art der Änderung |
|-------|-----------------|
| `5eyes-backend/models/snapshots.py` | **NEU** — SQLAlchemy-Modelle |
| `5eyes-backend/routers/snapshots.py` | **NEU** — 3 Endpoints |
| `5eyes-backend/schemas/snapshots.py` | **NEU** — Pydantic Schemas |
| `5eyes-backend/database.py` | **ÄNDERN** — 2 neue Tabellen + Seed-Daten |
| `5eyes-backend/main.py` | **ÄNDERN** — Router registrieren |
| `5eyes-electron/frontend/5eyes_v2.html` | **ÄNDERN** — Button, Modal, 3 Funktionen, Tab-Hook |

---

## Implementierungs-Checkliste für Codex

### Backend (in dieser Reihenfolge)

1. `models/snapshots.py` erstellen mit `StrategySnapshot` + `AssetClassAnnualReturn`
2. `schemas/snapshots.py` erstellen mit Create/Response-Schemas + BPS-Validator
3. `database.py`: `CREATE TABLE IF NOT EXISTS` für beide Tabellen + Seed-Daten einfügen
4. `routers/snapshots.py` erstellen mit POST + GET-Liste + GET-drift
5. `main.py`: `from routers import snapshots` + `app.include_router(snapshots.router)`
6. Backend starten, prüfen mit: `curl -X POST http://localhost:8000/mandates/TEST/strategy-snapshots`
7. Backend-Tests: `tests/test_snapshots.py` — mindestens 3 Tests (create, list, drift-empty)

### Frontend (in dieser Reihenfolge)

8. Grep: `grep -n 'btn-p.*onclick.*go.*po' 5eyes-electron/frontend/5eyes_v2.html | head -3`
   → Zeile ~952 finden: Button-Zeile in `page-al .ph-r`
   → Neuen "Portfolio umsetzen"-Button vor "Portfolio →" einfügen (mit `display:none`)
9. Grep: `grep -n 'function applyAllocationEngineResult' 5eyes-electron/frontend/5eyes_v2.html`
   → Zeile ~10532 finden
   → Button-Einblenden nach `charts.fan&&charts.fan.update();` einfügen
10. Modal `m-pu` am Ende der Modal-Sektion einfügen
11. Funktionen `openPortfolioUmsetzenModal` und `savePortfolioUmsetzen` einfügen (nach `printAnlagestrategie`, Zeile ~4237)
12. Grep: `grep -n 'rv-strategy-compare\|PORTFOLIO-CHECK' 5eyes-electron/frontend/5eyes_v2.html`
    → Zeile ~1247 finden
    → Neue Sektion `rv-spiegel-card` DAVOR einfügen
13. Funktionen `loadReviewSpiegel`, `renderSpiegelChart`, `renderDriftTable` einfügen (nach `renderReviewStrategyComparison`, Zeile ~14020)
14. Tab-Hook: Zeile ~11488 — `loadReviewSpiegel`-Call hinzufügen
15. `node --check 5eyes-electron/frontend/5eyes_v2.html` → 0 Fehler

---

## Akzeptanzkriterien

1. Nach "Anlagestrategie berechnen" erscheint der "Portfolio umsetzen ✓"-Button im `page-al`-Header
2. Button-Klick öffnet Modal mit Datum (heute) + Zusammenfassung der SOLL-Allokation
3. "Strategie festlegen & PDF" speichert Snapshot via API (`201 Created`) und öffnet `printAnlagestrategie()`
4. Im Demo-Modus: kein API-Call, direkt `printAnlagestrategie()`
5. `GET /mandates/{id}/strategy-snapshots` liefert gespeicherten Snapshot zurück
6. Review-Tab (`rv`) zeigt "Strategie-Spiegel"-Karte wenn mindestens 1 Snapshot + Jahres-Returns vorhanden
7. Line-Chart zeigt 3 Linien (Ihre Strategie / SPI-Proxy / Konservativ), Startwert = 100
8. Drift-Tabelle zeigt für jede Asset Class: SOLL / Drift-heute / Delta / Status (grün/gelb/rot)
9. Kein Snapshot vorhanden → "Strategie-Spiegel"-Karte ist unsichtbar (kein Fehler, kein leerer Zustand sichtbar)
10. `node --check` auf der HTML-Datei → 0 JS-Syntax-Fehler

---

## Testfälle (`tests/test_snapshots.py`)

```python
# Test 1: Snapshot erstellen
def test_create_snapshot(db_session, test_client, ...):
    # POST mit gültigem Body → 201 + id zurück

# Test 2: BPS-Summe falsch → 422
def test_create_snapshot_invalid_bps(test_client, ...):
    # soll_equities_bps = 5000, rest = 0 → Summe != 10000 → 422

# Test 3: Drift auf leerem Snapshot-Set → 404
def test_drift_no_snapshot(test_client, ...):
    # GET .../latest/drift → 404 wenn kein Snapshot

# Test 4: Drift mit Seed-Daten
def test_drift_with_returns(db_session, test_client, ...):
    # Snapshot erstellen mit snapshot_date='2023-01-01'
    # Drift abrufen → chart_years enthält 2023
    # drifted_bps['Aktien'] > soll_equities_bps (weil 2023 Aktien +19.8%)
```

---

## Risiken

- **`alloc.buckets` Struktur im Frontend:** `savePortfolioUmsetzen()` liest `b.asset_class` und `b.target_weight_bps` — prüfen ob diese Felder tatsächlich so heissen im API-Response. Grep: `grep -n 'target_weight_bps\|asset_class.*bucket' 5eyes-electron/frontend/5eyes_v2.html | head -10`
- **Seed-Daten:** Die vordefinierten Jahres-Returns sind Schätzwerte. OWNER-DECISION: Emanuele kalibriert diese mit internen CMA-Daten vor Go-Live.
- **Chart-Instanz:** `_rvSpiegelChart` muss vor Re-Render zerstört werden — in `loadReviewSpiegel` wird bei jedem Tab-Wechsel neu gerendert. Prüfen ob das bei schnellem Tab-Wechsel zu Problemen führt (Race Condition mit `async API.get`).

---

## OWNER-DECISIONS (offen, Emanuele entscheidet)

1. **Seed-Returns kalibrieren:** Die Jahres-Return-Tabelle muss mit realen Referenzanbieter-CMA-Daten befüllt werden bevor Produktion. Die hinterlegten Werte sind plausible Schätzwerte.
2. **Benchmark-Bezeichnungen:** "SPI-Proxy" und "Konservativ-Proxy" sind interne Bezeichnungen — ok so oder eigene Namen?
3. **Chart-Startpunkt:** Aktuell: normiert auf 100 am Snapshot-Datum. Alternative: CHF-Betrag auf Y-Achse. Welche Darstellung bevorzugt für Kundengespräch?
4. **Snapshot unveränderlich?** Aktuell: kein Delete-Endpoint. Soll ein Berater einen Snapshot löschen/überschreiben können? Vorschlag: Nein (Compliance).
