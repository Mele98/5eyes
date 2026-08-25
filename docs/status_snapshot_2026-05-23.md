# Status-Snapshot 2026-05-23

**Stand:** `develop @ e0b2709`, weit vor `origin/develop` (ungepusht). Volle
Backend-Suite zuletzt: **1670 passed, 5 skipped**. Working-Tree für Claude
sauber; Codex hat uncommitted Parallelarbeit (siehe §3).

## 1. Was in den letzten 48 h gelandet ist

| Commit | Thread | Inhalt |
|---|---|---|
| `e0b2709` | Stochastic-Spec | Claude-Spec als Antwort auf Codex-Brief — Risk-Matrix als harte FINMA-Suitability-Schranke, stochastische Goal-Engine als künftiger Default, Codex-Plan in 8 Stufen |
| `8e4984e` | U-P19b Daily-FX | Währungskorrekter Daily-Backtest (FX→CHF Forward-Fill, neue Tabelle `AssetClassFxHistory`), `risk_free` aus `cma.liquidity_return_bps`; CHF-korrektes 60/40 = CAGR 2.76% statt falscher USD-Sicht 3.08% |
| `10fee38` | U-P19 Netz-Test | Integrationstest gegen echte yfinance-Daten (`@network @skip`) |
| `07c1293` | U-P18 Regression | Regressionstest für Portfolio-Generierung nach SAA-Recalc + Präferenz-Hard-Blocks |
| `0a87407` | U-P19 Handoff | Claude→Codex-Anweisung für U-P19-Frontend in `CLAUDE_HANDOFF.md` |
| `b6c13b4` | U-P19 Frontend | Daily-Toggle + Backfill-Admin-Panel + Header-Umbau (Codex) |
| `41b90fd` | Portfolio-Fix | Suitability-Band leert SAA nicht mehr (Codex) — ein tiefer Risiko-Override sperrt nicht mehr alle Produkte |
| `5dddcbc` | U-P19 Backend | Daily-Resolution Strategie-Backtest (Modell + Backfill + Service + PDF) |
| `56ff8a0` / `e122bea` | U-P19 Spec | Daily-Backtest-Spec + Benchmark als First-Class |
| `55a9164` | U-P18 PDF | Rubrikreine Einzel-PDFs (Asset Allocation + Portfolio) |

## 2. Was funktional komplett ist

- **Daily-Strategie-Backtest** (U-P19 + U-P19b): Backend, Frontend-Toggle,
  Admin-Backfill-Panel, FX-Korrektheit, PDF, Netz-Integrationstest. Real-Daten
  bestätigt.
- **Portfolio-Generierung** robust gegen tiefe Risiko-Overrides (Codex-Fix
  `41b90fd`): leeres Portfolio kommt nicht mehr vor; Suitability-Override
  wird mit Warnung dokumentiert.
- **Stale-Run-Schutz** in `current/payload` (U-P18 `55a9164`): keine veralteten
  Portfolio-Empfehlungen gegen neuere Soll-Allokationen.
- **Rubrikreine PDFs**: `assetallocation.pdf`, `portfolio.pdf` sind sauber
  getrennt, `anlagestrategie.pdf` bleibt das 19-seitige Gesamtdokument.

## 3. Was in der Schwebe ist (uncommitted im Working-Tree)

Codex hat Parallelarbeit, die noch nicht committed ist:

- `5eyes-backend/services/portfolio_engine.py` (weitere Codex-Edits, Inhalt
  noch nicht von mir reviewed)
- `5eyes-backend/routers/wealth.py`
- `5eyes-backend/tests/test_goal_scoring_horizon.py`
- `5eyes-backend/tests/test_mandate_api_contracts.py`
- `5eyes-electron/frontend/5eyes_v2.html` (Codex-Bereiche, mein U-P19-Toggle
  liegt schon committed im File-Header)
