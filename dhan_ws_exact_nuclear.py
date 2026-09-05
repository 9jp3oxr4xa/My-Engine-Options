import asyncio
import os
import Dhan

async def main():
    token = os.environ.get("DHAN_ACCESS_TOKEN", "")
    client = os.environ.get("DHAN_CLIENT_ID", "")

    print("TOKEN_PRESENT=", bool(token))
    print("CLIENT_PRESENT=", bool(client))

    logger = Dhan.setup_logging("INFO", True, ".")
    metrics = Dhan.Metrics()
    clock = Dhan.Clock()

    ticks = []

    def on_tick(t):
        ticks.append(t)
        print(
            "TICK:",
            "security_id=", t.security_id,
            "ltp=", t.ltp,
            "ts=", t.ts,
            "volume_cum=", t.volume_cum,
            "ltq=", t.ltq
        )

    ws = Dhan.DhanWsFeed(
        token,
        client,
        logger,
        metrics,
        clock,
        10,
        on_tick
    )

    ws.set_subscriptions([("IDX_I", "13")])

    print("SUBSCRIPTIONS=", ws._subscriptions)
    print("SUBSCRIBE_MESSAGE=", ws._subscribe_message())

    task = asyncio.create_task(ws.run())

    await asyncio.sleep(15)

    print("\n=== WS RESULT ===")
    print("TICKS=", len(ticks))
    print("RECONNECTS=", ws.reconnect_count)
    print("LAST_PACKET_AGE=", ws.packet_age_s())

    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    await ws.close()

    print("WS_SMOKE=DONE")

asyncio.run(main())
