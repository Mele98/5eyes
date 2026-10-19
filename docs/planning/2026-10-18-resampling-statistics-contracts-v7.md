# Engine `saa_resampled_v7` – statistische Verträge für Resampling, Holdout und House-Prior

Stand 2026-10-18 · Branch `fix/resampling-statistics-contracts` (auf `develop@a7ffec9`, Engine v6)
Grundlage: Codex-Reviews `docs/audits/2026-10-18-resampled-efficiency-and-drawdown-validation-review.md` und `docs/audits/2026-10-18-house-prior-v6-pr640-current-review.md` (Branch `codex/asset-allocation-stochastic-core`).
Code: `services/optimizer/resampling.py`, `house_prior.py`, `scenario_engine.py` (Layout-Vertrag), `drawdown_certification.py` (Rollen/Texte), `solver.py` (nur Validierungs-/Resampling-Teil: `_build_validation_context`, `_significance_vs_house_anchor`, `_run_resampled_solver`, `_house_prior_disclosure`, Einzelwürfel-Rerank). Nicht angefasst: `objective.py`, Objective-Funktionen in `solver.py`, `portfolio_engine*.py`.

## 1. Übersicht

| Befund | Vertrag v7 | Nachweis |
|---|---|---|
| RESAMPLING-ANTITHETIC-BOOTSTRAP-001 (P0) | Bootstrap zieht unabhängige Einheiten (antithetische Paare), Einheiten-Metadaten in Modellbasis | Codex-Gegenfall: Zeilen p = 0.0374 → Paare 0.0723 (nullzentriert), Tail-Fraction 0.0873; nicht mehr signifikant |
| RESAMPLING-PVALUE-SEMANTICS-001 (P1) | `p_value` = nullzentrierter einseitiger p-Wert mit `null_hypothesis`/`p_value_calibration`; roher Anteil heißt `bootstrap_tail_fraction`; B = 999 | Größe unter H0 simuliert: 0.060 (1000 Datensätze, se 0.007), 0.049 (3000); Zeilen-Bootstrap 0.124 |
| DRAWDOWN-HOLDOUT-REUSE-001 (P0) | Auswahl-Würfel ≠ finaler Holdout; Challenger eingefroren; Zielerreichung + Test auf demselben finalen Cube | Störung des Holdouts ändert den Challenger nicht; Störung des Auswahl-Würfels ändert die Holdout-Identität nicht |
| RESAMPLING-SUCCESS-SURVIVOR-BIAS-001 (P1) | Mindestquote 90 % (36/40), darunter fail-closed; SE als bedingt benannt; Ausfall-Sensitivität | 40/39/36 → Mittel, 35/30/20/19 → House-Fallback |
| OPTIMIZER-POST-SELECTION-CERTIFICATION-001 (v6-Teil) | ohne finalen Validierungswürfel: Hausquote (Prior: `house_prior_fail_closed`; Varianten: `house_matrix`) | Reproducer + Variantentest |
| HOUSE-PRIOR-PSD-NULLSPACE-001 (P1) | Prior-Metrik `Σ + εI`, ε = 2'500 bps² | singuläre/fast singuläre PSD: λ_min ≥ ε; TE > 0 für jedes w ≠ w_H |
| HOUSE-PRIOR-DECISION-OBJECTIVE-IDENTITY-001 (P1) | Abschluss auf dem Prior-Context; `result.objective_value` = Entscheidungs-Zielfunktion | `evaluate_weights(result.context, w) == result.objective_value` |
| HOUSE-PRIOR-CALIBRATION-PROVENANCE-001 (P1) | Kalibrierungspaket commitgebunden + Holdout-Test | `docs/planning/2026-10-18-house-prior-kappa-calibration.md` |

Engine-Version `saa_resampled_v6` → `saa_resampled_v7` (geht in den Inhalts-Seed: neue Würfel, alte und neue Mathematik nie unter demselben Seed).

## 2. Stichprobeneinheit und p-Wert

**Layout-Vertrag** (`scenario_engine.sampling_unit_ids`): `build_scenario_paths(antithetic=True)` legt die `half = ⌈n/2⌉` Basispfade in die Zeilen `0..half−1`, ihre Spiegelungen in `half..n−1`. Pfad `i` und `i + half` sind eine Einheit; bei ungerader Pfadzahl ist der letzte Basispfad eine Einzel-Einheit (Replikationsgröße `2(m−k)+k`, Erwartung exakt `n`). Ohne Antithetics ist jeder Pfad eine Einheit – dann reproduziert der neue Bootstrap den alten Zeilen-Bootstrap bit-gleich (gleicher RNG-Strom). Der Validierungswürfel ist immer antithetisch (`solver.VALIDATION_CUBE_ANTITHETIC`, einzige Quelle für Bau und Einheit).

