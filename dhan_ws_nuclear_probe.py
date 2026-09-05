import os, asyncio, websockets

token = os.environ.get("DHAN_ACCESS_TOKEN", "")
client = os.environ.get("DHAN_CLIENT_ID", "")

print("TOKEN_PRESENT:", bool(token))
print("TOKEN_LENGTH:", len(token))
print("CLIENT:", client)

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

            import json
            await ws.send(json.dumps(msg))
            print("SUBSCRIBE_SENT")

            try:
                packet = await asyncio.wait_for(ws.recv(), timeout=5)
                print("FIRST_PACKET_TYPE=", type(packet).__name__)
                print("FIRST_PACKET_BYTES=", len(packet) if hasattr(packet,"__len__") else "?")
            except Exception as e:
                print("RECV_ERROR=", type(e).__name__, str(e))

    except Exception as e:
        print("WS_HANDSHAKE=FAIL")
        print("ERROR_TYPE=", type(e).__name__)
        print("ERROR=", str(e))

asyncio.run(main())
