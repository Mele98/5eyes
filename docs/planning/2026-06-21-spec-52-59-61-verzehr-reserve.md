# Spec #52 + #59 + #61 — Vermögensverzehr-Sockel · Goal-Liability-Doppelzählung · Reserve-Erklärbarkeit

**Status:** offen. Alle Verhaltensänderungen **opt-in** (default legacy), damit `tests/test_sequence_of_returns_depletion.py` grün bleibt.
**Erstellt:** 2026-06-21 (autonomer Spec-Sprint). Alle file:line per Read verifiziert.
**Branch-Vorschlag:** `codex/u52-verzehr-reserve`

---

## Kernbefunde (verifiziert)
1. **#59 (wichtigster):** MC-Verzehr nutzt NUR `cashflow_projection_series_rappen` (`portfolio_engine.py:3295,3330`) — Goals fliessen dort NICHT ein → **kein** Double-Count im MC. Das echte Risiko sitzt in der **Reserve**: wird dieselbe Ausgabe als `Cashflow(Expense)` UND als `Goal(Spending)` erfasst, fliesst sie in `near_term_shortfall_rappen` UND in das seit #AA-8 **summierte** `goal_reserve_sum` (`:4586-4600` + `:4608-4674`) → verdeckte Doppelzählung. Fix: Dedup-Guard.
2. **#52:** Heute KEIN Sockel-Konzept; `real_estate` wird als letzte Verzehr-Quelle geleert (`_apply_cashflow_to_bucket_values`, `:2009`). → opt-in Immobilien-Sockel separat mit `sockelIndexBps` indexieren, verzehrbares Vermögen mit konservativer Drawdown-Rendite.
3. **#61:** Reserve-Komponenten existieren nur als flache `reasoning`-Strings (`:6587`), im Report nicht ausgewiesen. → strukturierter `reserve_breakdown` aus `_compute_reserve_for_inputs` (`:4555-4703`) + `_build_reserve_narrative`.

## OWNER-DECISIONS (Defaults)
Konservative Drawdown-Rendite = **100 bps** · `sockelIndexBps` = **100 bps** · Sockel = nur selbstgenutzte Immobilie · #59-Verknüpfung = Heuristik (label+amount+Zeitraum) · Teil-Deckung = anteilig · alle Features opt-in.

---

## Codex-Prompt
```text
Branch: codex/u52-verzehr-reserve
Repo: C:\5eyes\5eyes_stage9_release_ready (5eyes-backend/)
Spec: docs/planning/2026-06-21-spec-52-59-61-verzehr-reserve.md

Implementiere Cluster #52/#59/#61. Alle Verhaltensänderungen OPT-IN (default legacy),
test_sequence_of_returns_depletion.py muss grün bleiben.

#52 Verzehr-Sockel (services/portfolio_engine.py):
- Konstanten _SOCKEL_INDEX_DEFAULT_BPS=100, _CONSUMABLE_DRAWDOWN_RETURN_DEFAULT_BPS=100 (Block ~:70-115).
- _verzehr_sockel_mode() (env VERZEHR_SOCKEL_MODE=sockel, default legacy), _split_sockel_and_consumable(), _index_sockel().
- _apply_cashflow_to_bucket_values (:1995) um draw_order-Param (default legacy).
- MC-Schleife (:3295-3399): im Sockel-Modus draw_order ohne real_estate; sockel_rappen separat indexieren und
  zum Pfad-Total (:3368-3369,:3386) addieren. sockelIndexBps aus simulation_prefs (analog :1903-1918).
- Test tests/test_verzehr_sockel.py (Units + Integration Sockel-vs-legacy + SoR-Lock + Leart-Eichung als xfail).

#59 Goal-Liability-Dedup (services/portfolio_engine.py):
- _goal_matches_cashflow(goal,cf) + _dedupe_goal_liabilities(goals,cashflows). Heuristik label+amount+Zeitraum
  (valid_until INKLUSIV). Aufruf in _collect_engine_inputs nach goals=... (:4377). Bereinigte Liste an
  _compute_reserve_for_inputs (:4555) und _build_goal_analysis (:2689); dedup_reasoning ins Payload.
- Test tests/test_goal_liability_no_double_count.py: reserve(beide)==max(nur-CF,nur-Goal);
  #AA-8-Summe bei VERSCHIEDENEN Goals weiterhin intakt.

#61 Reserve-Breakdown (services/portfolio_engine.py):
- _compute_reserve_for_inputs (:4555-4703) um breakdown-Param (reasoning-Appends bleiben). Keys: floor/
  near_term_shortfall/goal_reserve_sum/goal_reserve_items/reserve_needed/binding_component/saa_ceiling_bps/
  saa_capped/internal/external/external_absorbed_by_other_assets/narrative. _build_reserve_narrative(breakdown).
  reserve_breakdown ins Payload neben reserve_needed_rappen (:6573, rebuild :7210). advisory_report.py NICHT ändern.
- Test tests/test_reserve_breakdown_narrative.py: Vollständigkeit, binding_component, SAA-Cap, Other-Assets,
  Backwards-Compat reasoning, Konsistenz generate-vs-rebuild.

OWNER-DECISIONs (Defaults im Code, im PR markieren): Drawdown 100bps, sockelIndexBps 100bps, Sockel=nur
selbstgenutzt, #59=Heuristik, Teil-Deckung=anteilig, beide Features opt-in.
VOR jedem Commit: git branch --show-current == codex/u52-verzehr-reserve.
```
