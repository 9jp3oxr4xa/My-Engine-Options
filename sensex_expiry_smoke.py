import os
import aiohttp
import asyncio

async def main():
    headers = {
        "access-token": os.environ["DHAN_ACCESS_TOKEN"],
        "client-id": os.environ["DHAN_CLIENT_ID"],
        "Content-Type": "application/json",
    }

    body = {
        "UnderlyingScrip": 1,
        "UnderlyingSeg": "IDX_I",
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(
            "https://api.dhan.co/v2/optionchain/expirylist",
            headers=headers,
            json=body,
            timeout=10,
        ) as r:
            print("HTTP_STATUS=", r.status)
            print((await r.text())[:5000])

asyncio.run(main())
