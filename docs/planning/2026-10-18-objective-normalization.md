# OBJECTIVE-NORMALIZATION-001 – stetige, Pareto-monotone Zielfunktion und normierte Chance-Strafe

Stand 2026-10-18 · Branch `feat/objective-normalization` (gestapelt auf #619, `feat/saa-resampled-stability`)
Code: `services/optimizer/objective.py`, `services/optimizer/solver.py` (Validierungs-Verlust, Engine-Version), `services/optimizer/resampling.py` (Testversion)
Tests: `tests/test_objective_normalization.py` (neu) + nachgezogene Objective-/Chance-Tests

## 1. Befunde (gemessen, nicht geschätzt)

Messaufbau: die Optimizer-Contexts der sechs CH-Golden-Mandate (`tests/test_golden_snapshot_ch_regression.py`, Seeding dort) und des Fundament-Mandats (`tests/test_saa_resampled_stability.py`) wurden aus `generate_target_allocation` mitgeschnitten. Auf jedem Context liefen die 40 Produktions-Bags (je 500 Pfade, Inhalts-Seed) mit dem unveränderten Bag-Solver (Multi-Start-SLSQP + DE-Fallback). Jede Auswertung der Zielfunktion wurde in ihre Terme zerlegt protokolliert. Alle Läufe mit `OMP/OPENBLAS/MKL_NUM_THREADS=1`, `OPENBLAS_CORETYPE=Haswell`.

### 1.1 Größenordnungen der Terme (alte Formel, Bag-Gewinner, Median über 40 Bags)

| Mandat | Primärterm L(w) | Chance-Strafe (wenn > 0) | Vol-Tiebreak 1e-12·Var | Drawdown (Variante) | Min-Vol (Variante) |
|---|---|---|---|---|---|
| Golden Score 3 | 0 | 1.15e4 (19/40 Bags) | 2.6e2 | 0.06 | 0.034 |
| Golden Score 5 (3 Präferenzvarianten) | 0 … 3e-8 | 2.2e4 … 8.0e4 (21–25/40) | 1.5e3 … 1.8e3 | 0.12 | 0.066 |
| Golden Score 7 | 1.1e-8 | 1.8e4 (19/40) | 2.6e3 | 0.19 | 0.092 |
| Golden Score 9 | 7.3e-7 | 2.0e4 (23/40) | 4.6e3 | 0.25 | 0.11 |
| Fundament | 2.9 | **1.1e6** (40/40) | 1.1e4 | 0.26 | 0.11 |

Die Terme liegen über **zwölf Größenordnungen** verteilt (1e-9 … 1e6). Der Tiebreak war an die Währungseinheit gekoppelt (Rappen², Faktor W0²): bei CHF 500'000 ~2e3, bei CHF 5'000 ~0.2.

### 1.2 Befund B – der Stufen-Schalter greift in den Bags falsch

Der Volatilitätsterm wurde pro Allokation erst zugeschaltet, wenn deren Stufe 1 (L + Chance) < 1e-12 war. Eine Allokation mit Restfehlbetrag ~1e-9 hatte damit den Wert 1e-9, eine Allokation, die alle Ziele erfüllt, ~1.5e3.

| Mandat (goal_shortfall) | Bags, in denen der Solver einen Punkt mit Stufe 1 = 0 auswertete | davon gewann trotzdem ein Punkt mit Stufe 1 > 0 |
|---|---|---|
| Score 5, Default | 18 | 14 |
| Score 5, Aktien global | 18 | 17 |
| Score 5, CHF-only/EM | 13 | 13 |
| **Summe Score 5** | **49** | **44 (90 %)** |
| Score 3 / 7 / 9 / Fundament | 21 / 0 / 0 / 0 | 0 |

Zweite, gravierendere Folge derselben Skala: SLSQP stoppt bei absoluten Änderungen < `ftol = 1e-6`. Mit L ~ 1e-9 und ohne aktiven Tiebreak war die Zielfunktion für den Solver flach: **in 37–40 von 40 Bags war der Gewinner ein unveränderter Startpunkt** (Golden-Mandate, 3–17 SLSQP-Iterationen je Bag über alle Starts). Der „Optimierer" war dort ein Startpunkt-Wähler; die Bag-Streuung (Score 5: σ Aktien 5.6 pp je Bag) kam aus dem Springen zwischen Startpunkten.

### 1.3 Befund A – die Chance-Strafe erschlägt die Varianten

`LAMBDA_CHANCE_DEFAULT = 1e6` auf das Quadrat des Defizits `tau − LB`. Auf dem Fundament-Mandat (das einzige mit echtem Zielkonflikt: Vermögensziel CHF 5.78 Mio bei CHF 2.15 Mio Beratungsvermögen, Wahrscheinlichkeit 0) lag die Strafe bei 1.1e6, der Drawdown-Term bei 0.26:

| Fundament, Bag-Mittel (40 Bags) | Aktien | Obl. | Immo | Alt. | Liq. |
|---|---|---|---|---|---|
| goal_shortfall (Default) | 67.3 | 11.4 | 15.8 | 3.0 | 2.5 |
| max_drawdown | **67.9** | 17.1 | 8.9 | 3.5 | 2.5 |
| min_volatility | **70.3** | 16.7 | 6.8 | 3.7 | 2.5 |

Die Varianten „minimaler Drawdown" und „minimale Volatilität" lieferten **mehr** Aktien als der Default: entschieden hat allein die Strafe, die schon durch einzelne Pfade (0.2 pp Wahrscheinlichkeit, weit unter dem Monte-Carlo-Standardfehler) um Hunderte springt.

### 1.4 Nebenbefund (nicht in diesem PR behoben, eigener Auftrag nötig): Importance Sampling degeneriert

Alle sieben Mandate laufen mit Auto-Importance-Sampling (hartes Ziel). Die Kish-ESS der Likelihood-Gewichte:

| Mandat | ESS Hauptwürfel (2'000 Pfade) | ESS je Bag (500 Pfade), Median / Min | größtes Einzelgewicht |
|---|---|---|---|
| Golden Score 3 | 10.7 | 12.3 / 1.8 | 22 % |
| Golden Score 5 | 30.6 | 9.3 / 1.5 | 11 % |
| Golden Score 7 | 12.4 | 12.2 / 2.7 | 26 % |
| Golden Score 9 | 14.2 | 9.2 / 2.6 | 24 % |
| Golden CHF-only/EM | 8.2 | 8.1 / 2.0 | 33 % |
| Fundament | 7.3 | 6.5 / 1.2 | 30 % |

Ursache: der Mean-Shift von −0.5 σ wird **pro Jahr** angewandt; über T Jahre wächst die Log-Gewichts-Varianz mit `T · 0.25`, die erwartete ESS-Quote ist `exp(−T/4)` (T = 31: 4e-4). Folgen: (1) jede Kennzahl auf dem Bag-Würfel beruht auf ~10 effektiven Pfaden; (2) die Wilson-Untergrenze kann bei n_eff ≈ 10 selbst bei p = 1 nie über ~0.80 steigen – die Chance-Strafe der Golden-Mandate (1.1e4 … 8e4, alt) ist ein **reines ESS-Artefakt**, sie hängt nicht von der Allokation ab (Linienscan Golden Score 5: p = 1.000 über das ganze Band, LB 0.919 konstant). Empfehlung: Shift über den Horizont normieren (`strength / sqrt(T)`, ESS-Quote dann `exp(−0.25) ≈ 0.78`) oder IS für lange Horizonte abschalten; das ändert alle IS-Mandate und gehört in einen eigenen, gemessenen PR.

## 2. Entwurf

### 2.1 B: stetige Formulierung statt Schalter (gewählt) vs. echte lexikografische Zwei-Stufen-Optimierung

`f(w) = P(w) + C(w) + κ · Var(W_T) / W0²` – der Tiebreak ist **immer** aktiv, in der Einheit des Primärterms.

Abgewogen gegen die ε-Constraint-Lexikografie (Stufe 1 minimieren, dann Tiebreak unter `Stufe1 ≤ min + δ`):

| Kriterium | Stetig, immer aktiv | Lexikografisch (ε-Constraint) |
|---|---|---|
| Monotonie (Pareto) | ja, per Konstruktion | ja |
| Exakte Priorität | bis zur Toleranz κ·ΔVar | bis zur Toleranz δ |
| Numerik | glatter Gradient überall; behebt das Startpunkt-Steckenbleiben (1.2) | Nebenbedingung auf stückweise konstanter Stufe 1 (Chance-Indikatoren): SLSQP-Linearisierung undefiniert an jeder Sprungstelle |
| Laufzeit | unverändert (ein Solve je Start) | ~2× (zwei Solves je Start × 40 Bags), Performance-Budget gefährdet |
| Kalibrierung | κ (gemessen, 2.3) | δ (genauso zu kalibrieren) |

Beide Varianten brauchen eine Toleranz; die Lexikografie verlagert sie nur in eine harte Nebenbedingung, die auf der stückweise konstanten Stufe 1 numerisch nicht tragfähig ist. Die stetige Formulierung ist die übliche gewichtete Approximation der präemptiven Priorität (Sherali/Soyster) und hier die robustere Wahl. Der Signifikanztest (#619) vergleicht wieder die Skalar-Zielfunktion (`paired_bootstrap_one_sided_scalar_v3`) – dieselbe Ordnung, nach der optimiert wird; `lexicographic_improvement` bleibt als Werkzeug für Zwei-Stufen-Vergleiche erhalten.

### 2.2 A: Chance-Strafe linear und volumen-normiert

`C(w) = Σ_g max(0, τ_g − LB_g) · (Z_g / W0)²` (nur Ziele mit Härtegrad hart/primär, wie bisher)

* `Z_g` = Geldvolumen eines vollständigen Ausfalls (`goal_volume_rappen`): Zielbetrag; Summe der Fälligkeiten im Horizont; implizites Zielvermögen beim Renditeziel.
* `(Z_g / W0)²` ist exakt die Einheit von L(w) (mittlerer quadrierter relativer Fehlbetrag): ein Defizit Δ kostet so viel wie ein vollständiger Ausfall auf dem Pfadanteil Δ – die Obergrenze dessen, was dieses Defizit im Primärterm anrichten kann. Gewicht 1.0 ist die natürliche Einheit, kein Kalibrierungswert.
* Linear statt quadratisch: exakte (L1-)Strafe – kleine Defizite verschwinden nicht (Quadrat: 1 pp → 1e-4), große explodieren nicht.
* Schranke: auch ein unerreichbares Ziel kostet höchstens `τ · (Z/W0)²` (vorher `1e6 · τ²` = 6.4e5).

### 2.3 Kalibrierung von κ (gemessen)

40 Bags je Mandat, 7 Mandate, κ ∈ {0, 1e-6, 1e-5, 1e-4, 1e-3, 1e-2, 1e-1, 1, 10}:

* **Untergrenze – der Solver muss den Tiebreak auflösen:** bei κ ≤ 1e-5 blieb der Gewinner in 40/40 Bags ein Startpunkt; bei 1e-3 auf dem Defensiv-Mandat (Var/W0² = 0.11) weiterhin 40/40; bei **1e-2** in 2/40 (Score 3), 5–9/40 (Score 5–9).
* **Obergrenze – die Zielpriorität darf nicht erodieren:** Fundament-Allokation (Bag-Mittel Aktien) 65.2 % für κ = 0 … 1e-2, 64.9 % bei 1e-1 (erste Bewegung, −0.3 pp), 62.1 % bei 1 (−3.1 pp), 60.1 % (Bandgrenze) bei 10.

**κ = 1e-2**: der kleinste Wert, der auf allen Mandaten aufgelöst wird, eine Dekade unter der ersten messbaren Ziel-Erosion. Kleiner wäre nicht „vorsichtiger", sondern wieder ein Startpunkt-Wähler.

### 2.4 Konsistenz mit Signifikanztest (#619) und Drawdown-Rerank (#625)

* Bags, Signifikanztest gegen die Hausmatrix und Drawdown-Rerank werten **dieselbe** Skalar-Zielfunktion aus: Ziel-Stufe (Primärterm bzw. verfeinerter Drawdown via `primary_value_override` + normierte Chance-Strafe) + Tiebreak (nur `goal_shortfall`) + Soft-Preference. Der Rerank (`validated_drawdown_evaluation`) ruft `chance_constraint_penalty` mit Default-Gewicht – erbt die Normierung ohne eigene Kopie.
* Signifikanztest v3 (`paired_bootstrap_one_sided_scalar_v3`, `comparison = "scalar"`): Differenz der Skalare; eine untere Konfidenzgrenze ist wieder definiert (eine Einheit). Test `test_house_matrix_significance_compares_the_scalar_the_solver_minimizes` prüft, dass `anchor_objective`/`candidate_objective` exakt die Bag-Zielfunktion auf dem Validierungswürfel sind; `test_resampled_significance_uses_the_refined_drawdown` (#625) prüft Rerank = Test im Modus `max_drawdown` – beide grün.
* Engine-Version `saa_resampled_v3` (geht in den Inhalts-Seed ein: neue Mathematik zieht bewusst neue Würfel).

## 3. Wirkung (gleiche Würfel, Bag-Mittel über 40 Bags, alt → neu)

| Mandat / Modus | Aktien | Obl. | Immo | Alt. | Liq. |
|---|---|---|---|---|---|
| Score 3 goal_shortfall | 0.0 → 0.0 | 89.0 → 87.7 | 0.0 → 0.0 | 6.3 → 7.3 | 4.7 → 5.0 |
| Score 5 goal_shortfall | 46.2 → 40.0 | 38.7 → 44.1 | 8.5 → 6.2 | 4.1 → 6.7 | 2.5 → 3.0 |
| Score 5 global | 46.7 → 40.0 | 37.8 → 43.8 | 8.9 → 6.6 | 4.2 → 6.5 | 2.4 → 3.0 |
| Score 5 CHF-only/EM | 45.3 → 40.0 | 39.5 → 43.2 | 8.9 → 7.8 | 3.8 → 6.0 | 2.5 → 3.0 |
| Score 7 goal_shortfall | 60.0 → 60.0 | 25.0 → 23.5 | 10.0 → 6.5 | 3.0 → 8.0 | 2.0 → 2.0 |
| Score 9 goal_shortfall | 75.0 → 75.0 | 15.0 → 13.8 | 6.0 → 4.0 | 2.0 → 5.2 | 2.0 → 2.0 |
| Fundament goal_shortfall | 67.3 → 65.2 | 11.4 → 11.3 | 15.8 → 18.0 | 3.0 → 3.0 | 2.5 → 2.5 |
| Fundament max_drawdown | **67.9 → 60.6** | 17.1 → 23.9 | 8.9 → 9.5 | 3.5 → 3.6 | 2.5 → 2.5 |
| Fundament min_volatility | **70.3 → 63.1** | 16.7 → 22.0 | 6.8 → 7.7 | 3.7 → 4.8 | 2.5 → 2.5 |

Bag-Streuung der Aktienquote (σ je Bag): Score 5 5.6 → 0.0 pp, Fundament 5.1 → 4.7 pp (dort dominiert das IS-Rauschen aus 1.4).

Lesart: Wo die Ziele auf dem ganzen Band erfüllt sind (Golden-Mandate), entscheidet jetzt tatsächlich die Volatilität – innerhalb der Hausmatrix-Bandbreiten Richtung untere Aktien-/Immobiliengrenze und mehr Alternative (Diversifikation). Auf dem Konfliktmandat bleibt die Zielpriorität erhalten (Default), und die Risikomass-Varianten wirken wieder in ihre Richtung.

## 4. Produktion (Resampling + Signifikanztest, Engine `saa_resampled_v3`)

Vorher = Basis #625 (`feat/goal-attribution-and-dd-certification`, inkl. Drawdown-Rerank), nachher = dieser Branch; je Lauf `generate_target_allocation` mit 40 Bags + Signifikanztest gegen die Hausmatrix. Werte in % (Aktien/Obl./Immo/Alt./Liq.), in Klammern der Entscheid.

| Mandat | Modus | vorher | nachher | erw. Rendite/Vola (bps) |
|---|---|---|---|---|
| Score 3 | goal_shortfall | 0.0/89.0/0.0/6.3/4.7 (opt.) | 0.0/88.2/0.0/6.8/5.0 (opt.) | 207/344 → 206/342 |
| Score 5 | goal_shortfall | 46.2/38.7/8.5/4.1/2.5 (opt.) | 40.0/44.5/5.7/6.8/3.0 (opt.) | 435/740 → 398/647 |
| Score 5 global | goal_shortfall | 46.7/37.8/8.9/4.2/2.4 (opt.) | 40.0/44.5/6.2/6.4/3.0 (opt.) | 451/776 → 410/671 |
| Score 5 CHF/EM | goal_shortfall | 45.3/39.5/8.9/3.8/2.5 (opt.) | 40.0/43.8/6.0/7.2/3.0 (opt.) | 445/770 → 410/686 |
| Score 7 | goal_shortfall | 60.0/25.0/10.0/3.0/2.0 (opt.) | 60.0/23.1/6.8/8.1/2.0 (opt.) | 501/953 → 489/959 |
| Score 9 | goal_shortfall | 75.0/15.0/6.0/2.0/2.0 (opt.) | 75.0/13.9/3.9/5.2/2.0 (opt.) | 559/1171 → 551/1174 |
| Fundament | goal_shortfall | 67.3/11.4/15.8/3.0/2.5 (opt.) | 66.0/11.0/17.5/3.0/2.5 (opt.) | 546/1094 → 543/1081 |
| Fundament | max_drawdown | **68.0**/17.1/8.9/3.5/2.5 (opt.) | 67.5/17.0/7.0/6.0/2.5 (**Hausmatrix**; Bag-Kandidat 60.3/24.1/9.2/3.8/2.5) | 532/1076 → 524/1070 |
| Fundament | min_volatility | **70.2**/16.7/6.8/3.7/2.5 (opt.) | 67.5/17.0/7.0/6.0/2.5 (**Hausmatrix**; Bag-Kandidat 62.5/22.7/7.4/4.8/2.5) | 538/1104 → 524/1070 |

Golden-Mandate in den Varianten (`max_drawdown`, `min_volatility`): Änderungen ≤ 1 pp je Bucket – dort war die Chance-Strafe (ESS-Artefakt, siehe 1.4) allokationsunabhängig und hat nichts entschieden.

Fundament in den Varianten: die Bags liefern jetzt das, was die Variante verlangt (60–63 % Aktien statt 68–70 %). Der Signifikanztest auf dem unabhängigen Validierungswürfel (2'000 ungewichtete Pfade, verfeinerter Drawdown) behält trotzdem die Hausmatrix (67.5 %), weil der Bag-Kandidat Zielwahrscheinlichkeit kostet – Zahlen in Abschnitt 6. Gegenüber vorher ist das in beiden Varianten weniger Aktien (−0.5 / −2.7 pp), und der Entscheid beruht jetzt auf einem ehrlichen Vergleich statt auf einer Strafe, die einzelne Pfade um Hunderte bewegen.

## 5. Golden-Fixtures

Alle sechs CH-Golden-Fixtures neu eingefroren (Engine `saa_resampled_v3`; neue Engine-Version zieht bewusst neue Würfel). Erzeugt lokal mit `OMP/OPENBLAS/MKL_NUM_THREADS=1` unter `OPENBLAS_CORETYPE=Haswell` und `=Nehalem` (die beiden Kernel-Familien der früheren CI-Ausprägungen): 5 von 6 Dateien byte-identisch, Score 5 Default weicht um 1 bps (Obl./Immo) bzw. CHF 50 in einem Umsetzungsschritt ab – weit innerhalb der Test-Toleranz (30 bps / CHF 1'500). Eingefroren: Haswell.

| Profil | Aktien | Obl. | Immo | Alt. | Liq. | erw. Rendite | erw. Vola |
|---|---|---|---|---|---|---|---|
| Score 3 Defensiv | 0 → 0 | 89.03 → 88.24 | 0 → 0 | 6.29 → 6.76 | 4.68 → 5.00 | 2.07 → 2.06 % | 3.44 → 3.42 % |
| Score 5 Ausgewogen | 46.16 → 40.00 | 38.70 → 44.53 | 8.54 → 5.67 | 4.13 → 6.80 | 2.47 → 3.00 | 4.35 → 3.98 % | 7.40 → 6.47 % |
| Score 5 Aktien global | 46.69 → 40.00 | 37.83 → 44.45 | 8.91 → 6.22 | 4.18 → 6.36 | 2.39 → 2.97 | 4.51 → 4.10 % | 7.76 → 6.71 % |
| Score 5 CHF-only/EM | 45.33 → 40.00 | 39.45 → 43.79 | 8.90 → 6.00 | 3.82 → 7.21 | 2.50 → 3.00 | 4.45 → 4.10 % | 7.70 → 6.86 % |
| Score 7 Wachstum | 60.00 → 60.00 | 25.00 → 23.12 | 10.00 → 6.78 | 3.00 → 8.10 | 2.00 → 2.00 | 5.01 → 4.89 % | 9.53 → 9.59 % |
| Score 9 Dynamisch | 75.00 → 75.00 | 15.00 → 13.87 | 6.00 → 3.89 | 2.00 → 5.24 | 2.00 → 2.00 | 5.59 → 5.51 % | 11.71 → 11.74 % |

Alle sechs: Signifikanztest gegen die Hausmatrix `optimizer` (p = 0.0025, Minimum bei 400 Replikationen), Status `converged`.

Lesart: vorher waren Score 7/9 exakt der Startpunkt „Bandmitte/Unterkante" (Bag-Streuung 0 bps – kein einziger Bag hatte optimiert); Score 5 lag mit 46 % Aktien zwischen zufällig gewählten Startpunkten. Jetzt minimiert der Tiebreak die Endvermögens-Varianz innerhalb der Bänder: Aktien an die Unterkante (wo sie es nicht schon waren), Immobilien runter, Alternative (Gold) rauf. Bei Score 7/9 steigt die *analytische* Einperioden-Vola dabei um 3–6 bps, obwohl die Varianz des Endvermögens fällt. Zwei Gründe, beide nicht durch die Normierung entstanden, aber durch sie erstmals wirksam: (a) `Var(W_T)` – das Mass der Methodik (Slide 18) – ist mittelwertabhängig: eine höhere erwartete Rendite vergrössert über 31 Jahre auch die Endvermögens-Streuung, der Tiebreak bevorzugt damit tendenziell rendite-schwächere Mischungen (dieselbe Klasse wie OPTIMIZER-MIN-VOLATILITY-SEMANTICS-001); (b) er wird auf dem IS-Würfel mit ~10 effektiven Pfaden geschätzt (1.4). Siehe Owner-Frage 2 in Abschnitt 6.


## 6. Offene Owner-Entscheidung

**Frage 1 – Darf eine Risikomass-Variante Zielwahrscheinlichkeit gegen Drawdown-Schutz tauschen, und zu welchem Kurs?**

Umgesetzt ist der Kurs „Geldvolumen": ein Wahrscheinlichkeitspunkt eines Ziels kostet `(Z/W0)²` Punkte Primärterm. Gemessen auf dem Fundament-Mandat, Modus `max_drawdown`, Validierungswürfel:

| | Hausmatrix (67.5 % Aktien) | Bag-Kandidat (60.3 % Aktien) |
|---|---|---|
| verfeinerter mittlerer Max-Drawdown | 30.6 % | 27.0 % (−3.7 pp) |
| P(Familienvermögen 2035, CHF 5.78 Mio, primär, Z/W0 = 2.68) | 2.85 % | 1.70 % (−1.15 pp) |
| P(Einkommensbrücke Pension, primär, Z/W0 = 0.99) | 49.5 % | 47.2 % (−2.35 pp) |
| Chance-Strafe | 5.910 | 6.006 (+0.096, davon 0.073 aus dem Familienvermögen) |
| Zielfunktion (Drawdown + Strafe) | 6.217 | 6.276 → Hausmatrix gewinnt (p = 1.0) |

76 % des Ausschlags kommen von einem Ziel, das auf **keiner** zulässigen Allokation erreichbar ist (2.9 % gegen τ = 80 %). Optionen:
(a) wie umgesetzt – jedes Ziel zählt mit seinem vollen Geldvolumen (Ziele vor Risikomass, wie in Entwurfsentscheidung 1 der Varianten dokumentiert);
(b) Volumen je Ziel auf W0 deckeln (`min(Z, W0)/W0`) – dann stünde es 1.400 zu 1.397, statistisch unentscheidbar, der Test bliebe bei der Hausmatrix;
(c) in den Risikomass-Varianten Ziele ausnehmen, die an keiner Bandecke erreichbar sind (braucht eine Vorab-Prüfung je Lauf).
Umgesetzt ist (a), weil es der dokumentierten Owner-Entscheidung „Ziel-Untergrenze in jeder Variante" folgt und das Ergebnis gegenüber vorher in beiden Varianten weniger Risiko bedeutet; (b) würde am Fundament-Ergebnis nichts ändern.

**Frage 2 – Ist `Var(W_T)` das richtige Tiebreak-Mass?**

Mit dem jetzt wirksamen Tiebreak landen ziel-sichere Mandate an der Unterkante der Aktienbandbreite (Score 5: 46 → 40 %, erwartete Rendite 4.35 → 3.98 %, Vola 7.40 → 6.47 %). Das ist die Methodik (Slide 18: Priorität 2 = Volatilität minimieren), die vorher wegen der Skalierung nie gegriffen hat. `Var(W_T)` ist aber mittelwertabhängig (bevorzugt über 31 Jahre auch rendite-schwächere Mischungen, Score 7/9: analytische Vola +3–6 bps). Alternative: die cashflow-neutrale Einperioden-Volatilität aus `min_volatility` (OPTIMIZER-MIN-VOLATILITY-SEMANTICS-001) als Tiebreak. Nicht umgesetzt – das ändert die Methodik, nicht nur die Skala.

**Frage 3 (technisch, kein Owner-Entscheid, aber Priorität):** Importance Sampling reparieren (1.4). Solange ~10 effektive Pfade die Bag-Zielfunktion tragen, bleibt jede Feinjustierung der Terme im Rauschen.

**Nachtrag 2026-10-18:** Fragen 1 (Option c), 2 (Tiebreak w'Σw) und 3 (Importance Sampling) per CIO-Entscheid umgesetzt in IMPORTANCE-SAMPLING-ESS-001, siehe `docs/planning/2026-10-18-importance-sampling-ess.md`.
