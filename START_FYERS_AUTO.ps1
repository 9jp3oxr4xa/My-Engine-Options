$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Root = "C:\Users\Administrator\Desktop\Dhan Test"
Set-Location -LiteralPath $Root

$env:FYERS_REDIRECT_URI = "http://127.0.0.1:8765/callback"

Write-Host ""
Write-Host "=====================================================" -ForegroundColor Cyan
Write-Host " FYERS DAILY LOGIN (FYERS ONLY)" -ForegroundColor Cyan
Write-Host "=====================================================" -ForegroundColor Cyan
Write-Host "ROOT         : $Root"
Write-Host "REDIRECT_URI : $env:FYERS_REDIRECT_URI"
Write-Host ""

# -----------------------------------------------------
# 1. Required credentials
# -----------------------------------------------------
$AppId = [Environment]::GetEnvironmentVariable("FYERS_APP_ID","Process")
if (-not $AppId) { $AppId = [Environment]::GetEnvironmentVariable("FYERS_APP_ID","User") }
if (-not $AppId) { $AppId = [Environment]::GetEnvironmentVariable("FYERS_APP_ID","Machine") }

$Secret = [Environment]::GetEnvironmentVariable("FYERS_SECRET_ID","Process")
if (-not $Secret) { $Secret = [Environment]::GetEnvironmentVariable("FYERS_SECRET_ID","User") }
if (-not $Secret) { $Secret = [Environment]::GetEnvironmentVariable("FYERS_SECRET_ID","Machine") }

if (-not $AppId) {
    Write-Host "FAIL: FYERS_APP_ID missing" -ForegroundColor Red
    Read-Host "Press ENTER"
    exit 3
}

if (-not $Secret) {
    Write-Host "FAIL: FYERS_SECRET_ID missing" -ForegroundColor Red
    Read-Host "Press ENTER"
    exit 3
}

$env:FYERS_APP_ID = $AppId
$env:FYERS_SECRET_ID = $Secret

Write-Host "[OK] FYERS_APP_ID present (len=$($AppId.Length))" -ForegroundColor Green
Write-Host "[OK] FYERS_SECRET_ID present (len=$($Secret.Length))" -ForegroundColor Green

# -----------------------------------------------------
# 2. FORCE PROJECT VENV — NEVER SYSTEM PYTHON
# -----------------------------------------------------
$Py = Join-Path $Root ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $Py)) {
    Write-Host "FAIL: Project venv Python missing: $Py" -ForegroundColor Red
    Read-Host "Press ENTER"
    exit 3
}

$PyVersion = & $Py --version 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "FAIL: Project venv Python cannot execute" -ForegroundColor Red
    Read-Host "Press ENTER"
    exit 3
}

Write-Host "[OK] Python : $Py" -ForegroundColor Green
Write-Host "[OK] $PyVersion" -ForegroundColor Green

# -----------------------------------------------------
# 3. FYERS SDK
# -----------------------------------------------------
$sdk = & $Py -c "import fyers_apiv3; print('FYERS_SDK_OK')" 2>&1

if ($LASTEXITCODE -ne 0 -or (($sdk -join " ") -notmatch "FYERS_SDK_OK")) {
    Write-Host "FAIL: fyers_apiv3 unavailable in project venv" -ForegroundColor Red
    $sdk | ForEach-Object { Write-Host $_ }
    Read-Host "Press ENTER"
    exit 3
}

Write-Host "[OK] fyers_apiv3 SDK importable" -ForegroundColor Green

# -----------------------------------------------------
# 4. Port 8765
# -----------------------------------------------------
$busy = @(
    Get-NetTCPConnection -LocalAddress "127.0.0.1" -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue
)

if ($busy.Count -gt 0) {
    Write-Host "FAIL: 127.0.0.1:8765 already in use" -ForegroundColor Red
    $busy | Select-Object LocalAddress,LocalPort,OwningProcess | Format-Table -AutoSize
    Read-Host "Press ENTER"
    exit 3
}

Write-Host "[OK] Port 8765 free" -ForegroundColor Green

# -----------------------------------------------------
# 5. Temporary token sink
# -----------------------------------------------------
$TokenSink = Join-Path $Root (".fyers_token_" + [Guid]::NewGuid().ToString("N") + ".tmp")

