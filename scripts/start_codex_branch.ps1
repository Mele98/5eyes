param(
    [Parameter(Mandatory = $true)]
    [string]$Slug,

    [string]$BaseBranch = "develop",

    [switch]$FromCurrent
)

$ErrorActionPreference = "Stop"

function Normalize-Slug {
    param([string]$Value)
    $normalized = $Value.ToLowerInvariant() -replace "[^a-z0-9]+", "-"
    $normalized = $normalized.Trim("-")
    if (-not $normalized) {
        throw "Slug ist leer. Bitte einen sinnvollen Namen wie 'asset-allocation-v2' uebergeben."
    }
    return $normalized
}

$branchSlug = Normalize-Slug $Slug
$targetBranch = "codex/$branchSlug"

Write-Host "== Codex Branch Setup ==" -ForegroundColor Cyan
Write-Host "Zielbranch: $targetBranch"

git rev-parse --is-inside-work-tree | Out-Null

$status = git status --short
if ($status) {
    Write-Warning "Das Repo hat lokale Aenderungen. Es wird nichts automatisch verworfen."
    Write-Host $status
}

if (-not $FromCurrent) {
    Write-Host "Hole Base-Branch '$BaseBranch'..." -ForegroundColor Yellow
    git fetch origin $BaseBranch
    git checkout $BaseBranch
    git pull --ff-only origin $BaseBranch
}

Write-Host "Erzeuge oder aktualisiere $targetBranch ..." -ForegroundColor Yellow
$existing = git branch --list $targetBranch
if ($existing) {
    git checkout $targetBranch
} else {
    git checkout -b $targetBranch
}

Write-Host "Aktiver Branch:" -ForegroundColor Green
git branch --show-current
