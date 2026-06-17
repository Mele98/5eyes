# 5eyes Engine Specification — Mathematische Grundlage

**Status:** Living Document
**Version:** 1.0.0 (2026-06-06, A1 Sprint)
**Scope:** Formale Spec der Stochastic-Optimizer-Engine fuer externen Audit (Codex, FINMA) und Implementations-Selbstpruefung
**Out-of-Scope:** PDF-Rendering, Datenaggregation, Frontend-State

---

## 0. Lese-Konvention

| Symbol         | Bedeutung                                                  |
|----------------|------------------------------------------------------------|
| `N`            | Anzahl Monte-Carlo-Pfade (`n_paths`, typisch 2000)          |
| `T`            | Anzahl Jahre (`horizon_years`, typisch 10-30)               |
| `B`            | Anzahl Asset-Buckets (5: Liquidity, Bonds, Equities, RE, Alt) |
| `w_b`          | Allocation-Gewicht in Bucket b (decimal, summe = 1.0)      |
| `μ_b`          | Erwarteter log-return Bucket b p.a. (decimal)              |
| `σ_b`          | Vola Bucket b p.a. (decimal)                               |
| `s_b`          | Skewness Bucket b (decimal, clamped [-1,1])                |
| `k_b`          | Excess Kurtosis Bucket b (decimal, clamped [0,8])          |
| `Z_{p,t,b}`    | Standard-Normal Pfad p, Jahr t, Bucket b                   |
| `R_{p,t,b}`    | Return-Faktor Pfad p, Jahr t, Bucket b                     |
| `W_{p,t}`      | Wealth Pfad p, Ende Jahr t                                 |
| `CF_t`         | Netto-Cashflow Jahr t (Income - Expense)                   |
| `L_t`          | Liability (Goal-Outflow) Jahr t                            |
| `τ_g`          | Min. Erfolgs-Wahrscheinlichkeit fuer Goal g (Default 80%)  |
| `h_g`          | Hardness-Gewicht (hart=10, primaer=1, opp=0.2)             |
| `λ`            | Chance-Constraint-Penalty (Default 10^6)                   |
| `μ_shift`      | Mean-Shift-Vektor fuer Importance Sampling                 |
| `Λ_{is}`       | Block-Diagonal Korrelations-Matrix                         |

bps = basis points (1 bps = 0.01%). 10000 bps = 100% = decimal 1.0.

---

## 1. Scenario-Generierung — Monte-Carlo Pfade

### 1.1 Cornish-Fisher Fat-Tail-Erweiterung

Standard-Normal `Z` wird mit Skewness und Excess-Kurtosis erweitert zu Z*:

```
Z* = Z + (Z² - 1)·s/6 + (Z³ - 3·Z)·k/24 - (2·Z³ - 5·Z)·s²/36
```

**Code:** `services/optimizer/scenario_engine.py:68` (`cornish_fisher_array`)

**Clamping:** `s ∈ [-1, 1]`, `k ∈ [0, 8]` (Boudt/Peterson/Croux 2008 sichere Bereiche).
Werte ausserhalb -> NaN-Propagation moeglich. Clamping verhindert Singularitaeten.

**Literatur:**
- Cornish, E. A.; Fisher, R. A. (1937). "Moments and Cumulants in the Specification of Distributions"
- Glasserman (2004), "Monte Carlo Methods in Financial Engineering", Sec 4.6

**Test:** `tests/test_optimizer_distributions.py` (15 tests).

---

### 1.2 Korrelations-Struktur (Cholesky)

Korrelations-Matrix `Σ ∈ R^{B×B}` wird via Cholesky-Decomposition `Σ = L · L^T` zerlegt.

Korrelierte Stichproben:
```
Z_corr = einsum("phb, kb -> phk", Z_iid, L)
```

**Code:** `services/optimizer/scenario_engine.py:151-155`

**Fallback bei nicht-positiv-definiter Matrix:** Identity (uncorrelated).
**Code:** `_safe_cholesky` Zeile 98.

**Source-of-Truth Korrelationsmatrix:** `services/portfolio_engine.py:_DEFAULT_CORRELATION_MATRIX`. Identische Werte in scenario_engine + portfolio_engine erzwungen (Sprint U-P0 Fix C7).

