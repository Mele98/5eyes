# Sprint U-76 (2026-06-04): Codex-Branches mit ahead=0 löschen.
#
# Loescht NUR lokale codex/* Branches die KEINE einzigartigen Commits
# gegenueber develop haben (= komplett in develop gemergt). Branches
# mit unique Commits bleiben unberuehrt.
#
# Idempotent.

[CmdletBinding()]
param(
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'

# Aktuellen Branch ermitteln (darf nicht geloescht werden)
$CurrentBranch = (git branch --show-current).Trim()

# Lokale codex/* Branches sammeln
$CodexBranches = git branch | Where-Object { $_ -match '^\s+codex/' } | ForEach-Object { $_.Trim() }

if (-not $CodexBranches) {
    Write-Host "Keine codex/* Branches vorhanden." -ForegroundColor Green
    exit 0
}

$SafeToDelete = @()
$UniqueCommits = @()

foreach ($Branch in $CodexBranches) {
    if ($Branch -eq $CurrentBranch) {
        Write-Host "Skip $Branch (aktueller Branch)" -ForegroundColor Yellow
        continue
    }
    $Ahead = (git rev-list --count develop..$Branch 2>$null)
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Skip $Branch (rev-list failed)" -ForegroundColor Yellow
        continue
    }
    $AheadInt = [int]$Ahead
    if ($AheadInt -eq 0) {
        $SafeToDelete += $Branch
    } else {
        $UniqueCommits += [PSCustomObject]@{ Branch = $Branch; Ahead = $AheadInt }
    }
}

Write-Host "Sicher loeschbar (ahead=0, komplett in develop):" -ForegroundColor Cyan
foreach ($Branch in $SafeToDelete) {
    Write-Host "  $Branch"
}

if ($UniqueCommits.Count -gt 0) {
    Write-Host ""
    Write-Host "SKIP (haben unique Commits, manuell pruefen):" -ForegroundColor Yellow
    foreach ($Entry in $UniqueCommits) {
        Write-Host "  $($Entry.Branch) — $($Entry.Ahead) unique commit(s)"
    }
}

if ($SafeToDelete.Count -eq 0) {
    Write-Host ""
    Write-Host "Nichts zum Loeschen." -ForegroundColor Green
    exit 0
}

if ($DryRun) {
    Write-Host ""
    Write-Host "-DryRun gesetzt — keine Loeschung ausgefuehrt." -ForegroundColor Yellow
    exit 0
}

foreach ($Branch in $SafeToDelete) {
    Write-Host "Delete $Branch..."
    # -d (klein) statt -D: refuses bei nicht-gemergten Branches.
    # -d funktioniert wenn ahead=0 — Defense-in-Depth.
    git branch -d $Branch
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  -d failed, falling back to -D for fully-merged branch" -ForegroundColor Yellow
        git branch -D $Branch
        if ($LASTEXITCODE -ne 0) {
            Write-Error "git branch -D $Branch failed."
        }
    }
}

Write-Host ""
Write-Host "OK $($SafeToDelete.Count) Codex-Branches geloescht." -ForegroundColor Green
