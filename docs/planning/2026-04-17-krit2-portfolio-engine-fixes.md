# Spec — KRIT-2 + HIGH-2: portfolio_engine.py Korrekturen

## Meta
- Titel: Portfolio Engine — CMA Defaults, Reset-Bug, Wachstum→Wachstumsorientiert
- Datum: 2026-04-17
- Owner: Emanuele
- Branch-Vorschlag: `codex/krit2-portfolio-engine-fixes`
- Priorität: KRITISCH — Rentenwerte werden mit falschen Annahmen berechnet

---

## Warum diese Spec existiert

`portfolio_engine.py` hat drei voneinander unabhängige Bugs, alle in der gleichen
Datei. Sie werden zusammen in einem Branch gefixt um Merge-Konflikte zu vermeiden.

### Bug 1 — KRIT-2a: Falsche CMA Default-Renditen (new-install branch)
Wenn keine CMA in der DB existiert, werden die Fallback-Werte direkt in die DB
geschrieben. Drei Werte sind falsch (nicht institutionell kalibriert).

### Bug 2 — KRIT-2b: CMA Reset-Block zerstört Admin-Konfiguration (KRITISCHSTER BUG)
Der `elif`-Block bei Zeile 2434 überschreibt auf JEDEM Allokationsaufruf die
gespeicherte CMA des Admins mit den falschen Defaults — selbst wenn der Admin
eigene Werte eingetragen hat. Dieses `elif` darf überhaupt nicht existieren.

### Bug 3 — KRIT-2c: _DEFAULT_SUB_ASSET_CLASS_ASSUMPTIONS falsch kalibriert
Vier Einträge im In-Memory-Dict (das auch als Template für neue DB-Rows dient)
enthalten falsche Renditeerwartungen.

### Bug 4 — HIGH-2: Profilname "Wachstum" vs. "Wachstumsorientiert"
`ALLOWED_HOUSE_MATRIX_PROFILES` und die Seed-Daten verwenden "Wachstum",
aber `SCORE_TO_PROFILE` in `risk_scoring.py` und das Frontend verwenden
"Wachstumsorientiert". Das führt zu Profil-Mismatch beim Validieren.

---

## Scope

Nur `5eyes-backend/services/portfolio_engine.py`. Keine anderen Dateien.

---

## Betroffene Datei

| Datei | Art |
|---|---|
| `5eyes-backend/services/portfolio_engine.py` | ÄNDERN |

---

## Änderung 1 — _DEFAULT_SUB_ASSET_CLASS_ASSUMPTIONS (4 Werte)

**Grep zum Lokalisieren:**
```
grep -n "Aktien Global\|Obligationen CHF IG\|Obligationen Emerging\|Immobilien Schweiz" 5eyes-backend/services/portfolio_engine.py
```
Erwartete Treffer: ~Zeilen 972, 981, 984, 985.

### 1a: Aktien Global — Zeile ~972

**Alt:**
```python
    "Aktien Global": {"asset_class": "Aktien", "expected_return_bps": 690, "expected_volatility_bps": 1600},
```
**Neu:**
```python
    "Aktien Global": {"asset_class": "Aktien", "expected_return_bps": 700, "expected_volatility_bps": 1600},
```

### 1b: Obligationen CHF IG — Zeile ~981

**Alt:**
```python
    "Obligationen CHF IG": {"asset_class": "Obligationen", "expected_return_bps": 170, "expected_volatility_bps": 350},
```
**Neu:**
```python
    "Obligationen CHF IG": {"asset_class": "Obligationen", "expected_return_bps": 220, "expected_volatility_bps": 350},
```

### 1c: Obligationen Emerging — Zeile ~984

**Alt:**
```python
    "Obligationen Emerging": {"asset_class": "Obligationen", "expected_return_bps": 480, "expected_volatility_bps": 1100},
```
**Neu:**
```python
    "Obligationen Emerging": {"asset_class": "Obligationen", "expected_return_bps": 400, "expected_volatility_bps": 1100},
```

### 1d: Immobilien Schweiz — Zeile ~985

