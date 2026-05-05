# Stochastischer Optimizer — Master-Spec

## Meta

- **Titel**: Goal-Based Stochastic Optimizer (Mulvey/Ziemba-light)
- **Datum**: 2026-05-05
- **Owner**: Emanuele
- **Branch**: `codex/stochastic-optimizer` (abgezweigt von `codex/audit-master`)
- **Backup**: Tag `pre-optimizer-2026-05-05` + Bundle `C:\5eyes\audit-master-backup-2026-05-05.bundle`
- **Status**: Draft v0.1 (zum Review durch Emanuele)

## Ziel

5eyes von "House-Matrix-Default + Goal-Tilts" zu echter goal-basierter Allokation upgraden, wie 3eyes-Schulung Slide 18 sie definiert: **Optimierung minimiert Fehlbeträge über alle Szenarien, sekundär minimiert Volatilität wenn Ziele erfüllt**. Ergebnis: erklärbare, reproduzierbare Allokation pro Mandat, die mathematisch nachvollziehbar gegen die individuellen Lebensziele optimiert ist — nicht ein generisches Profil mit nachträglichen Tilts.

## Problem (heute)

`portfolio_engine.py::_apply_goal_and_reserve_tilts` startet mit der `HouseMatrix`-Profil-Allokation (basierend nur auf Risiko-Score) und appliziert dann statische Tilts. Goal-Score (`_compute_goal_score`) ist eine **post-hoc Bewertung**, kein Optimierungs-Driver. Konkret:

- Ziele beeinflussen nur über 2–3 manuelle Tilt-Regeln (`Vermoegensziel ≤5J → eq_reduction`, Reserve-Ceiling)
- Hardness (hart/primaer/opp) wirkt nur in der Score-Aggregation, nicht in der Allokationswahl
- Verschiedene Mandate mit gleichem Risikoprofil aber unterschiedlichen Goals → fast identische Allokation
- Die 3eyes-Schulung beschreibt explizit: "Optimierung gegen vordefinierte Modellportfolios **oder** Hyperpersonalisierung der SAA". 5eyes ist heute "vordefiniert".

## Scope

- Neuer Solver-Pfad: Sample-Average-Approximation (SAA) der Mulvey/Ziemba-Stochastik
- Goals werden zu Liability-Cashflow-Pfaden konvertiert
- Distributions-Engine mit Cornish-Fisher (Skewness + Kurtosis) statt Normal
- NumPy-Vektorisierung des MC-Loops (Voraussetzung: Solver braucht ≥1000 Pfade × ≥30 Iter)
- Feature-Flag `OPTIMIZER_MODE` mit 3 Modi: `house_matrix` (heute), `iterative` (Soft), `stochastic` (voll)
- Audit-Anchors: Solver-Seed, Iterations, Objective-Value, Konvergenz-Status pro `target_allocation`
- Constraints: Risky-Fraction-Cap aus Risiko-Score, House-Matrix-Bands als Min/Max, RE/Alts-Caps

## Nicht-Scope (= eigene spätere Specs)

- Sub-Asset-Class-Optimierung (Bonds CHF vs Bonds Global): bleibt fix per Building Block
- Steuern (Vermögens-/Einkommensteuer): kommt in v2
- Mortalitätsadjustierte Pensionen: v2 (BFS-Sterbetafel)
- Async-Background-Tasks für >5s-Laufzeiten: kommt wenn Performance-Problem akut
- FE-Optimization-Panel (Sensitivity, Reasoning-Trace): eigene Codex-Spec
- Verbindung zu echten SLAM-Daten-Feeds: heute manuelle CMA-Pflege

## Fachlogik

### Quellen

