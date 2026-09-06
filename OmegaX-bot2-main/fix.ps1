Write-Host "Fixing quantum_trading_bot.py..." -ForegroundColor Yellow

$content = Get-Content 'quantum_trading_bot.py' -Raw

# Apply fixes
$fixes = @(
    @('from prometheus_client import', '#from prometheus_client import'),
    @('PROMETHEUS_AVAILABLE = True', 'PROMETHEUS_AVAILABLE = False'),
    @('import websockets', '#import websockets'),
    @('WS_AVAILABLE = True', 'WS_AVAILABLE = False'),
    @('ThreadPoolExecutor(max_workers=20)', 'ThreadPoolExecutor(max_workers=2)'),
    @('ProcessPoolExecutor(max_workers=4)', 'None  # Disabled'),
    @('deque(maxlen=1000)', 'deque(maxlen=100)'),
    @('deque(maxlen=50)', 'deque(maxlen=10)'),
    @('ENABLE_SHADOW_TRADING = True', 'ENABLE_SHADOW_TRADING = False'),
    @('ENABLE_ML_PREDICTIONS = True', 'ENABLE_ML_PREDICTIONS = False'),
    @('PORT = int(os.environ.get("PORT", 8000))', 'PORT = int(os.environ.get("PORT", 10000))')
)

foreach ($fix in $fixes) {
    $content = $content -replace [regex]::Escape($fix[0]), $fix[1]
}

Set-Content 'quantum_trading_bot.py' $content -Encoding UTF8

Write-Host "Fixed!" -ForegroundColor Green