**Default-Werte (CH-Markt, konservativ):**
| Buckets        | Equities | Bonds  | RE    | Alt    | Liq   |
|----------------|----------|--------|-------|--------|-------|
| **Equities**   | 1.00     | -0.20  | 0.60  | 0.30   | 0.00  |
| **Bonds**      | -0.20    | 1.00   | 0.10  | 0.10   | 0.05  |
| **RE**         | 0.60     | 0.10   | 1.00  | 0.20   | 0.00  |
| **Alt**        | 0.30     | 0.10   | 0.20  | 1.00   | 0.00  |
| **Liq**        | 0.00     | 0.05   | 0.00  | 0.00   | 1.00  |

**Test:** `tests/test_optimizer_scenario_engine.py:correlation_*`.

---

### 1.3 Antithetic Variates

Standard-Variance-Reduction (Glasserman 2004 Sec 4.2):

- Generiere `N/2` Pfade mit `Z`
- Spiegel-Pfade: `Z_anti = -Z` (zweite Haelfte)
- Verkettung: `Z_combined = concat(cornish_fisher(Z), cornish_fisher(-Z))`

**Code:** `services/optimizer/scenario_engine.py:144-168`

**Wirkung:** Varianz-Reduktion 30-50% fuer symmetrische Statistiken (Mean, Median). Bei Tail-Statistiken (P1, P99) weniger effektiv -> Importance Sampling.

**Aktivierung:** Default an (`antithetic=True`).

---

### 1.4 Itô-Korrektur + Log-Normal-Returns

Aus Z* werden multiplikative Return-Faktoren:

```
R_{p,t,b} = exp(μ_b - 0.5·σ_b² + σ_b · Z*_{p,t,b})
```

Die `- 0.5·σ_b²` ist die Itô-Korrektur fuer log-normal Drift-Korrektur. Ohne sie waere `E[R] = exp(μ + 0.5·σ²)` statt `exp(μ)`.

**Code:** `services/optimizer/scenario_engine.py:171-174`

**Test:** `tests/test_optimizer_scenario_engine.py:test_drift_calibration`.

---

### 1.5 Deterministischer Seed

```
seed = hash_truncate(SHA256(cma_id || goal_ids || score || horizon || n_paths))
```

**Code:** `services/optimizer/solver.py:367-378` (`deterministic_seed`)

**Garantien:**
- Identische Inputs -> identischer Seed -> identische Pfade
- 63-Bit-Trunc (NumPy `uint64`-Konvention)
- Verifizierbar via Hash-Vergleich

**Test:** `tests/test_optimizer_context.py:test_build_context_with_explicit_seed_is_deterministic`.

---

## 2. Importance Sampling (Mean-Shift)

### 2.1 Mathematischer Ansatz (Glasserman 2004 Sec 4.6)

Statt aus `N(0, I)` zu sampeln, sampeln wir aus `N(μ_shift, I)`. Die Likelihood-Ratio (Radon-Nikodym derivative):

```
w_p = exp( - Σ_t Z_{p,t}·μ_shift + 0.5·T·||μ_shift||² )
```

So dass fuer beliebige integrable f:
```
E_{N(0,I)}[f(Z)] = E_{N(μ_shift,I)}[f(Z) · w(Z)]
```

**Code:** `services/optimizer/importance_sampling.py:94` (`compute_likelihood_weights`)

**Default Shift-Vektor (5-Bucket-Welt):**
```
μ_shift = [0, 0, -0.5, -0.5, 0]
            (Liq, Bonds, Eq_CH, Eq_Intl, Alt)
```

Rationale: Tail-kritisch sind Aktien-Drawdowns. Shift in negative Aktien-Returns -> mehr Stichproben im Shortfall-Bereich.

### 2.2 Auto-Aktivierungs-Logik (Sprint P1, 2026-06-06)

IS wird automatisch aktiviert wenn mindestens einer der folgenden Trigger zutrifft:

1. `score_x10 ≤ 30` (Risikoprofil Sicherheit/Konservativ)
2. `is_retired = True` (Decumulation-Phase, Sequence-of-Returns-Risk)
3. mindestens ein Goal mit `hardness = "Hart"`

