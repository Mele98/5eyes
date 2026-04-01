param(
    [Parameter(Mandatory = $true)]
    [string]$Slug,

    [string]$Title = "",

    [string]$Owner = "Claude"
)

$ErrorActionPreference = "Stop"

function Normalize-Slug {
    param([string]$Value)
    $normalized = $Value.ToLowerInvariant() -replace "[^a-z0-9]+", "-"
    $normalized = $normalized.Trim("-")
    if (-not $normalized) {
        throw "Slug ist leer. Bitte einen sinnvollen Namen uebergeben."
    }
    return $normalized
}

$templatePath = Join-Path $PSScriptRoot "..\\docs\\planning\\CLAUDE_SPEC_TEMPLATE.md"
$templatePath = [System.IO.Path]::GetFullPath($templatePath)
if (-not (Test-Path $templatePath)) {
    throw "Template nicht gefunden: $templatePath"
}

$branchSlug = Normalize-Slug $Slug
$datePrefix = Get-Date -Format "yyyy-MM-dd"
$targetPath = Join-Path $PSScriptRoot "..\\docs\\planning\\$datePrefix-$branchSlug.md"
$targetPath = [System.IO.Path]::GetFullPath($targetPath)

if (Test-Path $targetPath) {
    throw "Spec existiert bereits: $targetPath"
}

$content = Get-Content -Raw -Path $templatePath
$effectiveTitle = if ($Title) { $Title } else { $Slug }
$content = $content -replace "- Titel:", "- Titel: $effectiveTitle"
$content = $content -replace "- Datum:", "- Datum: $datePrefix"
$content = $content -replace "- Owner:", "- Owner: $Owner"
$content = $content -replace "- Branch-Vorschlag:", "- Branch-Vorschlag: codex/$branchSlug"

Set-Content -Path $targetPath -Value $content -Encoding UTF8

Write-Host "Neue Claude-Spec erstellt:" -ForegroundColor Green
Write-Host $targetPath
