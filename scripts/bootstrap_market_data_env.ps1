$ErrorActionPreference = 'Stop'

param(
    [switch]$Force
)

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Split-Path -Parent $scriptRoot
$targetEnv = Join-Path $repoRoot '.env'
$exampleEnv = Join-Path $repoRoot '5eyes-backend\.env.example'

if (-not (Test-Path $exampleEnv)) {
    throw "Quelle fehlt: $exampleEnv"
}

if ((Test-Path $targetEnv) -and -not $Force) {
    Write-Host "Backend-.env existiert bereits: $targetEnv"
    Write-Host "Keine Aenderung vorgenommen. Verwende -Force zum Ueberschreiben."
    exit 0
}

Copy-Item -Path $exampleEnv -Destination $targetEnv -Force:$Force

Write-Host "Backend-.env vorbereitet: $targetEnv"
Write-Host ""
Write-Host "Vor dem produktiven Marktdatenbetrieb bitte mindestens diese Keys setzen:"
Write-Host "  TWELVEDATA_API_KEY=..."
Write-Host "  EODHD_API_KEY=..."
Write-Host "  FRED_API_KEY=..."
Write-Host ""
Write-Host "Optional:"
Write-Host "  OPENFIGI_API_KEY=..."
Write-Host "  SIX_API_KEY=..."
Write-Host ""
Write-Host "Empfohlene Reihenfolge:"
Write-Host "  1. EODHD fuer Referenzdaten"
Write-Host "  2. Twelve Data fuer Marktpreise"
Write-Host "  3. FRED fuer globale Makrodaten"
Write-Host "  4. optional OpenFIGI / SIX"