- **3eyes-Schulung 2024-04-09 (SLWM intern)**: Slide 10 (Mulvey/Ziemba), Slide 15 (Risky Fraction = Risiko-Score×10%), Slide 17 (Building Blocks), Slide 18 (Optimierungshierarchie), Slide 19 (SLAM-Inputs Skewness/Kurtosis)
- **Mulvey/Vladimirou 1992** "Stochastic Network Programming for Financial Planning Problems"
- **Ziemba/Mulvey 1998** *Worldwide Asset and Liability Modeling* (Cambridge UP)
- **Rockafellar/Uryasev 2000** "Optimization of Conditional Value-at-Risk", *J. Risk*
- **Brunel 2003** "Revisiting the Asset Allocation Challenge through a Behavioral Finance Lens", *J. Wealth Management*
- **Das/Markowitz/Scheid/Statman 2010** "Portfolio Optimization with Mental Accounts", *JFQA*
- **Vanguard 2015** "Goal-Based Investing"
- **Cornish/Fisher 1937** "Moments and Cumulants in the Specification of Distributions"
- **Roy 1952** "Safety First and the Holding of Assets", *Econometrica* — Shortfall-Konzept

### Verbindliche Regeln (aus 3eyes-Slide 18)

1. **Priorität 1**: Minimiere Σ_g hardness_weight_g · E[max(0, target_g − wealth_g)^2] über alle Szenarien
2. **Priorität 2**: Wenn (1) ≤ ε → minimiere Var(terminal_wealth)
3. **Risky-Fraction-Cap**: Σ_b w_b · risky_fraction_b ≤ score_x10 / 10 (z.B. Score 70 → max 70% risky)
4. **House-Matrix-Bands**: w_b ∈ [min_b, max_b] aus aktiver `HouseMatrix`-Zeile für score_bucket
5. **RE-Cap**: w_real_estate ≤ 20%
6. **Alts-Cap**: w_alternatives ≤ 10%
7. **Liquidity-Floor**: w_liquidity ≥ 2% immer
8. **Sum-to-One**: Σ_b w_b = 1.0
9. **Hardness-Hierarchie**: harte Goals werden 50× stärker bestraft als opportunistische (hard_weight = 10, primary = 1, opp = 0.2)
10. **Reproduzierbarkeit**: Solver-Seed deterministisch aus (mandate_id, cma_id, goals_hash, score_bucket) — gleicher Input → gleicher Output

### Mathematische Definitionen

Für Mandant mit:
- Beratungsvermögen W₀ (rappen)
- Goal-Liste {g₁, …, g_G}
- CMA mit μ_i (return), σ_i (vol), s_i (skew), k_i (excess kurt) pro Asset i ∈ {1..A}
- Korrelationsmatrix Σ
- Cashflow-Pfad c_t (Income − Expense, ohne Goals)
- Liability-Pfad L_t = Σ_g goal_outflow_g(t) (negativ für Outflow)

Wir optimieren über Asset-Gewichte w = (w_equities, w_bonds, w_real_estate, w_alternatives, w_liquidity), Σw_i = 1.

**Szenario-Pfad** für Pfad n und Jahr t:
```
W_{n,t+1}(w) = (W_{n,t} × Σ_i w_i × R_{n,t,i}) + c_{t+1} − L_{t+1}
```
mit R_{n,t,i} = log-normal Return mit Cornish-Fisher-Adjustment für Asset i in Pfad n, Jahr t.

**Goal-Wealth** an Auswertungszeitpunkt T_g pro Goal:
```
WG_{n,g}(w) = W_{n,T_g}(w)
```

**Shortfall pro Goal pro Pfad**:
```
SF_{n,g}(w) = max(0, target_g − WG_{n,g}(w))^2
```

**Objective Function**:
```
ℒ(w) = Σ_g hardness_weight_g × goal_weight_g × (1/N) × Σ_n SF_{n,g}(w)
```

**Optimierung**:
```
min_w   ℒ(w)
s.t.    Σ_b w_b · risky_fraction_b ≤ score_x10 / 10
        min_b ≤ w_b ≤ max_b      ∀b
        w_real_estate ≤ 0.20
        w_alternatives ≤ 0.10
        w_liquidity ≥ 0.02
        Σ_b w_b = 1.0
```

**Sekundäre Optimierung** (wenn ℒ(w*) ≤ ε):
```
min_w   Var_n(W_{n,T}(w))
s.t.    ℒ(w) ≤ ℒ(w*) + δ      (lasse minimal Spielraum für Vol-Min)
        + alle Constraints oben
```

### Cornish-Fisher Distribution

