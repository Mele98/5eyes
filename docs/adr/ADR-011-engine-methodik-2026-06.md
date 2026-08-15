# ADR-011: Engine-Methodik-Verfeinerungen 2026-06

- **Status:** Accepted
- **Datum:** 2026-06-18
- **Sprint:** Kontroll-Audit + 3eyes-Parität + Verzehr-Realismus

## Kontext

Nach dem Kontroll-Audit der Beratungs-Engine (Vermögen → Cashflow → Ziele →
Reserve/SAA → Risikoprofil → Asset-Allocation → Monte-Carlo) und dem Abgleich mit
der etablierten Goal-Based-Methodik wurden mehrere Stellschrauben identifiziert, bei
denen 5eyes von der konservativen, methodikkonformen Praxis abwich oder inkonsistent
darstellte. Da die Engine FINMA-relevante Zahlen für die Kundenberatung erzeugt, sind
Korrektheit, Konsistenz und nachvollziehbare Konservativität entscheidend.

## Entscheidung

Sechs methodische Festlegungen (alle 2026-06-17/18 umgesetzt + test-abgesichert):

1. **Pessimistischer CHF-Fehlbetrag = schlechtestes Quartil (P25), nicht P10.**
   Für Nicht-Cashflow-Ziele weist die etablierte Methodik das schlechteste Quartil
   aus. 5eyes nutzte P10 (untere 10 %) — strenger als nötig und nicht methodikkonform.
   Umgesetzt in `_monte_carlo_goal_summary`.

2. **Ziel-Gewichtung = Gleichgewichtung (Default), Härtegrad opt-in.**
   „Alle Ziele sind gleich wichtig" (Mittelung) ist der methodikkonforme Default. Die
   frühere Härtegrad-Gewichtung (hart 10× / primär 1× / opp 0.2×) bleibt als opt-in via
   `OPTIMIZER_GOAL_WEIGHTING=hardness` erhalten. `_effective_hardness_weight`.

3. **Deterministischer Hauptpfad = momententreue MC-Median-Konvention.**
   Der angezeigte SOLL/IST-Hauptpfad nutzte `1+r` (arithmetisch) und lag damit
   optimistisch über dem MC-Median-Fächer, in dem er dargestellt wird. Jetzt
   Mit `v=log(1+(σ/(1+r))²)` gilt der Medianfaktor
   `exp(log(1+r) − ½v)`. Die Hauptlinie sitzt im Fächer-Zentrum; arithmetischer
   CMA-Mittelwert und einfache Return-Volatilität bleiben beide exakt kalibriert.

4. **Liquidität wertet in der Projektion nicht auf (Cash = 0 %).**
   `returns["liquidity"]=0`, `vols["liquidity"]=0` in deterministischem UND MC-Pfad.
   Echte Kontozinsen laufen ausschliesslich über den abgeleiteten Zinsertrag-Cashflow
   (kein Doppelzählen). `cma.liquidity_return_bps` bleibt risk-free-Satz für Sharpe/Optimizer.

5. **Illiquiditäts-Limit (`maxIlliquid`) deckelt nur den illiquiden Baustein (Private Equity).**
   Illiquidität ist eine Baustein-Eigenschaft, kein pauschaler Alternatives-Deckel
   (Gold/Liquid Alts sind liquide). Direktimmobilien laufen extern über das Gesamtvermögen.
   `_apply_illiquid_cap`, `_ILLIQUID_SUB_ASSET_CLASSES`.

6. **Konservativere CMA-Renditen für Alternatives.**
   Gold 3.0 % → 1.2 % (langfristige Realrendite ~0 %), Private Equity 8.0 % → 6.5 %,
   Krypto 12 % → 8 %. Aktien/Obligationen/Immobilien bleiben auf etablierten Werten.
   Maxime „im Zweifel der tiefere Renditewert" (Ruhestandsgelder).

## Alternativen (verworfen)

- **P10 beibehalten** (Entscheid 1): strenger, aber nicht methodikkonform; verwirrt im
  Vergleich mit 3eyes-orientierten Mandaten.
- **Härtegrad als Default** (Entscheid 2): bevorzugt harte Ziele, weicht aber von der
  Gleichgewichtungs-Lehre ab → als opt-in degradiert statt entfernt.
- **Arithmetische Hauptlinie** (Entscheid 3): einfacher, aber inkonsistent zum Median-Fächer
  und optimistisch → verworfen.
- **Alternatives-Quote pauschal deckeln** (Entscheid 5): trifft fälschlich liquide Bausteine →
  verworfen zugunsten Baustein-genauer Deckelung.
- **Aktien-Renditen ebenfalls senken** (Entscheid 6): erwogen, aber 6–7.6 % nominal sind
  mainstream-vertretbar; Mass-Trim hätte grosse Test-/Zahlen-Verschiebung ohne klaren
  Korrektheitsgewinn ausgelöst → nur die genuin optimistischen Alternatives gesenkt.

## Konsequenzen

- Angezeigte Hauptlinien sinken leicht (Vol-Drag) → konservativer + konsistent zum Fächer.
- Alternatives werden in der Optimierung weniger attraktiv (tiefere erwartete Rendite).
- Determinismus + Konsistenz sind durch Regressionstests gesichert
  (`test_engine_methodik_invariants`, `test_deterministic_ito_growth`,
  `test_goal_pessimistic_quartile`, `test_cma_conservative_alternatives`,
  `test_illiquid_cap`, `test_anlagephilosophie_no_timing`).
- Methodik-Transparenz: siehe `docs/methodology/5eyes-engine-whitepaper.md`.

## Referenzen

- Whitepaper: `docs/methodology/5eyes-engine-whitepaper.md`
- Anlagephilosophie: ADR-003
- Roadmap: `docs/planning/2026-06-18-roadmap-200-detailliert.md`
