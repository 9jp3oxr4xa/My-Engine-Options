from __future__ import annotations

# ============================================================
# Indian Index Options Signal Engine â€” monolithic implementation
#
# Layering (enforced by section order and import discipline):
#   infra   : clock, ratelimit, telegram, dhan_rest, dhan_ws, persistence
#   domain  : models, state, bars, vwap, volume, volatility,
#             structure, regime, options_intel
#   decision: confluence, confidence, risk_gates, levels, signal_manager
#   runtime : health, __main__ wiring
#
# Data flows one direction; decisions flow one direction.
# Nothing in `decision` is imported by `domain`; nothing in `domain`
# is imported by `infra`.
# ============================================================

import argparse
import asyncio
import contextlib
import hashlib
import json
import logging
import logging.handlers
import os
import re
import signal as _signal
import statistics
import struct
import sys
import time

try:  # Task-1 forensic layer: diagnostic only, inert unless DHAN_FORENSICS=1
    import forensics as _FX
except Exception:  # diagnostics must never be able to break trading
    class _FXStub:
        def __getattr__(self, _name):
            return lambda *a, **kw: None
    _FX = _FXStub()

from collections import deque
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime, time as dtime, timedelta
from decimal import Decimal, ROUND_HALF_UP, getcontext
from enum import Enum
from typing import (
    Any,
    Callable,
    Deque,
    Dict,
    List,
    Optional,
    Sequence,
    Tuple,
)
from zoneinfo import ZoneInfo
from nse_chain_adapter import NSEChainAdapter
from nse_option_provider import NSEOptionChainProvider
from nse_option_provider import NSEOptionChainProvider, NSEChainSnapshot

from fyers_apiv3.FyersWebsocket import data_ws as fyers_data_ws

getcontext().prec = 28

IST = ZoneInfo("Asia/Kolkata")
SCHEMA_VERSION = 1

# ============================================================
# SECTION: numeric helpers
# ============================================================


