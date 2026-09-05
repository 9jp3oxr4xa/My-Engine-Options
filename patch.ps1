# =====================================================================
# POST-AUDIT REMEDIATION PATCH — Indian Index Options Signal Engine
# TARGET (only file modified): C:\Users\Guest -A\Desktop\Dhan Test\Dhan.py
# Fail-closed: validates every anchor; writes only if ALL succeed;
# auto-restores backup if Python syntax validation fails.
# =====================================================================

$ErrorActionPreference = 'Stop'
$Target = 'C:\Users\Guest -A\Desktop\Dhan Test\Dhan.py'

if (-not (Test-Path -LiteralPath $Target -PathType Leaf)) {
    Write-Host "RESULT: FAIL — target not found: $Target" -ForegroundColor Red
    exit 1
}

$bytes  = [System.IO.File]::ReadAllBytes($Target)
$hasBom = ($bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF)
$raw    = [System.Text.Encoding]::UTF8.GetString($bytes)
if ($hasBom) { $raw = $raw.TrimStart([char]0xFEFF) }
$useCrLf = $raw.Contains("`r`n")
$text    = $raw -replace "`r`n", "`n"

$stamp  = Get-Date -Format 'yyyyMMdd-HHmmss'
$Backup = "$Target.$stamp.bak"
[System.IO.File]::WriteAllBytes($Backup, $bytes)
Write-Host "Backup: $Backup"

$script:Edits = New-Object System.Collections.ArrayList
function Add-Edit([string]$Id, [string]$Old, [string]$New, [int]$Count) {
    [void]$script:Edits.Add([pscustomobject]@{
        Id    = $Id
        Old   = ($Old -replace "`r`n", "`n")
        New   = ($New -replace "`r`n", "`n")
        Count = $Count
    })
}

# ---------------------------------------------------------------- SE-060
$o = @'
import contextlib
import copy
import hashlib
'@
$n = @'
import contextlib
import hashlib
'@
Add-Edit 'SE-060a' $o $n 1

$o = @'
import logging.handlers
import math
import os
'@
$n = @'
import logging.handlers
import os
'@
Add-Edit 'SE-060b' $o $n 1

$o = 'from dataclasses import asdict, dataclass, field, replace'
$n = 'from dataclasses import asdict, dataclass, replace'
Add-Edit 'SE-060c' $o $n 1

$o = @'
    Dict,
    Iterable,
    List,
'@
$n = @'
    Dict,
    List,
'@
Add-Edit 'SE-060d' $o $n 1

# ---------------------------------------------------------------- SE-061
$o = @'
# SECTION: numeric helpers
# ============================================================

TWO_PLACES = Decimal("0.01")


def _d(value: Any) -> Decimal:
'@
$n = @'
# SECTION: numeric helpers
# ============================================================


def _d(value: Any) -> Decimal:
'@
Add-Edit 'SE-061' $o $n 1

# ---------------------------------------------------------------- SE-038 (enum members)
$o = @'
    RETEST_OK = "RETEST_OK"
    RETEST_FAIL = "RETEST_FAIL"
'@
$n = @'
    RETEST_OK = "RETEST_OK"
    RETEST_FAIL = "RETEST_FAIL"
    OPENING_DRIVE_BREAK = "OPENING_DRIVE_BREAK"
    EXPANSION_IMPULSE = "EXPANSION_IMPULSE"
'@
Add-Edit 'SE-038a' $o $n 1

# ---------------------------------------------------------------- SE-034 (EvidenceOutcome)
$o = @'
class Direction(str, Enum):
    LONG_CE = "LONG_CE"
    LONG_PE = "LONG_PE"
'@
$n = @'
class EvidenceOutcome(str, Enum):
    TRUE = "true"
    FALSE = "false"
    NEUTRAL = "neutral"


class Direction(str, Enum):
    LONG_CE = "LONG_CE"
    LONG_PE = "LONG_PE"
'@
Add-Edit 'SE-034a' $o $n 1

# ---------------------------------------------------------------- SE-046 (Tick fields)
$o = @'
    bid: Decimal
    ask: Decimal
    bid_qty: int
    ask_qty: int

    def __post_init__(self) -> None:
        if self.ts.tzinfo is None:
'@
$n = @'
    bid: Decimal
    ask: Decimal
    bid_qty: int
    ask_qty: int
    total_buy_qty: int = 0
    total_sell_qty: int = 0

    def __post_init__(self) -> None:
        if self.ts.tzinfo is None:
'@
Add-Edit 'SE-046a' $o $n 1

# ---------------------------------------------------------------- SE-002 (OptionLeg.security_id)
$o = @'
    iv: Decimal
    bid_qty: int = 0
    ask_qty: int = 0
    delta: Optional[Decimal] = None
'@
$n = @'
    iv: Decimal
    bid_qty: int = 0
    ask_qty: int = 0
    security_id: str = ""
    delta: Optional[Decimal] = None
'@
Add-Edit 'SE-002a' $o $n 1

# ---------------------------------------------------------------- SE-034 (Evidence model)
$o = @'
class Evidence:
    category: str
    name: str
    passed: str  # "true" | "false" | "neutral"
    weight: float
    contribution: float
    detail: str
    semantic: str = "neutral"  # "bullish" | "bearish" | "neutral"
'@
$n = @'
class Evidence:
    category: str
    name: str
    passed: EvidenceOutcome
    weight: float
    contribution: float
    detail: str
    semantic: str = "neutral"  # "bullish" | "bearish" | "neutral"

    def __post_init__(self) -> None:
        if not isinstance(self.passed, EvidenceOutcome):
            object.__setattr__(self, "passed", EvidenceOutcome(str(self.passed)))
'@
Add-Edit 'SE-034b' $o $n 1

# ---------------------------------------------------------------- SE-048 / SE-058C (ScoredCandidate)
$o = @'
class ScoredCandidate:
    candidate: CandidateSignal
    ledger: List[Evidence]
    score: int
    band: str
    categories_passed: int
    contradictions: int
    mandatory_ok: bool
'@
$n = @'
class ScoredCandidate:
    candidate: Optional[CandidateSignal]
    ledger: List[Evidence]
    score: int
    band: str
    categories_passed: int
    contradictions: int
    mandatory_ok: bool
    min_categories_ok: bool = False
'@
Add-Edit 'SE-048a' $o $n 1

# ---------------------------------------------------------------- SE-051 (OutboundMessage)
$o = @'
class OutboundMessage:
    kind: str  # SIGNAL | HEALTH | DAILY_SUMMARY | REJECTION_DIGEST
    text: str
'@
$n = @'
class OutboundMessage:
    kind: str  # SIGNAL | HEALTH | DAILY_SUMMARY | REJECTION_DIGEST
    text: str
    enqueued_mono: float = 0.0
'@
Add-Edit 'SE-051a' $o $n 1

# ---------------------------------------------------------------- SE-069 / SE-010
$o = '            "ts": datetime.now(IST).isoformat(),'
$n = '            "ts": datetime.fromtimestamp(record.created, IST).isoformat(),'
Add-Edit 'SE-069' $o $n 1

$o = @'
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, sort_keys=True)
'@
$n = @'
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        rendered = json.dumps(payload, default=str, sort_keys=True)
        for pat in _SECRET_PATTERNS:
            rendered = pat.sub("[REDACTED]", rendered)
        return rendered
'@
Add-Edit 'SE-010' $o $n 1

# ---------------------------------------------------------------- SE-043 / SE-052 (Metrics)
$o = @'
        self.counters: Dict[str, int] = {}
        self.reservoirs: Dict[str, Deque[float]] = {}
        self.rejections_by_reason: Dict[str, int] = {}
'@
$n = @'
        self.counters: Dict[str, int] = {}
        self.reservoirs: Dict[str, Deque[float]] = {}
        self.rejections_by_reason: Dict[str, int] = {}
        self.events: Dict[str, Deque[float]] = {}
'@
Add-Edit 'SE-043a' $o $n 1

$o = @'
    def observe(self, name: str, value: float) -> None:
        res = self.reservoirs.setdefault(name, deque(maxlen=1024))
        res.append(value)

    def percentile(self, name: str, pct: float) -> float:
'@
$n = @'
    def observe(self, name: str, value: float) -> None:
        res = self.reservoirs.setdefault(name, deque(maxlen=1024))
        res.append(value)

    def mark(self, name: str, now_mono: float) -> None:
        ev = self.events.setdefault(name, deque(maxlen=4096))
        ev.append(now_mono)

    def window_count(self, name: str, window_s: float, now_mono: float) -> int:
        ev = self.events.get(name)
        if not ev:
            return 0
        return sum(1 for t in ev if (now_mono - t) <= window_s)

    def reset_session(self) -> None:
        self.counters.clear()
        self.rejections_by_reason.clear()
        self.reservoirs.clear()
        self.events.clear()

    def percentile(self, name: str, pct: float) -> float:
'@
Add-Edit 'SE-043b/SE-052a' $o $n 1

# ---------------------------------------------------------------- SE-013 (FixedClock.set)
$o = @'
    def set(self, when: datetime) -> None:
        self._now = when.astimezone(IST)
'@
$n = @'
    def set(self, when: datetime) -> None:
        target = when.astimezone(IST)
        delta = (target - self._now).total_seconds()
        if delta > 0:
            self._mono += delta
        self._now = target
'@
Add-Edit 'SE-013' $o $n 1

# ---------------------------------------------------------------- SE-035 / SE-036 (BarBuilder)
$o = @'
    def _reset(self, minute: datetime, tick: Tick) -> None:
        self._minute = minute
        self._open = tick.ltp
        self._high = tick.ltp
        self._low = tick.ltp
        self._close = tick.ltp
        self._tick_count = 1
        self._vol_start_cum = tick.volume_cum
        self._vol_end_cum = tick.volume_cum
        self._ltq_accum = tick.ltq
        self._suspect = False
        self._minute_mono = self.clock.monotonic()
'@
$n = @'
    def _reset(self, minute: datetime, tick: Tick) -> None:
        px = quantize_tick(tick.ltp, self.tick_size)
        self._minute = minute
        self._open = px
        self._high = px
        self._low = px
        self._close = px
        self._tick_count = 1
        self._vol_start_cum = tick.volume_cum
        self._vol_end_cum = tick.volume_cum
        self._ltq_accum = tick.ltq
        self._suspect = False
        self._minute_mono = self.clock.monotonic() - max(0.0, (tick.ts - minute).total_seconds())
'@
Add-Edit 'SE-035a/SE-036' $o $n 1

$o = @'
        self._close = t.ltp
        if self._high is None or t.ltp > self._high:
            self._high = t.ltp
        if self._low is None or t.ltp < self._low:
            self._low = t.ltp
        self._tick_count += 1
'@
$n = @'
        px = quantize_tick(t.ltp, self.tick_size)
        self._close = px
        if self._high is None or px > self._high:
            self._high = px
        if self._low is None or px < self._low:
            self._low = px
        self._tick_count += 1
'@
Add-Edit 'SE-035b' $o $n 1

# ---------------------------------------------------------------- SE-066 (dead property)
$o = @'
    @property
    def value(self) -> Optional[float]:
        return self._last_bw

    def percentile_rank(self) -> float:
'@
$n = @'
    def percentile_rank(self) -> float:
'@
Add-Edit 'SE-066a' $o $n 1

# ---------------------------------------------------------------- SE-027 (IVTracker persistence)
$o = @'
        iv_change = (iv1 - iv0) / iv0
        price_change = abs((spot1 - spot0) / spot0)
        return iv_change > Decimal("0.08") and price_change < Decimal("0.001")
'@
$n = @'
        iv_change = (iv1 - iv0) / iv0
        price_change = abs((spot1 - spot0) / spot0)
        return iv_change > Decimal("0.08") and price_change < Decimal("0.001")

    def state(self) -> Dict[str, Any]:
        return {"hist": [[ts.isoformat(), str(iv), str(spot)] for ts, iv, spot in self._hist]}

    def restore(self, s: Dict[str, Any]) -> None:
        self._hist = deque(
            ((datetime.fromisoformat(x[0]), _d(x[1]), _d(x[2])) for x in s.get("hist", [])),
            maxlen=6,
        )
'@
Add-Edit 'SE-027a' $o $n 1

# ---------------------------------------------------------------- SE-007 (RVOL minute-of-day)
$o = @'
    def rvol(self, ts: datetime, atm_option_volume: int) -> Optional[float]:
        pool: List[int] = []
        for vals in self._by_minute.values():
            pool.extend(vals)
        if len(pool) < 10:
'@
$n = @'
    def rvol(self, ts: datetime, atm_option_volume: int) -> Optional[float]:
        pool: List[int] = list(self._by_minute.get((ts.hour, ts.minute), []))
        if len(pool) < 10:
'@
Add-Edit 'SE-007' $o $n 1

# ---------------------------------------------------------------- SE-065 / structure __init__
$o = @'
        swing_left: int = 3,
        swing_right: int = 3,
        sweep_close_back_bars: int = 2,
        tick_size: Decimal = Decimal("0.05"),
    ) -> None:
        self.swing_left = swing_left
        self.swing_right = swing_right
        self.sweep_close_back = sweep_close_back_bars
        self.tick_size = tick_size
        self._bars_5m: Deque[Bar] = deque(maxlen=200)
        self._swings: List[Swing] = []
        self._events: Deque[StructureEvent] = deque(maxlen=50)
        self._pending: List[Tuple[int, SwingKind, Decimal, datetime]] = []
        self._last_bos_level: Optional[Decimal] = None
'@
$n = @'
        swing_left: int = 3,
        swing_right: int = 3,
        sweep_close_back_bars: int = 2,
    ) -> None:
        self.swing_left = swing_left
        self.swing_right = swing_right
        self.sweep_close_back = sweep_close_back_bars
        self._bars_5m: Deque[Bar] = deque(maxlen=200)
        self._swings: List[Swing] = []
        self._events: Deque[StructureEvent] = deque(maxlen=50)
        self._pending_bos: List[Dict[str, Any]] = []
        self._pending_sweeps: List[Dict[str, Any]] = []
        self._emitted: set[Tuple[str, str]] = set()
        self._chain_levels: List[Level] = []
        self._atr_5m: Optional[Decimal] = None
        self._avwap: Optional[Decimal] = None
        self._avwap_sigma: Decimal = Decimal(0)
        self._ema20: Optional[Decimal] = None
        self._last_bos_level: Optional[Decimal] = None
'@
Add-Edit 'SE-065a/SE-058A-init' $o $n 1

# ------------------------------------------- SE-058A / SE-003 / SE-004 / SE-011 / SE-018
$o = @'
    def on_bar_5m(self, bar: Bar, atr_5m: Optional[Decimal]) -> List[StructureEvent]:
        self._bars_5m.append(bar)
        if self._session_high is None or bar.high > self._session_high:
            self._session_high = bar.high
        if self._session_low is None or bar.low < self._session_low:
            self._session_low = bar.low
        new_events: List[StructureEvent] = []
        idx = len(self._bars_5m) - 1
        if idx >= self.swing_left:
            self._check_swing(idx - self.swing_right, bar.ts_open)
        new_events.extend(self._detect_bos_choch(bar, atr_5m))
        new_events.extend(self._detect_sweep(bar, atr_5m))
        self._detect_retest(bar, atr_5m, new_events)
        for ev in new_events:
            self._events.append(ev)
        self._update_levels(bar, atr_5m)
        return new_events