**Code:** `services/optimizer/importance_sampling.py:should_auto_enable_is`

**Settings:**
- `mc_importance_sampling_enabled` (Default `False`): Force-On-Flag
- `mc_importance_sampling_auto_enable` (Default `True`): Auto-Decision

**Wirkung:**
- IS aktiv -> Tail-Statistik (P1, P5) reduziert Varianz 5-50x
- IS inaktiv -> uniformer Sample-Mean, optimal fuer Erwartungswerte

**Test:** `tests/test_optimizer_is_auto_activation.py` (21 tests).

---

## 3. Wealth-Simulation pro Pfad

### 3.1 Update-Formel pro Jahr

Wealth-Pfad `W_{p, t+1}` wird aus `W_{p,t}` berechnet:

```
portfolio_factor_p,t = Σ_b w_b · R_{p,t,b}

grown_p,t = {
    W_{p,t} · portfolio_factor_p,t,    falls W_{p,t} > 0
    W_{p,t},                            sonst (negative bleibt nominal, kein Schuldzins)
}

[Optional: Steuer-Drag wenn tax_regime gesetzt]
grown_p,t -= grown_p,t · (div_drag_bps + wealth_tax_bps) / 10000

W_{p, t+1} = grown_p,t + CF_t - L_t
```

**Code:** `services/optimizer/scenario_engine.py:268` (`simulate_wealth_paths`)

### 3.2 Steuer-Order (wenn `tax_regime` aktiv)

1. Wachstum: `prev × portfolio_factor`
2. Dividenden-Steuer auf Yield-Komponente:
   ```
   div_income = wealth × (Σ_b w_b · yield_b)
   div_drag_bps = tax_regime.dividend_tax(ctx, div_income).effective_bps × weighted_yield / 10000
   ```
3. Vermoegenssteuer auf Wealth-after-growth (nur bei `supports_wealth_tax`):
   ```
   wt_drag_bps = tax_regime.annual_wealth_tax(ctx).effective_bps
   ```
4. Cashflow + Liability-Outflow

**WICHTIGE EINSCHRAENKUNG (Sprint P1 Audit):**
`TaxContext.wealth_rappen` ist der **MEDIAN ueber positive Pfade**, nicht per-Pfad. Das ist eine Vereinfachung — fuer CH-HNW mit Vermoegenssteuer 0.3-0.9% nicht ideal. Behoben in Sprint B2 (P3 Per-Pfad-Tax).

**Code-Zeile:** `services/optimizer/scenario_engine.py:401`

### 3.3 Mortalitaets-Maske

Wenn `death_year_index_per_path` gesetzt:
- Pfad p stirbt in Jahr `d_p`
- Fuer `t >= d_p`: `CF_t = L_t = 0`
- Wachstum laeuft weiter (Erbschaft)

**Code:** Zeile 351-365

**Test:** `tests/mortality/test_optimizer_context.py`

### 3.4 Lebensluecke-Konvention (W2.5)

Wenn `W_{p,t} < 0`:
- Kein Schuld-Zins (`grown = prev`, nicht `prev × factor`)
- Keine Steuer-Anwendung
- Weitere Negative-Cashflows summieren linear

Ratio: Realistisch gibt es keinen Kredit-Mechanismus in einem Vermoegensverwaltungs-Mandat. Negative Wealth ist die "Lebensluecke" — der Berater muss vorher gegensteuern.

**Code:** Zeile 388-390 (`grown = np.where(prev > 0, prev * portfolio_factor, prev)`)

---

## 4. Goal-zu-Liability-Transformation

### 4.1 Goal-Typen (6 Klassen)

| Goal-Typ              | target_kind         | Bewertung pro Pfad                                   |
|-----------------------|---------------------|------------------------------------------------------|
| Vermoegensziel        | `wealth_at_t`       | `W_{p,T_target} >= target_amount`                    |
| Renditeziel           | `return_rate`       | annualisierte Return `>= target_bps`                 |
| Einmalige Ausgabe     | `cashflow_in_year`  | `W_{p,T_event} >= target_amount` (Liability sub.)    |
| Wiederkehrende Ausg.  | `outflow_stream`    | `W_{p,T_end} >= 0` (kumuliert abgedeckt)             |
| Pensionsausgabe       | `outflow_stream`    | wie wiederkehrend, mit Start-Datum                    |
| Maximierung           | `maximize`          | keine Constraint, nur Vol-Min-Term                    |

