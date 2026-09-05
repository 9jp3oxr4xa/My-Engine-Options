import asyncio
import os
import Dhan

async def main():
    token = os.environ.get("DHAN_ACCESS_TOKEN", "")
    client = os.environ.get("DHAN_CLIENT_ID", "")

    logger = Dhan.setup_logging("INFO", True, ".")
    metrics = Dhan.Metrics()
    clock = Dhan.Clock()

    rest = Dhan.DhanRestClient(
        token, client, logger, metrics, clock
    )

    print("TOKEN=", bool(token))
    print("CLIENT=", bool(client))

    bars = await rest.intraday_minute(
        "13",
        "IDX_I",
        "INDEX",
        clock.now().replace(hour=9, minute=15, second=0, microsecond=0),
        clock.now()
    )

    print("BARS_COUNT=", len(bars))

    if bars:
        print("FIRST_BAR=", bars[0])
        print("LAST_BAR=", bars[-1])
        print("LAST_CLOSE=", bars[-1].close)
        print("LAST_VOLUME=", bars[-1].volume)

    await rest.close()

    print("Dhan_1M_REST_SMOKE=DONE")

asyncio.run(main())