try {
    Write-Host ""
    Write-Host "=== STARTING FYERS LOGIN ===" -ForegroundColor Yellow
    Write-Host "Complete normal FYERS login + 2FA in the browser." -ForegroundColor Yellow
    Write-Host ""

    & $Py -u (Join-Path $Root "fyers_login.py") $TokenSink

    if ($LASTEXITCODE -ne 0) {
        Write-Host "FAIL: FYERS login helper failed." -ForegroundColor Red
        if (Test-Path -LiteralPath $TokenSink) {
            Remove-Item -LiteralPath $TokenSink -Force -ErrorAction SilentlyContinue
        }
        Read-Host "Press ENTER"
        exit 3
    }

    if (-not (Test-Path -LiteralPath $TokenSink)) {
        Write-Host "FAIL: login succeeded without token file." -ForegroundColor Red
        Read-Host "Press ENTER"
        exit 3
    }

    $Token = [System.IO.File]::ReadAllText(
        $TokenSink,
        [System.Text.Encoding]::UTF8
    ).Trim()

    Remove-Item -LiteralPath $TokenSink -Force -ErrorAction SilentlyContinue

    if ([string]::IsNullOrWhiteSpace($Token)) {
        Write-Host "FAIL: empty FYERS access token." -ForegroundColor Red
        Read-Host "Press ENTER"
        exit 3
    }

    if ($Token.Length -lt 32) {
        Write-Host "FAIL: implausibly short FYERS token ($($Token.Length))." -ForegroundColor Red
        Read-Host "Press ENTER"
        exit 3
    }

    $env:FYERS_ACCESS_TOKEN = $Token

    Write-Host ""
    Write-Host "=====================================================" -ForegroundColor Green
    Write-Host " FYERS LOGIN SUCCESS" -ForegroundColor Green
    Write-Host " FYERS_ACCESS_TOKEN = SET" -ForegroundColor Green
    Write-Host " TOKEN LENGTH       = $($Token.Length)" -ForegroundColor Green
    Write-Host "=====================================================" -ForegroundColor Green
    Write-Host ""
    Write-Host "Token exists ONLY in this PowerShell process." -ForegroundColor DarkGray
    Write-Host "No Dhan process is started by this launcher." -ForegroundColor DarkGray
    Write-Host ""
    Write-Host ""
Write-Host "=== STARTING ONE ENGINE IN SAME TOKEN PROCESS ===" -ForegroundColor Green
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -match "(?i)Dhan\.py" } |
    ForEach-Object {
        Write-Host "KILL PID $($_.ProcessId)" -ForegroundColor Yellow
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }
Start-Sleep 2
$left = @(Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -match "(?i)Dhan\.py" })

}
catch {
    if (Test-Path -LiteralPath $TokenSink) {
        Remove-Item -LiteralPath $TokenSink -Force -ErrorAction SilentlyContinue
    }

    Write-Host ""
    Write-Host "FYERS LOGIN FAILED" -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    Write-Host "No token was accepted. Nothing was started." -ForegroundColor Red
    Read-Host "Press ENTER"
    exit 3
}

# ---------------------------------------------------------------------
# LAUNCH-FIX: FYERS login has already succeeded at this point. The engine
# startup below used to live INSIDE the login try/catch, so an engine
# exception was swallowed by the login catch and mis-reported as a login
# failure. It now runs outside that catch and reports its own error and
# exit code. The relocated statements are byte-identical to the original.
# ---------------------------------------------------------------------
Write-Host '' 
Write-Host 'FYERS LOGIN SUCCESS' -ForegroundColor Green
if (-not $env:FYERS_ACCESS_TOKEN) {
    Write-Host 'TOKEN MISSING AFTER LOGIN - refusing to start the engine' -ForegroundColor Red
    exit 3
}
Write-Host ('FYERS_ACCESS_TOKEN = SET (len=' + $env:FYERS_ACCESS_TOKEN.Length + ')') -ForegroundColor Green

$__lfLocation   = (Get-Location).Path
$__lfEngineFail = $false
$__lfEngineErr  = ''
$global:LASTEXITCODE = 0
try {
if ($left.Count) {
    $left | Select-Object ProcessId,CommandLine | Format-Table -AutoSize
    throw "Dhan.py still running"
}
if ([string]::IsNullOrWhiteSpace($env:FYERS_ACCESS_TOKEN)) {
    throw "Fresh FYERS token missing in launcher process"
}
Write-Host "[PASS] FYERS_ACCESS_TOKEN length=$($env:FYERS_ACCESS_TOKEN.Length)" -ForegroundColor Green
Write-Host "[PASS] ZERO OLD ENGINES" -ForegroundColor Green
& "$Root\.venv\Scripts\python.exe" "$Root\Dhan.py" 2>&1 |
    Tee-Object "$Root\logs\engine-live-current.txt"
    exit 0
}
catch {
    $__lfEngineFail = $true
    $__lfEngineErr  = $_.Exception.Message
    Write-Host ''
    Write-Host 'ENGINE START FAILED  (FYERS login had already SUCCEEDED)' -ForegroundColor Red
    Write-Host ('ENGINE ERROR : ' + $__lfEngineErr) -ForegroundColor Red
    if ($_.InvocationInfo -and $_.InvocationInfo.PositionMessage) {
        Write-Host ('ENGINE AT    : ' + $_.InvocationInfo.PositionMessage) -ForegroundColor Red
    }
    if ($_.ScriptStackTrace) {
        Write-Host ('ENGINE STACK : ' + $_.ScriptStackTrace) -ForegroundColor DarkGray
    }
}
Set-Location -LiteralPath $__lfLocation -ErrorAction SilentlyContinue

$__lfEngineExit = $LASTEXITCODE
if ($null -eq $__lfEngineExit) { $__lfEngineExit = 0 }
Write-Host ''
if ($__lfEngineFail) {
    Write-Host ('RESULT : ENGINE FAILED  (exception, last exit code ' + $__lfEngineExit + ')') -ForegroundColor Red
    exit 4
}
if ($__lfEngineExit -ne 0) {
    Write-Host ('RESULT : ENGINE EXITED NON-ZERO  exit=' + $__lfEngineExit) -ForegroundColor Red
    exit $__lfEngineExit
}
Write-Host 'RESULT : ENGINE EXITED CLEANLY  exit=0' -ForegroundColor Green