**Alt:**
```python
    "Immobilien Schweiz": {"asset_class": "Immobilien", "expected_return_bps": 330, "expected_volatility_bps": 820},
```
**Neu:**
```python
    "Immobilien Schweiz": {"asset_class": "Immobilien", "expected_return_bps": 450, "expected_volatility_bps": 820},
```

---

## Änderung 2 — CMA Creation Block: 3 falsche Default-Werte (Zeilen ~2391, ~2399, ~2403)

**Grep zum Lokalisieren:**
```
grep -n "bonds_chf_ig_return_bps\|equity_intl_return_bps\|real_estate_ch_return_bps" 5eyes-backend/services/portfolio_engine.py
```

### 2a: bonds_chf_ig_return_bps im `if not cma:` Block

**Alt:**
```python
            bonds_chf_ig_return_bps=170,
```
**Neu:**
```python
            bonds_chf_ig_return_bps=220,
```

### 2b: equity_intl_return_bps im `if not cma:` Block

**Alt:**
```python
            equity_intl_return_bps=690,
```
**Neu:**
```python
            equity_intl_return_bps=700,
```

### 2c: real_estate_ch_return_bps im `if not cma:` Block

**Alt:**
```python
            real_estate_ch_return_bps=330,
```
**Neu:**
```python
            real_estate_ch_return_bps=450,
```

---

## Änderung 3 — KOMPLETTEN elif-Block entfernen (Zeilen ~2434–2476)

**WICHTIG**: Dieser Block ist der kritischste Bug. Er überschreibt die Admin-CMA
bei JEDEM Allokationsaufruf — egal was der Admin konfiguriert hat. Er muss
vollständig gelöscht werden.

**Grep zum Lokalisieren der Grenzen:**
```
grep -n "elif cma.assumption_set_name == DEFAULT_CMA_NAME" 5eyes-backend/services/portfolio_engine.py
```
Erwartet: eine einzige Zeile, ~Zeile 2434. Der Block endet bei `cma.updated_at = now` (~Zeile 2476).

**Alt — GESAMTER Block zu löschen (von elif bis einschliesslich cma.updated_at = now):**
```python
    elif cma.assumption_set_name == DEFAULT_CMA_NAME or str(cma.source or "") == "5Eyes Default Runtime":
        cma.assumption_set_name = DEFAULT_CMA_NAME
        cma.valid_from = today
        cma.is_current = 1
        cma.bonds_chf_ig_return_bps = 170
        cma.bonds_chf_ig_vol_bps = 350
        cma.bonds_fx_hedged_return_bps = 220
        cma.bonds_fx_hedged_vol_bps = 430
        cma.bonds_hy_return_bps = 420
        cma.bonds_hy_vol_bps = 950
        cma.equity_ch_return_bps = 620
        cma.equity_ch_vol_bps = 1450
        cma.equity_intl_return_bps = 690
        cma.equity_intl_vol_bps = 1600
        cma.equity_em_return_bps = 760
        cma.equity_em_vol_bps = 1900
        cma.real_estate_ch_return_bps = 330
        cma.real_estate_ch_vol_bps = 820
        cma.alternatives_gold_return_bps = 300
        cma.alternatives_gold_vol_bps = 1200
        cma.liquidity_return_bps = 80
        cma.liquidity_vol_bps = 15
        cma.inflation_path_json = json.dumps({
            "2026": 50,
            "2027": 70,
            "2028": 60,
            "2029": 50,
            "2030": 60,
            "2031": 70,
            "2032": 70,
            "2033": 70,
            "2034": 70,
            "2035": 70,
            "2036": 70,
            "2037": 80,
            "2038": 90,
            "2039": 100,
            "2040": 110,
        })
        cma.sub_asset_class_assumptions_json = json.dumps(_DEFAULT_SUB_ASSET_CLASS_ASSUMPTIONS)
        cma.source = "5Eyes Default Runtime"
        cma.notes = "Automatisch erzeugte Default-CMA fuer V1-Engine"
        cma.updated_at = now
```

**Neu — nichts. Der Block wird ersatzlos gelöscht.**

Nach der Löschung muss die Struktur so aussehen (kein elif mehr zwischen `db.add(cma)` und `db.flush()`):
```python
        db.add(cma)

    db.flush()
    return policy, cma
```

