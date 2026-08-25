# Sprint 6 — Nelson-Siegel Yield-Curve

**Datum:** 2026-05-17 (spät abends)
**Status:** Spec / aktiv
**Vorgaenger:** Standortanalyse §B.4 — Engine-Tiefe Bonds-Bewertung.

## 0. Problem

Aktuell sind Bond-Returns als fixe `bonds_chf_ig_return_bps` (z.B. 200 bps p.a.)
in CMA hartkodiert. Das ist Allocation-relevante Vereinfachung:
- Keine Maturity-Struktur (1J vs 10J vs 30J alle gleich modelliert)
- Keine Yield-Curve-Dynamik (Steepening/Flattening nicht abgebildet)
- Reinvestment-Risk nicht modelliert
- Duration-Wirkung implizit ueber `bonds_chf_ig_vol_bps`, nicht explizit

**3eyes-Aequivalent:** Nelson-Siegel-VAR mit pro-Maturity-Forward-Rates,
Mean-Reversion zu Long-Term-Rate, Curve-Shift-Risiko stochastisch.

**Allocation-Wirkung:**
- Realistische Bond-Erwartungen bei aktuellem Niedrig-/Hochzins
- Duration-Tilt-Empfehlungen je nach Kurven-Form
- Risiko-Aufpreis fuer Long-Duration bei flacher/steiler Kurve

## 1. Loesung (Phase 1 = jetzt)

**Nelson-Siegel (1987)** als 4-parametriges Curve-Modell:

```
y(τ) = β₀ + β₁·((1-e^(-λτ))/(λτ)) + β₂·(((1-e^(-λτ))/(λτ)) - e^(-λτ))
```

Wobei:
- β₀ = Long-Term Rate (Level)
- β₁ = Short-Term Adjustment (Slope, neg = ansteigend)
- β₂ = Curvature Adjustment (Bauchigkeit)
- λ = Decay-Parameter (typisch 0.6 fuer Jahre, kontrolliert wo der Knick liegt)
- τ = Maturity in Jahren

## 2. Modul-Struktur (Phase 1)

```
5eyes-backend/
├── services/rates/
│   ├── __init__.py
│   ├── nelson_siegel.py     # NelsonSiegelCurve + Calibration
│   └── (Phase 2: dynamics.py — VAR-Forward-Rates)
└── tests/rates/
    ├── __init__.py
    └── test_nelson_siegel.py
```

## 3. Phasen-Plan

### Phase 1 — Foundation (jetzt, ~2h)
- `NelsonSiegelCurve` dataclass (β₀, β₁, β₂, λ)
- `.yield_at(maturity)` → Yield in bps (Vektorisiert)
- `.forward_rate(t1, t2)` → Forward-Rate (Carry)
- `.fit(market_yields_by_maturity)` → calibration via scipy.optimize
- Tests: Konstante Curve (flat), Steigend, Mean-Reversion, Edge-Cases

### Phase 2 — CMA-Integration (~2h, on-demand)
- CMA-Feld: `bonds_yield_curve_params_json` (β₀, β₁, β₂, λ)
- `scenario_inputs_from_cma` nutzt yield_at(maturity) statt fixem Return
- Maturities pro Bond-Bucket (kurz: 2J, mittel: 5J, lang: 10J)

### Phase 3 — Stochastische Curve-Dynamik (~3-4h, spaeter)
- VAR(1)-Modell ueber (β₀, β₁, β₂) mit historischer Calibration
- MC-Pfade: jedes Jahr neuer Set (β₀, β₁, β₂), daraus Bond-Returns
- Reinvestment-Risk explizit

## 4. Erfolgskriterien Phase 1

- `NelsonSiegelCurve(0.04, -0.02, 0.01, 0.6).yield_at(1)` plausibel (~2.4%)
- `yield_at(∞)` → β₀ (Long-Term-Rate)
- `yield_at(0+)` → β₀ + β₁ (Short-End)
- `.fit()` reproduziert reale CH-Eidg-Curve mit RMS-Error < 5 bps
- Vektorisiert: `.yield_at(np.array([1,5,10,30]))` returns shape (4,)
- ~12-15 Tests
