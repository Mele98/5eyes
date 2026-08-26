# =============================================================================
# 5eyes — Externer Zugriff von deinem PC (Phase-0: nur synthetische Daten)
#
# Startet das Backend im Staging-/Browser-Hosting-Modus auf 127.0.0.1:8000 und
# oeffnet einen Cloudflare-Quick-Tunnel mit HTTPS (kein Account, kein Port-
# Forwarding). Danach loggst du dich von ueberall im Browser ein.
#
# Aufruf (PowerShell):   .\docs\deploy\start-external.ps1
# Beenden: dieses Fenster mit Strg+C; das Backend-Fenster separat schliessen.
#
# OPS-001 (Codex-Audit 2026-08-25): ALLOW_REAL_CLIENT_DATA=false blockt nur
# NEUE Schreibzugriffe, die sich selbst als "real" klassifizieren
# (services/data_classification.py) — es macht weder die bereits
# vorhandene Electron-Desktop-DB unsichtbar noch verhindert es, dass dieses
# Skript sie oeffnet. Ohne explizites DB_PATH zeigt dieses Skript daher
# standardmaessig auf eine SEPARATE Datei (~\5eyes\external-demo.db), NIE
# auf die produktive Desktop-DB — ein oeffentlicher Cloudflare-Quick-Tunnel
# gegen echte Mandantendaten passiert damit nicht mehr aus Versehen.
# Fuer den bewussten Fall (z.B. echter externer Zugriff fuer eine Firma)
# $env:DB_PATH VOR dem Aufruf explizit setzen — das Skript warnt dann hart
# und verlangt eine getippte Bestaetigung.
# =============================================================================
$ErrorActionPreference = 'Stop'

$repo    = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$backend = Join-Path $repo '5eyes-backend'
$home5   = Join-Path $env:USERPROFILE '5eyes'
if (-not (Test-Path $home5)) { New-Item -ItemType Directory -Path $home5 | Out-Null }
$secretFile = Join-Path $home5 '.external-secret.txt'
$cfExe      = Join-Path $home5 'cloudflared.exe'
$realDbPath = Join-Path $home5 '5eyes.db'

if (-not $env:DB_PATH) {
  # Kein DB_PATH gesetzt -> sicherer Default: eigene Staging-DB, niemals
  # die produktive Desktop-DB. seed_external_demo.py kann diese Datei
  # separat mit synthetischen Demo-Mandaten befuellen.
  $env:DB_PATH = Join-Path $home5 'external-demo.db'
  Write-Host "DB_PATH nicht gesetzt -> nutze separate Staging-DB: $($env:DB_PATH)" -ForegroundColor Cyan
} elseif ((Resolve-Path -LiteralPath $env:DB_PATH -ErrorAction SilentlyContinue).Path -eq $realDbPath) {
  Write-Host '====================================================================' -ForegroundColor Red
  Write-Host ' WARNUNG: DB_PATH zeigt auf die produktive Electron-Desktop-DB!'      -ForegroundColor Red
  Write-Host ' Der Cloudflare-Tunnel macht diese DB oeffentlich erreichbar (nur'    -ForegroundColor Red
  Write-Host ' Login/2FA schuetzen sie). ALLOW_REAL_CLIENT_DATA blockt dabei NUR'   -ForegroundColor Red
  Write-Host ' neue Schreibzugriffe, keine Lesezugriffe auf bestehende Kundendaten.' -ForegroundColor Red
  Write-Host '====================================================================' -ForegroundColor Red
  $confirm = Read-Host 'Tippe GENAU "ich verstehe das risiko" zum Fortfahren'
  if ($confirm -ne 'ich verstehe das risiko') {
    Write-Host 'Abgebrochen.' -ForegroundColor Yellow
    exit 1
  }
}

# --- Python finden ---
$pyCmd = Get-Command python -ErrorAction SilentlyContinue
if (-not $pyCmd) { $pyCmd = Get-Command py -ErrorAction SilentlyContinue }
if (-not $pyCmd) { Write-Host 'Python nicht gefunden. Bitte Python 3.11+ installieren.' -ForegroundColor Red; exit 1 }
$pyExe = $pyCmd.Source

# --- Stabiles Secret (einmalig erzeugt, ueber Neustarts gleich) ---
if (-not (Test-Path $secretFile)) {
  $newSecret = (& $pyExe -c "import secrets;print(secrets.token_urlsafe(48))").Trim()
  Set-Content -Path $secretFile -Value $newSecret -NoNewline -Encoding ascii
  Write-Host "Neues stabiles Login-Secret erzeugt: $secretFile" -ForegroundColor Yellow
}
$secret = (Get-Content $secretFile -Raw).Trim()

