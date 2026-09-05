import os
import asyncio
import aiohttp

async def main():
    headers = {
        "access-token": os.environ["DHAN_ACCESS_TOKEN"],
        "client-id": os.environ["DHAN_CLIENT_ID"],
    }

    async with aiohttp.ClientSession() as session:
        async with session.get(
            "https://api.dhan.co/v2/profile",
            headers=headers,
            timeout=10,
        ) as r:
            print("HTTP_STATUS=", r.status)
            print((await r.text())[:2000])

asyncio.run(main())