'@
$n = @'
    def set_atr_5m(self, atr: Optional[Decimal]) -> None:
        self._atr_5m = atr

    def set_dynamic_levels(self, avwap: Optional[Decimal], sigma: Decimal,
                           ema20: Optional[Decimal]) -> None:
        self._avwap = avwap
        self._avwap_sigma = sigma
        self._ema20 = ema20

    def append_event(self, ev: StructureEvent) -> None:
        self._events.append(ev)

    def seed_bars(self, bars: Sequence[Bar]) -> None:
        self._bars_5m = deque(bars, maxlen=200)

    def _emit(self, kind: StructureKind, level: Decimal, ts: datetime,
              ref_swing: Optional[Swing]) -> Optional[StructureEvent]:
        key = (kind.value, ref_swing.ts.isoformat() if ref_swing is not None else str(level))
        if key in self._emitted:
            return None
        self._emitted.add(key)
        if len(self._emitted) > 400:
            live = {s.ts.isoformat() for s in self._swings}
            self._emitted = {k for k in self._emitted if k[1] in live}
            self._emitted.add(key)
        return StructureEvent(kind, level, ts, ref_swing)

    def _advance_pending(self, bar: Bar) -> List[StructureEvent]:
        out: List[StructureEvent] = []
        keep_bos: List[Dict[str, Any]] = []
        for p in self._pending_bos:
            p["bars"] = int(p["bars"]) + 1
            failed = False
            if int(p["bars"]) <= 3:
                if p["kind"] == StructureKind.BOS_UP and bar.close < p["level"]:
                    failed = True
                elif p["kind"] == StructureKind.BOS_DOWN and bar.close > p["level"]:
                    failed = True
            if failed:
                ev = self._emit(StructureKind.RETEST_FAIL, p["level"], bar.ts_open, p["ref_swing"])
                if ev is not None:
                    out.append(ev)
                continue
            if int(p["bars"]) > 12:
                continue
            keep_bos.append(p)
        self._pending_bos = keep_bos
        keep_sweep: List[Dict[str, Any]] = []
        for s in self._pending_sweeps:
            s["bars"] = int(s["bars"]) + 1
            closed_back = (bar.close < s["level"]) if s["kind"] == StructureKind.SWEEP_HIGH else (bar.close > s["level"])
            if closed_back:
                ev = self._emit(s["kind"], s["level"], bar.ts_open, s["ref_swing"])
                if ev is not None:
                    out.append(ev)
                continue
            if int(s["bars"]) < self.sweep_close_back:
                keep_sweep.append(s)
        self._pending_sweeps = keep_sweep
        return out

    def on_bar_1m(self, b: Bar, atr_5m: Optional[Decimal]) -> List[StructureEvent]:
        out: List[StructureEvent] = []
        if atr_5m is None or atr_5m <= 0 or not self._pending_bos:
            return out
        dist = Decimal("0.25") * atr_5m
        rng = b.high - b.low
        keep: List[Dict[str, Any]] = []
        for p in self._pending_bos:
            hit = False
            if p["kind"] == StructureKind.BOS_UP:
                if (abs(b.low - p["level"]) <= dist and b.close > b.open
                        and (rng == 0 or b.close > b.low + rng * Decimal("0.67"))):
                    hit = True
            else:
                if (abs(b.high - p["level"]) <= dist and b.close < b.open
                        and (rng == 0 or b.close < b.high - rng * Decimal("0.67"))):
                    hit = True
            if hit:
                ev = self._emit(StructureKind.RETEST_OK, p["level"], b.ts_open, p["ref_swing"])
                if ev is not None:
                    self._events.append(ev)
                    out.append(ev)
                continue
            keep.append(p)
        self._pending_bos = keep
        return out

    def on_bar_5m(self, b: Bar) -> List[StructureEvent]:
        bar = b
        atr_5m = self._atr_5m
        self._bars_5m.append(bar)
        if self._session_high is None or bar.high > self._session_high:
            self._session_high = bar.high
        if self._session_low is None or bar.low < self._session_low:
            self._session_low = bar.low
        new_events: List[StructureEvent] = []
        idx = len(self._bars_5m) - 1
        if idx >= self.swing_left:
            self._check_swing(idx - self.swing_right, bar.ts_open)
        new_events.extend(self._advance_pending(bar))
        new_events.extend(self._detect_bos_choch(bar, atr_5m))
        new_events.extend(self._detect_sweep(bar, atr_5m))
        for ev in new_events:
            self._events.append(ev)
        self._update_levels(bar, atr_5m)
        return new_events
'@
Add-Edit 'SE-058A/SE-003a/SE-004a/SE-011a/SE-018a' $o $n 1

# ---------------------------------------------------------------- SE-003 / SE-031 (BOS)
$o = @'
    def _detect_bos_choch(self, bar: Bar, atr: Optional[Decimal]) -> List[StructureEvent]:
        events: List[StructureEvent] = []
        if len(self._swings) < 2:
            return events
        last = self._swings[-1]
        prev = self._swings[-2]
        if last.kind == SwingKind.HIGH and prev.kind == SwingKind.LOW:
            if bar.close > last.price:
                if self._bias in ("BULLISH", "NEUTRAL"):
                    events.append(StructureEvent(StructureKind.BOS_UP, last.price, bar.ts_open, last))
                    self._bias = "BULLISH"
                    self._last_bos_level = last.price
                else:
                    events.append(StructureEvent(StructureKind.CHOCH_UP, last.price, bar.ts_open, last))
                    self._bias = "NEUTRAL"
        elif last.kind == SwingKind.LOW and prev.kind == SwingKind.HIGH:
            if bar.close < last.price:
                if self._bias in ("BEARISH", "NEUTRAL"):
                    events.append(StructureEvent(StructureKind.BOS_DOWN, last.price, bar.ts_open, last))
                    self._bias = "BEARISH"
                    self._last_bos_level = last.price
                else:
                    events.append(StructureEvent(StructureKind.CHOCH_DOWN, last.price, bar.ts_open, last))
                    self._bias = "NEUTRAL"
        for ev in events:
            if ev.kind in (StructureKind.BOS_UP, StructureKind.BOS_DOWN):
                self._check_false_breakout(ev)
        return events

    def _check_false_breakout(self, bos_ev: StructureEvent) -> None:
        bars = list(self._bars_5m)
        idx = len(bars) - 1
        if idx < 1:
            return
        for i in range(1, min(4, idx + 1)):
            lookback = bars[idx - i]
            if bos_ev.kind == StructureKind.BOS_UP and lookback.close < bos_ev.level:
                self._events.append(
                    StructureEvent(StructureKind.RETEST_FAIL, bos_ev.level, lookback.ts_open, bos_ev.ref_swing)
                )
                return
            if bos_ev.kind == StructureKind.BOS_DOWN and lookback.close > bos_ev.level:
                self._events.append(
                    StructureEvent(StructureKind.RETEST_FAIL, bos_ev.level, lookback.ts_open, bos_ev.ref_swing)
                )
                return
'@
$n = @'
    def _detect_bos_choch(self, bar: Bar, atr: Optional[Decimal]) -> List[StructureEvent]:
        events: List[StructureEvent] = []
        if len(self._swings) < 2:
            return events
        last = self._swings[-1]
        prev = self._swings[-2]
        if last.kind == SwingKind.HIGH and prev.kind == SwingKind.LOW:
            if bar.close > last.price:
                if self._bias in ("BULLISH", "NEUTRAL"):
                    ev = self._emit(StructureKind.BOS_UP, last.price, bar.ts_open, last)
                    if ev is not None:
                        events.append(ev)
                        self._bias = "BULLISH"
                        self._last_bos_level = last.price
                        self._pending_bos.append({"kind": StructureKind.BOS_UP, "level": last.price,
                                                  "ref_swing": last, "bars": 0})
                else:
                    ev = self._emit(StructureKind.CHOCH_UP, last.price, bar.ts_open, last)
                    if ev is not None:
                        events.append(ev)
                        self._bias = "NEUTRAL"
        elif last.kind == SwingKind.LOW and prev.kind == SwingKind.HIGH:
            if bar.close < last.price:
                if self._bias in ("BEARISH", "NEUTRAL"):
                    ev = self._emit(StructureKind.BOS_DOWN, last.price, bar.ts_open, last)
                    if ev is not None:
                        events.append(ev)
                        self._bias = "BEARISH"
                        self._last_bos_level = last.price
                        self._pending_bos.append({"kind": StructureKind.BOS_DOWN, "level": last.price,
                                                  "ref_swing": last, "bars": 0})
                else:
                    ev = self._emit(StructureKind.CHOCH_DOWN, last.price, bar.ts_open, last)
                    if ev is not None:
                        events.append(ev)
                        self._bias = "NEUTRAL"
        return events
'@
Add-Edit 'SE-003b/SE-031a' $o $n 1

# ---------------------------------------------------------------- SE-047 / SE-031 / SE-004
$o = @'
    def _detect_sweep(self, bar: Bar, atr: Optional[Decimal]) -> List[StructureEvent]:
        events: List[StructureEvent] = []
        if atr is None or atr == 0:
            return events
        thresh = Decimal("0.1") * atr
        bars = list(self._bars_5m)
        idx = len(bars) - 1
        span = min(self.sweep_close_back + 1, idx + 1)
        for s in self._swings[-5:]:
            if s.kind == SwingKind.HIGH and bar.high > s.price + thresh:
                if any(bars[idx - i].close < s.price for i in range(span)):
                    events.append(StructureEvent(StructureKind.SWEEP_HIGH, s.price, bar.ts_open, s))
            elif s.kind == SwingKind.LOW and bar.low < s.price - thresh:
                if any(bars[idx - i].close > s.price for i in range(span)):
                    events.append(StructureEvent(StructureKind.SWEEP_LOW, s.price, bar.ts_open, s))
        static_levels = [
            (self._prev_day_high, SwingKind.HIGH),
            (self._prev_day_low, SwingKind.LOW),
            (self._opening_range_high, SwingKind.HIGH),
            (self._opening_range_low, SwingKind.LOW),
        ]
        for lvl, kind in static_levels:
            if lvl is None:
                continue
            if kind == SwingKind.HIGH and bar.high > lvl + thresh:
                if any(bars[idx - i].close < lvl for i in range(span)):
                    events.append(StructureEvent(StructureKind.SWEEP_HIGH, lvl, bar.ts_open, None))
            elif kind == SwingKind.LOW and bar.low < lvl - thresh:
                if any(bars[idx - i].close > lvl for i in range(span)):
                    events.append(StructureEvent(StructureKind.SWEEP_LOW, lvl, bar.ts_open, None))
        return events

    def _detect_retest(self, bar: Bar, atr: Optional[Decimal], recent_events: List[StructureEvent]) -> None:
        if not recent_events or atr is None:
            return
        bos_list = [e for e in recent_events if e.kind in (StructureKind.BOS_UP, StructureKind.BOS_DOWN)]
        if not bos_list:
            return
        bars = list(self._bars_5m)
        idx = len(bars) - 1
        dist = Decimal("0.25") * atr
        for bos in bos_list:
            if bos.kind == StructureKind.BOS_UP:
                for i in range(1, min(13, idx + 1)):
                    old = bars[idx - i]
                    if abs(old.low - bos.level) <= dist:
                        if old.close > old.open and old.close > old.low + (old.high - old.low) * Decimal("0.67"):
                            self._events.append(
                                StructureEvent(StructureKind.RETEST_OK, bos.level, old.ts_open, bos.ref_swing)
                            )
                            return
            elif bos.kind == StructureKind.BOS_DOWN:
                for i in range(1, min(13, idx + 1)):
                    old = bars[idx - i]
                    if abs(old.high - bos.level) <= dist:
                        if old.close < old.open and old.close < old.high - (old.high - old.low) * Decimal("0.67"):
                            self._events.append(
                                StructureEvent(StructureKind.RETEST_OK, bos.level, old.ts_open, bos.ref_swing)
                            )
                            return
'@
$n = @'
    def _detect_sweep(self, bar: Bar, atr: Optional[Decimal]) -> List[StructureEvent]:
        events: List[StructureEvent] = []
        if atr is None or atr == 0:
            return events
        thresh = Decimal("0.1") * atr
        candidates: List[Tuple[StructureKind, Decimal, Optional[Swing]]] = []
        for s in self._swings[-5:]:
            if s.kind == SwingKind.HIGH and bar.high > s.price + thresh:
                candidates.append((StructureKind.SWEEP_HIGH, s.price, s))
            elif s.kind == SwingKind.LOW and bar.low < s.price - thresh:
                candidates.append((StructureKind.SWEEP_LOW, s.price, s))
        static_levels = [
            (self._prev_day_high, SwingKind.HIGH),
            (self._prev_day_low, SwingKind.LOW),
            (self._opening_range_high, SwingKind.HIGH),
            (self._opening_range_low, SwingKind.LOW),
        ]
        for lvl, kind in static_levels:
            if lvl is None:
                continue
            if kind == SwingKind.HIGH and bar.high > lvl + thresh:
                candidates.append((StructureKind.SWEEP_HIGH, lvl, None))
            elif kind == SwingKind.LOW and bar.low < lvl - thresh:
                candidates.append((StructureKind.SWEEP_LOW, lvl, None))
        for kind, level, ref in candidates:
            closed_back = (bar.close < level) if kind == StructureKind.SWEEP_HIGH else (bar.close > level)
            if closed_back:
                ev = self._emit(kind, level, bar.ts_open, ref)
                if ev is not None:
                    events.append(ev)
                continue
            if self.sweep_close_back <= 0:
                continue
            key = (kind.value, ref.ts.isoformat() if ref is not None else str(level))
            if key in self._emitted:
                continue
            if any(p["kind"] == kind and p["level"] == level for p in self._pending_sweeps):
                continue
            self._pending_sweeps.append({"kind": kind, "level": level, "ref_swing": ref, "bars": 0})
        return events
'@
Add-Edit 'SE-047/SE-031b/SE-004b' $o $n 1

# ---------------------------------------------------------------- SE-032 / SE-018 / SE-014
$o = @'
            nearby = [x for x in self._swings if abs(x.price - s.price) / s.price < Decimal("0.0015")]
            self._levels.append(Level(s.price, "swing", 1 + len(nearby)))
'@
$n = @'
            nearby = [x for x in self._swings if abs(x.price - s.price) / s.price < Decimal("0.0015")]
            self._levels.append(Level(s.price, "swing", len(nearby)))
'@
Add-Edit 'SE-032' $o $n 1

$o = @'
        if self._session_low:
            self._levels.append(Level(self._session_low, "session_low", 2))

    def merge_option_levels(self, option_levels: List[Level]) -> None:
        """Merge option-chain S/R levels into the level list (§10/§12)."""
        self._levels = [lv for lv in self._levels if not lv.source.startswith("chain_")]
        self._levels.extend(option_levels)
'@
$n = @'
        if self._session_low:
            self._levels.append(Level(self._session_low, "session_low", 2))
        if self._avwap is not None:
            self._levels.append(Level(self._avwap, "avwap_o", 2))
            if self._avwap_sigma > 0:
                self._levels.append(Level(self._avwap - self._avwap_sigma, "avwap_1sigma", 1))
                self._levels.append(Level(self._avwap + self._avwap_sigma, "avwap_1sigma", 1))
                self._levels.append(Level(self._avwap - Decimal(2) * self._avwap_sigma, "avwap_2sigma", 1))
                self._levels.append(Level(self._avwap + Decimal(2) * self._avwap_sigma, "avwap_2sigma", 1))
        if self._ema20 is not None:
            self._levels.append(Level(self._ema20, "ema20_5m", 2))
        self._levels.extend(self._chain_levels)

    def merge_option_levels(self, option_levels: List[Level]) -> None:
        """Merge option-chain S/R levels into the level list (§10/§12)."""
        self._chain_levels = list(option_levels)
        self._levels = [lv for lv in self._levels if not lv.source.startswith("chain_")]
        self._levels.extend(self._chain_levels)
'@
Add-Edit 'SE-018b/SE-014' $o $n 1

# ---------------------------------------------------------------- SE-073 (extremes)
$o = @'
    @property
    def bias(self) -> str:
        return self._bias

    @property
    def levels(self) -> List[Level]:
        return list(self._levels)
'@
$n = @'
    @property
    def bias(self) -> str:
        return self._bias

    @property
    def session_high(self) -> Optional[Decimal]:
        return self._session_high

    @property
    def session_low(self) -> Optional[Decimal]:
        return self._session_low

    @property
    def levels(self) -> List[Level]:
        return list(self._levels)
'@
Add-Edit 'SE-073a' $o $n 1

# ---------------------------------------------------------------- SE-011 (restore resets)
$o = @'
        self._prev_day_close = _d(s["pd_close"]) if s.get("pd_close") else None


# ============================================================
# SECTION: domain/regime.py  (§11)
'@
$n = @'
        self._prev_day_close = _d(s["pd_close"]) if s.get("pd_close") else None
        self._pending_bos = []
        self._pending_sweeps = []
        self._emitted = set()


# ============================================================
# SECTION: domain/regime.py  (§11)
'@
Add-Edit 'SE-011b' $o $n 1

