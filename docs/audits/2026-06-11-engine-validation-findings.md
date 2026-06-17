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

## Goals — Status 2026-06-12

### #2 (hoch, opt-in Stochastic): Renditeziel-Shortfall in bps statt CHF — GEFIXT ✅
`objective.shortfall_squared_per_path` rechnete für return_rate shortfall² in bps²
(~1e4-1e8), für wealth_at_t in Rappen² (~1e16) → in gemischten Goal-Sets war das Renditeziel
im primären SLSQP-Shortfall faktisch unsichtbar. Fix: return_rate-Shortfall via impliziertem
Wealth-Target `initial·(1+r)^h` in Rappen (Spec §4.1: annualized ≥ target ⇔ end_wealth ≥
initial·(1+target)^h). **IDENTISCH zu `goal_probability_per_path`** → primäres Objective und
Chance-Constraint (P-Ampel) nutzen jetzt dieselbe Definition. Nur OPTIMIZER_MODE=stochastic.
Verifiziert: 2 neue Tests (impliziertes Target + Kommensurabilität zu wealth_at_t) + volle
Suite grün (3853 passed).

### #3 (medium, MC, real-mode Goals): Ein-Jahr-Inflations-Versatz — QUANTIFIZIERT, dediziert
**Numerische Quantifizierung 2026-06-12:** Die Inflations-FUNKTIONEN sind identisch
(`_cumulative_inflation_factor(T)` == `_compound_inflation_factor(start, start+T)` = T Terme).
Der Versatz ist rein eine **Index-Konvention** im Szenario-Loop `wealth[t+1] = grown +
cashflow[t] − liability[t]`: am Wealth-Schritt k trägt der Cashflow `series[k-1]` = k−1 Terme
(Beginn-of-Year-Konvention), die Liability (Goal year-index k, `path[k-1]`) = k Terme
(End-of-Year). → real-mode Ziele tragen **genau einen Inflationsterm (~2%/Jahr) mehr** als
Cashflows am selben Schritt. **Fach-Entscheid nötig** (Cashflows Beginn- oder End-of-Year?),
dann liability `year_index-1` ODER cashflow `offset+1` angleichen. **Risiko: verschiebt ALLE
real-mode-MC-Pfade → MC-Tests neu kalibrieren.** → dedizierter Sprint (Konvention + Recalibration).

### #5 (medium): Renditeziel Brutto- vs Netto-Rendite — ENTSCHIEDEN (brutto), Implementierung dediziert
Deterministische Zielmatrix (`_build_goal_analysis:2693`) wertet Renditeziel gegen
`expected_return_bps` (**brutto**/strategie-rein), MC/Optimizer gegen den liability-reduzierten
`wealth_paths[:, horizon]` (**netto**). → Renditeziel kann deterministisch "erreicht", im
Optimizer "verfehlt" sein, wenn Outflows die Wealth drücken. **User-Entscheid 2026-06-12
(konsistent zur #AA-5-TWR-Entscheidung): Renditeziel = Strategie-Performance = BRUTTO/
deficit-frei.** Implementierungsplan: `simulate_wealth_paths` akkumuliert ein gross
growth-product pro Pfad (cheap, eine Multiplikation/Jahr, liability-/cashflow-frei) und gibt
es als optionalen Zusatz-Output zurück; `shortfall_squared_per_path` + `goal_probability_per_path`
nutzen es für return_rate (Fallback: aktuelles Verhalten). Berührt ~6 Solver-Pfad-Funktionen
(Signatur, opt-in) → dedizierter, verifizierter Sprint (Solver-Hotloop, Regressions-Fläche).

### #6 (niedrig, Doku/UI): Zwei Goal-Status-Vokabulare — GEFIXT ✅ (2026-06-12)
Deterministisch: Score-Buckets 70/45 (On Track/Prüfen/Gefährdet). Optimizer:
Wahrscheinlichkeits-tau 80/50 (erreichbar/knapp/nicht_erreichbar). Keine gemeinsame
Schwellen-Doku. Fix: engine-spec §4.5 dokumentiert beide Systeme (Kennzahl/Schwellen/
Begriffe/Code + warum sie bewusst getrennt sind — Punkt-Schätzer vs Verteilungs-Aussage)
+ UI-Tooltips am deterministischen Badge. Bewusst NICHT zwangsangeglichen.

## Hinweis — Status 2026-06-12
#1/#4/#6 GEFIXT. #2 GEFIXT (impliziertes Wealth-Target, opt-in stochastic). #5 (Brutto/Netto-
Renditeziel) + #3 (MC-Inflations-Offset) verbleiben — siehe unten.

