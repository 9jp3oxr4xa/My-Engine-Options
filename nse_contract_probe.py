import asyncio
import aiohttp
import json

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/151.0.0.0 Safari/537.36",
    "Accept": "application/json,text/plain,*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/option-chain",
}

async def main():
    async with aiohttp.ClientSession(headers=HEADERS) as session:

        print("STEP 1: Opening NSE...")
        async with session.get(
            "https://www.nseindia.com/option-chain",
            timeout=20
        ) as r:
            print("NSE_STATUS=", r.status)

        print("\nSTEP 2: Contract info...")
        url = "https://www.nseindia.com/api/option-chain-contract-info?symbol=NIFTY"

        async with session.get(url, timeout=20) as r:
            text = await r.text()

            print("CONTRACT_STATUS=", r.status)
            print("CONTENT_TYPE=", r.headers.get("Content-Type"))
            print("LENGTH=", len(text))
            print("PREVIEW=", text[:3000])

            if r.status == 200:
                try:
                    data = json.loads(text)
                    print("\nTOP_LEVEL_KEYS=", list(data.keys()))

                    print("\nFULL STRUCTURE:")
                    print(json.dumps(data, indent=2)[:10000])
                except Exception as e:
                    print("JSON_ERROR=", repr(e))

asyncio.run(main())