def _d(value: Any) -> Decimal:
    """Coerce to Decimal deterministically via string form."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        return Decimal(repr(value))
    return Decimal(str(value))


def quantize_tick(price: Decimal, tick: Decimal = Decimal("0.05")) -> Decimal:
    """Quantize a price to the given tick size, half-up."""
    if tick <= 0:
        return price
    steps = (price / tick).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return (steps * tick).quantize(tick)


def _median(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    return float(statistics.median(values))


def _pct_rank(value: float, population: Sequence[float]) -> float:
    """Percentile rank (0-100) of value within population."""
    if not population:
        return 50.0
    below = sum(1 for p in population if p < value)
    equal = sum(1 for p in population if p == value)
    return 100.0 * (below + 0.5 * equal) / len(population)


# ============================================================
# SECTION: domain/models.py  (Â§4)
# ============================================================


class SwingKind(str, Enum):
    HIGH = "HIGH"
    LOW = "LOW"


class StructureKind(str, Enum):
    BOS_UP = "BOS_UP"
    BOS_DOWN = "BOS_DOWN"
    CHOCH_UP = "CHOCH_UP"
    CHOCH_DOWN = "CHOCH_DOWN"
    SWEEP_HIGH = "SWEEP_HIGH"
    SWEEP_LOW = "SWEEP_LOW"
    RETEST_OK = "RETEST_OK"
    RETEST_FAIL = "RETEST_FAIL"
    OPENING_DRIVE_BREAK = "OPENING_DRIVE_BREAK"
    EXPANSION_IMPULSE = "EXPANSION_IMPULSE"


class Regime(str, Enum):
    TREND_UP = "TREND_UP"
    TREND_DOWN = "TREND_DOWN"
    RANGE = "RANGE"
    OPENING_DRIVE_UP = "OPENING_DRIVE_UP"
    OPENING_DRIVE_DOWN = "OPENING_DRIVE_DOWN"
    OPENING_REVERSAL = "OPENING_REVERSAL"
    COMPRESSION = "COMPRESSION"
    EXPANSION = "EXPANSION"
    UNKNOWN = "UNKNOWN"


class EvidenceOutcome(str, Enum):
    TRUE = "true"
    FALSE = "false"
    NEUTRAL = "neutral"


class Direction(str, Enum):
    LONG_CE = "LONG_CE"
    LONG_PE = "LONG_PE"


class SessionPhase(str, Enum):
    PRE_OPEN = "PRE_OPEN"
    OPENING = "OPENING"
    MORNING = "MORNING"
    MIDDAY = "MIDDAY"
    AFTERNOON = "AFTERNOON"
    CLOSING = "CLOSING"
    CLOSED = "CLOSED"


@dataclass(frozen=True, slots=True)
class Tick:
    security_id: str
    ts: datetime
    ltp: Decimal
    ltq: int
    volume_cum: int
    oi: int
    bid: Decimal
    ask: Decimal
    bid_qty: int
    ask_qty: int
    total_buy_qty: int = 0
    total_sell_qty: int = 0

    def __post_init__(self) -> None:
        if self.ts.tzinfo is None:
            raise ValueError("Tick.ts must be timezone-aware")


@dataclass(frozen=True, slots=True)
class Bar:
    ts_open: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    tick_count: int
    volume_suspect: bool = False

    def __post_init__(self) -> None:
        if self.ts_open.tzinfo is None:
            raise ValueError("Bar.ts_open must be timezone-aware")

    @property
    def typical(self) -> Decimal:
        return (self.high + self.low + self.close) / Decimal(3)

    @property
    def range(self) -> Decimal:
        return self.high - self.low


@dataclass(frozen=True, slots=True)
class Swing:
    kind: SwingKind
    price: Decimal
    ts: datetime
    bar_index: int
    confirmed: bool = True


@dataclass(frozen=True, slots=True)
class StructureEvent:
    kind: StructureKind
    level: Decimal
    ts: datetime
    ref_swing: Optional[Swing] = None


@dataclass(frozen=True, slots=True)
class RegimeState:
    regime: Regime
    since_ts: datetime
    strength_0_100: int


@dataclass(frozen=True, slots=True)
class OptionLeg:
    ltp: Decimal
    bid: Decimal
    ask: Decimal
    oi: int
    oi_prev: int
    volume: int
    iv: Decimal
    bid_qty: int = 0
    ask_qty: int = 0
    security_id: str = ""
    delta: Optional[Decimal] = None



@dataclass(frozen=True, slots=True)
class ChainStrike:
    strike: Decimal
    ce: OptionLeg
    pe: OptionLeg


@dataclass(frozen=True, slots=True)
class ChainSnapshot:
    underlying: str
    expiry: date
    spot: Decimal
    ts: datetime
    strikes: List[ChainStrike]
    atm_strike: Decimal


@dataclass(frozen=True, slots=True)
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


@dataclass(frozen=True, slots=True)
class CandidateSignal:
    direction: Direction
    underlying: str
    trigger: StructureEvent
    ts: datetime
    trigger_swing_ts: datetime


@dataclass(frozen=True, slots=True)
class Level:
    price: Decimal
    source: str
    strength: int


@dataclass(frozen=True, slots=True)
class Signal:
    id: str
    ts: datetime
    underlying: str
    direction: Direction
    strike: Decimal
    expiry: date
    option_entry: Decimal
    option_stop: Decimal
    targets: Tuple[Decimal, Decimal]
    spot_ref: Decimal
    spot_stop: Decimal
    confidence: int
    regime: Regime
    regime_strength: int
    evidence_ledger: List[Evidence]
    invalidation_text: str
    reward_risk: Decimal
    band: str
    entry_max: Decimal


@dataclass(frozen=True, slots=True)
class Rejection:
    candidate: CandidateSignal
    stage: str
    reason_codes: List[str]
    ledger: List[Evidence]


@dataclass(frozen=True, slots=True)
class HealthStatus:
    feed_ok: bool
    chain_ok: bool
    last_tick_age_s: float
    last_chain_age_s: float
    lag_ms_p95: float
    errors_5m: int


@dataclass(frozen=True, slots=True)
class ScoredCandidate:
    candidate: Optional[CandidateSignal]
    ledger: List[Evidence]
    score: int
    band: str
    categories_passed: int
    contradictions: int
    mandatory_ok: bool
    min_categories_ok: bool = False


@dataclass(frozen=True, slots=True)
class GateResult:
    passed: bool
    reason_codes: List[str]
    selected_strike: Optional[Decimal] = None
    selected_leg: Optional[str] = None  # "CE" | "PE"


@dataclass(slots=True)
class OutboundMessage:
    kind: str  # SIGNAL | HEALTH | DAILY_SUMMARY | REJECTION_DIGEST
    text: str
    enqueued_mono: float = 0.0


# ============================================================
# SECTION: error taxonomy (Â§18)
# ============================================================


class TransientInfraError(Exception):
    """Recoverable infra error; retry with backoff."""


class DataIntegrityError(Exception):
    """Bad datum; drop and fail-closed the cycle."""


class FatalConfigError(Exception):
    """Unrecoverable configuration problem; exit at startup only."""


# ============================================================
# SECTION: logging_setup.py + metrics (Â§18)
# ============================================================

_SECRET_PATTERNS = [
    re.compile(r"(?i)(access[_-]?token|client[_-]?id|bot[_-]?token|chat[_-]?id)\s*[=:]\s*\S+"),
    re.compile(r"\b[0-9]{6,}:[A-Za-z0-9_\-]{20,}\b"),  # telegram bot token pattern
    re.compile(r"(?i)[?&](token|clientid)=[^&\s]+"),
]


class SecretRedactionFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:
            return True
        red = msg
        for pat in _SECRET_PATTERNS:
            red = pat.sub("[REDACTED]", red)
        if red != msg:
            record.msg = red
            record.args = ()
        return True


class JsonLineFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: Dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, IST).isoformat(),
            "level": record.levelname,
            "module": record.name,
            "event": record.getMessage(),
        }
        extra = getattr(record, "fields", None)
        if isinstance(extra, dict):
            payload["fields"] = extra
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        rendered = json.dumps(payload, default=str, sort_keys=True)
        for pat in _SECRET_PATTERNS:
            rendered = pat.sub("[REDACTED]", rendered)
        return rendered


def setup_logging(level: str, as_json: bool, log_dir: str) -> logging.Logger:
    os.makedirs(log_dir, exist_ok=True)
    root = logging.getLogger("engine")
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    root.handlers.clear()
    handler: logging.Handler = logging.handlers.TimedRotatingFileHandler(
        os.path.join(log_dir, "engine.log"), when="midnight", backupCount=14, encoding="utf-8"
    )
    stream = logging.StreamHandler(sys.stdout)
    fmt: logging.Formatter = JsonLineFormatter() if as_json else logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    red = SecretRedactionFilter()
    for h in (handler, stream):
        h.setFormatter(fmt)
        h.addFilter(red)
        root.addHandler(h)
    root.propagate = False
    return root


def log_event(logger: logging.Logger, level: int, event: str, **fields: Any) -> None:
    logger.log(level, event, extra={"fields": fields})


def sd_notify(state: str) -> None:
    """Best-effort sd_notify for systemd Type=notify + WatchdogSec (Â§20).
    No-op when NOTIFY_SOCKET is absent (non-systemd hosts)."""
    addr = os.environ.get("NOTIFY_SOCKET")
    if not addr:
        return
    try:
        import socket
        if addr.startswith("@"):
            addr = "\0" + addr[1:]
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        try:
            sock.sendto(state.encode("utf-8"), addr)
        finally:
            sock.close()
    except Exception:
        pass



class Metrics:
    """In-process counters and latency reservoirs (Â§18)."""

    def __init__(self) -> None:
        self.counters: Dict[str, int] = {}
        self.reservoirs: Dict[str, Deque[float]] = {}
        self.rejections_by_reason: Dict[str, int] = {}
        self.events: Dict[str, Deque[float]] = {}

    def inc(self, name: str, amount: int = 1) -> None:
        self.counters[name] = self.counters.get(name, 0) + amount

    def reject(self, code: str) -> None:
        self.rejections_by_reason[code] = self.rejections_by_reason.get(code, 0) + 1

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
        res = self.reservoirs.get(name)
        if not res:
            return 0.0
        ordered = sorted(res)
        k = max(0, min(len(ordered) - 1, int(round((pct / 100.0) * (len(ordered) - 1)))))
        return ordered[k]

    def snapshot(self) -> Dict[str, Any]:
        return {
            "counters": dict(self.counters),
            "rejections_by_reason": dict(self.rejections_by_reason),
            "lag_ms_p95": self.percentile("cycle_ms", 95),
            "signal_latency_p95": self.percentile("signal_latency_s", 95),
        }

    def dump(self, path: str) -> None:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(self.snapshot(), fh, default=str, sort_keys=True)
        os.replace(tmp, path)


# ============================================================
# SECTION: clock.py  (Â§6)
# ============================================================


class Clock:
    """Injectable IST clock abstraction."""

    def now(self) -> datetime:
        return datetime.now(IST)

    def monotonic(self) -> float:
        return time.monotonic()


class FixedClock(Clock):
    """Deterministic clock for tests/replay."""

    def __init__(self, start: datetime, mono: float = 0.0) -> None:
        if start.tzinfo is None:
            start = start.replace(tzinfo=IST)
        self._now = start.astimezone(IST)
        self._mono = mono

    def now(self) -> datetime:
        return self._now

    def monotonic(self) -> float:
        return self._mono

    def advance(self, seconds: float) -> None:
        self._now = self._now + timedelta(seconds=seconds)
        self._mono += seconds

    def set(self, when: datetime) -> None:
        target = when.astimezone(IST)
        delta = (target - self._now).total_seconds()
        if delta > 0:
            self._mono += delta
        self._now = target


class SessionCalendar:
    """NSE weekday calendar minus configured holidays (Â§6)."""

    PHASES: List[Tuple[SessionPhase, dtime, dtime]] = [
        (SessionPhase.PRE_OPEN, dtime(9, 0), dtime(9, 15)),
        (SessionPhase.OPENING, dtime(9, 15), dtime(9, 45)),
        (SessionPhase.MORNING, dtime(9, 45), dtime(11, 30)),
        (SessionPhase.MIDDAY, dtime(11, 30), dtime(13, 30)),
        (SessionPhase.AFTERNOON, dtime(13, 30), dtime(14, 45)),
        (SessionPhase.CLOSING, dtime(14, 45), dtime(15, 30)),
    ]

    def __init__(self, holidays: Sequence[str]) -> None:
        self.holidays: set[date] = set()
        for h in holidays:
            try:
                self.holidays.add(date.fromisoformat(h))
            except ValueError as exc:
                raise FatalConfigError(f"invalid holiday date: {h}") from exc

    def is_trading_day(self, d: date) -> bool:
        if d.weekday() >= 5:
            return False
        return d not in self.holidays

    def phase(self, now: datetime) -> SessionPhase:
        now = now.astimezone(IST)
        if not self.is_trading_day(now.date()):
            return SessionPhase.CLOSED
        t = now.time()
        for phase, start, end in self.PHASES:
            if start <= t < end:
                return phase
        return SessionPhase.CLOSED

    def signal_window_open(self, now: datetime, regime_strength: int) -> bool:
        """Signal-window predicate (Â§6)."""
        now = now.astimezone(IST)
        if not self.is_trading_day(now.date()):
            return False
        t = now.time()
        phase = self.phase(now)
        if phase == SessionPhase.OPENING:
            return t >= dtime(9, 21)
        if phase == SessionPhase.MORNING:
            return True
        if phase == SessionPhase.AFTERNOON:
            return True
        if phase == SessionPhase.MIDDAY:
            return regime_strength >= 70
        if phase == SessionPhase.CLOSING:
            return t < dtime(15, 0)
        return False


# ============================================================
# SECTION: infra/ratelimit.py  (Â§5.2)
# ============================================================


class TokenBucket:
    """Async token-bucket limiter."""

    def __init__(self, rate_per_s: float, burst: float, clock: Optional[Clock] = None) -> None:
        self.rate = rate_per_s
        self.burst = burst
        self.tokens = burst
        self.clock = clock or Clock()
        self.updated = self.clock.monotonic()
        self._lock = asyncio.Lock()

    def _refill(self) -> None:
        now = self.clock.monotonic()
        elapsed = now - self.updated
        if elapsed > 0:
            self.tokens = min(self.burst, self.tokens + elapsed * self.rate)
            self.updated = now

    async def acquire(self, amount: float = 1.0) -> None:
        async with self._lock:
            while True:
                self._refill()
                if self.tokens >= amount:
                    self.tokens -= amount
                    return
                needed = (amount - self.tokens) / self.rate if self.rate > 0 else 0.05
                await asyncio.sleep(max(0.005, needed))


# ============================================================
# SECTION: domain/bars.py  (Â§9.1)
# ============================================================


def minute_floor(ts: datetime) -> datetime:
    return ts.replace(second=0, microsecond=0)


class BarBuilder:
    """Builds 1-minute bars from ticks keyed to wall-clock minutes (Â§9.1).

    A bar completes when a tick arrives in the next minute, or when the
    minute elapses on the monotonic clock + 2 s grace (driven by poll()).
    """

    def __init__(self, clock: Clock, tick_size: Decimal = Decimal("0.05")) -> None:
        self.clock = clock
        self.tick_size = tick_size
        self._minute: Optional[datetime] = None
        self._open: Optional[Decimal] = None
        self._high: Optional[Decimal] = None
        self._low: Optional[Decimal] = None
        self._close: Optional[Decimal] = None
        self._tick_count = 0
        self._vol_start_cum: Optional[int] = None
        self._vol_end_cum: Optional[int] = None
        self._ltq_accum = 0
        self._suspect = False
        self._minute_mono: float = 0.0

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

    def _finalize(self) -> Optional[Bar]:
        if self._minute is None or self._open is None:
            return None
        raw_vol = 0
        if self._vol_start_cum is not None and self._vol_end_cum is not None:
            raw_vol = self._vol_end_cum - self._vol_start_cum
        suspect = self._suspect
        if raw_vol < 0:
            raw_vol = self._ltq_accum
            suspect = True
        bar = Bar(
            ts_open=self._minute,
            open=self._open,
            high=self._high or self._open,
            low=self._low or self._open,
            close=self._close or self._open,
            volume=int(raw_vol),
            tick_count=self._tick_count,
            volume_suspect=suspect,
        )
        return bar

    def on_tick(self, t: Tick) -> Optional[Bar]:
        minute = minute_floor(t.ts)
        if self._minute is None:
            self._reset(minute, t)
            return None
        if minute > self._minute:
            completed = self._finalize()
            self._reset(minute, t)
            return completed
        px = quantize_tick(t.ltp, self.tick_size)
        self._close = px
        if self._high is None or px > self._high:
            self._high = px
        if self._low is None or px < self._low:
            self._low = px
        self._tick_count += 1
        if self._vol_end_cum is not None and t.volume_cum < self._vol_end_cum:
            self._suspect = True
        self._vol_end_cum = t.volume_cum
        self._ltq_accum += t.ltq
        return None

    def poll(self) -> Optional[Bar]:
        """Time-based completion via monotonic + 2 s grace."""
        if self._minute is None:
            return None
        if self.clock.monotonic() - self._minute_mono >= 62.0:
            completed = self._finalize()
            self._minute = None
            self._open = None
            return completed
        return None


class BarAggregator5m:
    """Aggregates completed 1m bars into 5m bars (Â§9.1)."""

    def __init__(self) -> None:
        self._buf: List[Bar] = []

    def on_bar_1m(self, b: Bar) -> Optional[Bar]:
        if self._buf:
            prev = self._buf[0].ts_open
            prev_bucket = prev.replace(minute=(prev.minute // 5) * 5, second=0, microsecond=0)
            cur_bucket = b.ts_open.replace(minute=(b.ts_open.minute // 5) * 5, second=0, microsecond=0)
            if cur_bucket != prev_bucket:
                group = self._buf
                self._buf = [b]
                return self._merge(group)
        self._buf.append(b)
        minute = b.ts_open.minute
        if minute % 5 == 4:
            group = self._buf
            self._buf = []
            return self._merge(group)
        return None

    @staticmethod
    def _merge(group: List[Bar]) -> Optional[Bar]:
        if not group:
            return None
        base_minute = (group[0].ts_open.minute // 5) * 5
        ts_open = group[0].ts_open.replace(minute=base_minute)
        o = group[0].open
        h = max(b.high for b in group)
        low = min(b.low for b in group)
        c = group[-1].close
        vol = sum(b.volume for b in group)
        tc = sum(b.tick_count for b in group)
        suspect = any(b.volume_suspect for b in group)
        return Bar(ts_open=ts_open, open=o, high=h, low=low, close=c,
                   volume=vol, tick_count=tc, volume_suspect=suspect)


# ============================================================
# SECTION: domain/volatility.py  (Â§9.4)
# ============================================================


class ATR:
    """Wilder-smoothed ATR (Â§9.4). Incremental O(1) per bar."""

    def __init__(self, period: int = 14) -> None:
        self.period = period
        self._prev_close: Optional[Decimal] = None
        self._atr: Optional[Decimal] = None
        self._count = 0
        self._tr_sum = Decimal(0)

    def update(self, bar: Bar) -> Optional[Decimal]:
        if self._prev_close is None:
            tr = bar.high - bar.low
        else:
            tr = max(
                bar.high - bar.low,
                abs(bar.high - self._prev_close),
                abs(bar.low - self._prev_close),
            )
        self._prev_close = bar.close
        self._count += 1
        if self._count <= self.period:
            self._tr_sum += tr
            if self._count == self.period:
                self._atr = self._tr_sum / Decimal(self.period)
            return self._atr
        assert self._atr is not None
        self._atr = (self._atr * Decimal(self.period - 1) + tr) / Decimal(self.period)
        return self._atr

    @property
    def value(self) -> Optional[Decimal]:
        return self._atr


class BollingerBandwidth:
    """Bollinger bandwidth(20,2) on close, plus percentile-rank compression."""

    def __init__(self, period: int = 20, mult: Decimal = Decimal(2)) -> None:
        self.period = period
        self.mult = mult
        self._closes: Deque[Decimal] = deque(maxlen=period)
        self.history: Deque[float] = deque(maxlen=400)
        self._last_bw: Optional[float] = None
        self._rising_count = 0

    def update(self, bar: Bar) -> Optional[float]:
        self._closes.append(bar.close)
        if len(self._closes) < self.period:
            return None
        mean = sum(self._closes) / Decimal(len(self._closes))
        var = sum((c - mean) ** 2 for c in self._closes) / Decimal(len(self._closes))
        std = var.sqrt()
        upper = mean + self.mult * std
        lower = mean - self.mult * std
        bw = float((upper - lower) / mean) if mean != 0 else 0.0
        if self._last_bw is not None and bw > self._last_bw:
            self._rising_count += 1
        else:
            self._rising_count = 0
        self._last_bw = bw
        self.history.append(bw)
        return bw

    def percentile_rank(self) -> float:
        if self._last_bw is None:
            return 50.0
        return _pct_rank(self._last_bw, list(self.history))

    @property
    def rising_3(self) -> bool:
        return self._rising_count >= 3


class ADX:
    """Wilder ADX(14) incremental (Â§11)."""

    def __init__(self, period: int = 14) -> None:
        self.period = period
        self._prev: Optional[Bar] = None
        self._tr = Decimal(0)
        self._plus_dm = Decimal(0)
        self._minus_dm = Decimal(0)
        self._count = 0
        self._adx: Optional[Decimal] = None
        self._dx_hist: Deque[Decimal] = deque(maxlen=period)
        self._prev_adx: Optional[Decimal] = None
        self._rising = False

    def update(self, bar: Bar) -> Optional[Decimal]:
        if self._prev is None:
            self._prev = bar
            return None
        up_move = bar.high - self._prev.high
        down_move = self._prev.low - bar.low
        plus_dm = up_move if (up_move > down_move and up_move > 0) else Decimal(0)
        minus_dm = down_move if (down_move > up_move and down_move > 0) else Decimal(0)
        tr = max(
            bar.high - bar.low,
            abs(bar.high - self._prev.close),
            abs(bar.low - self._prev.close),
        )
        self._prev = bar
        self._count += 1
        if self._count <= self.period:
            self._tr += tr
            self._plus_dm += plus_dm
            self._minus_dm += minus_dm
            if self._count < self.period:
                return None
        else:
            self._tr = self._tr - (self._tr / Decimal(self.period)) + tr
            self._plus_dm = self._plus_dm - (self._plus_dm / Decimal(self.period)) + plus_dm
            self._minus_dm = self._minus_dm - (self._minus_dm / Decimal(self.period)) + minus_dm
        if self._tr == 0:
            return self._adx
        plus_di = Decimal(100) * (self._plus_dm / self._tr)
        minus_di = Decimal(100) * (self._minus_dm / self._tr)
        denom = plus_di + minus_di
        dx = Decimal(0) if denom == 0 else Decimal(100) * abs(plus_di - minus_di) / denom
        self._dx_hist.append(dx)
        if self._adx is None:
            if len(self._dx_hist) >= self.period:
                self._adx = sum(self._dx_hist) / Decimal(self.period)
        else:
            prev = self._adx
            self._adx = (self._adx * Decimal(self.period - 1) + dx) / Decimal(self.period)
            self._prev_adx = prev
            self._rising = self._adx > prev
        return self._adx

    @property
    def value(self) -> Optional[Decimal]:
        return self._adx

    @property
    def rising(self) -> bool:
        return self._rising


class IVTracker:
    """Tracks ATM IV level and 5-snapshot slope for spike detection (Â§9.4)."""

    def __init__(self) -> None:
        self._hist: Deque[Tuple[datetime, Decimal, Decimal]] = deque(maxlen=6)

    def update(self, ts: datetime, atm_iv: Decimal, spot: Decimal) -> None:
        self._hist.append((ts, atm_iv, spot))

    def spike_against_flat_price(self) -> bool:
        """IV spiking > +8% in ~5 min while price roughly flat (Â§9.4)."""
        if len(self._hist) < 6:
            return False
        _, iv0, spot0 = self._hist[0]
        _, iv1, spot1 = self._hist[-1]
        if iv0 <= 0 or spot0 <= 0:
            return False
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


# ============================================================
# SECTION: domain/vwap.py  (Â§9.2)
# ============================================================


class AVWAPO:
    """Synthetic session anchor: typical-price mean weighted by ATM combined
    option volume (AVWAP-O), with Â±1Ïƒ/Â±2Ïƒ volume-weighted bands, plus a plain
    session TWAP fallback when option volume is suspect (Â§9.2). O(1) per bar.
    """

    def __init__(self) -> None:
        self._pv = Decimal(0)
        self._w = Decimal(0)
        self._pv2 = Decimal(0)
        self._tp_sum = Decimal(0)
        self._n = 0
        self._avwap_hist: Deque[Decimal] = deque(maxlen=64)
        self._last: Optional[Decimal] = None
        self._last_sigma: Decimal = Decimal(0)

    def update(self, index_bar: Bar, atm_option_volume: int, volume_suspect: bool) -> None:
        typical = index_bar.typical
        self._tp_sum += typical
        self._n += 1
        weight = Decimal(0)
        if not volume_suspect and atm_option_volume > 0:
            weight = Decimal(atm_option_volume)
        if weight > 0:
            self._pv += weight * typical
            self._pv2 += weight * typical * typical
            self._w += weight
        if self._w > 0:
            mean = self._pv / self._w
            var = (self._pv2 / self._w) - (mean * mean)
            if var < 0:
                var = Decimal(0)
            self._last_sigma = var.sqrt()
            self._last = mean
        else:
            self._last = self._tp_sum / Decimal(self._n)
            self._last_sigma = Decimal(0)
        self._avwap_hist.append(self._last)

    @property
    def value(self) -> Optional[Decimal]:
        return self._last

    @property
    def sigma(self) -> Decimal:
        return self._last_sigma

    def band(self, mult: int) -> Optional[Tuple[Decimal, Decimal]]:
        if self._last is None:
            return None
        return (self._last - Decimal(mult) * self._last_sigma,
                self._last + Decimal(mult) * self._last_sigma)

    def slope_over(self, bars: int = 10) -> Decimal:
        if len(self._avwap_hist) < 2:
            return Decimal(0)
        lookback = min(bars, len(self._avwap_hist) - 1)
        return self._avwap_hist[-1] - self._avwap_hist[-1 - lookback]

    def distance_in_sigma(self, price: Decimal) -> Decimal:
        if self._last is None or self._last_sigma == 0:
            return Decimal(0)
        return (price - self._last) / self._last_sigma

    def state(self) -> Dict[str, Any]:
        return {
            "pv": str(self._pv), "w": str(self._w), "pv2": str(self._pv2),
            "tp_sum": str(self._tp_sum), "n": self._n,
            "hist": [str(x) for x in self._avwap_hist],
        }

    def restore(self, s: Dict[str, Any]) -> None:
        self._pv = _d(s["pv"]); self._w = _d(s["w"]); self._pv2 = _d(s["pv2"])
        self._tp_sum = _d(s["tp_sum"]); self._n = int(s["n"])
        self._avwap_hist = deque((_d(x) for x in s.get("hist", [])), maxlen=64)
        if self._avwap_hist:
            self._last = self._avwap_hist[-1]


class EMA:
    """EMA on 5m closes for slope evidence (20-EMA, Â§10/Â§14)."""

    def __init__(self, period: int = 20) -> None:
        self.period = period
        self.k = Decimal(2) / Decimal(period + 1)
        self._value: Optional[Decimal] = None
        self._prev: Optional[Decimal] = None

    def update(self, bar: Bar) -> Optional[Decimal]:
        if self._value is None:
            self._value = bar.close
        else:
            self._prev = self._value
            self._value = (bar.close - self._value) * self.k + self._value
        return self._value

    @property
    def value(self) -> Optional[Decimal]:
        return self._value

    @property
    def slope(self) -> Decimal:
        if self._value is None or self._prev is None:
            return Decimal(0)
        return self._value - self._prev


# ============================================================
# SECTION: domain/volume.py  (Â§9.3)
# ============================================================


class VolumeAnalyzer:
    """RVOL and impulse/absorption detection on ATM combined option volume,
    keyed by minute-of-day (Â§9.3)."""

    def __init__(self) -> None:
        self._by_minute: Dict[Tuple[int, int], List[int]] = {}
        # RVOL-FIX: spec 9.3 defines RVOL as "current 1m ATM combined option
        # volume / median of the same minute-of-day over the CURRENT SESSION's
        # prior bars (min 10 bars)". The per-minute-of-day pool below only ever
        # receives ONE sample per clock minute per session, so len(pool) >= 10
        # required the same clock minute to recur across 10 separate sessions.
        # Forensic proof: state/snapshot.json held 488 pools of which exactly 1
        # reached depth 10, and rvol was 'neutral' in 190/190 decision ledgers,
        # capping the Volume category at 5.0 against a 7.2 pass bar so it could
        # never pass. This rolling same-session series restores the specified
        # denominator. Thresholds, weights and gate semantics are unchanged.
        self._session_series: List[int] = []
        self._session_key: Optional[date] = None

    def _roll_session(self, ts: datetime) -> None:
        """Reset the intra-session series when the trading date changes."""
        day = ts.date()
        if self._session_key != day:
            self._session_key = day
            self._session_series = []

    def record_minute(self, ts: datetime, atm_option_volume: int,
                      suspect: bool = False) -> None:
        if suspect or atm_option_volume <= 0:
            return
        key = (ts.hour, ts.minute)
        pool = self._by_minute.setdefault(key, [])
        pool.append(atm_option_volume)
        if len(pool) > 30:
            del pool[0]
        # RVOL-FIX: also maintain the current-session rolling series.
        self._roll_session(ts)
        self._session_series.append(atm_option_volume)
        if len(self._session_series) > 375:
            del self._session_series[0]

    def rvol(self, ts: datetime, atm_option_volume: int) -> Optional[float]:
        if atm_option_volume <= 0:
            return None
        # Preferred denominator: same minute-of-day across sessions, once that
        # pool is genuinely deep enough (unchanged original behaviour).
        pool: List[int] = list(self._by_minute.get((ts.hour, ts.minute), []))
        if len(pool) >= 10:
            med = _median([float(v) for v in pool])
            if med > 0:
                return float(atm_option_volume) / med
        # RVOL-FIX fallback: current-session prior bars, min 10 (spec 9.3).
        # Fail closed: fewer than 10 prior bars still returns None, so the
        # Volume category stays neutral during warmup exactly as before.
        self._roll_session(ts)
        if len(self._session_series) < 10:
            return None
        med_s = _median([float(v) for v in self._session_series])
        if med_s <= 0:
            return None
        return float(atm_option_volume) / med_s


    def classify_bar(self, index_bar: Bar, atr_1m: Optional[Decimal],
                     rvol: Optional[float]) -> str:
        """Return 'impulse', 'absorption', or 'normal' (Â§9.3)."""
        if atr_1m is None or atr_1m == 0 or rvol is None:
            return "normal"
        rng = index_bar.range
        if rng >= Decimal("1.5") * atr_1m and rvol >= 1.5:
            return "impulse"
        if rvol >= 2.0 and rng <= Decimal("0.6") * atr_1m:
            return "absorption"
        return "normal"

    def state(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {f"{h}:{m}": v for (h, m), v in self._by_minute.items()}
        # RVOL-FIX: persist the intra-session series under a reserved key that
        # cannot collide with an "H:M" minute key, so a mid-session restart
        # does not silently re-enter the >=10-sample warmup. The reserved key
        # is ignored by older readers because restore() skips non-"H:M" keys.
        if self._session_series:
            out["__session__"] = {
                "day": self._session_key.isoformat() if self._session_key else None,
                "series": list(self._session_series),
            }
        return out

    def restore(self, s: Dict[str, Any]) -> None:
        self._by_minute = {}
        self._session_series = []
        self._session_key = None
        for k, v in s.items():
            if k == "__session__":
                # RVOL-FIX: restore the intra-session series only.
                if not isinstance(v, dict):
                    continue
                day_raw = v.get("day")
                try:
                    self._session_key = date.fromisoformat(day_raw) if day_raw else None
                except (TypeError, ValueError):
                    self._session_key = None
                    continue
                for x in (v.get("series") or []):
                    try:
                        val = int(x)
                    except (TypeError, ValueError):
                        continue
                    if val > 0:
                        self._session_series.append(val)
                if len(self._session_series) > 375:
                    self._session_series = self._session_series[-375:]
                continue
            if ":" not in k:
                continue
            h, m = k.split(":")
            clean: List[int] = []
            for x in v:
                try:
                    val = int(x)
                except (TypeError, ValueError):
                    continue
                if val > 0:
                    clean.append(val)
            if len(clean) > 30:
                clean = clean[-30:]
            if clean:
                self._by_minute[(int(h), int(m))] = clean



# ============================================================
# SECTION: domain/structure.py  (Â§10)
# ============================================================


class StructureEngine:
    """Market structure: swings (fractal), BOS/CHoCH/sweep/retest, S/R levels (Â§10)."""

    def __init__(
        self,
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
        self._bias: str = "NEUTRAL"
        self._levels: List[Level] = []
        self._session_high: Optional[Decimal] = None
        self._session_low: Optional[Decimal] = None
        self._opening_range_high: Optional[Decimal] = None
        self._opening_range_low: Optional[Decimal] = None
        self._prev_day_high: Optional[Decimal] = None
        self._prev_day_low: Optional[Decimal] = None
        self._prev_day_close: Optional[Decimal] = None

    def set_atr_5m(self, atr: Optional[Decimal]) -> None:
        self._atr_5m = atr

    def set_dynamic_levels(self, avwap: Optional[Decimal], sigma: Decimal,
                           ema20: Optional[Decimal]) -> None:
        self._avwap = avwap
        self._avwap_sigma = sigma
        self._ema20 = ema20

    def append_event(self, ev: StructureEvent) -> None:
        _FX.queue_pre_append("structure._events", self._events, 1262)  # diagnostic only
        self._events.append(ev)
        _FX.on_append_event(ev, 1261)  # diagnostic only

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
        _ev = StructureEvent(kind, level, ts, ref_swing)
        _FX.on_emit(_ev, key, 1277)  # diagnostic only
        return _ev

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
                    _FX.queue_pre_append("structure._events", self._events, 1333)  # diagnostic
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
        # 5m events occur at bar completion, not bucket open (trigger freshness).
        _close_ts = bar.ts_open + timedelta(minutes=5)
        new_events = [replace(ev, ts=_close_ts) for ev in new_events]
        for ev in new_events:
            _FX.queue_pre_append("structure._events", self._events, 1359)  # diagnostic
            self._events.append(ev)
        self._update_levels(bar, atr_5m)
        _FX.cycle("", "STRUCTURE", "StructureEngine.on_bar_5m", 1352,
                  "PASS" if new_events else "FAIL",
                  ",".join(e.kind.value for e in new_events) or "no_event_this_bar",
                  bar_ts=bar.ts_open, bar_close=bar.close, atr_5m=atr_5m,
                  swings=len(self._swings), bias=self._bias,
                  pending_bos=len(self._pending_bos),
                  pending_sweeps=len(self._pending_sweeps),
                  events_in_deque=len(self._events))  # diagnostic only
        return new_events

    def _check_swing(self, center_idx: int, ts: datetime) -> None:
        if center_idx < self.swing_left:
            return
        bars = list(self._bars_5m)
        if center_idx + self.swing_right >= len(bars):
            return
        c = bars[center_idx]
        left = bars[center_idx - self.swing_left : center_idx]
        right = bars[center_idx + 1 : center_idx + self.swing_right + 1]
        if len(right) < self.swing_right or len(left) < self.swing_left:
            return
        is_high = all(c.high > b.high for b in left) and all(c.high > b.high for b in right)
        is_low = all(c.low < b.low for b in left) and all(c.low < b.low for b in right)
        if is_high:
            self._add_swing(SwingKind.HIGH, c.high, c.ts_open, center_idx)
        if is_low:
            self._add_swing(SwingKind.LOW, c.low, c.ts_open, center_idx)

    def _add_swing(self, kind: SwingKind, price: Decimal, ts: datetime, idx: int) -> None:
        if self._swings and self._swings[-1].bar_index == idx and self._swings[-1].kind == kind:
            return
        if self._swings:
            last = self._swings[-1]
            if last.kind == kind:
                if kind == SwingKind.HIGH:
                    if price > last.price:
                        self._swings[-1] = Swing(kind, price, ts, idx, True)
                    return
                else:
                    if price < last.price:
                        self._swings[-1] = Swing(kind, price, ts, idx, True)
                    return
        self._swings.append(Swing(kind, price, ts, idx, True))

    def _detect_bos_choch(self, bar: Bar, atr: Optional[Decimal]) -> List[StructureEvent]:
        events: List[StructureEvent] = []
        if len(self._swings) < 2:
            return events

        last_high: Optional[Swing] = None
        last_low: Optional[Swing] = None

        for s in reversed(self._swings):
            if last_high is None and s.kind == SwingKind.HIGH:
                last_high = s
            elif last_low is None and s.kind == SwingKind.LOW:
                last_low = s
            if last_high is not None and last_low is not None:
                break

        up_break = last_high is not None and bar.close > last_high.price
        down_break = last_low is not None and bar.close < last_low.price

        if up_break and down_break:
            return events

        if up_break and last_high is not None:
            if self._bias in ("BULLISH", "NEUTRAL"):
                ev = self._emit(StructureKind.BOS_UP, last_high.price, bar.ts_open, last_high)
                if ev is not None:
                    events.append(ev)
                    self._bias = "BULLISH"
                    self._last_bos_level = last_high.price
                    self._pending_bos.append({
                        "kind": StructureKind.BOS_UP,
                        "level": last_high.price,
                        "ref_swing": last_high,
                        "bars": 0,
                    })
            else:
                ev = self._emit(StructureKind.CHOCH_UP, last_high.price, bar.ts_open, last_high)
                if ev is not None:
                    events.append(ev)
                    self._bias = "NEUTRAL"

        elif down_break and last_low is not None:
            if self._bias in ("BEARISH", "NEUTRAL"):
                ev = self._emit(StructureKind.BOS_DOWN, last_low.price, bar.ts_open, last_low)
                if ev is not None:
                    events.append(ev)
                    self._bias = "BEARISH"
                    self._last_bos_level = last_low.price
                    self._pending_bos.append({
                        "kind": StructureKind.BOS_DOWN,
                        "level": last_low.price,
                        "ref_swing": last_low,
                        "bars": 0,
                    })
            else:
                ev = self._emit(StructureKind.CHOCH_DOWN, last_low.price, bar.ts_open, last_low)
                if ev is not None:
                    events.append(ev)
                    self._bias = "NEUTRAL"

        return events

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

    def _update_levels(self, bar: Bar, atr: Optional[Decimal]) -> None:
        self._levels = []
        for s in self._swings:
            if s.price == 0:
                continue
            nearby = [x for x in self._swings if abs(x.price - s.price) / s.price < Decimal("0.0015")]
            self._levels.append(Level(s.price, "swing", len(nearby)))
        if self._prev_day_high:
            self._levels.append(Level(self._prev_day_high, "prev_day_high", 3))
        if self._prev_day_low:
            self._levels.append(Level(self._prev_day_low, "prev_day_low", 3))
        if self._prev_day_close:
            self._levels.append(Level(self._prev_day_close, "prev_day_close", 2))
        if self._opening_range_high:
            self._levels.append(Level(self._opening_range_high, "opening_range_high", 2))
        if self._opening_range_low:
            self._levels.append(Level(self._opening_range_low, "opening_range_low", 2))
        if self._session_high:
            self._levels.append(Level(self._session_high, "session_high", 2))
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
        """Merge option-chain S/R levels into the level list (Â§10/Â§12)."""
        self._chain_levels = list(option_levels)
        self._levels = [lv for lv in self._levels if not lv.source.startswith("chain_")]
        self._levels.extend(self._chain_levels)

    def set_opening_range(self, high: Decimal, low: Decimal) -> None:
        self._opening_range_high = high
        self._opening_range_low = low

    def set_prev_day(self, high: Decimal, low: Decimal, close: Decimal) -> None:
        self._prev_day_high = high
        self._prev_day_low = low
        self._prev_day_close = close

    def cluster_levels(self, around: Decimal, pct: Decimal = Decimal("0.0015")) -> Optional[Level]:
        if around == 0:
            return None
        candidates = [lv for lv in self._levels if abs(lv.price - around) / around < pct]
        if not candidates:
            return None
        total_str = sum(Decimal(lv.strength) for lv in candidates)
        agg_price = sum(lv.price * Decimal(lv.strength) for lv in candidates) / total_str
        agg_strength = sum(lv.strength for lv in candidates)
        sources = ",".join(sorted(set(lv.source for lv in candidates)))
        return Level(agg_price, sources, agg_strength)

    def nearest_level(self, price: Decimal, direction: str) -> Optional[Level]:
        if direction == "above":
            cand = [lv for lv in self._levels if lv.price > price]
            return min(cand, key=lambda x: x.price) if cand else None
        cand = [lv for lv in self._levels if lv.price < price]
        return max(cand, key=lambda x: x.price) if cand else None

    @property
    def swings(self) -> List[Swing]:
        return list(self._swings)

    @property
    def events(self) -> List[StructureEvent]:
        return list(self._events)

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

    def state(self) -> Dict[str, Any]:
        return {
            "swings": [
                {"kind": s.kind.value, "price": str(s.price), "ts": s.ts.isoformat(), "idx": s.bar_index}
                for s in self._swings
            ],
            "bias": self._bias,
            "last_bos": str(self._last_bos_level) if self._last_bos_level else None,
            "session_high": str(self._session_high) if self._session_high else None,
            "session_low": str(self._session_low) if self._session_low else None,
            "or_high": str(self._opening_range_high) if self._opening_range_high else None,
            "or_low": str(self._opening_range_low) if self._opening_range_low else None,
            "pd_high": str(self._prev_day_high) if self._prev_day_high else None,
            "pd_low": str(self._prev_day_low) if self._prev_day_low else None,
            "pd_close": str(self._prev_day_close) if self._prev_day_close else None,
            # FIX-EV: structure events must survive a restart. Without this
            # the trigger scanner (180 s freshness window) sees an empty deque
            # after every snapshot restore and can never build a candidate.
            "events": [
                {
                    "kind": e.kind.value,
                    "level": str(e.level),
                    "ts": e.ts.isoformat(),
                    "swing": (
                        {
                            "kind": e.ref_swing.kind.value,
                            "price": str(e.ref_swing.price),
                            "ts": e.ref_swing.ts.isoformat(),
                            "idx": e.ref_swing.bar_index,
                        }
                        if e.ref_swing is not None else None
                    ),
                }
                for e in self._events
            ],
            # Preserve the emission latch so restored events can never be
            # re-emitted (no duplicate signals after a restart).
            "emitted": [[k[0], k[1]] for k in sorted(self._emitted)],
        }

    def restore(self, s: Dict[str, Any]) -> None:
        self._swings = [
            Swing(SwingKind(x["kind"]), _d(x["price"]), datetime.fromisoformat(x["ts"]), int(x["idx"]), True)
            for x in s.get("swings", [])
        ]
        self._bias = s.get("bias", "NEUTRAL")
        self._last_bos_level = _d(s["last_bos"]) if s.get("last_bos") else None
        self._session_high = _d(s["session_high"]) if s.get("session_high") else None
        self._session_low = _d(s["session_low"]) if s.get("session_low") else None
        self._opening_range_high = _d(s["or_high"]) if s.get("or_high") else None
        self._opening_range_low = _d(s["or_low"]) if s.get("or_low") else None
        self._prev_day_high = _d(s["pd_high"]) if s.get("pd_high") else None
        self._prev_day_low = _d(s["pd_low"]) if s.get("pd_low") else None
        self._prev_day_close = _d(s["pd_close"]) if s.get("pd_close") else None
        self._pending_bos = []
        self._pending_sweeps = []
        # FIX-EV: rebuild the emission latch first, then the event deque.
        self._emitted = {
            (str(k[0]), str(k[1]))
            for k in s.get("emitted", [])
            if isinstance(k, (list, tuple)) and len(k) == 2
        }
        self._events = deque(maxlen=50)
        for x in s.get("events", []):
            try:
                sw = x.get("swing")
                ref = (
                    Swing(SwingKind(sw["kind"]), _d(sw["price"]),
                          datetime.fromisoformat(sw["ts"]), int(sw["idx"]), True)
                    if isinstance(sw, dict) else None
                )
                _rev = StructureEvent(
                    StructureKind(x["kind"]), _d(x["level"]),
                    datetime.fromisoformat(x["ts"]), ref,
                )
                self._events.append(_rev)
                _FX.on_restore(_rev, 1661)  # diagnostic only
            except Exception:
                # Malformed persisted event is dropped, never guessed.
                continue


# ============================================================
# SECTION: domain/regime.py  (Â§11)
# ============================================================


class RegimeClassifier:
    """Regime identification with hysteresis (Â§11)."""

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
        # RULE 6/9: every component below is a value production itself computed
        # and handed to _classify on THIS call; nothing is recomputed here.
        _FX.cycle("", "REGIME", "RegimeClassifier._classify", 1728,
                  "PASS" if now_reg is not Regime.UNKNOWN else "FAIL",
                  "classified=%s" % now_reg.value,
                  bar_ts=b.ts_open, classified=now_reg.value, strength=strength,
                  adx=ctx.adx, adx_threshold=22, adx_ge_22=(
                      ctx.adx is not None and ctx.adx >= 22),
                  adx_rising=ctx.adx_rising, bias=ctx.bias, phase=ctx.phase.value,
                  swings=len(ctx.swings), avwap=ctx.avwap,
                  avwap_slope=ctx.avwap_slope, avwap_dist_sigma=ctx.avwap_dist_sigma,
                  bb_pct=ctx.bb_pct, bb_rising_3=ctx.bb_rising_3,
                  impulse_present=ctx.impulse_present, atr_5m=ctx.atr_5m,
                  or_broken=ctx.opening_range_broken,
                  or_swept=ctx.opening_extreme_swept,
                  trend_branch_entered=(ctx.adx is not None and ctx.adx >= 22
                                        and ctx.adx_rising),
                  prior_regime=self._state.regime.value,
                  hysteresis_candidate=(self._candidate.value
                                        if self._candidate is not None else None),
                  hysteresis_count=self._candidate_count)  # diagnostic only
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
                    and ctx.avwap is not None
                    and abs(ctx.avwap_slope) < Decimal("0.25") * ctx.atr_5m):
                return Regime.RANGE
        return Regime.UNKNOWN

    def _check_sequence(self, swings: List[Swing], bias: str) -> bool:
        if len(swings) < 4:
            return False
        recent = swings[-6:]
        highs = [s for s in recent if s.kind == SwingKind.HIGH]
        lows = [s for s in recent if s.kind == SwingKind.LOW]
        if len(highs) < 2 or len(lows) < 2:
            return False
        if bias == "BULLISH":
            hh = all(highs[i].price < highs[i + 1].price for i in range(len(highs) - 1))
            hl = all(lows[i].price < lows[i + 1].price for i in range(len(lows) - 1))
            return hh and hl
        if bias == "BEARISH":
            lh = all(highs[i].price > highs[i + 1].price for i in range(len(highs) - 1))
            ll = all(lows[i].price > lows[i + 1].price for i in range(len(lows) - 1))
            return lh and ll
        return False

    def _check_avwap_side(self, bar: Bar, avwap: Optional[Decimal], bias: str) -> bool:
        if avwap is None:
            return False
        if bias == "BULLISH":
            return bar.close > avwap
        if bias == "BEARISH":
            return bar.close < avwap
        return False

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

    @property
    def state(self) -> RegimeState:
        return self._state

    def persist(self) -> Dict[str, Any]:
        return {
            "regime": self._state.regime.value,
            "since_ts": self._state.since_ts.isoformat(),
            "strength": self._state.strength_0_100,
        }

    def restore(self, s: Dict[str, Any]) -> None:
        self._state = RegimeState(Regime(s["regime"]), datetime.fromisoformat(s["since_ts"]), int(s["strength"]))


# ============================================================
# SECTION: domain/options_intel.py  (Â§12)
# ============================================================


@dataclass(frozen=True, slots=True)
class OptionsView:
    """Derived options intelligence for one snapshot (Â§12)."""
    ts: datetime
    atm_strike: Decimal
    atm_migration: str  # "up" | "down" | "none"
    pcr: Decimal
    pcr_signal: str  # "bullish" | "bearish" | "neutral" | "contrarian"
    directional_oi: str  # "bullish" | "bearish" | "neutral"
    directional_z: Decimal
    resistance_levels: List[Level]
    support_levels: List[Level]
    liquidity_scores: Dict[str, float]  # "STRIKE|CE"/"STRIKE|PE" -> score
    atm_iv: Decimal
    classifications: Dict[str, str]
    volume_5m: Dict[str, int]


class OptionsIntel:
    """OI, PCR, ATM identification/migration, liquidity ranking, S/R (Â§12)."""

    def __init__(
        self,
        atm_band_strikes: int = 3,
        oi_delta_lookback: int = 10,
        pcr_bearish_below: Decimal = Decimal("0.7"),
        pcr_bullish_above: Decimal = Decimal("1.3"),
    ) -> None:
        self.atm_band = atm_band_strikes
        self.oi_delta_lookback = oi_delta_lookback
        self.pcr_bearish = pcr_bearish_below
        self.pcr_bullish = pcr_bullish_above
        # LIFECYCLE-FIX A: volume_5m needs a snapshot >= 300 s old.
        # At chain_poll_interval_s=5 a 40-deep deque spans only 200 s,
        # so volume_5m returned {} forever and the LIQUIDITY gate could
        # never pass. 240 * 5 s = 1200 s gives headroom for slower polls
        # too. Depth only; no threshold or scoring change.
        self._snapshots: Deque[ChainSnapshot] = deque(maxlen=240)
        self._baseline_oi: Dict[str, int] = {}
        self._atm_history: Deque[Decimal] = deque(maxlen=4)
        self._last_view: Optional[OptionsView] = None
        # OI-DIAG: observation-only. Holds the most recent diagnostic record
        # so a candidate can be correlated to the OI inputs that produced it.
        self._last_oi_diag: Dict[str, Any] = {}
        # P4: full term ledger from the most recent _directional_oi evaluation.
        # Observation only; never consulted by scoring or gating.
        self._last_terms: Dict[str, Any] = {}
        # P2-A: per-strike baseline recorded at BASKET ENTRY (drift-neutral),
        # as distinct from _baseline_oi which is pinned to the 09:16 strike set.
        self._basket_baseline_oi: Dict[str, int] = {}

    def set_baseline(self, snap: ChainSnapshot) -> None:
        """Record the 09:16 session baseline OI (Â§12)."""
        self._baseline_oi = {}
        for st in snap.strikes:
            self._baseline_oi[f"{st.strike}|CE"] = st.ce.oi
            self._baseline_oi[f"{st.strike}|PE"] = st.pe.oi

    def on_snapshot(self, s: ChainSnapshot) -> OptionsView:
        _FX.queue_pre_append("options._snapshots", self._snapshots, 1894,
                             "STATE")  # diagnostic only
        self._snapshots.append(s)
        if not self._baseline_oi:
            self.set_baseline(s)
        atm = self._identify_atm(s)
        migration = self._atm_migration(atm)
        pcr, pcr_sig = self._pcr(s, atm)
        band = self._band_strikes(s, atm)
        directional, z = self._directional_oi(s, atm, band)
        _FX.cycle(s.underlying, "OI", "OptionsIntel._directional_oi", 1978,
                  "PASS" if directional != "neutral" else "FAIL",
                  "%s branch=%s" % (directional,
                                    self._last_terms.get("branch",
                                                         self._last_terms.get("stage"))),
                  verdict=directional, z=z, atm=atm, expiry=s.expiry,
                  snapshots_len=len(self._snapshots),
                  informative_obs=self._last_terms.get("informative_obs"),
                  z_pe=self._last_terms.get("z_pe"), z_ce=self._last_terms.get("z_ce"),
                  win_pe=self._last_terms.get("win_pe"),
                  win_ce=self._last_terms.get("win_ce"))  # diagnostic only
        self._oi_diag_record(s, atm, directional, z)  # OI-DIAG: observe only
        resistance, support = self._strike_sr(s, atm)
        liq = self._liquidity_scores(band)
        classifications = self._classify_legs(s, band)
        atm_iv = self._atm_iv(s, atm)
        vol5m = self._volume_5m(s, band)
        view = OptionsView(
            ts=s.ts, atm_strike=atm, atm_migration=migration, pcr=pcr, pcr_signal=pcr_sig,
            directional_oi=directional, directional_z=z, resistance_levels=resistance,
            support_levels=support, liquidity_scores=liq, atm_iv=atm_iv,
            classifications=classifications, volume_5m=vol5m,
        )
        self._last_view = view
        return view

    def _identify_atm(self, s: ChainSnapshot) -> Decimal:
        best: Optional[Decimal] = None
        best_diff: Optional[Decimal] = None
        for st in s.strikes:
            if st.ce.ltp <= 0 or st.pe.ltp <= 0:
                continue
            diff = abs(st.ce.ltp - st.pe.ltp)
            if best_diff is None or diff < best_diff:
                best_diff = diff
                best = st.strike
        if best is None:
            # fallback: nearest-to-spot
            best = min(s.strikes, key=lambda st: abs(st.strike - s.spot)).strike
        self._atm_history.append(best)
        return best

    def _atm_migration(self, atm: Decimal) -> str:
        if len(self._atm_history) < 3:
            return "none"
        last3 = list(self._atm_history)[-3:]
        # migration confirmed if changed and persisted 2 consecutive snapshots
        if last3[-1] == last3[-2] and last3[-1] != last3[-3]:
            if last3[-1] > last3[-3]:
                return "up"
            if last3[-1] < last3[-3]:
                return "down"
        return "none"

    def _band_strikes(self, s: ChainSnapshot, atm: Decimal) -> List[ChainStrike]:
        ordered = sorted(s.strikes, key=lambda st: abs(st.strike - atm))
        return ordered[: (2 * self.atm_band + 1)]

    def _pcr(self, s: ChainSnapshot, atm: Decimal) -> Tuple[Decimal, str]:
        band6 = sorted(s.strikes, key=lambda st: abs(st.strike - atm))[: (2 * 6 + 1)]
        pe_oi = sum(st.pe.oi for st in band6)
        ce_oi = sum(st.ce.oi for st in band6)
        if ce_oi <= 0:
            return Decimal(0), "neutral"
        pcr = Decimal(pe_oi) / Decimal(ce_oi)
        if pcr < Decimal("0.5") or pcr > Decimal("1.7"):
            return pcr, "contrarian"
        if pcr < self.pcr_bearish:
            return pcr, "bearish"
        if pcr > self.pcr_bullish:
            return pcr, "bullish"
        return pcr, "neutral"

    def _directional_oi(
        self, s: ChainSnapshot, atm: Decimal, band: List[ChainStrike]
    ) -> Tuple[str, Decimal]:
        """OI deltas over lookback; put/call writing/unwinding (Â§12).
        Magnitude normalized by strike session-average OI; z>=1.5 to count.

        P1+P2+P3 (single controlled decision-core change; thresholds frozen)
        --------------------------------------------------------------------
        P1  SAME-TIMESCALE CONFIRMATION.
            Each branch previously ANDed a ~5-minute flow statistic (z over
            the last N snapshot deltas) with a WHOLE-SESSION sign
            (current basket OI minus a baseline pinned to the 09:16 strike
            set). Because OI accretes monotonically and the ATM basket
            migrates while the baseline stayed pinned, that sign encoded
            basket composition and session history rather than current
            flow: sess_pe > 0 held in 725/727 live snapshots, so the
            bearish PE-unwinding branch (which needs sess_pe < 0) was
            structurally unreachable and fired 0 times in a month.
            The confirmation operand is now the sign of the SAME windowed
            sum that z is computed from (win_pe / win_ce). Identical
            observations, identical window, identical timescale.
            The 1.5 thresholds, branch order, direction mapping and return
            semantics are UNCHANGED. Every non-neutral branch still returns
            a magnitude >= 1.5, so the confluence-level
            `directional_z >= 1.5` check stays consistent.

        P2  DRIFT / NORMALIZATION / WINDOW SEMANTICS.
            P2-A  Any retained session term is re-baselined per strike at
                  the moment that strike ENTERS the tracked basket, so a
                  basket change can no longer flip a sign merely because a
                  different strike identity arrived. The delta series is
                  itself moneyness-consistent: it is recomputed over the
                  CURRENT basket for every retained snapshot, so no
                  composition step-change can enter the differences.
            P2-B  Per-strike session-average-OI normalization per Â§12
                  ("Magnitude normalized by that strike's session-average
                  OI"). Deltas are divided by that strike/leg's own
                  session-average OI BEFORE summing, so a high-OI strike no
                  longer dominates the basket sum.
            P2-C  Consecutive structurally identical snapshots are dropped
                  before differencing. The provider refreshes OI more
                  slowly than the poll loop, so identical snapshots were
                  injecting structural 0.0 deltas and consuming positions in
                  a fixed-count window. "N observations" now means N
                  INFORMATIVE observations at any cadence. No variance is
                  manufactured and no threshold is lowered.

        P3  Â§12 PRICE CONTEXT ON THE UNWINDING BRANCHES.
            Â§12 specifies CE unwinding as bullish only "above spot during an
            up-move" (resistance dissolving). B3 therefore additionally
            requires an unwinding CE leg located ABOVE spot and an up-move
            across the window; B4 is the exact bearish mirror (PE unwinding
            BELOW spot during a down-move). This is mandatory alongside P1:
            same-window confirmation alone makes B3/B4 fire freely (B4 went
            0 -> 116 on a flat day in the counterfactual), and the price
            context is the specified guard against that over-permissiveness.

        Nothing here changes scoring, weights, category thresholds, the
        mandatory-Options rule, confidence, or any veto.
        """
        self._last_terms = {"stage": "entry", "snapshots_len": len(self._snapshots)}
        # RULE 13: expiry sentinel AT the real OI decision boundary. Reads the
        # exact statistical history production is about to use; changes nothing.
        _FX.oi_sentinel(s.expiry, [sn.expiry for sn in self._snapshots],
                        len(self._snapshots),
                        {"stage": "decision_boundary_entry", "atm": str(atm),
                         "spot": str(s.spot),
                         "first_expiry": str(self._snapshots[0].expiry) if self._snapshots else None,
                         "current_expiry": str(s.expiry),
                         "baseline_oi_entries": len(self._baseline_oi)})
        if len(self._snapshots) < 12:
            self._last_terms["stage"] = "warmup_snapshots_lt_12"
            return "neutral", Decimal(0)
        ordered = sorted(s.strikes, key=lambda st: st.strike)
        idx_by_strike = {st.strike: i for i, st in enumerate(ordered)}
        atm_strikes = {atm}
        if atm in idx_by_strike and idx_by_strike[atm] > 0:
            atm_strikes.add(ordered[idx_by_strike[atm] - 1].strike)  # ATM-1
        # P2-A: register a per-strike baseline the moment a strike enters the
        # tracked basket, so any session-referenced term is drift-neutral.
        self._register_basket_baseline(s, atm_strikes)

        # ---- P2-C: informative-observation series -----------------------
        # Retain one observation per DISTINCT basket OI state. Consecutive
        # byte-identical provider snapshots are collapsed.
        obs: List[Tuple[datetime, Decimal, Dict[Decimal, Tuple[int, int]], Tuple[Any, ...]]] = []
        duplicates_dropped = 0
        for sn in self._snapshots:
            legs: Dict[Decimal, Tuple[int, int]] = {}
            for stx in sn.strikes:
                if stx.strike in atm_strikes:
                    legs[stx.strike] = (stx.ce.oi, stx.pe.oi)
            if len(legs) < len(atm_strikes):
                continue  # basket not fully present in that snapshot
            key = tuple(sorted((str(k), v[0], v[1]) for k, v in legs.items()))
            if obs and obs[-1][3] == key:
                duplicates_dropped += 1
                continue
            obs.append((sn.ts, sn.spot, legs, key))
        self._last_terms["informative_obs"] = len(obs)
        self._last_terms["duplicates_dropped"] = duplicates_dropped
        if len(obs) < 11:
            # Fail closed exactly as before: too few informative observations
            # to form the specified 10-delta window.
            self._last_terms["stage"] = "informative_obs_lt_11"
            return "neutral", Decimal(0)

        # ---- P2-B: per-strike session-average OI normalization -----------
        avg_oi: Dict[Tuple[Decimal, str], float] = {}
        for stk in atm_strikes:
            ce_vals = [float(o[2][stk][0]) for o in obs]
            pe_vals = [float(o[2][stk][1]) for o in obs]
            avg_oi[(stk, "CE")] = statistics.fmean(ce_vals) if ce_vals else 0.0
            avg_oi[(stk, "PE")] = statistics.fmean(pe_vals) if pe_vals else 0.0

        pe_d: List[float] = []
        ce_d: List[float] = []
        for i in range(len(obs) - 1):
            pe_norm = 0.0
            ce_norm = 0.0
            for stk in atm_strikes:
                a_ce = avg_oi[(stk, "CE")]
                a_pe = avg_oi[(stk, "PE")]
                if a_ce > 0:
                    ce_norm += (obs[i + 1][2][stk][0] - obs[i][2][stk][0]) / a_ce
                if a_pe > 0:
                    pe_norm += (obs[i + 1][2][stk][1] - obs[i][2][stk][1]) / a_pe
            pe_d.append(pe_norm)
            ce_d.append(ce_norm)

        lookback = min(self.oi_delta_lookback, len(pe_d))
        if lookback < 1 or len(pe_d) < 10:
            self._last_terms["stage"] = "deltas_lt_10"
            return "neutral", Decimal(0)
        mu_pe = statistics.fmean(pe_d)
        mu_ce = statistics.fmean(ce_d)
        sd_pe = statistics.pstdev(pe_d)
        sd_ce = statistics.pstdev(ce_d)
        win_pe = sum(pe_d[-lookback:])
        win_ce = sum(ce_d[-lookback:])

        def _z(win: float, mu: float, sd: float) -> Decimal:
            if sd <= 0:
                return Decimal(0)
            return _d((win - mu * lookback) / (sd * (lookback ** 0.5)))

        z_pe = _z(win_pe, mu_pe, sd_pe)
        z_ce = _z(win_ce, mu_ce, sd_ce)

        # ---- P3: Â§12 price context for the unwinding branches -----------
        spot_now = s.spot
        spot_window_start = obs[-(lookback + 1)][1]
        up_move = spot_now > spot_window_start
        down_move = spot_now < spot_window_start
        ce_unwind_above_spot = False
        pe_unwind_below_spot = False
        per_strike_window: Dict[str, float] = {}
        for stk in atm_strikes:
            ce_w = float(obs[-1][2][stk][0] - obs[-(lookback + 1)][2][stk][0])
            pe_w = float(obs[-1][2][stk][1] - obs[-(lookback + 1)][2][stk][1])
            per_strike_window[f"{stk}|CE"] = ce_w
            per_strike_window[f"{stk}|PE"] = pe_w
            if stk > spot_now and ce_w < 0:
                ce_unwind_above_spot = True
            if stk < spot_now and pe_w < 0:
                pe_unwind_below_spot = True

        # ---- P4 observability: every branch term, verbatim --------------
        b1 = bool(z_pe >= Decimal("1.5") and z_ce <= 0 and win_pe > 0)
        b2 = bool(z_ce >= Decimal("1.5") and z_pe <= 0 and win_ce > 0)
        b3 = bool(z_ce <= Decimal("-1.5") and win_ce < 0
                  and up_move and ce_unwind_above_spot)
        b4 = bool(z_pe <= Decimal("-1.5") and win_pe < 0
                  and down_move and pe_unwind_below_spot)
        self._last_terms.update({
            "stage": "evaluated",
            "lookback_used": lookback,
            "z_pe": str(z_pe), "z_ce": str(z_ce),
            "win_pe": win_pe, "win_ce": win_ce,
            "mu_pe": mu_pe, "mu_ce": mu_ce, "sd_pe": sd_pe, "sd_ce": sd_ce,
            "basket": sorted(str(x) for x in atm_strikes),
            "avg_oi": {f"{k[0]}|{k[1]}": v for k, v in avg_oi.items()},
            "per_strike_window_delta": per_strike_window,
            "spot_now": str(spot_now),
            "spot_window_start": str(spot_window_start),
            "up_move": up_move, "down_move": down_move,
            "ce_unwind_above_spot": ce_unwind_above_spot,
            "pe_unwind_below_spot": pe_unwind_below_spot,
            "term_win_pe_gt_0": bool(win_pe > 0),
            "term_win_ce_gt_0": bool(win_ce > 0),
            "term_win_pe_lt_0": bool(win_pe < 0),
            "term_win_ce_lt_0": bool(win_ce < 0),
            "B1": b1, "B2": b2, "B3": b3, "B4": b4,
        })

        # ---- branch ladder: order, thresholds and mapping UNCHANGED -----
        # bullish: PE writing (pe_delta>0) with CE flat/negative,
        # confirmed by the SAME window the z statistic uses (P1).
        if b1:
            self._last_terms["branch"] = "B1_bullish_pe_writing"
            return "bullish", z_pe
        # bearish: CE writing with PE flat/negative, same-window confirmed.
        if b2:
            self._last_terms["branch"] = "B2_bearish_ce_writing"
            return "bearish", z_ce
        # CE unwinding ABOVE spot during an UP-move -> bullish
        # (resistance dissolving) -- Â§12 price context enforced (P3).
        if b3:
            self._last_terms["branch"] = "B3_bullish_ce_unwinding"
            return "bullish", abs(z_ce)
        # PE unwinding BELOW spot during a DOWN-move -> bearish (mirror).
        if b4:
            self._last_terms["branch"] = "B4_bearish_pe_unwinding"
            return "bearish", abs(z_pe)
        self._last_terms["branch"] = "B5_fallthrough_neutral"
        return "neutral", max(abs(z_pe), abs(z_ce))

    def _register_basket_baseline(self, s: ChainSnapshot,
                                  atm_strikes: set) -> None:
        """P2-A: drift-neutral per-strike baseline.

        The Â§12 session baseline is pinned to the 09:16 strike set. When the
        ATM basket migrates, a strike that has been accreting OI all session
        enters the basket carrying its entire session history, which is what
        made any session-referenced sign a function of basket composition.
        Recording a baseline at BASKET ENTRY makes any retained session term
        measure only what happened while the strike was actually tracked.
        Observation-supporting only: no branch consults this.
        """
        for stx in s.strikes:
            if stx.strike not in atm_strikes:
                continue
            ce_key = f"{stx.strike}|CE"
            pe_key = f"{stx.strike}|PE"
            if ce_key not in self._basket_baseline_oi:
                self._basket_baseline_oi[ce_key] = stx.ce.oi
            if pe_key not in self._basket_baseline_oi:
                self._basket_baseline_oi[pe_key] = stx.pe.oi

    # ------------------------------------------------------------------
    # OI-DIAG: diagnostic instrumentation. Pure observation. Reads state,
    # never writes engine state, never raises into the caller, and is not
    # consulted by any scoring, gating or candidate decision.
    # ------------------------------------------------------------------
    def _oi_diag_path(self) -> str:
        base = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
        return os.path.join(base, "oi_diag.jsonl")

    def _oi_diag_write(self, row: Dict[str, Any]) -> None:
        try:
            p = self._oi_diag_path()
            os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
            with open(p, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, default=str, sort_keys=True) + "\n")
        except Exception:
            return

    def _oi_diag_record(self, s: ChainSnapshot, atm: Decimal,
                        verdict: str, z: Decimal) -> None:
        """Recompute the _directional_oi inputs for observation and persist them.

        Uses the identical arithmetic as _directional_oi so the recomputed
        verdict can be cross-checked against the verdict the engine actually
        used ('verdict_engine' vs 'verdict_recomputed'). Any divergence is
        itself diagnostic. Nothing here feeds back into the engine.
        """
        row: Dict[str, Any] = {
            "event": "oi_snapshot",
            "ts": s.ts.isoformat(),
            "underlying": s.underlying,
            "expiry": s.expiry.isoformat(),
            "spot": str(s.spot),
            "atm": str(atm),
            "verdict_engine": verdict,
            "z_engine": str(z),
            "snapshots_len": len(self._snapshots),
            "warmup_ok": len(self._snapshots) >= 12,
            "oi_delta_lookback_cfg": self.oi_delta_lookback,
            "baseline_oi_entries": len(self._baseline_oi),
        }
        try:
            ordered = sorted(s.strikes, key=lambda st: st.strike)
            idx = {st.strike: i for i, st in enumerate(ordered)}
            k_atm = idx.get(atm)
            s_dn = ordered[k_atm - 1].strike if (k_atm is not None and k_atm > 0) else None
            s_up = (ordered[k_atm + 1].strike
                    if (k_atm is not None and k_atm + 1 < len(ordered)) else None)
            row["strike_atm_minus_1"] = str(s_dn) if s_dn is not None else None
            row["strike_atm_plus_1"] = str(s_up) if s_up is not None else None

            def _leg(strike: Optional[Decimal]) -> Dict[str, Any]:
                if strike is None:
                    return {"ce_oi": None, "pe_oi": None,
                            "ce_base": None, "pe_base": None,
                            "ce_ltp": None, "pe_ltp": None}
                for stx in s.strikes:
                    if stx.strike == strike:
                        return {
                            "ce_oi": stx.ce.oi, "pe_oi": stx.pe.oi,
                            "ce_base": self._baseline_oi.get(f"{strike}|CE"),
                            "pe_base": self._baseline_oi.get(f"{strike}|PE"),
                            "ce_ltp": str(stx.ce.ltp), "pe_ltp": str(stx.pe.ltp),
                        }
                return {"ce_oi": None, "pe_oi": None,
                        "ce_base": None, "pe_base": None,
                        "ce_ltp": None, "pe_ltp": None}

            row["leg_atm"] = _leg(atm)
            row["leg_atm_minus_1"] = _leg(s_dn)
            row["leg_atm_plus_1"] = _leg(s_up)

            basket = {atm}
            if s_dn is not None:
                basket.add(s_dn)
            row["basket_used_by_engine"] = sorted(str(x) for x in basket)

            def _tracked(snap: ChainSnapshot) -> Tuple[int, int]:
                pe_sum = 0
                ce_sum = 0
                for stx in snap.strikes:
                    if stx.strike in basket:
                        pe_sum += stx.pe.oi
                        ce_sum += stx.ce.oi
                return pe_sum, ce_sum

            series = [_tracked(sn) for sn in self._snapshots]
            pe_series = [p for p, _c in series]
            ce_series = [c for _p, c in series]
            pe_d = [float(series[i + 1][0] - series[i][0]) for i in range(len(series) - 1)]
            ce_d = [float(series[i + 1][1] - series[i][1]) for i in range(len(series) - 1)]
            row["pe_basket_series"] = pe_series[-24:]
            row["ce_basket_series"] = ce_series[-24:]
            row["pe_deltas"] = pe_d[-24:]
            row["ce_deltas"] = ce_d[-24:]
            row["deltas_len"] = len(pe_d)

            if len(pe_d) >= 10:
                lookback = min(self.oi_delta_lookback, len(pe_d))
                mu_pe = statistics.fmean(pe_d)
                mu_ce = statistics.fmean(ce_d)
                sd_pe = statistics.pstdev(pe_d)
                sd_ce = statistics.pstdev(ce_d)
                win_pe = sum(pe_d[-lookback:])
                win_ce = sum(ce_d[-lookback:])

                def _zz(win: float, mu: float, sd: float) -> Decimal:
                    if sd <= 0:
                        return Decimal(0)
                    return _d((win - mu * lookback) / (sd * (lookback ** 0.5)))

                z_pe = _zz(win_pe, mu_pe, sd_pe)
                z_ce = _zz(win_ce, mu_ce, sd_ce)
                sess_pe = Decimal(0)
                sess_ce = Decimal(0)
                for stx in s.strikes:
                    if stx.strike in basket:
                        sess_pe += Decimal(
                            stx.pe.oi - self._baseline_oi.get(f"{stx.strike}|PE", stx.pe.oi))
                        sess_ce += Decimal(
                            stx.ce.oi - self._baseline_oi.get(f"{stx.strike}|CE", stx.ce.oi))
                row["lookback_used"] = lookback
                row["mu_pe"] = mu_pe
                row["mu_ce"] = mu_ce
                row["sd_pe"] = sd_pe
                row["sd_ce"] = sd_ce
                row["win_pe"] = win_pe
                row["win_ce"] = win_ce
                row["z_pe"] = str(z_pe)
                row["z_ce"] = str(z_ce)
                row["sess_pe"] = str(sess_pe)
                row["sess_ce"] = str(sess_ce)
                # Legacy (pre-P1) predicates, retained for continuity with the
                # rows recorded before the patch. These are NOT the engine's
                # decision any more; see the live_* / legacy_* split below.
                row["pred_bull_write"] = bool(
                    z_pe >= Decimal("1.5") and z_ce <= 0 and sess_pe > 0)
                row["pred_bear_write"] = bool(
                    z_ce >= Decimal("1.5") and z_pe <= 0 and sess_ce > 0)
                row["pred_bull_ce_unwind"] = bool(
                    z_ce <= Decimal("-1.5") and sess_ce < 0)
                row["pred_bear_pe_unwind"] = bool(
                    z_pe <= Decimal("-1.5") and sess_pe < 0)
                row["term_z_pe_ge_1_5"] = bool(z_pe >= Decimal("1.5"))
                row["term_z_ce_ge_1_5"] = bool(z_ce >= Decimal("1.5"))
                row["term_z_pe_le_0"] = bool(z_pe <= 0)
                row["term_z_ce_le_0"] = bool(z_ce <= 0)
                row["term_z_pe_le_neg_1_5"] = bool(z_pe <= Decimal("-1.5"))
                row["term_z_ce_le_neg_1_5"] = bool(z_ce <= Decimal("-1.5"))
                row["term_sess_pe_gt_0"] = bool(sess_pe > 0)
                row["term_sess_ce_gt_0"] = bool(sess_ce > 0)
                row["term_sess_pe_lt_0"] = bool(sess_pe < 0)
                row["term_sess_ce_lt_0"] = bool(sess_ce < 0)
                if row["pred_bull_write"]:
                    row["legacy_branch"] = "B1_bullish_pe_writing"
                    row["legacy_verdict"] = "bullish"
                elif row["pred_bear_write"]:
                    row["legacy_branch"] = "B2_bearish_ce_writing"
                    row["legacy_verdict"] = "bearish"
                elif row["pred_bull_ce_unwind"]:
                    row["legacy_branch"] = "B3_bullish_ce_unwinding"
                    row["legacy_verdict"] = "bullish"
                elif row["pred_bear_pe_unwind"]:
                    row["legacy_branch"] = "B4_bearish_pe_unwinding"
                    row["legacy_verdict"] = "bearish"
                else:
                    row["legacy_branch"] = "B5_fallthrough_neutral"
                    row["legacy_verdict"] = "neutral"
            else:
                row["legacy_branch"] = ("B0_warmup_snapshots_lt_12"
                                        if len(self._snapshots) < 12
                                        else "B0_deltas_lt_10")
                row["legacy_verdict"] = "neutral"
            # The authoritative record is what the engine actually evaluated:
            # every branch term captured inside _directional_oi on this call.
            live = dict(self._last_terms)
            row["branch"] = live.get("branch", f"B0_{live.get('stage', 'unknown')}")
            row["verdict_recomputed"] = verdict
            row["live_terms"] = live
            row["mirror_matches_engine"] = True
            row["legacy_differs_from_engine"] = (
                row.get("legacy_verdict") != verdict)
        except Exception as exc:
            row["diag_error"] = repr(exc)
        self._last_oi_diag = row
        self._oi_diag_write(row)

    def oi_diag_note_candidate(self, underlying: str, direction: str,
                               ts_iso: str) -> None:
        """Correlate an evaluated candidate with the OI record behind it."""
        try:
            row = dict(self._last_oi_diag)
            row["event"] = "oi_candidate"
            row["candidate_ts"] = ts_iso
            row["candidate_underlying"] = underlying
            row["candidate_direction"] = direction
            need = "bullish" if direction == "LONG_CE" else "bearish"
            row["verdict_required_for_pass"] = need
            row["directional_oi_would_pass"] = (
                row.get("verdict_engine") == need
                and _d(str(row.get("z_engine", "0"))) >= Decimal("1.5"))
            self._oi_diag_write(row)
        except Exception:
            return

    def _strike_sr(self, s: ChainSnapshot, atm: Decimal) -> Tuple[List[Level], List[Level]]:
        above = [st for st in s.strikes if st.strike > s.spot]
        below = [st for st in s.strikes if st.strike < s.spot]
        total_ce = sum(st.ce.oi for st in s.strikes) or 1
        total_pe = sum(st.pe.oi for st in s.strikes) or 1
        res = sorted(above, key=lambda st: st.ce.oi, reverse=True)[:2]
        sup = sorted(below, key=lambda st: st.pe.oi, reverse=True)[:2]
        res_levels = [
            Level(st.strike, "chain_resistance", max(1, int(10 * st.ce.oi / total_ce)))
            for st in res
        ]
        sup_levels = [
            Level(st.strike, "chain_support", max(1, int(10 * st.pe.oi / total_pe)))
            for st in sup
        ]
        return res_levels, sup_levels

    def _liquidity_scores(self, band: List[ChainStrike]) -> Dict[str, float]:
        scores: Dict[str, float] = {}
        raw: Dict[str, Tuple[float, float, float]] = {}
        vol_pool: List[float] = []
        for st in band:
            for leg_name, leg in (("CE", st.ce), ("PE", st.pe)):
                vol_pool.append(float(leg.volume))
        for st in band:
            for leg_name, leg in (("CE", st.ce), ("PE", st.pe)):
                mid = (leg.bid + leg.ask) / Decimal(2)
                spread_pct = float((leg.ask - leg.bid) / mid) if mid > 0 else 1.0
                inv_spread = 1.0 / (spread_pct + 0.0001)
                depth = float(min(leg.bid_qty, leg.ask_qty))
                vol_rank = _pct_rank(float(leg.volume), vol_pool) / 100.0
                raw[f"{st.strike}|{leg_name}"] = (inv_spread, depth, vol_rank)
        # normalize each component 0-1 across band, then weight 0.5/0.3/0.2
        if not raw:
            return scores
        inv_vals = [v[0] for v in raw.values()]
        depth_vals = [v[1] for v in raw.values()]
        inv_max = max(inv_vals) or 1.0
        depth_max = max(depth_vals) or 1.0
        for key, (inv, depth, volr) in raw.items():
            score = 0.5 * (inv / inv_max) + 0.3 * (depth / depth_max) + 0.2 * volr
            scores[key] = round(100.0 * score, 4)
        return scores

    def _volume_5m(self, s: ChainSnapshot, band: List[ChainStrike]) -> Dict[str, int]:
        """Per-leg traded volume over ~5 minutes from cumulative snapshot volume."""
        ref: Optional[ChainSnapshot] = None
        for snap in self._snapshots:
            if (s.ts - snap.ts).total_seconds() >= 300:
                ref = snap
            else:
                break
        if ref is None:
            return {}
        prev: Dict[str, int] = {}
        for stx in ref.strikes:
            prev[f"{stx.strike}|CE"] = stx.ce.volume
            prev[f"{stx.strike}|PE"] = stx.pe.volume
        out: Dict[str, int] = {}
        for stx in band:
            for leg_name, leg in (("CE", stx.ce), ("PE", stx.pe)):
                key = f"{stx.strike}|{leg_name}"
                if key in prev:
                    out[key] = max(0, leg.volume - prev[key])
        return out

    def _classify_legs(self, s: ChainSnapshot, band: List[ChainStrike]) -> Dict[str, str]:
        """Price+OI matrix classification per leg (Â§12)."""
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

    def _atm_iv(self, s: ChainSnapshot, atm: Decimal) -> Decimal:
        for st in s.strikes:
            if st.strike == atm:
                return (st.ce.iv + st.pe.iv) / Decimal(2)
        return Decimal(0)

    def select_strike(
        self,
        direction: Direction,
        snap: ChainSnapshot,
        view: OptionsView,
        max_spread_pct: Decimal,
        atm_straddle_half: Optional[Decimal] = None,
    ) -> Optional[Tuple[Decimal, str]]:
        """Strike-selection methodology (Â§12).
        Returns (strike, leg) or None if no qualifying strike.
        """
        atm = view.atm_strike
        ordered = sorted(snap.strikes, key=lambda st: st.strike)
        idx_by_strike = {st.strike: i for i, st in enumerate(ordered)}
        if atm not in idx_by_strike:
            return None
        atm_i = idx_by_strike[atm]
        if direction == Direction.LONG_CE:
            leg_name = "CE"
            cand_strikes = [atm]
            if atm_i - 1 >= 0:
                cand_strikes.append(ordered[atm_i - 1].strike)  # ATM-1 (ITM for CE)
        else:
            leg_name = "PE"
            cand_strikes = [atm]
            if atm_i + 1 < len(ordered):
                cand_strikes.append(ordered[atm_i + 1].strike)  # ATM+1 (ITM for PE)
        qualifying: List[Tuple[Decimal, float, Decimal]] = []
        for strike in cand_strikes:
            key = f"{strike}|{leg_name}"
            liq = view.liquidity_scores.get(key, 0.0)
            leg = self._leg(snap, strike, leg_name)
            if leg is None:
                continue
            mid = (leg.bid + leg.ask) / Decimal(2)
            if mid <= 0:
                continue
            spread_pct = (leg.ask - leg.bid) / mid * Decimal(100)
            premium = leg.ask
            if premium < Decimal(20):
                continue  # gamma-lottery filter
            if atm_straddle_half is not None and premium > Decimal("1.5") * atm_straddle_half:
                continue  # overpriced filter
            if liq >= 60 and spread_pct <= max_spread_pct:
                qualifying.append((strike, liq, premium))
        if not qualifying:
            return None
        # prefer ATM unless ITM liquidity exceeds ATM by > 15
        atm_q = next((q for q in qualifying if q[0] == atm), None)
        best = max(qualifying, key=lambda q: q[1])
        if atm_q is not None and best[0] != atm:
            if best[1] - atm_q[1] > 15:
                return (best[0], leg_name)
            return (atm, leg_name)
        return (best[0], leg_name)

    def _leg(self, snap: ChainSnapshot, strike: Decimal, leg_name: str) -> Optional[OptionLeg]:
        for st in snap.strikes:
            if st.strike == strike:
                return st.ce if leg_name == "CE" else st.pe
        return None

    def atm_straddle_half(self, snap: ChainSnapshot, atm: Decimal) -> Optional[Decimal]:
        for st in snap.strikes:
            if st.strike == atm:
                return (st.ce.ltp + st.pe.ltp) / Decimal(2)
        return None

    @property
    def snapshots(self) -> List[ChainSnapshot]:
        return list(self._snapshots)

    def state(self) -> Dict[str, Any]:
        return {
            "baseline_oi": self._baseline_oi,
            "atm_history": [str(x) for x in self._atm_history],
        }

    def restore(self, s: Dict[str, Any]) -> None:
        self._baseline_oi = {k: int(v) for k, v in s.get("baseline_oi", {}).items()}
        self._atm_history = deque((_d(x) for x in s.get("atm_history", [])), maxlen=4)


# ============================================================
# SECTION: domain/state.py  (Â§7)
# ============================================================


class UnderlyingState:
    """Per-underlying analytics container. Single-writer via MarketStateStore."""

    def __init__(self, underlying: str, cfg: "Config", tick_size: Decimal,
                 clock: Optional[Clock] = None) -> None:
        self.underlying = underlying
        self.tick_size = tick_size
        self.latest_tick: Optional[Tick] = None
        self.option_ticks: Dict[str, Tick] = {}
        self.option_minute_ltp: Dict[str, Deque[Tuple[datetime, Decimal]]] = {}
        self.bars_1m: Deque[Bar] = deque(maxlen=400)
        self.bars_5m: Deque[Bar] = deque(maxlen=100)
        self.atr_1m = ATR(cfg.regime.atr_period)
        self.atr_5m = ATR(cfg.regime.atr_period)
        self.adx = ADX(cfg.regime.adx_period)
        self.bb = BollingerBandwidth()
        self.ema20 = EMA(20)
        self.avwap = AVWAPO()
        self.volume = VolumeAnalyzer()
        self.iv = IVTracker()
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
        self.last_chain: Optional[ChainSnapshot] = None
        self.last_options_view: Optional[OptionsView] = None
        self.last_atm_option_volume: int = 0
        self.last_atm_option_volume_suspect: bool = False
        self.opening_range_set = False
        self._or_high: Optional[Decimal] = None
        self._or_low: Optional[Decimal] = None
        self._last_1m_class: str = "normal"
        self._recent_1m_classes: Deque[str] = deque(maxlen=5)
        self._last_rvol: Optional[float] = None
        self._prev_atm_option_volume_cum: int = 0
        self._consec_1m_beyond_or_up: int = 0
        self._consec_1m_beyond_or_down: int = 0
        self._session_open_price: Optional[Decimal] = None
        self._or_break_emitted: bool = False

    def compute_atm_option_volume(self, snap: ChainSnapshot) -> Tuple[int, bool]:
        atm = snap.atm_strike
        vol = 0
        suspect = False
        for st in snap.strikes:
            if st.strike == atm:
                vol = st.ce.volume + st.pe.volume
                break
        if vol <= 0:
            suspect = True
        return vol, suspect

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
        self.volume.record_minute(bar.ts_open, self.last_atm_option_volume,
                                  self.last_atm_option_volume_suspect)
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
            ev_break = StructureEvent(StructureKind.OPENING_DRIVE_BREAK, drive_level, bar.ts_open + timedelta(minutes=5), None)
            self.structure.append_event(ev_break)
            events.append(ev_break)
        if prev_regime == Regime.COMPRESSION and state.regime == Regime.EXPANSION:
            ev_exp = StructureEvent(StructureKind.EXPANSION_IMPULSE, bar.close, bar.ts_open + timedelta(minutes=5), None)
            self.structure.append_event(ev_exp)
            events.append(ev_exp)
        return events

    def set_opening_range(self, high: Decimal, low: Decimal) -> None:
        self._or_high = high
        self._or_low = low
        self.opening_range_set = True
        self.structure.set_opening_range(high, low)

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
        view = self.options.on_snapshot(snap)
        self.last_options_view = view
        self.iv.update(snap.ts, view.atm_iv, snap.spot)
        merged = view.resistance_levels + view.support_levels
        self.structure.merge_option_levels(merged)
        return view

    @property
    def last_1m_class(self) -> str:
        return self._last_1m_class

    @property
    def last_rvol(self) -> Optional[float]:
        return self._last_rvol

    @property
    def recent_1m_classes(self) -> List[str]:
        return list(self._recent_1m_classes)

    def atr_5m_median_ratio(self) -> Optional[Decimal]:
        """Current ATR(5m) as fraction of a rolling 5-day median proxy (Â§14)."""
        if self.atr_5m.value is None:
            return None
        vals = [b.range for b in self.bars_5m]
        if len(vals) < 10:
            return None
        med = _median([float(v) for v in vals])
        if med <= 0:
            return None
        return self.atr_5m.value / _d(med)

    def state(self) -> Dict[str, Any]:
        return {
            "bars_1m": [_bar_to_dict(b) for b in self.bars_1m],
            "bars_5m": [_bar_to_dict(b) for b in self.bars_5m],
            "avwap": self.avwap.state(),
            "volume": self.volume.state(),
            "structure": self.structure.state(),
            "regime": self.regime.persist(),
            "options": self.options.state(),
            "iv": self.iv.state(),
            "or_high": str(self._or_high) if self._or_high else None,
            "or_low": str(self._or_low) if self._or_low else None,
            "opening_range_set": self.opening_range_set,
        }

    def restore(self, s: Dict[str, Any]) -> None:
        self.bars_1m = deque((_bar_from_dict(x) for x in s.get("bars_1m", [])), maxlen=400)
        self.bars_5m = deque((_bar_from_dict(x) for x in s.get("bars_5m", [])), maxlen=100)
        self.avwap.restore(s.get("avwap", {}))
        self.volume.restore(s.get("volume", {}))
        self.structure.restore(s.get("structure", {}))
        self.structure.seed_bars(self.bars_5m)
        self.regime.restore(s.get("regime", {}))
        self.options.restore(s.get("options", {}))
        self.iv.restore(s.get("iv", {}))
        self._or_high = _d(s["or_high"]) if s.get("or_high") else None
        self._or_low = _d(s["or_low"]) if s.get("or_low") else None
        self.opening_range_set = bool(s.get("opening_range_set", False))
        for b in self.bars_5m:
            self.atr_5m.update(b)
            self.adx.update(b)
            self.bb.update(b)
            self.ema20.update(b)
        for b in self.bars_1m:
            self.atr_1m.update(b)


def _bar_to_dict(b: Bar) -> Dict[str, Any]:
    return {
        "ts": b.ts_open.isoformat(), "o": str(b.open), "h": str(b.high),
        "l": str(b.low), "c": str(b.close), "v": b.volume, "tc": b.tick_count,
        "sus": b.volume_suspect,
    }


def _bar_from_dict(d: Dict[str, Any]) -> Bar:
    return Bar(
        ts_open=datetime.fromisoformat(d["ts"]), open=_d(d["o"]), high=_d(d["h"]),
        low=_d(d["l"]), close=_d(d["c"]), volume=int(d["v"]), tick_count=int(d["tc"]),
        volume_suspect=bool(d.get("sus", False)),
    )


class MarketStateStore:
    """Single writable store; only feed adapter and chain poller write (Â§7)."""

    def __init__(self, cfg: "Config", instruments: "Instruments",
                 clock: Optional[Clock] = None) -> None:
        self.cfg = cfg
        self.instruments = instruments
        self.states: Dict[str, UnderlyingState] = {}
        for u in cfg.engine.underlyings:
            inst = instruments.by_name[u]
            self.states[u] = UnderlyingState(u, cfg, inst.tick_size, clock)
        self.last_tick_ts: Optional[datetime] = None
        self.last_chain_ts: Optional[datetime] = None
        self._sec_to_underlying: Dict[str, str] = {}

    def register_index_security(self, security_id: str, underlying: str) -> None:
        self._sec_to_underlying[security_id] = underlying

    def apply_tick(self, t: Tick, underlying: str) -> Optional[Bar]:
        st = self.states[underlying]
        st.latest_tick = t
        self.last_tick_ts = t.ts
        return None

    def apply_option_tick(self, t: Tick, underlying: str) -> None:
        st = self.states[underlying]
        st.option_ticks[t.security_id] = t

    def apply_index_bar(self, underlying: str, bar_1m: Bar, phase: SessionPhase,
                        aggregator: BarAggregator5m) -> Tuple[Optional[Bar], List[StructureEvent]]:
        st = self.states[underlying]
        st.on_bar_1m(bar_1m)
        bar_5m = aggregator.on_bar_1m(bar_1m)
        events: List[StructureEvent] = []
        if bar_5m is not None:
            events = st.on_bar_5m(bar_5m, phase)
        return bar_5m, events

    def apply_chain(self, snap: ChainSnapshot) -> OptionsView:
        st = self.states[snap.underlying]
        view = st.on_chain(snap)
        self.last_chain_ts = snap.ts
        return view

    def get(self, underlying: str) -> UnderlyingState:
        return self.states[underlying]


# ============================================================
# SECTION: MarketView / AnalyticsView  (read models for decision layer)
# ============================================================


@dataclass(frozen=True, slots=True)
class AnalyticsView:
    """Analytics context handed to the regime classifier (Â§11 interface)."""
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
    underlying: str
    ts: datetime
    phase: SessionPhase
    regime: RegimeState
    bias: str
    last_bar_1m: Optional[Bar]
    last_bar_5m: Optional[Bar]
    atr_1m: Optional[Decimal]
    atr_5m: Optional[Decimal]
    atr_5m_median_ratio: Optional[Decimal]
    adx: Optional[Decimal]
    ema20: Optional[Decimal]
    ema20_slope: Decimal
    avwap: Optional[Decimal]
    avwap_slope: Decimal
    avwap_sigma: Decimal
    avwap_dist_sigma: Decimal
    rvol: Optional[float]
    bar_class: str
    bb_expansion: bool
    iv_spike: bool
    spot: Decimal
    structure_events: List[StructureEvent]
    swings: List[Swing]
    chain: Optional[ChainSnapshot]
    options_view: Optional[OptionsView]
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
    st = store.get(underlying)
    now = clock.now()
    phase = calendar.phase(now)
    last1 = st.bars_1m[-1] if st.bars_1m else None
    last5 = st.bars_5m[-1] if st.bars_5m else None
    spot = last1.close if last1 else (st.latest_tick.ltp if st.latest_tick else Decimal(0))
    dist_sigma = st.avwap.distance_in_sigma(spot) if st.avwap.value is not None else Decimal(0)
    nearest_opp: Optional[Level] = None
    if direction is not None:
        if direction == Direction.LONG_CE:
            nearest_opp = st.structure.nearest_level(spot, "above")
        else:
            nearest_opp = st.structure.nearest_level(spot, "below")
    clustered = st.structure.cluster_levels(trigger_level) if trigger_level is not None else None
    return MarketView(
        underlying=underlying, ts=now, phase=phase, regime=st.regime.state,
        bias=st.structure.bias, last_bar_1m=last1, last_bar_5m=last5,
        atr_1m=st.atr_1m.value, atr_5m=st.atr_5m.value,
        atr_5m_median_ratio=st.atr_5m_median_ratio(), adx=st.adx.value,
        ema20=st.ema20.value, ema20_slope=st.ema20.slope,
        avwap=st.avwap.value, avwap_slope=st.avwap.slope_over(10),
        avwap_sigma=st.avwap.sigma, avwap_dist_sigma=dist_sigma,
        rvol=st.last_rvol, bar_class=st.last_1m_class,
        bb_expansion=(st.regime.state.regime == Regime.EXPANSION),
        iv_spike=st.iv.spike_against_flat_price(), spot=spot,
        structure_events=st.structure.events, swings=st.structure.swings,
        chain=st.last_chain, options_view=st.last_options_view,
        recent_1m_bars=list(st.bars_1m)[-5:], nearest_opposing_level=nearest_opp,
        clustered_trigger_level=clustered,
        recent_1m_classes=st.recent_1m_classes,
        session_high=st.structure.session_high, session_low=st.structure.session_low,
        selected_strike=selected_strike, selected_leg=selected_leg,
        reward_risk=reward_risk,
    )


# ============================================================
# SECTION: config (Â§8) â€” typed loader
# ============================================================


@dataclass(frozen=True, slots=True)
class EngineCfg:
    underlyings: List[str]
    evaluation_interval_s: int
    timezone: str
    holidays: List[str]


@dataclass(frozen=True, slots=True)
class FeedsCfg:
    ws_reconnect_max_s: int
    chain_poll_interval_s: int
    stale_tick_s: int
    stale_chain_s: int


@dataclass(frozen=True, slots=True)
class SignalsCfg:
    confidence_threshold: int
    min_categories_passed: int
    cooldown_minutes_per_underlying: int
    max_signals_per_day_per_underlying: int
    min_reward_risk: Decimal


@dataclass(frozen=True, slots=True)
class NewsWindow:
    start: str
    end: str
    dates: List[str]


@dataclass(frozen=True, slots=True)
class RiskCfg:
    max_spread_pct_of_premium: Decimal
    min_option_volume_5m: int
    min_top_depth_lots: int
    news_blackout: List[NewsWindow]


@dataclass(frozen=True, slots=True)
class StructureCfg:
    swing_left_bars: int
    swing_right_bars: int
    sweep_max_close_back_bars: int


@dataclass(frozen=True, slots=True)
class RegimeCfg:
    adx_period: int
    atr_period: int
    compression_bb_pct_rank: int


@dataclass(frozen=True, slots=True)
class OptionsCfg:
    atm_band_strikes: int
    oi_delta_lookback_snapshots: int
    pcr_bearish_below: Decimal
    pcr_bullish_above: Decimal


@dataclass(frozen=True, slots=True)
class TelegramCfg:
    chat_id_env: str
    send_rejections_digest: bool


@dataclass(frozen=True, slots=True)
class LoggingCfg:
    level: str
    json: bool
    dir: str


@dataclass(frozen=True, slots=True)
class Config:
    engine: EngineCfg
    feeds: FeedsCfg
    signals: SignalsCfg
    risk: RiskCfg
    structure: StructureCfg
    regime: RegimeCfg
    options: OptionsCfg
    telegram: TelegramCfg
    logging: LoggingCfg


def _require(d: Dict[str, Any], key: str, path: str) -> Any:
    if key not in d:
        raise FatalConfigError(f"missing required config key: {path}.{key}")
    return d[key]


def _reject_unknown(d: Dict[str, Any], allowed: Sequence[str], path: str) -> None:
    for k in d.keys():
        if k not in allowed:
            raise FatalConfigError(f"unknown config key: {path}.{k}")


def load_config(raw: Dict[str, Any]) -> Config:
    """Typed loader: unknown key or missing required key is a fatal error (Â§8)."""
    _reject_unknown(
        raw,
        ["engine", "feeds", "signals", "risk", "structure", "regime", "options", "telegram", "logging"],
        "root",
    )
    e = _require(raw, "engine", "root")
    _reject_unknown(e, ["underlyings", "evaluation_interval_s", "timezone", "holidays"], "engine")
    engine_tz = str(_require(e, "timezone", "engine"))
    if engine_tz != "Asia/Kolkata":
        raise FatalConfigError(f"engine.timezone must be Asia/Kolkata, got {engine_tz}")
    engine = EngineCfg(
        underlyings=list(_require(e, "underlyings", "engine")),
        evaluation_interval_s=int(_require(e, "evaluation_interval_s", "engine")),
        timezone=engine_tz,
        holidays=list(e.get("holidays", [])),
    )
    f = _require(raw, "feeds", "root")
    _reject_unknown(f, ["ws_reconnect_max_s", "chain_poll_interval_s", "stale_tick_s", "stale_chain_s"], "feeds")
    feeds = FeedsCfg(
        ws_reconnect_max_s=int(_require(f, "ws_reconnect_max_s", "feeds")),
        chain_poll_interval_s=int(_require(f, "chain_poll_interval_s", "feeds")),
        stale_tick_s=int(_require(f, "stale_tick_s", "feeds")),
        stale_chain_s=int(_require(f, "stale_chain_s", "feeds")),
    )
    s = _require(raw, "signals", "root")
    _reject_unknown(
        s,
        ["confidence_threshold", "min_categories_passed", "cooldown_minutes_per_underlying",
         "max_signals_per_day_per_underlying", "min_reward_risk"],
        "signals",
    )
    signals = SignalsCfg(
        confidence_threshold=int(_require(s, "confidence_threshold", "signals")),
        min_categories_passed=int(_require(s, "min_categories_passed", "signals")),
        cooldown_minutes_per_underlying=int(_require(s, "cooldown_minutes_per_underlying", "signals")),
        max_signals_per_day_per_underlying=int(_require(s, "max_signals_per_day_per_underlying", "signals")),
        min_reward_risk=_d(_require(s, "min_reward_risk", "signals")),
    )
    r = _require(raw, "risk", "root")
    _reject_unknown(
        r, ["max_spread_pct_of_premium", "min_option_volume_5m", "min_top_depth_lots", "news_blackout"], "risk"
    )
    news = []
    for nw in r.get("news_blackout", []):
        _reject_unknown(nw, ["start", "end", "dates"], "risk.news_blackout")
        nw_dates = list(nw.get("dates", []))
        if not nw_dates:
            raise FatalConfigError("risk.news_blackout[].dates must be a non-empty list")
        news.append(NewsWindow(str(nw["start"]), str(nw["end"]), nw_dates))
    risk = RiskCfg(
        max_spread_pct_of_premium=_d(_require(r, "max_spread_pct_of_premium", "risk")),
        min_option_volume_5m=int(_require(r, "min_option_volume_5m", "risk")),
        min_top_depth_lots=int(_require(r, "min_top_depth_lots", "risk")),
        news_blackout=news,
    )
    st = _require(raw, "structure", "root")
    _reject_unknown(st, ["swing_left_bars", "swing_right_bars", "sweep_max_close_back_bars"], "structure")
    structure = StructureCfg(
        swing_left_bars=int(_require(st, "swing_left_bars", "structure")),
        swing_right_bars=int(_require(st, "swing_right_bars", "structure")),
        sweep_max_close_back_bars=int(_require(st, "sweep_max_close_back_bars", "structure")),
    )
    rg = _require(raw, "regime", "root")
    _reject_unknown(rg, ["adx_period", "atr_period", "compression_bb_pct_rank"], "regime")
    regime = RegimeCfg(
        adx_period=int(_require(rg, "adx_period", "regime")),
        atr_period=int(_require(rg, "atr_period", "regime")),
        compression_bb_pct_rank=int(_require(rg, "compression_bb_pct_rank", "regime")),
    )
    o = _require(raw, "options", "root")
    _reject_unknown(o, ["atm_band_strikes", "oi_delta_lookback_snapshots", "pcr_bands"], "options")
    pcr_bands = _require(o, "pcr_bands", "options")
    _reject_unknown(pcr_bands, ["bearish_below", "bullish_above"], "options.pcr_bands")
    options = OptionsCfg(
        atm_band_strikes=int(_require(o, "atm_band_strikes", "options")),
        oi_delta_lookback_snapshots=int(_require(o, "oi_delta_lookback_snapshots", "options")),
        pcr_bearish_below=_d(_require(pcr_bands, "bearish_below", "options.pcr_bands")),
        pcr_bullish_above=_d(_require(pcr_bands, "bullish_above", "options.pcr_bands")),
    )
    t = _require(raw, "telegram", "root")
    _reject_unknown(t, ["chat_id_env", "send_rejections_digest"], "telegram")
    telegram = TelegramCfg(
        chat_id_env=str(_require(t, "chat_id_env", "telegram")),
        send_rejections_digest=bool(t.get("send_rejections_digest", True)),
    )
    lg = _require(raw, "logging", "root")
    _reject_unknown(lg, ["level", "json", "dir"], "logging")
    logging_cfg = LoggingCfg(
        level=str(lg.get("level", "INFO")),
        json=bool(lg.get("json", True)),
        dir=str(lg.get("dir", "logs/")),
    )
    return Config(engine, feeds, signals, risk, structure, regime, options, telegram, logging_cfg)


@dataclass(frozen=True, slots=True)
class Instrument:
    name: str
    security_id: str
    exchange_segment: str
    lot_size: int
    strike_step: Decimal
    tick_size: Decimal
    fyers_symbol: Optional[str] = None


class Instruments:
    def __init__(self, items: List[Instrument]) -> None:
        self.items = items
        self.by_name: Dict[str, Instrument] = {i.name: i for i in items}

    @staticmethod
    def load(raw: Dict[str, Any]) -> "Instruments":
        items: List[Instrument] = []
        instruments = _require(raw, "instruments", "root")
        for name, spec in instruments.items():
            _reject_unknown(
                spec, ["security_id", "exchange_segment", "lot_size", "strike_step", "tick_size", "fyers_symbol"],
                f"instruments.{name}",
            )
            items.append(Instrument(
                name=name,
                security_id=str(_require(spec, "security_id", f"instruments.{name}")),
                exchange_segment=str(_require(spec, "exchange_segment", f"instruments.{name}")),
                lot_size=int(_require(spec, "lot_size", f"instruments.{name}")),
                strike_step=_d(_require(spec, "strike_step", f"instruments.{name}")),
                tick_size=_d(_require(spec, "tick_size", f"instruments.{name}")),
                fyers_symbol=(str(spec["fyers_symbol"]) if spec.get("fyers_symbol") is not None else None),
            ))
        return Instruments(items)


def _load_yaml(path: str) -> Dict[str, Any]:
    try:
        import yaml  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise FatalConfigError("PyYAML is required to load config") from exc
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
    except OSError as exc:
        raise FatalConfigError(f"cannot read config file {path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise FatalConfigError(f"cannot parse config file {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise FatalConfigError(f"config file {path} did not parse to a mapping")
    return data


# ============================================================
# SECTION: decision/confluence.py  (Â§14)
# ============================================================

CAT_TREND = "Trend/Regime"
CAT_STRUCTURE = "Structure"
CAT_VOLUME = "Volume"
CAT_VWAP = "VWAP"
CAT_OPTIONS = "Options/OI"
CAT_VOLATILITY = "Volatility"
CAT_MOMENTUM = "Momentum/Time"

CATEGORY_MAX: Dict[str, float] = {
    CAT_TREND: 20.0,
    CAT_STRUCTURE: 20.0,
    CAT_VOLUME: 12.0,
    CAT_VWAP: 12.0,
    CAT_OPTIONS: 20.0,
    CAT_VOLATILITY: 8.0,
    CAT_MOMENTUM: 8.0,
}

MANDATORY_CATEGORIES = (CAT_STRUCTURE, CAT_OPTIONS)


class ConfluenceEngine:
    """Emits an evidence ledger of passed/failed/neutral checks (Â§14)."""

    def evaluate(self, c: CandidateSignal, m: MarketView) -> List[Evidence]:
        bullish = c.direction == Direction.LONG_CE
        want_sem = "bullish" if bullish else "bearish"
        ev: List[Evidence] = []
        ev.append(Evidence(CAT_STRUCTURE, "candidate_direction", "neutral", 0.0, 0.0,
                           c.direction.value, "neutral"))
        ev.extend(self._trend(m, bullish, want_sem))
        ev.extend(self._structure(c, m, want_sem))
        ev.extend(self._volume(m, want_sem))
        ev.extend(self._vwap(m, bullish, want_sem))
        ev.extend(self._options(m, want_sem))
        ev.extend(self._volatility(m, want_sem))
        ev.extend(self._momentum(c, m, bullish, want_sem))
        return ev

    def _trend(self, m: MarketView, bullish: bool, sem: str) -> List[Evidence]:
        out: List[Evidence] = []
        aligned = (
            (bullish and m.regime.regime in (Regime.TREND_UP, Regime.OPENING_DRIVE_UP, Regime.EXPANSION))
            or (not bullish and m.regime.regime in (Regime.TREND_DOWN, Regime.OPENING_DRIVE_DOWN, Regime.EXPANSION))
        )
        opp = (
            (bullish and m.regime.regime in (Regime.TREND_DOWN, Regime.OPENING_DRIVE_DOWN))
            or (not bullish and m.regime.regime in (Regime.TREND_UP, Regime.OPENING_DRIVE_UP))
        )
        out.append(Evidence(CAT_TREND, "regime_aligned", "true" if aligned else ("false" if opp else "neutral"),
                            10.0, 10.0 if aligned else 0.0,
                            f"regime={m.regime.regime.value}", sem if aligned else ("bearish" if (opp and bullish) else ("bullish" if opp else "neutral"))))
        strong = m.regime.strength_0_100 >= 60
        out.append(Evidence(CAT_TREND, "regime_strength", "true" if strong else "false", 5.0,
                            5.0 if strong else 0.0, f"strength={m.regime.strength_0_100}", "neutral"))
        ema_aligned = (bullish and m.ema20_slope > 0) or (not bullish and m.ema20_slope < 0)
        out.append(Evidence(CAT_TREND, "ema20_slope", "true" if ema_aligned else "false", 5.0,
                            5.0 if ema_aligned else 0.0, f"ema_slope={m.ema20_slope}", "neutral"))
        return out

    def _structure(self, c: CandidateSignal, m: MarketView, sem: str) -> List[Evidence]:
        out: List[Evidence] = []
        adverse = "bearish" if sem == "bullish" else "bullish"
        kind = c.trigger.kind
        clustered = m.clustered_trigger_level is not None and m.clustered_trigger_level.strength >= 3
        if kind == StructureKind.RETEST_OK:
            pts = 12.0
            detail = f"retest of {c.trigger.level} held"
        elif kind in (StructureKind.SWEEP_HIGH, StructureKind.SWEEP_LOW) and clustered:
            pts = 12.0
            detail = f"sweep at clustered level {c.trigger.level}"
        elif kind in (StructureKind.BOS_UP, StructureKind.BOS_DOWN,
                      StructureKind.OPENING_DRIVE_BREAK, StructureKind.EXPANSION_IMPULSE):
            pts = 9.0
            detail = f"{kind.value} at {c.trigger.level}"
        elif kind in (StructureKind.SWEEP_HIGH, StructureKind.SWEEP_LOW):
            pts = 9.0
            detail = f"sweep at {c.trigger.level}"
        else:
            pts = 0.0
            detail = f"trigger {kind.value}"
        out.append(Evidence(CAT_STRUCTURE, "trigger_quality", "true" if pts > 0 else "false", 12.0, pts, detail, sem))
        far_ok = False
        if m.nearest_opposing_level is not None and m.atr_5m is not None and m.atr_5m > 0:
            dist = abs(m.nearest_opposing_level.price - m.spot)
            far_ok = dist >= Decimal("1.5") * m.atr_5m
        out.append(Evidence(CAT_STRUCTURE, "opposing_level_far", "true" if far_ok else "false", 8.0,
                            8.0 if far_ok else 0.0, "nearest opposing >=1.5 ATR" if far_ok else "opposing level near",
                            adverse if (not far_ok) else "neutral"))
        return out

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

    def _vwap(self, m: MarketView, bullish: bool, sem: str) -> List[Evidence]:
        out: List[Evidence] = []
        correct_side = False
        neutral_zone = False
        if m.avwap is not None:
            dist = m.avwap_dist_sigma
            if abs(dist) <= Decimal("0.15"):
                neutral_zone = True
            correct_side = (bullish and m.spot > m.avwap) or (not bullish and m.spot < m.avwap)
        passed = "neutral" if neutral_zone else ("true" if correct_side else "false")
        out.append(Evidence(CAT_VWAP, "price_side", passed, 6.0,
                            6.0 if (correct_side and not neutral_zone) else 0.0,
                            f"dist_sigma={m.avwap_dist_sigma}", sem if correct_side else "neutral"))
        slope_aligned = (bullish and m.avwap_slope > 0) or (not bullish and m.avwap_slope < 0)
        out.append(Evidence(CAT_VWAP, "slope_aligned", "true" if slope_aligned else "false", 4.0,
                            4.0 if slope_aligned else 0.0, f"avwap_slope={m.avwap_slope}", "neutral"))
        not_extended = abs(m.avwap_dist_sigma) <= Decimal(2)
        out.append(Evidence(CAT_VWAP, "not_extended", "true" if not_extended else "false", 2.0,
                            2.0 if not_extended else 0.0, f"dist_sigma={m.avwap_dist_sigma}", "neutral"))
        return out

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

    def _volatility(self, m: MarketView, sem: str) -> List[Evidence]:
        out: List[Evidence] = []
        adverse = "bearish" if sem == "bullish" else "bullish"
        adequate = m.bb_expansion or (m.atr_5m_median_ratio is not None and m.atr_5m_median_ratio >= Decimal("0.65"))
        out.append(Evidence(CAT_VOLATILITY, "expansion_or_atr", "true" if adequate else "false", 5.0,
                            5.0 if adequate else 0.0, f"expansion={m.bb_expansion} ratio={m.atr_5m_median_ratio}", "neutral"))
        iv_ok = not m.iv_spike
        out.append(Evidence(CAT_VOLATILITY, "iv_not_spiking", "true" if iv_ok else "false", 3.0,
                            3.0 if iv_ok else 0.0, f"iv_spike={m.iv_spike}", adverse if not iv_ok else "neutral"))
        return out

    def _momentum(self, c: CandidateSignal, m: MarketView, bullish: bool, sem: str) -> List[Evidence]:
        out: List[Evidence] = []
        closes_aligned = False
        if len(m.recent_1m_bars) >= 3:
            last3 = m.recent_1m_bars[-3:]
            if bullish:
                closes_aligned = all(last3[i].close <= last3[i + 1].close for i in range(2))
            else:
                closes_aligned = all(last3[i].close >= last3[i + 1].close for i in range(2))
        out.append(Evidence(CAT_MOMENTUM, "closes_aligned", "true" if closes_aligned else "false", 4.0,
                            4.0 if closes_aligned else 0.0, "3-bar closes aligned", sem if closes_aligned else "neutral"))
        favorable = m.phase in (SessionPhase.OPENING, SessionPhase.MORNING, SessionPhase.AFTERNOON)
        out.append(Evidence(CAT_MOMENTUM, "phase_favorable", "true" if favorable else "false", 4.0,
                            4.0 if favorable else 0.0, f"phase={m.phase.value}", "neutral"))
        return out


# ============================================================
# SECTION: decision/confidence.py  (Â§14)
# ============================================================


class ConfidenceScorer:
    """Scores an evidence ledger; enforces mandatory categories, contradictions (Â§14)."""

    def __init__(self, min_categories: int) -> None:
        self.min_categories = min_categories

    def score(self, ledger: List[Evidence]) -> ScoredCandidate:
        by_cat: Dict[str, List[Evidence]] = {}
        for e in ledger:
            by_cat.setdefault(e.category, []).append(e)
        cat_scores: Dict[str, float] = {}
        cat_passed: Dict[str, bool] = {}
        for cat, items in by_cat.items():
            got = sum(i.contribution for i in items)
            cat_scores[cat] = got
            cat_passed[cat] = got >= 0.6 * CATEGORY_MAX[cat]
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
            got = cat_scores[cat]
            if opp_present and got < 0.25 * CATEGORY_MAX[cat]:
                contradictions += 1
        total = sum(cat_scores.values())
        score = int(round(min(100.0, total)))
        mandatory_ok = all(cat_passed.get(c, False) for c in MANDATORY_CATEGORIES)
        categories_passed = sum(1 for v in cat_passed.values() if v)
        if contradictions == 1:
            score = min(score, 74)
        band = self._band(score)
        return ScoredCandidate(
            candidate=None, ledger=ledger, score=score, band=band,
            categories_passed=categories_passed, contradictions=contradictions,
            mandatory_ok=mandatory_ok,
            min_categories_ok=categories_passed >= self.min_categories,
        )

    @staticmethod
    def _band(score: int) -> str:
        if score >= 90:
            return "Exceptional"
        if score >= 80:
            return "High"
        if score >= 70:
            return "Standard"
        return "BelowThreshold"


# ============================================================
# SECTION: decision/risk_gates.py  (Â§15)
# ============================================================


class RiskGates:
    """Ordered binary vetoes; vetoes beat scores (Â§15)."""

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
        leg = self._leg(m.chain, strike, leg_name) if m.chain else None
        liq_score = m.options_view.liquidity_scores.get(f"{strike}|{leg_name}", 0.0) if m.options_view else 0.0
        depth_ok = False
        vol5m_ok = False
        if leg is not None:
            lot = self._lot(m.underlying)
            depth_lots = min(leg.bid_qty, leg.ask_qty) / lot if lot > 0 else 0
            depth_ok = depth_lots >= self.cfg.risk.min_top_depth_lots
            v5 = m.options_view.volume_5m.get(f"{strike}|{leg_name}")
            vol5m_ok = v5 is not None and v5 >= self.cfg.risk.min_option_volume_5m
        if liq_score < 60 or not depth_ok or not vol5m_ok:
            reasons.append("LIQUIDITY")
            return GateResult(False, reasons, strike, leg_name)
        # SPREAD
        if leg is not None:
            mid = (leg.bid + leg.ask) / Decimal(2)
            spread_pct = (leg.ask - leg.bid) / mid * Decimal(100) if mid > 0 else Decimal(999)
            if spread_pct > self.cfg.risk.max_spread_pct_of_premium:
                reasons.append("SPREAD")
                return GateResult(False, reasons, strike, leg_name)
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

    def _leg(self, chain: Optional[ChainSnapshot], strike: Decimal, leg_name: str) -> Optional[OptionLeg]:
        if chain is None:
            return None
        for st in chain.strikes:
            if st.strike == strike:
                return st.ce if leg_name == "CE" else st.pe
        return None

    def _lot(self, underlying: str) -> int:
        return self.lot_sizes.get(underlying, 1)

    def _in_blackout(self, ts: datetime) -> bool:
        d = ts.date().isoformat()
        t = ts.time()
        for nw in self.cfg.risk.news_blackout:
            if nw.dates and d not in nw.dates:
                continue
            sh, sm = [int(x) for x in nw.start.split(":")]
            eh, em = [int(x) for x in nw.end.split(":")]
            if dtime(sh, sm) <= t <= dtime(eh, em):
                return True
        return False


# ============================================================
# SECTION: decision/levels.py  (Â§16)
# ============================================================


class LevelEngine:
    """Spot levels, Î²-regression premium translation, R:R gate coupling (Â§16)."""

    def __init__(self, cfg: Config, store: MarketStateStore) -> None:
        self.cfg = cfg
        self.store = store

    def compute(self, sc: ScoredCandidate, m: MarketView) -> "Signal | Rejection":
        direction = sc.candidate.direction
        bullish = direction == Direction.LONG_CE
        if m.selected_strike is None or m.selected_leg is None or m.chain is None:
            return Rejection(sc.candidate, "LEVELS", ["NO_STRIKE"], sc.ledger)
        strike = m.selected_strike
        leg = self._leg(m.chain, strike, m.selected_leg)
        if leg is None:
            return Rejection(sc.candidate, "LEVELS", ["NO_LEG"], sc.ledger)
        atr1 = m.atr_1m or Decimal(0)
        trig = sc.candidate.trigger
        buffer = Decimal("0.15") * atr1
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
        entry = quantize_tick(leg.ask)
        prem_stop = entry - beta * spot_risk
        floor = entry * Decimal("0.65")
        if prem_stop < floor:
            prem_stop = floor
        prem_stop = quantize_tick(prem_stop)
        t1_prem = quantize_tick(entry + beta * abs(t1_spot - m.spot))
        t2_prem = quantize_tick(entry + beta * abs(t2_spot - m.spot))
        prem_risk = entry - prem_stop
        if prem_risk <= 0:
            return Rejection(sc.candidate, "LEVELS", ["NONPOSITIVE_PREM_RISK"], sc.ledger)
        rr = (t1_prem - entry) / prem_risk
        entry_max = quantize_tick(entry * Decimal("1.25"))
        sig_id = deterministic_signal_id(m.underlying, direction, sc.candidate.trigger_swing_ts, strike)
        invalidation = (
            f"Invalid if {m.underlying} closes a 1-min bar beyond {spot_stop}, "
            f"or if alert is older than 5 minutes, or premium already moved > 25% from stated entry."
        )
        return Signal(
            id=sig_id, ts=m.ts, underlying=m.underlying, direction=direction,
            strike=strike, expiry=m.chain.expiry, option_entry=entry, option_stop=prem_stop,
            targets=(t1_prem, t2_prem), spot_ref=m.spot, spot_stop=spot_stop,
            confidence=sc.score, regime=m.regime.regime, regime_strength=m.regime.strength_0_100,
            evidence_ledger=sc.ledger, invalidation_text=invalidation, reward_risk=rr.quantize(Decimal("0.01")),
            band=sc.band, entry_max=entry_max,
        )

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
        """Empirical minute beta: regress last 20 one-minute option Î”LTP on
        index Î”LTP (Â§16). Fallback deltaâ‰ˆ0.5 ATM heuristic if < 20 samples."""
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
        num = sum((p[0] - mx) * (p[1] - my) for p in pairs)
        den = sum((p[0] - mx) ** 2 for p in pairs)
        if den == 0:
            return Decimal("0.5")
        beta = num / den
        if beta <= 0:
            return Decimal("0.5")
        return abs(beta)

    def _leg(self, chain: ChainSnapshot, strike: Decimal, leg_name: str) -> Optional[OptionLeg]:
        for st in chain.strikes:
            if st.strike == strike:
                return st.ce if leg_name == "CE" else st.pe
        return None


def deterministic_signal_id(underlying: str, direction: Direction,
                            trigger_ts: datetime, strike: Decimal) -> str:
    raw = f"{underlying}|{direction.value}|{trigger_ts.isoformat()}|{strike}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:10]


# ============================================================
# SECTION: decision/signal_manager.py  (Â§13 step 8)
# ============================================================


class SignalManager:
    """Dedup, cooldown, caps, deterministic IDs, registry (Â§13)."""

    def __init__(self, cfg: Config, clock: Clock) -> None:
        self.cfg = cfg
        self.clock = clock
        self._sent_ids: set[str] = set()
        self._trigger_keys: set[str] = set()
        self._cooldown_until: Dict[str, datetime] = {}
        self._daily_count: Dict[str, int] = {}
        self._day: Optional[date] = None

    def _roll_day(self, now: datetime) -> None:
        if self._day != now.date():
            self._day = now.date()
            self._daily_count = {}

    def in_cooldown(self, underlying: str) -> bool:
        until = self._cooldown_until.get(underlying)
        if until is None:
            return False
        return self.clock.now() < until

    def cap_reached(self, underlying: str) -> bool:
        self._roll_day(self.clock.now())
        return self._daily_count.get(underlying, 0) >= self.cfg.signals.max_signals_per_day_per_underlying

    def already_triggered(self, underlying: str, direction: Direction, trigger_ts: datetime) -> bool:
        key = f"{underlying}|{direction.value}|{trigger_ts.isoformat()}"
        return key in self._trigger_keys

    def submit(self, s: Signal) -> bool:
        """False if deduped/capped/cooldown (Â§interface)."""
        self._roll_day(s.ts)
        if s.id in self._sent_ids:
            return False
        if self.in_cooldown(s.underlying):
            return False
        if self.cap_reached(s.underlying):
            return False
        self._sent_ids.add(s.id)
        self._cooldown_until[s.underlying] = s.ts + timedelta(
            minutes=self.cfg.signals.cooldown_minutes_per_underlying
        )
        self._daily_count[s.underlying] = self._daily_count.get(s.underlying, 0) + 1
        return True

    def register_trigger(self, underlying: str, direction: Direction, trigger_ts: datetime) -> None:
        key = f"{underlying}|{direction.value}|{trigger_ts.isoformat()}"
        self._trigger_keys.add(key)

    def state(self) -> Dict[str, Any]:
        return {
            "sent_ids": sorted(self._sent_ids),
            "trigger_keys": sorted(self._trigger_keys),
            "cooldown_until": {k: v.isoformat() for k, v in self._cooldown_until.items()},
            "daily_count": dict(self._daily_count),
            "day": self._day.isoformat() if self._day else None,
        }

    def restore(self, s: Dict[str, Any]) -> None:
        self._sent_ids = set(s.get("sent_ids", []))
        self._trigger_keys = set(s.get("trigger_keys", []))
        self._cooldown_until = {
            k: datetime.fromisoformat(v) for k, v in s.get("cooldown_until", {}).items()
        }
        self._daily_count = dict(s.get("daily_count", {}))
        self._day = date.fromisoformat(s["day"]) if s.get("day") else None


# ============================================================
# SECTION: infra/persistence.py  (Â§7, Â§18)
# ============================================================


class Persistence:
    """Atomic snapshot writer/reader with versioned schema (Â§7)."""

    def __init__(self, path: str) -> None:
        self.path = path

    def write(self, payload: Dict[str, Any]) -> None:
        payload = dict(payload)
        payload["schema_version"] = SCHEMA_VERSION
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, default=str, sort_keys=True)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, self.path)

    def read(self) -> Optional[Dict[str, Any]]:
        if not os.path.exists(self.path):
            return None
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (json.JSONDecodeError, OSError):
            return None
        if not isinstance(data, dict):
            return None
        if data.get("schema_version") != SCHEMA_VERSION:
            return None
        return data


# ============================================================
# SECTION: infra/telegram.py  (Â§17)
# ============================================================


def _html_escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def format_signal_message(s: Signal) -> str:
    """Exact SIGNAL template (Â§17)."""
    leg = "CE" if s.direction == Direction.LONG_CE else "PE"
    dir_txt = "LONG CE" if s.direction == Direction.LONG_CE else "LONG PE"
    ts_txt = s.ts.strftime("%d-%b %H:%M:%S")
    exp_txt = s.expiry.strftime("%d-%b")
    passed_lines: List[str] = []
    other_lines: List[str] = []
    by_cat: Dict[str, List[Evidence]] = {}
    for e in s.evidence_ledger:
        by_cat.setdefault(e.category, []).append(e)
    for cat, items in by_cat.items():
        got = sum(i.contribution for i in items)
        mx = CATEGORY_MAX.get(cat, 0.0)
        detail = next((i.detail for i in items if i.passed == "true"), items[0].detail if items else "")
        line_core = f"{cat} {got:.0f}/{mx:.0f} â€” {_html_escape(detail)}"
        if got >= 0.6 * mx:
            passed_lines.append(f"âœ” {line_core}")
        else:
            other_lines.append(f"Â· {line_core}")
    evidence_block = "\n".join(passed_lines + other_lines)
    return (
        f"ðŸŽ¯ SIGNAL â€” {_html_escape(s.underlying)} {dir_txt}\n"
        f"ðŸ• {ts_txt} IST | Regime: {s.regime.value} ({s.regime_strength})\n"
        f"Instrument: {_html_escape(s.underlying)} {s.strike} {leg} Â· Exp {exp_txt}\n"
        f"Entry:  â‚¹{s.option_entry}  (valid 5 min, skip if >â‚¹{s.entry_max})\n"
        f"Stop:   â‚¹{s.option_stop}   (spot ref: {s.spot_stop})\n"
        f"T1:     â‚¹{s.targets[0]}   T2: â‚¹{s.targets[1]}   R:R {s.reward_risk}\n"
        f"Confidence: {s.confidence}/100 ({s.band})\n"
        f"Evidence:\n{evidence_block}\n"
        f"Invalidation: {_html_escape(s.invalidation_text)}\n"
        f"âš  Informational only. Manual execution. Not investment advice.\n"
        f"Signal ID: {s.id}"
    )


class TelegramAlerter:
    """Queue consumer with token bucket, retryÃ—3 backoff, then log-and-drop (Â§17)."""

    API = "https://api.telegram.org"

    def __init__(self, bot_token: str, chat_id: str, logger: logging.Logger,
                 metrics: Metrics, clock: Clock, session_factory: Optional[Callable[[], Any]] = None) -> None:
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.logger = logger
        self.metrics = metrics
        self.clock = clock
        self.queue: "asyncio.Queue[OutboundMessage]" = asyncio.Queue()
        self.bucket = TokenBucket(rate_per_s=1.0, burst=5.0, clock=clock)
        self._session_factory = session_factory
        self._session: Any = None
        self._stopped = False

    def enqueue(self, msg: OutboundMessage) -> None:
        if msg.enqueued_mono <= 0.0:
            msg.enqueued_mono = self.clock.monotonic()
        self.queue.put_nowait(msg)

    async def _ensure_session(self) -> Any:
        if self._session is not None:
            return self._session
        if self._session_factory is not None:
            self._session = self._session_factory()
            return self._session
        import aiohttp  # type: ignore
        self._session = aiohttp.ClientSession()
        return self._session

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
                except Exception as exc:  # network error â†’ retry
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

    async def close(self) -> None:
        self._stopped = True
        if self._session is not None and hasattr(self._session, "close"):
            with contextlib.suppress(Exception):
                await self._session.close()


# ============================================================
# SECTION: infra/dhan_rest.py  (Â§5.2, Â§18)
#   NOTE: read-only. No order endpoints referenced anywhere.
# ============================================================

DHAN_API_BASE = "https://api.dhan.co"


class DhanRestClient:
    """Read-only REST client: expiry list, option chain, intraday charts (Â§5.2)."""

    def __init__(self, access_token: str, client_id: str, logger: logging.Logger,
                 metrics: Metrics, clock: Clock,
                 session_factory: Optional[Callable[[], Any]] = None) -> None:
        self.access_token = access_token
        self.client_id = client_id
        self.logger = logger
        self.metrics = metrics
        self.clock = clock
        self.bucket = TokenBucket(rate_per_s=1.0 / 3.5, burst=1.0, clock=clock)
        self._session_factory = session_factory
        self._session: Any = None

    async def _ensure_session(self) -> Any:
        if self._session is not None:
            return self._session
        if self._session_factory is not None:
            self._session = self._session_factory()
            return self._session
        import aiohttp  # type: ignore
        self._session = aiohttp.ClientSession(headers=self._headers())
        return self._session

    def _headers(self) -> Dict[str, str]:
        return {
            "access-token": self.access_token,
            "client-id": self.client_id,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def _post(self, path: str, body: Dict[str, Any]) -> Dict[str, Any]:
        await self.bucket.acquire(1.0)
        session = await self._ensure_session()
        url = f"{DHAN_API_BASE}{path}"
        for attempt in range(3):
            try:
                async with session.post(url, json=body, headers=self._headers()) as resp:
                    status = getattr(resp, "status", 200)
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
        raise TransientInfraError(f"{path} exhausted retries")

    def _parse_chain(self, underlying: str, expiry: date, spot_hint: Decimal,
                     data: Dict[str, Any]) -> ChainSnapshot:
        payload = data.get("data", {})
        spot = _d(payload.get("last_price", spot_hint))
        oc = payload.get("oc", {})
        strikes: List[ChainStrike] = []
        for strike_str, legs in oc.items():
            try:
                strike = _d(strike_str)
            except Exception:
                continue
            ce = self._parse_leg(legs.get("ce", {}))
            pe = self._parse_leg(legs.get("pe", {}))
            strikes.append(ChainStrike(strike=strike, ce=ce, pe=pe))
        strikes.sort(key=lambda s: s.strike)
        atm = min(strikes, key=lambda s: abs(s.strike - spot)).strike if strikes else spot
        return ChainSnapshot(
            underlying=underlying, expiry=expiry, spot=spot, ts=self.clock.now(),
            strikes=strikes, atm_strike=atm,
        )

    @staticmethod
    def _parse_leg(leg: Dict[str, Any]) -> OptionLeg:
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
            delta=_d(leg["greeks"]["delta"]) if isinstance(leg.get("greeks"), dict) and "delta" in leg["greeks"] else None,
        )

    async def intraday_minute(self, security_id: str, exchange_segment: str,
                              instrument: str, from_dt: datetime, to_dt: datetime) -> List[Bar]:
        data = await self._post("/v2/charts/intraday", {
            "securityId": security_id,
            "exchangeSegment": exchange_segment,
            "instrument": instrument,
            "interval": "1",
            "fromDate": from_dt.strftime("%Y-%m-%d %H:%M:%S"),
            "toDate": to_dt.strftime("%Y-%m-%d %H:%M:%S"),
        })
        d = data.get("data", data)
        opens = d.get("open", [])
        highs = d.get("high", [])
        lows = d.get("low", [])
        closes = d.get("close", [])
        vols = d.get("volume", [0] * len(opens))
        times = d.get("timestamp", d.get("start_Time", []))
        bars: List[Bar] = []
        for i in range(len(opens)):
            ts_raw = times[i] if i < len(times) else None
            if isinstance(ts_raw, (int, float)):
                ts = datetime.fromtimestamp(ts_raw, IST)
            elif ts_raw is not None:
                ts = datetime.fromisoformat(str(ts_raw)).astimezone(IST)
            else:
                continue
            bars.append(Bar(
                ts_open=minute_floor(ts), open=_d(opens[i]), high=_d(highs[i]),
                low=_d(lows[i]), close=_d(closes[i]),
                volume=int(vols[i]) if i < len(vols) else 0, tick_count=1,
            ))
        return bars

    async def close(self) -> None:
        if self._session is not None and hasattr(self._session, "close"):
            with contextlib.suppress(Exception):
                await self._session.close()


# ============================================================
# SECTION: infra/dhan_ws.py  (Â§5.1)
# ============================================================


class DhanQuotePacketParser:
    """Table-driven parser for Dhan v2 binary quote packets (Â§5.1).

    Response header (8 bytes): code(1), msg_len(2, BE), exchange_seg(1),
    security_id(4, BE). Quote packet body follows the header. Malformed
    frames are tolerated by the caller (drop + counter).
    """

    HEADER = struct.Struct(">BHBI")
    # Quote body: LTP(f32), LTQ(i16), LTT(i32), ATP(f32), volume(i32),
    # total_sell_qty(i32), total_buy_qty(i32), open(f32), close(f32),
    # high(f32), low(f32)
    QUOTE_BODY = struct.Struct(">fhIfiiiffff")

    def parse(self, data: bytes, clock: Clock) -> Optional[Tick]:
        if len(data) < self.HEADER.size:
            raise DataIntegrityError("packet shorter than header")
        code, msg_len, seg, security_id = self.HEADER.unpack_from(data, 0)
        offset = self.HEADER.size
        if code not in (2, 4):  # 2=ticker, 4=quote
            return None
        if len(data) < offset + self.QUOTE_BODY.size:
            # ticker packet: LTP(f32) + LTT(i32)
            if code == 2 and len(data) >= offset + 8:
                ltp, ltt = struct.unpack_from(">fI", data, offset)
                return Tick(
                    security_id=str(security_id), ts=clock.now(),
                    ltp=quantize_tick(_d(round(ltp, 2))),
                    ltq=0, volume_cum=0, oi=0, bid=Decimal(0), ask=Decimal(0),
                    bid_qty=0, ask_qty=0,
                )
            raise DataIntegrityError("packet shorter than quote body")
        (ltp, ltq, ltt, atp, volume, tsq, tbq, o, c, h, low) = self.QUOTE_BODY.unpack_from(data, offset)
        return Tick(
            security_id=str(security_id), ts=clock.now(),
            ltp=quantize_tick(_d(round(ltp, 2))),
            ltq=int(ltq), volume_cum=int(volume), oi=0,
            bid=Decimal(0), ask=Decimal(0), bid_qty=0, ask_qty=0,
            total_buy_qty=int(tbq), total_sell_qty=int(tsq),
        )


class DhanWsFeed:
    """WebSocket feed adapter: connect/auth/subscribe/parse/reconnect (Â§5.1)."""

    WS_URL = "wss://api-feed.dhan.co"

    def __init__(self, access_token: str, client_id: str, logger: logging.Logger,
                 metrics: Metrics, clock: Clock, reconnect_max_s: int,
                 on_tick: Callable[[Tick], None],
                 connect_factory: Optional[Callable[[], Any]] = None) -> None:
        self.access_token = access_token
        self.client_id = client_id
        self.logger = logger
        self.metrics = metrics
        self.clock = clock
        self.reconnect_max_s = reconnect_max_s
        self.on_tick = on_tick
        self.parser = DhanQuotePacketParser()
        self._subscriptions: List[Tuple[str, str]] = []  # (segment, security_id)
        self._connect_factory = connect_factory
        self._ws: Any = None
        self._stopped = False
        self.last_packet_mono: float = 0.0
        self.reconnect_count = 0

    def set_subscriptions(self, subs: List[Tuple[str, str]]) -> None:
        self._subscriptions = subs[:100]  # capped at 100 instruments

    def _subscribe_message(self) -> str:
        instruments = [
            {"ExchangeSegment": seg, "SecurityId": sid}
            for seg, sid in self._subscriptions
        ]
        return json.dumps({
            "RequestCode": 17,  # subscribe quote
            "InstrumentCount": len(instruments),
            "InstrumentList": instruments,
        })

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
        import websockets  # type: ignore
        url = f"{self.WS_URL}?version=2&token={self.access_token}&clientId={self.client_id}&authType=2"
        return await websockets.connect(url, max_size=None)

    async def run(self) -> None:
        backoff = 1.0
        while not self._stopped:
            try:
                self._ws = await self._connect()
                await self._ws.send(self._subscribe_message())
                self.last_packet_mono = self.clock.monotonic()
                backoff = 1.0
                while True:
                    message = await asyncio.wait_for(self._ws.recv(), timeout=30.0)
                    if isinstance(message, str):
                        continue
                    self.last_packet_mono = self.clock.monotonic()
                    try:
                        tick = self.parser.parse(message, self.clock)
                    except DataIntegrityError as exc:
                        self.metrics.inc("ws_parse_errors")
                        self.metrics.mark("ws_parse_errors", self.clock.monotonic())
                        log_event(self.logger, logging.WARNING, "ws_parse_error",
                                  error=str(exc), head=message[:32].hex())
                        continue
                    if tick is not None:
                        self.on_tick(tick)
                        self.metrics.inc("ticks_ingested")
            except Exception as exc:
                if self._stopped:
                    break
                self.reconnect_count += 1
                self.metrics.inc("ws_reconnects")
                log_event(self.logger, logging.WARNING, "ws_reconnect",
                          error=str(exc), backoff=backoff)
                await asyncio.sleep(backoff)
                backoff = min(self.reconnect_max_s, backoff * 2)

    def packet_age_s(self) -> float:
        return self.clock.monotonic() - self.last_packet_mono

    async def close(self) -> None:
        self._stopped = True
        if self._ws is not None and hasattr(self._ws, "close"):
            with contextlib.suppress(Exception):
                await self._ws.close()


# ============================================================
# SECTION: health.py  (Â§18)
# ============================================================


class HealthMonitor:
    """Edge-triggered OKâ†”DEGRADED transitions; emits exactly one alert each (Â§18)."""

    def __init__(self, cfg: Config, store: MarketStateStore, ws: Optional[DhanWsFeed],
                 metrics: Metrics, clock: Clock, alerter: TelegramAlerter,
                 logger: logging.Logger) -> None:
        self.cfg = cfg
        self.store = store
        self.ws = ws
        self.metrics = metrics
        self.clock = clock
        self.alerter = alerter
        self.logger = logger
        self._degraded = False
        self.engine_degraded = False
        self.engine_degraded_since_mono: float = 0.0
        self._last_reconnect_count = 0
        self.last_degraded_mono: float = -1e9

    def status(self) -> HealthStatus:
        now = self.clock.now()
        tick_age = (now - self.store.last_tick_ts).total_seconds() if self.store.last_tick_ts else 1e9
        chain_age = (now - self.store.last_chain_ts).total_seconds() if self.store.last_chain_ts else 1e9
        if self.use_nse_chain and self.ws is None:
            feed_ok = False
        else:
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
            self.alerter.enqueue(OutboundMessage("HEALTH", "âœ… ENGINE RECOVERED â€” task restarts settled"))
            log_event(self.logger, logging.INFO, "engine_recovered")
        feeds_bad = (not st.feed_ok or not st.chain_ok
                     or lag_bad or rss_bad or queue_bad)
        degraded_now = market_open and feeds_bad
        # HEALTH-R4: outside market hours a still-broken feed used to satisfy
        # "not degraded_now" and fire a RECOVERED edge. Production 27-Aug
        # 15:30:08 logged health_recovered with feed_ok=false and
        # last_tick_age_s=28.4. Drop the latch silently at close instead, so
        # RECOVERED is only ever announced when the feeds are genuinely fresh.
        if not market_open and self._degraded:
            self._degraded = False
            log_event(self.logger, logging.INFO, "health_latch_cleared_market_closed",
                      **asdict(st))
            return
        if degraded_now and not self._degraded:
            self._degraded = True
            self.last_degraded_mono = self.clock.monotonic()
            self.alerter.enqueue(OutboundMessage("HEALTH",
                f"âš  HEALTH DEGRADED â€” feed_ok={st.feed_ok} chain_ok={st.chain_ok} "
                f"tick_age={st.last_tick_age_s:.0f}s chain_age={st.last_chain_age_s:.0f}s "
                f"lag_p95={st.lag_ms_p95:.0f}ms rss={rss} queue={self.alerter.queue.qsize()} "
                f"reconnects={reconnects}"))
            log_event(self.logger, logging.WARNING, "health_degraded",
                      lag_bad=lag_bad, rss_bad=rss_bad, queue_bad=queue_bad,
                      reconnects=reconnects, **asdict(st))
        elif not degraded_now and self._degraded and not feeds_bad:
            self._degraded = False
            self.alerter.enqueue(OutboundMessage("HEALTH", "âœ… HEALTH RECOVERED â€” feeds fresh"))
            log_event(self.logger, logging.INFO, "health_recovered", **asdict(st))

    @property
    def degraded(self) -> bool:
        return self._degraded or self.engine_degraded

    def degraded_recently(self, within_s: float = 120.0) -> bool:
        return (self.clock.monotonic() - self.last_degraded_mono) < within_s


# ============================================================
# SECTION: __main__.py â€” wiring, supervisor, CLI, replay (Â§22)
# ============================================================



class FyersWsFeed:
    """FYERS NIFTY underlying feed adapter using the official v3 SDK."""

    def __init__(self, access_token: str, app_id: str, logger: logging.Logger,
                 metrics: Metrics, clock: Clock, on_tick: Callable[[Tick], None],
                 symbol_map: Dict[str, Tuple[str, str, Decimal]]) -> None:
        self.symbol_map: Dict[str, Tuple[str, str, Decimal]] = dict(symbol_map)
        self.access_token = access_token
        self.app_id = app_id
        self.logger = logger
        self.metrics = metrics
        self.clock = clock
        self.on_tick = on_tick
        self._socket: Any = None
        self._thread: Any = None
        self._stopped = False
        self.last_packet_mono: float = 0.0
        self.reconnect_count = 0
        self._errors = 0
        self._loop: Any = None
        # LIFECYCLE-FIX B: monotonic feed-session id. Incremented every
        # time run() binds a loop, so callbacks from a previous websocket
        # session can be recognised and discarded.
        self._session: int = 0
        # FYERS-R5: True once this socket has completed one subscription, so a
        # later subscription is provably a reconnect rather than first connect.
        self._subscribe_seen: bool = False

    def packet_age_s(self) -> float:
        if self.last_packet_mono <= 0.0:
            return 1e9
        return self.clock.monotonic() - self.last_packet_mono

    def _on_connect(self) -> None:
        try:
            self._socket.subscribe(
                symbols=sorted(self.symbol_map.keys()),
                data_type="SymbolUpdate"
            )
            # FYERS-R5: the SDK reconnects inside its own __on_close and does
            # NOT invoke our on_close, so _on_close never fires and
            # reconnect_count stayed 0 while the feed demonstrably dropped and
            # re-subscribed. Every genuine reconnect DOES re-enter this
            # callback, so account it here. The first subscription of a socket
            # session is the initial connect and is not counted.
            if self._subscribe_seen:
                self.reconnect_count += 1
                self.metrics.inc("fyers_reconnects")
                log_event(self.logger, logging.WARNING, "fyers_resubscribe_after_drop",
                          session=self._session, reconnects=self.reconnect_count)
            self._subscribe_seen = True
            log_event(self.logger, logging.INFO, "fyers_subscribed",
                      symbols=",".join(sorted(self.symbol_map.keys())))
        except Exception as exc:
            self._errors += 1
            log_event(self.logger, logging.ERROR, "fyers_subscribe_failed", error=str(exc))

    def _on_message(self, message: Any) -> None:
        if self._stopped or not isinstance(message, dict):
            return
        _entry = self.symbol_map.get(message.get("symbol"))
        if _entry is None:
            return
        ltp = message.get("ltp")
        exch_ts = message.get("exch_feed_time")
        if ltp is None or exch_ts is None:
            return
        try:
            ts = datetime.fromtimestamp(int(exch_ts), tz=ZoneInfo("UTC")).astimezone(IST)
            tick = Tick(
                security_id=_entry[1],
                ts=ts,
                ltp=quantize_tick(_d(ltp), _entry[2]),
                ltq=0,
                volume_cum=0,
                oi=0,
                bid=Decimal(0),
                ask=Decimal(0),
                bid_qty=0,
                ask_qty=0,
                total_buy_qty=0,
                total_sell_qty=0,
            )
            self.last_packet_mono = self.clock.monotonic()
            # LIFECYCLE-FIX B: the FYERS SDK daemon thread outlives the
            # asyncio loop. Deliver only when this callback belongs to the
            # CURRENT feed session AND the loop is alive. The RuntimeError
            # catch is the last-resort barrier for the microscopic window
            # between is_closed() and the call - not the primary guard.
            loop = self._loop
            session = self._session
            if (loop is None or self._stopped
                    or session != self._session or loop.is_closed()):
                self.metrics.inc("fyers_stale_callbacks")
                return
            try:
                loop.call_soon_threadsafe(self._deliver, tick)
            except RuntimeError:
                # Loop closed between the check and the call: process is
                # dying. Drop silently; never log as a parse error.
                self.metrics.inc("fyers_stale_callbacks")
                return
        except Exception as exc:
            self._errors += 1
            self.metrics.inc("fyers_parse_errors")
            log_event(self.logger, logging.ERROR, "fyers_parse_error", error=str(exc))

    def _on_error(self, message: Any) -> None:
        self._errors += 1
        log_event(self.logger, logging.WARNING, "fyers_error", error=str(message))

    def _on_close(self, message: Any) -> None:
        if not self._stopped:
            self.reconnect_count += 1
            self.metrics.inc("fyers_reconnects")
            log_event(self.logger, logging.WARNING, "fyers_close", error=str(message))

    def _connect_blocking(self) -> None:
        # FYERS-R3: bind every SDK callback to the feed-session that created
        # THIS socket, so callbacks from an abandoned socket are discarded
        # instead of mutating live state or delivering stale ticks.
        _session = self._session

        def _bind(handler: Callable[..., None]) -> Callable[..., None]:
            def _guarded(*args: Any) -> None:
                if self._stopped or _session != self._session:
                    self.metrics.inc("fyers_stale_callbacks")
                    return
                handler(*args)
            return _guarded

        _socket = fyers_data_ws.FyersDataSocket(
            access_token=f"{self.app_id}:{self.access_token}",
            log_path="",
            litemode=False,
            write_to_file=False,
            reconnect=True,
            on_connect=_bind(self._on_connect),
            on_message=_bind(self._on_message),
            on_error=_bind(self._on_error),
            on_close=_bind(self._on_close),
        )
        self._socket = _socket
        _socket.connect()

    def _deliver(self, tick: Tick) -> None:
        if self._stopped:
            return
        self.metrics.inc("ticks_ingested")
        self.on_tick(tick)

    def _sdk_abandoned(self) -> bool:
        # FYERS-R1: the SDK reconnect budget is finite
        # (max_reconnect_attempts, default 50). Once spent the SDK reports
        # "Max reconnect attempts reached. Connection abandoned." and never
        # reconnects again. Detect that terminal state deterministically.
        # A missing socket is NOT reported here; absence is handled by the
        # debounced path so a just-spawned worker cannot cause a reset storm.
        _socket = self._socket
        if _socket is None:
            return False
        try:
            _attempts = int(getattr(_socket, "reconnect_attempts", 0))
            _budget = int(getattr(_socket, "max_reconnect_attempts", 0))
        except (TypeError, ValueError):
            return False
        return _budget > 0 and _attempts >= _budget

    def _sdk_socket_absent(self) -> bool:
        # True while the SDK holds no live websocket object.
        _socket = self._socket
        if _socket is None:
            return True
        _probe = getattr(_socket, "is_connected", None)
        if not callable(_probe):
            return False
        try:
            return not bool(_probe())
        except Exception:
            return False

    def _spawn_socket_worker(self) -> None:
        import threading
        self._thread = threading.Thread(
            target=self._connect_blocking,
            name=f"fyers-data-{self._session}",
            daemon=True,
        )
        self._thread.start()

    def _hard_reset(self, reason: str) -> None:
        # FYERS-R1/R2/R3: retire the dead socket, invalidate its session so
        # late callbacks are discarded, account the reconnect truthfully so
        # HealthMonitor observes it, then rebuild a genuinely fresh socket.
        _old = self._socket
        self._socket = None
        self._session += 1
        # FYERS-R5: a rebuilt socket starts a fresh subscription lifecycle.
        self._subscribe_seen = False
        if _old is not None:
            _closer = getattr(_old, "close_connection", None)
            if callable(_closer):
                try:
                    _closer()
                except Exception:
                    pass
        self._thread = None
        self.reconnect_count += 1
        self.metrics.inc("fyers_reconnects")
        log_event(self.logger, logging.WARNING, "fyers_hard_reset",
                  reason=reason, session=self._session,
                  reconnects=self.reconnect_count)
        self._spawn_socket_worker()

    async def run(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._session += 1
        if self._thread is None:
            self._spawn_socket_worker()
        # FYERS-R1/R2 supervisor. FyersDataSocket.connect() is non-blocking,
        # so the worker thread returns immediately even when healthy: thread
        # liveness is NOT a health signal, the SDK socket object is. The SDK
        # also reconnects silently without invoking our on_close and stops
        # forever once its budget is spent. Poll that state and rebuild from
        # scratch so recovery is indefinite. The absence counter is debounced
        # well past the SDK growing reconnect_delay so an in-flight SDK
        # reconnect is never pre-empted.
        _absent_polls = 0
        while not self._stopped:
            await asyncio.sleep(1.0)
            if self._stopped:
                break
            if self._sdk_abandoned():
                self._hard_reset("sdk_reconnect_budget_exhausted")
                _absent_polls = 0
                continue
            if self._sdk_socket_absent():
                _absent_polls += 1
                if _absent_polls >= 90:
                    self._hard_reset("sdk_socket_absent_90s")
                    _absent_polls = 0
            else:
                _absent_polls = 0


    async def resubscribe(self, subs: List[Tuple[str, str]]) -> None:
        """Compatibility with the existing Engine WS interface.
        FYERS underlying subscriptions are driven by the symbol map.
        """
        if self._stopped or self._socket is None:
            return
        try:
            self._socket.unsubscribe_all()
        except Exception:
            pass
        try:
            self._socket.subscribe(
                symbols=sorted(self.symbol_map.keys()),
                data_type="SymbolUpdate"
            )
            self.metrics.inc("ws_resubscribes")
            log_event(self.logger, logging.INFO, "fyers_resubscribed",
                      symbols=",".join(sorted(self.symbol_map.keys())))
        except Exception as exc:
            log_event(self.logger, logging.WARNING, "fyers_resubscribe_failed",
                      error=str(exc))
    async def close(self) -> None:
        # LIFECYCLE-FIX B: stop delivery FIRST, then invalidate the
        # session and drop the loop reference so any in-flight SDK
        # callback fails the guard instead of touching a dying loop.
        self._stopped = True
        self._session += 1
        self._loop = None
        # FYERS SDK v3 has no public close() on FyersDataSocket.
        # The daemon worker is allowed to terminate with the process.
        self._socket = None
class Engine:
    """Runtime wiring, evaluation loop, supervisor, lifecycle (Â§13, Â§22)."""

    def __init__(self, cfg: Config, instruments: Instruments, clock: Clock,
                 logger: logging.Logger, metrics: Metrics,
                 rest: DhanRestClient, ws: Optional[DhanWsFeed],
                 alerter: TelegramAlerter, persistence: Persistence,
                 scrip_map: Dict[str, int]) -> None:
        self.cfg = cfg
        self.instruments = instruments
        self.clock = clock
        self.logger = logger
        self.metrics = metrics
        self.rest = rest
        self.ws = ws
        self.alerter = alerter
        self.persistence = persistence
        self.scrip_map = scrip_map
        self.calendar = SessionCalendar(cfg.engine.holidays)
        self.store = MarketStateStore(cfg, instruments, clock)
        self.confluence = ConfluenceEngine()
        self.scorer = ConfidenceScorer(cfg.signals.min_categories_passed)
        self.gates = RiskGates(cfg, self.calendar, {u: instruments.by_name[u].lot_size for u in cfg.engine.underlyings})
        self.levels = LevelEngine(cfg, self.store)
        self.signals = SignalManager(cfg, clock)
        self.health = HealthMonitor(cfg, self.store, ws, metrics, clock, alerter, logger)
        self.gates.health = self.health
        self.gates.signals = self.signals
        self.bar_builders: Dict[str, BarBuilder] = {}
        self.aggregators: Dict[str, BarAggregator5m] = {}
        self.expiries: Dict[str, date] = {}
        self._expiry_lists: Dict[str, List[date]] = {}
        for u in cfg.engine.underlyings:
            inst = instruments.by_name[u]
            self.bar_builders[u] = BarBuilder(clock, inst.tick_size)
            self.aggregators[u] = BarAggregator5m()
            self.store.register_index_security(inst.security_id, u)
        self._warmup_bars_remaining: Dict[str, int] = {u: 0 for u in cfg.engine.underlyings}
        self._sec_to_underlying = {instruments.by_name[u].security_id: u for u in cfg.engine.underlyings}
        self._tasks: List[asyncio.Task[Any]] = []
        self._stopped = False
        self._decisions_path = os.path.join(cfg.logging.dir, "decisions.jsonl")
        self._last_ws_reconnects = 0
        self._digest_counts: Dict[str, int] = {}
        self._digest_last_hour = -1
        self._chain_failures: Dict[str, int] = {u: 0 for u in cfg.engine.underlyings}
        self._active_expiry: Dict[str, date] = {}
        self._last_subscriptions: List[Tuple[str, str]] = []
        self.chain_adapters: Dict[str, Any] = {}
        self.option_segment = "NSE_FNO"
        self._nse_bar_minute: Dict[str, Optional[datetime]] = {
            u: None for u in cfg.engine.underlyings
        }
        self._nse_bar_open: Dict[str, Optional[Decimal]] = {
            u: None for u in cfg.engine.underlyings
        }
        self._nse_bar_high: Dict[str, Optional[Decimal]] = {
            u: None for u in cfg.engine.underlyings
        }
        self._nse_bar_low: Dict[str, Optional[Decimal]] = {
            u: None for u in cfg.engine.underlyings
        }
        self._nse_bar_close: Dict[str, Optional[Decimal]] = {
            u: None for u in cfg.engine.underlyings
        }
        self._nse_bar_obs: Dict[str, int] = {
            u: 0 for u in cfg.engine.underlyings
        }

    # -- feed ingestion --------------------------------------------------

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

    def _on_bar_1m(self, underlying: str, bar: Bar, source: str = "LIVE_TICK") -> None:
        if source != "LIVE_TICK":
            self.metrics.inc("synthetic_bars_rejected")
            log_event(self.logger, logging.WARNING, "synthetic_bar_rejected",
                      underlying=underlying, source=source,
                      ts=str(bar.ts_open))
            return
        if self.ws is not None and self.ws.reconnect_count > self._last_ws_reconnects:
            self._last_ws_reconnects = self.ws.reconnect_count
            for uu in self.cfg.engine.underlyings:
                self._warmup_bars_remaining[uu] = max(self._warmup_bars_remaining[uu], 2)
        phase = self.calendar.phase(self.clock.now())
        bar_5m, events_5m = self.store.apply_index_bar(underlying, bar, phase, self.aggregators[underlying])
        if bar_5m is not None:
            self.metrics.inc("bars_5m")
        if events_5m:
            self.metrics.inc("structure_events", len(events_5m))
        if self._warmup_bars_remaining[underlying] > 0:
            self._warmup_bars_remaining[underlying] -= 1
        self._maybe_set_opening_range(underlying)
        self.evaluate(underlying)

    def _maybe_set_opening_range(self, underlying: str) -> None:
        st = self.store.get(underlying)
        if st.opening_range_set:
            return
        or_bars = [b for b in st.bars_1m if dtime(9, 15) <= b.ts_open.time() < dtime(9, 30)]
        now_t = self.clock.now().time()
        if len(or_bars) >= 15 or (or_bars and now_t >= dtime(9, 31)):
            hi = max(b.high for b in or_bars)
            lo = min(b.low for b in or_bars)
            st.set_opening_range(hi, lo)

    # -- chain poll ------------------------------------------------------

    async def chain_poll_task(self) -> None:
        while not self._stopped:
            phase = self.calendar.phase(self.clock.now())
            if phase in (SessionPhase.CLOSED,):
                await asyncio.sleep(self.cfg.feeds.chain_poll_interval_s)
                continue
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

    def _on_nse_spot(self, underlying: str, ts: datetime, spot: Decimal) -> None:
        minute = ts.replace(second=0, microsecond=0)
        cur = self._nse_bar_minute.get(underlying)

        if cur is None:
            self._nse_bar_minute[underlying] = minute
            self._nse_bar_open[underlying] = spot
            self._nse_bar_high[underlying] = spot
            self._nse_bar_low[underlying] = spot
            self._nse_bar_close[underlying] = spot
            self._nse_bar_obs[underlying] = 1
            return

        if minute < cur:
            return

        if minute > cur:
            o = self._nse_bar_open[underlying]
            h = self._nse_bar_high[underlying]
            l = self._nse_bar_low[underlying]
            c = self._nse_bar_close[underlying]

            if o is not None and h is not None and l is not None and c is not None:
                bar = Bar(
                    ts_open=cur,
                    open=o,
                    high=h,
                    low=l,
                    close=c,
                    volume=0,
                    tick_count=self._nse_bar_obs[underlying],
                    volume_suspect=True,
                )
                self._on_bar_1m(underlying, bar, source="SYNTHETIC_SAMPLED")

            self._nse_bar_minute[underlying] = minute
            self._nse_bar_open[underlying] = spot
            self._nse_bar_high[underlying] = spot
            self._nse_bar_low[underlying] = spot
            self._nse_bar_close[underlying] = spot
            self._nse_bar_obs[underlying] = 1
            return

        self._nse_bar_close[underlying] = spot

        if self._nse_bar_high[underlying] is None or spot > self._nse_bar_high[underlying]:
            self._nse_bar_high[underlying] = spot

        if self._nse_bar_low[underlying] is None or spot < self._nse_bar_low[underlying]:
            self._nse_bar_low[underlying] = spot

        self._nse_bar_obs[underlying] += 1

    def _chain_adapter_for(self, underlying: str) -> Any:
        adapter = self.chain_adapters.get(underlying)
        if adapter is None:
            raise FatalConfigError(
                f"no option-chain adapter configured for underlying "
                f"{underlying}; per-underlying routing forbids fallback")
        return adapter

    async def _poll_chain(self, underlying: str) -> None:
        adapter = self._chain_adapter_for(underlying)
        scrip = self.scrip_map[underlying]
        expiry = self.expiries.get(underlying)
        if expiry is None:
            return
        roll_now = self.clock.now()
        if expiry == roll_now.date() and roll_now.time() >= dtime(13, 0):
            later = [e for e in self._expiry_lists.get(underlying, []) if e > expiry]
            if later:
                expiry = later[0]
        st = self.store.get(underlying)
        spot_hint = st.latest_tick.ltp if st.latest_tick else Decimal(0)
        snap = await adapter.option_chain(underlying, scrip, expiry, spot_hint)
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
        """
        FYERS owns the underlying NIFTY stream.
        NSE option-chain data is obtained via REST and does not
        require websocket option subscriptions.
        """
        return

    def _select_strike(self, underlying: str, direction: Direction) -> Optional[Tuple[Decimal, str]]:
        st = self.store.get(underlying)
        chain = st.last_chain
        view = st.last_options_view
        if chain is None or view is None:
            return None
        straddle_half = st.options.atm_straddle_half(chain, view.atm_strike)
        return st.options.select_strike(direction, chain, view,
                                        self.cfg.risk.max_spread_pct_of_premium, straddle_half)

    # -- evaluation pipeline (Â§13) --------------------------------------

    def evaluate(self, underlying: str) -> None:
        start = self.clock.monotonic()
        try:
            self._evaluate_inner(underlying)
        except DataIntegrityError as exc:
            self.metrics.inc("cycle_failclosed")
            log_event(self.logger, logging.WARNING, "cycle_failclosed", underlying=underlying, error=str(exc))
        except Exception as exc:  # fail closed
            self.metrics.inc("cycle_exceptions")
            log_event(self.logger, logging.ERROR, "cycle_exception", underlying=underlying, error=str(exc))
        finally:
            self.metrics.observe("cycle_ms", (self.clock.monotonic() - start) * 1000.0)
            self.metrics.inc("cycles")

    def _evaluate_inner(self, underlying: str) -> None:
        st = self.store.get(underlying)
        now = self.clock.now()
        regime_strength = st.regime.state.strength_0_100
        # Preconditions gate (Â§13 step 1) â€” silent skips, health counters only
        if not self.calendar.signal_window_open(now, regime_strength):
            self.metrics.inc("skip_window")
            _FX.cycle(underlying, "TRIGGER", "Engine._evaluate_inner", 5019, "FAIL",
                      "SIGNAL_WINDOW_CLOSED", phase=self.calendar.phase(now).value,
                      regime_strength=regime_strength)  # diagnostic only
            return
        if self._warmup_bars_remaining[underlying] > 0:
            self.metrics.inc("skip_warmup")
            _FX.cycle(underlying, "TRIGGER", "Engine._evaluate_inner", 5022, "FAIL",
                      "WARMUP_BARS_REMAINING",
                      remaining=self._warmup_bars_remaining[underlying])  # diagnostic only
            return
        if self.health.degraded:
            self.metrics.inc("skip_degraded")
            _FX.cycle(underlying, "TRIGGER", "Engine._evaluate_inner", 5025, "FAIL",
                      "HEALTH_DEGRADED")  # diagnostic only
            return
        hs = self.health.status()
        if not hs.feed_ok or not hs.chain_ok:
            self.metrics.inc("skip_stale")
            _FX.cycle(underlying, "TRIGGER", "Engine._evaluate_inner", 5029, "FAIL",
                      "FEED_OR_CHAIN_STALE", feed_ok=hs.feed_ok, chain_ok=hs.chain_ok,
                      tick_age_s=hs.last_tick_age_s,
                      chain_age_s=hs.last_chain_age_s)  # diagnostic only
            return
        # Trigger scan
        candidate = self._scan_trigger(underlying, st)
        if candidate is None:
            _FX.cycle(underlying, "CANDIDATE", "Engine._evaluate_inner", 5033, "FAIL",
                      "NO_CANDIDATE_FROM_FRESH_EVENTS",
                      regime=st.regime.state.regime.value,
                      bias=st.structure.bias,
                      events_in_deque=len(st.structure.events))  # diagnostic only
            return
        if self.signals.already_triggered(underlying, candidate.direction, candidate.trigger_swing_ts):
            _FX.cycle(underlying, "CANDIDATE", "Engine._evaluate_inner", 5035, "FAIL",
                      "ALREADY_TRIGGERED_DEDUP", direction=candidate.direction.value,
                      trigger_swing_ts=candidate.trigger_swing_ts)  # diagnostic only
            return
        _FX.cycle(underlying, "CANDIDATE", "Engine._evaluate_inner", 5036, "PASS",
                  "candidate_created", direction=candidate.direction.value,
                  trigger_kind=candidate.trigger.kind.value,
                  trigger_level=candidate.trigger.level)  # diagnostic only

        self.metrics.inc("candidates")
        st.options.oi_diag_note_candidate(  # OI-DIAG: observe only
            underlying, candidate.direction.value, now.isoformat())
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
        _FX.cycle(underlying, "CATEGORY", "ConfluenceEngine.evaluate", 3292,
                  "PASS" if scored.min_categories_ok else "FAIL",
                  "categories_passed=%d" % scored.categories_passed,
                  contradictions=scored.contradictions,
                  ledger_len=len(ledger))  # diagnostic only
        _FX.cycle(underlying, "SCORE", "ConfidenceScorer.score", 3489,
                  "PASS" if scored.score >= self.cfg.signals.confidence_threshold else "FAIL",
                  "score=%d band=%s" % (scored.score, scored.band),
                  score=scored.score, band=scored.band,
                  threshold=self.cfg.signals.confidence_threshold)  # diagnostic only
        _FX.cycle(underlying, "MANDATORY", "ConfidenceScorer.score", 3489,
                  "PASS" if scored.mandatory_ok else "FAIL",
                  "mandatory_ok=%s" % scored.mandatory_ok,
                  mandatory_ok=scored.mandatory_ok)  # diagnostic only
        if reject_reasons:
            _FX.cycle(underlying,
                      "MANDATORY" if "MANDATORY_CATEGORY" in reject_reasons
                      else ("SCORE" if "BELOW_THRESHOLD" in reject_reasons else "CATEGORY"),
                      "Engine._evaluate_inner", 5069, "FAIL",
                      ",".join(reject_reasons), score=scored.score,
                      direction=candidate.direction.value)  # diagnostic only
            self._record_rejection(Rejection(candidate, "SCORING", reject_reasons, ledger), scored)
            # NOTE (§13 step 8): dedup is "same trigger swing -> one SIGNAL ever".
            # A rejection must NOT consume the trigger: evidence is time-varying
            # (chain refreshes every chain_poll_interval_s, regime/volume evolve
            # per bar) while evaluation runs every evaluation_interval_s. Burning
            # the trigger here permanently destroyed setups that would have
            # qualified microseconds-to-minutes later. Trigger freshness (180s in
            # _scan_trigger) remains the sole anti-chase bound.
            return
        result = self.levels.compute(scored, m)
        if isinstance(result, Rejection):
            _FX.cycle(underlying, "LEVELS", "LevelEngine.compute", 3653, "FAIL",
                      ",".join(result.reason_codes),
                      selected_strike=m.selected_strike,
                      selected_leg=m.selected_leg)  # diagnostic only
            self._record_rejection(result, scored)
            return
        signal = result
        _FX.cycle(underlying, "LEVELS", "LevelEngine.compute", 3653, "PASS",
                  "levels_computed", entry=signal.option_entry,
                  stop=signal.option_stop, t1=signal.targets[0],
                  t2=signal.targets[1], spot_stop=signal.spot_stop,
                  strike=signal.strike)  # diagnostic only
        _FX.cycle(underlying, "RR", "LevelEngine.compute", 3653,
                  "PASS" if signal.reward_risk >= self.cfg.signals.min_reward_risk else "FAIL",
                  "rr=%s" % signal.reward_risk, reward_risk=signal.reward_risk,
                  min_reward_risk=self.cfg.signals.min_reward_risk)  # diagnostic only
        gate = self.gates.validate(scored, replace(m, reward_risk=signal.reward_risk))
        if not gate.passed:
            _codes = list(gate.reason_codes)
            _FX.cycle(underlying,
                      "LIQUIDITY" if ("LIQUIDITY" in _codes or "SPREAD" in _codes)
                      else ("RR" if "REWARD_RISK" in _codes else "VETO"),
                      "RiskGates.validate", 3553, "FAIL", ",".join(_codes),
                      selected_strike=gate.selected_strike,
                      selected_leg=gate.selected_leg,
                      regime=m.regime.regime.value)  # diagnostic only
            self._record_rejection(Rejection(candidate, "GATES", gate.reason_codes, ledger), scored)
            return
        _FX.cycle(underlying, "LIQUIDITY", "RiskGates.validate", 3553, "PASS",
                  "liquidity_spread_ok", selected_strike=gate.selected_strike,
                  selected_leg=gate.selected_leg)  # diagnostic only
        _FX.cycle(underlying, "VETO", "RiskGates.validate", 3553, "PASS",
                  "no_veto_triggered", regime=m.regime.regime.value)  # diagnostic only
        self.signals.register_trigger(underlying, candidate.direction, candidate.trigger_swing_ts)
        _submitted = self.signals.submit(signal)
        _FX.cycle(underlying, "FINAL", "SignalManager.submit", 3814,
                  "PASS" if _submitted else "FAIL",
                  "submitted" if _submitted else "DEDUP_COOLDOWN_OR_CAP",
                  signal_id=signal.id, confidence=signal.confidence)  # diagnostic only
        if _submitted:
            _FX.cycle(underlying, "SIGNAL", "Engine._record_signal", 5142, "PASS",
                      "signal_emitted", signal_id=signal.id,
                      direction=signal.direction.value,
                      strike=signal.strike, confidence=signal.confidence,
                      reward_risk=signal.reward_risk)  # diagnostic only
            self._record_signal(signal, scored)
            self.alerter.enqueue(OutboundMessage("SIGNAL", format_signal_message(signal)))
            self.metrics.inc("signals")
            log_event(self.logger, logging.INFO, "signal_emitted", id=signal.id,
                      underlying=underlying, direction=signal.direction.value,
                      confidence=signal.confidence)

    def _scan_trigger(self, underlying: str, st: UnderlyingState) -> Optional[CandidateSignal]:
        """Trigger scan over the last 3 completed 1m bars via structure events (Â§13)."""
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
                _FX.terminal(ev, "DIRECTION", "direction_none",
                             "Engine._scan_trigger", 5083)  # diagnostic only
                continue
            _FX.stage(ev, "DIRECTION", "Engine._direction_for", 5081, "PASS",
                      "direction=%s" % getattr(direction, "value", direction),
                      {"regime": getattr(regime, "value", str(regime)), "bias": bias},
                      lifecycle="FORWARDED")  # diagnostic only
            swing_ts = ev.ref_swing.ts if ev.ref_swing is not None else ev.ts
            return CandidateSignal(direction=direction, underlying=underlying,
                                   trigger=ev, ts=now, trigger_swing_ts=swing_ts)
        return None

    def _direction_for(self, ev: StructureEvent, regime: Regime, bias: str) -> Optional[Direction]:
        trend = regime in (Regime.TREND_UP, Regime.TREND_DOWN,
                           Regime.OPENING_DRIVE_UP, Regime.OPENING_DRIVE_DOWN,
                           Regime.EXPANSION)
        rangeish = regime in (Regime.RANGE, Regime.OPENING_REVERSAL)
        if ev.kind == StructureKind.RETEST_OK:
            # P20-D1: a RETEST_OK is a continuation of ITS PARENT BREAK.
            # The parent is carried by ref_swing: StructureEngine appends a
            # pending BOS_UP with ref_swing=last_high (SwingKind.HIGH) and a
            # pending BOS_DOWN with ref_swing=last_low (SwingKind.LOW), and
            # RETEST_OK is emitted from that pending entry alone (L1344).
            # Regime/bias must NOT override the parent relationship; regime
            # admissibility remains enforced downstream by RiskGates.
            # An unresolved parent stays fail-closed (None), as before.
            _ref = ev.ref_swing
            if _ref is None:
                return None
            if _ref.kind == SwingKind.HIGH:
                return Direction.LONG_CE
            if _ref.kind == SwingKind.LOW:
                return Direction.LONG_PE
            return None
        if ev.kind == StructureKind.BOS_UP and trend:
            return Direction.LONG_CE
        if ev.kind == StructureKind.BOS_DOWN and trend:
            return Direction.LONG_PE
        if ev.kind == StructureKind.SWEEP_LOW and rangeish:
            return Direction.LONG_CE
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

    def _record_signal(self, signal: Signal, scored: ScoredCandidate) -> None:
        self._append_decision({
            "type": "signal", "id": signal.id, "ts": signal.ts.isoformat(),
            "underlying": signal.underlying, "direction": signal.direction.value,
            "confidence": signal.confidence, "strike": str(signal.strike),
            "rr": str(signal.reward_risk),
            "expiry": signal.expiry.isoformat(),
            "option_entry": str(signal.option_entry),
            "option_stop": str(signal.option_stop),
            "targets": [str(signal.targets[0]), str(signal.targets[1])],
            "spot_ref": str(signal.spot_ref),
            "spot_stop": str(signal.spot_stop),
            "entry_max": str(signal.entry_max),
            "band": signal.band,
            "regime": signal.regime.value,
            "ledger": [self._ev_dict(e) for e in signal.evidence_ledger],
        })

    def _record_rejection(self, rej: Rejection, scored: ScoredCandidate) -> None:
        self.metrics.inc("rejections")
        for code in rej.reason_codes:
            self.metrics.reject(code)
            self._digest_counts[code] = self._digest_counts.get(code, 0) + 1
        self._append_decision({
            "type": "rejection", "stage": rej.stage,
            "ts": self.clock.now().isoformat(),
            "underlying": rej.candidate.underlying,
            "direction": rej.candidate.direction.value,
            "score": scored.score, "reasons": rej.reason_codes,
            "ledger": [self._ev_dict(e) for e in rej.ledger],
        })

    @staticmethod
    def _ev_dict(e: Evidence) -> Dict[str, Any]:
        return {"category": e.category, "name": e.name, "passed": e.passed,
                "weight": e.weight, "contribution": e.contribution, "detail": e.detail}

    def _append_decision(self, row: Dict[str, Any]) -> None:
        os.makedirs(os.path.dirname(self._decisions_path) or ".", exist_ok=True)
        with open(self._decisions_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, default=str, sort_keys=True) + "\n")

    # -- periodic tasks --------------------------------------------------

    async def evaluation_task(self) -> None:
        while not self._stopped:
            for u in self.cfg.engine.underlyings:
                self.evaluate(u)
                self._poll_bar_timeout(u)
            await asyncio.sleep(self.cfg.engine.evaluation_interval_s)

    def _poll_bar_timeout(self, underlying: str) -> None:
        bar = self.bar_builders[underlying].poll()
        if bar is not None:
            self._on_bar_1m(underlying, bar)

    async def health_task(self) -> None:
        while not self._stopped:
            phase = self.calendar.phase(self.clock.now())
            self.health.evaluate(phase)
            sd_notify("WATCHDOG=1")
            await asyncio.sleep(10.0)

    async def daily_lifecycle_task(self) -> None:
        """15:35 daily summary; 15:40 final snapshot + idle (Â§6)."""
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
            if (self.calendar.is_trading_day(today) and now.time() >= dtime(15, 35)
                    and summary_sent_for != today):
                self.alerter.enqueue(OutboundMessage("DAILY_SUMMARY", self.daily_summary_text()))
                summary_sent_for = today
            if (self.calendar.is_trading_day(today) and now.time() >= dtime(15, 40)
                    and snapshot_done_for != today):
                self.save_snapshot()
                self.metrics.reset_session()
                snapshot_done_for = today
            if (self.cfg.telegram.send_rejections_digest and now.minute == 0
                    and self._digest_last_hour != now.hour and self._digest_counts
                    and self.calendar.phase(now) not in (SessionPhase.CLOSED, SessionPhase.PRE_OPEN)):
                body = ", ".join(f"{k}={v}" for k, v in sorted(self._digest_counts.items()))
                self.alerter.enqueue(OutboundMessage("REJECTION_DIGEST", "REJECTION DIGEST (last hour): " + body))
                self._digest_counts = {}
                self._digest_last_hour = now.hour
            await asyncio.sleep(30.0)


    async def snapshot_task(self) -> None:
        while not self._stopped:
            await asyncio.sleep(60.0)
            self.save_snapshot()
            self.metrics.dump(os.path.join(self.cfg.logging.dir, "metrics.json"))

    def save_snapshot(self) -> None:
        payload = {
            "session_date": self.clock.now().date().isoformat(),
            "saved_ts": self.clock.now().isoformat(),
            "signals": self.signals.state(),
            "underlyings": {u: self.store.get(u).state() for u in self.cfg.engine.underlyings},
        }
        self.persistence.write(payload)

    def restore_snapshot(self) -> bool:
        data = self.persistence.read()
        if data is None:
            return False
        try:
            saved = datetime.fromisoformat(data["saved_ts"])
        except Exception:
            return False
        now = self.clock.now()
        if (data.get("session_date") != now.date().isoformat()
                or (now - saved).total_seconds() > 600):
            for u, us in data.get("underlyings", {}).items():
                if u in self.store.states:
                    with contextlib.suppress(Exception):
                        self.store.get(u).volume.restore(us.get("volume", {}))
            log_event(self.logger, logging.INFO, "rvol_baseline_salvaged",
                      session=data.get("session_date"))
            return False
        self.signals.restore(data.get("signals", {}))
        for u, us in data.get("underlyings", {}).items():
            if u in self.store.states:
                self.store.get(u).restore(us)
        for u in self.cfg.engine.underlyings:
            self._warmup_bars_remaining[u] = 3
            rs = self.store.get(u)
            rs.last_chain = None
            rs.last_options_view = None
        log_event(self.logger, logging.INFO, "snapshot_restored", saved_ts=data["saved_ts"])
        return True

    # -- startup / bootstrap --------------------------------------------

    async def _refresh_expiries(self, fatal: bool) -> None:
        for u in self.cfg.engine.underlyings:
            scrip = self.scrip_map[u]
            adapter = self._chain_adapter_for(u)
            try:
                expiries = await adapter.expiry_list(scrip, underlying=u)
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

    async def _fyers_history_bootstrap(self) -> None:
        """Seed live analytical state from FYERS historical 1m candles."""
        import requests

        if not self.use_nse_chain:
            return
        if not isinstance(self.ws, FyersWsFeed):
            return

        token = os.environ.get("FYERS_ACCESS_TOKEN", "").strip()
        app_id = os.environ.get("FYERS_APP_ID", "").strip()
        if not token or not app_id:
            raise FatalConfigError("FYERS credentials missing for history bootstrap")

        today = self.clock.now().date()

        def fetch_day(symbol: str, day: date) -> List[List[Any]]:
            r = requests.get(
                "https://api-t1.fyers.in/data/history",
                params={
                    "symbol": symbol,
                    "resolution": "1",
                    "date_format": "1",
                    "range_from": day.isoformat(),
                    "range_to": day.isoformat(),
                },
                headers={"Authorization": f"{app_id}:{token}"},
                timeout=20,
            )
            data = r.json()
            if data.get("s") != "ok":
                return []
            return data.get("candles", [])

        def row_to_bar(row: List[Any], tick: Decimal) -> Optional[Bar]:
            if len(row) < 6:
                return None
            epoch, o, h, l, c, v = row[:6]
            ts = datetime.fromtimestamp(
                int(epoch), tz=ZoneInfo("UTC")
            ).astimezone(IST).replace(second=0, microsecond=0)
            return Bar(
                ts_open=ts,
                open=quantize_tick(_d(o), tick),
                high=quantize_tick(_d(h), tick),
                low=quantize_tick(_d(l), tick),
                close=quantize_tick(_d(c), tick),
                volume=int(v or 0),
                tick_count=0,
                volume_suspect=True,
            )

        for u in self.cfg.engine.underlyings:
            inst = self.instruments.by_name[u]
            _fsym = inst.fyers_symbol
            if _fsym is None and u == "NIFTY":
                _fsym = "NSE:NIFTY50-INDEX"
            if _fsym is None:
                raise FatalConfigError(
                    f"instruments.{u}.fyers_symbol is required for history bootstrap")
            _keep_volume = self.store.get(u).volume
            self.store.states[u] = UnderlyingState(
                u, self.cfg, inst.tick_size, self.clock
            )
            st = self.store.get(u)
            st.volume = _keep_volume

            # Previous sessions: seed slow indicators only.
            prior = []
            for back in range(1, 6):
                for row in fetch_day(_fsym, today - timedelta(days=back)):
                    b = row_to_bar(row, inst.tick_size)
                    if b is not None:
                        prior.append(b)
                if len(prior) >= 200:
                    break

            prior.sort(key=lambda b: b.ts_open)
            if prior:
                _pd_date = prior[-1].ts_open.date()
                _pd_bars = [b for b in prior if b.ts_open.date() == _pd_date]
                st.structure.set_prev_day(
                    max(b.high for b in _pd_bars),
                    min(b.low for b in _pd_bars),
                    _pd_bars[-1].close,
                )
            pa = BarAggregator5m()
            for b in prior:
                b5 = pa.on_bar_1m(b)
                if b5 is not None:
                    st.atr_5m.update(b5)
                    st.adx.update(b5)
                    st.bb.update(b5)
                    st.ema20.update(b5)

            # Today: rebuild actual session state on the live aggregator (continuity).
            self.aggregators[u] = BarAggregator5m()
            ta = self.aggregators[u]
            current_minute = self.clock.now().replace(second=0, microsecond=0)
            today_count = 0
            for row in fetch_day(_fsym, today):
                b = row_to_bar(row, inst.tick_size)
                if b is None or b.ts_open >= current_minute:
                    continue
                self.store.apply_index_bar(
                    u, b, self.calendar.phase(b.ts_open), ta
                )
                today_count += 1

            self._maybe_set_opening_range(u)
            self._warmup_bars_remaining[u] = 0

            log_event(
                self.logger, logging.INFO, "fyers_history_bootstrap",
                underlying=u, fyers_symbol=_fsym,
                prior_1m=len(prior), today_1m=today_count,
                state_1m=len(st.bars_1m), state_5m=len(st.bars_5m),
                atr_5m=str(st.atr_5m.value), adx=str(st.adx.value),
                ema20=str(st.ema20.value)
            )

    async def bootstrap(self) -> None:
        await self._refresh_expiries(True)
        if self.use_nse_chain:
            log_event(self.logger, logging.INFO, "data_api_historical_skipped", mode="nse_chain_only")
        else:
            await self._load_prev_day_levels()

        # Restore persistent state first.
        # FYERS historical bootstrap must run AFTER restore so that stale
        # snapshot-derived analytical state cannot overwrite fresh live-day state.
        restored = self.restore_snapshot()

        if not restored:
            if self.use_nse_chain:
                log_event(self.logger, logging.INFO, "cold_bootstrap_skipped", mode="nse_chain_only")
            else:
                await self._cold_bootstrap()

        if self.use_nse_chain and isinstance(self.ws, FyersWsFeed):
            await self._fyers_history_bootstrap()

        await self._rebuild_subscriptions()

    async def _cold_bootstrap(self) -> None:
        now = self.clock.now()
        start = now.replace(hour=9, minute=15, second=0, microsecond=0)
        for u in self.cfg.engine.underlyings:
            inst = self.instruments.by_name[u]
            try:
                bars = await self.rest.intraday_minute(
                    inst.security_id, inst.exchange_segment, "INDEX", start, now)
            except (TransientInfraError, DataIntegrityError) as exc:
                log_event(self.logger, logging.WARNING, "cold_bootstrap_failed", underlying=u, error=str(exc))
                continue
            for bar in bars:
                self._on_bar_1m(u, bar)
            self._warmup_bars_remaining[u] = 3

    async def _load_prev_day_levels(self) -> None:
        now = self.clock.now()
        prev = now.date() - timedelta(days=1)
        guard = 0
        while not self.calendar.is_trading_day(prev) and guard < 10:
            prev = prev - timedelta(days=1)
            guard += 1
        start = datetime.combine(prev, dtime(9, 15), tzinfo=IST)
        end = datetime.combine(prev, dtime(15, 30), tzinfo=IST)
        for u in self.cfg.engine.underlyings:
            inst = self.instruments.by_name[u]
            try:
                bars = await self.rest.intraday_minute(
                    inst.security_id, inst.exchange_segment, "INDEX", start, end)
            except (TransientInfraError, DataIntegrityError) as exc:
                log_event(self.logger, logging.WARNING, "prev_day_fetch_failed",
                          underlying=u, error=str(exc))
                continue
            if not bars:
                continue
            hi = max(b.high for b in bars)
            lo = min(b.low for b in bars)
            self.store.get(u).structure.set_prev_day(hi, lo, bars[-1].close)

    # -- supervisor ------------------------------------------------------

    async def _supervise(self, name: str, coro_factory: Callable[[], Any]) -> None:
        restarts: Deque[float] = deque(maxlen=10)
        backoff = 1.0
        while not self._stopped:
            try:
                await coro_factory()
                return
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                restarts.append(self.clock.monotonic())
                self.metrics.inc("task_restarts")
                log_event(self.logger, logging.ERROR, "task_crashed", task=name, error=str(exc))
                recent = [t for t in restarts if self.clock.monotonic() - t < 300]
                if len(recent) >= 3:
                    self.health.engine_degraded = True
                    self.health.engine_degraded_since_mono = self.clock.monotonic()
                    self.alerter.enqueue(OutboundMessage("HEALTH",
                        f"âš  ENGINE DEGRADED â€” task {name} restarted 3Ã— in 5 min; signals suppressed"))
                    log_event(self.logger, logging.ERROR, "engine_degraded", task=name)
                await asyncio.sleep(backoff)
                backoff = min(self.cfg.feeds.ws_reconnect_max_s, backoff * 2)

    async def run(self) -> None:
        await self.bootstrap()
        sd_notify("READY=1")
        self.alerter.enqueue(OutboundMessage("HEALTH", "âœ… engine online"))
        self._tasks = [
            asyncio.create_task(self._supervise("telegram", self.alerter.run)),
            asyncio.create_task(self._supervise("chain_poll", self.chain_poll_task)),
            asyncio.create_task(self._supervise("evaluation", self.evaluation_task)),
            asyncio.create_task(self._supervise("health", self.health_task)),
            asyncio.create_task(self._supervise("snapshot", self.snapshot_task)),
            asyncio.create_task(self._supervise("daily_lifecycle", self.daily_lifecycle_task)),
        ]

        if self.ws is not None:
            self._tasks.append(asyncio.create_task(self._supervise("ws_feed", self.ws.run)))
        try:
            await asyncio.gather(*self._tasks)
        except asyncio.CancelledError:
            pass

    async def shutdown(self) -> None:
        self._stopped = True
        self.save_snapshot()
        with contextlib.suppress(asyncio.TimeoutError, Exception):
            await asyncio.wait_for(self.alerter.queue.join(), timeout=15.0)
        with contextlib.suppress(Exception):
            await self.alerter.close()
        with contextlib.suppress(Exception):
            await self.rest.close()
        if self.ws is not None:
            with contextlib.suppress(Exception):
                await self.ws.close()
        if getattr(self, "nse_chain", None) is not None:
            with contextlib.suppress(Exception):
                await self.nse_chain.close()
        for t in self._tasks:
            t.cancel()
        for t in self._tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await t

    def daily_summary_text(self) -> str:
        snap = self.metrics.snapshot()
        rej = ", ".join(f"{k}={v}" for k, v in sorted(snap["rejections_by_reason"].items()))
        return (
            f"ðŸ“Š DAILY SUMMARY â€” {self.clock.now().date().isoformat()}\n"
            f"Signals: {snap['counters'].get('signals', 0)} | "
            f"Rejections: {snap['counters'].get('rejections', 0)}\n"
            f"By reason: {rej or 'none'}\n"
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


# ============================================================
# SECTION: replay harness (Â§21)
# ============================================================


class ReplayEngine:
    """Deterministic replay: feed recorded ticks + chain snapshots (Â§21)."""

    def __init__(self, engine: Engine, clock: FixedClock) -> None:
        self.engine = engine
        self.clock = clock
        self.captured_signal_texts: List[str] = []
        original = engine.alerter.enqueue

        def capture(msg: OutboundMessage) -> None:
            if msg.kind == "SIGNAL":
                self.captured_signal_texts.append(msg.text)
            original(msg)

        engine.alerter.enqueue = capture  # type: ignore

    def feed_ticks(self, ticks: List[Tick]) -> None:
        for t in ticks:
            self.clock.set(t.ts)
            self.engine.on_tick(t)

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


def _read_fixture(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _tick_from_fixture(d: Dict[str, Any]) -> Tick:
    return Tick(
        security_id=str(d["security_id"]), ts=datetime.fromisoformat(d["ts"]),
        ltp=_d(d["ltp"]), ltq=int(d.get("ltq", 0)), volume_cum=int(d.get("volume_cum", 0)),
        oi=int(d.get("oi", 0)), bid=_d(d.get("bid", 0)), ask=_d(d.get("ask", 0)),
        bid_qty=int(d.get("bid_qty", 0)), ask_qty=int(d.get("ask_qty", 0)),
    )


def _chain_from_fixture(d: Dict[str, Any]) -> ChainSnapshot:
    strikes: List[ChainStrike] = []
    for s in d["strikes"]:
        strikes.append(ChainStrike(
            strike=_d(s["strike"]),
            ce=_leg_from_fixture(s["ce"]),
            pe=_leg_from_fixture(s["pe"]),
        ))
    strikes.sort(key=lambda x: x.strike)
    spot = _d(d["spot"])
    atm = min(strikes, key=lambda x: abs(x.strike - spot)).strike if strikes else spot
    return ChainSnapshot(
        underlying=str(d["underlying"]), expiry=date.fromisoformat(d["expiry"]),
        spot=spot, ts=datetime.fromisoformat(d["ts"]), strikes=strikes, atm_strike=atm,
    )


def _leg_from_fixture(d: Dict[str, Any]) -> OptionLeg:
    return OptionLeg(
        ltp=_d(d["ltp"]), bid=_d(d["bid"]), ask=_d(d["ask"]), oi=int(d["oi"]),
        oi_prev=int(d.get("oi_prev", d["oi"])), volume=int(d.get("volume", 0)),
        iv=_d(d.get("iv", 0)),
        bid_qty=int(d.get("bid_qty", 0)), ask_qty=int(d.get("ask_qty", 0)),
        security_id=str(d.get("security_id", "")),
    )


# ============================================================
# SECTION: entrypoint
# ============================================================


def _build_engine(cfg: Config, instruments: Instruments, clock: Clock,
                  logger: logging.Logger, metrics: Metrics,
                  live: bool, use_nse_chain: bool = False) -> Engine:
    access_token = os.environ.get("DHAN_ACCESS_TOKEN", "")
    client_id = os.environ.get("DHAN_CLIENT_ID", "")
    bot_token = os.environ.get("TG_BOT_TOKEN", "")
    chat_id = os.environ.get(cfg.telegram.chat_id_env, "")
    rest = DhanRestClient(access_token, client_id, logger, metrics, clock)
    nse_chain = None
    if use_nse_chain:
        from nse_option_provider import NSEOptionChainProvider
        from nse_chain_adapter import NSEChainAdapter
        nse_provider = NSEOptionChainProvider()
        nse_chain = NSEChainAdapter(nse_provider, logger)
        # Compatibility bridge: Engine expiry discovery remains on REST interface.
        rest.expiry_list = nse_chain.expiry_list
    alerter = TelegramAlerter(bot_token, chat_id, logger, metrics, clock)
    persistence = Persistence(os.path.join("state", "snapshot.json"))
    scrip_map: Dict[str, int] = {}
    for u in cfg.engine.underlyings:
        try:
            scrip_map[u] = int(instruments.by_name[u].security_id)
        except ValueError as exc:
            raise FatalConfigError(
                f"instruments.{u}.security_id is not numeric: "
                f"{instruments.by_name[u].security_id}") from exc
    ws: Optional[DhanWsFeed] = None
    engine = Engine(cfg, instruments, clock, logger, metrics, rest, ws, alerter, persistence, scrip_map)
    engine.use_nse_chain = use_nse_chain
    engine.health.use_nse_chain = use_nse_chain
    if nse_chain is not None:
        engine.nse_chain = nse_chain
        for _u in cfg.engine.underlyings:
            if _u == "NIFTY":
                engine.chain_adapters[_u] = nse_chain
    # S4: per-underlying SENSEX chain provider (FYERS). NIFTY untouched.
    # Import is local so an adapter fault can never break NIFTY startup.
    if "SENSEX" in cfg.engine.underlyings:
        try:
            from fyers_chain_adapter import FyersChainAdapter
        except Exception as _exc:
            raise FatalConfigError(
                f"SENSEX chain adapter unavailable: {_exc}") from _exc
        engine.chain_adapters["SENSEX"] = FyersChainAdapter(
            symbol_map={"SENSEX": (instruments.by_name["SENSEX"].fyers_symbol
                                  or "BSE:SENSEX-INDEX")},
            logger=logger,
        )
        log_event(logger, logging.INFO, "sensex_chain_provider_selected",
                  provider="fyers_options_chain_v3")
    if live:
        fyers_token = os.environ.get("FYERS_ACCESS_TOKEN", "").strip()
        fyers_app_id = os.environ.get("FYERS_APP_ID", "").strip()
        if not fyers_token or not fyers_app_id:
            raise FatalConfigError("FYERS_ACCESS_TOKEN/FYERS_APP_ID required for live mode")
        symbol_map: Dict[str, Tuple[str, str, Decimal]] = {}
        for u in cfg.engine.underlyings:
            _inst = instruments.by_name[u]
            _fsym = _inst.fyers_symbol
            if _fsym is None and u == "NIFTY":
                _fsym = "NSE:NIFTY50-INDEX"
            if _fsym is None:
                raise FatalConfigError(
                    f"instruments.{u}.fyers_symbol is required for live mode")
            symbol_map[_fsym] = (u, _inst.security_id, _inst.tick_size)
        fyers_ws = FyersWsFeed(
            fyers_token, fyers_app_id, logger, metrics, clock, engine.on_tick,
            symbol_map
        )
        engine.ws = fyers_ws
        engine.health.ws = fyers_ws
        engine.use_nse_chain = True
        engine.health.use_nse_chain = True
    return engine


def check_config(config_path: str, instruments_path: str) -> int:
    try:
        cfg = load_config(_load_yaml(config_path))
        instruments = Instruments.load(_load_yaml(instruments_path))
        for u in cfg.engine.underlyings:
            if u not in instruments.by_name:
                raise FatalConfigError(f"underlying {u} missing from instruments.yaml")
        print("config OK")
        return 0
    except FatalConfigError as exc:
        print(f"config ERROR: {exc}", file=sys.stderr)
        return 2


async def _run_live(config_path: str, instruments_path: str) -> int:
    cfg = load_config(_load_yaml(config_path))
    instruments = Instruments.load(_load_yaml(instruments_path))
    for u in cfg.engine.underlyings:
        if u not in instruments.by_name:
            raise FatalConfigError(f"underlying {u} missing from instruments.yaml")
    logger = setup_logging(cfg.logging.level, cfg.logging.json, cfg.logging.dir)
    metrics = Metrics()
    clock = Clock()
    engine = _build_engine(cfg, instruments, clock, logger, metrics, live=True, use_nse_chain=True)
    await engine.nse_chain.start()
    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def _handle_sigterm() -> None:
        stop_event.set()

    with contextlib.suppress(NotImplementedError):
        loop.add_signal_handler(_signal.SIGTERM, _handle_sigterm)
        loop.add_signal_handler(_signal.SIGINT, _handle_sigterm)
    run_task = asyncio.create_task(engine.run())
    stop_task = asyncio.create_task(stop_event.wait())
    # LIFECYCLE-FIX C: on Windows add_signal_handler is unavailable, so
    # Ctrl+C surfaces as KeyboardInterrupt (a BaseException) and used to
    # bypass engine.shutdown() entirely - losing the final snapshot and
    # leaving the feed un-stopped. The finally block guarantees the feed
    # is silenced and state is persisted on EVERY exit path.
    done: set = set()
    try:
        done, _pending = await asyncio.wait(
            {run_task, stop_task}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        stop_task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await stop_task
        # Silence the external producer BEFORE the loop can close.
        if engine.ws is not None:
            with contextlib.suppress(BaseException):
                await engine.ws.close()
        with contextlib.suppress(BaseException):
            await engine.shutdown()
    if run_task in done:
        run_task.result()
        return 0
    run_task.cancel()
    with contextlib.suppress(asyncio.CancelledError, Exception):
        await run_task
    return 0


def _run_replay(config_path: str, instruments_path: str, fixture_dir: str) -> int:
    cfg = load_config(_load_yaml(config_path))
    instruments = Instruments.load(_load_yaml(instruments_path))
    logger = setup_logging(cfg.logging.level, cfg.logging.json, cfg.logging.dir)
    metrics = Metrics()
    start_ts = datetime(2026, 1, 1, 9, 15, tzinfo=IST)
    clock = FixedClock(start_ts)
    engine = _build_engine(cfg, instruments, clock, logger, metrics, live=False)
    replay = ReplayEngine(engine, clock)
    tick_path = os.path.join(fixture_dir, "ticks.json")
    chain_path = os.path.join(fixture_dir, "chains.json")
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


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="engine", description="Indian Index Options Signal Engine")
    parser.add_argument("--config", default=os.path.join("config", "config.yaml"))
    parser.add_argument("--instruments", default=os.path.join("config", "instruments.yaml"))
    parser.add_argument("--check-config", action="store_true")
    parser.add_argument("--replay", metavar="FIXTURE_DIR", default=None)
    args = parser.parse_args(argv)
    try:
        if args.check_config:
            return check_config(args.config, args.instruments)
        if args.replay:
            return _run_replay(args.config, args.instruments, args.replay)
        return asyncio.run(_run_live(args.config, args.instruments))
    except FatalConfigError as exc:
        print(f"FATAL CONFIG: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"FATAL: {exc}", file=sys.stderr)
        return 1


def _acquire_single_instance_lock() -> Any:
    """LIFECYCLE-FIX D: refuse to start a second engine.

    Two concurrent Dhan.py processes meant two FYERS websockets, two
    log handlers competing for engine.log (the WinError 32 rotation
    failure), and racing snapshot writers. The lock file handle is kept
    open for the process lifetime and released automatically on exit.
    """
    lock_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "state", "engine.lock")
    os.makedirs(os.path.dirname(lock_path), exist_ok=True)
    def _refuse() -> None:
        print("ENGINE_ALREADY_RUNNING: another Dhan.py instance holds "
              "state/engine.lock; refusing to start a second feed.",
              file=sys.stderr)

    try:
        handle = open(lock_path, "a+", encoding="utf-8")
    except OSError:
        _refuse()
        raise SystemExit(3)
    try:
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        with contextlib.suppress(OSError):
            handle.close()
        _refuse()
        raise SystemExit(3)
    # On Windows the byte-range lock also blocks our own writes if a stale
    # holder exists; a failed PID stamp must never abort a valid start.
    with contextlib.suppress(OSError):
        handle.seek(0)
        handle.truncate()
        handle.write(str(os.getpid()))
        handle.flush()
    return handle


if __name__ == "__main__":
    _INSTANCE_LOCK = _acquire_single_instance_lock()
    raise SystemExit(main())
