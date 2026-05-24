# Sprint U-P20 — Depot-Check IST↔SOLL-Drift + IST-Lookup-Bug-Fix

## Meta

- **Datum:** 2026-05-24
- **Vorgänger:** Sprint U-P10..P14 (Depot-Check Engine + UI + PDF, Mai 2026)
- **Auslöser:** User-Vision „Kunde bringt sein Depot, wir zeigen IST vs. unsere SOLL — auch für Länder/Branchen/Währungen"
- **Scope:** Backend-Aggregation + Tests. Frontend/PDF folgt nach User-Spec.

## Zweck

Der bestehende Depot-Check (Sprint U-P12) liefert IST-Aggregationen für
Country/Sector/Currency, aber NUR Bucket-Drift gegen die SOLL-AllocationDieser Sprint ergänzt **IST↔SOLL-Drift auch für Country/Sector/Currency**
und behebt einen **bestehenden Bug** im IST-Lookup (siehe §4).

## Befund (bestehender Bug, vor U-P20)

`services/depot_check.py:178+229` liest:

```python
current_amount = _safe_int(getattr(rec_pos, "current_amount_rappen", 0))
if current_amount <= 0:
    current_amount = _safe_int(getattr(rec_pos, "target_amount_rappen", 0))
```

Aber `RecommendationPosition` hat **kein** `current_amount_rappen`-Feld im
DB-Schema (`models/review.py:217`+`5eyes_schema_v4.0_FINAL.sql:1105`).
`getattr()` liefert immer 0 → Engine fällt auf `target_amount_rappen` zurück
→ IST==SOLL → alle Drift-Werte = 0.

Real-Auswirkung: Der Depot-Check funktioniert HEUTE in der UI, aber die
„IST vs SOLL"-Vergleichszahlen pro Bucket sind nur dann sinnvoll, wenn
target_amount ≠ aktuelle Allokation aus WealthPosition (für Fallback-Path
ohne RecommendationRun) — bei vorhandener RecommendationRun ist IST=SOLL.

## Reproduktion

Vor U-P20:

```python
# Setup: 1 Mandat mit RecommendationRun + 2 Positions
# CH-Position: current_amount=800_000_00, target_amount=500_000_00
# US-Position: current_amount=200_000_00, target_amount=500_000_00
result = compute_depot_check(db, mandate)
# Erwartet: country["CH"] = 8000, drift["CH"] = 3000
# Tatsächlich vor U-P20: country["CH"] = 5000, drift["CH"] = 0
#   (weil current_amount im DB nicht persistiert wurde)
```

Mit U-P20: Spalte ist gepflegt → Drift = 3000 wie erwartet.

## Implementation

### 1. Schema-Erweiterung

**`models/review.py`:** neue Column `current_amount_rappen` (nullable Integer)
auf `RecommendationPosition`.

**`migrations/2026-05-24-u-p20-current-amount-rappen.sql`:** ALTER-Statement
für Production-DBs.

**`5eyes_schema_v4.0_FINAL.sql`:** wird in einem Folge-Edit aktualisiert
(jetzt nicht, weil Codex parallel am selben File arbeitet — vermeidet
Merge-Konflikt).

### 2. SOLL-Aggregation in `compute_depot_check`

Erweiterung von `services/depot_check.py`:

- Zweite Aggregation: `position_target_weights_bps` aus
  `target_amount_rappen`, gegen die SAME per-product Exposure-Maps.
- `aggregate_exposures(target_weights, country_exp)` → SOLL-Country.
- Analog Sector + Currency.
- Drift = IST − SOLL per Key (`_compute_drift()`-Helper).

### 3. Neue Result-Keys (backwards-compatible, additive)

```json
{
  ... bestehende Keys bleiben ...
  "soll_country_exposure_bps": {"CH": 5000, "US": 5000, ...},
  "soll_sector_exposure_bps":  {"Information Technology": 4400, ...},
  "soll_currency_exposure_bps":{"CHF": 5500, "USD": 4500},
  "country_exposure_drift_bps": {"CH": +3000, "US": -3000},
  "sector_exposure_drift_bps":  {"Information Technology": +4400, ...},
  "currency_exposure_drift_bps":{"CHF": -1500, "USD": +1500}
}
```

