# Phase 6 Optimizer-Smoke-Test
# ============================
# Manueller End-to-End-Test fuer den stochastischen Optimizer + FE-Panel.
# Setzt OPTIMIZER_MODE=stochastic, startet Backend, ruft die 3 wichtigen
# Endpoints auf und prueft dass alle Phase-6-Felder im Response sind.
#
# Voraussetzungen:
#   - Backend dependencies installiert (pip install -r 5eyes-backend/requirements.txt)
#   - Test-DB existiert (oder wird durch das Backend angelegt)
#   - Curl im PATH (oder via Invoke-RestMethod, was unten verwendet wird)
#
# Bedienung:
#   cd C:\5eyes\5eyes_stage9_release_ready_develop_security
#   .\scripts\smoke_test_phase6_optimizer.ps1
#   ENTER drücken nach Backend-Start, Skript faehrt fort.

param(
    [string]$BackendDir = "C:\5eyes\5eyes_stage9_release_ready_develop_security\5eyes-backend",
    [string]$BaseUrl = "http://127.0.0.1:8765",
    [string]$Username = "admin",
    [string]$Password = "admin",
    [switch]$SkipServerStart
)

$ErrorActionPreference = "Stop"

Write-Host "===================================" -ForegroundColor Cyan
Write-Host "Phase 6 Optimizer Smoke Test" -ForegroundColor Cyan
Write-Host "===================================" -ForegroundColor Cyan

# ----- 1. Backend starten (oder skippen wenn schon laeuft) -----
if (-not $SkipServerStart) {
    Write-Host ""
    Write-Host "[1/5] Backend mit OPTIMIZER_MODE=stochastic starten..." -ForegroundColor Yellow
    Write-Host "Oeffne ein zweites PowerShell-Fenster und fuehre dort aus:"
    Write-Host ""
    Write-Host "  cd $BackendDir" -ForegroundColor Green
    Write-Host "  `$env:OPTIMIZER_MODE = 'stochastic'" -ForegroundColor Green
    Write-Host "  python -m uvicorn main:app --host 127.0.0.1 --port 8765" -ForegroundColor Green
    Write-Host ""
    Read-Host "Druecke ENTER sobald das Backend laeuft (Logs sollten 'Application startup complete' zeigen)"
}

# ----- 2. Login -----
Write-Host ""
Write-Host "[2/5] Login als $Username..." -ForegroundColor Yellow
try {
    $loginBody = @{ username = $Username; password = $Password } | ConvertTo-Json
    $login = Invoke-RestMethod -Method POST -Uri "$BaseUrl/auth/login" -ContentType "application/json" -Body $loginBody
    $token = $login.access_token
    if (-not $token) { throw "Kein access_token im Response" }
    Write-Host "  -> Token erhalten ($($token.Substring(0,20))...)" -ForegroundColor Green
} catch {
    Write-Host "FEHLER beim Login: $_" -ForegroundColor Red
    Write-Host "Pruefe ob das Backend laeuft und Username/Password stimmen." -ForegroundColor Red
    exit 1
}
$headers = @{ Authorization = "Bearer $token" }

# ----- 3. Mandanten finden (nimmt den ersten verfuegbaren) -----
Write-Host ""
Write-Host "[3/5] Mandanten suchen..." -ForegroundColor Yellow
try {
    $clients = Invoke-RestMethod -Method GET -Uri "$BaseUrl/clients" -Headers $headers
    if (-not $clients -or $clients.Count -eq 0) {
        Write-Host "  Keine Mandanten gefunden — bitte vorher einen anlegen." -ForegroundColor Red
        exit 1
    }
    $client = $clients[0]
    $cid = $client.id
    Write-Host "  -> Client: $($client.first_name) $($client.last_name) ($cid)" -ForegroundColor Green

    $mandates = Invoke-RestMethod -Method GET -Uri "$BaseUrl/clients/$cid/mandates" -Headers $headers
    if (-not $mandates -or $mandates.Count -eq 0) {
        Write-Host "  Keine Mandate fuer diesen Client — bitte ein Mandat anlegen." -ForegroundColor Red
        exit 1
    }
    $mandate = $mandates[0]
    $mid = $mandate.id
    Write-Host "  -> Mandate: $($mandate.mandate_number) ($mid)" -ForegroundColor Green
} catch {
    Write-Host "FEHLER beim Mandanten-Lookup: $_" -ForegroundColor Red
    exit 1
}

