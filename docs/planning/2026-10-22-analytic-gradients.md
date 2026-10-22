# ANALYTIC-GRADIENTS-001 – analytische Gradienten für den SLSQP-Solver

Stand 2026-10-22 · Branch `docs/analytic-gradients-design` · Basis `develop@4105776` (Engine `saa_resampled_v10`)
Art: **Konzept + Experiment, keine Produktcode-Änderung.**
Experiment: `tools/analytic_gradients/analytic_gradient_experiment.py` (Subkommandos `check`, `solve`, `kappa`)

## 0. Kurzfassung

1. **Der Gradient ist geschlossen herleitbar und billig.** Die Vermögensrekursion inklusive Cashflows, Liabilities, Mortalitätsmaske, W2.5-Schalter (`W > 0`) und Prioritäts-Scope-Replays hat eine exakte Adjungierte (Rückwärtsrekursion). Je Scope braucht sie einen Rückwärtslauf auf Vektoren der Länge P. Dazu kommt **eine** Kontraktion `einsum('hp,hpb->b')` mit den Bucket-Renditen. Gemessen: Der Wert stimmt mit der Produktion auf 1e-15 überein. Der Gradient des glatten Teils (Fehlbetrag + Prior/Tiebreak + Präferenz) weicht von zentralen Differenzen der **Produktionsfunktion** um median 1e-10…1e-8 (rel.) ab, im Maximum um 2e-5 (Fundament, ein Kink-Punkt). Adjungierte und Tangente (Vorwärtsmodus) stimmen auf 1e-14 überein.
2. **Ohne Ergebnisänderung messbar schneller.** Variante `analytic` = exakter Gradient f.ü., Chance-Strafe mit Gradient 0. Sie liefert auf **allen 12 Fällen bps-identische Allokationen** wie die Produktion. Die Zahl der Simulationen sinkt um 90–97 %, die SLSQP-Zeit sinkt um 24–67 %. Die Gesamtlaufzeit von `run_solver` sinkt um 20–65 % (Fundament 11.4 s → 8.8 s; Messungen unter Parallel-Last, ±30 %).
3. **Befund: Der heutige FD-Gradient sieht die Chance-Strafe nicht.** scipy differenziert mit dem Schritt 1.49e-8. Auf 88 geprüften Punkten weicht dieser FD-Gradient vom analytischen Gradienten des glatten Teils median um 1e-7…2e-6 (rel.) ab, und es gab **0 Sprünge**. Die stückweise konstante Strafe C(w) liefert also keinen Gradienten. Sie wirkt nur über die Funktionswerte in der Linesearch. Die Variante `analytic` (Gradient von C = 0) reproduziert deshalb die Produktion bitgenau. Das ist kein Zufall, es ist dieselbe Mathematik.
4. **Der nicht-monotone TE in κ kommt NICHT von den FD-Gradienten.** FD und analytisch liefern für jedes κ dieselben Gewichte, also auch denselben nicht-monotonen TE. Ursache ist die **Stufe-1-Schranke der Zielhierarchie**: Ein Bag, dessen TE mit κ steigt, ist in **100 %** der gemessenen Fälle (26/26, 30/30, 31/31 Bags) ein Bag, in dem die Schranke bindet. Dort wählt die Streckensuche einen Punkt zwischen w1* und w2, nicht den Minimierer der κ-Zielfunktion. Eine echte Nebenbedingung mit analytischer Jacobi-Matrix (Variante `constrained`) senkt die Trainings-Zielfunktion und macht den TE bei Mandat C monoton (101.6 → 84.0 → 67.2 → 64.1 → 63.9 bps). Bei D und Fundament bleibt er nicht durchgehend monoton, und die Laufzeit steigt. Das ist ein eigener Schritt (Phase 3), kein Gradientenfix.
5. **Glättung der Chance-Strafe in Stufe 2** (Variante `smooth`, Auswahl weiterhin exakt) ändert Ergebnisse: Training besser auf B/C/D, OOS-Zielebene besser auf D (−1.6 %) und Fundament (−0.4 %), schlechter auf C (+0.4 %). Sie spart auf dem Fundament weitere 30 %. Das ist eine Methodik-Änderung → Owner-Entscheid, eigene Engine-Version.

## 1. Was SLSQP heute optimiert

Default-Modus `goal_shortfall`, je Bag-Würfel (40 × 500 Pfade), Stufe 2 (`_select_cube_candidate_core`):