Statt Z ~ N(0,1) ziehen wir Z̃ = Z + (Z²−1)·s/6 + (Z³−3Z)·k/24 − (2Z³−5Z)·s²/36, wobei s = skew, k = excess kurt.

Begründung: Realdaten Aktien haben s ≈ −0.5, k ≈ 4–6 (fat left tail). Mit Cornish-Fisher Z̃ liefert das die richtige Krise-Frequenz ohne externe Library. **Limitation**: für extremen Skew/Kurt kann CF nicht-monoton werden — wir clampen Inputs auf s ∈ [−1, 1], k ∈ [0, 8].

### Goal → Liability Konvertierung

| Goal-Typ | Liability-Pfad L_t | Auswertungszeitpunkt T_g | Target |
|---|---|---|---|
| `Renditeziel` | 0 (kein Outflow) | Horizont | annualized_return ≥ target_return_bps |
| `Kapitalerhalt` | 0 | T_target_date | W_T ≥ target_wealth_rappen × (1+infl)^T (wenn real) |
| `Vermoegensziel` | 0 | T_target_date | W_T ≥ target_wealth_rappen |
| `Einmalige_Ausgabe` | 0 außer L_{T_target} = +amount | T_target_date | W_T ≥ amount |
| `Wiederkehrende_Ausgabe` | L_t = annual_amount für t ∈ [start, end] | min(end, horizon) | Σ duration ≤ projected |
| `Pensionsausgabe` | L_t = annual_amount × inflation_factor_t für t ≥ start | min(end, horizon) | analog |
| `Maximierung` | 0 | Horizont | trivial: score=100 wenn W_T > W_0 |

### OWNER-DECISIONS (Emanuele entscheidet)

1. **OD-1**: Hardness-Multiplier — aktuell habe ich `_GOAL_HARDNESS_MULTIPLIER_BPS = {hart: 20000, primaer: 10000, opp: 4000}` (Faktor 5x zwischen hart/opp). Vorschlag für Optimizer: `{hart: 10.0, primaer: 1.0, opp: 0.2}` (Faktor 50x). Begründung: Bei der **Aggregation** zu einem Score reicht 5x. Bei der **Optimierung** brauchen wir 50x, sonst überstimmen viele opportunistische Goals ein hartes. ✅ **Default**: 50x. **Frage Emanuele**: Stimmst du zu? Oder sollte das aus Fachlogik anders sein?

2. **OD-2**: Shortfall-Exponent k. k=2 (squared) bestraft große Fehlbeträge stärker (Standard in PK-ALM). k=1 (linear) ist gleichmäßiger. ✅ **Default**: k=2. **Frage**: 2eyes/Vorgängersystem nutzt was?

3. **OD-3**: Anzahl MC-Pfade für Optimizer. Mehr = stabiler aber langsamer. SAA-Theorie sagt N=1000 reicht für 5-dim-Optimierung, N=5000 für robusteres Tail-Verhalten. ✅ **Default**: N=2000 mit Antithetic = effektiv N=4000.

4. **OD-4**: Konvergenz-Toleranz ε für Switch zu Vol-Min (Priorität 2). ε = 1% des kleinsten Goal-Targets in Rappen? Oder absolut z.B. 1000 CHF? **Default**: ε = max(1000_00 rappen, 0.01 × min(target_g)).

5. **OD-5**: Was passiert wenn Optimizer divergiert (kein gültiges w gefunden)? **Default**: Fallback auf `house_matrix`-Modus mit reasoning-Note "Optimizer konnte keine zulässige Lösung finden — verwende House-Matrix-Default". **Frage**: oder Fehler an User zurückgeben?

6. **OD-6**: Risky-Fraction pro Asset. 3eyes-Slide 17 zeigt: Bonds CH 20%, Eq CH Large 70%, Eq EM 100%, RE CH 50%, Gold 80%. Soll ich diese Werte aus 3eyes-Slide 17 1:1 übernehmen? **Default**: ja, übernehmen.

7. **OD-7**: Building-Block-Konzept (Standard vs Alternative) jetzt einführen oder später? **Default**: später (eigene Spec). Heute reicht eine "Default Building Block" mit den Werten aus 3eyes-Slide 17.