# ----- 4. POST /target-allocation/generate -----
Write-Host ""
Write-Host "[4/5] POST /target-allocation/generate (Solver-Lauf, ~5-10s)..." -ForegroundColor Yellow
try {
    $genBody = @{ preferences = $null } | ConvertTo-Json
    $gen = Invoke-RestMethod -Method POST -Uri "$BaseUrl/mandates/$mid/target-allocation/generate" -Headers $headers -ContentType "application/json" -Body $genBody

    $method = $gen.target_allocation.optimization_method
    $status = $gen.target_allocation.optimization_status
    $seed = $gen.target_allocation.optimization_seed
    $iter = $gen.target_allocation.optimization_iterations

    Write-Host ""
    Write-Host "  Optimizer-Audit-Felder:" -ForegroundColor Cyan
    Write-Host "    method   = $method"
    Write-Host "    status   = $status"
    Write-Host "    seed     = $seed"
    Write-Host "    iter     = $iter"

    if ($method -ne "stochastic" -and $method -ne "fallback_house_matrix") {
        Write-Host "  WARNUNG: optimization_method ist '$method' - erwartet 'stochastic' oder 'fallback_house_matrix'" -ForegroundColor Yellow
        Write-Host "  Wurde OPTIMIZER_MODE=stochastic gesetzt?" -ForegroundColor Yellow
    }

    $stress = $gen.stress_evaluations
    if ($stress) {
        Write-Host "  stress_evaluations: $($stress.PSObject.Properties.Name -join ', ')" -ForegroundColor Cyan
    } else {
        Write-Host "  stress_evaluations: NULL (Solver fiel auf Fallback)" -ForegroundColor Yellow
    }

    $reasoning = $gen.reasoning
    Write-Host "  reasoning: $($reasoning.Count) Eintraege" -ForegroundColor Cyan
    $solverLines = $reasoning | Where-Object { $_ -match "Solver|Stochastic|SLSQP|objective|Stress" }
    Write-Host "    Solver-Trace-Zeilen: $($solverLines.Count)" -ForegroundColor Cyan

    # Erstes Goal fuer Sensitivity raussuchen
    $firstGoal = $gen.goal_analysis | Select-Object -First 1
    if ($firstGoal) {
        $script:goalId = $firstGoal.goal_id
        Write-Host "  Erstes Goal: $($firstGoal.label) ($($firstGoal.goal_id))" -ForegroundColor Cyan
    }
} catch {
    Write-Host "FEHLER beim generate: $_" -ForegroundColor Red
    exit 1
}

# ----- 5. POST /target-allocation/sensitivity (-10%) -----
if ($script:goalId) {
    Write-Host ""
    Write-Host "[5/5] POST /target-allocation/sensitivity (delta=-10%, ~5s)..." -ForegroundColor Yellow
    try {
        $sensBody = @{ goal_id = $script:goalId; target_delta_pct = -10 } | ConvertTo-Json
        $sens = Invoke-RestMethod -Method POST -Uri "$BaseUrl/mandates/$mid/target-allocation/sensitivity" -Headers $headers -ContentType "application/json" -Body $sensBody

        Write-Host ""
        Write-Host "  Sensitivity-Result:" -ForegroundColor Cyan
        Write-Host "    delta_pct           = $($sens.delta_pct)"
        Write-Host "    target_baseline     = $($sens.target_amount_rappen_baseline) (Rp)"
        Write-Host "    target_new          = $($sens.target_amount_rappen_new) (Rp)"
        Write-Host "    objective_baseline  = $($sens.objective_value_milli_baseline)"
        Write-Host "    objective_new       = $($sens.objective_value_milli_new)"
        Write-Host "    delta_objective_pct = $($sens.delta_objective_pct)%"
        Write-Host "    status_baseline     = $($sens.status_baseline)"
        Write-Host "    status_new          = $($sens.status_new)"
    } catch {
        Write-Host "FEHLER beim sensitivity: $_" -ForegroundColor Red
        exit 1
    }
}

# ----- 6. Persistenz-Check via /current/payload -----
Write-Host ""
Write-Host "[Bonus] Persistenz-Check via GET /current/payload..." -ForegroundColor Yellow
try {
    $payload = Invoke-RestMethod -Method GET -Uri "$BaseUrl/mandates/$mid/target-allocation/current/payload" -Headers $headers
    $reloadStress = $payload.stress_evaluations
    $reloadReasoning = $payload.reasoning
    $reloadSolverLines = $reloadReasoning | Where-Object { $_ -match "Solver|Stochastic|SLSQP|objective|Stress" }
    Write-Host "  /current/payload stress_evaluations: $(if($reloadStress){'JA ('+$reloadStress.PSObject.Properties.Name.Count+' Szenarien)'}else{'NULL'})" -ForegroundColor Cyan
    Write-Host "  /current/payload Solver-Reasoning-Zeilen: $($reloadSolverLines.Count)" -ForegroundColor Cyan
    if ($reloadStress -and $reloadSolverLines.Count -gt 0) {
        Write-Host "  -> Persistenz Phase 6.1 + 6.2 funktioniert" -ForegroundColor Green
    } else {
        Write-Host "  -> Persistenz hat einen Gap (entweder Solver fiel auf Fallback, oder Lese-Pfad bug)" -ForegroundColor Yellow
    }
} catch {
    Write-Host "FEHLER beim payload-Check: $_" -ForegroundColor Red
}

Write-Host ""
Write-Host "===================================" -ForegroundColor Cyan
Write-Host "Smoke-Test abgeschlossen." -ForegroundColor Cyan
Write-Host "===================================" -ForegroundColor Cyan