**Warum Paare.** Antithetische Renditen garantieren nicht, dass die *Verlustdifferenz* zweier Portfolios negativ korreliert ist (Chance-Strafe, Shortfall, Drawdown sind nichtlinear). Zeilen-Resampling zählt dann 2m abhängige Beobachtungen als 2m unabhängige: im Grenzfall perfekt positiver Paar-Korrelation ist die Bootstrap-Streuung um √2 zu klein, die Größe des 5-%-Tests steigt auf 1 − Φ(1.645/√2) = 12.2 % (simuliert 12.4 %).

**p-Wert.** `p_value = (1 + #{Δ*_b − Δ̂ ≥ Δ̂}) / (B + 1)` – Shift-Bootstrap unter H0 (Δ = 0 am Rand von H0: Δ ≤ 0; Hall & Wilson 1991, Guideline 1), dual zur einseitigen Basic-Grenze `2Δ̂ − q_{1−α}` (`improvement_lower_bound`). Entscheid: `Δ̂ > 0` und `p_value ≤ α`. Der frühere Wert `(1 + #{Δ* ≤ 0})/(B + 1)` aus der *unzentrierten* Verteilung bleibt als `bootstrap_tail_fraction` (Stabilitätskennzahl, entscheidet nichts). Offenlegung des Priors analog: `p_value_better` (H0 Δ ≤ 0), `p_value_worse` (H0 Δ ≥ 0), Intervall `[2Δ̂ − q_{1−α}, 2Δ̂ − q_α]`, `bootstrap_tail_fraction_not_better/_not_worse`; Sicherheitsnetz `Δ̂ < 0 ∧ p_value_worse ≤ α`.

**B = 999** statt 400: `α(B+1) = 50` ganzzahlig (exaktes Niveau des (1+k)/(B+1)-Tests), MC-Fehler des p-Werts an α: 0.0069 statt 0.0109; Laufzeit +0.08 s je Lauf (gemessen, Mandat D 5.5–6.1 s gesamt).

**Modellbasis** (`resampling_model_basis`): `bootstrap_method`, `sampling_unit`, `n_independent_units`, `sampling_unit_hash` (SHA-256 der Einheiten-IDs), `null_hypothesis`, `p_value_calibration`, `bootstrap_tail_fraction`, `cube_role`, `selection_seed`, `selection_cube_hash` (nur max_drawdown); der Validierungs-Cube-Hash bindet zusätzlich `role=` und `sampling_unit=`.

## 3. Drei-Rollen-Architektur (max_drawdown)

```text
Bag-Würfel (40 × 500)     -> Kandidaten (projiziertes/rohes Bag-Mittel)
Auswahl-Würfel             -> Rerank {proj. Mittel, rohes Mittel, Hausanker}, genau EIN Challenger eingefroren
finaler Holdout            -> Challenger vs. Hausanker (Signifikanz) + publizierte Zielerreichung; keine Auswahl
```

* Seeds: finaler Holdout = Inhalts-Seed + `VALIDATION_SEED_OFFSET` (unverändert), Auswahl = `SHA-256("saa-validation-selection-v1", Inhalts-Seed)`; für einen künftigen Reachability-Screen ist die Rolle `reachability_screen` mit eigener Domäne vorbereitet.
* Auf dem Holdout wird genau ein Challenger getestet → keine Multiple-Selection-Korrektur nötig. Rerank-Kennzahlen heißen im Audit `cube_role = "selection"`, `selection_free = false`; Reasoning sagt „Auswahl-Würfel (Selektionsschätzung)“.
* Auch der Einzelwürfel-Pfad (`SINGLE_CUBE`) rankt seine Multi-Start-Finalisten jetzt auf dem Auswahl-Würfel; die Zielerreichung zertifiziert der finale Holdout.
* Der bisherige Produkttest, der identische Seeds/Hashes für Rerank, Test und Zielerreichung verlangte, ist auf den Drei-Rollen-Vertrag umgestellt (Codex: „kein Erfolgsbeleg“).

## 4. Survivor-Schwelle

Bias je Bucket = f · (μ_fehlend − μ_erfolgreich). Stressannahme: fehlende Bags liegen bis 2 σ_bag neben dem Mittel der erfolgreichen. Gemessen σ_bag ≈ 4–5 pp (500 Pfade), also 2σ ≈ 10 pp. Präzisionsziel der Quote 1 pp → f ≤ 10 % → **mindestens 90 % erfolgreiche Bags (36/40)**. Darunter fail-closed (`decision = fallback_house_matrix`, `reason = insufficient_successful_bags`, kein Mittel publiziert). Ausgewiesen: `min_successful_bag_share`, `missingness_sensitivity_bps = f · 2 · σ_bag` je Bucket (0 bei 40/40), Standardfehler umbenannt in `conditional_bag_mean_standard_error_bps` (bedingt auf erfolgreiche Bags; enthält weder Ausfall- noch Projektions- oder Gate-Unsicherheit). Offen (nicht Teil dieses PR): Diagnose Ausfall vs. Cube-Stressmerkmale (Regression 14 des Reviews).

## 5. House-Prior

