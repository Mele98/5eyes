# Spec #45 + #47 — Optimizer: Sub-Asset-Klassen-Tiefe + Currency-aware

**Status:** offen. Beide opt-in, default OFF, strikt backwards-kompatibel.
**Erstellt:** 2026-06-21 (autonomer Spec-Sprint). Alle file:line per Read verifiziert.
**Branch-Vorschlag:** `codex/u45-optimizer-subclass-currency`

---

## 0. Verifizierte IST-Anker (file:line)
- Engine-Draw: `services/optimizer/scenario_engine.py:121-175` (`build_scenario_paths`, `Z=einsum('phb,kb->phk',Z,cholesky)`); `ScenarioInputs:46-60`; `scenario_inputs_from_cma:542-681`.
- 5×5-Default-Korrelation + Cholesky: `services/portfolio_engine.py:1427-1434`, `:1472-1496`, `:1548-1591`.
- Sub-Klassen heute (nur analytische Vola-Dämpfung VOR der Engine): `config.py:260` (`sub_class_intra_correlation`, Validator `:289-297`); `portfolio_engine.py:1436-1469` (Sub-CMA-Defaults + Label→Bucket), `:1594-1634` (`_sub_asset_class_assumption_map`/`_sub_asset_class_metrics`), `:1713-1786` (`_weighted_bucket_metrics`, heutige Block-Diagonal-Vola-Formel).
- Sub-Allocation-Wiring im Solver: `solver.py:197,205,233,238-247,797,823`.
- FX (nur Cashflow-Layer deterministisch, Sprint B3; MC out-of-scope): `services/currency/fx_rates.py:22-109` (`FXRateSource`), `converter.py:24-54`, `models/mandates.py:17` (`base_currency`), `models/allocation.py:185-186`; Out-of-scope-Doku `docs/audits/2026-06-07-b3-multi-currency-implementation.md:129-132`.

## 1. Ziel
- **#45:** Intra-Bucket-Allokation (CH-Equity ↔ EM-Equity etc.) als echte K-dimensionale Sub-Klassen-Draws mit **Block-Diagonal-Korrelation** statt nur analytischer Vola-Dämpfung.
- **#47:** FX-Risiko/Hedging-Kosten in der Scenario-Engine; `base_currency`-Konsistenz via `FXRateSource`.

## 2. SOLL-Design
**#45:** Opt-in K-dim Sub-Klassen-Draws, Block-Diagonal-Korrelation (Intra=`rho_intra`, Inter=5×5). Aggregation `r_bucket[:,:,b] = Σ_{i∈b} weight_in_bucket[i]·r_sub[:,:,i]` zurück auf 5 Buckets → Output bleibt `(n_paths, horizon, 5)` → Solver unverändert. PSD-Garantie: Nearest-PD (Eigenwert-Clipping eps=1e-8, Diag=1) → Fallback `np.eye(K)`+Warning, **nie Crash**. Bei `rho_intra=1.0` == alter Pfad (Konsistenz-Pin).

**#47:** Opt-in log-normaler FX-Faktor pro Asset (μ_fx=0): `log_fx=-0.5·σ_fx²+σ_fx·Z_fx` (eigener rng-Seed XOR 0x46580000). Hedge-Dämpfung `r_fx_eff=hedge_ratio+(1-hedge_ratio)·r_fx` + deterministischer Hedge-Kosten-Drag `(1-cost/10000)^hedge_ratio`. `base==Heimwährung → fx_vol=0 → Identity`. FX auf Sub-Ebene wenn #45 aktiv, sonst Bucket-Ebene.

## 3. NICHT ÄNDERN (Backwards-Compat)
`scenario_inputs_from_cma`, `build_scenario_paths`, `simulate_wealth_paths`, `_weighted_bucket_metrics`, `_DEFAULT_CORRELATION_MATRIX`. Features default-off; alle bestehenden Optimizer-Tests müssen ohne Änderung grün bleiben.