- `docs/CLAUDE_HANDOFF.md` (Codex' eigener Stochastic-Brief am Anfang)
- `docs/planning/2026-05-23-stochastic-goal-engine-brief.md` (untracked, der
  Brief)
- `5eyes-backend/tests/test_frontend_goal_return_contracts.py` (untracked,
  neuer Codex-Contract)

**Bewertung:** Volle Suite war mit dieser Parallelarbeit **grün** (1670 passed),
also keine akute Brüche. Codex sollte das in einem zusammenhängenden Commit
landen; bis dahin nicht von Claude angefasst.

## 4. Strategischer Pfad für die nächsten 1-2 Sprints

### Priorität A — Stochastic-Engine als aktive Engine (Codex Stage 1-8)

Die Spec `docs/planning/2026-05-23-stochastic-goal-engine-spec.md` definiert
8 Stufen. **Reihenfolge ist verbindlich** (jede Stufe muss grün sein, bevor
die nächste startet):

1. **Datenmodell + Schema** — neue Goal-Felder, TargetAllocation-Felder,
   Feld-Isolation per Zieltyp. Klein, isoliert.
2. **Risikobudget-Cap immer-aktiv** — auch im `house_matrix`-Default.
3. **Chance Constraint + Achievability** — `P(Ziel) ≥ τ` als Lagrange-Penalty.
4. **Messages-Katalog** — 7 advisor-facing Konflikt-Codes.
5. **Default-Mode-Wechsel + Shadow** — `shadow_stochastic` als Übergang.
6. **Frontend** (Goal-Editor + Review) — Feld-Isolation sichtbar, Konflikt-
   Banner, Limiting-Factor-Badge.
7. **PDF-Reports** — `limiting_factor` + Achievability-Tabelle in
   `anlagestrategie.pdf`.
8. **Verifikation** — Shadow-Vergleich auf Foundation-Case + 3 reale Mandate.

**Owner-Decisions sind in der Spec gesetzt (OD-A bis OD-H)** — Codex hat
einen klaren Auftrag ohne Fachentscheidungs-Lücken.

### Priorität B — Daily-Backtest aktivieren

U-P19 ist gebaut, aber der **Daily-Backfill muss einmal manuell laufen**:
*Admin → Daten → Tageskurse → Aus Marktdaten füllen* (~25k Rows, netz-
intensiv, ~30s). Ohne diese Aktivierung fällt der „Täglich"-Modus korrekt auf
„Jährlich" zurück (mit Badge). Einmal-Aktion durch den Berater.

### Priorität C — Push develop → origin/develop

Viele Commits seit der letzten Synchronisation. Reine Maintenance-Aktion,
schützt vor Datenverlust, hat keine fachliche Auswirkung. **Outward-Aktion**,
braucht explizite Bestätigung durch den User.

### Priorität D — UX-Schliff am Goal-Editor (auf Stage 6 vorgreifen)

Vorbereitend für Stage 6 könnte Claude den **Goal-Editor-Wireframe** in
einem separaten Spec-Doc skizzieren (typabhängige Felder, Hardness-Disable
für Renditeziel, Live-Anzeige notwendige Rendite). Reine Planungsarbeit,
schadet nicht, beschleunigt Codex.

## 5. Risiken und Beobachtungen

- **Dual-Agent-Kollisionen**: Codex und Claude arbeiten beide direkt auf
  `develop` (kein Branch-Split). Das ging in den letzten Sprints gut, weil
  die Threads dateilich getrennt waren. Bei der Stochastic-Umsetzung wird
  sich das ändern (Stage 1 fasst `models/`, `schemas/`, `database.py` an —
  Codex-Land, Claude soll dort nicht parallel werken).
- **FX-Verfügbarkeit**: Der USD/CHF-Backfill nutzt das Yahoo-FX-Symbol
  `CHF=X`. Stooq-Fallback hat eine andere Konvention; bei Yahoo-Ausfall ist
  FX-Backfill möglicherweise unvollständig. Der Backtest hat einen Graceful-
  Fallback (FX-Lücke → Forward-Fill bzw. unkonvertiert + Warnung), aber für
  einen vollständig CHF-korrekten Backtest braucht es Yahoo-FX-Erreichbarkeit.
- **Performance-Budget Stochastic**: Spec OD-H setzt `λ_chance = 1e6` — die
  Chance Constraint kann den Solver-Zeit-Budget (~5s, jetzt ~8s ok) belasten.
  Falls überschritten, muss die `N=2000`-Scenario-Anzahl reevaluiert werden.
- **Codex' uncommitteter Stochastic-Brief in `CLAUDE_HANDOFF.md`**: nicht von
  Claude committen (Autorschaft); Codex committet seinen Teil selbst.

## 6. Empfehlung an den User

1. **Codex anschubsen für Stochastic Stage 1** — die Spec ist konkret, Owner-
   Decisions gesetzt, Codex kann sofort starten. Stage 1 ist klein (Daten-
   modell + Schema), als saubere erste Iteration.
2. **Push develop → origin** wenn nichts dagegen spricht (12+ ungepushte
   Commits, jeder ein echtes Feature). Eine kurze „push" reicht; Claude
   führt es aus.
3. **Daily-Backfill einmal in der App auslösen** für die nächste Beratung,
   damit der Daily-Backtest echte Tagesauflösung zeigt.
4. **`shadow_stochastic`-Mode** vor Default-Wechsel — Spec §10 Acceptance #10
   verlangt einen dokumentierten Shadow-Vergleich auf Foundation-Case + 3
   realen Mandaten, bevor `OPTIMIZER_MODE=stochastic` Default wird.

## 7. Was Claude als nächstes leisten kann (ohne Kollision)

- Stage 6 vorbereiten: Goal-Editor-Wireframe + Review-Cockpit-Wireframe.
- Stage 7 vorbereiten: PDF-Komponente `goal_achievability` skizzieren.
- Konflikt-Meldungs-Texte (§5.1 der Spec) ausformulieren und sprachlich
  feinjustieren (advisor-facing, kundentauglich).
- Eine **Review-Cockpit-UX-Spec** als eigenes Dokument (analog zur Stochastic-
  Spec) — fachliche UX-Planung im Claude-Scope.
- Nach Codex' Stage 1-Commit: Review gegen die Spec; bei Abweichungen
  Korrektur-Empfehlung.
