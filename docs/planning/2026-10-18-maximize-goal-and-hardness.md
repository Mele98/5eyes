# MAXIMIZE-GOAL-001 · GOAL-HARDNESS-DEFAULT-001 · GOAL-HIERARCHY-001 (Engine `saa_resampled_v7`)

Stand 2026-10-19 · Branch `feat/maximize-goal-and-hardness` (auf `develop` e07bde3)
Code: `services/optimizer/objective.py` (Maximierungsterm, Haertegrad, Stufe-1-Niveau, Surrogat), `solver.py` (Stufe 1/2 in `_select_cube_candidate`, Engine v7, Audit), `objective_contract.py` (`ObjectiveContractV2`), `goal_reachability.py` (nur noch Offenlegung, eigener Wuerfel), `goal_liabilities.py` (Docstrings), `config.py` (Default `hardness`), `resampling.py` (Modellbasis), `drawdown_certification.py` (Ausnahme entfernt). `portfolio_engine.py` unveraendert.
Tests: `tests/test_maximize_goal_and_hardness.py` (neu, 24 Tests; 21 davon rot auf develop), angepasste Bestandstests (siehe Abschnitt 9).
Grundlage: Variablen-Audit 2026-10-18 (Befunde A, B), CIO-Entscheid 2026-10-18 nach Codex-Review (`docs/audits/2026-10-18-objective-normalization-pr626-review.md`, `...-core-optimizer-pr631-reachability-and-validation-review.md` auf `codex/asset-allocation-stochastic-core`).

## 1. Befunde (verifiziert auf develop, Reproducer in den Tests)

Testmandat: Hausmatrix "Wachstum" (Aktien 45–70 %, Ziel 60/30/5/3/2), Score 75, CHF 500'000, keine Cashflows, Test-CMA aus `test_engine_input_sensitivity`, Produktions-Resampling (40 Bags × 500 Pfade), Seed 11.

**A – "Vermoegen maximieren" wirkt nicht.** `shortfall_squared_per_path` gab fuer `target_kind == "maximize"` 0 zurueck, die Chance-Strafe nimmt Maximierung aus. Ergebnis develop: Maximierung 25 J = keine Ziele = Hausquote 6000/3000/500/300/200 (TE 0, identisch auch bei 10 J und Hausmatrix "Ausgewogen").

**B – Haertegrad wirkungslos.** Default `OPTIMIZER_GOAL_WEIGHTING=equal` → h_g = 1; die Chance-Strafe gilt fuer hart und primaer gleich (gleiches tau, gleiches Gewicht). Develop, Vermoegensziel CHF 0.7 Mio: opportunistisch/primaer/hart 5993/3000/508/299/200 ≈ 5993/3000/508/299/200 ≈ 5992/3000/508/300/200 (TE 1.1/1.1/1.2 bps). Bei CHF 1.6 Mio primaer 6880/2030/852 vs. hart 6897/2025/846 – Unterschied nur Seed-Rauschen.

**C – (Codex) Reachability-Screen loescht Ziele.** Bis v6 nahm `penalty_exempt_goal_ids` ein auf einer endlichen Pruefmenge "unerreichbares" hartes/primaeres Ziel ganz aus Fehlbetrag und Strafe (CHF 0 und CHF 900 gegen CHF 1'000 waren gleich gut), auf dem Validierungswuerfel, der danach zertifiziert.

## 2. A – Maximierung als Log-Wachstumsterm

### Formel

    M_g(w) = − λ_M · h_g · g_g · T · E_n[ log(1 + r_n(w)) ]

`r_n` = cashflow-neutrale annualisierte Portfolio-Rendite (TWR) auf Pfad n (dieselbe Groesse wie beim Renditeziel), `T` = Bewertungshorizont, `g_g` = Rang-Gewicht (weight_bps/1e4), `h_g` = Haertegrad-Gewicht, fuer Maximierung auf ≤ 1 gedeckelt, λ_M = `MAXIMIZE_GROWTH_WEIGHT` = 1.0. Der Term steht im Primaerterm L(w) (Stufe 2), keine Chance-Strafe, kein Stufe-1-Schutz (kein Zielwert).

### Herleitung

1. *Was heisst "maximieren" ohne Zielwert?* Das Langfrist-Wachstum und der Median des Endvermoegens: fuer lognormales W_T ist median(W_T) = W0·exp(E log(W_T/W0)); E log maximieren heisst den Median maximieren (Kelly 1956, Latané 1959, Breiman 1961).
2. *Risikoavers:* E log(1+r) ≈ μ − σ²/2 (Jensen): Streuung kostet; ein risiko-neutraler Term E[W_T] wuerde in die renditestaerkste Ecke treiben. Test `test_maximize_term_is_risk_averse_for_equal_arithmetic_mean`.
3. *Skalenfrei:* invariant gegen W0 und Waehrung (Test), wie die normierten Zielterme.
4. *Cashflow-neutral (TWR):* Entnahmen sind kein "negatives Wachstum", kein log negativer Vermoegen.
5. *Normierung λ_M = 1:* die uebrigen Zielterme messen in relativem Endvermoegen (Fehlbetrag/W0, Zielvolumen/W0). d log W_T = dW_T/W_T ist bei W_T = W0 genau dieselbe Einheit. 1.0 ist die natuerliche Einheit, keine Kalibrierung.
6. *Wie weit weicht das vom Haus ab?* Erste-Ordnung-Bedingung mit dem Haus-Prior κ_H(w−w_H)'Σ(w−w_H): T·∇g = 2κ_H Σ Δw ⇒ TE* ≈ T/(2κ_H) · √(∇g'Σ⁻¹∇g). Linear im Horizont; gemessen TE 95 bps (25 J) vs. 39 bps (10 J), Verhaeltnis 2.4 ≈ 25/10. Die Eignung (Baender, Risikobudget) bleibt harte Restriktion.

