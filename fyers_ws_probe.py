import asyncio
import websockets

async def main():
    print("CONNECTING...")
    try:
        async with websockets.connect(
            "wss://api.fyers.in",
            open_timeout=10
        ) as ws:
            print("WS_CONNECTED")
    except Exception as exc:
        print("WS_ERROR=", type(exc).__name__, str(exc))

asyncio.run(main())