## 4. Test-Plan
`tests/test_optimizer_subclass_correlation.py`: PSD, Block-Struktur, Determinismus (`np.array_equal`), Aggregations-Konsistenz `rho_intra=1.0`==alter Pfad, Diversifikation `rho<1` senkt Vola, Shape `(.,.,5)`.
`tests/test_optimizer_currency_risk.py`: Identity bei base==CHF, FX erhöht Vola, Hedge senkt Vola+kostet Return, FX-Seed-Determinismus, base CHF→EUR, unbekannte Währung kein Crash.

## 5. OWNER-DECISIONS (Defaults aus Spec, im PR bestätigen)
OD-45-A Sub-Mix fix · OD-45-B Nearest-PD · OD-45-C Faktor-Aggregation · OD-45-D Bucket-Skew · OD-47-A μ_fx=0 · OD-47-B FX auf Sub-Ebene wenn #45 · OD-47-C Hedge aus Param/Heuristik · OD-47-D FX unkorreliert · OD-COMMON alles opt-in.

---

## Codex-Prompt
```text
Branch: codex/u45-optimizer-subclass-currency
Repo: C:\5eyes\5eyes_stage9_release_ready (5eyes-backend, Python FastAPI)
Spec: docs/planning/2026-06-21-spec-45-47-optimizer-subclass-currency.md (VOLLSTÄNDIG LESEN)

UMSETZUNG #45 (Sub-Klassen-Tiefe) in services/optimizer/scenario_engine.py:
- NEU: SubClassLayout, build_sub_class_layout(sub_allocations), SubScenarioInputs,
  build_block_diagonal_correlation(layout,inter_corr_5x5,intra_rho),
  sub_scenario_inputs_from_cma(cma,sub_allocations,*,intra_rho=None),
  build_scenario_paths_subclass(...) -> Output IMMER (n_paths,horizon,5).
  Aggregation: r_bucket[:,:,b]=Σ_{i∈b} weight_in_bucket[i]*r_sub[:,:,i].
- PSD: _safe_cholesky -> Nearest-PD (Eigenwert-Clip eps=1e-8, Diag=1) -> Fallback eye(K)+Warn. NIE Crash.
- Solver: build_optimizer_context/run_solver bekommen use_subclass_correlation=False.
  Aktiv nur wenn flag UND sub_allocations UND sub_class_intra_correlation<1.0. Cache-Key += "SUB"+intra_rho.

UMSETZUNG #47 (Currency-aware) in scenario_engine.py:
- NEU: CurrencyInputs, currency_inputs_from_cma(cma,*,base_currency,asset_labels,fx_source,hedge_ratio_bps_per_asset=None),
  apply_currency_to_return_factors(asset_factors,currency,*,seed,antithetic).
  FX: mu_fx=0; log_fx=-0.5*sig^2+sig*Z_fx (rng seed XOR 0x46580000);
  r_fx_eff=hedge+(1-hedge)*r_fx; drag=(1-cost/10000)^hedge. base==Heimwährung -> Identity.
- NEU CMA-Felder (nullable, opt-in) in models/allocation.py: asset_currency_map_json,
  fx_volatility_bps_json, fx_hedge_cost_bps_json + Default-Code-Konstanten.
- Solver: use_currency_risk=False, base_currency aus mandate, fx_source via FXRateSource.from_db.
  FX auf Sub-Ebene wenn #45 aktiv, sonst Bucket-Ebene. Cache-Key += "FX"+base_currency.

NICHT ÄNDERN: scenario_inputs_from_cma, build_scenario_paths, simulate_wealth_paths,
_weighted_bucket_metrics, _DEFAULT_CORRELATION_MATRIX.

TESTS: tests/test_optimizer_subclass_correlation.py + tests/test_optimizer_currency_risk.py (siehe Spec §4).
Alle bestehenden Optimizer-Tests OHNE Änderung grün (default-off).
OWNER-DECISIONs OD-45-A..D / OD-47-A..D / OD-COMMON im PR-Text bestätigen lassen.
VOR jedem Commit: git branch --show-current == codex/u45-optimizer-subclass-currency.
```