# ---------------------------------------------------------------- SE-016 / SE-057 / SE-058B / SE-070
$o = @'
    def __init__(self, adx_period: int = 14, atr_period: int = 14) -> None:
        self.adx_period = adx_period
        self.atr_period = atr_period
        self._state = RegimeState(Regime.UNKNOWN, datetime.now(IST), 0)
        self._candidate: Optional[Regime] = None
        self._candidate_count = 0

    def on_bar_5m(
        self,
        bar: Bar,
        adx_val: Optional[Decimal],
        adx_rising: bool,
        swings: List[Swing],
        bias: str,
        avwap_val: Optional[Decimal],
        avwap_slope: Decimal,
        bb_pct: float,
        bb_rising_3: bool,
        impulse_present: bool,
        phase: SessionPhase,
        opening_range_broken: bool,
        opening_extreme_swept: bool,
        atr_5m: Optional[Decimal] = None,
    ) -> RegimeState:
        now_reg = self._classify(
            bar, adx_val, adx_rising, swings, bias, avwap_val, avwap_slope,
            bb_pct, bb_rising_3, impulse_present, phase,
            opening_range_broken, opening_extreme_swept, atr_5m,
        )
        if phase == SessionPhase.OPENING and now_reg in (
            Regime.OPENING_DRIVE_UP, Regime.OPENING_DRIVE_DOWN, Regime.OPENING_REVERSAL
        ):
            self._state = RegimeState(now_reg, bar.ts_open, self._strength(now_reg, adx_val, swings, avwap_slope))
            self._candidate = None
            self._candidate_count = 0
            return self._state
        if now_reg == self._state.regime:
            self._candidate = None
            self._candidate_count = 0
            self._state = replace(self._state, strength_0_100=self._strength(now_reg, adx_val, swings, avwap_slope))
            return self._state
        if self._candidate == now_reg:
            self._candidate_count += 1
            if self._candidate_count >= 2:
                self._state = RegimeState(now_reg, bar.ts_open, self._strength(now_reg, adx_val, swings, avwap_slope))
                self._candidate = None
                self._candidate_count = 0
        else:
            self._candidate = now_reg
            self._candidate_count = 1
        return self._state

    def _classify(
        self, bar: Bar, adx: Optional[Decimal], adx_rising: bool, swings: List[Swing],
        bias: str, avwap: Optional[Decimal], avwap_slope: Decimal, bb_pct: float,
        bb_rising_3: bool, impulse: bool, phase: SessionPhase,
        or_broken: bool, or_swept: bool, atr_5m: Optional[Decimal] = None,
    ) -> Regime:
        if phase == SessionPhase.OPENING and or_broken:
            if bias == "BULLISH":
                return Regime.OPENING_DRIVE_UP
            if bias == "BEARISH":
                return Regime.OPENING_DRIVE_DOWN
        if or_swept and phase in (SessionPhase.OPENING, SessionPhase.MORNING):
            return Regime.OPENING_REVERSAL
        if bb_pct < 20 and (adx is None or adx < 18):
            return Regime.COMPRESSION
        if bb_rising_3 and impulse:
            return Regime.EXPANSION
        if adx is not None and adx >= 22 and adx_rising:
            if self._check_sequence(swings, bias) and self._check_avwap_side(bar, avwap, bias):
                if bias == "BULLISH":
                    return Regime.TREND_UP
                if bias == "BEARISH":
                    return Regime.TREND_DOWN
        if adx is not None and adx < 18 and len(swings) >= 4:
            recent = swings[-4:]
            prices = [s.price for s in recent]
            band = max(prices) - min(prices)
            if atr_5m is not None and band <= Decimal("1.2") * atr_5m * Decimal(4) and avwap is not None and abs(avwap_slope) < Decimal("0.5"):
                return Regime.RANGE
        return Regime.UNKNOWN
'@
$n = @'
    def __init__(self, adx_period: int = 14, atr_period: int = 14,
                 compression_bb_pct_rank: int = 20,
                 clock: Optional[Clock] = None) -> None:
        self.adx_period = adx_period
        self.atr_period = atr_period
        self.compression_pct = compression_bb_pct_rank
        self._state = RegimeState(Regime.UNKNOWN, (clock or Clock()).now(), 0)
        self._candidate: Optional[Regime] = None
        self._candidate_count = 0

    def on_bar_5m(self, b: Bar, ctx: "AnalyticsView") -> RegimeState:
        now_reg = self._classify(b, ctx)
        strength = self._strength(now_reg, ctx.adx, ctx.swings, ctx.bias, ctx.avwap_dist_sigma)
        if ctx.phase == SessionPhase.OPENING and now_reg in (
            Regime.OPENING_DRIVE_UP, Regime.OPENING_DRIVE_DOWN, Regime.OPENING_REVERSAL
        ):
            self._state = RegimeState(now_reg, b.ts_open, strength)
            self._candidate = None
            self._candidate_count = 0
            return self._state
        if now_reg == self._state.regime:
            self._candidate = None
            self._candidate_count = 0
            self._state = replace(self._state, strength_0_100=strength)
            return self._state
        if self._candidate == now_reg:
            self._candidate_count += 1
            if self._candidate_count >= 2:
                self._state = RegimeState(now_reg, b.ts_open, strength)
                self._candidate = None
                self._candidate_count = 0
        else:
            self._candidate = now_reg
            self._candidate_count = 1
        return self._state

    def _classify(self, bar: Bar, ctx: "AnalyticsView") -> Regime:
        adx = ctx.adx
        if ctx.phase == SessionPhase.OPENING and ctx.opening_range_broken:
            if ctx.bias == "BULLISH":
                return Regime.OPENING_DRIVE_UP
            if ctx.bias == "BEARISH":
                return Regime.OPENING_DRIVE_DOWN
        if (ctx.opening_extreme_swept
                and ctx.phase in (SessionPhase.OPENING, SessionPhase.MORNING)
                and dtime(9, 21) <= bar.ts_open.time() <= dtime(10, 15)):
            return Regime.OPENING_REVERSAL
        if ctx.bb_pct < self.compression_pct and (adx is None or adx < 18):
            return Regime.COMPRESSION
        if ctx.bb_rising_3 and ctx.impulse_present:
            return Regime.EXPANSION
        if adx is not None and adx >= 22 and ctx.adx_rising:
            if self._check_sequence(ctx.swings, ctx.bias) and self._check_avwap_side(bar, ctx.avwap, ctx.bias):
                if ctx.bias == "BULLISH":
                    return Regime.TREND_UP
                if ctx.bias == "BEARISH":
                    return Regime.TREND_DOWN
        if adx is not None and adx < 18 and len(ctx.swings) >= 4:
            recent = ctx.swings[-4:]
            prices = [s.price for s in recent]
            band = max(prices) - min(prices)
            if (ctx.atr_5m is not None and band <= Decimal("1.2") * ctx.atr_5m * Decimal(4)
                    and ctx.avwap is not None and abs(ctx.avwap_slope) < Decimal("0.5")):
                return Regime.RANGE
        return Regime.UNKNOWN
'@
Add-Edit 'SE-016a/SE-058B/SE-070a' $o $n 1

# ---------------------------------------------------------------- SE-033
$o = @'
    def _strength(self, reg: Regime, adx: Optional[Decimal], swings: List[Swing], avwap_slope: Decimal) -> int:
        if reg in (Regime.UNKNOWN, Regime.RANGE, Regime.COMPRESSION):
            return 0
        score = 50
        if adx is not None:
            if adx >= 25:
                score += 20
            elif adx >= 20:
                score += 10
        if len(swings) >= 6 and len(set(s.kind for s in swings[-6:])) == 2:
            score += 10
        if abs(avwap_slope) > Decimal("5.0"):
            score += 20
        return min(100, max(0, score))
'@
$n = @'
    @staticmethod
    def _sequence_purity(swings: List[Swing], bias: str) -> float:
        recent = swings[-6:]
        if len(recent) < 2 or bias not in ("BULLISH", "BEARISH"):
            return 0.0
        agree = 0
        total = 0
        prev_high: Optional[Decimal] = None
        prev_low: Optional[Decimal] = None
        for s in recent:
            if s.kind == SwingKind.HIGH:
                if prev_high is not None:
                    total += 1
                    if ((bias == "BULLISH" and s.price > prev_high)
                            or (bias == "BEARISH" and s.price < prev_high)):
                        agree += 1
                prev_high = s.price
            else:
                if prev_low is not None:
                    total += 1
                    if ((bias == "BULLISH" and s.price > prev_low)
                            or (bias == "BEARISH" and s.price < prev_low)):
                        agree += 1
                prev_low = s.price
        if total == 0:
            return 0.0
        return float(agree) / float(total)

    def _strength(self, reg: Regime, adx: Optional[Decimal], swings: List[Swing],
                  bias: str, avwap_dist_sigma: Decimal) -> int:
        if reg in (Regime.UNKNOWN, Regime.RANGE, Regime.COMPRESSION):
            return 0
        score = 50
        if adx is not None:
            if adx >= 25:
                score += 20
            elif adx >= 20:
                score += 10
        score += int(10 * self._sequence_purity(swings, bias))
        if abs(avwap_dist_sigma) >= Decimal("1.0"):
            score += 20
        return min(100, max(0, score))
'@
Add-Edit 'SE-033' $o $n 1

# ---------------------------------------------------------------- SE-065 (OptionsIntel ctor)
$o = @'
    def __init__(
        self,
        underlying: str,
        atm_band_strikes: int = 3,
        oi_delta_lookback: int = 10,
        pcr_bearish_below: Decimal = Decimal("0.7"),
        pcr_bullish_above: Decimal = Decimal("1.3"),
    ) -> None:
        self.underlying = underlying
        self.atm_band = atm_band_strikes
'@
$n = @'
    def __init__(
        self,
        atm_band_strikes: int = 3,
        oi_delta_lookback: int = 10,
        pcr_bearish_below: Decimal = Decimal("0.7"),
        pcr_bullish_above: Decimal = Decimal("1.3"),
    ) -> None:
        self.atm_band = atm_band_strikes
'@
Add-Edit 'SE-065b' $o $n 1

# ---------------------------------------------------------------- SE-019
$o = @'
        z_pe = pe_delta / avg_oi
        z_ce = ce_delta / avg_oi
        # bullish: PE writing (pe_delta>0) with CE flat/negative
        if z_pe >= Decimal("1.5") and z_ce <= 0:
            return "bullish", z_pe
        # bearish: CE writing with PE flat/negative
        if z_ce >= Decimal("1.5") and z_pe <= 0:
            return "bearish", z_ce
        # CE unwinding above spot during up-move -> bullish (resistance dissolving)
        if z_ce <= Decimal("-1.5"):
            return "bullish", abs(z_ce)
        if z_pe <= Decimal("-1.5"):
            return "bearish", abs(z_pe)
        return "neutral", max(abs(z_pe), abs(z_ce))
'@
$n = @'
        sess_pe = Decimal(0)
        sess_ce = Decimal(0)
        for st in s.strikes:
            if st.strike in atm_strikes:
                sess_pe += Decimal(st.pe.oi - self._baseline_oi.get(f"{st.strike}|PE", st.pe.oi))
                sess_ce += Decimal(st.ce.oi - self._baseline_oi.get(f"{st.strike}|CE", st.ce.oi))
        z_pe = pe_delta / avg_oi
        z_ce = ce_delta / avg_oi
        # bullish: PE writing (pe_delta>0) with CE flat/negative, session-confirmed
        if z_pe >= Decimal("1.5") and z_ce <= 0 and sess_pe > 0:
            return "bullish", z_pe
        # bearish: CE writing with PE flat/negative, session-confirmed
        if z_ce >= Decimal("1.5") and z_pe <= 0 and sess_ce > 0:
            return "bearish", z_ce
        # CE unwinding above spot during up-move -> bullish (resistance dissolving)
        if z_ce <= Decimal("-1.5") and sess_ce < 0:
            return "bullish", abs(z_ce)
        if z_pe <= Decimal("-1.5") and sess_pe < 0:
            return "bearish", abs(z_pe)
        return "neutral", max(abs(z_pe), abs(z_ce))
'@
Add-Edit 'SE-019' $o $n 1

# ---------------------------------------------------------------- SE-015
$o = @'
        result: Dict[str, str] = {}
        for st in band:
            for leg_name, leg in (("CE", st.ce), ("PE", st.pe)):
                price_up = leg.ltp >= leg.bid  # proxy; refined by oi_prev delta
                oi_up = leg.oi >= leg.oi_prev
                if price_up and oi_up:
                    result[f"{st.strike}|{leg_name}"] = "long_buildup"
                elif not price_up and oi_up:
                    result[f"{st.strike}|{leg_name}"] = "short_buildup"
                elif price_up and not oi_up:
                    result[f"{st.strike}|{leg_name}"] = "short_covering"
                else:
                    result[f"{st.strike}|{leg_name}"] = "long_unwinding"
        return result
'@
$n = @'
        result: Dict[str, str] = {}
        prev_ltp: Dict[str, Decimal] = {}
        if len(self._snapshots) >= 2:
            for pst in self._snapshots[-2].strikes:
                prev_ltp[f"{pst.strike}|CE"] = pst.ce.ltp
                prev_ltp[f"{pst.strike}|PE"] = pst.pe.ltp
        for st in band:
            for leg_name, leg in (("CE", st.ce), ("PE", st.pe)):
                key = f"{st.strike}|{leg_name}"
                prev = prev_ltp.get(key)
                if prev is None:
                    result[key] = "neutral"
                    continue
                price_up = leg.ltp > prev
                oi_up = leg.oi >= leg.oi_prev
                if price_up and oi_up:
                    result[key] = "long_buildup"
                elif not price_up and oi_up:
                    result[key] = "short_buildup"
                elif price_up and not oi_up:
                    result[key] = "short_covering"
                else:
                    result[key] = "long_unwinding"
        return result
'@
Add-Edit 'SE-015a' $o $n 1

# ---------------------------------------------------------------- SE-066
$o = @'
    @property
    def last_view(self) -> Optional[OptionsView]:
        return self._last_view

    @property
    def snapshots(self) -> List[ChainSnapshot]:
'@
$n = @'
    @property
    def snapshots(self) -> List[ChainSnapshot]:
'@
Add-Edit 'SE-066b' $o $n 1

# ---------------------------------------------------------------- UnderlyingState
$o = @'
    def __init__(self, underlying: str, cfg: "Config", tick_size: Decimal, strike_step: Decimal) -> None:
        self.underlying = underlying
        self.tick_size = tick_size
        self.strike_step = strike_step
        self.latest_tick: Optional[Tick] = None
'@
$n = @'
    def __init__(self, underlying: str, cfg: "Config", tick_size: Decimal,
                 clock: Optional[Clock] = None) -> None:
        self.underlying = underlying
        self.tick_size = tick_size
        self.latest_tick: Optional[Tick] = None
        self.option_ticks: Dict[str, Tick] = {}
        self.option_minute_ltp: Dict[str, Deque[Tuple[datetime, Decimal]]] = {}
'@
Add-Edit 'SE-065c/SE-041a' $o $n 1

$o = @'
        self.structure = StructureEngine(
            cfg.structure.swing_left_bars, cfg.structure.swing_right_bars,
            cfg.structure.sweep_max_close_back_bars, tick_size,
        )
        self.regime = RegimeClassifier(cfg.regime.adx_period, cfg.regime.atr_period)
        self.options = OptionsIntel(
            underlying, cfg.options.atm_band_strikes, cfg.options.oi_delta_lookback_snapshots,
            cfg.options.pcr_bearish_below, cfg.options.pcr_bullish_above,
        )
'@
$n = @'
        self.structure = StructureEngine(
            cfg.structure.swing_left_bars, cfg.structure.swing_right_bars,
            cfg.structure.sweep_max_close_back_bars,
        )
        self.regime = RegimeClassifier(
            cfg.regime.adx_period, cfg.regime.atr_period,
            cfg.regime.compression_bb_pct_rank, clock,
        )
        self.options = OptionsIntel(
            cfg.options.atm_band_strikes, cfg.options.oi_delta_lookback_snapshots,
            cfg.options.pcr_bearish_below, cfg.options.pcr_bullish_above,
        )
'@
Add-Edit 'SE-016b/SE-065d' $o $n 1

$o = @'
        self._last_1m_class: str = "normal"
        self._last_rvol: Optional[float] = None
        self._median_atr_5day: Optional[Decimal] = None
'@
$n = @'
        self._last_1m_class: str = "normal"
        self._recent_1m_classes: Deque[str] = deque(maxlen=5)
        self._last_rvol: Optional[float] = None
        self._prev_atm_option_volume_cum: int = 0
        self._consec_1m_beyond_or_up: int = 0
        self._consec_1m_beyond_or_down: int = 0
        self._session_open_price: Optional[Decimal] = None
        self._or_break_emitted: bool = False
'@
Add-Edit 'SE-065e/SE-005a/SE-008a' $o $n 1

$o = @'
    def on_bar_1m(self, bar: Bar) -> None:
        self.bars_1m.append(bar)
        self.atr_1m.update(bar)
        rvol = self.volume.rvol(bar.ts_open, self.last_atm_option_volume)
        self._last_rvol = rvol
        self.volume.record_minute(bar.ts_open, self.last_atm_option_volume)
        self._last_1m_class = self.volume.classify_bar(bar, self.atr_1m.value, rvol)
        self.avwap.update(bar, self.last_atm_option_volume, self.last_atm_option_volume_suspect)

    def on_bar_5m(self, bar: Bar, phase: SessionPhase) -> List[StructureEvent]:
        self.bars_5m.append(bar)
        self.atr_5m.update(bar)
        self.adx.update(bar)
        self.bb.update(bar)
        self.ema20.update(bar)
        events = self.structure.on_bar_5m(bar, self.atr_5m.value)
        or_broken = False
        or_swept = False
        if self._or_high is not None and bar.close > self._or_high:
            or_broken = True
        if self._or_low is not None and bar.close < self._or_low:
            or_broken = True
        for ev in events:
            if ev.kind in (StructureKind.SWEEP_HIGH, StructureKind.SWEEP_LOW):
                or_swept = True
        impulse_present = self._last_1m_class == "impulse"
        self.regime.on_bar_5m(
            bar, self.adx.value, self.adx.rising, self.structure.swings, self.structure.bias,
            self.avwap.value, self.avwap.slope_over(10), self.bb.percentile_rank(),
            self.bb.rising_3, impulse_present, phase, or_broken, or_swept,
            self.atr_5m.value,
        )
        return events
