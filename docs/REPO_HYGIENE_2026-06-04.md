# Repository-Hygiene-Audit 2026-06-04

**Sprint U-75 + U-76 + U-77 Bundle** — Bestandsaufnahme + selektive Aktion.

---

## Übersicht

Roadmap-Erwartung (Stand 2026-05-28): 12 Stashes + 3 WIP-Branches.
**Tatsächlich am 2026-06-04:** 28 Stashes + 5 codex/* Branches.

Wachstum entstand durch heutigen 28-PR-Sprint-Tag — Race-Recovery-Stashes
gegen Codex' parallele Branch-Switches.

---

## Stashes — 28 Total

### Recent Race-Recovery-Stashes (12 Stk., SAFE droppable)

Diese entstanden während des heutigen Sprint-Marathons als Codex
parallel auf seinen Branches arbeitete. Code ist alles in Claude-PRs
gemergt (#124-#158) — Stashes sind redundant.

| Stash | Branch | Sprint | Status |
|-------|--------|--------|--------|
| stash@{0} | feat/u-64-telemetry-stub-opt-in | U-64 → PR #150 | ✓ in PR |
| stash@{1} | feat/u-28-u-29-override-reason-quality | U-28+29 → PR #143 | ✓ in PR |
| stash@{2} | feat/u-15-pdf-ttf-embedding | U-56 → PR #139 | ✓ in PR |
| stash@{3} | feat/u-15-pdf-ttf-embedding | U-56 → PR #139 | ✓ in PR |
| stash@{4} | develop | U-62 → PR #136 | ✓ in PR |
| stash@{5} | feat/u-68-conflict-disclosures-aggregator | U-68 → PR #132 | ✓ in PR |
| stash@{6} | feat/u-68-conflict-disclosures-aggregator | U-68 → PR #132 | ✓ in PR |
| stash@{7} | feat/u-13-pdf-toc-page-numbers | U-52 → PR #130 | ✓ in PR |
| stash@{8} | feat/u-52-cover-print-aware | U-52 → PR #130 | ✓ in PR |
| stash@{9} | feat/u-59-bearer-token-ttl-audit | U-59 → PR #127 | ✓ in PR |
| stash@{10} | feat/u-47-subapp-print-css-test | U-47 → PR #119 | ✓ in PR |
| stash@{11} | feat/u-25-pdf-download-loading-spinner | U-25 → PR #117 | ✓ in PR |

**Empfehlung:** `scripts/cleanup-recent-race-stashes.ps1` ausführen (siehe unten).

### Codex-WIP-Stashes (16 Stk., MANUELL prüfen)

| Stash | Original-Branch | Datum | Klassifikation |
|-------|-----------------|-------|----------------|
| stash@{12} | feat/u-fe-5-vitest-frontend-tests | 2026-05-28 | Codex SOLL-edits, war Memory-Pin |
| stash@{13} | feat/u-fe-5-vitest-frontend-tests | 2026-05-28 | Codex SOLL-Fixtures |
| stash@{14} | feat/u-fe-5-vitest-frontend-tests | 2026-05-28 | Codex SOLL-Post-Merge |
| stash@{15} | feat/u-p26-pr-f-statement-vorgehen-polish | 2026-05-27 | Codex PDF-WIP |
| stash@{16} | feat/u-p26-pr-f-statement-vorgehen-polish | 2026-05-27 | Codex massive WIP |
| stash@{17} | feat/u-p26-pr-f-statement-vorgehen-polish | 2026-05-27 | Codex Aggregator-Tests |
| stash@{18} | feat/u-p26-pr-a-pdf-foundation | 2026-05-27 | Codex PDF-Pipeline |
| stash@{19} | feat/u-p28-pr-d-section-integration | 2026-05-27 | Codex U-P23 PR C |
| stash@{20} | test/u-p23-x-housematrix-consistency | (Rebase) | Codex PR #78 rebase |
| stash@{21} | test/u-p23-x-housematrix-consistency | (Rebase) | Codex PR #78 local |
| stash@{22} | develop | 2026-05-18 | Codex WIP batch |
| stash@{23} | develop | 2026-05-17 | Codex FE-Navigation |
| stash@{24} | codex/optimizer-runs-table | 2026-05-09 | Codex optimizer-runs |
| stash@{25} | codex/shadow-stochastic-c4 | 2026-05-08 | Codex pre-bugfix |
| stash@{26} | codex/shadow-stochastic-c4 | (during c4) | Codex during-c4 |
| stash@{27} | codex/fe-b6-conditional-goals | (pre-B3) | Codex FE-styling |

**Empfehlung:** **NICHT automatisch droppen.** Codex könnte einzelne Werte
noch brauchen wollen. Per Hand prüfen wenn Codex Bestätigung gibt dass
keine Reste mehr gebraucht sind.

---

## Codex-Branches — 5 Lokale Total

| Branch | Ahead | Behind | Empfehlung |
|--------|-------|--------|------------|
| codex/u-p23-pr-a-schema-toc | 0 | 38 | ✅ DELETE (komplett in develop) |
| codex/u-p23-pr-c-report-navigation | 0 | 22 | ✅ DELETE (komplett in develop) |
| codex/wip-2026-05-17-batches | 2 | 118 | ⚠️ SKIP (2 unique commits) |
| codex/wip-eignungspruefung-migration-2026-05-17 | 1 | 148 | ⚠️ SKIP (1 unique commit) |
| codex/wip-risikoprofil-2026-05-17 | 3 | 138 | ⚠️ SKIP (3 unique commits) |

`ahead=0` heisst: alle Branch-Commits sind bereits in develop drin (via
Squash-Merge ggf.). Löschen verliert nichts.

Die 3 `ahead>0` Branches haben unique Codex-Code der ggf. noch
gebraucht wird. Memory `project_5eyes.md` markiert sie als "parked".

---

## Worktrees

Stand 2026-06-04: nur Main-Worktree. Kein `codex/stochastic-optimizer`
Marker mehr da (Roadmap-Punkt 77 ist bereits erledigt).

---

## Action-Script (U-75/U-76)

`scripts/cleanup-recent-race-stashes.ps1` ist idempotent und droppt
nur die 12 Race-Recovery-Stashes mit dem `preserve-u`-Prefix. Codex-
WIP-Stashes (codex-wip-*, WIP-Codex-*) bleiben unberührt.

`scripts/cleanup-codex-branches-safe.ps1` löscht nur die 2 Branches
mit `ahead=0`. Die 3 mit unique Commits bleiben.

---

## Folge-Sprints

- **Codex-WIP-Stash-Review:** Bei nächstem Codex-Kontakt klären ob
  stash@{12-27} noch gebraucht werden. Falls nein: `git stash drop` pro Stück.
- **codex/wip-*-Branches:** Sobald Codex bestätigt dass die unique
  Commits in PRs gemergt sind, ebenfalls löschen.
- **Stash-Hygiene-Policy:** In Memory `feedback_branch_check_before_commit.md`
  einen Hinweis ergänzen — "Stashes mit `preserve-`-Prefix nach
  PR-Merge droppen, nicht akkumulieren lassen".