### 4. Drift-Warnings

Neue Warnings im `warnings`-Array bei ≥ 1500 bps Drift in einer Einzel-
Dimension (Country/Sector/Currency):

```
"Land-Drift Überhang bei 'CH': +30.0 Prozentpunkte gegenüber Empfehlung."
"Sektor-Drift Überhang bei 'Information Technology': +44.0 Prozentpunkte ..."
```

### 5. Edge-Case-Handling

- Keine `RecommendationRun` → SOLL-Maps leer (kein Drift möglich).
- Alle `target_amount_rappen = 0` → SOLL-Maps leer + Warning.
- Position fehlt im IST aber nicht im SOLL → `_compute_drift` setzt
  IST-Wert auf 0 für Union-Keys.

## Tests

`tests/test_depot_check.py` — 11 Tests, **alle grün**:

| # | Test | Was |
|---|---|---|
| 1 | `_compute_drift_handles_union_of_keys` | Unit: Drift-Helper, beide Key-Sets |
| 2 | `_compute_drift_handles_empty_inputs` | Unit: empty/None robustness |
| 3 | `empty_mandate_returns_warning` | Edge: kein Beratungsvermögen |
| 4 | `pure_ch_portfolio_with_matching_target_has_zero_drift` | Identische Exposures → Drift=0 |
| 5 | `overweight_ch_underweight_us_drift_has_correct_signs` | 80/20 IST vs 50/50 SOLL → +30pp / -30pp |
| 6 | `default_proxy_used_when_country_exposure_json_missing` | MSCI ACWI Proxies greifen |
| 7 | `hhi_concentration_single_country_is_maximum` | HHI = 10000 bei 100% einer Position |
| 8 | `no_recommendation_run_leaves_soll_empty` | WealthPosition-Fallback ohne SOLL |
| 9 | `recommendation_without_target_amount_produces_warning` | Edge: target=0 |
| 10 | `bucket_drift_against_target_allocation` | Bestehender Bucket-Drift bleibt OK |
| 11 | `sector_drift_computed_alongside_country` | Sector-Drift parallel zu Country |

**Vor U-P20: 0 Tests für depot_check.py** (trotz 367 Zeilen Engine).
**Mit U-P20: 11 Tests**, Foundation-Coverage etabliert.

## Was NICHT in U-P20 ist

- **Frontend-Anpassung** (5eyes_v2.html): Modal-Erweiterung für IST/SOLL/Drift-
  Visualisierung. → folgt nach User-Spec.
- **PDF-Anpassung** (`services/pdf/documents/depotcheck.py`): zusätzliche
  Tabellen/Bars für Country/Sector/Currency-Drift. → folgt nach User-Spec.
- **UI für `current_amount_rappen`-Pflege**: aktuell muss der Berater den
  Wert direkt via DB-Tool oder via "Empfehlung übernehmen" setzen
  (target_amount wird dann zur Initial-IST). Ein eigener PATCH-Endpoint
  + UI ist sinnvoller Folge-Sprint (U-P21).
- **Schema-File `5eyes_schema_v4.0_FINAL.sql` Aktualisierung**: wird
  separat nachgezogen, sobald Codex' parallele Edits committed sind
  (vermeidet Merge-Konflikt).

## Auswirkung für die Berater-Vision

Der Berater kann jetzt im Backend-Endpoint einen vollen Depotcheck
abrufen, der:

1. **IST aggregiert** (Country/Sector/Currency aus aktuellen Holdings).
2. **SOLL aggregiert** (gleiche Dimensionen aus empfohlenen Holdings).
3. **Drift mit Vorzeichen** (positiv = Überhang, negativ = Unterhang).
4. **Warnings** für hohe Drift (≥ 15 Prozentpunkte) auf jeder Dimension.
5. **HHI-Konzentration** (Single-Country/Sector dominanz).
6. **TER/Liquidität/ESG** gewichtet.
7. **Top-Positionen** sortiert nach Gewicht.

Frontend/PDF spiegeln das aktuell nur teilweise wider — Vision-Spec
vom Berater liefert die UX-Detail-Anforderungen.
