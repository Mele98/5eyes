# HOUSE-PRIOR-001 – Hausmatrix als Prior im Optimierer (Engine `saa_resampled_v6`)

Stand 2026-10-18 · Branch `feat/house-prior-v6` (gestapelt auf `fix/importance-sampling-ess`, Engine v5)
Code: `services/optimizer/house_prior.py` (neu), `solver.py` (Context-Feld, Tiebreak, `_run_resampled_solver`, Offenlegung, Engine v6), `resampling.py` (Modellbasis, Docstring), `portfolio_engine_optimizer_integration.py` (Sensitivity-Anker). `portfolio_engine.py` unverändert (7'018 Zeilen, Budget 7'100).
Tests: `tests/test_house_prior_shrinkage.py` (neu, 28 Tests); angepasst: `test_house_first_significance.py`, `test_saa_resampled_stability.py`, `test_objective_normalization.py`, `test_optimizer_drawdown_certification.py`, Golden-Docstring.
Grundlage: Design + Experiment HOUSE-PRIOR-SHRINKAGE-001 (Scratchpad `house_shrinkage_design.md`, `shrink/`; seit v7 commitgebunden unter `tools/house_prior_calibration/tuning_2026_10_18/` und `docs/planning/2026-10-18-house-prior-kappa-calibration/`), CIO-Entscheid 2026-10-18.

## 1. Befund (v5)

Der House-First-Signifikanztest (HOUSE-FIRST-SIGNIFICANCE-001) kannte nur zwei Ergebnisse: die projizierte Hausquote oder den resampelten Kandidaten (`p ≤ 5 %` auf der Zielebene). Folgen:

* **Unstetigkeit.** +1 % Zielbetrag ließ die Allokation um bis zu **20.9 pp Turnover** springen (Experiment, 5 Mandate × 41 Punkte), mit festem Seed immer noch 17.3 pp – der Sprung ist strukturell (Treppenfunktion), nicht nur Seed-Neuzug.
* **Seed-Instabilität.** Aktienquote über 6 Seeds mit σ bis **7.4 pp** (Entscheide O/H im Wechsel).
* **Falsche Alternative.** Der Kandidat wurde auf `G(w) + κ·w'Σw` optimiert, bei nahezu sicheren Zielen also auf die Min-Varianz-Ecke. Allokationen zwischen Hausquote und Ecke prüfte der Test nie.
* **Falsche Unsicherheit.** Der Bootstrap misst Monte-Carlo-Rauschen bei **fester** CMA, nicht deren Schätzfehler – den eigentlichen Grund, die Hausmeinung zu bevorzugen.

## 2. Formel

Je Bag `b` (Default `goal_shortfall`, Anker projizierbar):

    w_b = argmin_{w ∈ W}  G_b(w) + P_pref(w) + κ_H · (w − w_H)' Σ (w − w_H)
    w   = Π_W( (1/n) Σ_b w_b ),   danach bps-Rundung + _rounded_bps_with_repair

* `G` = Ziel-Fehlbetrag + Chance-Strafe (unverändert, inkl. `penalty_exempt_goal_ids`), `P_pref` = Soft-Preference.
* `w_H` = `_project_house_anchor(context, house_anchor_bps)` (bps, zulässig) – derselbe Anker wie in v5; Generate und Goal-Sensitivity übergeben ihn identisch.
* `Σ` = `context.scenario_cov_bps2 / 1e8` – dieselbe Matrix wie der bisherige Tiebreak `κ·w'Σw`, den der Prior-Term **ersetzt** (`_tiebreak_portfolio_variance`). `TIEBREAK_VARIANCE_WEIGHT` bleibt 1.0, der Prior trägt sein κ_H selbst.
* Der zulässige Bereich ist ein Polyeder (Box-Bounds inkl. Reserve/Illiquidität, Σw = 1, lineares Risikobudget) – das Bag-Mittel zulässiger Punkte ist zulässig; die Projektion ist Absicherung, die Rundung repariert `_rounded_bps_with_repair`.

