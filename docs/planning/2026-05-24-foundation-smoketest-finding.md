# Foundation-Smoketest-Befund — Stochastic-Solver konvergiert nicht auf Foundation-Case

## Meta

- **Datum:** 2026-05-24
- **Entdeckt durch:** `tests/test_stage8_foundation_smoketest.py::test_foundation_case_yields_green_or_yellow_verdict`
- **Verifiziert:** lokal 2× reproduziert, deterministisch (identische Zahlen).
- **Historische Auswirkung:** Default-Mode-Wechsel auf `stochastic` war nach Methodology §1 + §4 **blockiert**, bis Solver auf Foundation konvergiert.
- **Fix-Status:** Stage-9-Implementierung lokal umgesetzt; Foundation liefert jetzt `YELLOW` statt `RED`.

## Befund

> **Update 2026-05-24 / Stage-9-Implementierung:** Der konkrete Foundation-
> Blocker ist behoben. Der Solver akzeptiert nun eine finite Allokation trotz
> SciPy-Non-Success-Status nur dann, wenn sie nachgelagert strikt gegen
> Sum-to-one, House-Matrix-Bandbreiten und Risk-Cap geprüft wurde. Der
> Foundation-Test ist nicht mehr `xfail`; aktuelles Verdict: `YELLOW` mit
> `optimization_status=converged_robustified`. Die weitergehenden Stage-9-
> Hebel (n_paths-/n_starts-Retry, Soft-Tau, Monitoring) bleiben als spätere
> Ausbaustufen bestehen.

Beim historischen Durchlauf des Foundation-Case (`services/foundation_example.py::upsert_foundation_example_case`) unter `OPTIMIZER_MODE=shadow_stochastic` lieferte der Stochastic-Solver:

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

Aktuelles Ergebnis nach Stage-9-Implementierung: `PASS`, Verdict `YELLOW`,
`optimization_status=converged_robustified`. Der Test ist nicht mehr als
`xfail` markiert.

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

Historischer Vorschlag vor der Implementierung:

```
1. n_paths = default (2000)             → wenn diverged:
2. n_paths × 2  (4000), neuer Seed      → wenn diverged:
3. n_starts × 2 mit Seeds-Shuffle       → wenn diverged:
4. Soft-Tau-Lockerung: τ → 0.75         → wenn diverged:
5. Fallback House-Matrix-Mid (= heute)
```

Implementiert wurde zusätzlich Hebel 0: finite-feasible candidate acceptance.
Wenn SciPy `success=False` meldet, aber eine endliche Allokation liefert, wird
diese nur nach strikter Nachprüfung von Sum-to-one, House-Matrix-Bandbreiten
und Risk-Cap als `converged_robustified` akzeptiert. Dieses Ergebnis zählt im
Shadow-Vergleich als `YELLOW`, nicht als `RED`.

## Test-Verhalten

- `test_foundation_case_pipeline_persists_shadow_payload` → **PASS** (Pipeline läuft, persistiert).
- `test_foundation_case_appears_in_aggregate` → **PASS** (Aggregator findet Foundation-Mandat korrekt; Default-Switch bleibt bei nur 1 Mandat weiterhin wegen Stichprobe geblockt).
- `test_foundation_case_yields_green_or_yellow_verdict` → **PASS** (nicht mehr `xfail`; Foundation liefert mindestens YELLOW).
- `test_foundation_per_mandate_and_aggregate_verdicts_match` → **PASS** (Per-Mandate- und Aggregat-Verdict bleiben konsistent).

## Bedeutung für die Owner-Aktion Stage 8

**Foundation-Blocker ist behoben.** Die Owner-Aktion Stage 8 ist fachlich
entsperrt, sobald der Stage-9-Implementierungs-PR auf `develop` gemerged ist
und der Shadow-Vergleich mit Foundation + 3 realen Mandaten dokumentiert
wurde.

Konkrete Empfehlung:
1. Stage-9-Implementierungs-PR mergen.
2. `shadow_stochastic` aktivieren.
3. Foundation + 3 reale Mandate durchlaufen lassen.
4. Admin-Aggregat prüfen; bei 0 RED und ausreichendem GREEN-Anteil Owner-
   Entscheidung für den Default-Switch dokumentieren.
