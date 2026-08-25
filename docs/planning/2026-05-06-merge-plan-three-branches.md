# Merge-Plan: drei Branches in `develop`

**Datum:** 2026-05-06
**Owner:** Emanuele
**Voraussetzung:** `gh auth login -h github.com` (Token im Keyring ist tot)

## Ausgangslage

Drei aktive Feature-Branches, alle unmerged:

| Branch | Workspace | Stand |
|---|---|---|
| `codex/audit-master` | `_develop_security` | 18 Commits ahead von `origin`, 357 Tests grün. Z1–Z9 + B1–B6 + W2.5 + Security + F23 |
| `codex/stochastic-optimizer` | `_develop_security` | 17 Commits ahead von `audit-master` (35 von develop), 528 Tests grün. Phase 1–6.3 |
| `codex/rp-ueberarbeitung` | `_release_ready` | 31 modified + 2 untracked Files (uncommitted), Tests 285 (vor uncommitted-State) |

Plus offene **Phase 6 FE** = neuer Branch `codex/fe-optimizer-panel` (Codex implementiert nach `2026-05-06-phase6-fe-implementation-patch.md`).

## Reihenfolge (kritisch — nicht ändern)

```
develop
   ↑ 1
codex/audit-master
   ↑ 2
codex/stochastic-optimizer
   ↑ 3
codex/rp-ueberarbeitung           (rebase auf develop)
   ↑ 4
codex/fe-optimizer-panel          (rebase auf rp-ueberarbeitung)
```

Begründung:
1. **audit-master** zuerst — alle anderen bauen auf seinen Audit-Fixes auf. Risiko-niedrig: nur Backend, keine FE-Konflikte.
2. **stochastic-optimizer** danach — fast-forward Merge weil direkt von audit-master. Kein Konflikt erwartet.
3. **rp-ueberarbeitung** muss rebased werden weil RP von alter develop-Basis kommt und nun auf neuere audit-master-Inhalte trifft. Konflikte zu erwarten in: `portfolio_engine.py` (B5/B6/W2.5 vs. RP-Refactor), `risk_scoring.py` (B5 vs. RP-Logik), `5eyes_v2.html` (Drift).
4. **fe-optimizer-panel** zuletzt — FE-only, baut auf rp-ueberarbeitung's neuestem `5eyes_v2.html` auf.

## Schritt-für-Schritt (für Owner auszuführen, mit aktivem `gh auth`)

### 0. Vorbereitung — gh auth

```powershell
gh auth login -h github.com
gh auth status   # muss "Logged in" zeigen
```

### 1. Push aller drei Branches (Stand vor Merge)

```powershell
# Workspace _develop_security
cd C:\5eyes\5eyes_stage9_release_ready_develop_security
git push origin codex/audit-master
git push origin codex/stochastic-optimizer

# Workspace _release_ready (Codex' uncommitted Files VORHER absprechen!)
cd C:\5eyes\5eyes_stage9_release_ready
git status   # 31 Files? -> Codex muss zuerst committen oder stashen
# Wenn Codex commited hat:
git push origin codex/rp-ueberarbeitung
```

### 2. PR audit-master → develop

```powershell
cd C:\5eyes\5eyes_stage9_release_ready_develop_security
gh pr create --base develop --head codex/audit-master `
  --title "Audit-Master: Z1-Z9 + B1-B6 + W2.5 + Security + F23" `
  --body-file docs/planning/audit-master-pr-summary.md
```

PR-Body: Liste der 18 Commits + Test-Ergebnisse + Reviewer-Hinweise. **Nicht direkt mergen — Self-Review zuerst.** Erst nach Approval: `gh pr merge --merge` (kein Squash, History bleibt nachvollziehbar).

### 3. PR stochastic-optimizer → develop (NACH audit-master gemerged)