8. **OD-8**: Multi-Period-Liability für Pensionen — wie viele Jahre simulieren? Aktuell horizon=10. Pension läuft 30+ Jahre. **Default**: horizon = max(30, max(goal_horizon)). Performance-Impact: Solver-Zeit wächst linear mit Jahren.

## Betroffene Module / Dateien

### Neu (in `5eyes-backend/services/optimizer/`)

- `__init__.py` — Public API: `optimize_allocation(mandate, goals, ...) → AllocationResult`
- `distributions.py` — Cornish-Fisher Sampler, Calibration
- `goal_liabilities.py` — Goal → Liability-Pfad-Konversion
- `scenario_engine.py` — Vektorisierte MC-Engine mit NumPy
- `objective.py` — Shortfall + Vol-Min Objective Functions
- `constraints.py` — Risky-Fraction + Bands + Caps
- `solver.py` — SLSQP-Wrapper mit Multi-Start
- `audit_trace.py` — Solver-Output für Audit-Anchor
- `tests/` — Unit-Tests pro Modul + Calibration-Tests gegen historische Daten

### Backend angepasst

- `services/portfolio_engine.py` — `_apply_goal_and_reserve_tilts` kriegt einen Branch je nach `OPTIMIZER_MODE`
- `models/allocation.py::TargetAllocation` — neue Audit-Felder `optimization_method`, `optimization_objective_value`, `optimization_iterations`, `optimization_seed`, `optimization_status`
- `models/allocation.py::CapitalMarketAssumption` — neue Felder pro Asset-Class: `*_skewness_bps`, `*_excess_kurtosis_bps`
- `schemas/allocation.py` — Schema-Erweiterung CMA + AllocationResponse
- `database.py::ensure_runtime_columns` — Migration der neuen Felder
- `config.py::Settings` — `optimizer_mode: str = 'house_matrix'`

### Frontend (Codex-Domäne)

- Optimization-Panel im Allocation-View (Status, Iterations, Convergence)
- Reasoning-Trace anzeigen
- "Sensitivity": Was wenn ich Goal X um 10% senke → CVaR-Reduktion zeigen
- CMA-Manager um Skew/Kurt-Felder erweitern (Admin)

### Datenmodell — DB-Migrations

```sql
ALTER TABLE target_allocations ADD COLUMN optimization_method TEXT;
ALTER TABLE target_allocations ADD COLUMN optimization_objective_value INTEGER; -- in milli für Präzision
ALTER TABLE target_allocations ADD COLUMN optimization_iterations INTEGER;
ALTER TABLE target_allocations ADD COLUMN optimization_seed INTEGER;
ALTER TABLE target_allocations ADD COLUMN optimization_status TEXT; -- "converged" | "diverged" | "timeout" | "fallback_house_matrix"

ALTER TABLE capital_market_assumptions ADD COLUMN equity_ch_skewness_bps INTEGER;
ALTER TABLE capital_market_assumptions ADD COLUMN equity_ch_excess_kurtosis_bps INTEGER;
ALTER TABLE capital_market_assumptions ADD COLUMN equity_intl_skewness_bps INTEGER;
ALTER TABLE capital_market_assumptions ADD COLUMN equity_intl_excess_kurtosis_bps INTEGER;
ALTER TABLE capital_market_assumptions ADD COLUMN bonds_chf_ig_skewness_bps INTEGER;
-- ... pro Asset-Class
```

Neuer Default: skew=0, kurt=0 → fällt zurück auf Normalverteilung (backwards-compat).

## API / Schnittstellen

### Erweiterte Response

`TargetAllocationGenerateResponse` bekommt neues Feld:
```python
class OptimizerAuditTrace(BaseModel):
    method: str  # "house_matrix" | "iterative" | "stochastic"
    objective_value_milli: int  # ℒ(w*) in milli-rappen²
    iterations: int
    seed: int
    status: str
    convergence_quality_pct: int  # 0-100, basierend auf Optimality-Gap
    constraints_active: list[str]  # welche Constraints binden bei Optimum
    reasoning: list[str]  # menschenlesbare Erklärung
    sensitivity: dict | None  # optional: was wenn Goal X um 10% sinkt
```