### Alternativen (verworfen bzw. offen)

| Variante | Problem |
|---|---|
| E[W_T]/W0 (risiko-neutral) | ignoriert Streuung, treibt in die μ-Ecke – nicht konservativ |
| CRRA mit γ > 1 | γ waere eine erfundene Zahl; die Risikoaversion steckt schon in der Hausmatrix-Zeile. Bei γ = γ_Haus waere die Wirkung 0 |
| Maximum des P25 / CVaR25 | de-riskt fuer T < ~10 J (P25) bzw. < ~34 J (CVaR25) – "Maximierung" wuerde Aktien abbauen |
| Renditeziel = Haus-μ + Δ | Δ waere erfunden |
| Ambitioniertes Vermoegensziel | Zielwert erfunden, Chance-Strafe auf ein bewusst halb unerreichbares Ziel |

Log ist unter den gleichwertigen die konservativste Formulierung, die "maximieren" noch erfuellt (risikoavers, beschraenkt durch Eignung und Haus-Prior).

### Wirkung (vorher develop → nachher v7)

| Mandat | Aktien/Obl./Immo/Alt./Liq. (bps) | TE | μ / σ (bps) |
|---|---|---|---|
| Wachstum 25 J | 6000/3000/500/300/200 → 6262/2044/1321/173/200 | 0 → 95 | 495/923 → 525/991 |
| Wachstum 10 J | 6000/3000/500/300/200 → 6106/2608/837/249/200 | 0 → 39 | 495/923 → 507/950 |
| Ausgewogen 25 J | 4082/4592/510/306/510 → 4242/4768/690/0/300 | 0 → 44 | 407/638 → 418/660 |

Immobilien (4.5 % / 8.2 %) haben in dieser CMA das beste Wachstum je Tracking-Error-Einheit; Gold (3 %) wird abgebaut.

## 3. B – Haertegrad wirkt standardmaessig

### Bestehende Felder

`hardness` (Hart/Primär/Opportunistisch; Erfassungsmaske, Default "Primär", im Monolith Rang 1 → Hart), `weight_bps` (Rang-Gewicht 10000/5000/2500…, Wichtigkeit), `success_probability_min_x100` (tau, explizites Maskenfeld; das Schema fuellt 8000/5000 ein, wenn leer), `OPTIMIZER_GOAL_WEIGHTING` (`equal` | `hardness`, OD-1-Gewichte 10/1/0.2).

### Fruehere Entscheide

