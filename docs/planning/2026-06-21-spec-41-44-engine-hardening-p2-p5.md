# Spec — Roadmap #41–44: Engine-Hardening P2 / P3 / P4 / P5

**Datum:** 2026-06-21
**Branch:** `codex/u41-engine-hardening`
**Scope:** Verifikations- & Robustheits-Härtung der Wealth-/Optimizer-Engine.
**Maxime:** Pinned-Test VOR jedem Refactor. Kein Umbau ohne Not. Jeder Fix empirisch belegt.

---

## 0. Kontext & Abgrenzung (WICHTIG, vor Beginn lesen)

Der ursprüngliche CTO-3-Phasen-Plan (P1–P5 = A1–A4 / B1–B3 / C1–C2) ist
**bereits vollständig gemerged** (PRs #213–#228, alle 2026-06-07/08; Quelle:
Memory `project_5eyes_engine_hardening_plan.md`, Sprint-Tracking-Tabelle, alle
Zeilen „✓ MERGED").

Die Roadmap-Einträge **#41–#44** (`docs/planning/2026-06-14-roadmap-master.md:62-65`)
sind generische Platzhalter („offenen Punkt P2/P3/P4/P5 des CTO-Audits umsetzen").
Die **substanziell noch offenen** Engine-Härtungspunkte sind die zwei verbliebenen
Befunde aus der Engine-Validierung 2026-06-11 plus zwei dazugehörige Verifikations-/
Robustheits-Pakete. Diese Spec mappt #41–#44 auf konkrete, implementierungsfertige Arbeit:

| Roadmap | Diese Spec | Thema | Quelle IST |
|---------|-----------|-------|-----------|
| **#41 (P2)** | **HP-1** | MC-Inflations-Offset: Konventions-Entscheid + Recalibration | Findings #3 (`docs/audits/2026-06-11-engine-validation-findings.md:37-46`) |
| **#42 (P3)** | **HP-2** | Renditeziel brutto/netto: gross-growth-product opt-in | Findings #5 (`…findings.md:48-58`) |
| **#43 (P4)** | **HP-3** | Determinismus-/Drift-Pins + Parität deterministisch↔MC für Renditeziel | abgeleitet aus HP-1/HP-2 Regressionsfläche |
| **#44 (P5)** | **HP-4** | Engine-Invarianten-Härtung (Shape-/Pad-/NaN-Guards in `simulate_wealth_paths`) | `scenario_engine.py:362-534` |

**Bewusst NICHT in dieser Spec** (eigene Specs, nur referenzieren):
- Sub-Asset-Klassen-Tiefe / Block-Diagonal-Korrelation → Roadmap **#45**.
- Currency-aware Optimizer (FX-Risiko/Hedging) → Roadmap **#47**.
- Steuer in Netto-Cashflow / Tax-aware Objective → Roadmap **#39 / #46**.
Diese drei Engine-Major-Gaps (Sub-Alloc/Tax/Currency) wurden in B1/B2/B3 bereits
implementiert (`docs/audits/2026-06-07-b{1,2,3}-*.md`); die Roadmap-#45/#46/#47
sind reine Optimizer-Objective-Erweiterungen darüber — hier NICHT dupliziert.

**Verifizierte Datei-Anker (alle per Read am 2026-06-21 geprüft):**
- Engine-Kern: `5eyes-backend/services/portfolio_engine.py` (7997 Zeilen)
- Solver-MC-Loop: `5eyes-backend/services/optimizer/scenario_engine.py`
- Objective/Goal-Driver: `5eyes-backend/services/optimizer/objective.py`
- Goal→Liability + Inflation: `5eyes-backend/services/optimizer/goal_liabilities.py`
- Tests: `5eyes-backend/tests/` (z. B. `test_optimizer_scenario_engine.py`,
  `test_cashflow_in_mc_integration.py`, `test_chance_constraint.py`,
  `test_engine_reference_mandates.py`)

---

## HP-1 (#41 / P2) — MC-Inflations-Offset: Konventions-Entscheid + Recalibration

### Was genau
Im MC-Wealth-Loop tragen, am selben Wealth-Schritt, **Cashflow** und **Liability**
unterschiedlich viele Inflationsterme. Die Inflations-FUNKTIONEN sind identisch
(`_cumulative_inflation_factor(T)` == `_compound_inflation_factor(start, start+T)`,
beide = T multiplikative Terme — verifiziert in Findings #3). Der Versatz ist eine
reine **Index-Konvention**: real-mode-Ziele tragen pro Schritt **genau einen
Inflationsterm (~2 %/Jahr) mehr** als Cashflows.

### IST (verifiziert, file:line)
- Wealth-Update: `scenario_engine.py:530` (mit Mortality-Maske) bzw.
  `scenario_engine.py:532` (1D-Fallback):
  ```python
  wealth[:, t + 1] = grown + cashflow_per_path[:, t] - liability_per_path[:, t]   # :530
  wealth[:, t + 1] = grown + cashflow[t]            - liability[t]                # :532
  ```
  → am Wealth-Schritt für Jahr `t+1` (1-based `k=t+1`) trägt der Cashflow-Term
  `series[t]` = `series[k-1]` (**Beginn-of-Year**, k−1 Terme), die Liability
  (Goal `target_year_index=k`, real-inflationiert via `_inflate_at_year`) = **k Terme**
  (**End-of-Year**).
- Inflations-Faktor: `goal_liabilities.py:_cumulative_inflation_factor:238-254`
  (k Terme für year_index=k) und `_inflate_at_year:257-264` (1-based: Jahr k →
  `_cumulative_inflation_factor(k)`).
- Cashflow-Series wird außerhalb des Loops gebaut und 0-basiert übergeben
  (`scenario_engine.py:429-435`: Pad/Trim auf `horizon`, kein Index-Shift).

### OWNER-DECISION OD-HP1 (nötig, vor Implementierung) ⚠️
**Frage:** Sind Cashflows Beginn-of-Year oder End-of-Year zu modellieren?
- **Option A — Cashflows = End-of-Year** (Cashflow um +1 Term inflationieren →
  Liability bleibt). Fachlich: Lohn/AHV/Ausgaben fallen über das Jahr an, am
  Jahresende real entwertet — konsistent mit der Goal-Konvention.
- **Option B — Liability = Beginn-of-Year** (Liability `year_index-1` Terme →
  Cashflow bleibt). Fachlich: Ziel wird zu Jahresbeginn bewertet.

**Empfehlung (zur Bestätigung):** **Option A**. Begründung: Goals nutzen bereits
durchgängig die End-of-Year-Inflation (`_inflate_at_year`, 1-based); Cashflows an
dieselbe Konvention zu ziehen ist die kleinere Code-Änderung und lässt die
fachlich dokumentierte Goal-Bewertung unangetastet. **Konservativ** (Maxime
„tieferer Wert"): Cashflow-Inflationierung senkt reale Netto-Einzahlungen leicht →
vorsichtigere Wealth-Pfade.

### Konkrete Code-Änderung (Option A — anzupassen falls OD-HP1 = B)
1. Cashflow-Series an der **Bau-Stelle** (NICHT im Hotloop) um einen Inflationsterm
   verschieben: an der Stelle, wo `cashflow_series_rappen` für `simulate_wealth_paths`
   real aufbereitet wird, jeden Eintrag `series[i]` mit
   `_cumulative_inflation_factor(i+1, inflation_series_bps)` statt `i` skalieren
   (so trägt Schritt k = i+1 dann k Terme — gleich der Liability).
   - Falls die Cashflow-Series bereits inflationiert ankommt: den Aufruf der
     real-Skalierung um `+1` Term anheben (Single-Source: dieselbe Helper-Funktion
     verwenden, die Goals nutzen — `_inflate_at_year`/`_cumulative_inflation_factor`).
2. **Kein** Eingriff in den Hotloop `scenario_engine.py:530/532` (Index bleibt `t`).
3. Konvention in `docs/engine-spec.md` (Sektion `simulate_wealth_paths` / Inflation)
   dokumentieren: „Cashflows und Liabilities tragen am selben Wealth-Schritt
   identisch viele Inflationsterme (Option A: beide End-of-Year)."

### Risiko / Recalibration
**Verschiebt ALLE real-mode-MC-Pfade.** Vorgehen Pinned-Test-First:
1. **Vor** der Änderung: aktuelle MC-Outputs für die 5 Reference-Mandate
   (`test_engine_reference_mandates.py`) mit festem Seed snapshotten.
2. Nur für **real-mode** Mandate (M1 Pensionär-Decumulation, M5 Cashflow-heavy)
   sind Drifts erwartet → Erwartungs-Ranges in der Reference-Suite neu kalibrieren,
   mit Kommentar `# recal HP-1 (OD-HP1=A): +1 Inflationsterm Cashflow`.
3. nominal-only Mandate (M2 Akkumulation ohne real-Goals) müssen **bit-identisch**
   bleiben (Regressions-Guard, s. Pinned-Test).

### Pinned-Test
Neu in derselben Datei: `tests/test_inflation_offset_convention.py` (oder als Klasse
in `test_optimizer_scenario_engine.py`):
- `test_cashflow_and_liability_same_inflation_terms`: konstruiere real-mode Goal
  `target_year_index=k` + Cashflow am selben Jahr; assert dass beide nach der
  Änderung mit `_cumulative_inflation_factor(k)` skaliert sind (identische Termzahl).
- `test_nominal_mode_paths_unchanged`: nominal-only Mandat → Wealth-Pfade
  bit-identisch zu Pre-Change-Snapshot (feste Seeds), beweist eingegrenzten
  Blast-Radius.
- `test_real_mode_offset_quantified`: 1 real-Goal, 1 Cashflow, 1 Jahr → der
  Unterschied vor/nach Fix beträgt genau einen Inflationsterm (`~ infl[0]`),
  numerisch verankert.

---

## HP-2 (#42 / P3) — Renditeziel brutto vs. netto: gross-growth-product (opt-in)

### Was genau
Das Renditeziel wird **deterministisch brutto** (Strategie-Performance,
`expected_return_bps`) bewertet, im **MC/Optimizer aber netto** (liability-
reduzierter `wealth_paths`). → Ein Renditeziel kann deterministisch „erreicht",
im Optimizer „verfehlt" sein, sobald Outflows die Wealth drücken.

### OWNER-DECISION (bereits ENTSCHIEDEN ✅, Findings #5)
**Renditeziel = Strategie-Performance = BRUTTO / deficit-frei** (User-Entscheid
2026-06-12, konsistent zur #AA-5-TWR-Entscheidung). Keine erneute Entscheidung nötig.

### IST (verifiziert, file:line)
- **Deterministisch (bereits brutto, korrekt):** `portfolio_engine.py:_build_goal_analysis`
  — `goal_type == "Renditeziel"` (`:2742`) prüft
  `expected_return_bps >= goal.target_return_bps` (`:2745-2746`). ✅ Konform.
- **MC/Optimizer (netto, abweichend):** Renditeziel wird gegen den liability-/
  cashflow-reduzierten `wealth_paths` gerechnet:
  - `objective.py:shortfall_squared_per_path` `return_rate`-Zweig (`:139-155`):
    `target_wealth = initial·(1+r)^h`, verglichen mit `wealth_paths[:, horizon]`
    (= netto, Liability bereits abgezogen, vgl. Docstring `:131-133`).
  - `objective.py:goal_probability_per_path` `return_rate`-Zweig (`:191-195`):
    identisch gegen `wealth_paths[:, horizon]`.
- Wealth-Pfade enthalten Cashflow/Liability ab `scenario_engine.py:530/532`.

### Konkrete Code-Änderung
**Plan aus Findings #5 (`…findings.md:54-58`): ein gross-growth-product pro Pfad,
billig (eine Multiplikation/Jahr, liability-/cashflow-frei), opt-in, Fallback =
aktuelles Verhalten.**

1. `scenario_engine.py:simulate_wealth_paths` — neuer Kwarg
   `return_gross_growth: bool = False`. Im Loop pro Schritt das **Markt-Wachstums-
   Verhältnis vor Cashflow/Liability/Tax** akkumulieren (analog #AA-5 TWR-Faktor-
   Verkettung), liability-/cashflow-frei:
   ```python
   # vor der Schleife:
   if return_gross_growth:
       gross_growth = np.ones(n_paths, dtype=np.float64)   # (n_paths,)
   # in der Schleife, NACH portfolio_factor (:482), VOR den Tax-/CF-Schritten:
   if return_gross_growth:
       gross_growth *= portfolio_factor
   # Rückgabe:
   return (wealth, gross_growth) if return_gross_growth else wealth
   ```
   - **Brutto = vor Tax** (Strategie-rein, konsistent zu #AA-5 „brutto-of-Rebalancing-
     Kosten"); falls OWNER später netto-of-Tax-Renditeziel will → separater Schalter.
   - Backwards-Compat: Default `False` → Rückgabe-Typ unverändert (`np.ndarray`).
2. `objective.py` — `shortfall_squared_per_path` und `goal_probability_per_path`
   um optionalen Kwarg `gross_growth_per_path: np.ndarray | None = None` erweitern.
   Im `return_rate`-Zweig (`:139` / `:191`): wenn gesetzt, brutto-Endwert
   `gross_end = initial·gross_growth_per_path` statt `wealth_paths[:, horizon]`
   verwenden; sonst Fallback = aktuelles (netto) Verhalten.
   ```python
   if liability.target_kind == "return_rate":
       target_wealth = max(1.0, initial_wealth_rappen) * ((1.0+target_return)**horizon)
       if gross_growth_per_path is not None:
           end = max(1.0, initial_wealth_rappen) * gross_growth_per_path   # brutto
       else:
           end = wealth_paths[:, horizon]                                  # Fallback netto
       shortfall = np.maximum(0.0, target_wealth - end)
       return shortfall * shortfall
   ```
3. Den `gross_growth`-Vektor durch die **~6 Solver-Pfad-Funktionen** durchreichen
   (Signatur opt-in, Default None). Verifizierte Aufrufstellen:
   - `solver.py:182` (`simulate_wealth_paths`-Aufruf — hier `return_gross_growth=opt_in`)
   - `objective.py:236` (`goal_probability_per_path`), `:318` & `:415`
     (`shortfall_squared_per_path`), `:466` (`chance_constraint_penalty`)
   - `solver.py:1063` & `:1113` (`chance_constraint_penalty` für Achievability-Rows)
   - `stress_scenarios.py:134` (`simulate_wealth_paths` — gross-growth dort optional)
   → `chance_constraint_penalty` reicht `gross_growth_per_path` an
   `goal_probability_per_path` weiter (Signatur erweitern).
4. Opt-in-Gate: ENV `OPTIMIZER_GROSS_RETURN_GOAL` (Default `"0"` = aktuelles
   Verhalten), Helper analog `objective._goal_weighting_mode():47-54`. Bei `"1"`
   wird `return_gross_growth=True` gesetzt und der Vektor durchgereicht.

### Risiko
Solver-Hotloop + breite Signatur-Fläche (6 Funktionen). Daher **opt-in mit
Fallback** → 0 Regression bei Default. Eingebrochene Pfade: `gross_growth` bleibt
positiv (reines Marktwachstum, kein Wealth-Floor) → keine `<=0`-Sonderbehandlung nötig.

### Pinned-Test
Neu `tests/test_gross_return_goal.py`:
- `test_gross_growth_product_liability_free`: identischer Seed, einmal mit großem
  Liability-Outflow, einmal ohne → `gross_growth_per_path` **identisch** (beweist
  liability-/cashflow-Freiheit), `wealth_paths[:, horizon]` divergiert.
- `test_return_goal_brutto_vs_netto_diverges`: Mandat mit Renditeziel + großem
  Outflow → netto verfehlt, brutto erreicht; assert Achievability(brutto) >
  Achievability(netto).
- `test_default_off_no_regression`: ohne ENV-Flag liefert
  `shortfall_squared_per_path` / `goal_probability_per_path` bit-identische
  Resultate wie vor dem Patch (Fallback-Pfad).
- `test_deterministic_mc_brutto_parity`: bei aktiviertem Flag stimmt die MC-
  Renditeziel-Erreichung mit der deterministischen `_build_goal_analysis`-Bewertung
  (`:2745`) im Vorzeichen überein (beide brutto) → schließt die Findings-#5-Lücke.

---

## HP-3 (#43 / P4) — Determinismus-/Drift-Pins + deterministisch↔MC-Parität

### Was genau
HP-1 und HP-2 verändern MC-Pfade bzw. führen einen zweiten Bewertungspfad ein.
P4 pinnt die **Verifikations-Eigenschaften** dauerhaft, damit künftige Refactors
die in der Engine-Validierung erkämpfte Konsistenz nicht stillschweigend brechen.
(Reine Verifikations-Härtung — kein neuer Produktiv-Code außer evtl. Test-Hooks.)

### IST (verifiziert, file:line)
- Reference-Mandate-Suite existiert: `tests/test_engine_reference_mandates.py`
  (A2/A4, PR #216/#219). → erweitern, nicht neu erfinden.
- Renditeziel-Definition ist an **drei** Stellen kodiert, die übereinstimmen
  müssen: deterministisch `_build_goal_analysis:2745-2746`, MC-Shortfall
  `objective.py:148-155`, MC-Probability `objective.py:191-195`. Findings #2 stellte
  bereits Shortfall↔Probability gleich (`objective.py:140-147` Kommentar) — die
  deterministisch↔MC-Achse bleibt ungepinnt.

### Konkrete Änderung (nur Tests + ggf. Doku)
1. **Determinismus-Pin:** Reference-Mandate zweimal mit identischem Seed rechnen →
   bit-identische `wealth_paths` (kein versteckter RNG-State, kein Loop-Order-Drift).
2. **Renditeziel-Single-Definition-Pin:** Property-Test, dass für gegebenes
   `(initial, target_return, horizon)` das implizite Wealth-Target in allen drei
   Stellen identisch ist (`initial·(1+r)^h`).
3. **HP-1/HP-2-Koppel-Pin:** mit OD-HP1=A **und** `OPTIMIZER_GROSS_RETURN_GOAL=1`
   die volle Pipeline der 5 Mandate gegen neu kalibrierte Ranges; Snapshot-Update
   dokumentiert in `docs/audits/` (neuer Eintrag, NICHT in dieser Spec-Datei).
4. engine-spec §4.x: Cross-Reference-Zeile „Renditeziel-Definition (3 Stellen,
   identisch)" ergänzen.

### Pinned-Test
Erweiterung `tests/test_engine_reference_mandates.py` (oder neu
`tests/test_engine_hardening_invariants.py`):
- `test_mc_determinism_same_seed`: zweimal gleicher Seed → `np.array_equal`.
- `test_return_goal_target_single_source`: implizites Target in det./MC-shortfall/
  MC-prob identisch (parametrisiert über mehrere `(r,h)`).
- `test_reference_mandates_within_audited_ranges`: alle 5 Mandate End-to-End in
  Ranges (mit HP-1/HP-2 ein-/ausgeschaltet via Fixture-Param).

---

## HP-4 (#44 / P5) — Engine-Invarianten-Härtung in `simulate_wealth_paths`

### Was genau
Defensive Robustheit am Kern-Hotloop: explizite Shape-/Endlichkeits-Guards, damit
fehlerhafte Inputs **früh und klar** scheitern statt stiller NaN-Propagation durch
die ganze Optimierung. (Findings A1/A3 stellten die strukturelle Korrektheit fest;
P5 härtet die Eingangs-Contracts.)

### IST (verifiziert, file:line) — `scenario_engine.py:362-534`
- `n_buckets`-Check vorhanden (`:426-427` `ValueError`). ✅
- `dividend_yield`-Shape-Check (`:467-470`), `death_year_index`-Shape-Check
  (`:450-453`). ✅
- **Lücke:** `weights` wird `reshape(N_BUCKETS)` (`:424`) **ohne** Längen-Validierung
  → falsche Länge wirft kryptisches `cannot reshape`; keine Summen-/Negativ-Prüfung
  (Docstring `:380` sagt „keine Constraint hier").
- **Lücke:** `cashflow`/`liability` werden bei falscher Shape **still** gepaddet/
  getrimmt (`:430-435`, `:441-445`) — kein Warn-/Fail-Pfad bei grob falscher Länge
  (z. B. Series doppelt so lang = stiller Datenverlust).
- **Lücke:** kein Guard gegen nicht-endliche Inputs (`NaN`/`inf` in `return_paths`/
  `cashflow`/`liability`) → propagiert still in `wealth`.

### OWNER-DECISION OD-HP4 (klein, Default vorgeschlagen)
Trim-Verhalten bei **leicht** abweichender Series-Länge: **warnen, nicht hart
werfen** (Backwards-Compat zu bestehenden Aufrufern, die kurze Series liefern).
Hartes `ValueError` nur bei nicht-endlichen Werten und bei `weights`-Längenfehler.
→ Vorschlag: Default annehmen; `STRICT_ENGINE_INPUTS=1` macht auch Trim zum Fehler.

### Konkrete Code-Änderung — `scenario_engine.py`
Direkt nach `:424` (`weights = …reshape`) bzw. vor der Schleife:
```python
if weights.size != N_BUCKETS:
    raise ValueError(f"weights must have {N_BUCKETS} elements, got {weights.size}")
if not np.all(np.isfinite(weights)):
    raise ValueError("weights contains non-finite values")
if not np.all(np.isfinite(return_paths)):
    raise ValueError("return_paths contains non-finite values")
```
Bei den Pad/Trim-Blöcken (`:430-435`, `:441-445`): wenn
`cashflow.size != horizon` → `logging.warning(...)` (bzw. `ValueError` unter
`STRICT_ENGINE_INPUTS`); nach dem `np.asarray` zusätzlich
`NaN`/`inf`-Verbot → bei nicht-endlichen Werten `ValueError`. **Hotloop selbst
(`:480-532`) bleibt unverändert** (keine Per-Iter-Checks → keine Performance-Kosten).

### Risiko
Minimal — reine Eingangs-Guards vor dem Loop. Bestehende valide Aufrufer
(verifiziert: `solver.py:182`, `stress_scenarios.py:134`) liefern korrekte Shapes
→ keine Verhaltensänderung im Happy-Path.

### Pinned-Test
Neu `tests/test_simulate_wealth_paths_guards.py`:
- `test_wrong_weights_length_raises` / `test_nonfinite_returns_raises` /
  `test_nonfinite_cashflow_raises`.
- `test_short_cashflow_warns_not_raises` (Default) und unter
  `STRICT_ENGINE_INPUTS=1` → `ValueError`.
- `test_happy_path_unchanged`: valider Input → Output bit-identisch zu Pre-Patch
  (Snapshot), beweist 0 Regression im Produktiv-Pfad.

---

## Reihenfolge & DoD

1. **HP-4** zuerst (reine Guards, 0 Regression, schafft sichere Basis).
2. **HP-1** (OD-HP1 einholen → Konvention → Recalibration der real-Mandate).
3. **HP-2** (gross-growth opt-in, Fallback).
4. **HP-3** zuletzt (pinnt HP-1+HP-2 dauerhaft).

**Definition of Done je HP:**
- Pinned-Test **vor** dem Refactor geschrieben (rot → grün).
- Volle Backend-Suite grün (`pytest 5eyes-backend/tests`), keine Regression in
  `test_optimizer_scenario_engine.py`, `test_chance_constraint.py`,
  `test_cashflow_in_mc_integration.py`, `test_engine_reference_mandates.py`.
- Default-Verhalten (ohne neue ENV-Flags) bit-identisch zu Pre-Patch (außer HP-1,
  das real-mode bewusst verschiebt → dokumentierte Recalibration).
- Doku: betroffene Stellen in `docs/engine-spec.md` aktualisiert; Recalibration-
  Memo in `docs/audits/` (neue Datei).

**OWNER-DECISIONs zusammengefasst:**
- ⚠️ **OD-HP1** (offen): Cashflow Beginn- oder End-of-Year? Empfehlung **End-of-Year
  (Option A)**.
- ✅ **OD-HP2** (entschieden): Renditeziel = brutto/deficit-frei.
- 🟡 **OD-HP4** (Default vorgeschlagen): Trim warnen statt werfen;
  `STRICT_ENGINE_INPUTS` opt-in.
