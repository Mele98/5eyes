# 5eyes — Status-Snapshot 2026-05-14

**Zweck:** Eine einzige Seite, die zeigt, **was offen ist**, **wer dran ist**, und **in welcher Reihenfolge** gemergt werden sollte. Damit beendest du den aktuellen Sprint sauber, bevor neue UX-Arbeit beginnt.

---

## TL;DR

| Bereich | Status | User-Action |
|---|---|---|
| **Data Pipeline (P1-P20)** | ✅ Code+Test+Doku+CI fertig | 20 PRs sequentiell mergen |
| **Bug-Fixes (FE)** | ✅ Code fertig | 2 PRs mergen (klein, hoher Hebel) |
| **Sprint B (B2-B6, B3)** | ✅ Code fertig | 6 PRs sequentiell mergen |
| **Optimizer V3 (Sprint 1+2)** | ✅ Code fertig | 7 PRs sequentiell mergen |
| **WIP-Cleanup** | ✅ Code fertig | 1 PR mergen |
| **Codex WIP-FE-Restructure** | 🟡 101 Commits aufgeschoben | Separater Review-Slot |
| **Codex Audit-Branches (Z1-Z4)** | 🟡 Unbekannter Stand | Pruefen oder schliessen |
| **Stashes (4)** | 🟡 Aufgeschoben | Bei Bedarf restoren |
| **UX-Backlog (8 Sektionen)** | 📋 Nicht gestartet | Erst nach Merge-Sprint |

**Antwort auf "wann sind wir fertig":** Der Code-Teil **ist** fertig. Was bleibt, ist Merge-Review — kein Engineering-Aufwand mehr.

---

## 1. Offene PRs nach Schiene

### 1a. Data Pipeline (20 PRs, sequentiell gestackt)

P1 → P12 (Provider-Stack):
- **#18** P1: Provider-Adapter-Pattern
- **#19** P2: YFinanceProvider
- **#20** P3: StooqProvider
- **#21** P4: AlphaVantageProvider
- **#22** P5: MarketDataAggregator + Fallback
- **#23** P6: Smart Cache (SQLite + TTL)
- **#24** P7: Cross-Validation
- **#25** P8: OpenFIGIProvider
- **#26** P9: Macro-Pipeline (FRED/ECB/SNB)
- **#27** P10: CMA-CSV-Import
- **#28** P11: ETF-Scraper (opt-in)
- **#29** P12: TwelveDataProvider

P13 → P20 (Integration + Tooling):
- **#30** P13: legacy_compat + scheduled jobs
- **#31** P14: price_updater Migration
- **#32** P15: APScheduler-Hooks
- **#33** P16: Admin-Endpoint /admin/market-data/status
- **#34** P17: Admin-FE-Panel
- **#35** P18: Aktivierungs-Doku
- **#36** P19: Smoketest-CLI
- **#38** P20: GitHub Action (Weekly + on-PR)

**Merge-Reihenfolge:** in numerischer Folge, von #18 nach #38. Jedes PR baut auf dem vorigen auf.

### 1b. Sprint B (6 PRs)

- **#3** B4: Anlageuniversum + Building-Blocks
- **#4** B2: Anderes-Vermoegen Schloss-Mechanismus
- **#5** B5: Time-Bucket-Reserve (3 Fristen)
- **#6** B6: Conditional Goals (probability_pct)
- **#7** FE-B6: Goal-Editor wired probability_pct
- **#8** B3: Vorsorge-Differenziert Phase 1

### 1c. Optimizer V3 (7 PRs)

- **#9** Sprint 1: shadow_stochastic-Modus
- **#10** Sprint 1b: OptimizerContext + evaluate_weights
- **#11** Sprint 1c: Apples-to-Apples Methodenvergleich
- **#12** Sprint 1d: Constraint Slacks + Goal Drivers
- **#13** Sprint 1 Commit 4: FE Methodenvergleich-Panel
- **#16** Sprint 2: optimizer_runs Audit-Trail
- **#17** Sprint 2.1: TargetAllocation → OptimizerRun FK

### 1d. Bug-Fixes (2 PRs, klein, hoher Hebel)

- **#14** Risikoprofil-Backend = Source-of-Truth fuer AA-Navigation
- **#15** IST-Chart defensive Render-Pipeline ohne early-return

### 1e. Cleanup (1 PR)

- **#37** WIP-Cleanup-Analyse + .gitignore (Workspace 25 → 3 untracked)

---

## 2. Empfohlene Merge-Sequenz

**Tag 1: Quick-Wins (2 PRs, ~30 min Review)**
1. #14 + #15 — Bug-Fixes, klein, sofort spuerbar

**Tag 1-2: Sprint B (6 PRs, ~2-3 h Review)**
2. #3 → #4 → #5 → #6 → #7 → #8 in dieser Reihenfolge

**Tag 2-3: Optimizer V3 (7 PRs, ~3-4 h Review)**
3. #9 → #10 → #11 → #12 → #13 → #16 → #17

**Tag 3-4: Data Pipeline (20 PRs, ~5-6 h Review)**
4. #18 → #19 → … → #38 streng sequentiell

**Tag 4: Cleanup (1 PR)**
5. #37 — kann unabhaengig laufen

