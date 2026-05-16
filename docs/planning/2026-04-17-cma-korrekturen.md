# Spec — CMA Default-Werte Korrekturen

## Meta
- Titel: CMA Default-Werte — Institutionell kalibriert
- Datum: 2026-04-17
- Owner: Emanuele
- Branch-Vorschlag: `codex/cma-korrekturen`

---

## Warum diese Spec existiert — Fachlicher Kontext

Die hardcodierten CMA-Defaults in `5eyes_v2.html` weichen in 4 Positionen
material von institutionellen Quellen ab (JPMorgan LTCMA 2024, BlackRock BII 2024,
CMA via Advisory-Methodik-Dokumentation).

Diese Werte sind die **Fallback-Defaults**, die geladen werden wenn noch keine
Admin-gespeicherten Annahmen in der DB vorhanden sind. Falsche Defaults = falsche
erste Projektionen für neue Installationen.

**Identifizierte Abweichungen:**

| Anlageklasse | Alt (bps) | Neu (bps) | Begründung |
|---|---|---|---|
| Obligationen CHF IG | 170 (1.70%) | 220 (2.20%) | CHF-Bundesobl ~1% + IG-Spread; realistischer |
| Aktien Global | 690 (6.90%) | 700 (7.00%) | CMA: ~7.0-7.5%, konservativer Mittelpunkt |
| Obligationen Emerging | 480 (4.80%) | 400 (4.00%) | EM-Spread überschätzt; CHF-Hedging teuer |
| Immobilien Schweiz | 330 (3.30%) | 450 (4.50%) | SFIX historisch 4-5%, Cap Rate ~3.5% |

---

## Scope

Nur JS-Konstanten-Korrekturen in `5eyes_v2.html`. Keine DB-, Backend-, oder
Logik-Änderungen.

### Was sich ändert
1. `ADMIN_CMA_DEFAULTS.bonds_chf_ig_return_bps`: 170 → 220
2. `ADMIN_CMA_DEFAULTS.equity_intl_return_bps`: 690 → 700
3. `ADMIN_CMA_DEFAULTS.real_estate_ch_return_bps`: 330 → 450
4. `ADMIN_CMA_SUBASSET_DEFAULTS` — 4 Einträge:
   - `Obligationen CHF IG` expected_return_bps: 170 → 220
   - `Aktien Global` expected_return_bps: 690 → 700
   - `Obligationen Emerging` expected_return_bps: 480 → 400
   - `Immobilien Schweiz` expected_return_bps: 330 → 450

### Was NICHT ändert
- Volatilitätswerte (alle korrekt)
- Alle anderen Rendite-Werte
- Korrelationsmatrix
- Backend-Logik
- Gespeicherte Admin-Annahmen in der DB (diese Änderung betrifft nur die
  Fallback-Defaults für neue Installationen ohne gespeicherte CMA)

---

## Betroffene Dateien

| Datei | Art |
|---|---|
| `5eyes-electron/frontend/5eyes_v2.html` | ÄNDERN |

---

## Implementierung — Schritt 1: ADMIN_CMA_DEFAULTS

### Grep:
```
grep -n "bonds_chf_ig_return_bps\|equity_intl_return_bps\|real_estate_ch_return_bps" 5eyes-electron/frontend/5eyes_v2.html
```
Erwartet: Treffer um Zeile 5536, 5544, 5548.

### Änderungen in `ADMIN_CMA_DEFAULTS`:

**Alt:**
```javascript
  bonds_chf_ig_return_bps: 170,
```
**Neu:**
```javascript
  bonds_chf_ig_return_bps: 220,
```

**Alt:**
```javascript
  equity_intl_return_bps: 690,
```
**Neu:**
```javascript
  equity_intl_return_bps: 700,
```

**Alt:**
```javascript
  real_estate_ch_return_bps: 330,
```
**Neu:**
```javascript
  real_estate_ch_return_bps: 450,
```

---

## Implementierung — Schritt 2: ADMIN_CMA_SUBASSET_DEFAULTS

### Grep:
```
grep -n "Obligationen CHF IG\|Aktien Global\|Obligationen Emerging\|Immobilien Schweiz" 5eyes-electron/frontend/5eyes_v2.html
```
Erwartet: Treffer um Zeile 5563-5572.

### Änderungen in `ADMIN_CMA_SUBASSET_DEFAULTS`:

**Alt:**
```javascript
  { name: 'Obligationen CHF IG', asset_class: 'Obligationen', expected_return_bps: 170, expected_volatility_bps: 350 },
```
**Neu:**
```javascript
  { name: 'Obligationen CHF IG', asset_class: 'Obligationen', expected_return_bps: 220, expected_volatility_bps: 350 },
```

**Alt:**
```javascript
  { name: 'Aktien Global', asset_class: 'Aktien', expected_return_bps: 690, expected_volatility_bps: 1600 },
```
**Neu:**
```javascript
  { name: 'Aktien Global', asset_class: 'Aktien', expected_return_bps: 700, expected_volatility_bps: 1600 },
```

**Alt:**
```javascript
  { name: 'Obligationen Emerging', asset_class: 'Obligationen', expected_return_bps: 480, expected_volatility_bps: 1100 },
```
**Neu:**
```javascript
  { name: 'Obligationen Emerging', asset_class: 'Obligationen', expected_return_bps: 400, expected_volatility_bps: 1100 },
```

**Alt:**
```javascript
  { name: 'Immobilien Schweiz', asset_class: 'Immobilien', expected_return_bps: 330, expected_volatility_bps: 820 },
```
**Neu:**
```javascript
  { name: 'Immobilien Schweiz', asset_class: 'Immobilien', expected_return_bps: 450, expected_volatility_bps: 820 },
```

---

## Implementierungs-Checkliste für Codex

1. `ADMIN_CMA_DEFAULTS.bonds_chf_ig_return_bps`: 170 → 220
2. `ADMIN_CMA_DEFAULTS.equity_intl_return_bps`: 690 → 700
3. `ADMIN_CMA_DEFAULTS.real_estate_ch_return_bps`: 330 → 450
4. `ADMIN_CMA_SUBASSET_DEFAULTS` `Obligationen CHF IG` expected_return_bps: 170 → 220
5. `ADMIN_CMA_SUBASSET_DEFAULTS` `Aktien Global` expected_return_bps: 690 → 700
6. `ADMIN_CMA_SUBASSET_DEFAULTS` `Obligationen Emerging` expected_return_bps: 480 → 400
7. `ADMIN_CMA_SUBASSET_DEFAULTS` `Immobilien Schweiz` expected_return_bps: 330 → 450
8. `node --check 5eyes-electron/frontend/5eyes_v2.html` → 0 Fehler

---

## Akzeptanzkriterien

1. Admin-Modal → "Standardwerte" laden zeigt Obligationen CHF IG = 2.20%
2. Admin-Modal → "Standardwerte" laden zeigt Aktien Global = 7.00%
3. Admin-Modal → "Standardwerte" laden zeigt Obligationen Emerging = 4.00%
4. Admin-Modal → "Standardwerte" laden zeigt Immobilien Schweiz = 4.50%
5. Sub-Anlageklassen-Grid zeigt konsistente Werte mit den 4 Korrekturen
6. `node --check` → 0 Fehler
7. Keine anderen Werte verändert

---

## Quellen

- JPMorgan Long-Term Capital Market Assumptions 2024
- BlackRock Investment Institute 2024 CMAs
- CMA (Kapitalmarktannahmen-Provider) Szenarioraum — via Advisory-Methodik Schulungsdokumentation
- Pictet Secular Outlook 2024