**Ridge-Metrik.** `M = Σ + εI`, ε = 2'500 bps² = (0.5 %)² p.a. λ_min(M) ≥ ε → Term stark konvex, eindeutiges Minimum, Gauss-Prior proper. Anteil der Ridge an der TE-Varianz typischer 10-pp-Umschichtungen (Test-CMA): Aktien↔Obligationen 0.2 %, Immobilien↔Obligationen 0.7 %, Obligationen↔Liquidität 3.3 %. `tracking_error_vs_house_bps` ist der Abstand in M (regularisierter TE); `prior_metric` im Audit: ε, Eigenwerte, Konditionszahl, κ-Kalibrierungsstatus.

**Solver-Toleranz am Anker.** Ist der Gradient der Zielebene an der Hausquote 0 (Ziele sicher, keine Ziele), ist das exakte Optimum die Hausquote. SLSQP mit Produktions-`ftol = 1e-6` stoppt bei Zielfunktionswerten ~1e-11 vorher: gemessen 0.6 bp Restabweichung (Mandat E ohne Ziele; `ftol = 1e-9`: 0.0003 bp); mit der Ridge-Metrik rundete das bps-Mittel 509.39 auf 509 statt 510. Abweichungen ≤ 1 bp in jedem Bucket gelten deshalb als Solver-Toleranz: publiziert wird der Anker, `reason = within_solver_tolerance_of_house_anchor`. Größere Abweichungen bleiben unverändert stetig (kein Schalter).

**Entscheidungs-Zielfunktion.** Bags und Abschluss laufen auf demselben Prior-Context. `result.context` ist `replace(caller_context, house_prior_weights=w_H, house_prior_kappa=κ)` – alle übrigen Felder sind dieselben Objekte –, `result.objective_value = G + P_pref + κ_H·TE_M²`, `evaluate_weights(result.context, result.weights_bps).objective_value == result.objective_value`. Ein ohne Prior gebauter Context bewertet bewusst eine andere Zielfunktion (v5-Tiebreak w'Σw); die bestehenden Apples-to-Apples-Tests bauen deshalb den Context aus denselben Inputs plus dem publizierten Prior-Anker. Aktivierungsvalidierung und House-Fallback in `portfolio_engine_optimizer_integration.py` lesen `result.context` (gleiche Bounds/Constraints), der Shadow-Vergleich baut seinen eigenen Context und bewertet beide Allokationen darunter – beides unverändert gültig.

**Fail-closed.** Kein finaler Validierungswürfel → `decision = house_prior_fail_closed`, `final_bps` = projizierte Hausquote (vorher: Kandidat). In den Risikomaß-Varianten mit Anker analog `decision = house_matrix`, `reason = no_validation_cube` (vorher `optimizer_untested` mit Kandidat). `significance_test = False` (nur Messkonfigurationen) bleibt ein expliziter Opt-out.

## 6. Tests

* Codex-Reproducer unverändert als reguläre Tests übernommen (xfail entfernt): `tests/test_stat_contract_resampling_drawdown_validation.py` (2), `tests/test_stat_contract_resampling_estimand_and_pvalue.py` (2; einzige Harness-Ergänzung: Mock für den nie erreichten Fallback-Zweig), `tests/test_stat_contract_house_prior_v6.py` (4). Auf `develop@a7ffec9` alle 8 rot, mit v7 grün.
* Neu: `tests/test_resampling_statistics_contracts.py` (28): Layout gerade/ungerade, Partner gemeinsam und gleich oft, Zeilen-Bootstrap-Kompatibilität, Gegenfall-Zahlen vorher/nachher, Größe unter H0, Benennung, Survivor-Outcomes 40/39/36/35/30/20/19, Würfel-Rollen inkl. Störungsexperimente, Ridge (singulär, fast singulär, Nullraum, Marginalität, Rundung), Varianten fail-closed, Objective-Identität End-to-End.
* Angepasst (je Änderung begründet im Test): `test_house_prior_shrinkage.py`, `test_saa_resampled_stability.py`, `test_optimizer_drawdown_certification.py`, `test_optimizer_context.py`, `test_optimizer_strict_core_contract.py`, `test_optimizer_solver.py`, `test_house_first_significance.py`, `test_objective_normalization.py`.

## 7. Nicht in diesem PR (anderer Agent / offen)

* Objective-Hierarchie, harte Floors, Reachability: Reproducer `test_2026_10_18_house_first_significance_adversarial.py`, `test_2026_10_18_objective_normalization_adversarial.py`, `test_2026_10_18_pr631_goal_reachability_adversarial.py` (inkl. `test_final_certification_holdout_must_not_select_the_objective`: der Screen kann auf `_build_validation_context(context, role=CUBE_ROLE_REACHABILITY_SCREEN)` umgestellt werden – Rolle und Seed-Domäne sind vorbereitet).
* Survivor-Diagnose Ausfall ↔ Cube-Stressmerkmale (Review-Regression 14).
* Modellowner-Freigabe κ_H (siehe Kalibrierungsdokument).