**Gesamt: ~12 h verteilt auf 4 Arbeitstage.**

Bei Zeitknappheit: Priorisiere #14, #15 (Bugs) und Sprint B (#3-#8) — das gibt den meisten User-Wert pro Stunde Review.

---

## 3. Aufgeschoben (nicht in der Merge-Queue)

### 3a. Codex WIP-FE-Restructure
- Branch: `codex/wip-fe-review-restructure-2026-05-08`
- **101 Commits** ahead von develop
- Enthaelt Section-6-Vorarbeit (sr-approval-grid, sr-decision-grid IDs)
- Test-File `test_frontend_summary_contracts.py` (lokal untracked) testet die WIP-Features
- **Empfehlung:** Separates Review-Slot nach dem Merge-Sprint. NICHT in den aktuellen Sprint ziehen — Konflikt-Risiko.

### 3b. Codex Audit-Branches (Z1-Z4 + hardening + quick-fixes)
- `codex/audit-architecture-z1` … `z4`
- `codex/audit-hardening-r4`, `codex/audit-perm-hardening`, `codex/audit-quick-fixes`, `codex/audit-f3-cma-versioning`, `codex/audit-master`
- **Stand unbekannt** — keine offenen PRs dazu (vermutlich alle gemergt oder verworfen)
- **Empfehlung:** Mit Codex klaeren ob noch relevant, sonst schliessen/loeschen.

### 3c. Stashes (4)
```
stash@{0}: On codex/optimizer-runs-table: WIP-Codex-during-optimizer-runs-2026-05-09
stash@{1}: On codex/shadow-stochastic-c4: WIP-Codex-pre-bugfix-2026-05-08
stash@{2}: On codex/shadow-stochastic-c4: WIP-Codex-during-c4
stash@{3}: On codex/fe-b6-conditional-goals: WIP-FE-styling-pre-B3 5eyes_v2.html
```
- Diese sind Codex-Snapshots vor riskanten Operationen.
- **Empfehlung:** Nach Merge-Sprint pruefen ob noch was relevant ist, sonst `git stash drop`.

---

## 4. UX-Backlog (Codex Scope-Split, NICHT gestartet)

Aus `docs/CLAUDE_CODEX_SCOPE_SPLIT_NO_ASSET_ALLOCATION.md`:

| § | Bereich | Aufgabe-Kern | Hebel |
|---|---|---|---|
| 1 | Stammdaten/Mandat | Trennung Beratung/holistisch, Kunden-Copy | Mittel |
| 2 | Risikoprofil | Fragebogen ruhiger, Ergebnis erklaeren | Hoch |
| 3 | Ziele/Cashflows | Zielerreichung als klare Aussage | Hoch |
| 4 | Portfolio | Beratungs-/Umsetzungsbruecke-Wording | Mittel |
| 5 | Review | Consulting-Nachweis, keine Live-Monitoring-Lies | Mittel |
| 6 | Summary/POS | Sichtbare Seite max schlank, keine "Management Summary" | **Sehr Hoch** |
| 7 | Report | Buttonlabels ehrlich, keine PDF-Versprechen | Mittel |
| 8 | Admin | UI auf Klarheit pruefen | Niedrig |

**Empfohlene UX-Start-Phase nach Merge-Sprint:**
- **U1: § 6 Summary/POS** — der Point-of-Sales. Hoechster Hebel.
- **U2: § 2 Risikoprofil** — FINMA-relevant, oft erste Beruehrung.
- **U3: § 7 Report** — Druck-Workflow konsolidieren.

NICHT antasten in dieser Phase: Asset Allocation (Sektion explizit ausgeklammert).

---

## 5. Was als naechstes passieren sollte

1. **User:** Merge-Sprint Tag 1-4 abarbeiten (oben).
2. **Codex/Claude koordinieren:** Was bleibt vom WIP-FE-Restructure-Branch (3a)?
3. **Audit-Branches (3b):** Aufraeumen oder Stand klaeren.
4. **Stashes (3c):** Pruefen + drop.
5. **UX-Sprint U1-U3 starten** — erst nachdem die FE-Basis (entweder via Codex-WIP-Merge oder neu auf develop) stabil ist.

---

## 6. Wann ist die Pipeline _wirklich_ fertig?

Drei Definitionen:

| Definition | Status |
|---|---|
| **Code fertig** (alle Phasen implementiert + getestet + dokumentiert) | ✅ Heute |
| **Live deployt** (alle PRs gemergt + Production-`.env` umgestellt) | ⏳ Nach Merge-Sprint |
| **Produktiv ueberwacht** (CI-Action laeuft, Validation-Logs gefuellt) | ⏳ 1 Woche nach Live |

Aktuell: ✅ Code fertig.
Nach Merge-Sprint: ⏳ → ✅ Live.
Eine Woche spaeter: ⏳ → ✅ Produktiv ueberwacht.

Dann: Pipeline-Kapitel abgeschlossen, UX-Sprint startet.

---

**Erstellt:** 2026-05-14
**Branch:** `codex/status-snapshot-2026-05-14`
**Naechster Schritt:** User-Review + Entscheidung ob Merge-Sprint heute startet oder erst nach Codex-WIP-Koordination.
