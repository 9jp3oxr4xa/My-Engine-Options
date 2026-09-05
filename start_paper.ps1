$ErrorActionPreference = "Stop"

$ROOT = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ROOT

# ------------------------------------------------------------
# HYDRATE PROCESS ENVIRONMENT FROM PERSISTENT USER ENVIRONMENT
# ------------------------------------------------------------

$vars = @(
    "FYERS_APP_ID",
    "TG_BOT_TOKEN",
    "TG_CHAT_ID",
    "DHAN_PYTHON_EXE"
)

foreach($name in $vars) {
    $v = [Environment]::GetEnvironmentVariable($name, "User")
    if([string]::IsNullOrWhiteSpace($v)) {
        throw "PERSISTENT_USER_VALUE_MISSING: $name"
    }
    Set-Item -Path "Env:$name" -Value $v
}

# FYERS token is authoritative from the project token file.
$tokenFile = Join-Path $ROOT "fyers_access_token.txt"

if(-not (Test-Path $tokenFile)) {
    throw "FYERS_TOKEN_FILE_MISSING"
}

$token = (Get-Content $tokenFile -Raw).Trim()

if([string]::IsNullOrWhiteSpace($token)) {
    throw "FYERS_TOKEN_FILE_EMPTY"
}

$env:FYERS_ACCESS_TOKEN = $token

# ------------------------------------------------------------
# VERIFY
# ------------------------------------------------------------

Write-Host "=== RUNTIME HYDRATION ===" -ForegroundColor Cyan
Write-Host "FYERS_APP_ID_SET =" ([bool]$env:FYERS_APP_ID)
Write-Host "FYERS_ACCESS_TOKEN_SET =" ([bool]$env:FYERS_ACCESS_TOKEN)
Write-Host "TG_BOT_TOKEN_SET =" ([bool]$env:TG_BOT_TOKEN)
Write-Host "TG_CHAT_ID_SET =" ([bool]$env:TG_CHAT_ID)
Write-Host "DHAN_PYTHON_EXE =" $env:DHAN_PYTHON_EXE

# ------------------------------------------------------------
# FINAL STARTUP AUDIT
# ------------------------------------------------------------

python -u (Join-Path $ROOT "_final_startup_audit.py")

if($LASTEXITCODE -ne 0) {
    throw "STARTUP_AUDIT_FAILED"
}

Write-Host ""
Write-Host "STARTUP_AUDIT=PASS" -ForegroundColor Green
Write-Host "RUNTIME_HYDRATION=PASS" -ForegroundColor Green

# ------------------------------------------------------------
# LAUNCH ENGINE
# ------------------------------------------------------------

Write-Host ""
Write-Host "=== STARTING FYERS ENGINE ===" -ForegroundColor Cyan

$launcher = Join-Path $ROOT "fyers_auto_start.py"

if(-not (Test-Path $launcher)) {
    throw "LAUNCHER_MISSING: $launcher"
}

& $env:DHAN_PYTHON_EXE -u $launcher

$exitCode = $LASTEXITCODE

Write-Host ""
Write-Host "FYERS_AUTO_START_EXIT_CODE = $exitCode"

exit $exitCode
