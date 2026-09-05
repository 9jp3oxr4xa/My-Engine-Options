import os
import time
import multiprocessing
from decimal import Decimal
from datetime import datetime, timezone

from fyers_apiv3.FyersWebsocket import data_ws
import Dhan

APP_ID = "X53PITZA3A-100"
TOKEN = os.environ["FYERS_ACCESS_TOKEN"]

def worker(q):
    clock = Dhan.Clock()
    builder = Dhan.BarBuilder(clock, Decimal("0.05"))
    agg = Dhan.BarAggregator5m()

    bars1 = []
    bars5 = []
    errors = []

    def on_connect():
        print("FYERS_CONNECT=PASS", flush=True)
        fyers.subscribe(
            symbols=["NSE:NIFTY50-INDEX"],
            data_type="SymbolUpdate"
        )
        print("FYERS_SUBSCRIBE=PASS", flush=True)

    def on_message(message):
        if not isinstance(message, dict):
            return
        if message.get("symbol") != "NSE:NIFTY50-INDEX":
            return

        ltp = message.get("ltp")
        exch_ts = message.get("exch_feed_time")

        if ltp is None or exch_ts is None:
            return

        ts = datetime.fromtimestamp(
            int(exch_ts), tz=timezone.utc
        ).astimezone(Dhan.IST)

        tick = Dhan.Tick(
            security_id="13",
            ts=ts,
            ltp=Dhan.quantize_tick(
                Decimal(str(ltp)), Decimal("0.05")
            ),
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

        bar1 = builder.on_tick(tick)

        if bar1 is not None:
            bars1.append(bar1)
            print(
                "BAR_1M=",
                bar1.ts_open,
                "O=", bar1.open,
                "H=", bar1.high,
                "L=", bar1.low,
                "C=", bar1.close,
                "TICKS=", bar1.tick_count,
                "SUSPECT=", bar1.volume_suspect,
                flush=True
            )

            bar5 = agg.on_bar_1m(bar1)

            if bar5 is not None:
                bars5.append(bar5)
                print(
                    "BAR_5M=",
                    bar5.ts_open,
                    "O=", bar5.open,
                    "H=", bar5.high,
                    "L=", bar5.low,
                    "C=", bar5.close,
                    "TICKS=", bar5.tick_count,
                    "SUSPECT=", bar5.volume_suspect,
                    flush=True
                )

    def on_error(message):
        errors.append(message)
        print("FYERS_ERROR=", message, flush=True)

    def on_close(message):
        print("FYERS_CLOSE=", message, flush=True)

    global fyers
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

    print("5M_TEST_START=PASS", flush=True)
    fyers.connect()

    time.sleep(390)

    q.put({
        "bars1": len(bars1),
        "bars5": len(bars5),
        "errors": len(errors),
    })

if __name__ == "__main__":
    multiprocessing.freeze_support()

    q = multiprocessing.Queue()
    p = multiprocessing.Process(target=worker, args=(q,))
    p.start()

    p.join(410)

    if p.is_alive():
        print("TIMEOUT: terminating FYERS worker", flush=True)
        p.terminate()
        p.join(10)

    if not q.empty():
        r = q.get()
        print("\n=== FYERS 1M -> 5M RESULT ===", flush=True)
        print("BARS_1M=", r["bars1"], flush=True)
        print("BARS_5M=", r["bars5"], flush=True)
        print("ERRORS=", r["errors"], flush=True)

        if r["bars5"] >= 1 and r["errors"] == 0:
            print("FYERS_1M_5M_TEST=PASS", flush=True)
        else:
            print("FYERS_1M_5M_TEST=FAIL", flush=True)
    else:
        print("NO_RESULT_FROM_FYERS_WORKER", flush=True)
