# Engine-Validierung 2026-06-11 — Befunde

Multi-Agent-Validierung (Cashflow, Zielmatrix/Goals) + adversariale Verifikation.
Fokus: Rechen-/Darstellungsfehler und 3eyes-Divergenzen.

## Cashflow — GEFIXT (Commit fix(cashflow), Branch audit/engine-validation)
- **A (kritisch, Anzeige):** IST-Summary (Total Einnahmen/Ausgaben/Saldo) annualisierte
  wiederkehrende Flows nicht → 12x/4x/2x zu tief. Fix: Single-Source aus Backend-Summary.
- **B (hoch, Anzeige):** Frontend-Summary filterte wiederkehrende Flows nicht nach
  valid_from/until. Fix: via Backend-Summary + Fenster-Check im Fallback.
- **C (niedrig, Engine):** `_add_months` Day-Drift → Off-by-one an valid_until-Grenze.
  Fix: Occurrences index-basiert vom Anker + Regressionstest.
- Engine/Optimierung war NIE betroffen — nur die angezeigte Beraterzahl.

## Goals — GEFIXT
- **#4 (hoch):** Rank→Weight-Tabelle divergent (`_DEFAULT_WEIGHT_BY_RANK` {1:1875,...}
  vs `GOAL_WEIGHT_BY_RANK` {1:10000,...}) bei falschem "konsistent"-Kommentar →
  Goals im Optimizer anders gewichtet als in der Score-Aggregation. Fix: angeglichen
  ({1:10000,2:5000,3:2500,4:1250,5:625}) + Paritäts-Test.
- **#1 (hoch):** `probability_pct` (bedingte Goals) wurde in goal_liabilities ignoriert
  (Spec-4.4-Verstoss, Divergenz zur Reserve-Engine). Fix: `_goal_probability_factor`
  (spiegelt portfolio_engine) auf Wealth/Einmalige/wiederkehrende Outflow-Builder
  angewandt + Test (prob=50 → halbe Liability).

## Goals — OFFEN (dokumentiert, bewusst nicht unter Token-Druck blind gefixt)

### #2 (hoch, opt-in Stochastic): Renditeziel-Shortfall in bps statt CHF
`_build_renditeziel` setzt `target_kind="return_rate"`, `target_amount_rappen=target_bps`.
`objective.py` rechnet shortfall² in bps² (~1e8) für return_rate, aber in Rappen² (~1e16)
für wealth_at_t — gemischte Einheiten in einer Objective-Summe. In gemischten Goal-Sets
ist das Renditeziel im primären SLSQP-Shortfall faktisch unsichtbar (Verhältnis ~6e10).
Spec OD-C/§2.3 verlangt: Renditeziel als impliziertes `wealth_at_t` = initial·(1+r)^horizon.
Die Chance-Constraint (P-Ampel) honoriert OD-C bereits — nur das primäre Objective nicht.
**Nur OPTIMIZER_MODE=stochastic (opt-in, Default house_matrix).** Fix: `_build_renditeziel`
auf wealth_at_t mappen (braucht initial_value_rappen im Builder-Kontext). Risiko: ändert
Solver-Verhalten → Optimizer-Tests gegenprüfen.

### #3 (medium, MC-Fächer produktiv sichtbar): Ein-Jahr-Inflations-Versatz
`scenario_engine` wendet `wealth[t+1] = grown + cashflow[t] − liability[t]` an (CF und
Liability auf derselben t→t+1-Stufe). `cashflow_timeline._compound_inflation_factor`
nutzt offset 0 = heute = 1.0, während die real-mode Goal-Liabilities via `_inflate_at_year`
einen Inflationsterm mehr pro Stufe tragen. Folge: real-mode Ziele leicht überinflationiert
relativ zu Cashflows. Fix: Inflations-Origin beider Module auf dasselbe Jahr eichen
(liability mit `year_index-1` statt `year_index`). **Risiko: verschiebt ALLE MC-Pfade →
viele MC-Tests müssen neu kalibriert werden.** Vor Fix: numerisch quantifizieren.

### #5 (medium, Default-Pfad): Renditeziel Brutto- vs Netto-Rendite
Deterministische Zielmatrix (`_build_goal_analysis`) wertet Renditeziel-Erfolg gegen die
**Brutto**-Portfolio-Rendite (ohne Outflow-Subtraktion), MC/Optimizer gegen die
**outflow-reduzierte Netto**-Rendite. → Renditeziel kann deterministisch "erreicht",
im MC "verfehlt" sein. Fix: konsistente Definition (Renditeziel als outflow-freie
Allokations-Eigenschaft; im MC separater deficit-freier Rendite-Pfad). Braucht
Fach-Entscheid was "korrekt/3eyes" ist.

### #6 (niedrig, Doku/UI): Zwei Goal-Status-Vokabulare
Deterministisch: Score-Buckets 70/45 (On Track/Prüfen/Gefährdet). Optimizer:
Wahrscheinlichkeits-tau 80/50. Keine gemeinsame Schwellen-Doku. Fix: engine-spec
ergänzen + UI-Badges eindeutig als "Score" vs "Wahrscheinlichkeit" labeln.

## Hinweis
#2/#3/#5 brauchen Fach-/Design-Entscheide bzw. MC-Neukalibrierung — separat und
verifiziert angehen, nicht beiläufig.