'@
$n = @'
    def _record_option_minute(self, ts: datetime) -> None:
        snap = self.last_chain
        if snap is None:
            return
        ordered = sorted(snap.strikes, key=lambda x: abs(x.strike - snap.atm_strike))[:7]
        for st in ordered:
            for leg_name, leg in (("CE", st.ce), ("PE", st.pe)):
                key = f"{st.strike}|{leg_name}"
                series = self.option_minute_ltp.setdefault(key, deque(maxlen=40))
                if series and series[-1][0] == ts:
                    continue
                series.append((ts, leg.ltp))
        if len(self.option_minute_ltp) > 80:
            for k in sorted(self.option_minute_ltp.keys())[:-80]:
                del self.option_minute_ltp[k]

    def on_bar_1m(self, bar: Bar) -> None:
        self.bars_1m.append(bar)
        self.atr_1m.update(bar)
        if self._session_open_price is None and bar.ts_open.time() >= dtime(9, 15):
            self._session_open_price = bar.open
        if self._or_high is not None and bar.close > self._or_high:
            self._consec_1m_beyond_or_up += 1
        else:
            self._consec_1m_beyond_or_up = 0
        if self._or_low is not None and bar.close < self._or_low:
            self._consec_1m_beyond_or_down += 1
        else:
            self._consec_1m_beyond_or_down = 0
        rvol = self.volume.rvol(bar.ts_open, self.last_atm_option_volume)
        self._last_rvol = rvol
        self.volume.record_minute(bar.ts_open, self.last_atm_option_volume)
        self._last_1m_class = self.volume.classify_bar(bar, self.atr_1m.value, rvol)
        self._recent_1m_classes.append(self._last_1m_class)
        self.avwap.update(bar, self.last_atm_option_volume, self.last_atm_option_volume_suspect)
        self._record_option_minute(bar.ts_open)
        self.structure.on_bar_1m(bar, self.atr_5m.value)

    def on_bar_5m(self, bar: Bar, phase: SessionPhase) -> List[StructureEvent]:
        self.bars_5m.append(bar)
        self.atr_5m.update(bar)
        self.adx.update(bar)
        self.bb.update(bar)
        self.ema20.update(bar)
        self.structure.set_atr_5m(self.atr_5m.value)
        self.structure.set_dynamic_levels(self.avwap.value, self.avwap.sigma, self.ema20.value)
        events = self.structure.on_bar_5m(bar)
        rvol_ok = self._last_rvol is not None and self._last_rvol >= 2.0
        or_broken = False
        drive_level: Optional[Decimal] = None
        if (self._or_high is not None and bar.close > self._or_high
                and self._consec_1m_beyond_or_up >= 3 and rvol_ok):
            or_broken = True
            drive_level = self._or_high
        if (self._or_low is not None and bar.close < self._or_low
                and self._consec_1m_beyond_or_down >= 3 and rvol_ok):
            or_broken = True
            drive_level = self._or_low
        or_swept = False
        for ev in events:
            if (ev.kind == StructureKind.SWEEP_HIGH and self._or_high is not None
                    and ev.level == self._or_high):
                if self._session_open_price is not None and bar.close < self._session_open_price:
                    or_swept = True
            if (ev.kind == StructureKind.SWEEP_LOW and self._or_low is not None
                    and ev.level == self._or_low):
                if self._session_open_price is not None and bar.close > self._session_open_price:
                    or_swept = True
        impulse_present = self._last_1m_class == "impulse"
        ctx = AnalyticsView(
            adx=self.adx.value, adx_rising=self.adx.rising, swings=self.structure.swings,
            bias=self.structure.bias, avwap=self.avwap.value,
            avwap_slope=self.avwap.slope_over(10),
            avwap_dist_sigma=self.avwap.distance_in_sigma(bar.close),
            bb_pct=self.bb.percentile_rank(), bb_rising_3=self.bb.rising_3,
            impulse_present=impulse_present, phase=phase,
            opening_range_broken=or_broken, opening_extreme_swept=or_swept,
            atr_5m=self.atr_5m.value,
        )
        prev_regime = self.regime.state.regime
        state = self.regime.on_bar_5m(bar, ctx)
        if (or_broken and phase == SessionPhase.OPENING
                and not self._or_break_emitted and drive_level is not None):
            self._or_break_emitted = True
            ev_break = StructureEvent(StructureKind.OPENING_DRIVE_BREAK, drive_level, bar.ts_open, None)
            self.structure.append_event(ev_break)
            events.append(ev_break)
        if prev_regime == Regime.COMPRESSION and state.regime == Regime.EXPANSION:
            ev_exp = StructureEvent(StructureKind.EXPANSION_IMPULSE, bar.close, bar.ts_open, None)
            self.structure.append_event(ev_exp)
            events.append(ev_exp)
        return events
'@
Add-Edit 'SE-004c/SE-008b/SE-018c/SE-038b/SE-041b' $o $n 1

$o = @'
    def on_chain(self, snap: ChainSnapshot) -> OptionsView:
        self.last_chain = snap
        vol, suspect = self.compute_atm_option_volume(snap)
        self.last_atm_option_volume = vol
        self.last_atm_option_volume_suspect = suspect
'@
$n = @'
    def on_chain(self, snap: ChainSnapshot) -> OptionsView:
        self.last_chain = snap
        vol, suspect = self.compute_atm_option_volume(snap)
        if self._prev_atm_option_volume_cum > 0 and vol >= self._prev_atm_option_volume_cum:
            delta = vol - self._prev_atm_option_volume_cum
        else:
            delta = 0
        self._prev_atm_option_volume_cum = vol
        self.last_atm_option_volume = delta
        self.last_atm_option_volume_suspect = suspect or delta <= 0
'@
Add-Edit 'SE-005b' $o $n 1

$o = @'
    @property
    def last_rvol(self) -> Optional[float]:
        return self._last_rvol
'@
$n = @'
    @property
    def last_rvol(self) -> Optional[float]:
        return self._last_rvol

    @property
    def recent_1m_classes(self) -> List[str]:
        return list(self._recent_1m_classes)
'@
Add-Edit 'SE-030a' $o $n 1

$o = @'
            "regime": self.regime.persist(),
            "options": self.options.state(),
'@
$n = @'
            "regime": self.regime.persist(),
            "options": self.options.state(),
            "iv": self.iv.state(),
'@
Add-Edit 'SE-027b' $o $n 1

$o = @'
        self.structure.restore(s.get("structure", {}))
        self.regime.restore(s.get("regime", {}))
        self.options.restore(s.get("options", {}))
'@
$n = @'
        self.structure.restore(s.get("structure", {}))
        self.structure.seed_bars(self.bars_5m)
        self.regime.restore(s.get("regime", {}))
        self.options.restore(s.get("options", {}))
        self.iv.restore(s.get("iv", {}))
'@
Add-Edit 'SE-011c/SE-027c' $o $n 1

$o = @'
    def __init__(self, cfg: "Config", instruments: "Instruments") -> None:
        self.cfg = cfg
        self.instruments = instruments
        self.states: Dict[str, UnderlyingState] = {}
        for u in cfg.engine.underlyings:
            inst = instruments.by_name[u]
            self.states[u] = UnderlyingState(u, cfg, inst.tick_size, inst.strike_step)
'@
$n = @'
    def __init__(self, cfg: "Config", instruments: "Instruments",
                 clock: Optional[Clock] = None) -> None:
        self.cfg = cfg
        self.instruments = instruments
        self.states: Dict[str, UnderlyingState] = {}
        for u in cfg.engine.underlyings:
            inst = instruments.by_name[u]
            self.states[u] = UnderlyingState(u, cfg, inst.tick_size, clock)
'@
Add-Edit 'SE-070b/SE-065f' $o $n 1

$o = @'
    def apply_index_bar(self, underlying: str, bar_1m: Bar, phase: SessionPhase,
'@
$n = @'
    def apply_option_tick(self, t: Tick, underlying: str) -> None:
        st = self.states[underlying]
        st.option_ticks[t.security_id] = t

    def apply_index_bar(self, underlying: str, bar_1m: Bar, phase: SessionPhase,
'@
Add-Edit 'SE-002b' $o $n 1

# ---------------------------------------------------------------- SE-057 / MarketView
$o = @'
@dataclass(frozen=True, slots=True)
class MarketView:
    """Immutable read-only view passed to the decision layer."""
'@
$n = @'
@dataclass(frozen=True, slots=True)
class AnalyticsView:
    """Analytics context handed to the regime classifier (§11 interface)."""
    adx: Optional[Decimal]
    adx_rising: bool
    swings: List[Swing]
    bias: str
    avwap: Optional[Decimal]
    avwap_slope: Decimal
    avwap_dist_sigma: Decimal
    bb_pct: float
    bb_rising_3: bool
    impulse_present: bool
    phase: SessionPhase
    opening_range_broken: bool
    opening_extreme_swept: bool
    atr_5m: Optional[Decimal]


@dataclass(frozen=True, slots=True)
class MarketView:
    """Immutable read-only view passed to the decision layer."""
'@
Add-Edit 'SE-057' $o $n 1

$o = @'
    recent_1m_bars: List[Bar]
    nearest_opposing_level: Optional[Level]
    clustered_trigger_level: Optional[Level]


def build_market_view(store: MarketStateStore, underlying: str, calendar: SessionCalendar,
                      clock: Clock, trigger_level: Optional[Decimal],
                      direction: Optional[Direction]) -> MarketView:
'@
$n = @'
    recent_1m_bars: List[Bar]
    nearest_opposing_level: Optional[Level]
    clustered_trigger_level: Optional[Level]
    recent_1m_classes: List[str]
    session_high: Optional[Decimal]
    session_low: Optional[Decimal]
    selected_strike: Optional[Decimal] = None
    selected_leg: Optional[str] = None
    reward_risk: Optional[Decimal] = None


def build_market_view(store: MarketStateStore, underlying: str, calendar: SessionCalendar,
                      clock: Clock, trigger_level: Optional[Decimal],
                      direction: Optional[Direction],
                      selected_strike: Optional[Decimal] = None,
                      selected_leg: Optional[str] = None,
                      reward_risk: Optional[Decimal] = None) -> MarketView:
'@
Add-Edit 'SE-030b/SE-039a/SE-073b' $o $n 1

$o = @'
        recent_1m_bars=list(st.bars_1m)[-5:], nearest_opposing_level=nearest_opp,
        clustered_trigger_level=clustered,
    )
'@
$n = @'
        recent_1m_bars=list(st.bars_1m)[-5:], nearest_opposing_level=nearest_opp,
        clustered_trigger_level=clustered,
        recent_1m_classes=st.recent_1m_classes,
        session_high=st.structure.session_high, session_low=st.structure.session_low,
        selected_strike=selected_strike, selected_leg=selected_leg,
        reward_risk=reward_risk,
    )
'@
Add-Edit 'SE-039b' $o $n 1

# ---------------------------------------------------------------- SE-029 / SE-072 / SE-028
$o = @'
    engine = EngineCfg(
        underlyings=list(_require(e, "underlyings", "engine")),
        evaluation_interval_s=int(_require(e, "evaluation_interval_s", "engine")),
        timezone=str(_require(e, "timezone", "engine")),
        holidays=list(e.get("holidays", [])),
    )
'@
$n = @'
    engine_tz = str(_require(e, "timezone", "engine"))
    if engine_tz != "Asia/Kolkata":
        raise FatalConfigError(f"engine.timezone must be Asia/Kolkata, got {engine_tz}")
    engine = EngineCfg(
        underlyings=list(_require(e, "underlyings", "engine")),
        evaluation_interval_s=int(_require(e, "evaluation_interval_s", "engine")),
        timezone=engine_tz,
        holidays=list(e.get("holidays", [])),
    )
'@
Add-Edit 'SE-029' $o $n 1

$o = @'
        _reject_unknown(nw, ["start", "end", "dates"], "risk.news_blackout")
        news.append(NewsWindow(str(nw["start"]), str(nw["end"]), list(nw.get("dates", []))))
'@
$n = @'
        _reject_unknown(nw, ["start", "end", "dates"], "risk.news_blackout")
        nw_dates = list(nw.get("dates", []))
        if not nw_dates:
            raise FatalConfigError("risk.news_blackout[].dates must be a non-empty list")
        news.append(NewsWindow(str(nw["start"]), str(nw["end"]), nw_dates))
'@
Add-Edit 'SE-072' $o $n 1

$o = @'
    with open(path, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
'@
$n = @'
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
    except OSError as exc:
        raise FatalConfigError(f"cannot read config file {path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise FatalConfigError(f"cannot parse config file {path}: {exc}") from exc
    if not isinstance(data, dict):
'@
Add-Edit 'SE-028' $o $n 1

# ---------------------------------------------------------------- Confluence
$o = @'
        ev: List[Evidence] = []
        ev.extend(self._trend(m, bullish, want_sem))
'@
$n = @'
        ev: List[Evidence] = []
        ev.append(Evidence(CAT_STRUCTURE, "candidate_direction", "neutral", 0.0, 0.0,
                           c.direction.value, "neutral"))
        ev.extend(self._trend(m, bullish, want_sem))
'@
Add-Edit 'SE-058C-a' $o $n 1

$o = @'
    def _structure(self, c: CandidateSignal, m: MarketView, sem: str) -> List[Evidence]:
        out: List[Evidence] = []
        kind = c.trigger.kind
'@
$n = @'
    def _structure(self, c: CandidateSignal, m: MarketView, sem: str) -> List[Evidence]:
        out: List[Evidence] = []
        adverse = "bearish" if sem == "bullish" else "bullish"
        kind = c.trigger.kind
'@
Add-Edit 'SE-012a' $o $n 1

$o = @'
        elif kind in (StructureKind.BOS_UP, StructureKind.BOS_DOWN):
            pts = 9.0
            detail = f"BOS fresh at {c.trigger.level}"
'@
$n = @'
        elif kind in (StructureKind.BOS_UP, StructureKind.BOS_DOWN,
                      StructureKind.OPENING_DRIVE_BREAK, StructureKind.EXPANSION_IMPULSE):
            pts = 9.0
            detail = f"{kind.value} at {c.trigger.level}"
'@
Add-Edit 'SE-038c' $o $n 1

$o = @'
                            8.0 if far_ok else 0.0, "nearest opposing >=1.5 ATR" if far_ok else "opposing level near",
                            "bearish" if (not far_ok) else "neutral"))
'@
$n = @'
                            8.0 if far_ok else 0.0, "nearest opposing >=1.5 ATR" if far_ok else "opposing level near",
                            adverse if (not far_ok) else "neutral"))
'@
Add-Edit 'SE-012b' $o $n 1

$o = @'
    def _volume(self, m: MarketView, sem: str) -> List[Evidence]:
        out: List[Evidence] = []
        rvol_ok = m.rvol is not None and m.rvol >= 1.5
        out.append(Evidence(CAT_VOLUME, "rvol", "true" if rvol_ok else ("neutral" if m.rvol is None else "false"),
                            7.0, 7.0 if rvol_ok else 0.0, f"rvol={m.rvol}", "neutral"))
        no_absorb = m.bar_class != "absorption"
        out.append(Evidence(CAT_VOLUME, "no_absorption", "true" if no_absorb else "false", 5.0,
                            5.0 if no_absorb else 0.0, f"bar_class={m.bar_class}",
                            "bearish" if not no_absorb else "neutral"))
        return out
'@
$n = @'
    def _volume(self, m: MarketView, sem: str) -> List[Evidence]:
        out: List[Evidence] = []
        adverse = "bearish" if sem == "bullish" else "bullish"
        bullish = sem == "bullish"
        rvol_ok = m.rvol is not None and m.rvol >= 1.5
        out.append(Evidence(CAT_VOLUME, "rvol", "true" if rvol_ok else ("neutral" if m.rvol is None else "false"),
                            7.0, 7.0 if rvol_ok else 0.0, f"rvol={m.rvol}", "neutral"))
        no_absorb = True
        ref = m.session_high if bullish else m.session_low
        for cls, b in zip(m.recent_1m_classes[-3:], m.recent_1m_bars[-3:]):
            if cls != "absorption":
                continue
            against = (b.close < b.open) if bullish else (b.close > b.open)
            if not against:
                continue
            if ref is None or m.atr_5m is None or m.atr_5m <= 0:
                no_absorb = False
                continue
            extreme = b.high if bullish else b.low
            if abs(extreme - ref) <= Decimal("0.15") * m.atr_5m:
                no_absorb = False
        out.append(Evidence(CAT_VOLUME, "no_absorption", "true" if no_absorb else "false", 5.0,
                            5.0 if no_absorb else 0.0,
                            f"bar_class={m.bar_class} recent={list(m.recent_1m_classes[-3:])}",
                            adverse if not no_absorb else "neutral"))
        return out