**Herleitung/Lesarten.**
1. *Stetigkeit:* der Prior-Term ist stark konvex (Hesse 2κ_HΣ ≻ 0) mit eindeutigem Minimum; er übernimmt die Aufgabe des Tiebreaks (Plateaus nicht flach) und zieht nicht in eine Ecke, sondern zur Hausquote.
2. *CIO-Regel in stetiger Form:* sind die Ziele mit der Hausquote sicher erreicht (∇G = 0), ist das Optimum exakt `w_H`. Eine Abweichung mit Tracking Error 1 % wird nur genommen, wenn sie die Zielebene um mindestens 300·(1 %)² = 0.03 verbessert.
3. *Bayes/MAP:* Gauss-Prior auf die Gewichte mit Erwartung `w_H` (IC-Meinung) und Präzision 2κ_HΣ – strukturell wie der Black-Litterman-Gedanke, aber ohne μ-Views (kein BL im engeren Sinn).

**Kein Anker** (keine Hausquote, nicht projizierbar) und **Risikomass-Varianten** (min_volatility, max_drawdown, cvar_return, max_return): unverändert v5 (Tiebreak `w'Σw` bzw. Signifikanztest mit 50-bps-Materialität), Audit unter `significance`. Der Einzelwürfel-Altpfad (`SINGLE_CUBE`, nur Vergleichsmessungen) bleibt ebenfalls v5.

## 3. Offenlegung statt Schalter, Sicherheitsnetz

`resampling.house_prior` (auch in der Modellbasis/`allocation_context_hash`): `version` (`house_prior_tracking_error_v1`), `kappa`, `house_anchor_bps` (roh), `house_anchor_projected_bps`, `candidate_bps` (Bag-Mittel), `final_bps`, `tracking_error_vs_house_bps = 1e4·√((w−w_H)'Σ(w−w_H))` (Kandidat und Final), `final_prior_penalty`, `disclosure` (gepaarter Bootstrap auf dem unabhängigen Validierungswürfel: Zielebene Haus/Final, Δ, 90-%-Intervall [α- und (1−α)-Quantil], `p_value_better`, `p_value_worse`, `significantly_worse`; Test `paired_bootstrap_disclosure_goal_level_v5`), `goal_probabilities` (je Ziel und Planzeile: P Haus vs. P Final, `publish_goal_achievability` auf demselben Validierungswürfel), Validierungs-Seed/-Hash/-Pfade, `decision`, `reason`.

* `decision = house_prior`: Ergebnis = projiziertes Bag-Mittel (`identical_to_house_anchor` bzw. `not_significantly_worse_than_house`).
* `decision = house_prior_guard` (Sicherheitsnetz): Final auf der Zielebene **einseitig signifikant schlechter** als die Hausquote (`Δ < 0` und `p_worse ≤ α`, gleiches α = 5 %, B = 400) → Hausquote publiziert, Grund im Audit und im Reasoning. Bewusst unstetig, nur für Ausreißer; gegen CMA-Fehler schützt er nicht (gleiche CMA).
* Reasoning-Satz z. B.: „Hausmatrix als Anker des Optimierers (Prior, kappa = 300): Abweichung nur so weit, wie sie die Zielerreichung verbessert (Tracking Error zur Hausmatrix 0.54 %). Zielebene … Zielwahrscheinlichkeit (Validierungswürfel): Ziel X: 67.5 % statt 64.8 % mit der Hausmatrix.“ Ob das für FIDLEG-Dokumentationspflichten genügt, ist eine Rechtsfrage und hier nicht beurteilt.

> **Überholt durch Engine `saa_resampled_v7`** (`2026-10-18-resampling-statistics-contracts-v7.md`): Abschluss auf dem Prior-Context, Ridge-Metrik Σ + εI, Einheiten-Bootstrap mit nullzentrierten p-Werten, fail-closed ohne Validierungswürfel; κ-Kalibrierungspaket in `2026-10-18-house-prior-kappa-calibration.md`.