### Neue Endpunkte

- `POST /allocation/optimize-sensitivity` — Sensitivity-Analyse für interaktive UI (Codex-Spec)

## UI / UX (für später)

- **Status-Pill**: "Konvergiert (15 Iter, 1.2s)" / "Fallback (House-Matrix)"
- **Reasoning-Trace** als Bullet-Liste neben Allokations-Torte
- **Sensitivity-Slider**: pro Goal, ±20%, zeigt sofort neue CVaR
- **Constraint-Anzeige**: Welche Bänder/Caps sind aktiv (z.B. "RE-Cap binding")

## Akzeptanzkriterien

1. ✅ Mit `OPTIMIZER_MODE=house_matrix` (Default) verhält sich System exakt wie heute. Alle bestehenden Tests grün.
2. ✅ Mit `OPTIMIZER_MODE=stochastic` produziert Optimizer eine Allokation die in einem Test-Mandat (3 Goals: Pension hart, Erbschaft primaer, Renditeziel opp) **niedrigeren weighted_shortfall** liefert als House-Matrix-Default.
3. ✅ Reproduzierbarkeit: 10× hintereinander mit gleichen Inputs → identische Allokation (Seed-determinismus).
4. ✅ Constraints: keine Allokation verletzt Risky-Fraction-Cap, RE-Cap, Alts-Cap, Liquidity-Floor, Sum-to-One.
5. ✅ Performance: Optimization für typischen Mandanten (3-5 Goals, 10J Horizon, 2000 Pfade) < 5s.
6. ✅ Konvergenz: in 95% der Test-Fälle status="converged"; bei Divergenz → Fallback auf House-Matrix mit reasoning.
7. ✅ Audit-Anchor: jede Optimization speichert seed/objective/iterations/status in `target_allocations`.
8. ✅ Cornish-Fisher Distribution Output: Skewness und Kurtosis von 100k Samples weichen <5% von Input-Parametern ab.

## Testfälle

### Unit-Tests
- `test_distributions_cornish_fisher.py`: Sample-Statistiken matchen Input-Parameter
- `test_goal_liabilities.py`: Pro Goal-Typ wird korrekter Liability-Pfad erzeugt
- `test_objective.py`: ℒ(w_zero_assets) > ℒ(w_optimal), Penalty bei Constraint-Verletzung
- `test_constraints.py`: All 8 Constraints werden korrekt evaluiert
- `test_solver_slsqp.py`: Konvergiert auf einfachem 2-Goal-Test mit bekanntem Optimum

### Integration-Tests (in pytest, langsam)
- `test_optimizer_e2e.py`: Generate Allocation für 3-Goal-Mandant → Allokation respektiert alle Constraints
- `test_optimizer_vs_house_matrix.py`: Optimizer-Allokation hat ≤ House-Matrix-shortfall in 90% der Test-Mandate

### Performance-Benchmark
- `test_optimizer_perf.py`: 5-Goal-Mandant, 10J horizon, 2000 paths < 5s wall-clock

### Calibration
- `test_distribution_calibration.py`: Cornish-Fisher-Distribution mit SP500-historischen Skew/Kurt liefert realistic 1Y-Drawdowns (>10% in 30% der Pfade)

### Edge Cases
- Mandant ohne Goals → Optimizer fällt zurück auf Vol-Min (Priorität 2)
- Mandant mit nur 1 Hart-Goal das unmöglich ist (target zu hoch) → ℒ stays > 0, status="converged_with_unmet_hard_goal"
- Mandant mit Score=10 (max risky) und Goals die Cash brauchen → Liquidity-Floor binding, reasoning informiert
- Mandant mit gegensätzlichen Goals (1 Hart Vermögensziel = sehr konservativ, 1 Hart Renditeziel = aggressiv) → Solver findet Mischung oder weakest_hard_score zeigt Konflikt

## Risiken

