# 5eyes — Methodik der Anlagestrategie-Engine

**Whitepaper · Stand 2026-06-17 · Roadmap PAR-11**

Dieses Dokument erklärt die wissenschaftliche und technische Grundlage der
5eyes-Engine, die aus Risikoprofil, Lebenszielen, Vermögens- und Cashflow-Situation
eine strategische Asset-Allokation (SAA) herleitet. Zielpublikum: Berater, Compliance/
Revision, Aufsicht. Alle Aussagen sind im Quellcode verankert (Modul-/Funktionsangaben
in Klammern), damit die Methodik prüfbar ist.

> Hinweis: 5eyes verfolgt eine **zielbasierte, stochastische** Methodik. Es findet
> **kein Markt-Timing** und **keine aktive Einzeltitel-Spekulation** statt
> (siehe ADR-003). Die Engine ist deterministisch reproduzierbar (Abschnitt 9).

---

## 1. Grundidee: zielbasierte stochastische Optimierung

Klassische Mean-Variance-Optimierung (Markowitz 1952) maximiert Rendite je
Risiko-Einheit, ohne die **konkreten Lebensziele** und **Verbindlichkeiten** des
Kunden zu kennen. 5eyes optimiert stattdessen direkt auf **Zielerreichung**:
Wie hoch ist die Wahrscheinlichkeit (und der Grad), dass der Kunde mit der gewählten
Allokation seine Ziele — Pensionierung, Eigenheim, Schenkung, Vermögenserhalt —
über Tausende simulierte Kapitalmarktpfade erreicht?

Methodisch ist dies ein **mehrperiodisches stochastisches Optimierungsproblem mit
Verbindlichkeiten** (asset-liability management, vgl. Mulvey/Ziemba). Die Allokation
`w` (Gewichte über Anlageklassen) wird so gewählt, dass die erwartete
**Unterschreitung** der Ziele im **Downside** minimal ist.

## 2. Kapitalmarktmodell (CMA)

Eingang sind die **Capital Market Assumptions** (erwartete Rendite, Volatilität,
Korrelationsmatrix, Inflationspfad) je Anlageklasse — versioniert und konservativ
gepflegt (Maxime: im Zweifel der tiefere Renditewert). Zusätzlich werden **höhere
Momente** modelliert:

- **Schiefe (Skew)** und **Exzess-Kurtosis** je Anlageklasse (`scenario_engine.py`).
  Renditen sind nicht normalverteilt — Aktien/Alternatives haben fette, linksschiefe
  Verlust-Tails. Werte werden geklemmt (`_clamp_skew/_clamp_kurt`), um numerische
  Stabilität zu sichern.
- **Konservative Alternatives-Annahmen (2026-06-18):** Gold/Rohstoffe **1.2 %** (langfr.
  Realrendite ~0 %), Private Equity **6.5 %**, Krypto **8.0 %** nominal — bewusst am unteren
  Rand, da diese Klassen unsicher/spekulativ sind. Aktien (CH 6.2 % / Intl 7.0 % / EM 7.6 %),
  Obligationen (~2.2 %) und Immobilien (4.5 %) bleiben auf den etablierten, vertretbaren
  Werten. Ein Regressions-Lock (`test_cma_conservative_alternatives`) verhindert ein
  stilles Hochdriften der Alternatives-Renditen.

## 3. Szenario-Engine (Monte-Carlo)

Die Engine zieht tausende mehrjährige Pfade (`scenario_engine.py`):

- **Fat Tails via Cornish-Fisher-Expansion** (`cornish_fisher_array`): Normal-Quantile
  werden um Skew/Kurtosis korrigiert, sodass Krisenszenarien realistisch häufig
  auftreten — entscheidend für ehrliche Downside-Kennzahlen (VaR/CVaR/Drawdown).