**Abschluss auf dem Aufrufer-Context (v6).** Bags und Offenlegung rechnen auf `replace(context, house_prior_weights=w_H)`. `result.context` und `result.objective_value` bleiben auf dem übergebenen Context (Objekt-Identität für Aktivierungsvalidierung/Explainability/Shadow-Vergleich; `evaluate_weights(ctx, result.weights_bps).objective_value == result.objective_value` für jeden aus denselben Inputs gebauten Context – bestehende Verträge in `test_optimizer_strict_core_contract.py`/`test_optimizer_context.py`). Der Prior-Term steht separat als `final_prior_penalty`.

`sensitivity_house_anchor_bps` liest den Anker aus `house_prior`, Fallback `significance` (v5-Allokationen, Varianten).

## 4. κ-Wahl (CIO-Entscheid: κ_H = 300, konstant, versioniert)

Aus dem Experiment (Inhalts-Seed, Test-CMA aus `test_engine_reference_mandates.py`, 5 Mandate):

| | (a) v5 | κ 30 | κ 100 | **κ 300** | κ 1000 | κ 3000 |
|---|---|---|---|---|---|---|
| Schätzfehler-Test (μ̂ = μ + Lz/√20, 150 gepaarte Welten): Δ wahre Zielebene vs. (a) | 0 | −0.0247 | −0.0336 | **−0.0355** (se 0.008) | −0.0321 | – |
| Δ wahre P(Ziel) vs. (a) | 0 | +1.16 pp | +1.16 pp | **+1.31 pp** (se 0.18) | +1.15 pp | – |
| OOS-Zielebene (κ-Raster, Summe 5 Mandate) | 0.648 | 0.627 | 0.601 | **0.602** | 0.612 | 0.643 |
| max. Sprung je 2 % (pp) | 22.2 | 5.7 | 4.0 | **4.0** | 4.2 | 2.0 |

κ 100–1000 sind innerhalb 1 se gleichwertig; 300 ist das beste Mittel aus Schätzfehler-Robustheit und OOS-Zielebene. Unter korrekter CMA war (c) in 0 von 500 Fällen schlechter als die Hausmatrix, unter CMA-Schätzfehler in 6 von 150 Welten (unvermeidbarer Preis jeder Abweichung bei falschem μ). Der reine Optimierer verliert unter Schätzfehler −2.21 pp P(Ziel).

## 5. Messungen der Implementierung

