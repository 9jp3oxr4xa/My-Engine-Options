import asyncio, logging, sys
from datetime import datetime, date
from decimal import Decimal

import Dhan
from Dhan import (_build_engine, load_config, Instruments, FixedClock, Metrics,
                  FatalConfigError, ChainSnapshot, ChainStrike, OptionLeg, IST)
from nse_chain_adapter import NSEChainAdapter

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
 "logging": {"level": "INFO", "json": True, "dir": "logs_s3_test"},
}
INS = {"instruments": {
 "NIFTY":  {"security_id": "13",  "exchange_segment": "NSE_FNO", "lot_size": 65,
            "strike_step": 50,  "tick_size": 0.05},
 "SENSEX": {"security_id": "999", "exchange_segment": "BSE_FNO", "lot_size": 20,
            "strike_step": 100, "tick_size": 0.05,
            "fyers_symbol": "BSE:SENSEX-INDEX"},
}}

cfg = load_config(CFG)
ins = Instruments.load(INS)
clock = FixedClock(datetime(2026, 8, 20, 12, 0, tzinfo=IST))
logger = logging.getLogger("s3test")
metrics = Metrics()
eng = _build_engine(cfg, ins, clock, logger, metrics, live=False, use_nse_chain=True)

# --- T1: provider map exists and NIFTY routes to the current NSE adapter ---
assert isinstance(eng.chain_adapters, dict), "chain_adapters missing"
print("S3_PROVIDER_MAP=PASS")

assert "NIFTY" in eng.chain_adapters, "NIFTY not routed"
assert eng._chain_adapter_for("NIFTY") is eng.chain_adapters["NIFTY"]
print("NIFTY_PROVIDER=PASS")

assert isinstance(eng.chain_adapters["NIFTY"], NSEChainAdapter), "wrong adapter type"
assert eng.chain_adapters["NIFTY"] is eng.nse_chain, "NIFTY adapter is not the existing NSE instance"
print("NIFTY_PROVIDER_IS_CURRENT_NSE=PASS")

# --- T2: SENSEX explicitly unconfigured ---
assert "SENSEX" not in eng.chain_adapters, "SENSEX must have no adapter before S4"
try:
    eng._chain_adapter_for("SENSEX")
    print("SENSEX_PROVIDER_UNCONFIGURED=FAIL")
    sys.exit(1)
except FatalConfigError:
    print("SENSEX_PROVIDER_UNCONFIGURED=PASS")

# --- T3: no fallback. Spy replaces NIFTY adapter; SENSEX requests must
# --- refuse BEFORE any adapter call, on both consumption paths. ---
class Spy:
    def __init__(self):
        self.chain_calls = 0
        self.expiry_calls = 0
    async def option_chain(self, *a, **k):
        self.chain_calls += 1
        raise AssertionError("NIFTY adapter invoked for foreign underlying")
    async def expiry_list(self, *a, **k):
        self.expiry_calls += 1
        return [date(2026, 8, 26)]

spy = Spy()
eng.chain_adapters["NIFTY"] = spy
eng.expiries["SENSEX"] = date(2026, 8, 26)  # routing must refuse even with an expiry present

try:
    asyncio.run(eng._poll_chain("SENSEX"))
    print("SENSEX_DOES_NOT_FALLBACK_TO_NIFTY=FAIL")
    sys.exit(1)
except FatalConfigError:
    pass
assert spy.chain_calls == 0, "poll fallback occurred"

try:
    asyncio.run(eng._refresh_expiries(False))
    print("SENSEX_DOES_NOT_FALLBACK_TO_NIFTY=FAIL")
    sys.exit(1)
except FatalConfigError:
    pass
assert spy.expiry_calls == 1, "expiry routing skipped NIFTY or leaked SENSEX"
assert eng.expiries["NIFTY"] == date(2026, 8, 26), "NIFTY expiry path broken"
print("SENSEX_DOES_NOT_FALLBACK_TO_NIFTY=PASS")

# --- T4: chain state isolation ---
leg = OptionLeg(ltp=Decimal("100"), bid=Decimal("99.5"), ask=Decimal("100.5"),
                oi=1000, oi_prev=900, volume=500, iv=Decimal("12"),
                bid_qty=100, ask_qty=100, security_id="x")
snap = ChainSnapshot(underlying="NIFTY", expiry=date(2026, 8, 26),
                     spot=Decimal("24000"), ts=clock.now(),
                     strikes=[ChainStrike(Decimal("24000"), leg, leg)],
                     atm_strike=Decimal("24000"))
eng.store.apply_chain(snap)
assert eng.store.get("NIFTY").last_chain is not None
assert eng.store.get("SENSEX").last_chain is None, "NIFTY chain leaked into SENSEX"
print("STATE_ISOLATION=PASS")