```powershell
git fetch origin
git checkout codex/stochastic-optimizer
git rebase origin/develop   # sollte FF sein, weil audit-master schon drin
git push --force-with-lease origin codex/stochastic-optimizer
gh pr create --base develop --head codex/stochastic-optimizer `
  --title "Stochastic Optimizer Phase 1-6.3" `
  --body "Goal-based Mulvey/Ziemba-light Solver + FE-Panel-Backend. Opt-in via OPTIMIZER_MODE=stochastic. 528/528 Tests gruen."
```

### 4. Rebase rp-ueberarbeitung auf develop

```powershell
cd C:\5eyes\5eyes_stage9_release_ready
git fetch origin
git checkout codex/rp-ueberarbeitung
git rebase origin/develop
# >>> KONFLIKTE ERWARTET in: portfolio_engine.py, risk_scoring.py, 5eyes_v2.html
# Strategie pro Konflikt:
#   - portfolio_engine.py: audit-master B5/B6 wins; RP-Refactor adaptiert
#   - risk_scoring.py: B5 hardness-α-Hybrid wins; RP nutzt das neue Schema
#   - 5eyes_v2.html: hand-merge per Section
```

Vorsicht: dieser Rebase ist **nicht trivial**. Empfehlung: lokal arbeiten, per Section mergen, dann Tests lokal laufen lassen (`pytest`), erst dann `git push --force-with-lease`.

### 5. PR rp-ueberarbeitung → develop

Nach erfolgreichem Rebase + lokalen grünen Tests: PR aufmachen, Self-Review, mergen.

### 6. fe-optimizer-panel implementieren

Codex implementiert Phase 6 FE nach `2026-05-06-phase6-fe-implementation-patch.md`.
Branch von `codex/rp-ueberarbeitung` (mit `-FromCurrent` Flag).

```powershell
cd C:\5eyes\5eyes_stage9_release_ready
.\scripts\start_codex_branch.ps1 -Slug "fe-optimizer-panel" -FromCurrent
# Patch anwenden (3 Edits in 5eyes_v2.html + Mock in desktop-api.js)
# Manueller Smoke-Test (siehe scripts/smoke_test_phase6_optimizer.ps1)
git push origin codex/fe-optimizer-panel
gh pr create --base develop --head codex/fe-optimizer-panel `
  --title "Phase 6 FE: Optimizer-Panel mit Stress-Tabelle und Sensitivity-Slider"
```

## Konflikt-Vorhersage (vorab durchdenken)

| Datei | Audit-Master-Aenderung | RP-Aenderung | Strategie |
|---|---|---|---|
| `services/portfolio_engine.py` | B1/B5/B6, W2.5, F23, Optimizer-Hooks | Engine-Alignment Refactor | Audit wins, RP-Refactor anpassen |
| `services/risk_scoring.py` | (vermutlich nicht) | RP-Ueberarbeitung Logik | RP wins (eigener Scope) |
| `models/allocation.py` | Optimizer-Spalten + Phase-6-Persistenz | (vermutlich keine) | Audit wins |
| `schemas/allocation.py` | TargetAllocationGenerateResponse + sensitivity-Schemas | minor field changes | merge beide |
| `5eyes_v2.html` | (audit-master bisschen) | RP-Refactor (umfangreich) | RP wins, audit-Drift hand-merge |

## Rollback-Plan

Falls etwas schief geht:

```powershell
# Tag vor jedem Merge setzen
git checkout develop
git tag pre-merge-audit-master-$(Get-Date -Format yyyyMMdd-HHmm)
git push origin --tags

# Im Notfall: develop zurueckdrehen
git reset --hard pre-merge-audit-master-2026XXXX-XXXX
git push --force-with-lease origin develop
```

Bundle-Backups existieren bereits:
- `C:\5eyes\audit-master-backup-2026-05-05.bundle`

## Was NICHT in diesem Plan ist

- Code-Review der einzelnen Commits (separate PR-Reviews)
- CI-Pipeline-Tuning (sollte vor dem ersten Merge stabil laufen)
- Production-Deployment (nicht Scope von 5eyes-Desktop-App)
