# Sprint U-75 (2026-06-04): Recent Race-Recovery-Stashes droppen.
#
# Droppt NUR Stashes mit Message-Prefix `preserve-u` (heutige Race-
# Recoveries). Codex-WIP-Stashes (`codex-wip-*`, `WIP-Codex-*`) bleiben
# unberuehrt — die brauchen Codex-Bestaetigung vor Aktion.
#
# Idempotent: kann mehrmals laufen.

[CmdletBinding()]
param(
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'

# Stashes mit Indexen sammeln. git stash list liefert "stash@{N}: branch: msg"
$AllStashes = git stash list

if (-not $AllStashes) {
    Write-Host "Keine Stashes vorhanden — nichts zu tun." -ForegroundColor Green
    exit 0
}

$RaceStashes = @()
foreach ($Line in $AllStashes) {
    if ($Line -match '^(stash@\{\d+\}):\s+(?:WIP on|On)\s+[^:]+:\s+(.*)$') {
        $StashRef = $Matches[1]
        $Message = $Matches[2]
        if ($Message -match '^preserve-u') {
            $RaceStashes += [PSCustomObject]@{
                Ref = $StashRef
                Message = $Message
            }
        }
    }
}

if ($RaceStashes.Count -eq 0) {
    Write-Host "Keine Race-Recovery-Stashes (preserve-u*) gefunden." -ForegroundColor Yellow
    exit 0
}

Write-Host "Race-Recovery-Stashes zum Droppen ($($RaceStashes.Count)):" -ForegroundColor Cyan
foreach ($Stash in $RaceStashes) {
    Write-Host "  $($Stash.Ref): $($Stash.Message)"
}

if ($DryRun) {
    Write-Host ""
    Write-Host "-DryRun gesetzt — kein drop ausgefuehrt." -ForegroundColor Yellow
    exit 0
}

# WICHTIG: stash@{N} indexes shift sich beim Drop. Wir muessen rueckwaerts
# (hoechster Index zuerst) droppen damit niedrige Indexe stabil bleiben.
$Sorted = $RaceStashes | Sort-Object {
    if ($_.Ref -match 'stash@\{(\d+)\}') {
        [int]$Matches[1]
    } else { 0 }
} -Descending

foreach ($Stash in $Sorted) {
    Write-Host "Drop $($Stash.Ref)..."
    git stash drop $Stash.Ref | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Error "git stash drop $($Stash.Ref) failed."
    }
}

Write-Host ""
Write-Host "OK $($Sorted.Count) Race-Recovery-Stashes geloescht." -ForegroundColor Green
Write-Host ""
Write-Host "Verbleibende Stashes (Codex-WIP — manuell pruefen):" -ForegroundColor Cyan
git stash list