**Code:** `services/optimizer/goal_liabilities.py:goals_to_liabilities` (Zeile 256-430)

### 4.2 Aggregierte Liability-Path

Jeder Goal `g` liefert `liability_path_g ∈ R^T`. Aggregiert:
```
L_t = Σ_g liability_path_g[t]
```

**Code:** `services/optimizer/goal_liabilities.py:aggregate_liability_path`

### 4.3 Inflation-Behandlung

`value_mode = "real"`: Liability wird mit Inflations-Series hochgezinst:
```
L_t = nominal_amount × Π_{i=0..t} (1 + inflation_i)
```

`value_mode = "nominal"`: keine Inflation (fixed Betrag).

**Code:** Zeile 218-244

### 4.4 Bedingte Goals

`probability_pct ∈ [0, 100]`: Goal tritt nur mit dieser Wahrscheinlichkeit ein.
- `100` = sicher
- `0` = nicht aktiv
- Sprint U-B6: Liability wird pro-rata gewichtet

### 4.5 Goal-Status: zwei Vokabulare (deterministisch vs stochastisch) — #6

Es gibt **zwei bewusst getrennte** Status-Systeme. Sie messen Verschiedenes und
dürfen **nicht** gleichgesetzt werden — die UI labelt sie entsprechend.

| Pfad | Kennzahl | Schwellen | Status-Begriffe | Code |
|---|---|---|---|---|
| **Deterministisch** (Zielmatrix, Default-/house_matrix-Pfad) | `achievement_score` 0-100 (Funded-Ratio-artiger Punkt-Schätzer: projiziertes/zielbezogenes Vermögen vs Zielbetrag) | **≥70 / ≥45** | On Track / Prüfen / Gefährdet | `portfolio_engine._build_goal_analysis` |
| **Stochastisch** (Optimizer, OPTIMIZER_MODE=stochastic) | `P_g` = Anteil MC-Pfade die das Ziel erreichen (Wahrscheinlichkeit, 0-1) | **≥τ / ≥0.50** (τ: 80% Vermögens-/Cashflow-Ziel, 50% Renditeziel) | erreichbar / knapp / nicht_erreichbar | `optimizer/objective.chance_constraint_penalty` |

**Warum unterschiedlich:** Der Score ist ein einzelner deterministischer Punkt-Schätzer
(eine Projektion), die Wahrscheinlichkeit eine Verteilungs-Aussage über viele MC-Szenarien.
Ein Ziel kann deterministisch „On Track" und stochastisch „knapp" sein (Punkt-Schätzer trifft,
aber das Verteilungsband reicht unter τ). Das ist **kein Widerspruch**, sondern komplementäre
Information. UI-Badges: deterministisch = „Score", stochastisch = „Zielerreichungs-
Wahrscheinlichkeit" (5eyes_v2.html: dt. Score ~Z.5483, stoch. ~Z.5035-5043).

---

## 5. Objective-Funktionen

### 5.1 Shortfall L(w) — Primary Objective

```
L(w) = Σ_g  h_g · g_g · (1/N) · Σ_p shortfall²_g(W_p(w))

mit:
  h_g  = HARDNESS_WEIGHT[hardness_key]  (hart=10, primaer=1, opp=0.2)
  g_g  = goal.weight_bps / 10000
  shortfall_g(W_p) = max(0, target_g - W_{p,T_target})  (typ-spezifisch)
```

**Code:** `services/optimizer/objective.py:shortfall_objective` (Zeile 205)

**Mit IS-Weights (Sprint P1):**
```
L(w) = Σ_g  h_g · g_g · ( Σ_p w_p · shortfall²_g ) / Σ_p w_p
```

Wobei `w_p` die Likelihood-Ratio-Gewichte sind.

**Hardness-Gewichte (OWNER-DECISION OD-1):**
- `hart` = 10.0
- `primaer` = 1.0
- `opportunistisch` = 0.2

