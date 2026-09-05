<#
 FYERS RECONNECT REMEDIATION - SURGICAL PATCH
 TARGET : C:\Users\Administrator\Desktop\Dhan Test\Dhan.py   (only file touched)
 FIXES  : FYERS-R1  SDK reconnect budget is finite (max_reconnect_attempts=50);
                    after exhaustion the SDK logs "Max reconnect attempts
                    reached. Connection abandoned." and never reconnects.
                    Dhan.py spawned the worker once (if self._thread is None)
                    and never rebuilt the socket -> permanent silent feed death.
          FYERS-R2  SDK __on_close reconnects internally WITHOUT invoking the
                    user on_close, so _on_close never fired, reconnect_count
                    stayed 0 and HealthMonitor reconnect_delta was untruthful
                    (production 27-Aug: repeated "Connection to remote host was
                    lost." with reconnects=0 and zero fyers_close events).
          FYERS-R3  Stale-callback isolation was inert: _on_message compared
                    session to self._session after copying it, which can never
                    differ. Callbacks are now bound to the creating session.
#>

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$Target = 'C:\Users\Administrator\Desktop\Dhan Test\Dhan.py'
$Stamp  = Get-Date -Format 'yyyyMMdd-HHmmss'
$Backup = "$Target.$Stamp.bak"

function Fail([string]$c,[string]$m){
  Write-Host ''
  Write-Host "FAIL [$c] $m" -ForegroundColor Red
  Write-Host 'Dhan.py UNCHANGED. FAIL CLOSED.' -ForegroundColor Red
  exit 3
}

if (-not (Test-Path -LiteralPath $Target)) { Fail 'E_NO_TARGET' "Missing: $Target" }

$bytes  = [System.IO.File]::ReadAllBytes($Target)
$hasBom = ($bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF)
$raw    = [System.IO.File]::ReadAllText($Target, [System.Text.Encoding]::UTF8)
$nl     = if ($raw -match "`r`n") { "`r`n" } else { "`n" }

if ($raw -match '_hard_reset') { Fail 'E_ALREADY_APPLIED' 'Marker _hard_reset already present.' }

$A1 = @(
'    def _connect_blocking(self) -> None:',
'        self._socket = fyers_data_ws.FyersDataSocket(',
'            access_token=f"{self.app_id}:{self.access_token}",',
'            log_path="",',
'            litemode=False,',
'            write_to_file=False,',
'            reconnect=True,',
'            on_connect=self._on_connect,',
'            on_message=self._on_message,',
'            on_error=self._on_error,',
'            on_close=self._on_close,',
'        )',
'        self._socket.connect()'
) -join $nl

$R1 = @(
'    def _connect_blocking(self) -> None:',
'        # FYERS-R3: bind every SDK callback to the feed-session that created',
'        # THIS socket, so callbacks from an abandoned socket are discarded',
'        # instead of mutating live state or delivering stale ticks.',
'        _session = self._session',
'',
'        def _bind(handler: Callable[..., None]) -> Callable[..., None]:',
'            def _guarded(*args: Any) -> None:',
'                if self._stopped or _session != self._session:',
'                    self.metrics.inc("fyers_stale_callbacks")',
'                    return',
'                handler(*args)',
'            return _guarded',
'',
'        _socket = fyers_data_ws.FyersDataSocket(',
'            access_token=f"{self.app_id}:{self.access_token}",',
'            log_path="",',
'            litemode=False,',
'            write_to_file=False,',
'            reconnect=True,',
'            on_connect=_bind(self._on_connect),',
'            on_message=_bind(self._on_message),',
'            on_error=_bind(self._on_error),',
'            on_close=_bind(self._on_close),',
'        )',
'        self._socket = _socket',
'        _socket.connect()'
) -join $nl

$A2 = @(
'    async def run(self) -> None:',
'        self._loop = asyncio.get_running_loop()',
'        self._session += 1',
'        if self._thread is None:',
'            import threading',
'            self._thread = threading.Thread(',
'                target=self._connect_blocking,',
'                name="fyers-data",',
'                daemon=True,',
'            )',
'            self._thread.start()',
'        while not self._stopped:',
'            await asyncio.sleep(1.0)'
) -join $nl

$R2 = @(
'    def _sdk_abandoned(self) -> bool:',
'        # FYERS-R1: the SDK reconnect budget is finite',
'        # (max_reconnect_attempts, default 50). Once spent the SDK reports',
'        # "Max reconnect attempts reached. Connection abandoned." and never',
'        # reconnects again. Detect that terminal state deterministically.',
'        # A missing socket is NOT reported here; absence is handled by the',
'        # debounced path so a just-spawned worker cannot cause a reset storm.',
'        _socket = self._socket',
'        if _socket is None:',
'            return False',
'        try:',
'            _attempts = int(getattr(_socket, "reconnect_attempts", 0))',
'            _budget = int(getattr(_socket, "max_reconnect_attempts", 0))',
'        except (TypeError, ValueError):',
'            return False',
'        return _budget > 0 and _attempts >= _budget',
'',
'    def _sdk_socket_absent(self) -> bool:',
'        # True while the SDK holds no live websocket object.',
'        _socket = self._socket',
'        if _socket is None:',
'            return True',
'        _probe = getattr(_socket, "is_connected", None)',
'        if not callable(_probe):',
'            return False',
'        try:',
'            return not bool(_probe())',
'        except Exception:',
'            return False',
'',
'    def _spawn_socket_worker(self) -> None:',
'        import threading',
'        self._thread = threading.Thread(',
'            target=self._connect_blocking,',
'            name=f"fyers-data-{self._session}",',
'            daemon=True,',
'        )',
'        self._thread.start()',
'',
'    def _hard_reset(self, reason: str) -> None:',
'        # FYERS-R1/R2/R3: retire the dead socket, invalidate its session so',
'        # late callbacks are discarded, account the reconnect truthfully so',
'        # HealthMonitor observes it, then rebuild a genuinely fresh socket.',
'        _old = self._socket',
'        self._socket = None',
'        self._session += 1',
'        if _old is not None:',
'            _closer = getattr(_old, "close_connection", None)',
'            if callable(_closer):',
'                try:',
'                    _closer()',
'                except Exception:',
'                    pass',
'        self._thread = None',
'        self.reconnect_count += 1',
'        self.metrics.inc("fyers_reconnects")',
'        log_event(self.logger, logging.WARNING, "fyers_hard_reset",',
'                  reason=reason, session=self._session,',
'                  reconnects=self.reconnect_count)',
'        self._spawn_socket_worker()',
'',
'    async def run(self) -> None:',
'        self._loop = asyncio.get_running_loop()',
'        self._session += 1',
'        if self._thread is None:',
'            self._spawn_socket_worker()',
'        # FYERS-R1/R2 supervisor. FyersDataSocket.connect() is non-blocking,',
'        # so the worker thread returns immediately even when healthy: thread',
'        # liveness is NOT a health signal, the SDK socket object is. The SDK',
'        # also reconnects silently without invoking our on_close and stops',
'        # forever once its budget is spent. Poll that state and rebuild from',
'        # scratch so recovery is indefinite. The absence counter is debounced',
'        # well past the SDK growing reconnect_delay so an in-flight SDK',
'        # reconnect is never pre-empted.',
'        _absent_polls = 0',
'        while not self._stopped:',
'            await asyncio.sleep(1.0)',
'            if self._stopped:',
'                break',
'            if self._sdk_abandoned():',
'                self._hard_reset("sdk_reconnect_budget_exhausted")',
'                _absent_polls = 0',
'                continue',
'            if self._sdk_socket_absent():',
'                _absent_polls += 1',
'                if _absent_polls >= 90:',
'                    self._hard_reset("sdk_socket_absent_90s")',
'                    _absent_polls = 0',
'            else:',
'                _absent_polls = 0'
) -join $nl

$c1 = [regex]::Matches($raw, [regex]::Escape($A1)).Count
$c2 = [regex]::Matches($raw, [regex]::Escape($A2)).Count
Write-Host "ANCHOR_1 _connect_blocking : count=$c1 (expected 1)"
Write-Host "ANCHOR_2 FyersWsFeed.run   : count=$c2 (expected 1)"
if ($c1 -ne 1) { Fail 'E_ANCHOR1' "expected 1 match, found $c1" }
if ($c2 -ne 1) { Fail 'E_ANCHOR2' "expected 1 match, found $c2" }

Copy-Item -LiteralPath $Target -Destination $Backup -Force
if (-not (Test-Path -LiteralPath $Backup)) { Fail 'E_BACKUP' 'Backup not created.' }
Write-Host "BACKUP : $Backup" -ForegroundColor Green

$new = $raw.Replace($A1, $R1).Replace($A2, $R2)
if ($new -eq $raw) { Fail 'E_NOOP' 'Replacement produced no change.' }

$enc = New-Object System.Text.UTF8Encoding($hasBom)
[System.IO.File]::WriteAllText($Target, $new, $enc)

$out = & python -m py_compile "$Target" 2>&1
if ($LASTEXITCODE -ne 0) {
  Copy-Item -LiteralPath $Backup -Destination $Target -Force
  Fail 'E_SYNTAX' ("py_compile failed, rolled back: " + ($out -join ' '))
}

$chk = @(
  [regex]::Matches($new, [regex]::Escape('    def _hard_reset(self, reason: str) -> None:')).Count,
  [regex]::Matches($new, [regex]::Escape('    def _spawn_socket_worker(self) -> None:')).Count,
  [regex]::Matches($new, [regex]::Escape('    def _sdk_abandoned(self) -> bool:')).Count,
  [regex]::Matches($new, [regex]::Escape('    def _sdk_socket_absent(self) -> bool:')).Count,
  [regex]::Matches($new, [regex]::Escape('            on_message=_bind(self._on_message),')).Count
)
if (($chk | Where-Object { $_ -ne 1 }).Count -gt 0) {
  Copy-Item -LiteralPath $Backup -Destination $Target -Force
  Fail 'E_POSTVERIFY' ("post-patch marker counts: " + ($chk -join ','))
}

Write-Host ''
Write-Host 'RESULT : PASS' -ForegroundColor Green
Write-Host 'FIXED  : FYERS-R1 (finite SDK reconnect budget / no socket respawn)' -ForegroundColor Green
Write-Host 'FIXED  : FYERS-R2 (silent SDK reconnect never reached _on_close -> untruthful reconnect_count/health)' -ForegroundColor Green
Write-Host 'FIXED  : FYERS-R3 (inert stale-callback session guard / duplicate-socket callback bleed)' -ForegroundColor Green
Write-Host "ROLLBACK : Copy-Item -LiteralPath '$Backup' -Destination '$Target' -Force" -ForegroundColor Yellow
exit 0
