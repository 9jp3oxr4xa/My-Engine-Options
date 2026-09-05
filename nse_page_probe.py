import asyncio
import aiohttp
import re

URL = "https://www.nseindia.com/option-chain"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/151.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

async def main():
    async with aiohttp.ClientSession(headers=HEADERS) as session:
        async with session.get(URL, timeout=20) as r:
            text = await r.text()

            print("STATUS=", r.status)
            print("LENGTH=", len(text))

            tests = [
                "option-chain-v3",
                "option-chain-indices",
                "expiryDates",
                "underlyingValue",
                "NIFTY",
                "api/",
                "__NEXT_DATA__",
            ]

            print("\nSTRING SEARCH:")
            for x in tests:
                print(f"{x} =", x in text)

            print("\nPOSSIBLE API REFERENCES:")
            matches = sorted(set(re.findall(
                r'https?://[^"\']+|/api/[^"\']+',
                text,
                re.I
            )))

            for m in matches[:100]:
                print(m[:300])

asyncio.run(main())
