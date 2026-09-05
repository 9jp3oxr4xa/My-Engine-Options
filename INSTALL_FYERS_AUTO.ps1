# =====================================================================
#  INSTALLER : FYERS-ONLY DAILY LOGIN  (Windows PowerShell 5.1 tested)
#  Creates   : C:\Users\Administrator\Desktop\Dhan Test\fyers_login.py
#              C:\Users\Administrator\Desktop\Dhan Test\START_FYERS_AUTO.ps1
#              C:\Users\Administrator\Desktop\START FYERS AUTO.lnk
#  Redirect  : http://127.0.0.1:8765/callback   (exact, registered)
#  No Dhan. No Telegram. Fail-closed. No nested here-strings.
#  Paste this whole block into PowerShell 5.1 and press Enter.
# =====================================================================

$ErrorActionPreference = 'Stop'

$ProjDir  = 'C:\Users\Administrator\Desktop\Dhan Test'
$DeskDir  = 'C:\Users\Administrator\Desktop'
$Redirect = 'http://127.0.0.1:8765/callback'

$HelperPath   = Join-Path $ProjDir 'fyers_login.py'
$LauncherPath = Join-Path $ProjDir 'START_FYERS_AUTO.ps1'
$ShortcutPath = Join-Path $DeskDir 'START FYERS AUTO.lnk'

function Abort([string]$code, [string]$why) {
    Write-Host ''
    Write-Host ('INSTALL FAILED [' + $code + ']') -ForegroundColor Red
    Write-Host ('REASON : ' + $why) -ForegroundColor Red
    exit 3
}

Write-Host '=====================================================' -ForegroundColor Cyan
Write-Host '  INSTALL : FYERS DAILY LOGIN (FYERS ONLY)' -ForegroundColor Cyan
Write-Host '=====================================================' -ForegroundColor Cyan

if (-not (Test-Path -LiteralPath $ProjDir)) { Abort 'E_NO_PROJDIR' ('Missing directory: ' + $ProjDir) }
if (-not (Test-Path -LiteralPath $DeskDir)) { Abort 'E_NO_DESKTOP' ('Missing directory: ' + $DeskDir) }

# ---------------------------------------------------------------------
# PAYLOAD 1 : Python login helper (single literal here-string, no nesting)
# ---------------------------------------------------------------------
$PyBody = @'
"""FYERS-only interactive login helper.

Generates the official FYERS login URL, captures auth_code on the registered
loopback redirect (http://127.0.0.1:8765/callback), exchanges it for a fresh
access token with the official fyers_apiv3 SDK, and writes ONLY that token to
the file path given as argv[1].

Never prints the token. Never touches Dhan. Fails closed on every error.
"""

from __future__ import annotations

import os
import secrets
import socket
import sys
import threading
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Dict, NoReturn, Optional

REDIRECT_URI = "http://127.0.0.1:8765/callback"
BIND_HOST = "127.0.0.1"
BIND_PORT = 8765
CALLBACK_PATH = "/callback"
LOGIN_TIMEOUT_S = 300


def out(message: str) -> None:
    sys.stdout.write(message + "\n")
    sys.stdout.flush()


def fail(code: str, detail: str = "") -> NoReturn:
    out("FYERS_LOGIN_FAIL=" + code)
    if detail:
        out("DETAIL=" + detail)
    raise SystemExit(1)


RESULT: Dict[str, Optional[str]] = {"auth_code": None, "state": None, "error": None}
DONE = threading.Event()


class ExclusiveHTTPServer(HTTPServer):
    # False so a second listener can never hijack port 8765 on Windows.
    allow_reuse_address = False


class CallbackHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def log_message(self, fmt: str, *args: Any) -> None:
        return

    def _reply(self, status: int, body: bytes, ctype: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != CALLBACK_PATH:
            self._reply(404, b"NOT_FOUND", "text/plain; charset=utf-8")
            return

        qs = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
        status = (qs.get("s", [""])[0] or "").strip().lower()
        auth_code = (qs.get("auth_code", [""])[0] or "").strip()
        state = (qs.get("state", [""])[0] or "").strip()
        err = (qs.get("error", [""])[0] or "").strip()
        err_code = (qs.get("error_code", [""])[0] or "").strip()
        err_msg = (qs.get("message", [""])[0] or "").strip()

        if err:
            RESULT["error"] = "CALLBACK_ERROR:" + err
        elif err_code:
            RESULT["error"] = "CALLBACK_ERROR_CODE:" + err_code
        elif status and status != "ok":
            RESULT["error"] = "CALLBACK_STATUS_NOT_OK:" + status
        elif not auth_code:
            RESULT["error"] = "AUTH_CODE_MISSING"
            if err_msg:
                RESULT["error"] = "AUTH_CODE_MISSING:" + err_msg
        else:
            RESULT["auth_code"] = auth_code
            RESULT["state"] = state

        if RESULT["auth_code"]:
            page = (
                b"<html><body style=\"font-family:Segoe UI,Arial;text-align:center;"
                b"margin-top:90px\"><h1>FYERS LOGIN CAPTURED</h1>"
                b"<p>Return to the PowerShell window. You may close this tab.</p>"
                b"</body></html>"
            )
        else:
            page = (
                b"<html><body style=\"font-family:Segoe UI,Arial;text-align:center;"
                b"margin-top:90px\"><h1>FYERS LOGIN FAILED</h1>"
                b"<p>Return to the PowerShell window for the exact reason.</p>"
                b"</body></html>"
            )
        self._reply(200, page, "text/html; charset=utf-8")
        DONE.set()


def port_is_free() -> bool:
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind((BIND_HOST, BIND_PORT))
    except OSError:
        return False
    finally:
        try:
            probe.close()
        except OSError:
            pass
    return True


def main() -> int:
    if len(sys.argv) < 2 or not sys.argv[1].strip():
        fail("TOKEN_SINK_ARG_MISSING")
    token_sink = sys.argv[1].strip()

    app_id = os.environ.get("FYERS_APP_ID", "").strip()
    secret_id = os.environ.get("FYERS_SECRET_ID", "").strip()
    if not app_id:
        fail("FYERS_APP_ID_MISSING")
    if not secret_id:
        fail("FYERS_SECRET_ID_MISSING")

    try:
        from fyers_apiv3 import fyersModel
    except Exception as exc:
        fail("FYERS_SDK_IMPORT_FAILED", str(exc))

    if not port_is_free():
        fail("PORT_8765_IN_USE",
             "close the process holding 127.0.0.1:8765 and retry")

    state = secrets.token_urlsafe(24)
    try:
        session = fyersModel.SessionModel(
            client_id=app_id,
            secret_key=secret_id,
            redirect_uri=REDIRECT_URI,
            response_type="code",
            grant_type="authorization_code",
            state=state,
        )
        auth_url = session.generate_authcode()
    except Exception as exc:
        fail("AUTH_URL_GENERATION_FAILED", str(exc))

    if not isinstance(auth_url, str) or not auth_url.startswith("http"):
        fail("AUTH_URL_INVALID", str(auth_url))

    try:
        server = ExclusiveHTTPServer((BIND_HOST, BIND_PORT), CallbackHandler)
    except OSError as exc:
        fail("CALLBACK_BIND_FAILED", str(exc))

    server.timeout = 1.0
    worker = threading.Thread(target=server.serve_forever,
                              kwargs={"poll_interval": 0.25},
                              name="fyers-callback", daemon=True)
    worker.start()

    out("REDIRECT_URI=" + REDIRECT_URI)
    out("CALLBACK_LISTENING=1")
    out("AUTH_URL_READY=1")

    opened = False
    try:
        opened = bool(webbrowser.open(auth_url, new=1))
    except Exception:
        opened = False
    if opened:
        out("BROWSER_OPENED=1")
    else:
        out("BROWSER_OPEN_FAILED=1")
        out("OPEN_THIS_URL_MANUALLY:")
        out(auth_url)

    out("WAITING_FOR_LOGIN=1 timeout_s=" + str(LOGIN_TIMEOUT_S))
    captured = DONE.wait(LOGIN_TIMEOUT_S)

    try:
        server.shutdown()
    except Exception:
        pass
    try:
        server.server_close()
    except Exception:
        pass

    if not captured:
        fail("LOGIN_TIMEOUT",
             "no callback within " + str(LOGIN_TIMEOUT_S) + "s")

    if RESULT["error"]:
        fail("CALLBACK_REJECTED", str(RESULT["error"]))

    auth_code = RESULT["auth_code"] or ""
    if not auth_code:
        fail("AUTH_CODE_MISSING")

    returned_state = RESULT["state"] or ""
    if returned_state and returned_state != state:
        fail("STATE_MISMATCH")

    out("AUTH_CODE_CAPTURED=1")

    try:
        session.set_token(auth_code)
        response = session.generate_token()
    except Exception as exc:
        fail("TOKEN_EXCHANGE_EXCEPTION", str(exc))

    if not isinstance(response, dict):
        fail("TOKEN_EXCHANGE_BAD_RESPONSE", str(type(response)))
    if response.get("s") != "ok":
        fail("TOKEN_EXCHANGE_REJECTED",
             "s=" + str(response.get("s")) + " code=" + str(response.get("code"))
             + " message=" + str(response.get("message")))

    access_token = str(response.get("access_token", "") or "").strip()
    if not access_token:
        fail("ACCESS_TOKEN_EMPTY")

    try:
        with open(token_sink, "w", encoding="utf-8", newline="") as fh:
            fh.write(access_token)
            fh.flush()
            os.fsync(fh.fileno())
    except OSError as exc:
        fail("TOKEN_SINK_WRITE_FAILED", str(exc))

    try:
        written = os.path.getsize(token_sink)
    except OSError as exc:
        fail("TOKEN_SINK_VERIFY_FAILED", str(exc))
    if written != len(access_token.encode("utf-8")):
        fail("TOKEN_SINK_SIZE_MISMATCH", str(written))

    out("TOKEN_EXCHANGE=OK")
    out("TOKEN_LENGTH=" + str(len(access_token)))
    out("FYERS_LOGIN_OK=1")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'@

# ---------------------------------------------------------------------
# PAYLOAD 2 : PowerShell launcher (single literal here-string, no nesting)
# ---------------------------------------------------------------------
$Ps1Body = @'
# =====================================================================
#  START FYERS AUTO  --  FYERS-ONLY daily login (Windows PowerShell 5.1)
#  Redirect URI (registered, exact): http://127.0.0.1:8765/callback
#  Fail-closed. Never starts Dhan. Never requires Dhan/Telegram secrets.
# =====================================================================

$ErrorActionPreference = 'Stop'

$Root      = if ($PSScriptRoot) { $PSScriptRoot } else { (Get-Location).Path }
$Helper    = Join-Path $Root 'fyers_login.py'
$Redirect  = 'http://127.0.0.1:8765/callback'
$TokenSink = Join-Path $Root ('.fyers_token_' + [Guid]::NewGuid().ToString('N') + '.tmp')

function Say([string]$m)  { Write-Host $m }
function Good([string]$m) { Write-Host $m -ForegroundColor Green }
function Note([string]$m) { Write-Host $m -ForegroundColor DarkGray }

function Cleanup {
    if (Test-Path -LiteralPath $TokenSink) {
        try {
            $len = (Get-Item -LiteralPath $TokenSink).Length
            if ($len -gt 0) {
                $pad = New-Object byte[] $len
                [System.IO.File]::WriteAllBytes($TokenSink, $pad)
            }
        } catch { }
        Remove-Item -LiteralPath $TokenSink -Force -ErrorAction SilentlyContinue
    }
}

function Stop-Closed([string]$code, [string]$why) {
    Cleanup
    Write-Host ''
    Write-Host '=====================================================' -ForegroundColor Red
    Write-Host ('FYERS LOGIN FAILED  [' + $code + ']') -ForegroundColor Red
    Write-Host ('REASON : ' + $why) -ForegroundColor Red
    Write-Host 'FYERS_ACCESS_TOKEN = NOT SET' -ForegroundColor Red
    Write-Host 'Nothing was started. Fail closed.' -ForegroundColor Red
    Write-Host '=====================================================' -ForegroundColor Red
    exit 3
}

Write-Host '=====================================================' -ForegroundColor Cyan
Write-Host '  FYERS DAILY LOGIN  (FYERS ONLY - no Dhan, no Telegram)' -ForegroundColor Cyan
Write-Host '=====================================================' -ForegroundColor Cyan
Say ('ROOT         : ' + $Root)
Say ('REDIRECT_URI : ' + $Redirect)
Say ''

# ---------------------------------------------------------- 1. helper file
if (-not (Test-Path -LiteralPath $Helper)) {
    Stop-Closed 'E_NO_HELPER' ('Missing helper script: ' + $Helper)
}
Good '[OK] Login helper present'

# ------------------------------------------------------- 2. FYERS env vars
$AppId  = [Environment]::GetEnvironmentVariable('FYERS_APP_ID','Process')
if (-not $AppId) { $AppId = [Environment]::GetEnvironmentVariable('FYERS_APP_ID','User') }
if (-not $AppId) { $AppId = [Environment]::GetEnvironmentVariable('FYERS_APP_ID','Machine') }

$Secret = [Environment]::GetEnvironmentVariable('FYERS_SECRET_ID','Process')
if (-not $Secret) { $Secret = [Environment]::GetEnvironmentVariable('FYERS_SECRET_ID','User') }
if (-not $Secret) { $Secret = [Environment]::GetEnvironmentVariable('FYERS_SECRET_ID','Machine') }

if (-not $AppId)  { Stop-Closed 'E_NO_APP_ID' 'FYERS_APP_ID is not set (process/user/machine).' }
if (-not $Secret) { Stop-Closed 'E_NO_SECRET' 'FYERS_SECRET_ID is not set (process/user/machine).' }

$env:FYERS_APP_ID    = $AppId
$env:FYERS_SECRET_ID = $Secret
Good ('[OK] FYERS_APP_ID present (len=' + $AppId.Length + ')')
Good ('[OK] FYERS_SECRET_ID present (len=' + $Secret.Length + ')')

# ---------------------------------------------------------- 3. interpreter
$Py = ''
$cands = @()
if ($env:FYERS_PYTHON_EXE) { $cands += $env:FYERS_PYTHON_EXE }
$cands += 'python'
$cands += 'py'
foreach ($c in $cands) {
    try { $probe = & $c -c "import sys;print(sys.executable)" 2>$null } catch { continue }
    if ($LASTEXITCODE -eq 0 -and $probe) { $Py = ($probe | Select-Object -First 1); break }
}
if (-not $Py) { Stop-Closed 'E_NO_PYTHON' 'No usable Python interpreter found on PATH.' }
Good ('[OK] Python : ' + $Py)

# ------------------------------------------------------------- 4. FYERS SDK
$sdk = & $Py -c "import fyers_apiv3;print('FYERS_SDK_OK')" 2>&1
if (($sdk -join ' ') -notmatch 'FYERS_SDK_OK') {
    Stop-Closed 'E_NO_SDK' ('fyers_apiv3 not importable: ' + ($sdk -join ' '))
}
Good '[OK] fyers_apiv3 SDK importable'

# --------------------------------------------------------------- 5. port 8765
$busy = $null
try {
    $busy = Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction Stop
} catch {
    $busy = $null
}
if ($busy) {
    $owners = @()
    foreach ($b in $busy) {
        $pname = 'unknown'
        try { $pname = (Get-Process -Id $b.OwningProcess -ErrorAction Stop).ProcessName } catch { }
        $owners += ($pname + ' (PID ' + $b.OwningProcess + ')')
    }
    Stop-Closed 'E_PORT_BUSY' ('127.0.0.1:8765 already has a listener: ' + ($owners -join ', ') + '. Close it and retry.')
}
Good '[OK] Port 8765 free for the callback listener'

# -------------------------------------------------------------- 6. do login
Say ''
Write-Host '-----------------------------------------------------' -ForegroundColor Cyan
Write-Host ' A browser window will open the FYERS login page.' -ForegroundColor Cyan
Write-Host ' Complete your normal FYERS login + OTP/2FA there.' -ForegroundColor Cyan
Write-Host ' The auth_code is captured automatically on 8765.' -ForegroundColor Cyan
Write-Host ' Timeout: 300 seconds.' -ForegroundColor Cyan
Write-Host '-----------------------------------------------------' -ForegroundColor Cyan
Say ''

& $Py -u $Helper $TokenSink
$rc = $LASTEXITCODE

if ($rc -ne 0) {
    Stop-Closed 'E_LOGIN' ('Login helper exited with code ' + $rc + ' (see the FYERS_LOGIN_FAIL line above).')
}

# ------------------------------------------------------- 7. consume token
if (-not (Test-Path -LiteralPath $TokenSink)) {
    Stop-Closed 'E_NO_TOKEN_FILE' 'Helper reported success but no token was produced.'
}

$Token = ''
try {
    $Token = [System.IO.File]::ReadAllText($TokenSink, [System.Text.Encoding]::UTF8)
} catch {
    Stop-Closed 'E_TOKEN_READ' $_.Exception.Message
}
$Token = $Token.Trim()
Cleanup

if (-not $Token)          { Stop-Closed 'E_TOKEN_EMPTY' 'Token file was empty after login.' }
if ($Token.Length -lt 32) { Stop-Closed 'E_TOKEN_SHORT' ('Token length ' + $Token.Length + ' is implausible; refusing.') }

$env:FYERS_ACCESS_TOKEN = $Token
if (-not $env:FYERS_ACCESS_TOKEN) {
    Stop-Closed 'E_TOKEN_NOT_SET' 'Failed to place the token into this process environment.'
}

Say ''
Write-Host '=====================================================' -ForegroundColor Green
Write-Host ' FYERS LOGIN SUCCESS' -ForegroundColor Green
Write-Host ' FYERS_ACCESS_TOKEN = SET' -ForegroundColor Green
Write-Host '=====================================================' -ForegroundColor Green
Note (' token length : ' + $env:FYERS_ACCESS_TOKEN.Length)
Note (' scope        : this PowerShell process only (not persisted)')
Note (' temp file    : shredded and removed')
Note (' Dhan         : NOT started (by design)')
Say ''
Say 'This window stays open. The token lives in $env:FYERS_ACCESS_TOKEN here.'
exit 0
'@

# ---------------------------------------------------------------------
# WRITE FILES (UTF-8, no BOM)
# ---------------------------------------------------------------------
$enc = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($HelperPath,   $PyBody,  $enc)
[System.IO.File]::WriteAllText($LauncherPath, $Ps1Body, $enc)
Write-Host ('[OK] wrote ' + $HelperPath)   -ForegroundColor Green
Write-Host ('[OK] wrote ' + $LauncherPath) -ForegroundColor Green

# ---------------------------------------------------------------------
# DESKTOP SHORTCUT
# ---------------------------------------------------------------------
$PsExe = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
if (-not (Test-Path -LiteralPath $PsExe)) { Abort 'E_NO_POWERSHELL' ('Not found: ' + $PsExe) }

if (Test-Path -LiteralPath $ShortcutPath) { Remove-Item -LiteralPath $ShortcutPath -Force }

$shell = New-Object -ComObject WScript.Shell
$lnk = $shell.CreateShortcut($ShortcutPath)
$lnk.TargetPath       = $PsExe
$lnk.Arguments        = '-NoLogo -NoProfile -ExecutionPolicy Bypass -NoExit -File "' + $LauncherPath + '"'
$lnk.WorkingDirectory = $ProjDir
$lnk.WindowStyle      = 1
$lnk.IconLocation     = $PsExe + ',0'
$lnk.Description      = 'FYERS daily API login (FYERS only, no Dhan start)'
$lnk.Save()
[System.Runtime.InteropServices.Marshal]::ReleaseComObject($shell) | Out-Null

if (-not (Test-Path -LiteralPath $ShortcutPath)) { Abort 'E_NO_SHORTCUT' 'Shortcut was not created.' }
Write-Host ('[OK] wrote ' + $ShortcutPath) -ForegroundColor Green

# ---------------------------------------------------------------------
# SELF-TEST (no browser, no login, no Dhan)
# ---------------------------------------------------------------------
Write-Host ''
Write-Host '--------------------- SELF-TEST ---------------------' -ForegroundColor Cyan
$fails = @()

$raw  = Get-Content -LiteralPath $LauncherPath -Raw
$errs = $null
$toks = [System.Management.Automation.PSParser]::Tokenize($raw, [ref]$errs)
if ($errs -and $errs.Count -gt 0) {
    $fails += 'launcher_parse'
    Write-Host ('[!!] launcher parse errors = ' + $errs.Count) -ForegroundColor Red
    foreach ($e in $errs) { Write-Host ('     ' + $e.Message) -ForegroundColor Red }
} else {
    Write-Host ('[OK] launcher parses under PowerShell ' + $PSVersionTable.PSVersion.ToString() + ' (tokens=' + $toks.Count + ')') -ForegroundColor Green
}

$Py = ''
$cands = @()
if ($env:FYERS_PYTHON_EXE) { $cands += $env:FYERS_PYTHON_EXE }
$cands += 'python'
$cands += 'py'
foreach ($c in $cands) {
    try { $probe = & $c -c "import sys;print(sys.executable)" 2>$null } catch { continue }
    if ($LASTEXITCODE -eq 0 -and $probe) { $Py = ($probe | Select-Object -First 1); break }
}
if (-not $Py) {
    $fails += 'python'
    Write-Host '[!!] no Python interpreter on PATH' -ForegroundColor Red
} else {
    Write-Host ('[OK] Python : ' + $Py) -ForegroundColor Green
    $pc = & $Py -m py_compile $HelperPath 2>&1
    if ($LASTEXITCODE -eq 0) { Write-Host '[OK] fyers_login.py compiles' -ForegroundColor Green }
    else { $fails += 'py_compile'; Write-Host ('[!!] py_compile failed: ' + ($pc -join ' ')) -ForegroundColor Red }
    $sdk = & $Py -c "import fyers_apiv3;print('FYERS_SDK_OK')" 2>&1
    if (($sdk -join ' ') -match 'FYERS_SDK_OK') { Write-Host '[OK] fyers_apiv3 SDK installed' -ForegroundColor Green }
    else { $fails += 'sdk'; Write-Host ('[!!] fyers_apiv3 not importable: ' + ($sdk -join ' ')) -ForegroundColor Red }
}

$AppId  = [Environment]::GetEnvironmentVariable('FYERS_APP_ID','Process')
if (-not $AppId) { $AppId = [Environment]::GetEnvironmentVariable('FYERS_APP_ID','User') }
if (-not $AppId) { $AppId = [Environment]::GetEnvironmentVariable('FYERS_APP_ID','Machine') }
$Secret = [Environment]::GetEnvironmentVariable('FYERS_SECRET_ID','Process')
if (-not $Secret) { $Secret = [Environment]::GetEnvironmentVariable('FYERS_SECRET_ID','User') }
if (-not $Secret) { $Secret = [Environment]::GetEnvironmentVariable('FYERS_SECRET_ID','Machine') }
if ($AppId)  { Write-Host ('[OK] FYERS_APP_ID present (len=' + $AppId.Length + ')') -ForegroundColor Green }
else { $fails += 'app_id'; Write-Host '[!!] FYERS_APP_ID missing' -ForegroundColor Red }
if ($Secret) { Write-Host ('[OK] FYERS_SECRET_ID present (len=' + $Secret.Length + ')') -ForegroundColor Green }
else { $fails += 'secret_id'; Write-Host '[!!] FYERS_SECRET_ID missing' -ForegroundColor Red }

$uriOk = $true
foreach ($f in @($HelperPath, $LauncherPath)) {
    $c = Get-Content -LiteralPath $f -Raw
    if ($c -notmatch [regex]::Escape($Redirect)) { $uriOk = $false }
    if ($c -match 'localhost:8765') { $uriOk = $false }
}
if ($uriOk) { Write-Host ('[OK] redirect URI is exactly ' + $Redirect) -ForegroundColor Green }
else { $fails += 'redirect_uri'; Write-Host '[!!] redirect URI mismatch' -ForegroundColor Red }

$dhanHit = @()
foreach ($f in @($HelperPath, $LauncherPath)) {
    $c = Get-Content -LiteralPath $f -Raw
    if ($c -match 'Dhan\.py' -or $c -match 'DHAN_ACCESS_TOKEN' -or $c -match 'DHAN_CLIENT_ID' -or $c -match 'TG_BOT_TOKEN' -or $c -match 'TG_CHAT_ID') { $dhanHit += $f }
}
if ($dhanHit.Count -eq 0) { Write-Host '[OK] no Dhan / Telegram dependency in either file' -ForegroundColor Green }
else { $fails += 'dhan_refs'; Write-Host ('[!!] forbidden references in: ' + ($dhanHit -join ', ')) -ForegroundColor Red }

$vs = New-Object -ComObject WScript.Shell
$chk = $vs.CreateShortcut($ShortcutPath)
$argOk = ($chk.Arguments -match '-NoLogo') -and ($chk.Arguments -match '-NoProfile') -and ($chk.Arguments -match '-ExecutionPolicy Bypass') -and ($chk.Arguments -match '-NoExit') -and ($chk.Arguments -match [regex]::Escape($LauncherPath))
$wdOk = ($chk.WorkingDirectory -eq $ProjDir)
[System.Runtime.InteropServices.Marshal]::ReleaseComObject($vs) | Out-Null
if ($argOk) { Write-Host '[OK] shortcut arguments include -NoLogo -NoProfile -ExecutionPolicy Bypass -NoExit -File' -ForegroundColor Green }
else { $fails += 'lnk_args'; Write-Host ('[!!] shortcut arguments wrong: ' + $chk.Arguments) -ForegroundColor Red }
if ($wdOk) { Write-Host ('[OK] shortcut working directory = ' + $ProjDir) -ForegroundColor Green }
else { $fails += 'lnk_wd'; Write-Host ('[!!] shortcut working directory = ' + $chk.WorkingDirectory) -ForegroundColor Red }

Write-Host '-----------------------------------------------------' -ForegroundColor Cyan
Write-Host ''
if ($fails.Count -gt 0) { Abort 'E_SELFTEST' ('failed checks: ' + ($fails -join ', ')) }

Write-Host '=====================================================' -ForegroundColor Green
Write-Host ' INSTALL COMPLETE - SELF-TEST PASSED' -ForegroundColor Green
Write-Host '=====================================================' -ForegroundColor Green
Write-Host ''
Write-Host 'SHORTCUT (double-click this every day):' -ForegroundColor Yellow
Write-Host ('  ' + $ShortcutPath) -ForegroundColor Yellow
Write-Host ''
Write-Host 'LAUNCHER:'
Write-Host ('  ' + $LauncherPath)
Write-Host 'HELPER:'
Write-Host ('  ' + $HelperPath)
Write-Host ''
Write-Host 'TEST COMMAND:'
Write-Host ('  powershell -NoLogo -NoProfile -ExecutionPolicy Bypass -NoExit -File "' + $LauncherPath + '"')
exit 0