```
f(w) = L(w) + C(w) + κ_H (w − w_H)' M (w − w_H) / 1e8  [+ λ Σ α_b (w_b − p_b)²]
```

* `L(w) = Σ_g h_g g_g cap_g · E_ω[s_g(w)² / W̃0²]`, wobei `W̃0 = max(1, W0)` und ω die (IS-)Pfadgewichte sind (`shortfall_objective`).
* `C(w) = Σ_g λ_C φ_g V_g² · max(0, τ_g − LB_Wilson(p̂_g(w), n_eff))`, wobei p̂_g = E_ω[1{Ziel g erreicht}] (`chance_constraint_penalty`).
* Prior: `M = Σ + 2500·I` (bps²), κ_H = 300 (`house_prior.py`). Ohne Anker gilt stattdessen der Tiebreak `κ w'Σw/1e8`.
* Stufe 1 (`_goal_protection_stage`) minimiert die glatte Näherung `protected_goal_level_surrogate`. Darin wird der Indikator durch `σ(m/β)` ersetzt, mit β = 0.02.

`_solve_single_start` ruft `scipy.optimize.minimize(method="SLSQP")` **ohne `jac`** auf. Pro Gradient sind das 5 zusätzliche Auswertungen (2-Punkt-FD), jede mit voller Simulation und allen Scope-Replays. Linear sind nur die Nebenbedingungen (Summe = 1 und Risikobudget, beide mit `jac`).

## 2. Herleitung

### 2.1 Vorwärtsrekursion (wie `_simulate_wealth_paths_untaxed`)

Für Pfad p, Jahr t = 0…H−1, Gewichte w ∈ R⁵ und Bucket-Bruttorendite R_{t,p} ∈ R⁵:

```
f_{t,p}   = R_{t,p} · w
π_{t,p}   = 1[W_{t,p} > 0]                         (W2.5: negatives Vermögen wird nicht verzinst)
W_{t+1,p} = π_{t,p} W_{t,p} f_{t,p} + (1 − π_{t,p}) W_{t,p} + a_{t,p} (c^k_t − ℓ^k_t)
```

`a_{t,p}` ist die Mortalitätsmaske (konstant in w). `(c^k, ℓ^k)` ist der Plan des Scopes k: der gemeinsame Plan bzw. je Prioritäts-Scope Cashflow ohne entfallende Reserve-Freigaben und Scope-Liability (`ScopeReplayInputs.prepare_scope`). Alle Scopes teilen **dieselben** f_{t,p} (CRN).

Die annualisierte TWR ist `r_p = exp(mean_t log max(f_{t,p}, 1e-12)) − 1` (bps ·1e4).

### 2.2 Saaten (∂f/∂W und ∂f/∂TWR je Ziel)

Mit dem Fehlbetrag `s` je Pfad, dem Pfadgewicht `ω_p` (Summe 1) und `c_g = h_g g_g cap_g`:

| Zielart | Saat |
|---|---|
| `wealth_at_t` (Spalte i) | `A^k_{i,p} += −2 c_g ω_p s_p / W̃0²` |
| `cashflow_in_year` / `outflow_stream` | `A^k_{j*(p),p} += −2 c_g ω_p s_p / W̃0²`, wobei `j*(p) = argmin` über die fälligen Spalten (Clarke-Subgradient, bei Gleichstand die erste) |
| `return_rate` (Horizont h) | `B_p += −2 c_g ω_p s_p / W̃0² · W̃0 h (1+r_p)^{h−1} / 1e4` |
| `maximize` | `B_p += −κ_max h_g g_g ω_p · h / (1+r_p) / 1e4` (0 unter der Klemme 1e-12) |
| Chance-Strafe exakt | 0 f.ü. (stückweise konstant, siehe 2.4) |
| Chance-Strafe geglättet | `k_p = −λ_C φ V² · LB'(p̃) · ω_p σ'(m_p/β)/β`, angewandt auf `∂m_p/∂W` bzw. `∂m_p/∂r` wie oben (Abstand m wie `_success_margin_per_path`) |

Die Ableitung der Wilson-Grenze lautet `LB'(p) = (1 − z(1−2p) / (2n·√(p(1−p)/n + z²/4n²))) / (1 + z²/n)`. Sie ist 0, wo LB auf [0,1] geklemmt ist. Die Ableitung von `max(0, τ − LB)` ist 0 auf der zulässigen Seite.

### 2.3 Adjungierte (Rückwärtsrekursion) je Scope k