## Asset Allocation — 9 bestätigte Befunde (6-Agent-Audit + Verifikation, alle Production-Pfad)

### #AA-1 (KRITISCH, EMPIRISCH BESTÄTIGT): Kapitalschutz crasht generate_target_allocation
Bonds-Bucket-Risky-Fraction = ungewichteter BB-Mittel (2000+2500+5000+4000)/4 = 3375 bps
(`constraints.py:bucket_risky_fractions_from_building_blocks:189-224`, Docstring gibt
Vereinfachung zu). Kapitalschutz-Cap = 3000. Bonds-Band-Min 6500 dominiert → keine
Allokation ≤ 3000 möglich → `assert_risk_budget_ok` (portfolio_engine.py:5824, NICHT
gefangen) wirft `RiskBudgetExceeded: Ist=4248, Limit=3000`. **Empirisch reproduziert**
(tests/test_kapitalschutz_risk_budget_regression.py, xfail). **Jedes Score-1-2-Mandat
crasht.** Fix-Optionen: (A) sub-allocation-gewichtete Risky-Fraction (korrekt, Docstring-
bestätigt, aber MC/Tests neu kalibrieren), (B) Cap-Review konsistent zu 3375, (C) graceful
konservativer Fallback statt Crash. **TOP-PRIORITÄT, dediziert + voll verifiziert angehen.**

### #AA-2 (→ LOW, Test-Qualität): Konsistenz-Test gibt falsche Sicherheit — ENTSCHÄRFT (2026-06-12)
`test_house_matrix_risk_budget_consistency.py` nutzt hardcoded bonds=2250 statt produktivem
Mittel 3375 → war grün trotz Crash. **Die gefährliche false-confidence (grün-trotz-Crash) ist
durch den #AA-1-Fix aufgelöst** (Engine crasht nicht mehr, #AA-3 ebenfalls gelöst). Der Test
bleibt als komplementärer **Design-Buffer-Check** (haben die HM-Caps Headroom für eine
repräsentative Mid-Allokation) gültig. **Bewusst NICHT umgestellt** (Maxime „kein Umbau ohne
Not"): Den hardcoded-Wert auf den ungewichteten Produktiv-Mittelwert 3375 zu ziehen würde einen
FALSCH-fehlschlagenden Test erzeugen, weil die Engine post-#AA-1 das sub-allocation-GEWICHTETE
Maß nutzt, nicht den ungewichteten Mittelwert. Optionaler Folge-Refactor (separat): Test aus
`bucket_risky_fraction_bps_from_building_blocks` + realer Sub-Allokation speisen, um Engine-Pfad
und Design-Buffer-Check zu vereinheitlichen — kein Produktions-Impact.

### #AA-3 (HOCH): Defensiv/Ausgewogen verletzen systematisch ihr Budget → immer Mid-Reset-Fallback — GELÖST ✅ (2026-06-12, via #AA-1)
Mit produktivem Mittel 3375: Defensiv realized 5012 > Cap 4500, Ausgewogen 6306 > 6000.
Crashte NICHT (Fallback fing), aber JEDES Defensiv/Ausgewogen-Mandat lief in WARN_FALLBACK
(Mid-Reset) statt sauberer SAA. **Gelöst durch #AA-1 Fix A** (sub-allocation-gewichtete
Risky-Fraction): empirisch generieren Defensiv (Score 35) und Ausgewogen (Score 55) jetzt
mit **0 Warnungen, kein WARN_FALLBACK, kein Mid-Reset** — realized ≤ Cap. Verankert in
test_kapitalschutz_risk_budget_regression.py (Assertion: keine Fallback-Warnung für 35/55).

