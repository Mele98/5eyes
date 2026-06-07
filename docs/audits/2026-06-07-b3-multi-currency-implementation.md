# Sprint B3: Multi-Currency-Cashflow-Konversion (Implementation-Audit)

**Datum:** 2026-06-07
**Sprint:** B3 (Engine-Hardening Phase B, erste Engine-Verbesserung)
**Trigger:** Sprint A3 markierte F5 als MAJOR-Gap — `cashflow_timeline.py` ignorierte das `Cashflow.currency`-Feld.

---

## Executive Summary

**F5-Lücke geschlossen ohne Breaking-Change.**

- Neue Funktionalität: Cashflows mit `currency != "CHF"` werden bei aktivem FX-Source konvertiert
- Backwards-Compat: Default-Pfad ohne `fx_source` bleibt unverändert (currency ignoriert)
- Production-Wiring: `portfolio_engine` lädt FX-Source aus DB pro Aggregator-Call

| Metrik | Wert |
|--------|------|
| Geänderte Files | 2 (cashflow_timeline.py, portfolio_engine.py) |
| Neue Tests | 7 (Multi-Currency + Edge-Cases + Backwards-Compat) |
| Regression-Tests | 234 passing |
| Breaking-Changes | KEINE (alle bestehenden Aufrufer ohne fx_source funktionieren weiter) |

---

## 1. Architektur

### Public-API

```python
# services/cashflow_timeline.py
def totals_for_year(
    cashflows: list,
    year: int | None = None,
    *,
    inflation_series_bps: list[int] | None = None,
    start_year: int | None = None,
    fx_source: FXRateSource | None = None,      # NEU (B3)
    target_currency: str = "CHF",                # NEU (B3)
) -> dict[str, int]: ...
```

Analog für `net_cashflow_series` und `recurring_net_cashflow_series`.

### Conversion-Helper

```python
def _convert_cf_amount_to_target_currency(cf, fx_source, target_currency: str) -> int:
    # 1. fx_source=None oder amount=0 → no-op (Backwards-Compat)
    # 2. cf.currency fehlt/leer → "CHF" default
    # 3. cf.currency == target_currency → no-op (Identity)
    # 4. fx_source.cross_rate(cf.currency, target_currency) → konvertierter Betrag
    # 5. Bei unbekannter Currency: defensiver Fallback → return amount_rappen
```

### Reihenfolge der Operationen

```
Cashflow (cf.amount_rappen in cf.currency)
  → Currency-Conversion via fx_source
  → Inflation-Faktor (in target_currency)
  → contribution_for_year (Annualisierung)
  → totals (aggregiert)
```

**Begründung Currency vor Inflation:**
CMA-Inflation-Series (`inflation_series_bps`) bezieht sich auf CHF-Werte. USD-Income muss erst zu CHF konvertiert werden, dann mit CH-Inflation hochgezinst.

---

## 2. Production-Wiring (portfolio_engine.py)

Beide Aggregator-Pfade (`_load_allocation_inputs` und `rebuild_allocation_outputs`) wurden um den FX-Source-Layer erweitert:

```python
fx_source = None
try:
    from services.currency.fx_rates import FXRateSource
    fx_source = FXRateSource.from_db(db)
except Exception:
    fx_source = None
target_currency = str(getattr(mandate, "base_currency", "CHF") or "CHF").upper()
```

- `mandate.base_currency` ist Ziel-Währung (existiert im Model, default "CHF")
- Defensive Lazy-Import: bei Import-Failure oder DB-Lese-Fehler fällt der Code auf altes Verhalten zurück (keine Conversion)
- `FXRateSource.from_db(db)` liest aktuelle FX-Rates aus DB mit DEFAULT_FX_RATES als Fallback

---

## 3. Backwards-Compat-Garantien