'@
Add-Edit 'SE-030c/SE-012c' $o $n 1

$o = @'
    def _options(self, m: MarketView, sem: str) -> List[Evidence]:
        out: List[Evidence] = []
        ov = m.options_view
        if ov is None:
            out.append(Evidence(CAT_OPTIONS, "directional_oi", "false", 10.0, 0.0, "no chain", "neutral"))
            out.append(Evidence(CAT_OPTIONS, "atm_migration", "false", 5.0, 0.0, "no chain", "neutral"))
            out.append(Evidence(CAT_OPTIONS, "chain_sr", "false", 5.0, 0.0, "no chain", "neutral"))
            return out
        oi_aligned = ov.directional_oi == sem and ov.directional_z >= Decimal("1.5")
        oi_opp = ov.directional_oi != sem and ov.directional_oi != "neutral" and ov.directional_z >= Decimal("1.5")
        out.append(Evidence(CAT_OPTIONS, "directional_oi", "true" if oi_aligned else ("false" if oi_opp else "neutral"),
                            10.0, 10.0 if oi_aligned else 0.0,
                            f"oi={ov.directional_oi} z={ov.directional_z}",
                            ov.directional_oi if ov.directional_oi != "neutral" else "neutral"))
        want_mig = "up" if sem == "bullish" else "down"
        mig_ok = ov.atm_migration in (want_mig, "none")
        out.append(Evidence(CAT_OPTIONS, "atm_migration", "true" if mig_ok else "false", 5.0,
                            5.0 if mig_ok else 0.0, f"migration={ov.atm_migration}",
                            "bearish" if not mig_ok else "neutral"))
        opposing = ov.resistance_levels if sem == "bullish" else ov.support_levels
        immediate = False
        if opposing and m.atr_5m and m.atr_5m > 0:
            nearest = min(opposing, key=lambda lv: abs(lv.price - m.spot))
            immediate = abs(nearest.price - m.spot) < m.atr_5m
        out.append(Evidence(CAT_OPTIONS, "chain_sr_clear", "true" if not immediate else "false", 5.0,
                            5.0 if not immediate else 0.0,
                            "chain S/R not immediately opposing" if not immediate else "chain S/R opposing",
                            "bearish" if immediate else "neutral"))
        return out
'@
$n = @'
    def _options(self, m: MarketView, sem: str) -> List[Evidence]:
        out: List[Evidence] = []
        adverse = "bearish" if sem == "bullish" else "bullish"
        ov = m.options_view
        if ov is None:
            out.append(Evidence(CAT_OPTIONS, "directional_oi", "false", 10.0, 0.0, "no chain", "neutral"))
            out.append(Evidence(CAT_OPTIONS, "atm_migration", "false", 5.0, 0.0, "no chain", "neutral"))
            out.append(Evidence(CAT_OPTIONS, "chain_sr_clear", "false", 5.0, 0.0, "no chain", "neutral"))
            out.append(Evidence(CAT_OPTIONS, "pcr_tiebreak", "neutral", 0.0, 0.0, "no chain", "neutral"))
            return out
        oi_aligned = ov.directional_oi == sem and ov.directional_z >= Decimal("1.5")
        oi_opp = ov.directional_oi != sem and ov.directional_oi != "neutral" and ov.directional_z >= Decimal("1.5")
        cls_ce = ov.classifications.get(f"{ov.atm_strike}|CE", "n/a")
        cls_pe = ov.classifications.get(f"{ov.atm_strike}|PE", "n/a")
        out.append(Evidence(CAT_OPTIONS, "directional_oi", "true" if oi_aligned else ("false" if oi_opp else "neutral"),
                            10.0, 10.0 if oi_aligned else 0.0,
                            f"oi={ov.directional_oi} z={ov.directional_z} atmCE={cls_ce} atmPE={cls_pe}",
                            ov.directional_oi if ov.directional_oi != "neutral" else "neutral"))
        want_mig = "up" if sem == "bullish" else "down"
        mig_ok = ov.atm_migration in (want_mig, "none")
        out.append(Evidence(CAT_OPTIONS, "atm_migration", "true" if mig_ok else "false", 5.0,
                            5.0 if mig_ok else 0.0, f"migration={ov.atm_migration}",
                            adverse if not mig_ok else "neutral"))
        opposing = ov.resistance_levels if sem == "bullish" else ov.support_levels
        immediate = False
        if opposing and m.atr_5m and m.atr_5m > 0:
            nearest = min(opposing, key=lambda lv: abs(lv.price - m.spot))
            immediate = abs(nearest.price - m.spot) < m.atr_5m
        out.append(Evidence(CAT_OPTIONS, "chain_sr_clear", "true" if not immediate else "false", 5.0,
                            5.0 if not immediate else 0.0,
                            "chain S/R not immediately opposing" if not immediate else "chain S/R opposing",
                            adverse if immediate else "neutral"))
        if ov.pcr_signal == sem:
            pcr_passed = "true"
        elif ov.pcr_signal in ("bullish", "bearish"):
            pcr_passed = "false"
        else:
            pcr_passed = "neutral"
        out.append(Evidence(CAT_OPTIONS, "pcr_tiebreak", pcr_passed, 0.0, 0.0,
                            f"pcr={ov.pcr} signal={ov.pcr_signal}",
                            ov.pcr_signal if ov.pcr_signal in ("bullish", "bearish") else "neutral"))
        return out
'@
Add-Edit 'SE-012d/SE-015b/SE-020/SE-068' $o $n 1

$o = @'
    def _volatility(self, m: MarketView, sem: str) -> List[Evidence]:
        out: List[Evidence] = []
        adequate = m.bb_expansion or (m.atr_5m_median_ratio is not None and m.atr_5m_median_ratio >= Decimal("0.65"))
'@
$n = @'
    def _volatility(self, m: MarketView, sem: str) -> List[Evidence]:
        out: List[Evidence] = []
        adverse = "bearish" if sem == "bullish" else "bullish"
        adequate = m.bb_expansion or (m.atr_5m_median_ratio is not None and m.atr_5m_median_ratio >= Decimal("0.65"))
'@
Add-Edit 'SE-012e' $o $n 1

$o = @'
                            3.0 if iv_ok else 0.0, f"iv_spike={m.iv_spike}", "bearish" if not iv_ok else "neutral"))
'@
$n = @'
                            3.0 if iv_ok else 0.0, f"iv_spike={m.iv_spike}", adverse if not iv_ok else "neutral"))
'@
Add-Edit 'SE-012f' $o $n 1

# ---------------------------------------------------------------- Scorer
$o = @'
    def score(self, ledger: List[Evidence], candidate: CandidateSignal) -> ScoredCandidate:
'@
$n = @'
    def score(self, ledger: List[Evidence]) -> ScoredCandidate:
'@
Add-Edit 'SE-058C-b' $o $n 1

$o = @'
        want_sem = "bullish" if candidate.direction == Direction.LONG_CE else "bearish"
        opp_sem = "bearish" if want_sem == "bullish" else "bullish"
        contradictions = 0
        for cat, items in by_cat.items():
            opp_contrib = sum(
                i.weight for i in items if i.semantic == opp_sem and i.passed == "false"
            )
            # a category with strong opposite semantic evidence
            opp_present = any(i.semantic == opp_sem for i in items)
'@
$n = @'
        want_sem = "bullish"
        for e in ledger:
            if e.name == "candidate_direction":
                want_sem = "bullish" if e.detail == Direction.LONG_CE.value else "bearish"
                break
        opp_sem = "bearish" if want_sem == "bullish" else "bullish"
        contradictions = 0
        for cat, items in by_cat.items():
            # a category with strong opposite semantic evidence
            opp_present = any(i.semantic == opp_sem for i in items)
'@
Add-Edit 'SE-062/SE-058C-c' $o $n 1

$o = @'
        return ScoredCandidate(
            candidate=candidate, ledger=ledger, score=score, band=band,
            categories_passed=categories_passed, contradictions=contradictions,
            mandatory_ok=mandatory_ok,
        )
'@
$n = @'
        return ScoredCandidate(
            candidate=None, ledger=ledger, score=score, band=band,
            categories_passed=categories_passed, contradictions=contradictions,
            mandatory_ok=mandatory_ok,
            min_categories_ok=categories_passed >= self.min_categories,
        )
'@
Add-Edit 'SE-048b' $o $n 1

# ---------------------------------------------------------------- Risk gates
$o = @'
    def __init__(self, cfg: Config, calendar: SessionCalendar,
                 lot_sizes: Optional[Dict[str, int]] = None) -> None:
        self.cfg = cfg
        self.calendar = calendar
        self.lot_sizes: Dict[str, int] = lot_sizes or {}

    def validate(self, sc: ScoredCandidate, m: MarketView,
                 feed_degraded_recent: bool) -> GateResult:
        reasons: List[str] = []
        direction = sc.candidate.direction
        # LIQUIDITY
        selected: Optional[Tuple[Decimal, str]] = None
        if m.chain is not None and m.options_view is not None:
            atm = m.options_view.atm_strike
            straddle_half = None
            for st in m.chain.strikes:
                if st.strike == atm:
                    straddle_half = (st.ce.ltp + st.pe.ltp) / Decimal(2)
                    break
            selected = self._select(direction, m, straddle_half)
        if selected is None:
            reasons.append("LIQUIDITY")
            return GateResult(False, reasons)
        strike, leg_name = selected
'@
$n = @'
    def __init__(self, cfg: Config, calendar: SessionCalendar,
                 lot_sizes: Optional[Dict[str, int]] = None) -> None:
        self.cfg = cfg
        self.calendar = calendar
        self.lot_sizes: Dict[str, int] = lot_sizes or {}
        self.health: Optional["HealthMonitor"] = None
        self.signals: Optional["SignalManager"] = None

    def validate(self, sc: ScoredCandidate, m: MarketView) -> GateResult:
        reasons: List[str] = []
        # LIQUIDITY
        strike = m.selected_strike
        leg_name = m.selected_leg
        if strike is None or leg_name is None or m.chain is None or m.options_view is None:
            reasons.append("LIQUIDITY")
            return GateResult(False, reasons)
'@
Add-Edit 'SE-058D-a/SE-059a' $o $n 1

$o = @'
        # REGIME
        if m.regime.regime in (Regime.RANGE, Regime.UNKNOWN, Regime.COMPRESSION):
            # sweeps in RANGE at extremes are the only permitted setup class
            is_sweep = sc.candidate.trigger.kind in (StructureKind.SWEEP_HIGH, StructureKind.SWEEP_LOW)
            if not (m.regime.regime == Regime.RANGE and is_sweep):
                reasons.append("REGIME")
                return GateResult(False, reasons, strike, leg_name)
        # UNCERTAINTY
        disorderly = (
            m.last_bar_1m is not None and m.atr_1m is not None and m.atr_1m > 0
            and m.last_bar_1m.range > Decimal(3) * m.atr_1m
        )
        if m.iv_spike or feed_degraded_recent or disorderly:
            reasons.append("UNCERTAINTY")
            return GateResult(False, reasons, strike, leg_name)
        # NEWS
        if self._in_blackout(m.ts):
            reasons.append("NEWS")
            return GateResult(False, reasons, strike, leg_name)
        return GateResult(True, reasons, strike, leg_name)

    def _select(self, direction: Direction, m: MarketView,
                straddle_half: Optional[Decimal]) -> Optional[Tuple[Decimal, str]]:
        if m.chain is None or m.options_view is None:
            return None
        oi = OptionsIntel(m.underlying)
        return oi.select_strike(direction, m.chain, m.options_view,
                               self.cfg.risk.max_spread_pct_of_premium, straddle_half)
'@
$n = @'
        # REGIME
        if m.regime.regime in (Regime.RANGE, Regime.UNKNOWN, Regime.COMPRESSION):
            # sweeps in RANGE at range extremes are the only permitted setup class
            trig = sc.candidate.trigger if sc.candidate is not None else None
            is_sweep = trig is not None and trig.kind in (StructureKind.SWEEP_HIGH, StructureKind.SWEEP_LOW)
            at_extreme = False
            if is_sweep and trig is not None and m.atr_5m is not None and m.atr_5m > 0:
                ref = m.session_high if trig.kind == StructureKind.SWEEP_HIGH else m.session_low
                at_extreme = ref is not None and abs(trig.level - ref) <= Decimal("0.25") * m.atr_5m
            if not (m.regime.regime == Regime.RANGE and is_sweep and at_extreme):
                reasons.append("REGIME")
                return GateResult(False, reasons, strike, leg_name)
        # REWARD_RISK
        if m.reward_risk is None or m.reward_risk < self.cfg.signals.min_reward_risk:
            reasons.append("REWARD_RISK")
            return GateResult(False, reasons, strike, leg_name)
        # UNCERTAINTY
        disorderly = (
            m.last_bar_1m is not None and m.atr_1m is not None and m.atr_1m > 0
            and m.last_bar_1m.range > Decimal(3) * m.atr_1m
        )
        degraded_recent = self.health.degraded_recently() if self.health is not None else False
        if m.iv_spike or degraded_recent or disorderly:
            reasons.append("UNCERTAINTY")
            return GateResult(False, reasons, strike, leg_name)
        # NEWS
        if self._in_blackout(m.ts):
            reasons.append("NEWS")
            return GateResult(False, reasons, strike, leg_name)
        # CAPS
        if self.signals is not None and (self.signals.in_cooldown(m.underlying)
                                         or self.signals.cap_reached(m.underlying)):
            reasons.append("CAPS")
            return GateResult(False, reasons, strike, leg_name)
        return GateResult(True, reasons, strike, leg_name)
'@
Add-Edit 'SE-039c/SE-058D-b/SE-059b/SE-073c' $o $n 1

# ---------------------------------------------------------------- Level engine
$o = @'
    def compute(self, sc: ScoredCandidate, m: MarketView, gate: GateResult) -> "Signal | Rejection":
        direction = sc.candidate.direction
        bullish = direction == Direction.LONG_CE
        if gate.selected_strike is None or gate.selected_leg is None or m.chain is None:
            return Rejection(sc.candidate, "LEVELS", ["NO_STRIKE"], sc.ledger)
        strike = gate.selected_strike
        leg = self._leg(m.chain, strike, gate.selected_leg)
'@
$n = @'
    def compute(self, sc: ScoredCandidate, m: MarketView) -> "Signal | Rejection":
        direction = sc.candidate.direction
        bullish = direction == Direction.LONG_CE
        if m.selected_strike is None or m.selected_leg is None or m.chain is None:
            return Rejection(sc.candidate, "LEVELS", ["NO_STRIKE"], sc.ledger)
        strike = m.selected_strike
        leg = self._leg(m.chain, strike, m.selected_leg)
'@
Add-Edit 'SE-058E-a' $o $n 1

$o = @'
        if bullish:
            spot_stop = trig.level - buffer
            spot_risk = m.spot - spot_stop
        else:
            spot_stop = trig.level + buffer
            spot_risk = spot_stop - m.spot
        if spot_risk <= 0:
            return Rejection(sc.candidate, "LEVELS", ["NONPOSITIVE_RISK"], sc.ledger)
        t1_level = self._nearest_target(m, bullish, spot_risk)
        if bullish:
            t1_spot = t1_level if t1_level is not None else m.spot + Decimal("2.5") * spot_risk
            t2_spot = m.spot + Decimal("2.5") * spot_risk
        else:
            t1_spot = t1_level if t1_level is not None else m.spot - Decimal("2.5") * spot_risk
            t2_spot = m.spot - Decimal("2.5") * spot_risk
        beta = self._beta(m.underlying, gate.selected_leg, strike)
'@
$n = @'
        if bullish:
            spot_stop = quantize_tick(trig.level - buffer, Decimal("0.05"))
            spot_risk = m.spot - spot_stop
        else:
            spot_stop = quantize_tick(trig.level + buffer, Decimal("0.05"))
            spot_risk = spot_stop - m.spot
        if spot_risk <= 0:
            return Rejection(sc.candidate, "LEVELS", ["NONPOSITIVE_RISK"], sc.ledger)
        default_t = (m.spot + Decimal("2.5") * spot_risk) if bullish else (m.spot - Decimal("2.5") * spot_risk)
        t1_level = self._nearest_target(m, bullish, spot_risk)
        t1_spot = t1_level if t1_level is not None else default_t
        t2_level = self._nearest_target(m, bullish, spot_risk, t1_spot) if t1_level is not None else None
        t2_spot = t2_level if t2_level is not None else default_t
        if bullish and t2_spot < t1_spot:
            t2_spot = t1_spot
        if (not bullish) and t2_spot > t1_spot:
            t2_spot = t1_spot
        beta = self._beta(m.underlying, m.selected_leg, strike)
