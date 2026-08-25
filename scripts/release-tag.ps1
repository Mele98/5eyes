# Sprint U-78 (2026-06-04): Release-Tag Helper-Script
#
# Usage:
#   .\scripts\release-tag.ps1 -Version "1.4.0" -Title "Q2 2026 Compliance"
#   .\scripts\release-tag.ps1 -Version "1.4.0-rc.1" -Title "Q2 RC"
#
# Validiert dass:
#   - Branch ist 'main' oder 'release/*'
#   - Working-Tree clean
#   - Backend app_version == Electron package.json version == Version-Arg
#   - Tag noch nicht existiert
#
# Erstellt:
#   - Annotated Tag v{Version} mit Message-Template
#
# Push ist NICHT automatisch. Manuell: git push origin --tags

[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)]
    [ValidatePattern('^\d+\.\d+\.\d+(-[a-z0-9.]+)?$')]
    [string]$Version,

    [Parameter(Mandatory=$true)]
    [string]$Title,

    [string]$Reviewer = ""
)

$ErrorActionPreference = 'Stop'

# --- 1. Branch-Check
$Branch = (git branch --show-current).Trim()
if ($Branch -ne "main" -and -not $Branch.StartsWith("release/")) {
    Write-Error "Release-Tags muessen von 'main' oder 'release/*' erstellt werden. Aktueller Branch: $Branch"
}
Write-Host "OK Branch: $Branch" -ForegroundColor Green

# --- 2. Working-Tree-Clean-Check
$Status = (git status --porcelain).Trim()
if ($Status) {
    Write-Error "Working-Tree nicht clean. Bitte zuerst committen oder stashen:`n$Status"
}
Write-Host "OK Working-Tree clean" -ForegroundColor Green

# --- 3. Tag-Existenz-Check
$TagName = "v$Version"
$ExistingTag = (git tag -l $TagName)
if ($ExistingTag) {
    Write-Error "Tag $TagName existiert bereits."
}
Write-Host "OK Tag $TagName ist neu" -ForegroundColor Green

# --- 4. Version-Konsistenz Backend <-> Electron <-> Arg
$BackendConfigPath = Join-Path $PSScriptRoot "..\5eyes-backend\config.py"
$ElectronPkgPath = Join-Path $PSScriptRoot "..\5eyes-electron\package.json"

if (-not (Test-Path $BackendConfigPath)) {
    Write-Error "Backend config.py nicht gefunden: $BackendConfigPath"
}
if (-not (Test-Path $ElectronPkgPath)) {
    Write-Error "Electron package.json nicht gefunden: $ElectronPkgPath"
}

$BackendVersion = (Select-String -Path $BackendConfigPath -Pattern "app_version:\s*str\s*=\s*'([^']+)'" | ForEach-Object { $_.Matches.Groups[1].Value })
$ElectronPkgRaw = Get-Content $ElectronPkgPath -Raw | ConvertFrom-Json
$ElectronVersion = $ElectronPkgRaw.version

Write-Host "Backend app_version: $BackendVersion"
Write-Host "Electron version:    $ElectronVersion"
Write-Host "Tag Version:         $Version"

if ($BackendVersion -ne $Version) {
    Write-Error "Backend-Version '$BackendVersion' matched nicht Tag-Version '$Version'. Bitte app_version in config.py updaten."
}
if ($ElectronVersion -ne $Version) {
    Write-Error "Electron-Version '$ElectronVersion' matched nicht Tag-Version '$Version'. Bitte package.json updaten."
}
Write-Host "OK Versionen synchron" -ForegroundColor Green

# --- 5. Tag-Message zusammenstellen
$ReleaseDate = (Get-Date).ToString("yyyy-MM-dd")
$ReviewerLine = if ($Reviewer) { "Compliance-Review: $Reviewer, $ReleaseDate" } else { "Compliance-Review: PENDING (vor Production-Use ergaenzen)" }

$TagMessage = @"
$TagName - $Title

Release-Datum: $ReleaseDate
Backend: $BackendVersion
Electron: $ElectronVersion

Aenderungen siehe CHANGELOG.md.

$ReviewerLine
"@

# --- 6. Tag erstellen
git tag -a $TagName -m $TagMessage
if ($LASTEXITCODE -ne 0) {
    Write-Error "git tag failed."
}
Write-Host "OK Tag $TagName erstellt" -ForegroundColor Green

Write-Host ""
Write-Host "Naechste Schritte:" -ForegroundColor Cyan
Write-Host "  1. Tag-Message pruefen: git show $TagName"
Write-Host "  2. Push: git push origin $Branch --tags"
Write-Host "  3. GitHub-Release (UI oder gh):"
Write-Host "     gh release create $TagName --notes-file CHANGELOG.md"
