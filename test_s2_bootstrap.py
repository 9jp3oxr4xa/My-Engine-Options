import sys, os, types, asyncio, inspect, logging
from datetime import datetime, date, timedelta
from decimal import Decimal

import Dhan
from Dhan import (Engine, Instruments, load_config, FixedClock, Metrics,
                  TelegramAlerter, DhanRestClient, Persistence, FyersWsFeed,
                  FatalConfigError, IST)

# --- T1: source inspection ---
src = inspect.getsource(Engine._fyers_history_bootstrap)
assert "underlyings[0]" not in src, "underlyings[0] still present"
assert "for u in self.cfg.engine.underlyings" in src, "loop missing"
assert "fyers_symbol" in src, "symbol resolution missing"
print("NO_UNDERLYINGS_ZERO=PASS")
print("MULTI_UNDERLYING_HISTORY_LOGIC=PASS")

# --- stubbed FYERS history endpoint ---
TODAY = date(2026, 8, 20)
PRIOR = TODAY - timedelta(days=1)
BASE = {"NSE:NIFTY50-INDEX": 24000.0, "BSE:SENSEX-INDEX": 77500.0}

def _candles(sym, day):
    out = []
    for i in range(15):
        t = datetime(day.year, day.month, day.day, 9, 15 + i, tzinfo=IST)
        px = BASE[sym] + i
        out.append([int(t.timestamp()), px, px + 2.0, px - 2.0, px + 1.0, 0])
    return out

class _Resp:
    def __init__(self, p): self._p = p
    def json(self): return self._p

def _get(url, params=None, headers=None, timeout=None):
    sym = params["symbol"]
    day = date.fromisoformat(params["range_from"])
    if sym in BASE and day in (TODAY, PRIOR):
        return _Resp({"s": "ok", "candles": _candles(sym, day)})
    return _Resp({"s": "no_data", "candles": []})

stub = types.ModuleType("requests")
stub.get = _get
sys.modules["requests"] = stub

os.environ["FYERS_ACCESS_TOKEN"] = "t"
os.environ["FYERS_APP_ID"] = "a"

CFG = {
 "engine": {"underlyings": ["NIFTY", "SENSEX"], "evaluation_interval_s": 5,
            "timezone": "Asia/Kolkata", "holidays": []},
 "feeds": {"ws_reconnect_max_s": 60, "chain_poll_interval_s": 60,
           "stale_tick_s": 30, "stale_chain_s": 120},
 "signals": {"confidence_threshold": 70, "min_categories_passed": 4,
             "cooldown_minutes_per_underlying": 15,
             "max_signals_per_day_per_underlying": 6, "min_reward_risk": 1.5},
 "risk": {"max_spread_pct_of_premium": 2.0, "min_option_volume_5m": 100,
          "min_top_depth_lots": 5, "news_blackout": []},
 "structure": {"swing_left_bars": 3, "swing_right_bars": 3,
               "sweep_max_close_back_bars": 2},
 "regime": {"adx_period": 14, "atr_period": 14, "compression_bb_pct_rank": 20},
 "options": {"atm_band_strikes": 3, "oi_delta_lookback_snapshots": 10,
             "pcr_bands": {"bearish_below": 0.7, "bullish_above": 1.3}},
 "telegram": {"chat_id_env": "TG_CHAT_ID", "send_rejections_digest": True},
 "logging": {"level": "INFO", "json": True, "dir": "logs_s2_test"},
}
INS = {"instruments": {
 "NIFTY":  {"security_id": "13",  "exchange_segment": "NSE_FNO", "lot_size": 65,
            "strike_step": 50,  "tick_size": 0.05},
 "SENSEX": {"security_id": "999", "exchange_segment": "BSE_FNO", "lot_size": 20,
            "strike_step": 100, "tick_size": 0.05,
            "fyers_symbol": "BSE:SENSEX-INDEX"},
}}

def make_engine(ins_raw):
    cfg = load_config(CFG)
    ins = Instruments.load(ins_raw)
    clock = FixedClock(datetime(2026, 8, 20, 12, 0, tzinfo=IST))
    logger = logging.getLogger("s2test")
    metrics = Metrics()
    rest = DhanRestClient("", "", logger, metrics, clock)
    alerter = TelegramAlerter("", "", logger, metrics, clock)
    pers = Persistence(os.path.join("state_s2_test", "snap.json"))
    eng = Engine(cfg, ins, clock, logger, metrics, rest, None, alerter, pers,
                 {"NIFTY": 13, "SENSEX": 51})
    eng.use_nse_chain = True
    smap = {"NSE:NIFTY50-INDEX": ("NIFTY", "13", Decimal("0.05")),
            "BSE:SENSEX-INDEX": ("SENSEX", "51", Decimal("0.05"))}
    eng.ws = FyersWsFeed("t", "a", logger, metrics, clock, lambda t: None, smap)
    return eng

# --- T2: multi-underlying bootstrap + state isolation ---
eng = make_engine(INS)
asyncio.run(eng._fyers_history_bootstrap())
s_n = eng.store.get("NIFTY")
s_s = eng.store.get("SENSEX")
assert len(s_n.bars_1m) == 15, ("NIFTY today bars", len(s_n.bars_1m))
assert len(s_s.bars_1m) == 15, ("SENSEX today bars", len(s_s.bars_1m))
assert all(Decimal(23000) < b.close < Decimal(25000) for b in s_n.bars_1m), "SENSEX leaked into NIFTY"
assert all(Decimal(76000) < b.close < Decimal(79000) for b in s_s.bars_1m), "NIFTY leaked into SENSEX"
pd_n = s_n.structure._prev_day_high
pd_s = s_s.structure._prev_day_high
assert pd_n is not None and pd_n < Decimal(30000), ("NIFTY prev-day", pd_n)
assert pd_s is not None and pd_s > Decimal(70000), ("SENSEX prev-day", pd_s)
assert len(s_n.bars_5m) == 3 and len(s_s.bars_5m) == 3, (len(s_n.bars_5m), len(s_s.bars_5m))
assert s_n.opening_range_set and s_s.opening_range_set
assert eng._warmup_bars_remaining["NIFTY"] == 0 and eng._warmup_bars_remaining["SENSEX"] == 0
print("NIFTY_HISTORY_PATH=PASS")   # NIFTY had no fyers_symbol -> default path exercised
print("STATE_ISOLATION=PASS")
print("S2_BOOTSTRAP=PASS")

# --- T3: missing symbol on non-NIFTY underlying must fail explicitly ---
INS2 = {"instruments": {
 "NIFTY":  dict(INS["instruments"]["NIFTY"]),
 "SENSEX": {"security_id": "999", "exchange_segment": "BSE_FNO", "lot_size": 20,
            "strike_step": 100, "tick_size": 0.05},
}}
eng2 = make_engine(INS2)
try:
    asyncio.run(eng2._fyers_history_bootstrap())
    print("SYMBOL_REQUIRED=FAIL")
    sys.exit(1)
except FatalConfigError:
    print("SYMBOL_REQUIRED=PASS")