```
λ_H = A^k_H
für t = H−1 … 0:
    G_{t,p} += λ_{t+1,p} π_{t,p} W^k_{t,p}                  (∂W_{t+1}/∂f_t)
    λ_t     = A^k_t + λ_{t+1} (π_t f_t + 1 − π_t)            (∂W_{t+1}/∂W_t)
G_{t,p} += B_p (1 + r_p) · 1e4 / H · 1[f_{t,p} > 1e-12] / f_{t,p}   (TWR, scope-unabhängig)
∇_w f = Σ_{t,p} G_{t,p} R_{t,p}  +  2 κ_H M (w − w_H)/1e8  +  2 λ α ⊙ (w − p)
```

* **Cashflows/Liabilities/Mortalität** gehen nur in den Vorwärtslauf ein. In ∂W_{t+1}/∂W_t kommen sie nicht vor, sie sind additiv und konstant in w. Die Mortalitätsmaske ist seit 2026-09-19 deterministisch, damit ist auch sie konstant.
* **Scopes**: Je eindeutigem Scope gibt es einen Rückwärtslauf. Alle Beiträge landen in derselben Matrix G. Das ergibt eine Kontraktion für alle Scopes. Ein Scope, der erst ab dem Jahr t0 abweicht (`divergence`), kann die Spalten 0…t0 vom gemeinsamen Lauf übernehmen. Das gilt vorwärts wie rückwärts für die Pfadwerte, die Saaten bleiben getrennt.
* **IS-Gewichte und n_eff** sind Konstanten des Würfels.
* **Prior**: trivial, `2κ_H M δ / 1e8`.
* **Kosten**: Vorwärtslauf wie heute + H Vektoroperationen der Länge P je Scope + ein einsum über (H, P, 5). Der Vorwärtsmodus (Tangente S = ∂W/∂w, (P, 5) je Jahr) ist bei nur 5 Parametern ebenfalls möglich. Gemessen ist er aber 1.6–2.4× teurer als die Adjungierte (siehe 3.1).

### 2.4 Nicht-glatte Stellen

| Stelle | Natur | Behandlung |
|---|---|---|
| `W_t = 0` (W2.5) | Knick, Maß null | einseitig (`π = 1[W > 0]`), wie die Vorwärtsrekursion |
| `max(0, ·)²` im Fehlbetrag | C¹ | exakt |
| `min` über Fälligkeiten | Knick bei Gleichstand | Clarke-Subgradient (argmin) |
| Chance-Strafe exakt | **stückweise konstant**, Sprünge ΔC = λ V² ΔLB bei jedem Pfadwechsel | Gradient 0 f.ü. (= was FD heute praktisch sieht). Optional geglättet (σ(m/β)) wie die Stufe-1-Suche, Entscheidung immer exakt |
| `max(0, τ − LB)` | Knick | 0 auf der zulässigen Seite |
| Steuer-Pfad (`median`/`binned`) | Querschnittsstatistiken über alle Pfade, Bin-Grenzen | **nicht abgedeckt** → FD-Fallback (siehe 5) |
| Risikomass-Varianten (Drawdown, CVaR …) | max/Quantil | nicht abgedeckt → FD-Fallback |

## 3. Experiment

**Aufbau.** Referenzmandate M1–M5 1:1 aus `tests/test_engine_reference_mandates.py`. Dazu M3R: M3 mit Erbschaft auf Rang 1 und Pension auf Rang 2, damit ein abweichender Prioritäts-Scope repliziert wird. Dazu A–E: Kalibrierungsmandate aus `tools/house_prior_calibration/calibration_common.py` mit knappen Zielen, sodass Fehlbetrag und Chance-Strafe aktiv sind. Und das Fundament (FUND): `run_solver`-kwargs aus einem Lauf der Stage-8-Pipeline (`generate_target_allocation`, `shadow_stochastic`, frische SQLite unter `DB_PATH`), 4 Ränge, 1 abweichender Scope, keine Steuerjurisdiktion. Produktionskonfiguration: 40 Bags × 500 Pfade, Haus-Prior κ_H = 300. Der Eingriff erfolgt nur per Monkeypatch im Skript: `_solve_single_start` bekommt `jac`, der Wert für die Linesearch wird ohne Rückwärtslauf berechnet. Die Auswahl, `_finite_feasible_candidate`, die Stufe-1-Schranke, die Streckensuche und die Rundung bleiben unverändert. OOS: unabhängiger antithetischer Würfel mit 20'000 Pfaden (Seed 0xA07, gleiche Verteilung, ohne IS), Zielebene = Fehlbetrag + Chance-Strafe (`two_phase_objective_parts`).

