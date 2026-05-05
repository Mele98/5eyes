# Push-All-Branches Script (nach gh auth login)
# ============================================
# Pusht alle 4 Feature-Branches die durch die letzte Session entstanden sind:
#   - codex/audit-master (18 Commits)
#   - codex/stochastic-optimizer (18 Commits, baut auf audit-master)
#   - codex/fe-optimizer-panel (1 Commit, FE-Implementation)
#
# Voraussetzung: gh auth login -h github.com erfolgreich gelaufen.
#
# Bedienung:
#   .\scripts\push_all_branches_after_gh_auth.ps1
#
# Bei Push-Fehler (Auth nicht gegangen, etc.) wird abgebrochen, kein
# Branch nur teilweise gepusht.

$ErrorActionPreference = "Stop"

Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "Push-All Branches (nach gh auth login)"   -ForegroundColor Cyan
Write-Host "=========================================" -ForegroundColor Cyan

# 1. gh-Auth pruefen
Write-Host ""
Write-Host "[1/4] gh-Auth pruefen..." -ForegroundColor Yellow
$status = (gh auth status 2>&1 | Out-String)
if ($status -notmatch "Logged in") {
    Write-Host "FEHLER: gh ist nicht eingeloggt." -ForegroundColor Red
    Write-Host "Bitte erst ausfuehren: gh auth login -h github.com" -ForegroundColor Red
    exit 1
}
Write-Host "  -> gh ist eingeloggt." -ForegroundColor Green

# 2. _develop_security Workspace: audit-master + stochastic-optimizer pushen
Write-Host ""
Write-Host "[2/4] _develop_security Workspace pushen..." -ForegroundColor Yellow
$ws1 = "C:\5eyes\5eyes_stage9_release_ready_develop_security"
Push-Location $ws1
try {
    Write-Host "  Push origin codex/audit-master ..."
    git push origin codex/audit-master 2>&1 | ForEach-Object { Write-Host "    $_" }
    if ($LASTEXITCODE -ne 0) { throw "audit-master Push fehlgeschlagen" }

    Write-Host "  Push origin codex/stochastic-optimizer ..."
    git push origin codex/stochastic-optimizer 2>&1 | ForEach-Object { Write-Host "    $_" }
    if ($LASTEXITCODE -ne 0) { throw "stochastic-optimizer Push fehlgeschlagen" }
} finally {
    Pop-Location
}
Write-Host "  -> 2 Branches gepusht." -ForegroundColor Green

# 3. _release_ready Workspace: fe-optimizer-panel pushen
Write-Host ""
Write-Host "[3/4] _release_ready Workspace pushen..." -ForegroundColor Yellow
$ws2 = "C:\5eyes\5eyes_stage9_release_ready"
Push-Location $ws2
try {
    Write-Host "  Push origin codex/fe-optimizer-panel ..."
    git push origin codex/fe-optimizer-panel 2>&1 | ForEach-Object { Write-Host "    $_" }
    if ($LASTEXITCODE -ne 0) { throw "fe-optimizer-panel Push fehlgeschlagen" }
} finally {
    Pop-Location
}
Write-Host "  -> 1 Branch gepusht." -ForegroundColor Green

# 4. PRs vorschlagen (kein Auto-Create — Owner soll Body kontrollieren)
Write-Host ""
Write-Host "[4/4] PR-Befehle vorschlagen ..." -ForegroundColor Yellow
Write-Host ""
Write-Host "  Reihenfolge laut Merge-Plan:" -ForegroundColor Cyan
Write-Host ""
Write-Host "  1. Audit-Master in develop:" -ForegroundColor White
Write-Host "     cd $ws1" -ForegroundColor Gray
Write-Host "     gh pr create --base develop --head codex/audit-master --title 'Audit-Master Z1-Z9 + B1-B6 + W2.5 + Security + F23' --body-file docs/planning/audit-master-pr-summary.md" -ForegroundColor Gray
Write-Host ""
Write-Host "  2. Stochastic-Optimizer in develop (NACH audit-master gemerged):" -ForegroundColor White
Write-Host "     cd $ws1" -ForegroundColor Gray
Write-Host "     git checkout codex/stochastic-optimizer" -ForegroundColor Gray
Write-Host "     git rebase origin/develop  # sollte Fast-Forward sein" -ForegroundColor Gray
Write-Host "     git push --force-with-lease origin codex/stochastic-optimizer" -ForegroundColor Gray
Write-Host "     gh pr create --base develop --head codex/stochastic-optimizer --title 'Stochastic Optimizer Phase 1-6.3'" -ForegroundColor Gray
Write-Host ""
Write-Host "  3. RP-Ueberarbeitung rebasen + mergen (Codex' uncommitted erst committen!):" -ForegroundColor White
Write-Host "     cd $ws2" -ForegroundColor Gray
Write-Host "     # Erst Codex' 33 uncommitted Files committen oder stashen" -ForegroundColor Gray
Write-Host "     git checkout codex/rp-ueberarbeitung" -ForegroundColor Gray
Write-Host "     git rebase origin/develop  # Konflikte erwartet, siehe merge-plan" -ForegroundColor Gray
Write-Host "     gh pr create --base develop --head codex/rp-ueberarbeitung --title 'RP-Ueberarbeitung'" -ForegroundColor Gray
Write-Host ""
Write-Host "  4. FE-Optimizer-Panel rebasen + mergen:" -ForegroundColor White
Write-Host "     cd $ws2" -ForegroundColor Gray
Write-Host "     git checkout codex/fe-optimizer-panel" -ForegroundColor Gray
Write-Host "     git rebase origin/develop" -ForegroundColor Gray
Write-Host "     gh pr create --base develop --head codex/fe-optimizer-panel --title 'Phase 6 FE: Optimizer-Panel'" -ForegroundColor Gray

Write-Host ""
Write-Host "==============================================" -ForegroundColor Cyan
Write-Host "Alle Branches gepusht. PR-Erstellung manuell." -ForegroundColor Cyan
Write-Host "Voller Plan: docs/planning/2026-05-06-merge-plan-three-branches.md" -ForegroundColor Cyan
Write-Host "==============================================" -ForegroundColor Cyan