| Risiko | Wahrscheinlichkeit | Mitigation |
|---|---|---|
| Solver konvergiert nicht für gewisse Inputs | mittel | Multi-Start (5 Initials) + Fallback auf House-Matrix + status-Tracking |
| Performance < 5s nicht erreichbar | mittel | NumPy-Vektorisierung erst, dann Optimizer; falls nicht: Reduktion N=2000→1000, oder Async |
| scipy als neue Dependency wird Build-Größe erhöhen | niedrig | scipy ist 60MB, total Build wird ~150MB → noch akzeptabel für Desktop-App |
| Cornish-Fisher Distribution monotonicität verletzt für extreme Skew/Kurt | niedrig | Input-Clamping s∈[-1,1], k∈[0,8] |
| Berater versteht den Optimizer nicht / Schwarz-Box-Problem | hoch | Reasoning-Trace im FE, Constraints-Active anzeigen, Sensitivity-Analyse |
| Optimizer findet "absurde" Allokation (z.B. 100% Gold weil eine Krise dann vermieden wird) | niedrig | Constraints (RE 20%, Alts 10%) verhindern das. Plus Sub-Allocation bleibt fix per Building Block |
| Stochastic-Mode produziert für gleichen Mandanten andere Allokation als zuvor | hoch wenn Seed nicht deterministisch | Determinismus-Test in CI, Seed in Audit-Anchor |
| FINMA-Audit findet Solver "nicht erklärbar" | mittel | Audit-Anchor (seed, iterations, objective_value), reasoning-Trace, Quellen in Code-Kommentaren |

## Performance-Budget

- 5 Goals × 10 Jahre × 2000 Pfade = 100k Wealth-Updates pro Solver-Iteration
- 30 Iterations × 5 Multi-Starts = 150 Solver-Calls = 15M Wealth-Updates
- Mit NumPy-Vektorisierung: 15M × ~50ns = ~0.75s pro Allocation
- Plus Cholesky + Sampling: +1s
- **Total: ~2s pro typischer Mandant**. Akzeptabel.

## Rollout-Plan

### Phase 1 — Foundation (autonom Backend, ~600 Zeilen)
- Spec-Doku ✅ (heute)
- `optimizer/__init__.py` Skeleton
- `optimizer/distributions.py` mit Cornish-Fisher
- `optimizer/goal_liabilities.py` mit allen 7 Goal-Typen
- Calibration-Tests gegen historische Daten
- Feature-Flag `optimizer_mode` in `config.py`
- DB-Migration für Audit-Felder

### Phase 2 — Engine (~700 Zeilen)
- NumPy-Vektorisierung des MC-Loops
- `optimizer/scenario_engine.py` mit Antithetic Variates
- CMA-Schema-Erweiterung Skew/Kurt
- Performance-Benchmark grün

### Phase 3 — Solver-Kern (~1500 Zeilen)
- `optimizer/objective.py`
- `optimizer/constraints.py`
- `optimizer/solver.py` SLSQP + Multi-Start
- `optimizer/audit_trace.py`
- E2E-Test: 3-Goal-Mandant Optimizer-Allokation < House-Matrix-shortfall

### Phase 4 — Integration (~300 Zeilen)
- `_apply_goal_and_reserve_tilts` mit Modus-Branch
- `OPTIMIZER_MODE=stochastic` als opt-in
- Audit-Anchor in `target_allocation`

### Phase 5 — Robustheit & Stress (~600 Zeilen, optional)
- Importance Sampling für Tail
- GA-Fallback wenn SLSQP divergiert
- Stress-Scenarios als zusätzliche Constraints

### Phase 6 — UX (Codex-Spec)
- FE-Optimization-Panel
- Sensitivity-Slider
- Reasoning-Trace anzeigen

## Implementierungs-Checkliste (für Codex bei Phase 4–6)

Wird **erst** geschrieben wenn Phase 1–3 grün sind. Heute leer gelassen.

## Referenz-Implementierung — Pseudo-Code