# --- Staging-/Browser-Hosting-Env (Prozess-lokal; .env bleibt unberuehrt) ---
$env:APP_ENV               = 'staging'
$env:SERVE_MAIN_FRONTEND   = 'true'
$env:ALLOW_REAL_CLIENT_DATA = 'false'
$env:APP_HOST              = '127.0.0.1'
$env:APP_PORT              = '8000'
$env:SECRET_KEY            = $secret
$env:DEPLOYMENT_TIER       = 'tier2'   # Multi-Firma
$env:TENANCY_MODE          = 'multi'
$env:TENANT_ADMIN_UI_ENABLED = 'true'  # Operator-Provisioning (Firmen/Mitarbeiter)
$env:STRICT_TENANT_ISOLATION = 'true'  # physische Trennung: NULL-tenant_id unsichtbar
# Pflicht-2FA: erzwingt Authenticator-Enrollment beim externen Zugriff. Default sicher = true.
# Fuer einen reibungslosen Kollegen-Test (NUR synthetische Daten) vorher abschaltbar via
#   $env:REQUIRE_2FA = 'false'
# (dann wird ein bereits gesetzter Wert respektiert statt ueberschrieben).
if (-not $env:REQUIRE_2FA) { $env:REQUIRE_2FA = 'true' }

# Optional: Einladungs-E-Mails direkt verschicken (sonst Link-Copy). Auskommentiert
# lassen, bis ein SMTP-Zugang vorliegt — der Invite-Flow funktioniert auch ohne.
# $env:SMTP_ENABLED  = 'true'
# $env:SMTP_HOST     = 'smtp.deinprovider.ch'
# $env:SMTP_PORT     = '587'
# $env:SMTP_USER     = 'postmaster@deinedomain.ch'
# $env:SMTP_PASSWORD = '<app-passwort>'
# $env:SMTP_FROM     = '5eyes <no-reply@deinedomain.ch>'
# $env:SMTP_USE_TLS  = 'true'

Write-Host 'Starte Backend (staging, browser-hosting) auf 127.0.0.1:8000 ...' -ForegroundColor Cyan
Start-Process -FilePath $pyExe -ArgumentList '-m uvicorn main:app --host 127.0.0.1 --port 8000' `
              -WorkingDirectory $backend -WindowStyle Minimized

# --- Auf Backend warten ---
$up = $false
for ($i = 0; $i -lt 40; $i++) {
  Start-Sleep -Milliseconds 750
  try {
    $r = Invoke-WebRequest -Uri 'http://127.0.0.1:8000/' -UseBasicParsing -TimeoutSec 2
    if ($r.StatusCode -eq 200) { $up = $true; break }
  } catch { }
}
if (-not $up) {
  Write-Host 'Backend nicht erreichbar. Pruefe das minimierte Backend-Fenster' -ForegroundColor Red
  Write-Host '(evtl. "pip install -r requirements.txt" im Ordner 5eyes-backend noetig).' -ForegroundColor Red
  exit 1
}
Write-Host 'Backend laeuft.' -ForegroundColor Green

# --- cloudflared einmalig laden ---
if (-not (Test-Path $cfExe)) {
  Write-Host 'Lade cloudflared (einmalig, ~30 MB) ...' -ForegroundColor Cyan
  $cfUrl = 'https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe'
  Invoke-WebRequest -Uri $cfUrl -OutFile $cfExe -UseBasicParsing
}

Write-Host ''
Write-Host '====================================================================' -ForegroundColor Green
Write-Host ' Gleich erscheint eine  https://<zufall>.trycloudflare.com  URL.'    -ForegroundColor Green
Write-Host ' Oeffne sie extern (Handy/anderer PC) MIT  /app/5eyes_v2.html :'     -ForegroundColor Green
Write-Host '   https://<zufall>.trycloudflare.com/app/5eyes_v2.html'             -ForegroundColor White
Write-Host ' Login wie gewohnt (inkl. 2FA, falls aktiviert).'                    -ForegroundColor Green
Write-Host '====================================================================' -ForegroundColor Green
Write-Host ''

# --- Tunnel im Vordergrund (zeigt die URL) ---
& $cfExe tunnel --url http://127.0.0.1:8000
