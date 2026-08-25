# Sprint 7 — KGV-Mean-Reversion fuer Equity-Returns

**Datum:** 2026-05-17 (Nacht)
**Status:** Spec / aktiv
**Vorgaenger:** Standortanalyse §B.5 — Engine-Tiefe Equity-Bewertung.

## 0. Problem

Equity-Returns aktuell als fixe `equity_ch_return_bps` / `equity_intl_return_bps`
in CMA. Das ignoriert empirisch bewaehrte Erkenntnis:
- **KGV (Kurs-Gewinn-Verhaeltnis) ist mean-reverting** (Shiller CAPE-Studien
  ueber 100+ Jahre)
- Bei aktuellem KGV deutlich ueber fairem Long-Term-KGV: niedrigere erwartete
  Returns
- Bei niedrigem KGV: hoehere erwartete Returns

**Allocation-Wirkung:**
- Aktuelle SAA kann nicht zwischen "Equity in Bubble" und "Equity nach Crash"
  unterscheiden — beide bekommen die gleiche Return-Schaetzung
- Mit KGV-MR: zyklische Anpassung der Equity-Returns

## 1. Loesung

**Modell** (simpel, gut testbar):

```
expected_return_adj_bps = alpha * (kgv_fair - kgv_current) / kgv_fair * horizon_factor
```

Wobei:
- `kgv_current` = aktuelles KGV (z.B. 22 SPX)
- `kgv_fair` = langfristiges Mean-Reversion-Ziel (z.B. 17)
- `alpha` = jaehrliche Reversion-Speed (typisch 0.1-0.2)
- `horizon_factor` = Daempfung ueber Anlagehorizont (kuerzer = staerker)

Beispiel: KGV-Current 25, KGV-Fair 17, alpha 0.15, horizon 10J
→ Adjustment p.a. ≈ -100 bps (zyklisch tieferer Return)

## 2. Modul

```
5eyes-backend/
├── services/equity_valuation/
│   ├── __init__.py
│   └── mean_reversion.py    # KGVMeanReversionModel
└── tests/equity_valuation/
    └── test_mean_reversion.py
```

## 3. Phasen

### Phase 1 — Foundation (jetzt, 1h)
- `KGVMeanReversionModel` dataclass (kgv_current, kgv_fair, alpha, vol)
- `.expected_annual_return_adjustment_bps(horizon_years)` → bps
- `.current_overvaluation_pct()` → % over/under fair value
- Tests: alpha=0 → 0 Adjustment, hoch KGV → neg Adjustment, etc.

### Phase 2 — CMA-Integration (jetzt, 1h)
- CMA-Felder: `equity_kgv_current_x10`, `equity_kgv_fair_x10`, `equity_kgv_alpha_x100`
- `scenario_inputs_from_cma` addiert Adjustment auf equity_*_return_bps
- Backwards-Compat: fehlende Felder → kein Adjustment

### Phase 3 — Spaeter (on-demand)
- Stochastische KGV-Pfade (Ornstein-Uhlenbeck)
- Pro Region/Index separates KGV (CH, US, Europa, EM)

## 4. Erfolgskriterien

- KGV-Current = KGV-Fair → Adjustment = 0
- KGV-Current >> KGV-Fair → negatives Adjustment
- Adjustment skaliert mit alpha
- Bei langem Horizont (>20J) deutlich weniger Wirkung als 5J
- Engine: equity-Returns aendern sich bei aktiviertem KGV-MR
- Andere Buckets (bonds, RE, etc.) unveraendert