```python
# 5eyes-backend/services/optimizer/__init__.py
from .distributions import sample_returns
from .goal_liabilities import goal_to_liability_path
from .scenario_engine import build_scenarios
from .objective import shortfall_objective, vol_objective
from .constraints import build_constraint_set
from .solver import solve_slsqp_multistart
from .audit_trace import OptimizerAuditTrace


def optimize_allocation(
    *,
    mandate: Mandate,
    goals: list[Goal],
    cma: CapitalMarketAssumption,
    house_matrix: HouseMatrix,
    advisory_wealth_rappen: int,
    cashflow_series: list[int],
    risk_score_x10: int,
    horizon_years: int = 10,
    n_paths: int = 2000,
) -> tuple[dict[str, int], OptimizerAuditTrace]:
    """Stochastischer Optimizer nach Mulvey/Ziemba-light.

    Returns: (target_weights_bps, audit_trace)
    target_weights_bps: dict mit equities/bonds/real_estate/alternatives/liquidity in bps (sum=10000)
    """
    seed = _deterministic_seed(mandate, cma, goals, risk_score_x10)
    
    # 1. Goal → Liability
    liability_paths = [goal_to_liability_path(g, horizon_years, cma) for g in goals]
    
    # 2. Szenario-Sampling (vektorisiert)
    scenarios = build_scenarios(cma, horizon_years, n_paths, seed)
    # shape: (n_paths, horizon_years, n_assets)
    
    # 3. Constraints
    constraints = build_constraint_set(house_matrix, risk_score_x10, score_bucket)
    
    # 4. Objective
    obj = lambda w: shortfall_objective(w, scenarios, liability_paths, goals,
                                         advisory_wealth_rappen, cashflow_series)
    
    # 5. Multi-Start
    initial_guesses = _build_initial_guesses(house_matrix, score_bucket)
    best_result = solve_slsqp_multistart(obj, constraints, initial_guesses)
    
    # 6. Vol-Min wenn Phase 1 ≤ ε
    if best_result.objective_value < EPSILON:
        vol_obj = lambda w: vol_objective(w, scenarios, advisory_wealth_rappen)
        best_result = solve_slsqp_multistart(vol_obj, constraints, [best_result.x])
        best_result.method_phase = "vol_min"
    
    # 7. Audit-Trace
    trace = OptimizerAuditTrace(
        method="stochastic",
        objective_value_milli=int(best_result.objective_value * 1000),
        iterations=best_result.nit,
        seed=seed,
        status="converged" if best_result.success else "diverged",
        convergence_quality_pct=int(100 * (1 - best_result.optimality_gap)),
        constraints_active=best_result.active_constraints,
        reasoning=_explain(best_result, goals, house_matrix),
    )
    
    target_weights_bps = {key: int(round(w * 10000)) for key, w in zip(BUCKETS, best_result.x)}
    return target_weights_bps, trace
```

## Offene Fragen an Owner

Siehe **OWNER-DECISIONS** OD-1 bis OD-8 oben. Bitte einzeln entscheiden, dann starte ich Phase 1.

### Konkret zu klären vor Coding-Start:

1. **OD-1**: Hardness-Multiplier 50x für Optimizer? (Default: ja)
2. **OD-3**: N=2000 Pfade ausreichend? (Default: ja, mit Antithetic = 4000 effektiv)
3. **OD-5**: Solver-Divergenz → Fallback auf House-Matrix? (Default: ja)
4. **OD-6**: Risky-Fraction-Werte aus 3eyes-Slide 17 1:1 übernehmen? (Default: ja)
5. **OD-7**: Building Block Standard nur (Alternative später)? (Default: ja)
6. **OD-8**: Default-Horizon = max(30, max_goal_horizon)? (Default: ja)

Wenn alle 6 Defaults okay sind: ✅, dann starte ich Phase 1 sofort. Sonst sag was anders sein soll.

## Branch-Befehl (bereits ausgeführt)

```bash
# Bereits geschehen — Branch existiert
git -C C:\5eyes\5eyes_stage9_release_ready_develop_security checkout -b codex/stochastic-optimizer
```

## Backup (bereits eingerichtet)

- Tag: `pre-optimizer-2026-05-05` → `c071cc8`
- Bundle: `C:\5eyes\audit-master-backup-2026-05-05.bundle` (6 MB, complete history)
- Recovery: `git checkout codex/audit-master && git reset --hard pre-optimizer-2026-05-05 && git branch -D codex/stochastic-optimizer`