### 3.1 Gradient-Check (`check`, je Fall 1–2 Bag-Würfel × 6–8 zulässige Punkte: Multi-Starts, Hausquote, Zufallspunkte)

Fehler relativ in der 2-Norm. „Grad L+Prior“ und „Stufe-1“ werden gegen zentrale FD (h = 1e-6) der **Produktionsfunktion** gemessen (`combined_objective_two_phase(..., lambda_chance=0)` bzw. `protected_goal_level_surrogate`). „scipy-FD“ bezeichnet den 2-Punkt-FD mit Schritt 1.49e-8 auf der exakten Produktionsfunktion, also das, was SLSQP heute bekommt.

| Fall | Punkte | Scopes | Wert rel. max | Adj vs. Tangente | Grad L+Prior max (med) | Stufe-1 max (med) | scipy-FD vs. analytisch (med) | Punkte mit C > 0 | ms Wert (prod) | ms Wert+Grad (Adj.) | ms Tangente | ms FD-Grad (6 Ausw.) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| M1 | 8 | 0 | 2e-16 | 0 | 3e-11 | – | 9e-08 | 0 | 0.27 | 0.45 | 1.12 | 1.61 |
| M2 | 8 | 0 | 4e-15 | 7e-15 | 2e-10 (1e-10) | – | 1e-07 | 0 | 0.46 | 0.67 | 1.39 | 2.76 |
| M3R | 8 | 1 | 3e-16 | 0 | 8e-09 (3e-11) | – | 2e-07 | 0 | 0.80 | 1.04 | 2.38 | 4.82 |
| M4 | 8 | 0 | 4e-16 | 1e-15 | 1e-09 (9e-10) | 1e-09 (1e-09) | 7e-07 | 0 | 0.35 | 0.48 | 0.84 | 2.07 |
| A | 8 | 0 | 3e-15 | 2e-15 | 7e-10 (6e-10) | 7e-10 (6e-10) | 8e-07 | 1 | 0.34 | 0.40 | 0.70 | 2.05 |
| B | 8 | 0 | 1e-15 | 5e-15 | 4e-09 (3e-09) | 4e-08 (3e-09) | 2e-06 | 3 | 0.36 | 0.46 | 0.83 | 2.14 |
| C | 8 | 0 | 1e-15 | 4e-15 | 8e-10 (8e-10) | 2e-08 (3e-09) | 4e-07 | 8 | 0.23 | 0.33 | 0.67 | 1.37 |
| D | 8 | 0 | 4e-16 | 4e-15 | 5e-10 (4e-10) | 4e-09 (2e-09) | 5e-07 | 8 | 0.18 | 0.25 | 0.53 | 1.09 |
| E | 8 | 0 | 7e-16 | 2e-15 | 1e-09 (1e-09) | 2e-08 (1e-09) | 9e-07 | 4 | 0.18 | 0.29 | 0.57 | 1.09 |
| FUND | 16 | 1 | 1e-15 | 7e-15 | 2e-05 (2e-09) | 3e-05 (2e-08) | 5e-07 | 16 | 0.87 | 1.70 | 3.66 | 5.20 |

Lesart:
* Der Wert ist bitnah identisch. Die Herleitung bildet also dieselbe Funktion ab, inklusive Scopes, IS-Gewichten, Maximierungs- und Renditezielen.
* Die Maxima von 2e-5/3e-5 beim Fundament stammen von einem Punkt, an dem die zentrale Differenz (±1e-6) einen Knick überspannt (argmin-Wechsel bzw. `W = 0`). Der Median liegt bei 1e-9.
* **scipy-FD vs. analytisch (Gradient von C = 0)**: median 1e-7…2e-6 und auf 88 Punkten **kein einziger Sprung** (Kriterium |Δ| > 1). Das gilt auch auf den 40 Punkten mit aktiver Strafe. SLSQP bekommt heute faktisch den Gradienten von L + Prior. C wirkt nur über die Linesearch-Werte.
* Ein Wert+Gradient per Adjungierte kostet 1.1–2.0 Wertauswertungen. Ein FD-Gradient kostet 6.