### #AA-4 (HOCH, MC-Report): 1-Jahres-VaR/CVaR/Loss-Probability durch Cashflow verfälscht — GEFIXT ✅ (2026-06-12)
Jahr-1-Rendite enthielt Cashflow-Einzahlung (`_return_bps(target_start, target_by_year[1])`,
Post-Cashflow) → VaR/Loss-Prob zu klein (Verlustrisiko unterschätzt), bei Entnahmen zu groß.
Fix (portfolio_engine.py:~3116/3137/3187): Marktwert nach Wachstum, VOR Cashflow/Rebalancing
erfasst (`target_year1_market_value`) und als Basis der 1-J-Risikomasse genutzt. Verifiziert:
neuer Test (identischer Seed, Jahr-1-Risikomasse IDENTISCH mit/ohne 50%-Einzahlung — vorher
hätte die Einzahlung die Loss-Prob künstlich gesenkt) + 126 MC-/runtime-/scenario-Tests grün.
Test-Invarianten (var ≤ cvar ≤ 10000, loss_prob 0-100) unverändert erfüllt.

### #AA-5 (HOCH, MC-Report): Money-weighted Terminal-Value als CAGR fehletikettiert — GEFIXT ✅ (2026-06-12)
`target/current_annualized_return_p50_bps` (+ Renditeziel-success_rate/median/score) nutzten
`_annualized_return_bps(start, end_over_horizon)` = money-weighted (end/start enthält alle
Ein-/Auszahlungen) → eine Einzahlung vor einem guten Jahr hob die ausgewiesene Rendite
künstlich. **User-Entscheid 2026-06-12: time-weighted (TWR).** Fix (portfolio_engine.py:
neuer `_twr_annualized_bps` + Pre-/Post-Growth-Faktor-Verkettung im MC-Loop ~3121/3142/3187):
geometrische Verkettung der jährlichen MARKT-Wachstumsfaktoren (vor Cashflow). Eingebrochene
Pfade → -100% (Floor analog #AA-6). Verifiziert: TWR cashflow-timing-neutral (identisch mit/ohne
2x-Einzahlung bei Rebalancing) + 6 neue Tests + 155 annualized-/MC-/backtest-Tests grün.
**Hinweis:** TWR ist brutto-of-Rebalancing-Transaktionskosten (Kosten heben sich im
Faktor-Verhältnis auf) — Kosten-Drag 2. Ordnung, dokumentiert.

### #AA-6 (MEDIUM, MC): _annualized_return_bps gibt 0 statt -100% für aufgebrauchte Pfade — GEFIXT ✅ (2026-06-12)
Aufgebrauchte Pfade (end_value ≤ 0 = Totalverlust) flossen mit 0% statt -100% ein →
Median + Erfolgsrate nach oben verzerrt. Fix (portfolio_engine.py:~2806): `if end_value <= 0:
return -10000` (analog `_return_bps`). **Blast-Radius geringer als befürchtet:** die Metriken
(success_rate vs positives Renditeziel, median/p50) sind robust gegen Änderungen im unteren
Tail — der Median verschiebt sich nur bei >50% aufgebrauchten Pfaden (dann korrekt). Verifiziert:
5 neue Unit-Tests + 118 MC-/Backtest-/Goal-Tests grün (0 Regression).

### #AA-7 (HOCH): Themen-Tilt nutzt Total-Portfolio-bps als Per-Bucket-Wert — GEFIXT ✅ (2026-06-12)
`theme_total = 0.15 * targets["equities"]` (Portfolio-Raum), aber eq_splits leben im
Per-Bucket-Raum (Summe 10000, in `_append_split` renormalisiert) → effektive Themen-Gewichtung
war **größenabhängig** (empirisch: eq=8000→12%, eq=5000→7.5%, eq=2000→3%). Eine explizite
"overweight"-Präferenz wirkte für konservative Profile viel schwächer. Fix
(portfolio_engine.py:~3420): `theme_total = min(round(10000*0.15), 1200)` — Per-Bucket-Raum,
Cap 1200 (12%) bleibt → **konstante 12%** unabhängig von der Aktienquote. Verifiziert: 5 neue
Regressionstests (Größen-Unabhängigkeit über eq=8000/5000/2000 + Multi-Theme-Split) +
93 theme-/runtime-Tests grün.
**Hinweis Magnitude (tunbar):** typische Profile steigen von ~7.5% auf 12% Themen-Gewicht —
die 12% folgen aus dem bestehenden Cap 1200; der Wert ist über die Konstante anpassbar,
falls fachlich ein schwächerer/stärkerer Tilt gewünscht ist.

