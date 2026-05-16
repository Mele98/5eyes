# Status-Snapshot 2026-05-17

Stand nach Codex-Scope-Audit, App-Notice-System-Einführung, Optimizer-
Phase-5/6-Analyse und Datenpipeline-Aktivierungs-Vorbereitung.

## TL;DR

**develop @ a780c34**. 1213 Tests grün. 0 offene PRs.

Drei Initiativen analysiert, eine vollständig umgesetzt:

| Initiative | Status |
|---|---|
| Codex-Scope-Lücken-Cleanup (5 Diskrepanzen) | ✅ alle gefixt oder Doku korrigiert |
| Globales App-Notice-System (Toast-Stack) | ✅ eingebaut, getestet, 1 Pilot-Anwendung |
| Optimizer Phase 5 (Robustheit) | ⚠️ 2/3 fertig — Importance-Sampling fehlt |
| Optimizer Phase 6 (UX) | ✅ Methodenvergleich, Sensitivity, Goal-Drivers alle da |
| Datenpipeline P1-P25 | ✅ deployed, Smoketest grün, **wartet auf Aktivierung** |

---

## 1. Codex-Scope-Cleanup (commit 3302f1b)

Systematische Verifikation der 30 Codex-§11 Items hat 5 Diskrepanzen
aufgedeckt:

| # | Befund | Fix |
|---|---|---|
| 17 | 4 `Stub:`/`Platzhalter`-Marker im Code | entfernt |
| 4 | §6 listet 6 fiktive sr-* IDs | durch 22 echt existierende ersetzt |
| 9, 13, 14, 22-25 | "global sichtbar" — System fehlte | präzisiert + neues System (s.u.) |
| 26 | `jsAttrArg()` behauptet, existiert nicht | als nicht-erledigt markiert |
| §11 footer | `test_frontend_summary_contracts.py` nie existiert | Liste mit echten Test-Files ersetzt |

13 doppelte JS-Funktions-Definitionen analysiert (commit 46cf01c):
- 3 echte Top-Level-Duplikate (allocationTimelineIsOneOff,
  allocationTimelineSectionLabel, allocationTimelineSectionRank) → entfernt
- 10 "Differ"-Varianten alle lokal nested Helper (showErr, dg, dcf etc.)
  → legitimes JS-Pattern, kein Bug

## 2. App-Notice-System (commits ce27a04 + a780c34)

Globales Toast-Stack-System eingeführt — bisher fehlte echtes app-weites
Notice-System (Codex §11.9/13/14/22-25 versprochen aber nie gebaut).

**Komponenten:**
- HTML-Container `#app-notice-stack` (top-right, ARIA-konform)
- CSS-Klassen `.app-notice` + 4 Level (`.an-error/warn/success/info`)
  mit slideIn/Out-Animation
- JS `showAppNotice({level, message, title?, durationMs?, action?})`
  + Convenience-Wrapper `showAppError/Warn/Success/Info`
- Auto-dismiss: error=8s, warn=6s, success=4s, info=4s; 0=manuell
- Optional Action-Button mit onClick-Callback

**Tests:** 8 Static-Contract-Tests in `test_frontend_app_notice.py`.

**Pilot-Anwendung:** `calculateInvestmentStrategy()` zeigt jetzt:
- Erfolg → `showAppSuccess('Anlagestrategie aktualisiert', {title:'Berechnung abgeschlossen'})`
- Fehler → `showAppError(detail, {title:'Berechnung gestoppt'})`

**Weitere Aufrufstellen** (für künftige Sessions):
- Login/Bootstrap-Fehler
- Mandat-Create-Fehler
- Cashflow/Wealth-Save-Bestätigungen
- Strategy-Snapshot-Save
- Review-Trigger-Erfolg

## 3. Optimizer Phase 5 (Robustheit & Stress)

Spec: `docs/planning/2026-05-05-stochastic-optimizer-spec.md` §5.

| Subitem | Status |
|---|---|
| Antithetic Variates | ✅ in scenario_engine.py |
| GA/DE-Fallback wenn SLSQP divergiert | ✅ in solver.py Z 571-636 (`SLSQP+DE-Fallback`) |
| Stress-Scenarios als Constraints | ✅ stress_scenarios.py + solver-Integration |
| **Importance Sampling für Tail** | ❌ fehlt |

**Importance Sampling** ist anspruchsvolle Numerik (~200 Zeilen +
Calibration-Tests). Würde Tail-Risk (z.B. Black Swans) besser samplen.
Spec sagt Phase 5 ist optional. **Eigene Mini-Spec wenn gewünscht.**

## 4. Optimizer Phase 6 (UX) — weitgehend fertig

| Subitem | Status |
|---|---|
| FE-Optimization-Panel (Methodenvergleich) | ✅ V3 Sprint 1c-d (allocation_method_comparison) |
| Sensitivity-Slider | ✅ POST `/mandates/{id}/target-allocation/sensitivity` + `evaluate_goal_sensitivity()` |
| Reasoning-Trace (Goal-Drivers, Constraint-Slacks) | ✅ V3 Sprint 1d |

## 5. Datenpipeline (P1-P25)

Code: alle 25 Phasen in develop.
Doku: `docs/data_pipeline_activation.md`, `docs/data_pipeline_README.md`.

**Status der Aktivierung** (per `python scripts/check_env_for_pipeline.py`):

```
[WARN] PRICE_REFRESH_PRIMARY_PROVIDER  Aggregator nicht aktiv (primary=yfinance)
[ OK ] MARKET_DATA_PROVIDERS           Fallback-Chain: yfinance -> stooq -> alphavantage
[WARN] ALPHAVANTAGE_API_KEY            Key fehlt → Provider als unhealthy markiert
[ OK ] PRICE_SCHEDULER_ENABLED         Scheduler aktiv
[ OK ] MARKET_DATA_CACHE_PURGE_ENABLED Daily Cache-Purge aktiv
```

**E2E-Smoketest grün:**
- yfinance ✓ (UBSG.SW = 35.97, AAPL = 300.23)
- stooq ✓
- alphavantage ✗ (Key fehlt — Fallback funktioniert trotzdem)

**Was du tun musst um Pipeline live zu schalten:**

1. `.env` aus `.env.example` kopieren
2. Setzen:
   ```env
   PRICE_REFRESH_PRIMARY_PROVIDER=aggregator
   MARKET_DATA_PROVIDERS=yfinance,stooq,alphavantage
   ALPHAVANTAGE_API_KEY=<gratis-key>  # https://alphavantage.co/support/#api-key
   ```
3. Backend neustarten
4. Verifikation: Admin-Modal → Tab "Datenpipeline" zeigt Provider-Status

Optional: `OPTIMIZER_MODE=stochastic` für die Mulvey/Ziemba-light Solver-Pfad.

---

## Verbleibendes für künftige Sessions (alle eigene Initiativen)

1. **Importance Sampling** für Optimizer Phase 5 — eigene Mini-Spec
2. **`jsAttrArg()`-Helper** falls Inline-Handler-Sicherheit gewünscht — Codex-Item 26
3. **App-Notice an weitere 10+ Aufrufstellen** ausrollen — leichter Sweep
4. **Datenpipeline aktivieren** — operationale Entscheidung des Users
5. **Visuelle Customer-Journey-Verifikation in Electron** — Smoke-Test der 8 Steps