M1, M3, M3R und M5: Alle Ziele sind auf allen Pfaden erfüllt, deshalb prüft der Check dort vor allem Prior und Scopes. Echte Fehlbetrags-Gradienten prüfen M2, M4, A–E und FUND (alle Punkte mit Ziel-Gradient ≠ 0).

### 3.2 Solver-Läufe (`solve`, 40 Bags × 500 Pfade, je Modus ein Lauf)

`fd` = Produktion, `analytic` = Adjungierte und Gradient von C = 0, `smooth` = Stufe 2 auf geglätteter C (β = 0.02, Auswahl exakt). Stufe 1 ist in `analytic` und `smooth` identisch, dort mit analytischem Gradienten der Produktions-Glättung. „Sims“ zählt die Produktionssimulationen (`_evaluation_inputs`), „Grad“ die Rückwärtsläufe. Zeiten: zweiter Messlauf (`a07_solve2`), Gesamt-`run_solver` / davon in SLSQP.

| Fall | fd: Zeit (SLSQP) | fd: Sims | analytic: Zeit (SLSQP) | analytic: Sims / Grad | Gewichte analytic = fd? | smooth: Zeit (SLSQP) | smooth: Gewichte E/B/RE/A/L |
|---|---|---|---|---|---|---|---|
| M1 | 3.1 (2.7) | 6602 | 1.6 (1.2) | 441 / 1040 | ja | 1.6 (1.2) | = fd |
| M2 | 5.0 (4.5) | 7773 | 2.2 (1.7) | 321 / 1188 | ja | 2.9 (2.3) | = fd |
| M3 | 6.3 (5.8) | 8041 | 2.5 (2.1) | 281 / 1200 | ja | 2.8 (2.4) | = fd |
| M3R | 7.4 (7.0) | 8041 | 3.8 (3.3) | 281 / 1200 | ja | 3.1 (2.7) | = fd |
| M4 | 4.0 (3.3) | 8407 | 2.0 (1.5) | 401 / 1224 | ja | 1.9 (1.4) | = fd |
| M5 | 4.2 (3.9) | 9121 | 2.5 (2.1) | 361 / 1400 | ja | 3.0 (2.5) | = fd |
| A | 4.0 (3.1) | 9744 | 2.2 (1.4) | 841 / 1407 | ja | 2.5 (1.6) | = fd |
| B | 6.6 (5.7) | 13649 | 3.6 (2.5) | 531 / 1692 | ja | 2.9 (1.8) | 793/7027/181/0/1999 (fd 774/7015/210/1/2000) |
| C | 10.9 (9.7) | 19912 | 6.1 (5.0) | 870 / 2414 | ja | 4.1 (2.9) | 6087/2292/1235/186/200 (fd 6142/2335/1234/89/200) |
| D | 9.8 (9.0) | 21399 | 3.6 (3.0) | 589 / 2380 | ja | 1.4 (0.8) | 6235/2015/1500/50/200 (fd 6038/2225/1444/93/200) |
| E | 3.9 (3.1) | 9970 | 1.9 (1.2) | 881 / 1447 | ja | 2.1 (1.3) | ≈ fd (±1 bp) |
| **FUND** | **11.4 (7.0)** | 8449 | **8.8 (5.3)** | 758 / 1107 | ja | **6.1 (1.8)** | 6242/1390/1817/300/251 (fd 6234/1440/1775/300/251) |

Zeiten in Sekunden, gemessen unter Last von ~20 parallelen Agenten. Der erste Messlauf (`a07_solve`) lag je Zelle bis ±30 % daneben, die Verhältnisse bleiben stabil. Das Fundament braucht ausserhalb von SLSQP ~3.5–4 s (Würfelbau, exakte Stufe-1-Niveaus, Validierungswürfel, Signifikanztest, Zertifizierung). Diesen Anteil verkürzen analytische Gradienten nicht.