- **Korrelierte Ziehung** über die Cholesky-Zerlegung der Korrelationsmatrix.
- **Antithetische Varianten** (`antithetic=True`): zu jedem Pfad wird der gespiegelte
  Pfad gezogen → Varianzreduktion, stabilere Schätzer bei gleicher Pfadzahl.
- **Mean-Shift Importance Sampling** (`importance_sampling.py`, Glasserman 2004,
  Ch. 4.6): für Tail-Risk werden Stichproben in den Verlustbereich verschoben und
  mit Likelihood-Gewichten zurückkorrigiert — mehr Information über Black-Swan-Verluste
  bei gleicher Rechenlast (opt-in / auto-enable je Kontext).

**Anzeige-Projektion (SOLL/IST-Verläufe) ↔ Optimierung.** Die Optimierung nutzt die obige
Szenario-Engine. Die *dargestellten* Vermögensverläufe (`portfolio_engine._build_simulation_payload`)
verwenden eine eigene, deterministisch geseedete Pfadschar (SHA256-Seed über Mandat/CMA/
Horizont/Targets). Der **deterministische Hauptpfad** nutzt seit 2026-06-17 dieselbe
**momententreue geometrische Wachstumskonvention** wie der Monte-Carlo-Median.
Mit `v=log(1+(σ/(1+r))²)` ist
`growth = exp(log(1+r) − ½v)`, sodass die Hauptlinie **im Zentrum des
MC-Median-Fächers** liegt statt optimistisch darüber. Arithmetischer CMA-Mittelwert
und einfache Return-Volatilität werden dabei gleichzeitig erhalten. So sind
„Hauptszenario" und Median-Band konsistent und die ausgewiesene
„Median-Rendite (CAGR)" stimmt mit der dargestellten Kurve überein.

## 4. Zielmodellierung (Goal → Liability)

Jedes Lebensziel wird in eine **GoalLiability** übersetzt (`goal_liabilities.py`):

- **Spending-Ziele** (Einmalige/Wiederkehrende Ausgabe, Pensionsausgabe) erzeugen einen
  **Outflow-Pfad** (`liability_path_rappen`) zum jeweiligen Zeitpunkt.
- **Wealth-Ziele** (Vermögensziel, Kapitalerhalt) und **Renditeziel** werden am
  **Zieljahr-Index** gegen eine Schwelle bewertet (`target_kind`: Wealth-Schwelle /
  annualisierter Cashflow / Return-bps).
