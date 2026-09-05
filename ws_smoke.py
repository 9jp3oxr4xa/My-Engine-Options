import asyncio
import json
import os
import websockets

async def main():
    token = os.environ["DHAN_ACCESS_TOKEN"]
    client = os.environ["DHAN_CLIENT_ID"]

    url = (
        "wss://api-feed.dhan.co"
        f"?version=2&token={token}&clientId={client}&authType=2"
    )

    print("CONNECTING...")

    try:
        async with websockets.connect(
            url,
            max_size=None,
            open_timeout=10,
            ping_interval=20,
            ping_timeout=20,
        ) as ws:

            print("WEBSOCKET_CONNECTED")

            request = {
                "RequestCode": 17,
                "InstrumentCount": 1,
                "InstrumentList": [
                    {
                        "ExchangeSegment": "NSE_FNO",
                        "SecurityId": "1006"
                    }
                ]
            }

            payload = json.dumps(request)

            print("SENDING_SUBSCRIPTION...")
            print(payload)

            await ws.send(payload)

            print("SUBSCRIPTION_SENT")
            print("WAITING_FOR_SERVER...")

            for i in range(10):
                try:
                    msg = await asyncio.wait_for(
                        ws.recv(),
                        timeout=5
                    )

                    if isinstance(msg, bytes):
                        print(
                            f"BINARY_RECEIVED #{i+1} "
                            f"LEN={len(msg)} "
                            f"HEAD={msg[:32].hex()}"
                        )
                    else:
                        print(
                            f"TEXT_RECEIVED #{i+1}: "
                            f"{msg[:1000]!r}"
                        )

                except asyncio.TimeoutError:
                    print(f"TIMEOUT #{i+1}")
                except websockets.exceptions.ConnectionClosed as e:
                    print(
                        "CONNECTION_CLOSED",
                        "code=", e.code,
                        "reason=", repr(e.reason)
                    )
                    break

    except Exception as e:
        print("WEBSOCKET_ERROR")
        print(type(e).__name__ + ":", str(e))

asyncio.run(main())
