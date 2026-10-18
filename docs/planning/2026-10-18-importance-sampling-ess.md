# IMPORTANCE-SAMPLING-ESS-001 – Importance Sampling repariert, Tiebreak auf w'Σw, unerreichbare Ziele

Stand 2026-10-18 · Branch `fix/importance-sampling-ess` (gestapelt auf #626 `feat/objective-normalization` → #625 → #619)
Code: `services/optimizer/importance_sampling.py`, `scenario_engine.py` (`build_scenario_paths_with_weights`), `scenario_cache.py`, `resampling.py` (`build_bag_paths`), `solver.py` (Context-Bau, Audit, Tiebreak, Rundungs-Reparatur, Engine v4), `objective.py` (Tiebreak, Strafausnahme), `goal_reachability.py` (neu), `certification.py` (`wilson_upper_bound`), `drawdown_certification.py`
Tests: `tests/test_importance_sampling_ess.py` (neu), angepasst: `test_objective_normalization.py`, `test_optimizer_objective_constraints.py`, `test_optimizer_objective_dimensionless.py`, Golden-Fixtures
Messskripte: Scratchpad `isfix/` (`analytic.py`, `unbiased.py`, `ess_measure.py`, `tailcov.py`, `measure.py` + `runkappa.sh`, `prodcompare.py`)

## 1. Befund

`compute_likelihood_weights` gewichtete jeden Pfad mit `w = exp(−μᵀ Σ_t x_t + ½ T |μ|²)` bei `μ = −0.5` auf dem Aktienfaktor **in jedem Jahr**. Für die Proposal `q` gilt

    E_q[w²] = exp(Σ_t |μ_t|²) = exp(T |μ|²)   ⇒   ESS/N ≈ 1 / E_q[w²] = exp(−T/4).

Bei T = 31 sind das 4·10⁻⁴. Gleichzeitig war der kumulierte Aktienfaktor `S = Σ_t Z_t / √T` um `0.5 √T` Standardabweichungen verschoben (T = 31: 2.8 σ, T = 41: 3.2 σ) – weit jenseits jeder Zielgrenze: 84–95 % der Pfade lagen unter dem nominalen 5 %-Quantil des Portfolio-Endwerts (Tabelle 3.2).

Gemessen (Produktion, Engine v3, Hauptwürfel 2'000 Pfade): Kish-ESS 13–85, Einzelpfade bis 33 % Gewichtsmasse. IS wird per `decide_is_for_context` automatisch aktiv bei konservativem Profil, Decumulation oder hartem Ziel – bei allen sieben Messmandaten.

## 2. Herleitung und Entscheide

### 2.1 a) Horizont-skalierter Shift

Für einen Shift des kumulierten Faktors `S` um `c` braucht man `Σ_t μ_t = c √T`. Unter dieser Nebenbedingung minimiert (Cauchy-Schwarz) der **konstante** Shift `μ_t = c/√T` die Gewichtsvarianz `Σ_t μ_t² = c²` – sie ist dann horizontunabhängig. Der alte Shift ist der Spezialfall `c = 0.5 √T`, also mit dem Horizont wachsend.

Umgesetzt: `per_year_shift_profile(shift_vector, T) = shift_vector / √T` auf dem gezogenen (gemeinsamen Szenario-)Horizont. Die Gewichte werden auf dem **tatsächlich verwendeten Jahres-Präfix** (Optimierungshorizont H) berechnet – die Likelihood-Ratio der Marginale der ersten H Jahre (korrekt für die gekürzten Pfade, ohne die Varianz der verworfenen Jahre). Pfade bleiben bei gleichem Seed byte-gleich (Common Random Numbers der Horizont-Sensitivität).

### 2.2 b) Defensive Mischung (Hesterberg 1995; Balance-Heuristik Veach/Guibas 1995, Owen/Zhou 2000)

Proposal `m = α p + (1−α) q`, Komponenten deterministisch verteilt (Pfad i geshiftet, wenn `⌊(i+1)(1−α)⌋ > ⌊i(1−α)⌋`, bei α = 0.5 abwechselnd – jedes Präfix enthält dieselbe Mischung). Gewicht für **jeden** Pfad

    w = p / (α p + (1−α) q) = 1 / (α + (1−α) Λ),   Λ = q/p = exp(Σ_t μ_t x_t − ½ Σ_t |μ_t|²),

im Log-Raum stabil berechnet (`logaddexp`). Folgen: `0 < w ≤ 1/α` pfadweise, und aus `Σ w² ≤ (1/α) Σ w` deterministisch `ESS ≥ α Σ w`. Mit festen Komponentenanteilen ist der Balance-Heuristik-Schätzer unverzerrt.

### 2.3 Kalibrierung von c und α (analytisch, `analytic.py`)

Modell: Erfolgsindikator hängt mit Ladung ρ am Aktienfaktor, Fehlschlag-Wahrscheinlichkeit P. Varianzgewinn = `P(1−P) / E_p[w (1_A − P)²]` (selbstnormierter Schätzer), ESS/N = `1 / E_p[w]`, Abdeckung = Anteil Proposal-Pfade im Fehlschlag-Bereich.

| α | c | ESS/N | Gewinn ρ=.6 P=5 % | ρ=.6 P=20 % | ρ=.9 P=5 % | ρ=.9 P=20 % | Abdeckung ρ=.9 P=5 % |
|---|---|---|---|---|---|---|---|
| 0 (rein) | 0.5 | 0.78 | 1.43 | 1.07 | 1.97 | 1.26 | 11.6 % |
| 0 | 1.0 | 0.37 | 1.28 | **0.69** | 2.36 | 0.91 | 22.8 % |
| 0.3 | 1.0 | 0.70 | 1.42 | 0.99 | 2.37 | 1.23 | 17.5 % |
| **0.5** | **1.0** | **0.83** | **1.40** | **1.06** | **2.10** | **1.25** | **13.9 %** |
| 0.5 | 1.5 | 0.72 | 1.31 | 0.95 | 2.34 | 1.16 | 21.7 % |
| alt (T = 31) | 2.78 | 0.0004 | – | – | – | 0.002 | 95 % |

Gewählt **c = 1.0, α = 0.5**: einziger Punkt des Rasters mit ESS/N ≥ 0.8 **und** Gewinn ≥ 1 in allen vier Zellen (minimax gegenüber Standard-MC), Gewichtsschranke 2. α = 0.3 brächte im besten Fall +13 % Gewinn bei ESS 0.70; c ≥ 1.25 verliert bei schwach aktienlastigen Portfolios gegen Standard-MC.

### 2.4 c) Selbstnormierung, ESS-Audit, Rückfall

* Alle Schätzer sind bereits selbstnormiert (`Σ f w / Σ w`: Shortfall, Chance, Volatilität, Drawdown, Publikation) – geprüft, unverändert.
* Neu im Audit (`OptimizerContext.importance_sampling_audit`, `OptimizerResult.importance_sampling`, Reasoning-Zeile): Entscheid + Grund, Schema-Version, c, Shift pro Jahr, α, Gewichtsschranke, Gewichtshorizont, Kish-ESS, ESS/N, größtes Gewicht (Anteil und normiert); im Resampling-Audit `importance_sampling_bags` (ESS/N min/median über die 40 Bags, Anzahl Rückfälle).
* Rückfall: Kish-ESS < 0.30·N ⇒ Standard-MC für diesen Würfel (Haupt- oder Bag-Würfel), Grund `ess_below_threshold` im Audit. Mit α = 0.5 praktisch unerreichbar (ESS ≥ 0.5·Σw), aber die Sicherung gehört zur Methode, nicht zum Parameter.

### 2.5 d) Wilson-Grenze mit n = ESS

War bereits so umgesetzt (`certify_success_indicator`: `n_effective = effective_sample_size(weights)` → `wilson_lower_bound(p, n_eff)`, OPTIMIZER-POST-SELECTION-CERTIFICATION-001), gilt für Chance-Strafe und Publikation gleichermaßen. Neu per Test abgesichert (`test_context_reports_ess_and_wilson_uses_it`). Wirkung: Golden-Mandate mit p = 1.000 hatten wegen n_eff ≈ 10 eine LB von 0.75–0.92 (die allokationsunabhängige Chance-Strafe aus OBJECTIVE-NORMALIZATION-001 §1.4) – jetzt 0.998.

### 2.6 e) Unverzerrtheit (Test `test_is_estimators_are_unbiased_against_lognormal_closed_form`)

Aktien-Bucket exakt lognormal (Schiefe/Kurtosis 0, unkorreliert), 20'000 Pfade, T ∈ {5, 20, 40}: `E[W_T] = 1.065^T` und `P(W_T < K)` für das 5 %- und 20 %-Quantil, Toleranz 4 Standardfehler (Delta-Methode). Explorativ mit 40'000 Pfaden: z-Werte −1.46 … +1.11; ESS/N 0.83 bei allen drei Horizonten; Standardfehler für P = 5 % 0.0007 gegenüber 0.0011 bei Standard-MC (Varianzgewinn 2.4×, Test `test_tail_probability_variance_is_reduced` über 60 Würfel).

## 3. Messung auf den Mandaten

### 3.1 ESS (Produktion; vorher Engine v3, nachher v4)

| Mandat | T | Kish-ESS Hauptwürfel vorher → nachher (von 2'000) | ESS/N Bags (500 Pfade) min / median nachher | größtes Gewicht vorher → nachher |
|---|---|---|---|---|
| Golden Score 3 | 31 | 85 → 1'659 | 0.81 / 0.83 | 22 % → 0.10 % |
| Golden Score 5 | 31 | 16 → 1'644 | 0.81 / 0.83 | 11 % → 0.10 % |
| Golden Score 5 global | 31 | 14 → 1'671 | 0.81 / 0.83 | 13 % → 0.10 % |
| Golden Score 5 CHF/EM | 31 | 17 → 1'663 | 0.81 / 0.83 | 33 % → 0.10 % |
| Golden Score 7 | 31 | 17 → 1'663 | 0.81 / 0.83 | 26 % → 0.10 % |
| Golden Score 9 | 31 | 80 → 1'655 | 0.81 / 0.83 | 24 % → 0.10 % |
| Fundament | 41 | 13 → 1'657 | 0.81 / 0.83 | 30 % → 0.10 % |

(Größtes Gewicht vorher: Messung des Vorgänger-Contexts, OBJECTIVE-NORMALIZATION-001 §1.4. Kein Rückfall auf Standard-MC in irgendeinem Haupt- oder Bag-Würfel.)

### 3.2 Tail-Abdeckung (Anteil Pfade unter dem nominalen 5 %-Quantil des Portfolio-Endfaktors, Bandmitte)

| Mandat | alt (Anteil / gewichtete Schätzung) | neu | nominal |
|---|---|---|---|
| Score 5 | 84.2 % / 5.2 % | 14.6 % / 4.8 % | 5 % |
| Score 7 | 88.0 % / 5.9 % | 15.4 % / 5.1 % | 5 % |
| Score 9 | 87.1 % / 6.2 % | 13.1 % / 4.2 % | 5 % |
| Fundament | 94.5 % / 5.4 % | 16.9 % / 5.7 % | 5 % |
| Score 3 (0 % Aktien an der Bandmitte) | 2.1 % / 4.7 % | 4.3 % / 4.8 % | 5 % |

Alt lag fast jeder Pfad im Tail – die Information steckte in wenigen Pfaden mit riesigem Gewicht. Neu: 3× Abdeckung bei ESS 0.83.

### 3.3 Zielwahrscheinlichkeiten Fundament (Hauptwürfel, Bandmitte; Standardfehler)

| Ziel (τ = 80 %) | alt p (SE) | neu p (SE) | Standard-MC p (SE) |
|---|---|---|---|
| Familienvermögen 2035 | 0.000 (0.000) | 0.025 (0.004) | 0.024 (0.003) |
| Einkommensbrücke Pension | 0.495 (**0.186**) | 0.488 (0.012) | 0.490 (0.011) |

Ehrliche Einordnung: die Ziele dieser Mandate sind **keine Tail-Ereignisse** (Golden: p = 1.000; Fundament: p ≈ 0.02 bzw. ≈ 0.5). Für sie ist das reparierte IS ungefähr neutral (SE 0.012 vs. 0.011); der Gewinn ist, dass es nicht mehr schadet (alt: SE 0.186, ~17× die Varianz von Standard-MC). Der Varianzgewinn zeigt sich bei Fehlschlag-Wahrscheinlichkeiten von 5–20 % (2.3).

## 4. Tiebreak `κ · w'Σw` (CIO-Entscheid 2)

`Var(W_T)/W0²` war mittelwertabhängig (über 31 Jahre wächst die Endvermögens-Streuung mit der erwarteten Rendite) und wurde auf dem IS-Würfel mit ~10 effektiven Pfaden geschätzt. Neu: einjährige Portfolio-Varianz `w'Σw` aus der CMA-Kovarianz des Contexts (`scenario_cov_bps2`, Dezimal²) – exakt, glatt, pfadfrei, dieselbe Größe wie die ausgewiesene erwartete Volatilität. Der Aufrufer, der die Allokation kennt, übergibt sie (`portfolio_variance`): Solver-Closure, `evaluate_weights`, Signifikanztest; ohne Allokation (Konsumenten außerhalb eines Laufs) kein Tiebreak.

Kalibrierung (40 Bags × 7 Mandate, `goal_shortfall`, neue IS-Würfel):

| κ | 0 | 1e-2 | 1e-1 | 3e-1 | **1** | 3 | 10 | 100 |
|---|---|---|---|---|---|---|---|---|
| Bags mit Gewinner = Startpunkt, Score 3 (Defensiv) | 40 | 40 | 40 | 40 | **0** | 0 | 0 | 0 |
| … Score 5 (alle drei Varianten) | 40 | 40 | 0 | 0 | 0 | 0 | 0 | 0 |
| … Score 7 | 40 | 40 | 0 | 0 | 0 | 0 | 0 | 0 |
| … Score 9 | 40 | 40 | 40 | 0 | 0 | 0 | 0 | 0 |
| Fundament: Bag-Mittel Aktien | 67.8 | 67.8 | 67.8 | 67.8 | 67.6 | 67.6 | **66.5** | 60.0 |

**κ = 1**: der kleinste Wert, bei dem kein Mandat mehr in 40/40 Bags am Startpunkt klebt (Defensiv-Mandat: w'Σw ≈ 0.0012, der Unterschied über das Band liegt unter SLSQP-`ftol` = 1e-6, solange κ < 1); eine Dekade unter der ersten messbaren Ziel-Erosion auf dem Konfliktmandat (κ = 10: −1.3 pp Aktien; κ = 1 und 3: −0.2 pp, unter dem Standardfehler des Bag-Mittels von 0.7 pp). Ab κ = 1 sind die Golden-Allokationen identisch zu κ = 100 – das Tiebreak-Minimum innerhalb der Bänder ist erreicht.

## 5. Praktisch unerreichbare Ziele (CIO-Entscheide 3 und Nachtrag 2026-10-18, `goal_reachability.py`)

Definition: Prüfmenge K = Ecken des Bandbreiten-Simplex (höchstens ein Bucket strikt zwischen seinen Grenzen; verletzt eine Ecke weitere harte Nebenbedingungen, euklidisch zulässig projiziert) ∪ Multi-Start-Punkte des Solvers. Bewertung auf dem **nominalen** Validierungswürfel (kein IS, unabhängiger Seed) mit der Erfolgsdefinition der Chance-Strafe. Ein Ziel mit Untergrenze ist **praktisch unerreichbar**, wenn

    max_{w∈K} UB₉₅(p̂(w), N) < UNREACHABLE_TAU_FRACTION · τ,   UNREACHABLE_TAU_FRACTION = 0.5.

Begründung der Schwelle τ/2 (CIO): Ein Ziel, das mehr als die halbe geforderte Sicherheit erreichen kann, bleibt entscheidungsrelevant und steuert weiter (Fundament: Einkommensbrücke, max ≈ 54 % gegen τ = 80 %); nur praktisch aussichtslose Ziele (Familienvermögen 2035, max ≈ 5 %) werden ausgenommen. K ist eine Überdeckung, kein Beweis (ein Maximum kann im Inneren liegen); obere Grenze, halbe Schwelle und Multi-Start-Punkte halten die Regel konservativ. Einmal je Context berechnet (0.02–0.05 s; frühes Ende, sobald jedes Ziel die Schwelle erreicht – `max_probability` eines erreichbaren Ziels ist daher die beste bis dahin geprüfte, nicht zwingend das Maximum).

Wirkung in den **Risikomass-Varianten** (`max_drawdown`, `min_volatility`, `cvar_return`, `max_return`; CIO-Entscheid b): dort steuern nur Ziele, deren Schwelle τ auf mindestens einer zulässigen Allokation erreichbar ist (`max UB₉₅ ≥ τ`). Begründung: Die Variante verspricht ein Risikomass; sie darf nicht für ein ohnehin nicht absicherbares Ziel Risiko aufbauen. Gemessen: Solange die Einkommensbrücke (max ≈ 54 % gegen τ 80 %) in `min_volatility` steuerte, lieferte die Variante 73.7 % Aktien – mehr als Default (64.4 %) und Hausmatrix (67.5 %). Teilweise erreichbare Ziele (über τ/2, unter τ) werden dort mit eigenem Beraterhinweis offengelegt („Ziel 'X' wird in dieser Risikovariante (min_volatility) nicht optimiert, da die geforderte Sicherheit auf keiner zulässigen Allokation erreichbar ist (…). Die Variante baut für ein nicht absicherbares Ziel kein Risiko auf; Ziel mit dem Kunden überprüfen …“). Regressionstest auf dem Fundament (`test_risk_variants_take_no_more_risk_than_the_default_on_the_foundation`): Aktienquote und analytische Vola von `min_volatility` ≤ Default, verfeinerter Drawdown von `max_drawdown` ≤ Default.

Wirkung im **Default** (CIO-Nachtrag 4): ein praktisch unerreichbares Ziel steuert weder die Chance-Strafe noch (Default `goal_shortfall`) den Primärterm L(w) – sein Fehlbetrag bleibt auf jeder zulässigen Allokation, als Zielterm würde es nur in mehr Risiko treiben („Hoffen auf ein Wunder“, gegen den Kapitalschutz). Es wird weiter simuliert und publiziert. Offenlegung: `OptimizerResult.goal_reachability`, je Ziel ein Beraterhinweis im Reasoning („Beraterhinweis: Ziel 'X' ist mit keiner zulässigen Allokation mit ausreichender Sicherheit erreichbar (max. Y %, …). Ziel mit dem Kunden überprüfen (Betrag, Termin, Priorität). …“) und `feasible_set_reachable` auf den publizierten Zeilen der geprüften Ziele (auch im House-Matrix-Fallback der Produktionsgrenze). Bags, Signifikanztest und Drawdown-Rerank erben die Ausnahme über den Context (eine Zielfunktion).

Ergebnis: Golden-Mandate – alle Ziele erreichbar, auch an τ (sie steuern in jedem Modus). Fundament – Default: „Familienvermögen 2035“ (max 5.2 %, UB < 40 %) ausgenommen, „Einkommensbrücke Pension“ (≈ 49–54 %) und „Eigenmittel Ferienhaus“ steuern; Risikomass-Varianten: Familienvermögen und Einkommensbrücke ausgenommen, nur das Ferienhaus steuert.

## 6. Nebenbefund: bps-Rundung auf aktiver Nebenbedingung (BPS-ROUNDING-ON-ACTIVE-CONSTRAINT-001)

Mit dem wirksamen Varianz-Tiebreak landen ziel-sichere Mandate auf Bandecken und Flächen linearer Nebenbedingungen. Referenzmandat M1 (`test_engine_reference_mandates.py`): alle 40 Bags auf demselben Punkt einer Ungleichung mit nicht-ganzzahligem bps-Rand; die bps-Rundung verletzte sie um 5·10⁻⁶ → Status `diverged_infeasible`. Fix: `_repair_rounded_bps` verschiebt greedy je 1 bps zwischen zwei Buckets (Bänder eingehalten, Summe 10'000) bis zulässig; angewandt auf den Resampling-Kandidaten, den Drawdown-zertifizierten Kandidaten, `_bps_dict_for_feasible_point` und die Final-Rundung. M1 jetzt `converged` (Obl. 6857 → 6858, Immo 373 → 372 bps).

## 7. Konsistenz

Eine Zielfunktion für alle Pfade: `_objective_from_array` (Bags/Einzelwürfel), `evaluate_weights`, Signifikanztest (`_context_loss_components_on_validation`, bis Engine v4 `_context_loss_pair_on_validation`) und Drawdown-Rerank (`validated_drawdown_evaluation`) übergeben dieselbe Tiebreak-Varianz und dieselbe Strafausnahme aus dem Context; Bag-Würfel ziehen mit derselben Proposal und denselben Gewichtsregeln wie der Hauptwürfel. Tests: `test_house_matrix_significance_compares_the_goal_level_not_the_tiebreak` (bis Engine v4 `..._compares_the_scalar_the_solver_minimizes`; seit Abschnitt 12 Zielebene ohne Tiebreak), `test_unreachable_goal_does_not_steer_risk_measure_variants` (Hauptwürfel, Bag, `evaluate_weights` = Closure, Validierung, Drawdown-Rerank).

## 8. Wirkung in Produktion (40 Bags + Signifikanztest; vorher = #626 Engine v3, nachher Engine v4)

Werte in % (Aktien/Obl./Immo/Alt./Liq.), erw. Rendite/Vola in bps, Entscheid in Klammern. Zielwahrscheinlichkeiten (Validierungswürfel) der Golden-Mandate in allen Modi vorher und nachher 100 % (Pension, Eigenheim, Plan-Solvenz).

| Mandat | Modus | vorher | nachher | Rendite/Vola | Bag-σ max (bps) |
|---|---|---|---|---|---|
| Score 3 | goal_shortfall | 0.0/88.2/0.0/6.8/5.0 (opt.) | 0.0/87.0/0.0/8.0/5.0 (opt.) | 206/342 → 205/341 | 255 → 0 |
| Score 5 | goal_shortfall | 40.0/44.5/5.7/6.8/3.0 (opt.) | 40.0/45.0/5.0/7.0/3.0 (opt.) | 398/647 → 396/645 | 176 → 0 |
| Score 5 global | goal_shortfall | 40.0/44.5/6.2/6.4/3.0 (opt.) | 40.0/45.0/5.0/7.0/3.0 (opt.) | 410/671 → 407/668 | 201 → 0 |
| Score 5 CHF/EM | goal_shortfall | 40.0/43.8/6.0/7.2/3.0 (opt.) | 40.0/45.0/5.0/7.0/3.0 (opt.) | 410/686 → 408/682 | 283 → 0 |
| Score 7 | goal_shortfall | 60.0/23.1/6.8/8.1/2.0 (opt.) | 60.0/25.0/5.4/7.6/2.0 (opt.) | 489/959 → 486/951 | 372 → 0 |
| Score 9 | goal_shortfall | 75.0/13.9/3.9/5.2/2.0 (opt.) | 75.0/15.0/3.0/5.0/2.0 (opt.) | 551/1174 → 550/1169 | 257 → 0 |
| Fundament | goal_shortfall | 66.0/11.0/17.5/3.0/2.5 (opt.) | 64.4/10.1/20.0/3.0/2.5 (opt., p = 0.0025) | 543/1081 → 542/1067 | 474 → **16** |
| Fundament | max_drawdown | 67.5/17.0/7.0/6.0/2.5 (**Hausmatrix**) | 60.0/25.0/9.5/3.0/2.5 (**opt.**, p = 0.0025) | 524/1070 → 499/952 | 193 → 0 |
| Fundament | min_volatility | 67.5/17.0/7.0/6.0/2.5 (**Hausmatrix**) | 60.0/25.0/5.1/7.4/2.5 (**opt.**, p = 0.0025) | 524/1070 → 485/950 | 470 → 23 |
| Golden (alle) | max_drawdown / min_volatility | Änderungen ≤ 1.7 pp je Bucket, Aktien unverändert | | | ≤ 54 |

Fundament, Zielwahrscheinlichkeiten (Validierungswürfel) vorher → nachher:

| Ziel | goal_shortfall | max_drawdown | min_volatility |
|---|---|---|---|
| Eigenmittel Ferienhaus 2028 (τ 80 %, erreichbar) | 100 → 100 % | 100 → 100 % | 100 → 100 % |
| Familienvermögen 2035 (τ 80 %, praktisch unerreichbar; überall ausgenommen) | 5.9 → 6.7 % | 5.3 → 4.0 % | 5.3 → 3.5 % |
| Einkommensbrücke Pension (τ 80 %, über τ/2 und unter τ; steuert nur im Default) | 52.5 → 51.6 % | 49.5 → 48.4 % | 49.5 → 46.1 % |
| Mindestrendite Advisory (keine Untergrenze) | 59.6 → 59.0 % | 55.3 → 51.2 % | 55.3 → 48.2 % |
| Plan-Solvenz (alle Ziele gemeinsam) | 3.2 → 3.2 % | 2.6 → 1.5 % | 2.6 → 1.4 % |

Lesart: Auf den Golden-Mandaten verschwindet die Bag-Streuung (2–4 pp → 0): alle 40 Bags finden dieselbe Bandecke, weil der Tiebreak pfadfrei ist und die Chance-Strafe nicht mehr am ESS-Artefakt hängt (Golden-Allokationen durch den Nachtrag unverändert, alle Ziele erreichbar).

Fundament (nach CIO-Nachtrag, Schwelle τ/2, auch im Default):
* **Default:** Ohne das aussichtslose Familienvermögen-Ziel im Primärterm verschwindet das flache Plateau: Bag-σ 474 bps (v3) → 634 bps (v4 vor Nachtrag) → **16 bps**. Allokation 64.4/10.1/20.0/3.0/2.5, Vola 10.81 → 10.67 %, Zielwahrscheinlichkeiten praktisch unverändert (Familienvermögen 6.7 %, Einkommensbrücke 51.6 %, Ferienhaus 100 %).
* **max_drawdown:** 60.0 % Aktien (Bandunterkante) statt Hausmatrix 67.5 %; Vola 9.52 %, Bag-σ 0.
* **min_volatility:** 60.0 % Aktien, Vola 9.50 % (Default 10.67 %), Bag-σ 23 bps.
* Verlauf `min_volatility` über die Entscheide: Hausmatrix 67.5 % (v3) → 60.0 % (v4, Ausnahme nur unerreichbarer Ziele) → 73.7 % (τ/2 in jedem Modus, Einkommensbrücke steuerte wieder) → **60.0 %** (Entscheid b). Bezahlt wird mit 1–3 pp Wahrscheinlichkeit der zwei nicht absicherbaren Ziele (Familienvermögen 3.5–4.0 %, Einkommensbrücke 46–48 %); beide werden mit Beraterhinweis offengelegt.

## 9. Golden-Fixtures

Alle sechs neu eingefroren (Engine `saa_resampled_v4`), erzeugt mit `OMP/OPENBLAS/MKL_NUM_THREADS=1` unter `OPENBLAS_CORETYPE=Haswell` **und** `=Nehalem`: alle sechs Dateien byte-identisch (vorher 5 von 6). Zahlen im Docstring von `tests/test_golden_snapshot_ch_regression.py` und Tabelle 8.

## 10. Tests und Budgets

* Neu `tests/test_importance_sampling_ess.py` (28 Tests): Unverzerrtheit gegen Lognormal (T = 5/20/40), ESS/N ≥ 0.75 für T = 5…40, Kollaps des alten Shifts (ESS/N < 0.05), Gewichte ≤ 1/α und ESS ≥ α Σw, Mischungs-Präfixe, Tail-Abdeckung 15.5 %, Varianzreduktion, Gewichte der Marginale + CRN, ESS im Audit und in der Wilson-Grenze, ESS-Rückfall, Erreichbarkeits-Screen (Ausnahme in jedem Modus inkl. Primärterm, Schwelle τ/2 mit 54 %/5 %-Fall, Beraterhinweis, eine Zielfunktion über Bag/Evaluate/Validierung/Rerank), Strafausnahme, Publikation, Rundungs-Reparatur.
* SIGNIFICANCE-SCALAR-ONLY-001: die Zwei-Stufen-Logik in `resampling.py` (`lexicographic_improvement`, Stufen-Schalter in `_objective_scalar`) ist entfernt. Tupel-Verluste werden wie im Solver summiert (`scalar_loss`), ungültige Formen abgelehnt; Tests in `test_saa_resampled_stability.py` umgestellt (Tupel- = Skalar-Bootstrap, Golden-Fall entscheidet auf jedem Würfel gleich, Ablehnung ungültiger Formen).
* Angepasst: Tiebreak-Tests in `test_objective_normalization.py` (Monotonie-Property, Stetigkeit, Reproducer, Signifikanz-Skalar; neu: Tiebreak = κ w'Σw und mittelwertunabhängig), `test_optimizer_objective_constraints.py`, `test_optimizer_objective_dimensionless.py`.
* Performance-Budget: `generate_target_allocation` 4.6 s (Budget 24 s). `services/portfolio_engine.py` unverändert 6'979 Zeilen (≤ 7'100).

## 11. Owner-Entscheide (CIO, 2026-10-18) und verbleibende Frage

1. **Wilson mit Kish-ESS bleibt.** Die Grenze rechnet mit n ≈ 0.83 N, obwohl der IS-Schätzer für Fehlschlag-Wahrscheinlichkeiten von 5–20 % 1.1–2.4× genauer ist. Bewusst konservativ: eine indikatorspezifische effektive Stichprobe `p(1−p)/Var̂(p̂)` wäre bei wenigen Fehlschlag-Pfaden selbst instabil (p̂ = 1 ⇒ Varianzschätzung 0 ⇒ n = ∞), und eine Zertifizierung darf nicht an einer instabilen Gutschrift hängen. Kosten: die Grenze liegt bei p = 1 bei 0.9984 statt 0.9986.
2. **Auto-IS bleibt.** Mit ESS/N = 0.83, Gewichten ≤ 2 und Varianzgewinn ≥ 1 im ganzen Kalibrierungsraster ist es auch dort unschädlich, wo die Ziele keine Tail-Ereignisse sind, und hilft, wo sie es sind (5–20 % Fehlschlag: 1.1–2.4×).
3. **Schwelle „praktisch unerreichbar“ = max UB₉₅ < τ/2** (`UNREACHABLE_TAU_FRACTION`), Abschnitt 5.
4. **Auch im Default steuern praktisch unerreichbare Ziele weder Strafe noch Primärterm**; Beraterhinweis im Ergebnis. Fundament Default: Bag-σ 634 → 16 bps (Abschnitt 8).

5. **Risikomass-Varianten steuern nur auf an τ erreichbare Ziele** (Entscheid b). Fundament `min_volatility` 73.7 → 60.0 % Aktien; per Regressionstest abgesichert (Varianten ≤ Default in Aktienquote, Vola, verfeinertem Drawdown).

Keine offenen Fragen aus diesem Auftrag.

## 12. HOUSE-FIRST-SIGNIFICANCE-001 – Hausmatrix, solange die Ziele mit ihr gleich sicher erreicht sind (CIO-Entscheid 2026-10-18, Engine v5)

### 12.1 Befund

Auf allen sechs CH-Golden-Mandaten erreichen Hausmatrix und Optimierer alle Ziele mit p = 1 (Validierungswürfel). Die Zielebene (Ziel-Fehlbetrag + Chance-Strafe) ist für beide exakt 0; übrig bleibt der Tiebreak `κ·wᵀΣw`. Der ist **pfadfrei**: die Differenz Anker − Kandidat hat in jeder Bootstrap-Replikation dasselbe Vorzeichen, der Test meldet unabhängig von der Grösse der Differenz p = 1/(B+1) = 0.0025. Ergebnis: der Optimierer gewann immer, mit Eckenlösungen (Alternative = Gold auf Bandmaximum, Immobilien und Aktien auf Bandminimum), getragen von Schätzfehlern der Korrelationsmatrix. Gegenüber der Hausmeinung (IC) war das eine Abweichung ohne Bezug zu den Zielen des Kunden.

### 12.2 Herleitung

* **Was der Test entscheiden soll.** Die Hausmatrix ist die IC-Meinung und gilt, bis der Optimierer etwas *für den Kunden* besser macht. Im Default ist das die Zielerreichung (Fehlbetrag + Chance-Strafe). Eine Varianzdifferenz bei sicher erreichten Zielen ist kein Kundennutzen, sondern eine Aussage über die Schätzung von Σ.
* **Warum der Tiebreak im Solver bleibt.** Ohne ihn ist die Zielfunktion auf Mandaten mit sicheren Zielen flach; SLSQP bliebe am Startpunkt stehen und die Bag-Streuung käme zurück (OBJECTIVE-NORMALIZATION-001). Er ordnet die Kandidaten weiter, entscheidet aber nicht mehr über Anker vs. Kandidat.
* **Ein deterministischer Term hat im gepaarten Bootstrap keine Stichprobenverteilung.** Jeder pfadfreie Term (Tiebreak, Soft-Preference) wird entweder immer oder nie „signifikant“. Die Soft-Preference bleibt trotzdem auf der Zielebene: sie ist eine explizite Berater-Vorgabe (Target Intent, CERT-ALLOCATION-INTENT-001), keine Schätzgrösse. Ein Lauf mit Target Intent soll diese Vorgabe nicht durch die Hausmatrix verlieren.
* **Risikomass-Varianten.** Dort ist das Risikomass der Zweck des Laufs. Entschieden wird deshalb zusätzlich auf dem Skalar (Risikomass + Chance-Strafe + Preference), aber nur mit **Materialitätsschwelle 50 bps** auf dem Risikomass selbst (`RISK_MEASURE_MATERIALITY = 0.005`, alle Varianten sind Renditeanteile). Begründung:
  * Ein Vola-Schätzer aus 20 Jahren Monatsdaten hat eine relative Standardabweichung von etwa 1/√(2·240) = 4.6 %. Bei 8–12 % Portfolio-Vola sind das 35–55 bps. Kleinere Unterschiede lassen sich von den CMA-Schätzfehlern nicht trennen.
  * Für den Drawdown (etwa 2–3× Vola) und die erwartete Rendite (Standardfehler mehrere Prozentpunkte) ist dieselbe Schwelle relativ noch nachsichtiger.
  * Die SAA wird in ganzen Prozent kommuniziert.
  * Die verworfenen Eckenlösungen brachten 2–7 bps Vola, also eine bis zwei Grössenordnungen weniger.
* **Ziele vor Risiko, auch in den Varianten.** Ist der Kandidat auf der Zielebene signifikant besser, gilt er ohne Materialitätsprüfung (die Ziele sind die Untergrenze jeder Variante, Modul-Docstring `objective_variants.py`, Entwurfsentscheidung 1).

### 12.3 Regel (`solver._significance_vs_house_anchor`, Test `paired_bootstrap_one_sided_goal_level_v4`)

1. Zielebene (alle Modi): gepaarter einseitiger Bootstrap (B = 400, α = 5 %) auf `Fehlbetrag + Chance-Strafe + Soft-Preference`. Ist das Ergebnis signifikant, gilt `optimizer` (`significant_goal_improvement`).
2. Default: sonst `house_matrix` (`goal_improvement_not_significant`), der bestehende House-Fallback-Pfad mit `publish_goal_achievability`.
3. Varianten: sonst Skalar-Bootstrap; signifikant **und** Risikomass-Verbesserung ≥ 50 bps ergibt `optimizer` (`significant_material_risk_improvement`), sonst `house_matrix` (`risk_improvement_not_material` / `risk_improvement_not_significant`). Die Statistik steht im Audit unter `significance.risk_measure_test` (Risikomass Anker/Kandidat, Verbesserung, Schwelle, p) und in der Modellbasis.
4. Drawdown-Rerank (#625): unverändert. Er wählt unter {projiziertes Mittel, rohes Mittel, Anker} den besten Nicht-Anker-Kandidaten auf dem verfeinerten Drawdown. Signifikanztest und Materialität messen mit demselben verfeinerten Mass (`refined_primary_per_path`, gleicher Brücken-Seed).
5. Unerreichbare Ziele (#631): unverändert. Die Strafausnahme gilt auf der Zielebene genauso wie in Bags und Rerank (`penalty_exempt_goal_ids`), es gibt also eine Zielfunktion für alle Pfade.

### 12.4 Wirkung in Produktion (vorher = Engine v4, nachher = Engine v5)

40 Bags, Signifikanztest, Fundament-Beispielmandat und die sechs CH-Golden-Mandate, `OPENBLAS_CORETYPE=Haswell`, Threads = 1. Allokation in % (Aktien/Obl./Immo/Alt./Liq.), erw. Rendite/Vola in %. p = Zielebene; ΔRisiko = Verbesserung des Risikomasses Anker → Kandidat auf dem Validierungswürfel. Zielwahrscheinlichkeiten: publizierte Zeilen (Golden: Pension · Eigenheim · Plan-Solvenz; Fundament: Ferienhaus · Familienvermögen · Einkommensbrücke · Mindestrendite · Plan-Solvenz).

**goal_shortfall**

| Mandat | Hausmatrix (Anker) | vorher A/O/I/Alt/L | vorher Rend./Vola | vorher Entscheid | nachher A/O/I/Alt/L | nachher Rend./Vola | nachher Entscheid | Zielwahrsch. nachher (%) |
|---|---|---|---|---|---|---|---|---|
| Score 3 | 0/95/0/3/2 | 0/87/0/8/5 | 2.05/3.41 | Opt, p=0.0025 | 0/95/0/3/2 | 2.14/3.62 | Haus, p=1.0000 | 100 · 100 · 100 |
| Score 5 | 48/35/10/5/2 | 40/45/5/7/3 | 3.96/6.45 | Opt, p=0.0025 | 48/35/10/5/2 | 4.46/7.76 | Haus, p=1.0000 | 100 · 100 · 100 |
| Score 7 | 68/16/8/6/2 | 60/25/5.4/7.6/2 | 4.86/9.51 | Opt, p=0.0025 | 68/16/8/6/2 | 5.29/10.81 | Haus, p=1.0000 | 100 · 100 · 100 |
| Score 9 | 79/8/7/4/2 | 75/15/3/5/2 | 5.50/11.69 | Opt, p=0.0025 | 79/8/7/4/2 | 5.77/12.45 | Haus, p=0.3441 | 100 · 99.95 · 99.95 |
| Score 5 global | 48/35/10/5/2 | 40/45/5/7/3 | 4.07/6.68 | Opt, p=0.0025 | 48/35/10/5/2 | 4.59/8.04 | Haus, p=1.0000 | 100 · 100 · 100 |
| Score 5 CHF/EM | 48/35/10/5/2 | 40/45/5/7/3 | 4.08/6.82 | Opt, p=0.0025 | 48/35/10/5/2 | 4.60/8.21 | Haus, p=1.0000 | 100 · 100 · 100 |
| Fundament | 67.5/17/7/6/2.5 | 64.4/10.1/20/3/2.5 | 5.42/10.67 | Opt, p=0.0025 | 64.4/10.1/20/3/2.5 | 5.42/10.67 | Opt, p=0.0025 | 100 · 6.6 · 53.1 · 60.2 · 2.85 |

**max_drawdown**

| Mandat | Hausmatrix (Anker) | vorher A/O/I/Alt/L | vorher Rend./Vola | vorher Entscheid | nachher A/O/I/Alt/L | nachher Rend./Vola | nachher Entscheid | Zielwahrsch. nachher (%) |
|---|---|---|---|---|---|---|---|---|
| Score 3 | 0/95/0/3/2 | 0/87.2/0/7.8/5 | 2.05/3.41 | Opt, p=0.0025 | 0/87.2/0/7.8/5 | 2.05/3.41 | Opt, p=1.0000; ΔRisiko 67 bps (p=0.0025) | 100 · 100 · 100 |
| Score 5 | 48/35/10/5/2 | 40/45/9/3/3 | 4.09/6.48 | Opt, p=0.0025 | 40/45/9/3/3 | 4.09/6.48 | Opt, p=1.0000; ΔRisiko 380 bps (p=0.0025) | 100 · 100 · 100 |
| Score 7 | 68/16/8/6/2 | 60/25/10/3/2 | 5.01/9.53 | Opt, p=0.0025 | 60/25/10/3/2 | 5.01/9.53 | Opt, p=1.0000; ΔRisiko 392 bps (p=0.0025) | 100 · 100 · 100 |
| Score 9 | 79/8/7/4/2 | 75/15/6/2/2 | 5.59/11.71 | Opt, p=0.0025 | 75/15/6/2/2 | 5.59/11.71 | Opt, p=1.0000; ΔRisiko 217 bps (p=0.0025) | 100 · 100 · 100 |
| Score 5 global | 48/35/10/5/2 | 40/45/9/3/3 | 4.20/6.71 | Opt, p=0.0025 | 40/45/9/3/3 | 4.20/6.71 | Opt, p=1.0000; ΔRisiko 397 bps (p=0.0025) | 100 · 100 · 100 |
| Score 5 CHF/EM | 48/35/10/5/2 | 40/45/9/3/3 | 4.21/6.84 | Opt, p=0.0025 | 40/45/9/3/3 | 4.21/6.84 | Opt, p=1.0000; ΔRisiko 402 bps (p=0.0025) | 100 · 100 · 100 |
| Fundament | 67.5/17/7/6/2.5 | 60/25/9.5/3/2.5 | 4.99/9.52 | Opt, p=0.0025 | 60/25/9.5/3/2.5 | 4.99/9.52 | Opt, p=1.0000; ΔRisiko 388 bps (p=0.0025) | 100 · 3.2 · 47.5 · 51.6 · 1 |

**min_volatility**

| Mandat | Hausmatrix (Anker) | vorher A/O/I/Alt/L | vorher Rend./Vola | vorher Entscheid | nachher A/O/I/Alt/L | nachher Rend./Vola | nachher Entscheid | Zielwahrsch. nachher (%) |
|---|---|---|---|---|---|---|---|---|
| Score 3 | 0/95/0/3/2 | 0/87/0/8/5 | 2.05/3.41 | Opt, p=0.0025 | 0/95/0/3/2 | 2.14/3.62 | Haus, p=1.0000; ΔRisiko 21 bps (p=0.0025) | 100 · 100 · 100 |
| Score 5 | 48/35/10/5/2 | 40/45/5.1/6.9/3 | 3.97/6.45 | Opt, p=0.0025 | 40/45/5.3/6.7/3 | 3.97/6.46 | Opt, p=1.0000; ΔRisiko 131 bps (p=0.0025) | 100 · 100 · 100 |
| Score 7 | 68/16/8/6/2 | 60/25/5.6/7.4/2 | 4.87/9.51 | Opt, p=0.0025 | 60/25/5.5/7.5/2 | 4.86/9.51 | Opt, p=1.0000; ΔRisiko 130 bps (p=0.0025) | 100 · 100 · 100 |
| Score 9 | 79/8/7/4/2 | 75/15/3/5/2 | 5.50/11.69 | Opt, p=0.0025 | 75/15/3/5/2 | 5.50/11.69 | Opt, p=1.0000; ΔRisiko 76 bps (p=0.0025) | 100 · 100 · 100 |
| Score 5 global | 48/35/10/5/2 | 40/45/5.2/6.8/3 | 4.08/6.68 | Opt, p=0.0025 | 40/45/5.2/6.8/3 | 4.08/6.68 | Opt, p=1.0000; ΔRisiko 136 bps (p=0.0025) | 100 · 100 · 100 |
| Score 5 CHF/EM | 48/35/10/5/2 | 40/45/5.2/6.8/3 | 4.08/6.82 | Opt, p=0.0025 | 40/45/5.1/6.9/3 | 4.08/6.82 | Opt, p=1.0000; ΔRisiko 137 bps (p=0.0025) | 100 · 100 · 100 |
| Fundament | 67.5/17/7/6/2.5 | 60/25/5.1/7.4/2.5 | 4.85/9.50 | Opt, p=0.0025 | 60/25/5.1/7.3/2.5 | 4.85/9.50 | Opt, p=1.0000; ΔRisiko 119 bps (p=0.0025) | 100 · 2.95 · 45.65 · 47.45 · 0.9 |

**cvar_return**

| Mandat | Hausmatrix (Anker) | vorher A/O/I/Alt/L | vorher Rend./Vola | vorher Entscheid | nachher A/O/I/Alt/L | nachher Rend./Vola | nachher Entscheid | Zielwahrsch. nachher (%) |
|---|---|---|---|---|---|---|---|---|
| Score 3 | 0/95/0/3/2 | 0/95/0/3/2 | 2.14/3.62 | Haus, p=0.0748 | 0/95/0/3/2 | 2.14/3.62 | Haus, p=1.0000; ΔRisiko 0 bps (p=0.1347) | 100 · 100 · 100 |
| Score 5 | 48/35/10/5/2 | 40/35.8/19.2/3/2 | 4.33/6.92 | Opt, p=0.0025 | 48/35/10/5/2 | 4.46/7.76 | Haus, p=1.0000; ΔRisiko 20 bps (p=0.0025) | 100 · 100 · 100 |
| Score 7 | 68/16/8/6/2 | 60/16.4/18.6/3/2 | 5.20/9.91 | Opt, p=0.0025 | 68/16/8/6/2 | 5.29/10.81 | Haus, p=1.0000; ΔRisiko 29 bps (p=0.0025) | 100 · 100 · 100 |
| Score 9 | 79/8/7/4/2 | 75/5.8/15.2/2/2 | 5.80/12.09 | Opt, p=0.0025 | 79/8/7/4/2 | 5.77/12.45 | Haus, p=1.0000; ΔRisiko 17 bps (p=0.0025) | 100 · 99.95 · 99.95 |
| Score 5 global | 48/35/10/5/2 | 40/35.2/19.8/3/2 | 4.45/7.18 | Opt, p=0.0025 | 48/35/10/5/2 | 4.59/8.04 | Haus, p=1.0000; ΔRisiko 22 bps (p=0.0025) | 100 · 100 · 100 |
| Score 5 CHF/EM | 48/35/10/5/2 | 40/35.4/19.6/3/2 | 4.46/7.30 | Opt, p=0.0025 | 48/35/10/5/2 | 4.60/8.21 | Haus, p=1.0000; ΔRisiko 23 bps (p=0.0025) | 100 · 100 · 100 |
| Fundament | 67.5/17/7/6/2.5 | 60/14.6/19.9/3/2.5 | 5.22/9.98 | Opt, p=0.0025 | 67.5/17/7/6/2.5 | 5.24/10.70 | Haus, p=1.0000; ΔRisiko 26 bps (p=0.0025) | 100 · 5.65 · 49.65 · 55.9 · 2.25 |

**max_return**

| Mandat | Hausmatrix (Anker) | vorher A/O/I/Alt/L | vorher Rend./Vola | vorher Entscheid | nachher A/O/I/Alt/L | nachher Rend./Vola | nachher Entscheid | Zielwahrsch. nachher (%) |
|---|---|---|---|---|---|---|---|---|
| Score 3 | 0/95/0/3/2 | 0/97/0/1/2 | 2.16/3.69 | Opt, p=0.0025 | 0/95/0/3/2 | 2.14/3.62 | Haus, p=1.0000; ΔRisiko 2 bps (p=0.0025) | 100 · 100 · 100 |
| Score 5 | 48/35/10/5/2 | 55/25/15/3/2 | 4.90/8.97 | Opt, p=0.0025 | 48/35/10/5/2 | 4.46/7.76 | Haus, p=1.0000; ΔRisiko 35 bps (p=0.0025) | 100 · 100 · 100 |
| Score 7 | 68/16/8/6/2 | 75/10/10/3/2 | 5.67/11.90 | Opt, p=0.0025 | 68/16/8/6/2 | 5.29/10.81 | Haus, p=1.0000; ΔRisiko 27 bps (p=0.0025) | 100 · 100 · 100 |
| Score 9 | 79/8/7/4/2 | 85/5/6/2/2 | 6.03/13.31 | Opt, p=0.0025 | 79/8/7/4/2 | 5.77/12.45 | Haus, p=1.0000; ΔRisiko 17 bps (p=0.0025) | 100 · 99.95 · 99.95 |
| Score 5 global | 48/35/10/5/2 | 54.5/25.4/15.1/3/2 | 5.03/9.22 | Opt, p=0.0025 | 48/35/10/5/2 | 4.59/8.04 | Haus, p=1.0000; ΔRisiko 35 bps (p=0.0025) | 100 · 100 · 100 |
| Score 5 CHF/EM | 48/35/10/5/2 | 50.6/26.1/18.3/3/2 | 4.93/8.92 | Opt, p=0.0025 | 48/35/10/5/2 | 4.60/8.21 | Haus, p=1.0000; ΔRisiko 27 bps (p=0.0025) | 100 · 100 · 100 |
| Fundament | 67.5/17/7/6/2.5 | 75/10/9.5/3/2.5 | 5.65/11.89 | Opt, p=0.0025 | 67.5/17/7/6/2.5 | 5.24/10.70 | Haus, p=1.0000; ΔRisiko 30 bps (p=0.0025) | 100 · 5.65 · 49.65 · 55.9 · 2.25 |

Lesart:

* **Default:** Alle sechs Golden-Mandate publizieren jetzt die Hausmatrix (Zielebene identisch, p = 1; Score 9 p = 0.34, weil ein einzelner Validierungspfad der Hausmatrix die Plan-Solvenz verfehlt: 99.95 %). Das korrigiert nicht nur die Immo/Alt-Ecken aus dem Befund. Der Tiebreak hatte auch die **Aktienquote** an die Bandunterkante gedrückt (Score 5: 40 statt 48 %, Score 7: 60 statt 68 %, Score 9: 75 statt 79 %, Score 3: Obligationen 87 statt 95 %). Die publizierte Strategie wird dadurch spürbar riskanter und renditestärker: Score 5 Vola 6.45 → 7.76 %, erw. Rendite 3.96 → 4.46 %; Score 7 9.51 → 10.81 % / 4.86 → 5.29 %. Das ist die Hausmeinung. Die Zielwahrscheinlichkeiten bleiben bei 100 %.
* **Fundament (Default):** unverändert Optimierer. Ziele werden nicht sicher erreicht, der Kandidat ist auf der Zielebene signifikant besser (p = 0.0025, Verbesserung 0.149).
* **max_drawdown / min_volatility:** Optimierer mit materiellen Verbesserungen (Drawdown 67–402 bps, Vola 76–137 bps). Ausnahme: min_volatility Score 3 (21 bps Vola) publiziert jetzt die Hausmatrix. Die Varianten bleiben nicht riskanter als der Default (Regressionstest grün).
* **cvar_return / max_return:** auf allen sieben Mandaten Hausmatrix. Die Verbesserungen des Expected Shortfall (0–29 bps) bzw. der erwarteten Rendite (2–35 bps auf dem Validierungswürfel) liegen unter der Schwelle. Vorher lieferten diese Modi 15–20 % Immobilien (cvar) bzw. bis 85 % Aktien (max_return).

### 12.5 Bekannte Grenzen / Hinweise für den CIO

1. **Materialität gilt für den Kandidaten als Ganzes.** Ist der Kandidat einer Variante material besser (z. B. min_volatility Score 5: 131 bps, getragen von 8 pp weniger Aktien), werden kleine Ecken im selben Kandidaten mitgenommen (Alt 6.7 % statt 5 %). Eine Zerlegung je Abweichung wäre ein eigener Entscheid.
2. **Fundament cvar_return / max_return vs. Default:** Die Varianten publizieren die Hausmatrix (67.5 % Aktien, Vola 10.70 %), der Default den Optimierer (64.4 %, Vola 10.67 %). Grund ist #631 Entscheid b: Varianten steuern nur auf an τ erreichbare Ziele. Damit fehlt ihnen die Zielverbesserung, die im Default den Optimierer trägt. Die Regressionstests decken min_volatility/max_drawdown ab und sind grün.
3. Die Golden-Mandate werden durch die Hausmatrix-Rückkehr spürbar riskanter (Vola +0.2 bis +1.4 pp). Das folgt aus der Regel. Ist das nicht gewollt, liegt die Frage bei der Hausmatrix (IC), nicht beim Optimierer.

### 12.6 Tests

* Neu `tests/test_house_first_significance.py`:
  * Entscheidungslogik mit synthetischer Ziel-/Risikoebene. Reproducer: Ziele erfüllt und kleinere Varianz ergibt Hausmatrix. Nicht erreichte Ziele mit signifikant besserem Kandidaten ergeben den Optimierer, auch bei höherer Vola. Ein-Pfad-Rauschen ist nicht signifikant. Je Variante: 5 bps ergibt Hausmatrix, 100 bps den Optimierer; Grenzfall genau 50 bps; materiell weniger Risiko gegen Zielverlust wird nicht genommen; Zielgewinn in der Variante ohne Materialitätsprüfung.
  * Golden-Reproducer End-to-End (Score 5): vor dem Fix rot (Optimierer 40/45/5/7/3, p = 0.0025), jetzt Hausmatrix 48/35/10/5/2.
* Angepasst: `test_objective_normalization.py` (Signifikanz vergleicht Zielebene, Tiebreak existiert weiter) und `test_saa_resampled_stability.py` (Testversion v4, Vergleich `goal_level`).
* Golden-Fixtures neu eingefroren (Engine `saa_resampled_v5`), unter `OPENBLAS_CORETYPE=Haswell` und `=Nehalem` alle sechs byte-identisch. Zahlen im Docstring von `tests/test_golden_snapshot_ch_regression.py`.
