import os, asyncio, websockets, json

token = os.environ["DHAN_ACCESS_TOKEN"]
client = os.environ["DHAN_CLIENT_ID"]

url = (
    "wss://api-feed.dhan.co"
    f"?version=2&token={token}&clientId={client}&authType=2"
)

async def main():
    print("CONNECTING...")

    try:
        async with websockets.connect(
            url,
            max_size=None,
            open_timeout=10,
            ping_interval=None,
        ) as ws:

            print("WS_HANDSHAKE=PASS")
            print("STATE=CONNECTED")

            msg = {
                "RequestCode": 15,
                "InstrumentCount": 1,
                "InstrumentList": [
                    {
                        "ExchangeSegment": "IDX_I",
                        "SecurityId": "13"
                    }
                ]
            }

            raw = json.dumps(msg)
            print("SUBSCRIBE=", raw)

            await ws.send(raw)
            print("SUBSCRIBE_SENT")

            try:
                while True:
                    packet = await asyncio.wait_for(ws.recv(), timeout=10)
                    print(
                        "PACKET:",
                        type(packet).__name__,
                        "LEN=",
                        len(packet) if hasattr(packet, "__len__") else "?"
                    )

                    if isinstance(packet, bytes):
                        print("HEX_HEAD=", packet[:64].hex())

                    else:
                        print("TEXT_HEAD=", repr(packet[:500]))

            except asyncio.TimeoutError:
                print("RECV_TIMEOUT")

            except websockets.exceptions.ConnectionClosed as e:
                print("CONNECTION_CLOSED")
                print("CLOSE_CODE=", e.code)
                print("CLOSE_REASON=", repr(e.reason))
                print("EXC_TYPE=", type(e).__name__)
                raise

    except Exception as e:
        print("FINAL_EXCEPTION_TYPE=", type(e).__name__)
        print("FINAL_EXCEPTION=", str(e))

asyncio.run(main())