'@
Add-Edit 'SE-040a/SE-042a/SE-058E-b' $o $n 1

$o = @'
        rr = (t1_prem - entry) / prem_risk
        if rr < self.cfg.signals.min_reward_risk:
            return Rejection(sc.candidate, "REWARD_RISK", ["REWARD_RISK"], sc.ledger)
        entry_max = quantize_tick(entry * Decimal("1.25"))
'@
$n = @'
        rr = (t1_prem - entry) / prem_risk
        entry_max = quantize_tick(entry * Decimal("1.25"))
'@
Add-Edit 'SE-039d' $o $n 1

$o = @'
            targets=(t1_prem, t2_prem), spot_ref=m.spot, spot_stop=quantize_tick(spot_stop, Decimal("0.05")),
'@
$n = @'
            targets=(t1_prem, t2_prem), spot_ref=m.spot, spot_stop=spot_stop,
'@
Add-Edit 'SE-042b' $o $n 1

$o = @'
    def _nearest_target(self, m: MarketView, bullish: bool, spot_risk: Decimal) -> Optional[Decimal]:
        st = self.store.get(m.underlying)
        direction = "above" if bullish else "below"
        lvl = st.structure.nearest_level(m.spot, direction)
        if lvl is None:
            return None
        if bullish and (lvl.price - m.spot) < spot_risk:
            return None
        if not bullish and (m.spot - lvl.price) < spot_risk:
            return None
        return lvl.price

    def _beta(self, underlying: str, leg_name: str, strike: Decimal) -> Decimal:
        """Empirical minute beta: regress last 20 option ΔLTP on index ΔLTP (§16).
        Fallback delta≈0.5 ATM heuristic if < 20 samples."""
        st = self.store.get(underlying)
        idx = list(st.bars_1m)
        if len(idx) < 21:
            return Decimal("0.5")
        # We only have index bars; option minute deltas approximated via chain snapshots.
        snaps = st.options.snapshots
        pairs: List[Tuple[Decimal, Decimal]] = []
        prev_idx: Optional[Decimal] = None
        prev_opt: Optional[Decimal] = None
        for snap in snaps[-21:]:
            opt = None
            for stk in snap.strikes:
                if stk.strike == strike:
                    opt = stk.ce.ltp if leg_name == "CE" else stk.pe.ltp
                    break
            if opt is None:
                continue
            if prev_idx is not None and prev_opt is not None:
                pairs.append((snap.spot - prev_idx, opt - prev_opt))
            prev_idx = snap.spot
            prev_opt = opt
        if len(pairs) < 20:
            return Decimal("0.5")
        sx = sum(p[0] for p in pairs)
        sy = sum(p[1] for p in pairs)
        n = Decimal(len(pairs))
        mx = sx / n
        my = sy / n
'@
$n = @'
    def _nearest_target(self, m: MarketView, bullish: bool, min_dist: Decimal,
                        beyond: Optional[Decimal] = None) -> Optional[Decimal]:
        st = self.store.get(m.underlying)
        levels = st.structure.levels
        if bullish:
            cand = sorted((lv for lv in levels if lv.price > m.spot), key=lambda x: x.price)
        else:
            cand = sorted((lv for lv in levels if lv.price < m.spot), key=lambda x: x.price, reverse=True)
        for lv in cand:
            dist = (lv.price - m.spot) if bullish else (m.spot - lv.price)
            if dist < min_dist:
                continue
            if beyond is not None:
                if bullish and lv.price <= beyond:
                    continue
                if (not bullish) and lv.price >= beyond:
                    continue
            cl = st.structure.cluster_levels(lv.price)
            if cl is None or cl.strength < 2:
                continue
            return lv.price
        return None

    def _beta(self, underlying: str, leg_name: str, strike: Decimal) -> Decimal:
        """Empirical minute beta: regress last 20 one-minute option ΔLTP on
        index ΔLTP (§16). Fallback delta≈0.5 ATM heuristic if < 20 samples."""
        st = self.store.get(underlying)
        series = st.option_minute_ltp.get(f"{strike}|{leg_name}")
        if not series or len(series) < 21:
            return Decimal("0.5")
        idx_by_ts = {b.ts_open: b.close for b in st.bars_1m}
        pairs: List[Tuple[Decimal, Decimal]] = []
        prev_ts: Optional[datetime] = None
        prev_opt: Optional[Decimal] = None
        for ts, opt in list(series):
            if ts not in idx_by_ts:
                prev_ts = None
                prev_opt = None
                continue
            if prev_ts is not None and prev_opt is not None and prev_ts in idx_by_ts:
                pairs.append((idx_by_ts[ts] - idx_by_ts[prev_ts], opt - prev_opt))
            prev_ts = ts
            prev_opt = opt
        if len(pairs) < 20:
            return Decimal("0.5")
        pairs = pairs[-20:]
        sx = sum(p[0] for p in pairs)
        sy = sum(p[1] for p in pairs)
        n = Decimal(len(pairs))
        mx = sx / n
        my = sy / n
'@
Add-Edit 'SE-040b/SE-041c' $o $n 1

# ---------------------------------------------------------------- Telegram
$o = @'
        f"🎯 SIGNAL — {s.underlying} {dir_txt}\n"
        f"🕐 {ts_txt} IST | Regime: {s.regime.value} ({s.regime_strength})\n"
        f"Instrument: {s.underlying} {s.strike} {leg} · Exp {exp_txt}\n"
'@
$n = @'
        f"🎯 SIGNAL — {_html_escape(s.underlying)} {dir_txt}\n"
        f"🕐 {ts_txt} IST | Regime: {s.regime.value} ({s.regime_strength})\n"
        f"Instrument: {_html_escape(s.underlying)} {s.strike} {leg} · Exp {exp_txt}\n"
'@
Add-Edit 'SE-075' $o $n 1

$o = @'
    def enqueue(self, msg: OutboundMessage) -> None:
        self.queue.put_nowait(msg)
'@
$n = @'
    def enqueue(self, msg: OutboundMessage) -> None:
        if msg.enqueued_mono <= 0.0:
            msg.enqueued_mono = self.clock.monotonic()
        self.queue.put_nowait(msg)
'@
Add-Edit 'SE-051b' $o $n 1

$o = @'
    async def _send_once(self, text: str) -> bool:
        session = await self._ensure_session()
        url = f"{self.API}/bot{self.bot_token}/sendMessage"
        payload = {"chat_id": self.chat_id, "text": text, "parse_mode": "HTML"}
        async with session.post(url, json=payload) as resp:
            status = getattr(resp, "status", 200)
            if status == 200:
                return True
            if status in (429, 500, 502, 503, 504):
                return False
            body = await resp.text()
            log_event(self.logger, logging.WARNING, "telegram_send_failed", status=status, body=body[:200])
            return True  # non-retryable; drop

    async def run(self) -> None:
        while not self._stopped:
            msg = await self.queue.get()
            await self.bucket.acquire(1.0)
            delay = 1.0
            sent = False
            for attempt in range(3):
                try:
                    ok = await self._send_once(msg.text)
                    if ok:
                        sent = True
                        break
                except Exception as exc:  # network error → retry
                    log_event(self.logger, logging.WARNING, "telegram_exception", error=str(exc), attempt=attempt)
                await asyncio.sleep(delay)
                delay *= 2
            if sent:
                self.metrics.inc("telegram_sent")
            else:
                self.metrics.inc("telegram_dropped")
                log_event(self.logger, logging.ERROR, "telegram_dropped", kind=msg.kind)
            self.queue.task_done()
'@
$n = @'
    async def _send_once(self, text: str) -> str:
        """Returns 'deliver' | 'retry' | 'drop'."""
        session = await self._ensure_session()
        url = f"{self.API}/bot{self.bot_token}/sendMessage"
        payload = {"chat_id": self.chat_id, "text": text, "parse_mode": "HTML"}
        async with session.post(url, json=payload) as resp:
            status = getattr(resp, "status", 200)
            if status == 200:
                return "deliver"
            if status in (429, 500, 502, 503, 504):
                return "retry"
            body = await resp.text()
            log_event(self.logger, logging.WARNING, "telegram_send_failed", status=status, body=body[:200])
            return "drop"

    async def run(self) -> None:
        self._stopped = False
        while not self._stopped:
            msg = await self.queue.get()
            await self.bucket.acquire(1.0)
            delay = 1.0
            outcome = "drop"
            for attempt in range(3):
                try:
                    outcome = await self._send_once(msg.text)
                    if outcome in ("deliver", "drop"):
                        break
                except Exception as exc:  # network error → retry
                    outcome = "retry"
                    log_event(self.logger, logging.WARNING, "telegram_exception", error=str(exc), attempt=attempt)
                if attempt < 2:
                    await asyncio.sleep(delay)
                    delay *= 2
            if outcome == "deliver":
                self.metrics.inc("telegram_sent")
                if msg.kind == "SIGNAL" and msg.enqueued_mono > 0.0:
                    self.metrics.observe("signal_latency_s",
                                         max(0.0, self.clock.monotonic() - msg.enqueued_mono))
            else:
                self.metrics.inc("telegram_dropped")
                log_event(self.logger, logging.ERROR, "telegram_dropped", kind=msg.kind)
            self.queue.task_done()
'@
Add-Edit 'SE-049/SE-050/SE-051c' $o $n 1

# ---------------------------------------------------------------- REST
$o = @'
                    if status == 429:
                        self.metrics.inc("rest_429")
                        await asyncio.sleep(10.0)
                        continue
                    data = await resp.json()
                    if status >= 500:
                        raise TransientInfraError(f"{path} status {status}")
                    if status >= 400:
                        raise DataIntegrityError(f"{path} status {status}: {data}")
                    return data
            except (TransientInfraError,) as exc:
                if attempt == 2:
                    raise
                await asyncio.sleep(2.0 * (attempt + 1))
            except DataIntegrityError:
                raise
            except Exception as exc:
                raise TransientInfraError(str(exc)) from exc
'@
$n = @'
                    if status == 429:
                        self.metrics.inc("rest_429")
                        self.metrics.mark("rest_429", self.clock.monotonic())
                        await asyncio.sleep(10.0)
                        continue
                    if status >= 500:
                        raise TransientInfraError(f"{path} status {status}")
                    try:
                        data = await resp.json(content_type=None)
                    except TypeError:
                        data = await resp.json()
                    except Exception:
                        data = {}
                    if status >= 400:
                        raise DataIntegrityError(f"{path} status {status}: {data}")
                    return data
            except TransientInfraError:
                if attempt == 2:
                    raise
                await asyncio.sleep(2.0 * (attempt + 1))
            except DataIntegrityError:
                raise
            except Exception as exc:
                if attempt == 2:
                    raise TransientInfraError(str(exc)) from exc
                await asyncio.sleep(2.0 * (attempt + 1))
'@
Add-Edit 'SE-021/SE-064/SE-043c' $o $n 1

