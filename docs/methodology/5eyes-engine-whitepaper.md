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

## 4. Zielmodellierung (Goal → Liability)

Jedes Lebensziel wird in eine **GoalLiability** übersetzt (`goal_liabilities.py`):

- **Spending-Ziele** (Einmalige/Wiederkehrende Ausgabe, Pensionsausgabe) erzeugen einen
  **Outflow-Pfad** (`liability_path_rappen`) zum jeweiligen Zeitpunkt.
- **Wealth-Ziele** (Vermögensziel, Kapitalerhalt) und **Renditeziel** werden am
  **Zieljahr-Index** gegen eine Schwelle bewertet (`target_kind`: Wealth-Schwelle /
  annualisierter Cashflow / Return-bps).
- **Hardness-Gewichte** priorisieren Ziele (`objective.py`): *hart* = 10.0,
  *primär* = 1.0, *opportunistisch* = 0.2. Ein hartes Mindestziel dominiert die
  Optimierung; opportunistische Ziele werden nur „mitgenommen".

## 5. Zielfunktion (Downside-orientiert, zweiphasig)

Primäre Zielfunktion (`objective.combined_objective_two_phase`):

```
L(w) = Σ_g  h_g · w_g · (1/N) · Σ_n  max(0, target_g − wealth_g(w, n))²
```

— die mittlere **quadrierte Unterschreitung** je Ziel `g` über alle Pfade `n`,
gewichtet mit Hardness `h_g` und Zielgewicht `w_g`. Nur **Unterschreitungen** zählen
(`max(0, …)`): Überschuss wird nicht „belohnt", d. h. die Engine optimiert den
**Downside**, nicht den Erwartungswert.

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

## 11. Mortalität & Horizont

Der Projektions-/Optimierungs-Horizont reicht bis zur **Lebenserwartung**
(Geburtsjahr + 83 [Mann] / + 85 [Frau], bei Paaren das längere) bzw. dem letzten
erfassten Cashflow — der Vermögensverzehr nach der Pensionierung wird also vollständig
abgebildet. Optional zerschneiden **BFS-Sterbewahrscheinlichkeiten** die MC-Pfade für
realistischere Langlebigkeits-Szenarien.

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
`services/portfolio_engine.py`: Orchestrierung, Reserve, Mortalität, MC-Kennzahlen.