### #AA-8 (HOCH): Goal-Reserve nutzt max() statt Summe — GEFIXT ✅ (2026-06-12)
Mehrere gleichzeitige Nahziele wurden unterreserviert (nur das größte zählt). **Empirisch
bewiesen** (100k+50k → 100k statt 150k). Fix (`_compute_reserve_for_inputs`,
portfolio_engine.py:~4248-4308): Spending-Goal-Beiträge werden in `goal_reserve_sum`
SUMMIERT, dann als ein Kandidat via `max()` mit den Floor-Kandidaten (manuelle/Liquiditäts-
Reserve, Cashflow-Shortfall) kombiniert — Floor dominiert weiterhin wenn größer. Verifiziert:
4 neue Regressionstests (Summe / Floor-max / Einzelziel / Mid-Term-50%) + reserve-/optimizer-
Integration grün (113 Tests).

### #AA-9 (LOW): Banker's-Rounding in _risk_score_bucket
`int(round(score_x10/10))` (Banker's) bricht Monotonie + divergiert vom Profil-Namen-Mapping
(score 45/65). Fix: round-half-up (math.floor(x+0.5)), konsistent zu risk_scoring.py:118.
→ GEFIXT (siehe Commit).

## Empfehlung — STATUS 2026-06-12: alle AA-Befunde abgearbeitet ✅
#AA-1/#AA-3/#AA-4/#AA-5/#AA-6/#AA-7/#AA-8/#AA-9 GEFIXT + verifiziert + committet/gepusht (PR #263).
#AA-2 auf LOW herabgestuft (false-confidence durch #AA-1 weg). Jeder Fix empirisch bewiesen vor
dem Commit, mit eigenem Regressionstest. Verbleibend nur noch Goal #2/#3/#5/#6 (Fach-Entscheide /
opt-in stochastic / doc-UI) — siehe Goals-OFFEN-Sektion oben.

## FIX-Update 2026-06-11 (nach empirischer Verifikation)

### #AA-1 KRITISCH — GEFIXT ✅
Empirisch bewiesen (Kapitalschutz-Generierung crashte mit RiskBudgetExceeded), dann
3-teilig sauber behoben + verifiziert (test_kapitalschutz_risk_budget_regression.py jetzt
GRÜN, 48 Risk-Budget/Allokations-Tests grün):
1. **Konsistentes Risky-Maß:** Gate + finale Asserts (portfolio_engine.py:5754/5765/5827)
   nutzen jetzt das sub-allocation-gewichtete `risky_fraction_total_bps` (konsistent zur
   Enforcement-Cascade) statt des ungewichteten BB-Bucket-Mittels. (adressiert auch #AA-3
   teilweise: weniger spurious-Fallbacks.)
2. **`_enforce_risk_budget(allow_best_effort=True)`:** die letzte Eskalationsstufe gibt die
   konservativste ERREICHBARE Allokation zurück statt hart zu werfen.
3. **Graceful finaler Check:** bei strukturell unerreichbarem Budget konservativste
   Allokation + Compliance-Warnung statt Crash (Design-Absicht "Berater alarmieren" erfüllt,
   aber ohne 500). Kapitalschutz liefert jetzt z.B. {Aktien 5%, Obli 85%, Liq 10%} + Warnung.

### Verbleibend offen (dokumentiert) — Stand 2026-06-12
Nur noch Goals: #2 (Renditeziel bps↔CHF, nur OPTIMIZER_MODE=stochastic), #3 (MC-Inflations-Offset,
recalibration-risk), #5 (Brutto/Netto-Renditeziel, Fach-Entscheid), #6 (Status-Vokabular doc/UI).
Alle AA-Befunde (#AA-1 bis #AA-9) sind erledigt.