Ergebnisqualität (OOS-Zielebene, 20'000 Pfade, kleiner = besser; P = Zielwahrscheinlichkeit OOS):

| Fall | fd = analytic | smooth | Training-Zielfunktion fd → smooth |
|---|---|---|---|
| A | 0.016883 (P 0.873) | 0.016883 | 0.065652 → 0.065652 |
| B | 0.0051485 (P 0.8242) | 0.0051467 (P 0.8246) | 0.004564 → 0.004563 |
| C | 0.215738 (P 0.6249) | 0.216514 (P 0.6240) | 0.240033 → 0.236717 |
| D | 2.43935 (P 0.6792) | 2.39944 (P 0.6838) | 2.78324 → 2.72778 |
| E | 0.0070041 | 0.0070036 | 0.149349 → 0.149381 |
| FUND | 0.371058 | 0.369555 | 0.425866 → 0.425988 |
| M1–M5, M3R | identisch | identisch | identisch |

`smooth` findet auf B, C und D einen **niedrigeren exakten** Trainingswert als die Produktion. Das belegt, dass die gegen C blinde Suche das Minimum dort verfehlt. OOS ist der Effekt gemischt (D und FUND besser, C schlechter). Die Strafe ist eine weiche Untergrenze, und ein niedrigerer Trainingswert ist keine OOS-Garantie.

### 3.3 TE in κ_H (`kappa`, κ ∈ {30, 100, 300, 1000, 3000})

Der TE ist der ausgewiesene Tracking Error zur projizierten Hausquote in bps.

| Fall | fd | analytic | smooth | constrained |
|---|---|---|---|---|
| C | 107.7 / 91.0 / 74.3 / **75.4 / 75.4** | identisch fd | 112.6 / 101.8 / 69.3 / **72.9 / 75.8** | 101.6 / 84.0 / 67.2 / 64.1 / 63.9 (monoton) |
| D | 100.3 / 97.4 / 82.5 / 76.5 / **83.0** | identisch fd | 109.5 / 109.1 / 105.5 / 92.6 / 84.7 (monoton) | 92.5 / 91.9 / 82.4 / 75.6 / **80.2** |
| FUND | 124.7 / 115.5 / 112.7 / **122.3 / 124.3** | identisch fd | 120.8 / 117.6 / 114.4 / **120.3 / 123.9** | 124.7 / 114.1 / 109.6 / **114.3 / 114.7** |

Theorie: Für den **globalen** Minimierer von `F(w) + κ P(w)` auf einer κ-unabhängigen zulässigen Menge ist P(w_κ) in κ nicht steigend. Die Stufe-1-Schranke hängt nicht von κ ab, weil die Stufe 1 ohne Prior rechnet und die Toleranz auf Haus vs. w1* gepaart ist. Jeder Anstieg ist also ein Optimierungsartefakt.

Zerlegung je Bag (κ ∈ {100, 300, 1000, 3000}, gleiche Bag-Würfel):

| Fall / Modus | Bags mit TE-Anstieg | davon Stufe-1-Schranke bindend | Bags mit bindender Schranke bei κ = 100/300/1000/3000 |
|---|---|---|---|
| C analytic | 26/40 | **26** | 25 / 38 / 40 / 40 |
| D analytic | 30/40 | **30** | 40 / 10 / 26 / 35 |
| FUND analytic | 31/40 | **31** | 30 / 37 / 40 / 40 |
| C constrained | 18/40 | – | – |
| D constrained | 28/40 | – | – |
| FUND constrained | 25/40 | – | – |

**Diagnose.** Je grösser κ, desto näher liegt das Stufe-2-Optimum w2 an der Hausquote. Damit verletzt es die Schranke `G1 ≤ G1* + ε` öfter. Dann wählt `_select_cube_candidate` den besten zulässigen Punkt auf der Strecke w1* → w2. w1* ist der Stufe-1-Minimierer **ohne** Prior, er liegt hausfern. Mit steigendem κ wandert die Auswahl damit Richtung w1*, und der TE steigt. Die FD-Gradienten sind daran unbeteiligt (`analytic` ≡ `fd`).

**`constrained`** (nur im Skript) ersetzt die Streckensuche bei bindender Schranke durch einen SLSQP-Lauf mit der Nebenbedingung `G1_glatt(w) ≤ Schranke`. Er läuft mit analytischer Jacobi-Matrix und Start im Streckenpunkt, entschieden wird exakt (G1 und f). Effekt bei κ = 300: Die Trainings-Zielfunktion sinkt (C 0.2400 → 0.2356, FUND 0.42587 → 0.42367), der TE sinkt (C 74.3 → 67.2, FUND 112.7 → 109.6). Die OOS-Zielebene steigt leicht (C 0.2157 → 0.2174, FUND 0.3711 → 0.3702). Das ist erwartbar: näher am Haus heisst mehr Fehlbetrag, und genau das ist der Zweck des Priors. Die Laufzeit steigt aber auf 21 s (FUND, κ = 300). D und FUND bleiben nicht durchgehend monoton, weil SLSQP lokal sucht und die glatte G1-Nebenbedingung von der exakten abweicht. Für eine Produktion bräuchte das einen eigenen Entwurf (siehe 4, Phase 3).

## 4. Umsetzungsplan

### Phase 1 – analytischer Gradient, Ergebnis unverändert (Vorschlag: nächste Engine-Version, `saa_resampled_v11`)

Ziel: nur Laufzeit. Gemessen auf 12/12 Fällen bps-identisch. Allgemein ist Bitidentität **nicht** garantiert: SLSQP-Iterate weichen um ~1e-7 ab, im Fall B gab es 1683 statt 1673 Iterationen bei gleichem Ergebnis. Deshalb Versionssprung statt stiller Änderung.

| Datei | Änderung |
|---|---|
| `services/optimizer/gradients.py` (neu) | `objective_value_and_gradient(context, inputs, w)` und `stage1_surrogate_gradient(...)`: Saaten je Zielart (Tabelle 2.2), Adjungierte je Scope (2.3), Prior/Tiebreak/Präferenz. Liest die Vorwärtsinputs aus `_EvaluationMemo` (keine zweite Simulation). Dazu Positivmaske und Scope-Pfade, die `priority_scope.simulate_many` dafür mitliefern muss (inkl. der Spalten ab `divergence`). `gradient_supported(context) -> bool` (False bei Steuer, Risikomass-Varianten, `scenario_weights` mit falscher Form). |
| `services/optimizer/priority_scope.py` | `simulate_many(..., keep_masks=True)`: Positivmasken je Scope. `stops` bleibt, denn die Rückwärtsrekursion braucht nur Spalten ≤ stop. |
| `services/optimizer/solver.py` | `_solve_single_start(..., jac=None)` reicht `jac` durch. `_select_cube_candidate_core` und `_goal_protection_stage` übergeben `jac` nur bei `gradient_supported`, sonst bleibt es bei FD. `OPTIMIZER_ENGINE_VERSION` wird erhöht, im ObjectiveContract steht neu `gradient_method = "adjoint_v1" | "finite_difference"`. **`portfolio_engine.py` wächst nicht.** |
| `services/optimizer/objective.py` | unverändert. Die Formeln werden nur gelesen, sie bleiben eine Quelle der Wahrheit. Der Gradient-Test (unten) bindet beide aneinander. |

Tests (rot gegen develop, wo sinnvoll):
* `tests/test_optimizer_analytic_gradient.py`: (a) Wert-Parität 1e-12 gegen `_objective_from_array` auf M1–M5, M3R (Scopes), A–E; (b) Gradient gegen zentrale FD der Produktionsfunktion ohne C, rel. ≤ 1e-6, an Multi-Start-Punkten (knickfrei gewählt); (c) Adjungierte ≡ Tangente ≤ 1e-12; (d) Stufe-1-Surrogat ≤ 1e-6; (e) Mortalitätsmaske, IS-Gewichte, `return_rate`/`maximize`, Reserve-Freigaben im Scope; (f) `gradient_supported` = False bei `tax_regime`, und dann wird kein `jac` übergeben (Spy).
* Regression: `tests/test_engine_reference_mandates.py` unverändert grün, Golden-Snapshots (`test_golden_snapshot_ch_regression.py`) bps-gleich, sonst mit Begründung pinnen. `test_stage8_foundation_smoketest.py` als Laufzeitbudget.
* Laufzeit-Test: Zähler der `_evaluation_inputs`-Aufrufe je Bag (z. B. ≤ 25 % von heute auf M4), statt Wanduhr.

### Phase 2 – geglättete Chance-Strafe in Stufe 2 (Owner-Entscheid, eigene Engine-Version)

Stufe 2 sucht auf `L + C̃_β + Prior`, Auswahl und Ausweis bleiben exakt (`_finite_feasible_candidate` mit exaktem f). Das gleiche Muster nutzt Stufe 1 schon heute. Nutzen gemessen: Trainingswert auf B/C/D besser, Fundament weitere −30 % Laufzeit. Kosten: Ergebnisse ändern sich, OOS gemischt (C +0.4 %, D −1.6 %, FUND −0.4 %). **Owner-Entscheid**, ob β = 0.02 übernommen wird (heute nur Numerik-Konstante der Stufe 1) und ob die gemischte OOS-Bilanz trägt. Vorher wäre ein Holdout nach dem Muster `kappa_holdout.py` mit vorab registrierter Regel nötig.

### Phase 3 – Stufe-1-Schranke als echte Nebenbedingung (separater Auftrag)

Der nicht-monotone TE in κ entsteht durch die Streckensuche, nicht durch die Gradienten. Kandidat: SLSQP mit `G1_glatt ≤ Schranke` und analytischer Jacobi-Matrix, exakte Nachprüfung, Rückfall auf die Strecke (Skript-Variante `constrained`). Gemessen ist das nur ein Teilerfolg: C wird monoton, D und FUND nicht durchgehend, und die Laufzeit steigt ×2.4. Offen ist, wie die glatte Nebenbedingung so kalibriert wird, dass sie die exakte Schranke konservativ einschliesst (z. B. Schranke um den gemessenen Surrogat-Bias senken). Ebenso offen ist die Frage, ob ein Multi-Start in Stufe 2 unter der Nebenbedingung bezahlbar ist. Phase 1 ist dafür Voraussetzung, sonst kostet jede Jacobi-Matrix 6 Simulationen.

## 5. Risiken

* **Zwei Implementierungen derselben Zielfunktion** (Wert in `objective.py`, Ableitung in `gradients.py`) sind genau die Divergenzklasse der MC-Paritätsbefunde. Gegenmittel: Der Gradient liest die Inputs aus derselben Simulation (Memo), und die Pflicht-Tests (b)/(c) laufen auf allen Zielarten. Jede neue Zielart in `objective.py` ohne Saat soll `gradient_supported = False` liefern (Allowlist der `target_kind`s, fail-closed auf FD).
* **Steuer-Pfad**: `median`/`binned` koppeln die Pfade über Querschnittsstatistiken. Ein „frozen-statistic“-Gradient (Median als Konstante) wäre falsch um den Term ∂median/∂w. Phase 1 lässt Steuer-Mandate bewusst auf FD. Eine Messung des Anteils produktiver Mandate mit `tax_jurisdiction` steht aus (Live-DB nur zählend lesen).
* **Knicke** (`W = 0`, argmin-Wechsel, `max(0, τ − LB)`): Dort ist der Gradient ein Subgradient. SLSQP ist ein Verfahren für glatte Probleme. Heute gilt dasselbe implizit mit FD (gemessen: FD ≡ analytisch). Phase 1 verschlechtert das nicht.
* **Ergebnisänderungen** in Phase 1 sind trotz identischer Mathematik möglich, weil sich SLSQP-Iterate um ~1e-7 unterscheiden und Multi-Start-Gewinner bei Gleichstand kippen können. Darum Versionssprung und Golden-Snapshot-Prüfung.
* **Messrauschen**: Die Laufzeiten stammen von einem geteilten Rechner (±30 %). Die Zähler (Sims, nfev, nit) sind deterministisch und massgeblich.
* **Variante `smooth`/`constrained`** ändert die Methodik. Ohne Holdout und Owner-Entscheid kein Produktiveinsatz.

## 6. Reproduktion

```
DB_PATH=<scratch>/a07_grad.db python tools/analytic_gradients/analytic_gradient_experiment.py check --cases M1,M2,M3R,M4,A,B,C,D,E,FUND --bags 1 --random 2
DB_PATH=... python tools/analytic_gradients/analytic_gradient_experiment.py solve --cases FUND,M1,M2,M3,M3R,M4,M5,A,B,C,D,E
DB_PATH=... python tools/analytic_gradients/analytic_gradient_experiment.py kappa --cases C,D,FUND --modes fd,analytic,smooth
DB_PATH=... python tools/analytic_gradients/analytic_gradient_experiment.py kappa --cases C,D,FUND --modes constrained
```

Das Skript lehnt die Live-DB ab und schreibt nur nach `DB_PATH` (Fundament-Fall: `<stem>_fund.db` + Pickle-Cache der kwargs). Threads = 1. Zieldaten sind relativ zu `date.today()`, die Zahlen sind innerhalb eines Bewertungstags reproduzierbar. Messdatum: 2026-10-21.

## 7. Offene Owner-Entscheide

1. Phase 1 umsetzen (Laufzeit, Engine-Versionssprung trotz gemessen identischer Ergebnisse)?
2. Phase 2: geglättete Chance-Strafe in Stufe 2 (β = 0.02) – erst nach registriertem Holdout.
3. Phase 3: Ist die Zielhierarchie-Schranke wichtiger als die Monotonie des TE in κ? Heute gewinnt die Schranke (per Design), der κ-Regler wirkt jenseits von ~300 nicht mehr in Richtung Haus.