OD-1 (2026-05-05, vom User bestaetigt): Haertegrad-Gewichte 10/1/0.2. ADR-011 Entscheid 2 (2026-06-17, PR #274/#275): Default `equal` (3eyes "Alle Ziele sind gleich wichtig – Mittelung"), Haertegrad als Opt-in. Damals gab es weder Haus-Prior noch Zielhierarchie.

### CIO-Entscheid 2026-10-18 und Begruendung der Default-Aenderung

1. Die Maske bietet den Haertegrad an; eine Wahl ohne jede Wirkung ist fuer Kunde und Berater irrefuehrend (Befund B).
2. Die "Mittelung" der Ziele bleibt: Wichtigkeit zwischen Zielen ist der Rang (`weight_bps`). Der Haertegrad regelt jetzt etwas anderes – wie stark ein Ziel gegen die Hausmatrix-Abweichung geschuetzt wird.
3. Versionierte Konstanten: `config.DEFAULT_GOAL_WEIGHTING_MODE = "hardness"`, `objective.GOAL_HARDNESS_POLICY_VERSION = "hardness_scales_shortfall_and_protection_v1"`, OD-1-Gewichte unveraendert; alles im `ObjectiveContractV2`-Hash. Opt-out `OPTIMIZER_GOAL_WEIGHTING=equal` bleibt.

### Umsetzung

* Gewichte 10/1/0.2 auf den **Fehlbetrag** L_g (wie der bisherige Opt-in-Modus).
* Die Chance-Strafe bleibt **ungewichtet** (weiche Strafe). Gemessen (Vermoegensziel 1.0/1.2/1.4 Mio × 3 Seeds, ohne Hierarchie): Gewichtung auch der Strafe aenderte die Zielwahrscheinlichkeit um ≤ 0.4 pp (Aktien bis 3.2 pp), kostete aber +37 % SLSQP-Iterationen (1.6 Mio hart: 5'500 statt 4'010).
* **Zielhierarchie** (Abschnitt 4): hart und primaer sind Stufe 1, opportunistisch Stufe 2; ist ein hartes Ziel geschuetzt, wird die Erosionstoleranz durch h_hart = 10 geteilt.
* tau nach Haertegrad (z. B. hart 90 %) **verworfen**: tau ist ein explizites Maskenfeld, das das Schema beim Speichern mit 80 % fuellt; ein Default liesse sich von einer bewussten Wahl nicht unterscheiden, und 90 % waere erfunden.

### Wirkung (develop → v7, Seed 11)

| Vermoegensziel 25 J | opportunistisch | primaer | hart |
|---|---|---|---|
| CHF 0.7 Mio, P(Haus) 96.4 % | TE 1 → 0; P 96.4 % | TE 1 → 1; P 96.4 % | TE 1 → **175 bps**; Aktien 59.9 → **48.9 %**, σ 9.2 → **7.7 %**, P 96.4 → **97.2 %** |
| CHF 1.2 Mio, P(Haus) 71.8 % | 5911/2900/711 (TE 18) → 5982/2979/544 (TE 4) | 6097/2404/1117 (TE 60) → 6145/2339/1143 (TE 67), P 74.2 % | 6150/2398/1074 (TE 62) → 5955/2248/1499 (TE 82), P 74.2 → 75.0 % |
| CHF 1.6 Mio, P(Haus) 44.2 % | 5869/2500/1219 (TE 55) → 5972/2885/663 (TE 13) | 6880/2030/852 → unveraendert (TE 154) | 6897/2025/846 → 6338/2019/1427 (TE 111), P 52.2 → 52.0 % |

Lesart: ein hartes Ziel, das mit der Hausquote fast sicher ist, wird durch Risikoabbau sicherer (das ist der "kundengerechte" Haupteffekt); ein opportunistisches Ziel zieht kaum noch (Gewicht 0.2, keine Stufe 1); bei ambitionierten Zielen schuetzen hart und primaer gleichermassen (beide Stufe 1), hart verlagert dabei von Aktien zu Immobilien (tiefere Streuung bei gleicher Zielebene).

## 4. Zielhierarchie (GOAL-HIERARCHY-001, Codex OBJECTIVE-TIEBREAK-NOT-LEXICOGRAPHIC-001)

Je Szenario-Wuerfel (jeder Bag):

    Stufe 1:  G1(w) = Σ_{g hart/primaer, im Horizont} ( h_g·g_g·L_g(w) + C_g(w) ),   G1* = min_w G1(w)
    Stufe 2:  min_w F(w)  u. d. N.  G1(w) ≤ G1* + ε,   F = volle Zielfunktion (inkl. Maximierung, Soft-Preference, Haus-Prior κ_H = 300)
    ε = z · SE( G1(w_H) − G1(w1*) ) / h_max + 1e-9,   z = 1.645 (einseitig 5 %)

* **Dieselben Terme** wie in F – kein zweites Zielmass.
* **ε statistisch, nicht erfunden:** gepaarter Monte-Carlo-Standardfehler der Zielebenen-Differenz zwischen Hausquote und Stufe-1-Optimum auf demselben Wuerfel (Fehlbetragsteil exakt je Pfad, Strafteil per Delta-Methode dC/dp = −V²). Eine Erosion innerhalb dieses Rauschens ist nicht als Verschlechterung belegbar und bleibt dem Haus-Prior; alles darueber kann der Prior nicht mehr "auskaufen". Gleiches α wie die Hausmatrix-Offenlegung. Ohne Haus-Anker: SE von G1 im Stufe-1-Optimum.
* **Haertegrad:** h_max = 10, sobald ein hartes Ziel geschuetzt ist → nur ein Zehntel des Rauschens als Erosion.
* **Stufe-1-Suche:** exaktes G1 an allen Multi-Start-Punkten und der Hausquote, dann ein SLSQP-Lauf (≤ 25 Iterationen) auf einer glatten Naeherung (Erfolgsindikator logistisch geglaettet, Breite 2 % des Zielvolumens), Ergebnis wieder exakt bewertet. Entschieden wird nur mit dem exakten G1. G1* ist das beste **gefundene** Minimum (kein globaler Beweis; die Schranke ist eher zu weit). Ist G1 an einem Startpunkt 0, entfaellt die Suche (Golden-Mandate).
* **Stufe 2 "lazy":** erfuellt das Optimum von F die Schranke, ist es auch das Optimum unter der Schranke. Sonst wird auf der Strecke w1* → w2 (konvexe Kombination zulaessiger Punkte, 11 Punkte) der Punkt mit kleinstem F gewaehlt, der die Schranke **exakt** einhaelt. Ein SLSQP-Lauf mit G1 als Nebenbedingung scheiterte gemessen an der stueckweise konstanten Strafe und fiel in die DE-Suche (+5 s je bindendem Bag).
* **Audit je Bag** (`resampling.bags[].goal_protection`): geschuetzte Ziele, G1*, SE, Basis, z, h_max, ε, Schranke, finales G1, Stufe-1-Loesungen, `constraint_pass`, w1*.
* **Garantie und Grenze:** die Hierarchie gilt je Bag exakt. Das Bag-Mittel und die Projektion (Resampling-Zone, nicht Teil dieses PR) koennen sie nicht formal erhalten; der Haus-Prior-Guard bleibt das Sicherheitsnetz.
* **Nur Default `goal_shortfall`.** Risikomass-Varianten: Phase 2 (Codex-Befund 4, eigener PR).

Test `test_house_prior_cannot_buy_erosion_of_a_protected_goal`: mit κ_H = 1e6 waere ohne Hierarchie die Hausquote das Ergebnis; mit Hierarchie liegt G1 ≤ G1* + ε, die Hausquote verletzt die Schranke.

## 5. Reachability-Screen nur noch Offenlegung (Codex GOAL-SCREEN-*)

* `penalty_exempt_goal_ids` und die Parameter `excluded_goal_ids` / `penalty_exempt_goal_ids` sind entfernt – kein Weg, ein Ziel auszunehmen (OBJECTIVE-ERASURE).
* Eigener Screening-Wuerfel (`SCREENING_SEED_OFFSET = 2_000_003`), nie der Validierungswuerfel (HOLDOUT-LEAKAGE).
* Status `not_found_reachable_in_screen_set` statt "unerreichbar" (FEASIBLE-SET-PROOF), Beraterhinweis "Ziel mit dem Kunden ueberpruefen … es wird nicht ausgenommen".
* Codex-Reproducer als regulaere Tests (ohne xfail): `test_codex_unreachable_label_must_not_erase_shortfall_ranking`, `..._finite_candidate_screen_...`, `..._final_certification_holdout_...` (auf develop rot, jetzt gruen). Aufrufe nur dort angepasst, wo die Schnittstelle absichtlich entfiel (Parameter existiert nicht mehr; Screening-Wuerfel statt Validierungswuerfel).

**Folge und Herabstufung (GOAL-HIERARCHY-002, CIO-Review #650):** ein auf der Pruefmenge nicht gefundenes Ziel (Default: obere 95-%-Grenze < tau/2) bleibt mit vollem Fehlbetrag in der Zielfunktion (Codex "CHF 0 ≠ CHF 900"), gehoert aber unabhaengig vom Haertegrad **nicht zur Stufe 1** (`solver._stage1_liabilities`): es wird nachrangig verfolgt und kann erreichbare harte/primaere Ziele nicht ueber deren Schranke hinaus verdraengen. Reasoning: "Ziel X ist mit keiner der geprueften zulaessigen Allokationen mit der Mindestsicherheit erreichbar (…; endliche Pruefmenge, kein Unmoeglichkeitsnachweis); es wird nachrangig verfolgt und verdraengt keine erreichbaren Ziele." Audit je Bag: `goal_protection.demoted_goal_ids`. Siehe Abschnitt 10.

## 6. ObjectiveContractV2

`ObjectiveContractV2(ObjectiveContractV1)` bindet neben den Modi alle Koeffizienten, Scopes und Policies: Haertegrad-Policy und -Gewichte, Hierarchie-Policy/-Scope, geschuetzte Haertegrade, z, numerische Toleranz, Maximierungs-Policy und λ_M, Chance-Policy und -Gewicht, Tiebreak-Policy und -Gewicht, Haus-Prior-Version und κ_H, Soft-Preference-Policy und λ, Reachability-Policy, Normierung. Fehlende Felder werden mit den implementierten Werten belegt; ein explizit anderer Wert ist fail-closed unzulaessig (kein stiller Replay mit anderer Mathematik). Hash ueber alle Felder; Nachweis in `resampling.objective_contract` und der Modellbasis. V1-Konsumenten bleiben kompatibel (Unterklasse).

## 7. Golden-Snapshots

Unter `OPENBLAS_CORETYPE=Haswell` und `=Nehalem` (Threads = 1) neu erzeugt, beide byte-identisch:

| Fixture | Ergebnis |
|---|---|
| Score 3, Score 5 (alle drei Praeferenzen) | unveraendert |
| Score 7 | 6800/1600/800/600/200 → 6792/1609/797/602/200 (529/1081 → 528/1080 bps) |
| Score 9 | 7900/800/700/400/200 → 7807/916/707/370/200 (577/1245 → 573/1230 bps, Risikoanteil 69.2 → 68.5 %) |

Begruendung: die Golden-Mandate haben eine **harte** Pension. In einzelnen Bags hat die Hausquote Fehlbetragspfade dieser Pension, die mehr als ein Zehntel des Rauschens ausmachen; die Allokation wird dort geringfuegig defensiver. Ohne Haertegrad-Unterschied (Score 3/5) bleibt alles gleich.

## 8. Laufzeit (diese Maschine, solo, Threads = 1)

| Fall | develop (v6) | v7 |
|---|---|---|
| Stage-8-Fundament (`elapsed_ms`, solo) | 5'542 / 5'536 | erste Fassung 12'817 / 12'761; nach CIO-Review **4'475 / 4'543** |
| Zwischenstaende (Fundament) | – | Herabstufung 13'363 → + Zielfunktions-Skalierung 9'639 → + 2 Starts bei Herabstufung 4'475 |
| Vermoegensziel 1.2 Mio hart / primaer (Resampling, 500 Pfade; nicht solo, nur Groessenordnung) | 10.1 s / 9.8 s | 7.4 s / 7.6 s |

Nach dem CIO-Review liegt der Fundament-Lauf im gruenen Band (< 8'000 ms), mit Reserve fuer #649 (+~0.9 s). Zwei Massnahmen: (1) STAGE2-OBJECTIVE-SCALE-001 – SLSQP sieht f/s mit s = max(1, |f| am besten Startpunkt): gleiches argmin, ftol wird relativ; fuer |f| ≤ 1 (alle Golden-Mandate) s = 1, bitidentisch. Mandate mit grossen Fehlbetraegen koennen sich im Rahmen der Solver-Toleranz verschieben (Vermoegensziel 1.6 Mio primaer: 6880/2030/852 → 6911/2032/836). (2) Mit herabgestuften Zielen laeuft Stufe 2 nur von den 2 besten Startpunkten (`GOAL_DEMOTED_STAGE2_STARTS`): dort bestimmt die Stufe-1-Schranke das Ergebnis (Streckensuche in 39 von 40 Bags), der Multi-Start liefert nur die Richtung; Fundament-Allokation 6178 → 6184 bps Aktien. Iterationen 2'837 → 796. Verworfen: Stufe-1-Schranke als Dauer-Nebenbedingung (44.5 s), zwei Stufe-1-Starts (24 s).

## 9. Angepasste Bestandstests

* Engine-Version v6 → v7 (`test_house_prior_shrinkage`, `test_saa_resampled_stability`).
* Default-Gewichtung: `test_objective_equal_weighting_is_default` → `test_objective_hardness_weighting_is_default` + `test_objective_equal_opt_out_ignores_hardness`; Typo-Test-Positivkontrollen (Default-Ratio 50, explizit `equal` 1); Tiebreak-Test (opportunistisches Ziel × 0.2).
* Reachability (`test_importance_sampling_ess`, `test_saa_resampled_stability`): Ausnahme → Offenlegung, Parameter entfallen, neue Hinweistexte; "Variante nie riskanter als Default" (CIO-Entscheid b, nur durch die Ausnahme erfuellt) → "Variante auf ihrem eigenen Mass mindestens so gut wie der Default".
* κ-Grenzfall: κ → ∞ zieht bis an die Zielschutz-Schranke, nicht mehr bis auf die Hausquote.

## 10. Nachtrag CIO-Review #650 (2026-10-19)

**Fundament-Mandat** (develop → v7, solo):

| | develop | v7 erste Fassung | v7 nach Review |
|---|---|---|---|
| Allokation | 6494/1037/1918/300/251 | 7343/1008/1098/300/251 | 6184/1388/1877/300/251 |
| publiziert P(Einkommensbruecke) | 74.4 % (eigener Wuerfel) | 72.3 % | 73.1 % |
| publiziert P(Familienvermoegen) | 12.6 % | 15.7 % | 11.5 % |

Die publizierten Zahlen stammen von verschiedenen Validierungswuerfeln (die Engine-Version geht in den Inhalts-Seed). Vergleich auf DEMSELBEN unabhaengigen Wuerfel mit 20'000 Pfaden: P(Einkommensbruecke) develop-Allokation 73.41 %, v7 73.25 % (−0.16 pp; mit z = 0 statt 1.645: 73.27 %, d. h. nicht die Toleranz, sondern das Stufe-1-Mass). Stufe-1-Niveau G1 (Fehlbetrag + weiche Strafe der erreichbaren Ziele) auf dem Trainingswuerfel: develop-Allokation 0.1175, v7 0.1172 (besser). Stufe 1 schuetzt die Zielebene (Fehlbetragshoehe + weiche Strafe), nicht die Wahrscheinlichkeit allein; eine reine Wahrscheinlichkeits-Untergrenze ist Codex-Befund 2 (Phase 2). Ergebnis: P(Einkommensbruecke) liegt auf gleichem Wuerfel 0.16 pp unter der develop-Allokation (Standardfehler der gepaarten Differenz bei 20'000 Pfaden ~0.1–0.2 pp), die erste Fassung lag 2.1 pp darunter.

**Unerreichbares Ziel CHF 5 Mio allein** (hart oder primaer, keine weiteren Ziele): 7000/2000/800/0/200, unveraendert gegenueber der ersten Fassung. Ohne erreichbare Ziele gibt es nichts zu verdraengen; der volle Fehlbetrag zieht bis an die Bandobergrenze (develop: Hausquote durch Ausnahme). Wenn der CIO hier die Hausquote will, braucht es eine eigene Regel (z. B. herabgestufte Ziele mit opportunistischem Gewicht) – nicht umgesetzt, weil "voller Fehlbetrag" verlangt war.

**Goldens:** nach dem Review byte-identisch zur ersten v7-Fassung (Haswell = Nehalem). Score 3/5 = develop. Score 7 (−8 bps Aktien) und Score 9 (−93 bps) einzeln geprueft: mit Haertegrad-Teiler 1 statt 10 (Experiment) sind beide exakt die develop-Fixtures – die Aenderung kommt ausschliesslich von der harten Pension (Toleranz ein Zehntel des Rauschens), keine herabgestuften Ziele, keine Skalierungswirkung (|f| ≤ 1).

**Varianten-Test (Runde 1, in Runde 2 behoben – kein xfail mehr):** `test_risk_variants_improve_their_own_measure_on_the_foundation` war kurzzeitig `xfail(strict=True)`: der Default ist auf dem Fundament defensiver (Aktien 61.8 %, Vola 10.2 %), `min_volatility` hat noch keine Hierarchie/Herabstufung und wird von den Strafen nicht erreichbarer Ziele getrieben (74.5 %, 11.6 %). Offener Defekt fuer Phase 2 (Codex-Befund 4), bewusst sichtbar statt abgeschwaecht.

**Engine-Version:** bleibt bis zum Merge von #649 `saa_resampled_v7`; nach dessen Merge wird develop eingemergt und die Version `saa_resampled_v8`.

### Runde 2 (CIO-Entscheide 2026-10-19): DEMOTED-GOAL-WEIGHT-001

Herabgestufte Ziele (Screen: auf der Pruefmenge nicht erreichbar; Default: obere Grenze < tau/2, Varianten: < tau) zaehlen unabhaengig vom erfassten Haertegrad wie ein Wunschziel: Gewicht `DEMOTED_GOAL_WEIGHT` = 0.2 auf Fehlbetrag UND Chance-Strafe, in jedem Modus (auch Risikomass-Varianten), nicht Stufe 1. Markierung `GoalLiability.demoted` (gesetzt in `build_optimizer_context`, erfasster Haertegrad bleibt fuer die Anzeige). Reasoning: "… es wird als nachrangiges Wunschziel verfolgt und verdraengt keine erreichbaren Ziele".

Messung: das Gewicht 0.2 allein genuegte NICHT – Vermoegensziel CHF 5 Mio bei CHF 0.5 Mio (Z/W0 = 10) blieb bei 6947/2000/853/0/200 (Fehlbetragsterm ~40, ×0.2 ~8 gegen einen Prior-Term ~0.1). Ursache ist die Groesse des Ziels, nicht seine Bedeutung. Darum zusaetzlich das Volumen herabgestufter Ziele auf W0 gedeckelt (Faktor 1/max(1, (Z/W0)²) auf beide Terme) – Option (b) aus OBJECTIVE-NORMALIZATION-001, hier nur fuer herabgestufte Ziele; monoton, CHF 0 bleibt schlechter als CHF 900; fuer nicht herabgestufte Ziele Faktor 1 (bitidentisch). **Diese Deckelung geht ueber den Wortlaut des CIO-Entscheids hinaus und ist das Mittel, sein erklaertes Ziel ("Haus-Prior dominiert") zu erreichen – bitte bestaetigen.** Policy `screen_not_found_demoted_wish_weight_v2`, `demoted_goal_weight` im ObjectiveContractV2.

| Fall | erste Fassung | Runde 1 | Runde 2 |
|---|---|---|---|
| nur unerreichbares Ziel CHF 5 Mio (hart/primaer) | 7000/2000/800/0/200 | 7000/2000/800/0/200 | **6014/2958/534/294/200** (TE 4 bps, Hausquote 6000/3000/500/300/200) |
| Fundament, Default | 7343/1008/1098/300/251 | 6184/1388/1877/300/251 | 6161/1431/1857/300/251 |
| Fundament, P(Einkommensbruecke), gleicher 20k-Wuerfel (develop-Allokation 73.41 %) | – | 73.25 % | 73.21 % |
| Fundament min_volatility (Aktien) | – | 74.5 % (riskanter als Default) | **60.0 %** (≤ Default 61.6 %) |
| Fundament max_drawdown (Aktien) | – | – | 60.0 % |
| Stage-8-Fundament solo | 12.8 s | 4.5 s | **3.9 s** |

`test_risk_variants_improve_their_own_measure_on_the_foundation` ist wieder ein regulaerer Test (kein xfail) und gruen: min_volatility nicht volatiler als der Default, max_drawdown mit kleinerem Drawdown. Goldens unveraendert (keine herabgestuften Ziele, Haswell = Nehalem).

### Runde 3: Merge mit #649 (Statistik-Vertraege), Engine `saa_resampled_v8`

develop 854ee8e (#649 v7 Statistik, #641, #645, #646, #647, #648) eingemergt; Konflikte nur in Kommentaren (Versionshistorie in `solver.py`, Golden-Docstring). Beide Absichten erhalten: Paar-Bootstrap, Shift-p-Wert, getrennte Selection/Final-Cubes, Survivor-Schwelle 90 %, Fail-closed, Ridge-Prior, Prior-Context (#649) und Hierarchie, Herabstufung, Maximize, ContractV2, Skalierung (dieser PR). Anpassung: der ContractV2-Nachweis im Resampling-Audit wird defensiv gebildet (`_contract_evidence`), weil #649-Tests Vertragsattrappen ohne `as_evidence` verwenden. Version `saa_resampled_v8`.

Goldens (Haswell = Nehalem): Score 3/5 = develop; Score 7 6800/1600/800/600/200 → 6734/1674/810/582/200 (529/1081 → 526/1071 bps), Score 9 7900/800/700/400/200 → 7799/959/670/372/200 (577/1245 → 572/1227 bps). Ursache je einzeln geprueft: mit Haertegrad-Teiler 1 statt 10 ergeben beide exakt die develop-Fixtures (harte Pension).

Fundament (develop 854ee8e → v8): 6491/1051/1907/300/251 → 6184/1501/1764/300/251; Stage-8 solo 6.4 s → 4.7 / 4.7 s. Gleicher unabhaengiger 20k-Wuerfel: P(Einkommensbruecke) develop-Allokation 73.19 %, v8 72.90 % (−0.29 pp, ~2 Standardfehler der gepaarten Differenz – etwas mehr als die in Runde 2 akzeptierten −0.16 pp); P(Familienvermoegen) 13.1 → 11.3 %, P(Mindestrendite) 59.4 → 57.1 %. Publiziert (je eigener Wuerfel): Einkommensbruecke 73.4 → 73.9 %.

## 11. Offen (Phase 2, eigener PR)

1. Codex OBJECTIVE-TIEBREAK (1): Varianz/Prior gegen **opportunistische** Ziele ist weiterhin additiv (opportunistisch = Stufe 2 by design).
2. Codex CHANCE-PENALTY-NOT-CONSTRAINT (2): echte Wahrscheinlichkeits-Untergrenzen (WilsonLB ≥ tau) statt weicher Strafe, in allen Modi; bis dahin heisst die Strafe im Code "weiche Strafe" – UI/PDF-Wortlaut pruefen.
3. Codex (4): Goal-Preservation-Gate fuer die Risikomass-Varianten (`_significance_vs_house_anchor` liegt in der Zone des Statistik-Agenten).
4. κ_H = 300 wurde ohne Hierarchie kalibriert; der Schaetzfehler-Test (HOUSE-PRIOR-001 Abschnitt 4) ist mit Hierarchie nicht nachgemessen.
5. Hart vs. Wahrscheinlichkeit: Stufe 1 schuetzt die Zielebene (Fehlbetrag + weiche Strafe), nicht die Wahrscheinlichkeit allein; bei ambitionierten Zielen kann "hart" die Streuung senken, ohne P zu erhoehen (1.6 Mio: 52.2 → 52.0 %).
6. Zielverzicht als expliziter Kundenentscheid (Ziel-ID, Grund, Zeitpunkt, Widerruf) statt Ausnahme.

## 12. Nachtrag Codex-Befund zu #650: zertifizierte Unerreichbarkeit (Engine `saa_resampled_v9`)

**Befund (Codex, docs/audits/2026-10-19-maximize-goal-hardness-pr650-current-review.md, Abschnitt 4):** `_demoted_goal_ids()` uebernahm alle `not_found_reachable_goal_ids` des endlichen Screens. Ein hartes Ziel, das beide geprueften Endpunkte verfehlen, eine zulaessige 50/50-Innenallokation aber auf allen 200 Pfaden erfuellt, verlor damit Stufe 1 und bekam das Wunschziel-Gewicht. Der Reproducer ist als regulaerer Test uebernommen (`tests/test_goal_reachability_certificate.py`, rot auf develop exakt an `_stage1_liabilities(context) == [goal]`).

**CIO-Entscheid (2026-10-19):** die Herabstufung (Gewicht 0.2 + W0-Deckel) bleibt als Mechanismus, greift aber nur bei **zertifizierter** Unerreichbarkeit.

**Zertifikat (`goal_reachability.certify_goal_reachability`, `max_smoothed_success_multistart_v1`):** nur fuer Ziele, die der guenstige Screen nicht mit `UB_95 >= tau/2` findet.

1. Starts: Zentrum der zulaessigen Menge (Mittel der Screen-Kandidaten; Bandbreiten, Summe = 1 und Risikobudget sind konvex, geprueft mit `is_feasible`, sonst projiziert) und **alle** Screen-Kandidaten (Ecken + Solver-Multi-Starts).
2. Je Start SLSQP auf `-log mean sigmoid(m_n / b)` mit dem relativen Erfolgsabstand `m_n` aus `_success_margin_per_path` (dieselbe Definition wie die Stufe-1-Suche), Fortsetzung `b = 0.25 -> 0.05 -> 0.02`, dieselben Bandbreiten und Nebenbedingungen (`context.bounds`, `context.scipy_constraints`) wie der Solver. Log der Glaettung, damit auch sehr kleine Wahrscheinlichkeiten einen Gradienten haben.
3. An **jedem** zulaessigen ausgewerteten Punkt (Starts, Liniensuche, lokale Optima) der EXAKTE Erfolgsindikator (`_goal_probability_core`) auf dem Screening-Wuerfel (eigener Seed, nie der Validierungs-Holdout); massgeblich ist der beste Punkt.
4. `certified_unreachable_on_screen_cube` nur, wenn die obere einseitige 95-%-Wilson-Grenze mit Kish-ESS des besten Punktes `< tau/2`; sonst `reachable` (Abbruch beim ersten Treffer). Ohne bekannte zulaessige Menge `certificate_unavailable` -> keine Herabstufung (fail-safe).
5. Operativ wirkt nur `demoted_goal_ids` (= `certified_unreachable_goal_ids`); `not_found_reachable_goal_ids` bleibt Offenlegung. Gleiche Regel in allen Modi.

Policy-Versionen (ObjectiveContractV2-Hash wechselt): `goal_reachability_screen_v5_certified_demotion`, `certified_unreachable_demoted_wish_weight_v3` (Mechanismus identisch zu `screen_not_found_demoted_wish_weight_v2`, nur der Ausloeser ist neu).

Das Zertifikat ist ein bestes gefundenes lokales Optimum auf einem Wuerfel, kein globaler Unmoeglichkeitsnachweis; der Beraterhinweis sagt das. **Nicht umgesetzt (nur dokumentiert), Codex 6.1.4:** Herabstufung ausschliesslich ueber eine explizite, append-only und versionierte `GoalRevisionDecision` (Kunde/Berater, Grund, urspruenglicher Rang/Haertegrad/tau, neue Behandlung, Zeitpunkt, Hash); das waere die Ablösung jeder automatischen Herabstufung durch einen Kundenentscheid (siehe Abschnitt 11, Punkt 6).

**Wirkung in den Risikomass-Varianten:** bisher wurde dort jedes Ziel herabgestuft, dessen tau auf der Pruefmenge nicht erreicht wurde (Fundament: auch die Einkommensbruecke, max. ~73 % gegen 80 %). Mit der CIO-Regel (zertifiziert < tau/2) bleibt die Einkommensbruecke voll gewichtet; herabgestuft bleibt nur Familienvermoegen 2035.

## 13. Codex-Closure-Review zu #655: keine automatische Herabstufung, GoalRevisionDecisionV1 (Engine `saa_resampled_v11`)

**Befund (Codex P0, docs/audits/2026-10-20-goal-reachability-certificate-pr655-closure-review.md):** eine zulaessige Allokation erreicht ein hartes Ziel auf 400/400 Pfaden; die schmale Erfolgsinsel liegt zwischen allen Startpunkten, SLSQP verfehlt sie, das Ergebnis war trotzdem `certified_unreachable_on_screen_cube` -> Herabstufung aus Stufe 1. Ein lokales Optimum ist kein globaler Unmoeglichkeitsnachweis. Reproducer als regulaerer Test: `tests/test_goal_revision_decision.py::test_local_multistart_failure_cannot_certify_global_unreachability` (rot auf develop, gruen hier).

**CIO-Entscheid (2026-10-21):**

1. Die lokale Suche bleibt (Multi-Start, Glaettungsfortsetzung, exakter Indikator), liefert aber nur `reachable` oder `not_found_reachable_locally` (ohne zulaessige Menge `global_certificate_unavailable`), dazu `global_certificate: unavailable_local_search_only`, Solverstatus-Zaehler und `upper_bound_kind: sampling_wilson_at_best_found_point`. Kein Zustand ausser `reachable` hat eine Wirkung; das Ziel bleibt mit seinem Haertegrad in Stufe 1. `certified_unreachable_goal_ids` ist immer leer.
2. Herabgestuft (Wunschziel-Gewicht 0.2 + W0-Deckel, nicht Stufe 1) wird nur ein Ziel mit gueltiger **GoalRevisionDecisionV1** (`goal_revision_decisions`, append-only, Trigger gegen UPDATE/DELETE, kein FK auf goals/mandates; Alembic `e3c7a91f5b28`, Bootstrap-DDL, Runtime-Patch, ORM). Gebunden: Ziel-Snapshot (Hash + JSON der wirtschaftlichen Zieldefinition), bisheriger Haertegrad, neuer Status `nachrangiges_wunschziel`, Begruendung (Qualitaetspruefung wie Override-Reason), Engine-Evidenz (Status, beste gefundene Wahrscheinlichkeit, Wilson-Obergrenze am besten Punkt, tau, Engine-Version, Allokation, Screening-Wuerfel), Actor, Zeit, Regelversion, SHA-256. Die Engine prueft Hash, Ziel und Ziel-Snapshot-Hash (`services/goal_revision_decision.py::apply_to_liabilities`); jede Zielaenderung macht die Decision unwirksam. Die Decision geht in den Input-Snapshot-Hash ein (die aktuelle Allokation wird veraltet).
3. Vorschlag statt Automatik: `revision_suggested` je Zielzeile (`goal_revision`-Evidenz), Beraterhinweis im Reasoning ("mit den geprueften Allokationen nicht mit ausreichender Sicherheit erreicht ... oder als nachrangiges Wunschziel einstufen"), in der AA-Ansicht die Aktion "Als nachrangiges Wunschziel einstufen..." -> `POST /mandates/{id}/goals/{goal_id}/revision-decisions` (fail-closed: Begruendung 422, fehlende/veraltete Evidenz oder kein Vorschlag 409, bereits wirksam 409). `GET` liefert die Historie mit Gueltigkeit.
4. Laufzeit: schuetzt Stufe 1 ein lokal nicht gefundenes Ziel, erhaelt Stufe 2 dasselbe reduzierte Startbudget wie bis v10 bei herabgestuften Zielen (`_protects_unfound_goal`, reines Suchbudget; Schutzklasse unveraendert).

Policies: `goal_reachability_screen_v6_local_search_no_auto_demotion`, `max_smoothed_success_multistart_v2_local_only`, `goal_revision_decision_demoted_wish_weight_v4`.

**Fundament ohne Decision** (Familienvermoegen 2035 bleibt Stufe 1): 6234/1440/1775/300/251 -> 7485/1055/909/300/251 (Aktien/Obl./Immo/Alt./Liq.); P(Familienvermoegen) 11.2 -> 15.7 %, P(Einkommensbruecke) 72.9 -> 72.0 %, P(Mindestrendite) 56.9 -> 61.5 %; Stage-8-Verdikt yellow -> green; Stage-8 `elapsed_ms` (je 3 Laeufe abwechselnd) develop 7457/7575/7761 vs. v11 6782/7049/5980. Mit Decision entspricht das Verhalten v10 (5-Mio-Test: 6014/2958/534/294/200, identisch; ohne Decision 7000/2000/800/0/200).

Goldens: Score 7/9 nur Seed-Effekt (mit v10-Seed alle sechs byte-identisch), Haswell = Nehalem.