Spread 50x zwischen `hart` und `opportunistisch` — bewusst stark, damit harte Goals dominieren.

### 5.2 Volatility-Objective — Secondary

```
Var(w) = Var_p(W_{p,T})  (Endvermoegen-Varianz)
```

Mit IS-Weights:
```
Var(w) = Σ_p w_p · (W_p - mean_w)²  /  Σ_p w_p
mean_w = Σ_p w_p · W_p  /  Σ_p w_p
```

**Code:** `services/optimizer/objective.py:volatility_objective`

### 5.3 Combined Two-Phase

```
combined(w) = primary_weight · L(w) + volatility_weight · Var(w)
            + lambda_chance · Σ_g max(0, τ_g - P_g)²  · [g ist primaer/hart]
```

Defaults:
- `primary_weight = 1.0`
- `volatility_weight = 1e-12` (rappen² ist gross, daher kleiner Multiplikator)
- `lambda_chance = 10^6`

**Code:** `services/optimizer/objective.py:combined_objective_two_phase` (Zeile 404)

### 5.4 Chance-Constraint-Penalty

Pro Goal:
```
P_g = (1/N) · Σ_p 1{Goal g erreicht in Pfad p}    (uniform)

oder mit IS:

P_g = Σ_p w_p · 1{Goal g erreicht in Pfad p}  /  Σ_p w_p
```

Status-Klassifikation:
- `P_g >= τ_g` -> "erreichbar"
- `0.5 <= P_g < τ_g` -> "knapp"
- `P_g < 0.5` -> "nicht_erreichbar"

`τ_g` Defaults: 80% (Vermoegensziel), 50% (return_rate), 100% (maximize).

**Code:** `services/optimizer/objective.py:chance_constraint_penalty` (Zeile 169)

**Penalty greift nur bei `hardness ∈ {hart, primaer}`** — opportunistische Goals werden nicht erzwungen.

---

## 6. Constraint-System

### 6.1 Bucket-Bounds (House-Matrix)

Pro Risikoprofil sind min/max-Bandbreiten pro Bucket gegeben:
```
w_b ∈ [bucket_min_b, bucket_max_b]
```

**Code:** `services/optimizer/constraints.py:build_bounds` (Zeile 77-104)

**Source:** `services/recommendation.py:HOUSE_MATRIX` (5 Profile × 5 Buckets × 3 Werte).

### 6.2 Sum-to-One Equality (Hard)

```
Σ_b w_b = 1.0      (Jacobian-aware fuer SLSQP)
```

**Code:** Zeile 133-139

### 6.3 Globale Caps (Hard)

- `w_RE <= 20%`
- `w_Alt <= 10%`
- `w_Liq >= 2%`

**Code:** Zeile 59-62

### 6.4 Risky-Fraction-Cap

```
Σ_b∈risky w_b · risky_fraction_b <= max_risky_fraction
```

`max_risky_fraction` skaliert mit `score_x10`:
- `score_x10 = 100` (Wachstum) -> `0.95`
- `score_x10 = 0` (Sicherheit) -> `0.30`

**Code:** Zeile 142-162

### 6.5 Building-Block-Granularitaet

Innerhalb eines Buckets koennen Building-Blocks unterschiedliche Risky-Fractions haben (z.B. Equity-Bucket = 100% risky, Bonds-Bucket = 30%). Wird aus House-Matrix-Setup eingelesen.

**Code:** Zeile 142-162 (`build_risky_fraction_constraint`)

---

## 7. Solver-Pipeline

### 7.1 Multi-Start SLSQP

5 Initial-Allocations:
1. `Mid-Bounds` — Mitte der Bounds
2. `Conservative` — Min-Aktien + Max-Bonds
3. `Aggressive` — Max-Aktien + Min-Bonds
4. `Risk-Cap-Edge` — Allokation am `max_risky_fraction`-Rand
5. `Equal-Weight` — gleichmaessig verteilt

**Code:** `services/optimizer/solver.py:_build_initials` (~Zeile 447-509)

Jeder Init startet einen SLSQP-Solver-Run. Beste konvergente feasible Allocation gewinnt.

### 7.2 GA-Fallback (Differential Evolution)