---

## Änderung 4 — HIGH-2: "Wachstum" → "Wachstumsorientiert" (2 Stellen)

**Grep zum Lokalisieren:**
```
grep -n "Wachstum" 5eyes-backend/services/portfolio_engine.py
```
Erwartete Treffer: Zeile ~64 (ALLOWED_HOUSE_MATRIX_PROFILES) und Zeile ~2312 (Seed-Tupel).

### 4a: ALLOWED_HOUSE_MATRIX_PROFILES — Zeile ~64

**Alt:**
```python
ALLOWED_HOUSE_MATRIX_PROFILES = ("Kapitalschutz", "Defensiv", "Ausgewogen", "Wachstum", "Dynamisch", "Aktien")
```
**Neu:**
```python
ALLOWED_HOUSE_MATRIX_PROFILES = ("Kapitalschutz", "Defensiv", "Ausgewogen", "Wachstumsorientiert", "Dynamisch", "Aktien")
```

### 4b: Seed-Tupel in ensure_runtime_reference_data — Zeile ~2312

**Alt:**
```python
        (7, 8, "Wachstum", 0, 150, 200, 1000, 1600, 2500, 6000, 6800, 7500, 500, 800, 1200, 300, 600, 1000, 8000, 6000),
```
**Neu:**
```python
        (7, 8, "Wachstumsorientiert", 0, 150, 200, 1000, 1600, 2500, 6000, 6800, 7500, 500, 800, 1200, 300, 600, 1000, 8000, 6000),
```

---

## Implementierungs-Checkliste für Codex

1. `_DEFAULT_SUB_ASSET_CLASS_ASSUMPTIONS["Aktien Global"]` expected_return_bps: 690 → 700
2. `_DEFAULT_SUB_ASSET_CLASS_ASSUMPTIONS["Obligationen CHF IG"]` expected_return_bps: 170 → 220
3. `_DEFAULT_SUB_ASSET_CLASS_ASSUMPTIONS["Obligationen Emerging"]` expected_return_bps: 480 → 400
4. `_DEFAULT_SUB_ASSET_CLASS_ASSUMPTIONS["Immobilien Schweiz"]` expected_return_bps: 330 → 450
5. `if not cma:` Block — `bonds_chf_ig_return_bps`: 170 → 220
6. `if not cma:` Block — `equity_intl_return_bps`: 690 → 700
7. `if not cma:` Block — `real_estate_ch_return_bps`: 330 → 450
8. LÖSCHEN: gesamter `elif cma.assumption_set_name == DEFAULT_CMA_NAME...` Block (43 Zeilen)
9. `ALLOWED_HOUSE_MATRIX_PROFILES`: "Wachstum" → "Wachstumsorientiert"
10. Seed-Tupel in `ensure_runtime_reference_data`: "Wachstum" → "Wachstumsorientiert"
11. Verifikation: `python -c "import services.portfolio_engine"` → kein ImportError
12. Verifikation: `grep -n "Wachstum[^s]" services/portfolio_engine.py` → kein Treffer mehr
13. Verifikation: `grep -n "elif cma.assumption_set_name" services/portfolio_engine.py` → kein Treffer mehr

---

## Akzeptanzkriterien

1. Nach dem Fix: `grep "elif cma.assumption_set_name" portfolio_engine.py` → 0 Treffer
2. Admin speichert eigene CMA → nächste Allokation überschreibt sie NICHT mehr
3. Neue Installation ohne DB → CMA wird mit Obligationen CHF IG=220, Aktien Global=700, Immobilien Schweiz=450, Obligationen Emerging=400 angelegt
4. `ALLOWED_HOUSE_MATRIX_PROFILES` enthält "Wachstumsorientiert", nicht "Wachstum"
5. `python -c "import services.portfolio_engine"` → kein Fehler
6. Keine anderen Zeilen geändert ausser den 10 oben aufgeführten

---

## Quellen der Korrekturen

- JPMorgan Long-Term Capital Market Assumptions 2024
- BlackRock Investment Institute 2024 CMAs
- CMA (Kapitalmarktannahmen-Provider) via Advisory-Methodik Schulungsdokumentation
- Pictet Secular Outlook 2024