- **Ziel-Gewichtung (Methodik-Default = Gleichgewichtung).** Standardmässig gehen
  **alle Ziele gleich gewichtet** in die Zielfunktion ein (Mittelung) — methodik-konform
  zur etablierten Goal-Based-Lehre („alle Ziele sind gleich wichtig"). Die
  **Hardness-Gewichtung** (*hart* = 10.0, *primär* = 1.0, *opportunistisch* = 0.2,
  `objective._effective_hardness_weight`) ist als **opt-in** erhalten und wird nur bei
  `OPTIMIZER_GOAL_WEIGHTING=hardness` aktiv; dann dominiert ein hartes Mindestziel die
  Optimierung und opportunistische Ziele werden nur „mitgenommen". (Stand 2026-06-17.)
- **Ziel-Bezugsgrösse (`goal_scope`).** Standardmässig werden Ziele gegen das
  **Beratungsvermögen** bewertet (die Strategie optimiert nur dieses). Wird ein
  Wealth-Ziel (Vermögensziel/Kapitalerhalt) auf **`goal_scope="Gesamtvermögen"`** gesetzt,
  fliessen zusätzlich die **externen Assets** (Eigenheim etc. = Gesamt- minus
  Beratungsvermögen) in die Hochrechnung ein — **konservativ nur mit der Teuerung
  fortgeschrieben (realer Zuwachs 0 %, keine Volatilität)**. Da dieser externe Anteil eine
  deterministische Konstante ist und in **beiden** Pfaden (deterministisch + Monte-Carlo)
  identisch addiert wird, entsteht **kein Drift** zwischen den Bewertungen. Ausgaben- und
  Renditeziele bleiben scope-neutral (Ausgaben sind liquiditätsgetrieben — illiquide
  externe Assets finanzieren keine kurzfristige Ausgabe). (User-Fachentscheid 2026-06-19;
  `portfolio_engine._goal_uses_total_scope`, `_external_assets_inflation_value`.)

## 5. Zielfunktion (Downside-orientiert, zweiphasig)

Primäre Zielfunktion (`objective.combined_objective_two_phase`):

```
L(w) = Σ_g  h_g · w_g · (1/N) · Σ_n  max(0, target_g − wealth_g(w, n))²
```

— die mittlere **quadrierte Unterschreitung** je Ziel `g` über alle Pfade `n`,
gewichtet mit `h_g` und Zielgewicht `w_g`. Nur **Unterschreitungen** zählen
(`max(0, …)`): Überschuss wird nicht „belohnt", d. h. die Engine optimiert den
**Downside**, nicht den Erwartungswert. **`h_g` ist im Default 1.0** (alle Ziele
gleich; Hardness nur als opt-in, siehe Abschnitt 4).

**Anzeige der Zielerreichung (SOLL/IST):** Pro Ziel werden die *Median-Zielerreichung*
(effektiv ÷ gewünscht, auf 100 % gedeckelt) und ein *pessimistischer CHF-Fehlbetrag*
ausgewiesen. Der Fehlbetrag basiert auf dem **schlechtesten Quartil (P25)** der
Pfadverteilung (nicht P10) — methodik-konform zur Praxis, für Nicht-Cashflow-Ziele das
schlechteste Quartil auszuweisen (`portfolio_engine._monte_carlo_goal_summary`, Stand 2026-06-17).

**Zweiphasig:** Ist die Zielerreichung gesichert (L ≈ 0), schaltet die Engine auf die
**sekundäre** Zielfunktion um und minimiert die Vermögens-**Varianz** — d. h. unter
mehreren zielerfüllenden Allokationen wird die ruhigste gewählt.

## 6. Chance-Constraints (Mindestwahrscheinlichkeit)

Zusätzlich erzwingt die Engine **Wahrscheinlichkeits-Nebenbedingungen**
(`objective.chance_constraint_penalty`): `P(Ziel_g erreicht) ≥ τ_g`. Default-Schwellen
sind konservativ (Wealth/Cashflow höher als Renditeziele). Verletzungen werden über
einen Penalty-Term in die Optimierung eingepreist — die Lösung respektiert die vom
Profil/Ziel geforderte Mindest-Erfolgswahrscheinlichkeit.

## 7. Verbindliche Constraints (8 Regeln)

Harte Regeln, die jede Lösung einhalten muss (`constraints.py`):

1. **Summe = 1** (Vollinvestition über die Anlageklassen).
2. **Risiko-Budget-Cap:** Σ wᵢ·rfᵢ ≤ Score/10 — die risikobehaftete Fraktion (gewichtet
   mit Anlageklassen-Risikokoeffizienten rfᵢ, z. B. Aktien 0.80, Immobilien 0.60,
   Alternatives 0.60) darf das Risikoprofil nicht überschreiten.
3. **House-Matrix-Bänder:** profilabhängige Min/Max je Bucket (Box-Bounds).
4. **Immobilien-Cap ≤ 20 %.**
5. **Alternatives-Cap ≤ 10 %.**
6. **Liquiditäts-Floor ≥ 2 %.**
7. **Nicht-Negativität** (keine Leerverkäufe).
8. **Reproduzierbarkeit** über den Seed (Abschnitt 9).

Sind die Constraints nicht einhaltbar, greift ein **dokumentierter Fallback** auf die
House-Matrix-Standardallokation (Status `fallback_house_matrix`) — die Engine liefert
nie ein stilles oder regelwidriges Ergebnis.

## 8. Solver

`solver.py`: **SLSQP** (Sequential Least Squares Programming, `scipy.optimize.minimize`)
mit **Multi-Start** — mehrere Initial-Allokationen (House-Matrix-Mid/konservativ/
aggressiv/Risky-Edge) werden optimiert, die beste zulässige Lösung gewinnt. Bei
schlechter Konvergenz dient **Differential Evolution** (`differential_evolution`) als
globaler Fallback. So wird die Gefahr lokaler Minima reduziert.

## 9. Reproduzierbarkeit & Auditierbarkeit

- **Deterministischer Seed** (`solver.deterministic_seed`) aus (CMA, Ziele, Score,
  Horizont, Pfadzahl). Identische Eingaben → identische Szenarien → identisches
  Ergebnis. Zufallszahlen über **PCG64** (`np.random.default_rng`), nicht Legacy-RNG.
- **Reasoning-Trace / Shadow-Comparison:** jeder Lauf ist nachvollziehbar; ein
  Schatten-Vergleich gegen die House-Matrix dokumentiert Abweichungen.
- **Audit-Log** (manipulationssicher, Hash-Kette) protokolliert datenverändernde
  Operationen.

Diese Eigenschaften sind für eine FINMA-konforme Beratung zentral: ein Ergebnis ist
**erklärbar und exakt wiederherstellbar**.

## 10. Reserve & Liquidität

Nahe Ziele und kurzfristiger Liquiditätsbedarf werden über eine **Reserve mit
glattem Decay** abgesichert (`portfolio_engine._reserve_decay_factor`): sofort fällige
Bedürfnisse → volle Reserve; mit zunehmendem Horizont sinkt der Reserve-Anteil bis auf
eine **Tail-Risk-Restreserve von 5 %**. Das verhindert Zwangsverkäufe in Krisen.

**Liquidität wertet in der Projektion NICHT auf (Cash = 0 %).** In der Vermögens-
projektion (deterministischer Pfad UND Monte-Carlo) wird die Liquidität mit
`returns["liquidity"]=0` und `vols["liquidity"]=0` geführt — ein 0 %-Konto bleibt flach.
Tatsächliche Kontozinsen fliessen ausschliesslich über den **abgeleiteten Zinsertrag-
Cashflow** ein (kein Doppelzählen). Die CMA-`liquidity_return_bps` bleibt davon unberührt
und dient weiter als risk-free-Satz für Sharpe/Optimizer. (User-Fachentscheid 2026-06-17.)

**Illiquidität ist eine Baustein-Eigenschaft.** Das Mandatslimit „maximaler illiquider
Anteil" (`maxIlliquid`) deckelt gezielt den **echt illiquiden Baustein Private Equity**
(`_apply_illiquid_cap`, `_ILLIQUID_SUB_ASSET_CLASSES`) — nicht pauschal die gesamte
Alternatives-Quote (Gold/Liquid Alts sind liquide). Direktimmobilien werden ohnehin als
**externes Vermögen** geführt und nicht in die handelbare SAA umgeschichtet. Ein
Überschuss über das Limit wandert primär zu liquiden Alt-Bausteinen, sonst in die
Liquidität — die Renditen je Baustein bleiben unverändert.

## 11. Mortalität & Horizont

Der Projektions-/Optimierungs-Horizont reicht bis zur **Lebenserwartung**
(Geburtsjahr + 83 [Mann] / + 85 [Frau], bei Paaren das längere), dem letzten
erfassten Cashflow oder dem spätesten Start-/Zieldatum eines aktiven Ziels —
der Vermögensverzehr nach der Pensionierung wird also vollständig abgebildet.
Ein fehlendes numerisches Ziel-`horizon_years` kürzt ein datiertes Ziel nicht.
Optional zerschneiden **BFS-Sterbewahrscheinlichkeiten** die MC-Pfade für
realistischere Langlebigkeits-Szenarien.

**Sequence-of-Returns-/Verzehr-Risiko (Kennzahl).** Für den Verzehr weist die Engine aus
den MC-Pfaden eine **Depletion-Kennzahl** aus: den Anteil der Pfade, deren Vermögen vor
Horizontende **aufgezehrt** ist (Pfad-Total ≤ 0), sowie das **mittlere Erschöpfungsjahr**
(Median der betroffenen Pfade) — getrennt für SOLL und IST
(`portfolio_engine._sequence_of_returns_depletion`;
`monte_carlo.target_/current_depletion_probability_pct` + `…_median_year`). Sie macht das
**Sequence-of-Returns-Risiko** sichtbar: schlechte Renditen früh im Verzehr zehren das
Kapital schneller auf als dieselben Renditen in günstiger Reihenfolge. In reiner
Akkumulation (keine Netto-Entnahmen) ist die Quote 0 %. Im SOLL/IST-Kennzahlen-Vergleich
erscheint sie als Zeile „Verzehr-Risiko" (tiefer = besser). (Stand 2026-06-19.)

## 12. Nach-Steuer- und Währungssicht

Die Szenario-Engine kann **steueraware** (CH-Steuerregime via Tax-Plugin-SDK, z. B.
Kapitalbezugssteuer, Pensionierungs-Status) und **währungskorrekt** (FX→CHF) rechnen;
der Schweizer Anleger trägt das Fremdwährungsrisiko, das entsprechend modelliert wird.

## 13. Grenzen & Annahmen

- Ergebnisse sind **Szenario-Projektionen**, keine Garantien; Kapitalmarktannahmen sind
  Schätzungen und konservativ gewählt.
- Die Engine ersetzt nicht das Beraterurteil; sie liefert eine **nachvollziehbare,
  zielorientierte Entscheidungsgrundlage**.
- Re-Balancing erfolgt **nicht** durch Markt-Timing, sondern nur via Eignungsprüfung/
  Kunden-Meldung (Anlagephilosophie, ADR-003).

## Quellen (Methodik)

- Markowitz, H. (1952): *Portfolio Selection.*
- Mulvey, J. / Ziemba, W.: mehrperiodische stochastische Optimierung mit Verbindlichkeiten (ALM).
- Glasserman, P. (2004): *Monte Carlo Methods in Financial Engineering*, Kap. 4.6 (Importance Sampling).
- Cornish, E. / Fisher, R. (1938): Quantil-Approximation über Momente (Skew/Kurtosis).
- Rockafellar, R. / Uryasev, S. (2000): *Optimization of Conditional Value-at-Risk* (CVaR/Downside).

## Code-Referenzen (Prüfpfad)

`services/optimizer/`: `solver.py` (SLSQP/DE, Seed) · `scenario_engine.py` (Fat-Tails,
antithetisch) · `importance_sampling.py` · `objective.py` (Zielfunktion, Chance-Constraints,
Hardness) · `goal_liabilities.py` (Ziel→Liability) · `constraints.py` (8 Regeln) ·
`distributions.py` (Cornish-Fisher) · `stress_scenarios.py`.
`services/portfolio_engine.py`: Orchestrierung, Reserve, Mortalität, MC-Kennzahlen;
`_goal_uses_total_scope` + `_external_assets_inflation_value` (Gesamtvermögen-Scope, §4),
`_sequence_of_returns_depletion` (Verzehr-Kennzahl, §11).

**Regression-Locks (Auswahl):** `test_goal_scope_gesamtvermoegen` (Scope real 0 %, kein
MC-Drift) · `test_audit_b4_goal_base_consistency` (Default-Scope advisory-only) ·
`test_sequence_of_returns_depletion` (Verzehr-Kennzahl + Akkumulation = 0 %) ·
`test_engine_methodik_invariants` · `test_goal_pessimistic_quartile` (P25) ·
`test_deterministic_ito_growth` · `test_liquidity_zero_engine_lock` (Cash 0 %) ·
`test_illiquid_cap`.