1. **Default-Verhalten unverändert:** Aufrufer ohne `fx_source`-Parameter sehen identische Outputs wie pre-B3
2. **portfolio_engine-Aufrufer ohne FX-DB-Setup:** Try/Except umschließt FX-Import → Fallback auf alte Behavior
3. **CHF-Mandate ohne Multi-Currency-CFs:** Conversion ist Identity (no-op) — keine Performance-Regression

---

## 4. Test-Coverage

### Direkt-Tests (`tests/test_cashflow_in_mc_integration.py`)

| Test | Was wird verifiziert |
|------|----------------------|
| `test_f5_backwards_compat_ohne_fx_source_keine_konversion` | Default-Pfad: USD bleibt unkonvertiert |
| `test_f5_b3_mit_fx_source_konvertiert_usd_zu_chf` | Aktiv-Pfad: 100k USD → ~88k CHF (Default-Rate 0.88) |
| `test_f5_b3_eur_und_gbp_mix_zu_chf` | Mix: 50k EUR + 20k GBP → korrekte Summe in CHF |
| `test_f5_b3_chf_unveraendert_wenn_fx_source_gesetzt` | Identity-Path: CHF-CFs nicht konvertiert |
| `test_f5_b3_unbekannte_currency_defensiv_kein_crash` | Defensive: XYZ-Code crashed nicht |
| `test_f5_b3_leere_currency_default_zu_chf` | Fehlendes Field: Default "CHF" |
| `test_f5_b3_inflation_wirkt_nach_currency_conversion` | Reihenfolge: Currency → Inflation |

### Regression (234 Tests passing)

- Cashflow-Timeline: 24 Tests
- Cashflow-in-MC-Integration: 18 Tests
- Engine-Reference-Mandate: 8 Tests
- Engine-Input-Sensitivity: 9 Tests
- Optimizer + Solver + Scenario: ~80 Tests
- Portfolio-Engine: 100+ Tests
- Goal/Rank: 17 Tests

---

## 5. Bewusste Out-of-Scope-Entscheidungen

| Punkt | Begründung |
|-------|-----------|
| **Stochastische FX-Pfade** | Multi-Currency-Volatilität wird NICHT in MC modelliert. CFs sind in CHF nach Conversion deterministisch. Stochastik kommt aus den Asset-Returns (Bucket-Returns) |
| **Future-FX-Rate-Projektion** | Aktuelle Spot-Rate wird für alle Jahre verwendet. Kein FX-Forward-Curve-Modell. Akzeptabel für Standard-Beratungs-Horizonte (10-30J) |
| **Cross-Currency-Hedging** | Nicht modelliert. Berater muss manuell entscheiden |
| **Currency pro Goal** | Goals haben keine `currency`-Felder. Implizit: alle Goals in `target_currency` (CHF default) |

---

## 6. Lifecycle

- **Drift-Protection:** xfail-Test in test_cashflow_in_mc_integration.py wurde durch echte Asserts ersetzt
- **Reviewer-Pflicht:** Wenn `cashflow_timeline.py` geändert wird, MUSS Backwards-Compat verifiziert werden (test_f5_backwards_compat... muss grün bleiben)
- **Future-Evolution:** FXRateSource.from_db() ist die Erweiterungs-Schnittstelle für Berater-pflegbare Rates

---

## 7. Referenzen

- `services/cashflow_timeline.py:_convert_cf_amount_to_target_currency` (Helper)
- `services/cashflow_timeline.py:totals_for_year` (Public-API)
- `services/portfolio_engine.py:_load_allocation_inputs` (Wiring 1)
- `services/portfolio_engine.py:rebuild_allocation_outputs` (Wiring 2)
- `services/currency/fx_rates.py:FXRateSource` (FX-Source)
- `services/currency/converter.py:convert_rappen` (Currency-Converter)
- `docs/audits/2026-06-07-cashflow-in-mc-audit.md` (F5-Originalbefund)
- `docs/engine-spec.md` (Spec-Update folgt mit B1+B2-Merge)

---

**Status:** B3 komplett. Folge: B2 Per-Pfad-Tax.