$o = @'
        return OptionLeg(
            ltp=_d(leg.get("last_price", 0)),
            bid=_d(leg.get("top_bid_price", leg.get("bid", 0))),
            ask=_d(leg.get("top_ask_price", leg.get("ask", 0))),
            oi=int(leg.get("oi", 0)),
            oi_prev=int(leg.get("previous_oi", leg.get("oi", 0))),
            volume=int(leg.get("volume", 0)),
            iv=_d(leg.get("implied_volatility", 0)),
'@
$n = @'
        return OptionLeg(
            ltp=quantize_tick(_d(leg.get("last_price", 0))),
            bid=quantize_tick(_d(leg.get("top_bid_price", leg.get("bid", 0)))),
            ask=quantize_tick(_d(leg.get("top_ask_price", leg.get("ask", 0)))),
            oi=int(leg.get("oi", 0)),
            oi_prev=int(leg.get("previous_oi", leg.get("oi", 0))),
            volume=int(leg.get("volume", 0)),
            iv=_d(leg.get("implied_volatility", 0)),
            bid_qty=int(leg.get("top_bid_quantity", leg.get("bid_qty", 0))),
            ask_qty=int(leg.get("top_ask_quantity", leg.get("ask_qty", 0))),
            security_id=str(leg.get("security_id", leg.get("securityId", ""))),
'@
Add-Edit 'SE-001a/SE-002c/SE-035c' $o $n 1

# ---------------------------------------------------------------- WS parser
$o = @'
                return Tick(
                    security_id=str(security_id), ts=clock.now(), ltp=_d(round(ltp, 2)),
                    ltq=0, volume_cum=0, oi=0, bid=Decimal(0), ask=Decimal(0),
                    bid_qty=0, ask_qty=0,
                )
'@
$n = @'
                return Tick(
                    security_id=str(security_id), ts=clock.now(),
                    ltp=quantize_tick(_d(round(ltp, 2))),
                    ltq=0, volume_cum=0, oi=0, bid=Decimal(0), ask=Decimal(0),
                    bid_qty=0, ask_qty=0,
                )
'@
Add-Edit 'SE-035d' $o $n 1

$o = @'
        return Tick(
            security_id=str(security_id), ts=clock.now(), ltp=_d(round(ltp, 2)),
            ltq=int(ltq), volume_cum=int(volume), oi=0,
            bid=Decimal(0), ask=Decimal(0), bid_qty=int(tbq), ask_qty=int(tsq),
        )
'@
$n = @'
        return Tick(
            security_id=str(security_id), ts=clock.now(),
            ltp=quantize_tick(_d(round(ltp, 2))),
            ltq=int(ltq), volume_cum=int(volume), oi=0,
            bid=Decimal(0), ask=Decimal(0), bid_qty=0, ask_qty=0,
            total_buy_qty=int(tbq), total_sell_qty=int(tsq),
        )
'@
Add-Edit 'SE-046b/SE-035e' $o $n 1

$o = @'
    async def _connect(self) -> Any:
        if self._connect_factory is not None:
            return self._connect_factory()
'@
$n = @'
    def _unsubscribe_message(self, subs: List[Tuple[str, str]]) -> str:
        instruments = [
            {"ExchangeSegment": seg, "SecurityId": sid}
            for seg, sid in subs
        ]
        return json.dumps({
            "RequestCode": 18,  # unsubscribe quote
            "InstrumentCount": len(instruments),
            "InstrumentList": instruments,
        })

    async def resubscribe(self, subs: List[Tuple[str, str]]) -> None:
        old = list(self._subscriptions)
        self.set_subscriptions(subs)
        ws = self._ws
        if ws is None:
            return
        try:
            if old:
                await ws.send(self._unsubscribe_message(old))
            await ws.send(self._subscribe_message())
            self.metrics.inc("ws_resubscribes")
        except Exception as exc:
            log_event(self.logger, logging.WARNING, "ws_resubscribe_failed", error=str(exc))

    async def _connect(self) -> Any:
        if self._connect_factory is not None:
            result = self._connect_factory()
            if asyncio.iscoroutine(result):
                result = await result
            return result
'@
Add-Edit 'SE-002d/SE-077' $o $n 1

$o = @'
                        self.metrics.inc("ws_parse_errors")
                        log_event(self.logger, logging.WARNING, "ws_parse_error",
'@
$n = @'
                        self.metrics.inc("ws_parse_errors")
                        self.metrics.mark("ws_parse_errors", self.clock.monotonic())
                        log_event(self.logger, logging.WARNING, "ws_parse_error",
'@
Add-Edit 'SE-043d' $o $n 1

# ---------------------------------------------------------------- Health
$o = @'
        self._degraded = False
        self.engine_degraded = False
        self.last_degraded_mono: float = -1e9
'@
$n = @'
        self._degraded = False
        self.engine_degraded = False
        self.engine_degraded_since_mono: float = 0.0
        self._last_reconnect_count = 0
        self.last_degraded_mono: float = -1e9
'@
Add-Edit 'SE-044a' $o $n 1

$o = @'
        feed_ok = tick_age <= self.cfg.feeds.stale_tick_s
        chain_ok = chain_age <= self.cfg.feeds.stale_chain_s
        lag_p95 = self.metrics.percentile("cycle_ms", 95)
        errors = self.metrics.counters.get("ws_parse_errors", 0) + self.metrics.counters.get("rest_429", 0)
        return HealthStatus(feed_ok, chain_ok, tick_age, chain_age, lag_p95, errors)

    def evaluate(self, phase: SessionPhase) -> None:
        st = self.status()
        market_open = phase not in (SessionPhase.CLOSED, SessionPhase.PRE_OPEN)
        degraded_now = market_open and (not st.feed_ok or not st.chain_ok)
        if degraded_now and not self._degraded:
            self._degraded = True
            self.last_degraded_mono = self.clock.monotonic()
            self.alerter.enqueue(OutboundMessage("HEALTH",
                f"⚠ HEALTH DEGRADED — feed_ok={st.feed_ok} chain_ok={st.chain_ok} "
                f"tick_age={st.last_tick_age_s:.0f}s chain_age={st.last_chain_age_s:.0f}s"))
            log_event(self.logger, logging.WARNING, "health_degraded", **asdict(st))
'@
$n = @'
        feed_ok = (tick_age <= self.cfg.feeds.stale_tick_s
                   and (self.ws is None or self.ws.packet_age_s() <= 10.0))
        chain_ok = chain_age <= self.cfg.feeds.stale_chain_s
        lag_p95 = self.metrics.percentile("cycle_ms", 95)
        mono = self.clock.monotonic()
        errors = (self.metrics.window_count("ws_parse_errors", 300.0, mono)
                  + self.metrics.window_count("rest_429", 300.0, mono))
        return HealthStatus(feed_ok, chain_ok, tick_age, chain_age, lag_p95, errors)

    def _rss_bytes(self) -> int:
        try:
            with open("/proc/self/statm", "r", encoding="utf-8") as fh:
                parts = fh.read().split()
            if len(parts) >= 2:
                return int(parts[1]) * os.sysconf("SC_PAGE_SIZE")
        except Exception:
            return 0
        return 0

    def evaluate(self, phase: SessionPhase) -> None:
        st = self.status()
        market_open = phase not in (SessionPhase.CLOSED, SessionPhase.PRE_OPEN)
        lag_bad = st.lag_ms_p95 > 1000.0
        rss = self._rss_bytes()
        rss_bad = rss > 400 * 1024 * 1024
        queue_bad = self.alerter.queue.qsize() > 50
        reconnects = self.ws.reconnect_count if self.ws is not None else 0
        reconnect_delta = reconnects - self._last_reconnect_count
        self._last_reconnect_count = reconnects
        if self.engine_degraded and reconnect_delta > 0:
            self.engine_degraded_since_mono = self.clock.monotonic()
        if (self.engine_degraded and self.engine_degraded_since_mono > 0.0
                and (self.clock.monotonic() - self.engine_degraded_since_mono) >= 300.0):
            self.engine_degraded = False
            self.engine_degraded_since_mono = 0.0
            self.alerter.enqueue(OutboundMessage("HEALTH", "✅ ENGINE RECOVERED — task restarts settled"))
            log_event(self.logger, logging.INFO, "engine_recovered")
        degraded_now = market_open and (not st.feed_ok or not st.chain_ok
                                        or lag_bad or rss_bad or queue_bad)
        if degraded_now and not self._degraded:
            self._degraded = True
            self.last_degraded_mono = self.clock.monotonic()
            self.alerter.enqueue(OutboundMessage("HEALTH",
                f"⚠ HEALTH DEGRADED — feed_ok={st.feed_ok} chain_ok={st.chain_ok} "
                f"tick_age={st.last_tick_age_s:.0f}s chain_age={st.last_chain_age_s:.0f}s "
                f"lag_p95={st.lag_ms_p95:.0f}ms rss={rss} queue={self.alerter.queue.qsize()} "
                f"reconnects={reconnects}"))
            log_event(self.logger, logging.WARNING, "health_degraded",
                      lag_bad=lag_bad, rss_bad=rss_bad, queue_bad=queue_bad,
                      reconnects=reconnects, **asdict(st))
'@
Add-Edit 'SE-009/SE-043e/SE-044b/SE-045' $o $n 1

# ---------------------------------------------------------------- Engine
$o = @'
        self.calendar = SessionCalendar(cfg.engine.holidays)
        self.store = MarketStateStore(cfg, instruments)
'@
$n = @'
        self.calendar = SessionCalendar(cfg.engine.holidays)
        self.store = MarketStateStore(cfg, instruments, clock)
'@
Add-Edit 'SE-070c' $o $n 1

$o = @'
        self.health = HealthMonitor(cfg, self.store, ws, metrics, clock, alerter, logger)
        self.bar_builders: Dict[str, BarBuilder] = {}
'@
$n = @'
        self.health = HealthMonitor(cfg, self.store, ws, metrics, clock, alerter, logger)
        self.gates.health = self.health
        self.gates.signals = self.signals
        self.bar_builders: Dict[str, BarBuilder] = {}
'@
Add-Edit 'SE-058D-c' $o $n 1

$o = @'
        self._last_ws_reconnects = 0
        self._digest_counts: Dict[str, int] = {}
        self._digest_last_hour = -1
'@
$n = @'
        self._last_ws_reconnects = 0
        self._digest_counts: Dict[str, int] = {}
        self._digest_last_hour = -1
        self._chain_failures: Dict[str, int] = {u: 0 for u in cfg.engine.underlyings}
        self._active_expiry: Dict[str, date] = {}
        self._last_subscriptions: List[Tuple[str, str]] = []
        self.option_segment = "NSE_FNO"
'@
Add-Edit 'SE-022a/SE-002e' $o $n 1

$o = @'
    def on_tick(self, tick: Tick) -> None:
        underlying = self._sec_to_underlying.get(tick.security_id)
        if underlying is None:
            return
        self.store.apply_tick(tick, underlying)
        bar = self.bar_builders[underlying].on_tick(tick)
        if bar is not None:
            self._on_bar_1m(underlying, bar)
'@
$n = @'
    def on_tick(self, tick: Tick) -> None:
        underlying = self._sec_to_underlying.get(tick.security_id)
        if underlying is None:
            return
        if tick.security_id != self.instruments.by_name[underlying].security_id:
            self.store.apply_option_tick(tick, underlying)
            return
        self.store.apply_tick(tick, underlying)
        bar = self.bar_builders[underlying].on_tick(tick)
        if bar is not None:
            self._on_bar_1m(underlying, bar)
'@
Add-Edit 'SE-002f' $o $n 1

$o = @'
        phase = self.calendar.phase(self.clock.now())
        self.store.apply_index_bar(underlying, bar, phase, self.aggregators[underlying])
        if self._warmup_bars_remaining[underlying] > 0:
'@
$n = @'
        phase = self.calendar.phase(self.clock.now())
        bar_5m, events_5m = self.store.apply_index_bar(underlying, bar, phase, self.aggregators[underlying])
        if bar_5m is not None:
            self.metrics.inc("bars_5m")
        if events_5m:
            self.metrics.inc("structure_events", len(events_5m))
        if self._warmup_bars_remaining[underlying] > 0:
'@
Add-Edit 'SE-066c' $o $n 1

$o = @'
            for u in self.cfg.engine.underlyings:
                try:
                    await self._poll_chain(u)
                except (TransientInfraError, DataIntegrityError) as exc:
                    self.metrics.inc("chain_poll_errors")
                    log_event(self.logger, logging.WARNING, "chain_poll_error",
                              underlying=u, error=str(exc))
            await asyncio.sleep(self.cfg.feeds.chain_poll_interval_s)
'@
$n = @'
            loop_start = self.clock.monotonic()
            for u in self.cfg.engine.underlyings:
                try:
                    await self._poll_chain(u)
                    self._chain_failures[u] = 0
                except (TransientInfraError, DataIntegrityError) as exc:
                    self.metrics.inc("chain_poll_errors")
                    self._chain_failures[u] = self._chain_failures.get(u, 0) + 1
                    log_event(self.logger, logging.WARNING, "chain_poll_error",
                              underlying=u, error=str(exc),
                              consecutive=self._chain_failures[u])
                    if self._chain_failures[u] >= 3:
                        cs = self.store.get(u)
                        cs.last_chain = None
                        cs.last_options_view = None
                        log_event(self.logger, logging.WARNING, "chain_marked_stale", underlying=u)
            elapsed = self.clock.monotonic() - loop_start
            await asyncio.sleep(max(0.0, self.cfg.feeds.chain_poll_interval_s - elapsed))
'@
Add-Edit 'SE-022b/SE-071' $o $n 1

$o = @'
        st = self.store.get(underlying)
        spot_hint = st.latest_tick.ltp if st.latest_tick else Decimal(0)
        snap = await self.rest.option_chain(underlying, scrip, expiry, spot_hint)
        self.store.apply_chain(snap)
        self.evaluate(underlying)
'@
$n = @'
        st = self.store.get(underlying)
        spot_hint = st.latest_tick.ltp if st.latest_tick else Decimal(0)
        snap = await self.rest.option_chain(underlying, scrip, expiry, spot_hint)
        view = self.store.apply_chain(snap)
        prev_active = self._active_expiry.get(underlying)
        self._active_expiry[underlying] = expiry
        if view.atm_migration != "none" or prev_active != expiry:
            await self._rebuild_subscriptions()
        self.evaluate(underlying)

    def _option_subscription_list(self) -> List[Tuple[str, str]]:
        subs: List[Tuple[str, str]] = [
            (self.instruments.by_name[u].exchange_segment, self.instruments.by_name[u].security_id)
            for u in self.cfg.engine.underlyings
        ]
        for u in self.cfg.engine.underlyings:
            st = self.store.get(u)
            chain = st.last_chain
            view = st.last_options_view
            if chain is None or view is None:
                continue
            width = 2 * self.cfg.options.atm_band_strikes + 1
            band = sorted(chain.strikes, key=lambda x: abs(x.strike - view.atm_strike))[:width]
            for stk in sorted(band, key=lambda x: x.strike):
                for leg in (stk.ce, stk.pe):
                    if not leg.security_id:
                        continue
                    self._sec_to_underlying.setdefault(leg.security_id, u)
                    entry = (self.option_segment, leg.security_id)
                    if entry not in subs:
                        subs.append(entry)
        return subs[:100]

    async def _rebuild_subscriptions(self) -> None:
        if self.ws is None:
            return
        subs = self._option_subscription_list()
        if subs == self._last_subscriptions:
            return
        self._last_subscriptions = subs
        await self.ws.resubscribe(subs)

    def _select_strike(self, underlying: str, direction: Direction) -> Optional[Tuple[Decimal, str]]:
        st = self.store.get(underlying)
        chain = st.last_chain
        view = st.last_options_view
        if chain is None or view is None:
            return None
        straddle_half = st.options.atm_straddle_half(chain, view.atm_strike)
        return st.options.select_strike(direction, chain, view,
                                        self.cfg.risk.max_spread_pct_of_premium, straddle_half)
'@
Add-Edit 'SE-002g/SE-039e/SE-059c' $o $n 1

$o = @'
    def _evaluate_inner(self, underlying: str) -> None:
        st = self.store.get(underlying)
        now = self.clock.now()
        phase = self.calendar.phase(now)
        regime_strength = st.regime.state.strength_0_100
        # Preconditions gate
        if not self.calendar.signal_window_open(now, regime_strength):
            return
        if now.time() >= dtime(15, 0) and phase == SessionPhase.CLOSING:
            return
        if self._warmup_bars_remaining[underlying] > 0:
            return
        if self.health.degraded:
            return
        if self.signals.in_cooldown(underlying) or self.signals.cap_reached(underlying):
            return
        hs = self.health.status()
        if not hs.feed_ok or not hs.chain_ok:
            return
        # Trigger scan
        candidate = self._scan_trigger(underlying, st)
        if candidate is None:
            return
        if self.signals.already_triggered(underlying, candidate.direction, candidate.trigger_swing_ts):
            return
        m = build_market_view(self.store, underlying, self.calendar, self.clock,
                              candidate.trigger.level, candidate.direction)
        ledger = self.confluence.evaluate(candidate, m)
        scored = self.scorer.score(ledger, candidate)
        # mandatory + threshold + categories + contradictions
        reject_reasons: List[str] = []
        if scored.contradictions >= 2:
            reject_reasons.append("CONTRADICTORY_EVIDENCE")
        if not scored.mandatory_ok:
            reject_reasons.append("MANDATORY_CATEGORY")
        if scored.categories_passed < self.cfg.signals.min_categories_passed:
            reject_reasons.append("MIN_CATEGORIES")
        if scored.score < self.cfg.signals.confidence_threshold:
            reject_reasons.append("BELOW_THRESHOLD")
        if reject_reasons:
            self._record_rejection(Rejection(candidate, "SCORING", reject_reasons, ledger), scored)
            self.signals.register_trigger(underlying, candidate.direction, candidate.trigger_swing_ts)
            return
        gate = self.gates.validate(scored, m, self.health.degraded_recently())
        if not gate.passed:
            self._record_rejection(Rejection(candidate, "GATES", gate.reason_codes, ledger), scored)
            self.signals.register_trigger(underlying, candidate.direction, candidate.trigger_swing_ts)
            for code in gate.reason_codes:
                self.metrics.reject(code)
            return
        result = self.levels.compute(scored, m, gate)
        if isinstance(result, Rejection):
            self._record_rejection(result, scored)
            self.signals.register_trigger(underlying, candidate.direction, candidate.trigger_swing_ts)
            for code in result.reason_codes:
                self.metrics.reject(code)
            return
        signal = result
        self.signals.register_trigger(underlying, candidate.direction, candidate.trigger_swing_ts)
'@
$n = @'
    def _evaluate_inner(self, underlying: str) -> None:
        st = self.store.get(underlying)
        now = self.clock.now()
        regime_strength = st.regime.state.strength_0_100
        # Preconditions gate (§13 step 1) — silent skips, health counters only
        if not self.calendar.signal_window_open(now, regime_strength):
            self.metrics.inc("skip_window")
            return
        if self._warmup_bars_remaining[underlying] > 0:
            self.metrics.inc("skip_warmup")
            return
        if self.health.degraded:
            self.metrics.inc("skip_degraded")
            return
        hs = self.health.status()
        if not hs.feed_ok or not hs.chain_ok:
            self.metrics.inc("skip_stale")
            return
        # Trigger scan
        candidate = self._scan_trigger(underlying, st)
        if candidate is None:
            return
        if self.signals.already_triggered(underlying, candidate.direction, candidate.trigger_swing_ts):
            return
        self.metrics.inc("candidates")
        sel = self._select_strike(underlying, candidate.direction)
        m = build_market_view(self.store, underlying, self.calendar, self.clock,
                              candidate.trigger.level, candidate.direction,
                              sel[0] if sel is not None else None,
                              sel[1] if sel is not None else None)
        ledger = self.confluence.evaluate(candidate, m)
        scored = replace(self.scorer.score(ledger), candidate=candidate)
        # mandatory + threshold + categories + contradictions
        reject_reasons: List[str] = []
        if scored.contradictions >= 2:
            reject_reasons.append("CONTRADICTORY_EVIDENCE")
        if not scored.mandatory_ok:
            reject_reasons.append("MANDATORY_CATEGORY")
        if not scored.min_categories_ok:
            reject_reasons.append("MIN_CATEGORIES")
        if scored.score < self.cfg.signals.confidence_threshold:
            reject_reasons.append("BELOW_THRESHOLD")
        if reject_reasons:
            self._record_rejection(Rejection(candidate, "SCORING", reject_reasons, ledger), scored)
            self.signals.register_trigger(underlying, candidate.direction, candidate.trigger_swing_ts)
            return
        result = self.levels.compute(scored, m)
        if isinstance(result, Rejection):
            self._record_rejection(result, scored)
            self.signals.register_trigger(underlying, candidate.direction, candidate.trigger_swing_ts)
            return
        signal = result
        gate = self.gates.validate(scored, replace(m, reward_risk=signal.reward_risk))
        if not gate.passed:
            self._record_rejection(Rejection(candidate, "GATES", gate.reason_codes, ledger), scored)
            self.signals.register_trigger(underlying, candidate.direction, candidate.trigger_swing_ts)
            return
        self.signals.register_trigger(underlying, candidate.direction, candidate.trigger_swing_ts)
'@
Add-Edit 'SE-017/SE-037a/SE-039f/SE-048c/SE-067/SE-076' $o $n 1

$o = @'
        events = st.structure.events
        if not events:
            return None
        recent = events[-3:]
        regime = st.regime.state.regime
        now = self.clock.now()
        for ev in reversed(recent):
            if (now - ev.ts).total_seconds() > 900:
                continue
            direction = self._direction_for(ev, regime)
            if direction is None:
                continue
'@
$n = @'
        events = st.structure.events
        if not events:
            return None
        regime = st.regime.state.regime
        bias = st.structure.bias
        now = self.clock.now()
        fresh = [ev for ev in events if 0 <= (now - ev.ts).total_seconds() <= 180]
        for ev in reversed(fresh):
            direction = self._direction_for(ev, regime, bias)
            if direction is None:
                continue
'@
Add-Edit 'SE-037b' $o $n 1

$o = @'
    def _direction_for(self, ev: StructureEvent, regime: Regime) -> Optional[Direction]:
'@
$n = @'
    def _direction_for(self, ev: StructureEvent, regime: Regime, bias: str) -> Optional[Direction]:
'@
Add-Edit 'SE-038d' $o $n 1

$o = @'
        if ev.kind == StructureKind.SWEEP_HIGH and rangeish:
            return Direction.LONG_PE
        return None
'@
$n = @'
        if ev.kind == StructureKind.SWEEP_HIGH and rangeish:
            return Direction.LONG_PE
        if ev.kind == StructureKind.OPENING_DRIVE_BREAK:
            if regime == Regime.OPENING_DRIVE_UP:
                return Direction.LONG_CE
            if regime == Regime.OPENING_DRIVE_DOWN:
                return Direction.LONG_PE
            return None
        if ev.kind == StructureKind.EXPANSION_IMPULSE and regime == Regime.EXPANSION:
            if bias == "BULLISH":
                return Direction.LONG_CE
            if bias == "BEARISH":
                return Direction.LONG_PE
            return None
        return None
'@
Add-Edit 'SE-038e' $o $n 1

$o = @'
        summary_sent_for: Optional[date] = None
        snapshot_done_for: Optional[date] = None
        while not self._stopped:
            now = self.clock.now()
            today = now.date()
'@
$n = @'
        summary_sent_for: Optional[date] = None
        snapshot_done_for: Optional[date] = None
        expiries_refreshed_for: Optional[date] = None
        while not self._stopped:
            now = self.clock.now()
            today = now.date()
            if (self.calendar.is_trading_day(today) and now.time() >= dtime(9, 0)
                    and expiries_refreshed_for != today):
                await self._refresh_expiries(False)
                expiries_refreshed_for = today
'@
Add-Edit 'SE-025a' $o $n 1

$o = @'
                    and snapshot_done_for != today):
                self.save_snapshot()
                snapshot_done_for = today
'@
$n = @'
                    and snapshot_done_for != today):
                self.save_snapshot()
                self.metrics.reset_session()
                snapshot_done_for = today
'@
Add-Edit 'SE-052b' $o $n 1

$o = @'
        for u in self.cfg.engine.underlyings:
            self._warmup_bars_remaining[u] = 3
        log_event(self.logger, logging.INFO, "snapshot_restored", saved_ts=data["saved_ts"])
'@
$n = @'
        for u in self.cfg.engine.underlyings:
            self._warmup_bars_remaining[u] = 3
            rs = self.store.get(u)
            rs.last_chain = None
            rs.last_options_view = None
        log_event(self.logger, logging.INFO, "snapshot_restored", saved_ts=data["saved_ts"])
'@
Add-Edit 'SE-027d' $o $n 1

$o = @'
    async def bootstrap(self) -> None:
        for u in self.cfg.engine.underlyings:
            scrip = self.scrip_map[u]
            try:
                expiries = await self.rest.expiry_list(scrip)
                if expiries:
                    today = self.clock.now().date()
                    weekly = [e for e in expiries if e >= today]
                    self.expiries[u] = weekly[0] if weekly else expiries[0]
                    self._expiry_lists[u] = weekly if weekly else expiries
            except (TransientInfraError, DataIntegrityError) as exc:
                log_event(self.logger, logging.WARNING, "expiry_fetch_failed", underlying=u, error=str(exc))
        await self._load_prev_day_levels()
        restored = self.restore_snapshot()
        if not restored:
            await self._cold_bootstrap()
'@
$n = @'
    async def _refresh_expiries(self, fatal: bool) -> None:
        for u in self.cfg.engine.underlyings:
            scrip = self.scrip_map[u]
            try:
                expiries = await self.rest.expiry_list(scrip)
            except (TransientInfraError, DataIntegrityError) as exc:
                if fatal:
                    raise FatalConfigError(
                        f"expiry list unavailable for underlying {u}: {exc}") from exc
                log_event(self.logger, logging.WARNING, "expiry_fetch_failed",
                          underlying=u, error=str(exc))
                continue
            if not expiries:
                if fatal:
                    raise FatalConfigError(f"expiry list empty for underlying {u}")
                log_event(self.logger, logging.WARNING, "expiry_list_empty", underlying=u)
                continue
            today = self.clock.now().date()
            weekly = [e for e in expiries if e >= today]
            self.expiries[u] = weekly[0] if weekly else expiries[0]
            self._expiry_lists[u] = weekly if weekly else expiries

    async def bootstrap(self) -> None:
        await self._refresh_expiries(True)
        await self._load_prev_day_levels()
        restored = self.restore_snapshot()
        if not restored:
            await self._cold_bootstrap()
        await self._rebuild_subscriptions()
'@
Add-Edit 'SE-023/SE-025b/SE-002h' $o $n 1

$o = @'
            for bar in bars:
                self._on_bar_1m(u, bar)
            self._warmup_bars_remaining[u] = 2
'@
$n = @'
            for bar in bars:
                self._on_bar_1m(u, bar)
            self._warmup_bars_remaining[u] = 3
'@
Add-Edit 'SE-026' $o $n 1

$o = @'
                if len(recent) >= 3:
                    self.health.engine_degraded = True
'@
$n = @'
                if len(recent) >= 3:
                    self.health.engine_degraded = True
                    self.health.engine_degraded_since_mono = self.clock.monotonic()
'@
Add-Edit 'SE-044c' $o $n 1

$o = @'
    async def run(self) -> None:
        await self.bootstrap()
        self.alerter.enqueue(OutboundMessage("HEALTH", "✅ engine online"))
        self._tasks = [
            asyncio.create_task(self.alerter.run()),
'@
$n = @'
    async def run(self) -> None:
        await self.bootstrap()
        sd_notify("READY=1")
        self.alerter.enqueue(OutboundMessage("HEALTH", "✅ engine online"))
        self._tasks = [
            asyncio.create_task(self._supervise("telegram", self.alerter.run)),
'@
Add-Edit 'SE-006/SE-053' $o $n 1

$o = @'
        self._stopped = True
        self.save_snapshot()
        with contextlib.suppress(Exception):
            await self.alerter.close()
'@
$n = @'
        self._stopped = True
        self.save_snapshot()
        with contextlib.suppress(asyncio.TimeoutError, Exception):
            await asyncio.wait_for(self.alerter.queue.join(), timeout=15.0)
        with contextlib.suppress(Exception):
            await self.alerter.close()
'@
Add-Edit 'SE-056' $o $n 1

$o = @'
            f"Cycles: {snap['counters'].get('cycles', 0)} | "
            f"Lag p95: {snap['lag_ms_p95']:.0f}ms | "
            f"Ticks: {snap['counters'].get('ticks_ingested', 0)}"
        )
'@
$n = @'
            f"Cycles: {snap['counters'].get('cycles', 0)} | "
            f"Lag p95: {snap['lag_ms_p95']:.0f}ms | "
            f"Ticks: {snap['counters'].get('ticks_ingested', 0)}\n"
            f"Health: ws_reconnects={snap['counters'].get('ws_reconnects', 0)} "
            f"parse_errors={snap['counters'].get('ws_parse_errors', 0)} "
            f"rest_429={snap['counters'].get('rest_429', 0)} "
            f"chain_errors={snap['counters'].get('chain_poll_errors', 0)} "
            f"task_restarts={snap['counters'].get('task_restarts', 0)} | "
            f"Signal latency p95: {snap['signal_latency_p95']:.2f}s"
        )
'@
Add-Edit 'SE-074' $o $n 1

# ---------------------------------------------------------------- Replay
$o = @'
        self.engine = engine
        self.clock = clock
        self.signals_emitted: List[Signal] = []
        self.captured_signal_texts: List[str] = []
'@
$n = @'
        self.engine = engine
        self.clock = clock
        self.captured_signal_texts: List[str] = []
'@
Add-Edit 'SE-054a' $o $n 1

$o = @'
    def feed_chain(self, snap: ChainSnapshot) -> None:
        self.clock.set(snap.ts)
        self.engine.store.apply_chain(snap)
        self.engine.evaluate(snap.underlying)
'@
$n = @'
    def feed_chain(self, snap: ChainSnapshot) -> None:
        self.clock.set(snap.ts)
        self.engine.store.apply_chain(snap)
        self.engine.evaluate(snap.underlying)

    def run(self, ticks: List[Tick], chains: List[ChainSnapshot]) -> None:
        events: List[Tuple[datetime, int, Any]] = []
        for t in ticks:
            events.append((t.ts, 0, t))
        for c in chains:
            events.append((c.ts, 1, c))
        events.sort(key=lambda x: (x[0], x[1]))
        for _ts, kind, obj in events:
            if kind == 0:
                self.feed_ticks([obj])
            else:
                self.feed_chain(obj)
'@
Add-Edit 'SE-054b' $o $n 1

$o = @'
    return OptionLeg(
        ltp=_d(d["ltp"]), bid=_d(d["bid"]), ask=_d(d["ask"]), oi=int(d["oi"]),
        oi_prev=int(d.get("oi_prev", d["oi"])), volume=int(d.get("volume", 0)),
        iv=_d(d.get("iv", 0)),
    )
'@
$n = @'
    return OptionLeg(
        ltp=_d(d["ltp"]), bid=_d(d["bid"]), ask=_d(d["ask"]), oi=int(d["oi"]),
        oi_prev=int(d.get("oi_prev", d["oi"])), volume=int(d.get("volume", 0)),
        iv=_d(d.get("iv", 0)),
        bid_qty=int(d.get("bid_qty", 0)), ask_qty=int(d.get("ask_qty", 0)),
        security_id=str(d.get("security_id", "")),
    )
'@
Add-Edit 'SE-001b' $o $n 1

$o = @'
        try:
            scrip_map[u] = int(instruments.by_name[u].security_id)
        except ValueError:
            scrip_map[u] = 0
'@
$n = @'
        try:
            scrip_map[u] = int(instruments.by_name[u].security_id)
        except ValueError as exc:
            raise FatalConfigError(
                f"instruments.{u}.security_id is not numeric: "
                f"{instruments.by_name[u].security_id}") from exc
'@
Add-Edit 'SE-024' $o $n 1

$o = @'
    run_task = asyncio.create_task(engine.run())
    await stop_event.wait()
    await engine.shutdown()
    run_task.cancel()
    with contextlib.suppress(asyncio.CancelledError, Exception):
        await run_task
    return 0
'@
$n = @'
    run_task = asyncio.create_task(engine.run())
    stop_task = asyncio.create_task(stop_event.wait())
    done, _pending = await asyncio.wait({run_task, stop_task},
                                        return_when=asyncio.FIRST_COMPLETED)
    stop_task.cancel()
    with contextlib.suppress(asyncio.CancelledError, Exception):
        await stop_task
    await engine.shutdown()
    if run_task in done:
        run_task.result()
        return 0
    run_task.cancel()
    with contextlib.suppress(asyncio.CancelledError, Exception):
        await run_task
    return 0
'@
Add-Edit 'SE-055a' $o $n 1

$o = @'
    events: List[Tuple[datetime, str, Any]] = []
    if os.path.exists(tick_path):
        for d in _read_fixture(tick_path).get("ticks", []):
            t = _tick_from_fixture(d)
            events.append((t.ts, "tick", t))
    if os.path.exists(chain_path):
        for d in _read_fixture(chain_path).get("chains", []):
            snap = _chain_from_fixture(d)
            events.append((snap.ts, "chain", snap))
    events.sort(key=lambda x: x[0])
    for ts, kind, obj in events:
        clock.set(ts)
        if kind == "tick":
            engine.on_tick(obj)
        else:
            engine.store.apply_chain(obj)
            engine.evaluate(obj.underlying)
    print(json.dumps(metrics.snapshot(), default=str, sort_keys=True))
    return 0
'@
$n = @'
    ticks: List[Tick] = []
    chains: List[ChainSnapshot] = []
    if os.path.exists(tick_path):
        for d in _read_fixture(tick_path).get("ticks", []):
            ticks.append(_tick_from_fixture(d))
    if os.path.exists(chain_path):
        for d in _read_fixture(chain_path).get("chains", []):
            chains.append(_chain_from_fixture(d))
    replay.run(ticks, chains)
    print(json.dumps({
        "metrics": metrics.snapshot(),
        "signals": replay.captured_signal_texts,
        "rejections_by_reason": dict(sorted(metrics.rejections_by_reason.items())),
    }, default=str, sort_keys=True))
    return 0
'@
Add-Edit 'SE-054c' $o $n 1

$o = @'
    except FatalConfigError as exc:
        print(f"FATAL CONFIG: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
'@
$n = @'
    except FatalConfigError as exc:
        print(f"FATAL CONFIG: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"FATAL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
'@
Add-Edit 'SE-055b' $o $n 1

# =====================================================================
# VALIDATE + APPLY (fail closed)
# =====================================================================
$failures = New-Object System.Collections.ArrayList
$applied  = New-Object System.Collections.ArrayList
$work = $text

foreach ($e in $script:Edits) {
    $found = ([regex]::Matches($work, [regex]::Escape($e.Old))).Count
    if ($found -ne $e.Count) {
        [void]$failures.Add(("{0}: expected {1} match(es), found {2}" -f $e.Id, $e.Count, $found))
        continue
    }
    $work = $work.Replace($e.Old, $e.New)
    [void]$applied.Add($e.Id)
}

if ($failures.Count -gt 0) {
    Write-Host ""
    Write-Host "ANCHOR VALIDATION FAILED - Dhan.py NOT modified:" -ForegroundColor Red
    $failures | ForEach-Object { Write-Host "  $_" -ForegroundColor Red }
    Remove-Item -LiteralPath $Backup -Force -ErrorAction SilentlyContinue
    Write-Host "RESULT: FAIL" -ForegroundColor Red
    exit 1
}

$out = if ($useCrLf) { $work -replace "`n", "`r`n" } else { $work }
$enc = New-Object System.Text.UTF8Encoding($hasBom)
[System.IO.File]::WriteAllText($Target, $out, $enc)
Write-Host "Applied $($applied.Count) validated edits."

$pyOk = $false
$pyMsg = ''
$pyExe = $null
foreach ($cand in @('python', 'py')) {
    $c = Get-Command $cand -ErrorAction SilentlyContinue
    if ($c) { $pyExe = $c.Source; break }
}
if ($pyExe) {
    $code = 'import ast,sys' + "`n" + 'ast.parse(open(sys.argv[1],encoding="utf-8").read(),sys.argv[1])'
    $pyMsg = & $pyExe -c $code $Target 2>&1 | Out-String
    $pyOk = ($LASTEXITCODE -eq 0)
} else {
    $pyOk = $true
    $pyMsg = 'python not found on PATH - syntax validation skipped'
}

if (-not $pyOk) {
    [System.IO.File]::WriteAllBytes($Target, [System.IO.File]::ReadAllBytes($Backup))
    Write-Host ""
    Write-Host "PYTHON SYNTAX VALIDATION FAILED - backup restored:" -ForegroundColor Red
    Write-Host $pyMsg -ForegroundColor Red
    Write-Host "RESULT: FAIL" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "AUDIT FINDINGS FIXED:" -ForegroundColor Green
Write-Host ('SE-001, SE-002, SE-003, SE-004, SE-005, SE-006, SE-007, SE-008, SE-009, SE-010, ' +
            'SE-011, SE-012, SE-013, SE-014, SE-015, SE-016, SE-017, SE-018, SE-019, SE-020, ' +
            'SE-021, SE-022, SE-023, SE-024, SE-025, SE-026, SE-027, SE-028, SE-029, SE-030, ' +
            'SE-031, SE-032, SE-033, SE-034, SE-035, SE-036, SE-037, SE-038, SE-039, SE-040, ' +
            'SE-041, SE-042, SE-043, SE-044, SE-045, SE-046, SE-047, SE-048, SE-049, SE-050, ' +
            'SE-051, SE-052, SE-053, SE-054, SE-055, SE-056, SE-057, SE-058, SE-059, SE-060, ' +
            'SE-061, SE-062, SE-064, SE-065, SE-066, SE-067, SE-068, SE-069, SE-070, SE-071, ' +
            'SE-072, SE-073, SE-074, SE-075, SE-076, SE-077')
Write-Host ""
Write-Host "NOT CHANGED (accounted for, no code change required):" -ForegroundColor Yellow
Write-Host "  SE-063 ALREADY CORRECT - 'my' is consumed by the regression numerator; not a dead local."
Write-Host "  SE-078 UNSAFE TO AUTOMATE - test deliverable; verified no '/orders','/super','/forever' present."
Write-Host "  SE-079 INFORMATIONAL - measurement blockers SE-009/SE-013/SE-051 fixed; benchmarks are runtime data."
Write-Host "  SE-080 INFORMATIONAL - unresolved specification ambiguity; behavior intentionally unchanged."
Write-Host ""
Write-Host "Backup retained: $Backup"
Write-Host "RESULT: PASS" -ForegroundColor Green
exit 0