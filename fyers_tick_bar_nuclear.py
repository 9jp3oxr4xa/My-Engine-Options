import os
import time
from decimal import Decimal
from datetime import datetime, timezone
from fyers_apiv3.FyersWebsocket import data_ws
import Dhan

TOKEN = os.environ["FYERS_ACCESS_TOKEN"]
APP_ID = "X53PITZA3A-100"

clock = Dhan.Clock()
builder = Dhan.BarBuilder(clock, Decimal("0.05"))

messages = []
bars = []

def on_connect():
    print("FYERS_CONNECT=PASS")
    fyers.subscribe(
        symbols=["NSE:NIFTY50-INDEX"],
        data_type="SymbolUpdate"
    )
    print("FYERS_SUBSCRIBE=PASS")

def on_message(message):
    if not isinstance(message, dict):
        return

    if message.get("symbol") != "NSE:NIFTY50-INDEX":
        return

    ltp = message.get("ltp")
    exch_ts = message.get("exch_feed_time")

    if ltp is None or exch_ts is None:
        return

    ts = datetime.fromtimestamp(int(exch_ts), tz=timezone.utc).astimezone(
        Dhan.IST
    )

    # FYERS NIFTY index has no underlying volume field.
    # Keep cumulative volume at 0; strategy RVOL comes from option-chain volume.
    tick = Dhan.Tick(
        security_id="13",
        ts=ts,
        ltp=Dhan.quantize_tick(Decimal(str(ltp)), Decimal("0.05")),
        ltq=0,
        volume_cum=0,
        oi=0,
        bid=Decimal("0"),
        ask=Decimal("0"),
        bid_qty=0,
        ask_qty=0,
        total_buy_qty=0,
        total_sell_qty=0,
    )

    messages.append(tick)

    bar = builder.on_tick(tick)

    if bar is not None:
        bars.append(bar)
        print(
            "BAR_1M=",
            bar.ts_open,
            "O=", bar.open,
            "H=", bar.high,
            "L=", bar.low,
            "C=", bar.close,
            "V=", bar.volume,
            "TICKS=", bar.tick_count,
            "SUSPECT=", bar.volume_suspect,
        )

def on_error(message):
    print("FYERS_ERROR=", message)

def on_close(message):
    print("FYERS_CLOSE=", message)

fyers = data_ws.FyersDataSocket(
    access_token=f"{APP_ID}:{TOKEN}",
    log_path="",
    litemode=False,
    write_to_file=False,
    reconnect=True,
    on_connect=on_connect,
    on_message=on_message,
    on_error=on_error,
    on_close=on_close,
)

print("ADAPTER_TEST_START=PASS")
fyers.connect()

# Run long enough to cross multiple minute boundaries.
time.sleep(135)

print("\n=== FYERS -> TICK -> BAR RESULT ===")
print("TICKS_RECEIVED=", len(messages))
print("BARS_1M=", len(bars))

if messages:
    print("FIRST_TICK_TS=", messages[0].ts)
    print("LAST_TICK_TS=", messages[-1].ts)
    print("FIRST_LTP=", messages[0].ltp)
    print("LAST_LTP=", messages[-1].ltp)

if bars:
    print("FIRST_BAR=", bars[0])
    print("LAST_BAR=", bars[-1])

print("ADAPTER_TEST=DONE")