Wenn alle SLSQP-Multi-Starts divergieren ODER kein feasible Kandidat:
- `scipy.optimize.differential_evolution` mit gleichen Bounds + Constraints
- Population 30, Max-Iter 100

**Code:** Zeile ~595-625

### 7.3 Robustification (Stage 9 Hardening)

Wenn SciPy `success=False` meldet, aber Allocation:
- `is_feasible(w)` = True (alle Constraints erfuellt)
- `objective(w)` ist finite

-> Akzeptiere als "robustified" mit Status `converged_robustified`.

**Code:** Zeile 628-741

### 7.4 Derisk-Tiebreak

Bei zwei Solutions mit objective-Differenz < 5%:
- Bevorzuge weniger riskante (niedrigere `risky_fraction`)
- Bevorzuge weniger Equity

**3eyes-Philosophie:** "So viel Risiko wie noetig, aber bei gleichwertiger Zielerreichung die defensivere Allokation."

**Code:** Zeile 1000-1015

### 7.5 Status-Codes

| Status                       | Bedeutung                                                     |
|------------------------------|---------------------------------------------------------------|
| `converged`                  | SLSQP konvergiert + feasible                                  |
| `converged_robustified`      | SciPy unsicher, aber Allocation strict feasible (Stage 9)     |
| `diverged_infeasible`        | Beste Allocation verletzt Constraints                         |
| `fallback_house_matrix`      | Alle Multi-Starts + GA divergiert -> House-Matrix-Mid         |

### 7.6 Output: OptimizerResult

```python
@dataclass
class OptimizerResult:
    weights_bps: dict[str, int]  # {bucket: bps, sum=10000}
    objective_value: float
    status: str
    method: str  # 'SLSQP' | 'SLSQP+DE-Fallback' | 'fallback_house_matrix'
    reasoning: list[str]  # Audit-Trail
    goal_achievability: tuple[dict, ...]  # Pro Goal: probability, status, hardness
    robustification: dict | None  # Stage-9 Audit-Info
    restart_results: tuple[...]  # Pro Multi-Start: convergence, objective
    stress_results: dict | None  # 3 Krisen-Szenarien (1929, 2008, 2020)
```

---

## 8. Stress-Szenarien (Audit-Erweiterung)

3 hart-codierte historische Pfade:
- **Great Depression 1929** — Aktien -85%, Bonds +30%
- **Financial Crisis 2008** — Aktien -50%, Bonds +10%
- **COVID + Inflation 2020-22** — Aktien volatil, Bonds -15% (real)

**Code:** `services/optimizer/stress_scenarios.py:43-68`

Berechnet POST-Optimization End-Wealth in jedem Pfad. Berater sieht "wie haette diese Allocation 2008 abgeschnitten".

**Test:** `tests/test_optimizer_stress_scenarios.py`

---

## 9. Bekannte Vereinfachungen + Roadmap

| Punkt | Aktuell                                          | Geplant (Sprint)         |
|-------|--------------------------------------------------|--------------------------|
| Sub-Allocation | Bucket-Returns = einfache Durchschnitt    | B1 (P2 Sub-Alloc-Aware)  |
| Tax-Context | Median-Wealth in TaxContext (nicht per-Pfad) | B2 (P3 Per-Pfad-Tax)     |
| Multi-Currency | `Cashflow.currency` ignoriert              | B3 (P4 Multi-Currency)   |
| Stress-Szenarien | Nur 3 historische Pfade hart-codiert     | Spaeter (faktorisiert)   |
| Yield-Curve | Nelson-Siegel nur fuer Bonds-Bucket          | OK fuer 5-Bucket-Welt    |

Diese Vereinfachungen sind **bewusste Scope-Entscheidungen**, nicht Bugs. Roadmap in `[[5eyes-engine-hardening-plan-p1-bis-p5]]`.

---

## 10. Cross-Reference Tabelle

