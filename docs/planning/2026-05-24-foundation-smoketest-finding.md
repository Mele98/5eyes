# Foundation-Smoketest-Befund — Stochastic-Solver konvergiert nicht auf Foundation-Case

## Meta

- **Datum:** 2026-05-24
- **Entdeckt durch:** `tests/test_stage8_foundation_smoketest.py::test_foundation_case_yields_green_or_yellow_verdict`
- **Verifiziert:** lokal 2× reproduziert, deterministisch (identische Zahlen).
- **Auswirkung:** Default-Mode-Wechsel auf `stochastic` ist nach Methodology §1 + §4 **blockiert**, bis Solver auf Foundation konvergiert.
- **Scope für Fix:** Stage 9 Spec (Solver-Robustifizierung) — momentan von Codex in Bearbeitung.

## Befund

Beim Durchlauf des Foundation-Case (`services/foundation_example.py::upsert_foundation_example_case`) unter `OPTIMIZER_MODE=shadow_stochastic` liefert der Stochastic-Solver:

```
verdict               = RED
limiting_factor       = solver_konvergenz
optimization_status   = fallback_house_matrix
total_drift_bps       = 185
risky_drift_bps       = 47
budget_compliance     = {house_matrix: True, stochastic: True}
goal_counts.n_hard_unreachable_st = 0
goal_counts.n_goals_unreachable_st = 2
verdict_notes         = ["optimization_status != converged"]
```

**Interpretation:** Solver versagt graziös → Pipeline fängt mit House-Matrix-Fallback ab → kein Crash, aber Methodology §4 RED-Schwelle „optimization_status != converged" greift.

**Kein hartes Goal-Konflikt:** `n_hard_unreachable_st=0`. Die 2 unreachable Goals sind „opportunistisch"/„primär" (nicht „hart") → Solver schaltet sie korrekt nicht zur Stop-Bedingung hoch, scheitert aber an der Gesamt-Optimierung.

**Drift klein:** total_drift=185 bps, risky_drift=47 bps. Solver versucht, weicht von HM nur leicht ab, gibt dann auf.

## Reproduktion

```bash
cd 5eyes-backend
python -m pytest tests/test_stage8_foundation_smoketest.py::test_foundation_case_yields_green_or_yellow_verdict -v
```

Erwartetes (aktuelles) Ergebnis: `XFAIL` mit obigem Diagnose-Output.

## Code-Stellen (verifiziert per Read-Tool)

| Datei | Zeilen | Was passiert |
|---|---|---|
| `services/foundation_example.py:237` | `upsert_foundation_example_case(db, user)` | Foundation seeding — 4 Goals, 6 Wealth-Positionen, Score 7-8 |
| `services/portfolio_engine.py:5602-5614` | `goal_achievability + classify_limiting_factor` | Liest `optimizer_result.goal_achievability`; setzt `limiting_factor = "risikoprofil"` falls Budget voll |
| `services/portfolio_engine.py:5710-5715` | `risk_budget_fallback`-Block | Setzt `optimization_status = "fallback_house_matrix"` wenn Solver versagt |
| `services/shadow_comparison.py:154-155` | `classify_shadow_verdict` RED-Schwelle | `if str(optimization_status or "") != "converged": red_reasons.append("optimization_status != converged")` |

## Hypothesen für Stage 9 Spec (zu validieren)

1. **n_paths zu niedrig** für die spezifische Goal-Struktur — Foundation hat 4 Goals mit verschiedenen Horizonten (Pensionsvorsorge bis 30J, Hauskauf 2032, Sicherheitsreserve), evtl. brauchen wir > 2000 Pfade für Konvergenz.
2. **Seed-Sensitivität:** ein einziger Seed liefert hier ein nicht-feasibles Subproblem; mit `n_starts > 1` + Seed-Shuffle wäre mindestens ein Pfad konvergent.
3. **Tau zu strikt:** Default τ=80 % Wealth/Cashflow, 50 % Renditeziel. Bei der Foundation-Goal-Kombination möglicherweise nicht simultan erfüllbar; weiche Soft-Tau-Lockerung (τ=75 %) als Fallback-Stage könnte konvergieren.
4. **Inflation/Cashflow-Wechselwirkung:** Foundation hat 7 Cashflows (Lohn + AHV + BVG + 3a + Lebenshaltung + Mietnebenkosten + Versicherungen). Wenn der Cashflow-Pfad einen ungünstigen Restkapital-Punkt vor Pensionsbeginn erzeugt, kann es kein Allocation-Set geben, das alle Goals erfüllt.

## Minimal-Fix-Vorschlag

**Kein Code-Patch hier** — Stage 9 Spec (Codex in Arbeit) muss erst die Fallback-Hierarchie definieren. Vorgeschlagene Reihenfolge im Stage-9-Solver-Restart:

```
1. n_paths = default (2000)             → wenn diverged:
2. n_paths × 2  (4000), neuer Seed      → wenn diverged:
3. n_starts × 2 mit Seeds-Shuffle       → wenn diverged:
4. Soft-Tau-Lockerung: τ → 0.75         → wenn diverged:
5. Fallback House-Matrix-Mid (= heute)
```

Bei Stages 1-3 darf das Resultat noch als `converged` audited werden. Bei Stage 4 wird `optimization_status = "converged_with_soft_tau"` (neuer Status), Methodology §4 müsste das als YELLOW (nicht RED) akzeptieren. Bei Stage 5 bleibt `fallback_house_matrix` mit RED — wie heute.

## Test-Verhalten

- `test_foundation_case_pipeline_persists_shadow_payload` → **PASS** (Pipeline läuft, persistiert).
- `test_foundation_case_appears_in_aggregate` → **PASS** (Aggregator findet RED-Mandat korrekt, Default-Switch wird hart geblockt).
- `test_foundation_case_yields_green_or_yellow_verdict` → **XFAIL** (Befund festgehalten).
- `test_foundation_per_mandate_and_aggregate_verdicts_match` → **PASS** (Per-Mandate- und Aggregat-Verdict bleiben konsistent, auch bei RED).

Sobald Stage 9 Fixes landen und der Solver auf Foundation konvergiert, wird das xfail XPASS — sichtbar in CI. Dann `xfail`-Marker entfernen + `strict=True` setzen, damit Regressionen sofort auffallen.

## Bedeutung für die Owner-Aktion Stage 8

**Owner-Aktion ist solange blockiert, wie der Foundation-Case nicht konvergiert.** Methodology §1 lässt sich nicht weich-umgehen: ohne grünen Foundation gibt es keinen Default-Switch.

Konkrete Empfehlung:
1. Stage 9 Spec (Codex) abwarten.
2. Stage 9 Implementation (vermutlich neuer Codex-Auftrag nach Spec-Review).
3. Diesen Test wieder rot werden lassen → grün werden lassen (XPASS).
4. ERST dann mit den 3 realen Mandaten starten.

Ohne Stage-9-Fix würde der Owner-Run nur die gleiche RED-Klassifikation auf 3 weiteren Mandaten reproduzieren — Verschwendung von Aufwand.
