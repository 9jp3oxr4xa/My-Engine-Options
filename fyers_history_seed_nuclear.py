import asyncio
import os
import requests
from decimal import Decimal
from datetime import datetime, timezone, time as dtime

import Dhan

APP_ID = os.environ["FYERS_APP_ID"]
TOKEN = os.environ["FYERS_ACCESS_TOKEN"].strip()

def fetch_history():
    today = Dhan.Clock().now().date().isoformat()

    url = "https://api-t1.fyers.in/data/history"
    params = {
        "symbol": "NSE:NIFTY50-INDEX",
        "resolution": "1",
        "date_format": "1",
        "range_from": today,
        "range_to": today,
    }

    r = requests.get(
        url,
        params=params,
        headers={"Authorization": f"{APP_ID}:{TOKEN}"},
        timeout=20,
    )

    data = r.json()

    print("FYERS_HISTORY_HTTP=", r.status_code, flush=True)
    print("FYERS_HISTORY_STATUS=", data.get("s"), flush=True)

    if data.get("s") != "ok":
        raise RuntimeError(data)

    return data["candles"]

async def main():
    cfg = Dhan.load_config(Dhan._load_yaml(r"config\config.yaml"))
    ins = Dhan.Instruments.load(Dhan._load_yaml(r"config\instruments.yaml"))
    log = Dhan.setup_logging(cfg.logging.level, cfg.logging.json, cfg.logging.dir)
    metrics = Dhan.Metrics()
    clock = Dhan.Clock()

    e = Dhan._build_engine(
        cfg, ins, clock, log, metrics,
        live=True,
        use_nse_chain=True,
    )

    e.use_nse_chain = True
    e.health.use_nse_chain = True

    await e.nse_chain.start()

    candles = fetch_history()

    print("HISTORY_1M_COUNT=", len(candles), flush=True)

    u = cfg.engine.underlyings[0]

    # Seed today's completed 1m bars directly through the EXISTING
    # production bar-state path. Only today's completed bars are used.
    completed = []

    for row in candles:
        epoch, o, h, l, c, v = row[:6]

        ts = datetime.fromtimestamp(
            int(epoch), tz=timezone.utc
        ).astimezone(Dhan.IST)

        if ts.time() < dtime(9, 15):
            continue

        bar = Dhan.Bar(
            ts_open=ts.replace(second=0, microsecond=0),
            open=Dhan.quantize_tick(Decimal(str(o)), Decimal("0.05")),
            high=Dhan.quantize_tick(Decimal(str(h)), Decimal("0.05")),
            low=Dhan.quantize_tick(Decimal(str(l)), Decimal("0.05")),
            close=Dhan.quantize_tick(Decimal(str(c)), Decimal("0.05")),
            volume=int(v or 0),
            tick_count=0,
            volume_suspect=True,
        )

        e._on_bar_1m(u, bar, source="LIVE_TICK")
        completed.append(bar)

    st = e.store.get(u)

    print("\n=== FYERS HISTORY SEED RESULT ===", flush=True)
    print("SEEDED_1M=", len(completed), flush=True)
    print("STATE_1M=", len(st.bars_1m), flush=True)
    print("STATE_5M=", len(st.bars_5m), flush=True)
    print("REGIME=", st.regime.state, flush=True)
    print("ATR_5M=", st.atr_5m.value, flush=True)
    print("ADX=", st.adx.value, flush=True)
    print("EMA20=", st.ema20.value, flush=True)

    print("\n=== EXPECTED ===", flush=True)
    print("FRESH_ANALYTICS_READY=",
          len(st.bars_5m) >= 14 and st.adx.value is not None,
          flush=True)

    await e.shutdown()

asyncio.run(main())