Referenzmandate A/B/C/D/E (CMA/Hausmatrizen 1:1 aus `test_engine_reference_mandates.py`, Zieldaten kalenderjahr-relativ mit festem Monat/Tag), Produktions-Resampling (40 Bags × 500 Pfade, 2'000 Hauptpfade, B = 400).

**Sprung bei Zielbetrag 0.80…1.20, 2-%-Schritte, Inhalts-Seed (max. Turnover zwischen Nachbarn, pp):**

| Mandat | v5 | v6 |
|---|---|---|
| A Ausgewogen, Sparen | 15.64 | 3.22 |
| B Konservativ, Entnahme | – | 0.31 |
| C Wachstum, Entnahme | 13.79 | 1.43 |
| D Wachstum, Sparen | 16.87 | 3.86 |
| E Ausgewogen, Entnahme | 19.87 | 0.59 |

**1-%-Schritte an den v5-Kipppunkten (Testfall):** D 0.90→0.91→0.92: v5 16.87/0.00, v6 0.52/0.50; E 0.96→0.98: v5 1.83/19.13, v6 0.04/0.00; A 1.02→1.04: v5 15.64/0.00, v6 2.22/1.00; D mit festem Seed (CRN): v5 17.14, v6 ≤ 1.04.

**Seed-Stabilität (6 Seeds, σ Aktienquote in pp):** D 0.92: v5 6.21 (H/H/H/O/H/O) → v6 0.13; A 1.03: v5 6.57 (O/O/H/O/H/H) → v6 0.09; E 0.97: v5 6.41 → v6 0.00; D 0.91: v5 0.59 → v6 0.13.

**Golden-Snapshots (6 CH-Mandate):** unter `OPENBLAS_CORETYPE=Haswell` und `=Nehalem` (Threads = 1) neu erzeugt – **byte-identisch** zu den v5-Fixtures, keine Datei geändert. Fachlich erwartet: alle Ziele mit der Hausquote sicher erreicht → Optimum = projizierte Hausquote (TE 0, `identical_to_house_anchor`). Score 3 0/9500/0/300/200, Score 5 (alle drei Präferenzen) 4800/3500/1000/500/200, Score 7 6800/1600/800/600/200, Score 9 7900/800/700/400/200.

**Laufzeit** (`elapsed_ms`, solo, diese Maschine):

| Fall | v5 | v6 |
|---|---|---|
| Stage-8-Fundament (Verdict-Eingang, 2 Läufe) | 2'382 / 2'442 | 3'484 / 3'523 |
| B 1.08 | 9'728 | 10'577 |
| B 1.12 | 14'514 | 10'102 |
| A 1.20 | 8'093 | 8'344 |

Das Stage-8-Laufzeitkriterium (rot > 15'000, gelb > 8'000) hält v6 auf dem Fundament klar ein; das Gesamtverdikt bleibt wie in v5 gelb, aber wegen der Drift zur Hausmatrix (v5 1'299 → v6 1'218 bps), nicht wegen der Zeit. Die Mandate B/A liegen in beiden Versionen im gelben Bereich (vorbestehend; v5 B 1.12 knapp unter rot). Ein Warmstart der Bags an `w_H` wurde gemessen und **nicht** übernommen: er änderte in keinem Bag das Ergebnis (gleiche Minima), kostete aber +17–23 % SLSQP-Iterationen (6 Bags, D 1.0, κ 30/300/3000).

## 6. Grenzen und offene Punkte

* **Nur Mittelwert-Schätzfehler getestet** (T = 20 Jahre, 10 Welten je Zelle); keine Σ-, Schiefe- oder Tail-Fehler. Die Rangfolge (c) > Haus ≈ v5 ≫ reiner Optimierer ist mit ~4 se klar, die Feinkalibrierung von κ_H (100 vs. 300 vs. 1000) nicht.
* **Test-CMA, nicht Produktions-CMA**; synthetische Ein-Ziel-Mandate. Mehrziel-Mandate und Produktions-CMA sind nicht nachgemessen.
* **Risikomass-Varianten: Kalibrierung offen** (Phase 2: `risk_measure(w) + Chance + κ_H,var·TE²`, κ_H,var über denselben Schätzfehler-Test, danach Materialitätsschwelle ablösen).
* **SLSQP findet unter dem Prior nicht immer das Bag-Minimum.** Für exakte Minimierer wäre TE(κ) nicht steigend; gemessen D 1.0 (40 Bags): TE 92/47/103/49/2 bps bei κ 3/30/300/3000/30000. In 4 von 4 untersuchten Bags hatte die κ-300-Lösung auch unter κ 30 den kleineren Zielwert als die κ-30-Lösung – die Zielebene (Chance-Strafe auf Pfad-Indikatoren) ist nicht glatt, Finite-Differenzen-SLSQP bleibt in lokalen Punkten stehen. Vorbestehend (Multi-Start ist unverändert); der Test prüft deshalb nur die Grenzfälle (κ → ∞ ⇒ Hausquote). Kandidat für einen eigenen Befund (glatte Surrogat-Strafe oder analytischer Gradient).
* Das Sicherheitsnetz bewertet unter derselben CMA wie der Optimierer und schützt nicht gegen CMA-Fehler.
* `allocation_context_hash` ändert sich für neue Default-Allokationen (Modellbasis `house_prior` statt `significance`). Bestehende Allokationen behalten ihren v5-Audit; der Sensitivity-Anker wird weiter gelesen.
