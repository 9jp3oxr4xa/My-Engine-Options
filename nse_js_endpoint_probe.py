import asyncio
import aiohttp
import re

JS_URL = "https://www.nseindia.com/dist/js/sections/option-chain-v3.js?v=14082026"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/151.0.0.0 Safari/537.36",
    "Accept": "*/*",
    "Referer": "https://www.nseindia.com/option-chain",
}

async def main():
    async with aiohttp.ClientSession(headers=HEADERS) as session:
        async with session.get(JS_URL, timeout=20) as r:
            text = await r.text()

            print("STATUS=", r.status)
            print("LENGTH=", len(text))

            print("\n--- API/ENDPOINT REFERENCES ---")
            for m in sorted(set(re.findall(r'.{0,180}(?:option-chain-v3|option-chain-contract-info|api/).{0,250}', text, re.I))):
                print(m[:700])
                print()

            print("\n--- EXPIRY REFERENCES ---")
            for m in sorted(set(re.findall(r'.{0,150}(?:expiry|expiryDate|expiryDates).{0,250}', text, re.I))):
                print(m[:700])
                print()

asyncio.run(main())