| Funktion                           | Spec-Section | Code                                                 | Test                                          |
|------------------------------------|--------------|------------------------------------------------------|-----------------------------------------------|
| `cornish_fisher_array`             | 1.1          | scenario_engine.py:68                                | test_optimizer_distributions.py               |
| `_safe_cholesky`                   | 1.2          | scenario_engine.py:98                                | test_optimizer_scenario_engine.py             |
| `build_scenario_paths`             | 1.3, 1.4     | scenario_engine.py:121                               | test_optimizer_scenario_engine.py             |
| `build_scenario_paths_with_weights`| 2.1          | scenario_engine.py:178                               | test_scenario_engine_is_wrapper.py            |
| `simulate_wealth_paths`            | 3            | scenario_engine.py:268                               | test_optimizer_scenario_engine.py             |
| `should_auto_enable_is`            | 2.2          | importance_sampling.py:should_auto_enable_is         | test_optimizer_is_auto_activation.py          |
| `decide_is_for_context`            | 2.2          | importance_sampling.py:decide_is_for_context         | test_optimizer_is_auto_activation.py          |
| `goals_to_liabilities`             | 4.1          | goal_liabilities.py:256                              | test_optimizer_goal_liabilities.py            |
| `aggregate_liability_path`         | 4.2          | goal_liabilities.py:aggregate_liability_path         | test_optimizer_goal_liabilities.py            |
| `shortfall_objective`              | 5.1          | objective.py:205                                     | test_optimizer_objective_constraints.py       |
| `volatility_objective`             | 5.2          | objective.py:volatility_objective                    | test_optimizer_objective_with_weights.py      |
| `combined_objective_two_phase`     | 5.3          | objective.py:404                                     | test_optimizer_objective_constraints.py       |
| `chance_constraint_penalty`        | 5.4          | objective.py:169                                     | test_chance_constraint.py, test_optimizer_is_auto_activation.py |
| `build_bounds` + Constraints       | 6            | constraints.py                                       | test_optimizer_objective_constraints.py       |
| `build_optimizer_context`          | 7            | solver.py:188                                        | test_optimizer_context.py                     |
| `run_solver`                       | 7            | solver.py:783                                        | test_optimizer_solver.py, test_optimizer_integration.py |
| `deterministic_seed`               | 1.5          | solver.py:367                                        | test_optimizer_context.py                     |
| `evaluate_stress_scenarios`        | 8            | stress_scenarios.py                                  | test_optimizer_stress_scenarios.py            |

---

## 11. Literatur-Cross-Reference

| Konzept                          | Quelle                                                                              |
|----------------------------------|-------------------------------------------------------------------------------------|
| Cornish-Fisher                   | Cornish + Fisher (1937), "Moments and Cumulants in the Specification of Distributions" |
| Cholesky correlation             | Glasserman (2004), "Monte Carlo Methods in Financial Engineering", Ch. 2            |
| Antithetic Variates              | Glasserman (2004), Sec 4.2                                                          |
| Mean-Shift Importance Sampling   | Glasserman (2004), Sec 4.6                                                          |
| Itô-Korrektur log-normal         | Hull (2017), "Options, Futures, and Other Derivatives", Ch. 14                      |
| Multi-Period ALM                 | Mulvey + Ziemba (1995), "Asset and Liability Allocation in a Global Environment"    |
| Goal-Based Investing             | Brunel (2011), "Goals-Based Wealth Management"                                      |
| Performance Attribution          | Brinson + Hood + Beebower (1986), "Determinants of Portfolio Performance"           |
| SLSQP                            | Kraft (1988), "A Software Package for Sequential Quadratic Programming"             |
| Differential Evolution           | Storn + Price (1997), "Differential Evolution"                                      |
| Skewness/Kurtosis Clamping       | Boudt + Peterson + Croux (2008), "Estimation and Decomposition of Downside Risk"    |

---

## 12. Lifecycle dieses Dokuments

| Trigger                                  | Aktion                                          |
|------------------------------------------|-------------------------------------------------|
| Engine-Code-Change                       | Spec UPDATE im selben PR                        |
| Neue Conformance-Anforderung             | Section 9 erweitern                             |
| Externer Audit (Codex/FINMA)             | Section 10 Cross-Reference fuer Auditor      |
| Major-Version-Bump                       | Spec auf neues Major-Version-Doc kopieren       |

**Drift-Protection:** Diese Spec MUSS bei jedem Engine-Code-Change im selben PR aktualisiert werden. Reviewer pruefen Drift Spec↔Code als Pflicht-Item.
