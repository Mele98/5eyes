# =============================================================================
# 5eyes — EXTERNER TEST mit SEPARATER Staging-DB (garantiert KEINE echten Mandanten)
#
# Wie start-external.ps1, aber zeigt auf ~/5eyes/5eyes-staging.db (DB_PATH) — eine
# eigene DB mit NUR synthetischen Demo-Tenants/Accounts. Selbst wenn die
# Tenant-Isolation versagte, gibt es hier schlicht KEINE echten Kundendaten.
#
# 1x vorher seeden:  cd 5eyes-backend ; python seed_external_demo.py
# Aufruf:            .\docs\deploy\start-external-staging.ps1
# Beenden: Strg+C; das minimierte Backend-Fenster separat schliessen.
#
# WICHTIG: vorher die normale Electron-App schliessen (sonst DB-/Port-Konflikt).
# =============================================================================
$ErrorActionPreference = 'Stop'

$repo    = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$backend = Join-Path $repo '5eyes-backend'
$home5   = Join-Path $env:USERPROFILE '5eyes'
if (-not (Test-Path $home5)) { New-Item -ItemType Directory -Path $home5 | Out-Null }
$secretFile = Join-Path $home5 '.external-secret.txt'
$cfExe      = Join-Path $home5 'cloudflared.exe'
$stagingDb  = Join-Path $home5 '5eyes-staging.db'

$pyCmd = Get-Command python -ErrorAction SilentlyContinue
if (-not $pyCmd) { $pyCmd = Get-Command py -ErrorAction SilentlyContinue }
if (-not $pyCmd) { Write-Host 'Python nicht gefunden.' -ForegroundColor Red; exit 1 }
$pyExe = $pyCmd.Source

# Staging-DB muss existieren (sonst Hinweis zum Seeden).
if (-not (Test-Path $stagingDb)) {
  Write-Host "Staging-DB fehlt: $stagingDb" -ForegroundColor Yellow
  Write-Host "Bitte zuerst seeden:  cd 5eyes-backend ; python seed_external_demo.py" -ForegroundColor Yellow
  exit 1
}

if (-not (Test-Path $secretFile)) {
  $newSecret = (& $pyExe -c "import secrets;print(secrets.token_urlsafe(48))").Trim()
  Set-Content -Path $secretFile -Value $newSecret -NoNewline -Encoding ascii
}
$secret = (Get-Content $secretFile -Raw).Trim()

# --- Staging-Env (Prozess-lokal). DB_PATH -> separate Staging-DB! ---
$env:DB_PATH               = $stagingDb        # <<< getrennt von der Live-DB
$env:APP_ENV               = 'staging'
$env:SERVE_MAIN_FRONTEND   = 'true'
$env:ALLOW_REAL_CLIENT_DATA = 'false'
$env:APP_HOST              = '127.0.0.1'
$env:APP_PORT              = '8000'
$env:SECRET_KEY            = $secret
$env:DEPLOYMENT_TIER       = 'tier2'
$env:TENANCY_MODE          = 'multi'
$env:TENANT_ADMIN_UI_ENABLED = 'true'
$env:STRICT_TENANT_ISOLATION = 'true'
$env:REQUIRE_2FA           = 'true'

Write-Host "Starte Backend (STAGING-DB $stagingDb) auf 127.0.0.1:8000 ..." -ForegroundColor Cyan
Start-Process -FilePath $pyExe -ArgumentList '-m uvicorn main:app --host 127.0.0.1 --port 8000' `
              -WorkingDirectory $backend -WindowStyle Minimized

$up = $false
for ($i = 0; $i -lt 40; $i++) {
  Start-Sleep -Milliseconds 750
  try { $r = Invoke-WebRequest -Uri 'http://127.0.0.1:8000/' -UseBasicParsing -TimeoutSec 2
        if ($r.StatusCode -eq 200) { $up = $true; break } } catch { }
}
if (-not $up) { Write-Host 'Backend nicht erreichbar (minimiertes Fenster pruefen).' -ForegroundColor Red; exit 1 }
Write-Host 'Backend laeuft (Staging-DB, nur synthetische Daten).' -ForegroundColor Green

if (-not (Test-Path $cfExe)) {
  Write-Host 'Lade cloudflared (einmalig) ...' -ForegroundColor Cyan
  Invoke-WebRequest -Uri 'https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe' -OutFile $cfExe -UseBasicParsing
}

Write-Host ''
Write-Host '====================================================================' -ForegroundColor Green
Write-Host ' Gleich erscheint eine  https://<zufall>.trycloudflare.com  URL.'    -ForegroundColor Green
Write-Host ' Teile sie + diesen Pfad mit Kollegen:'                              -ForegroundColor Green
Write-Host '   https://<zufall>.trycloudflare.com/app/5eyes_v2.html'             -ForegroundColor White
Write-Host ' Logins (Initial-PW Start-5eyes-2026! , 2FA-Pflicht beim 1. Login):' -ForegroundColor Green
Write-Host '   operator / a.berater / a.admin / b.berater / b.admin'            -ForegroundColor White
Write-Host '====================================================================' -ForegroundColor Green
Write-Host ''

& $cfExe tunnel --url http://127.0.0.1:8000
